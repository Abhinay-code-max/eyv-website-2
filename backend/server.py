import os
import logging
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from motor.motor_asyncio import AsyncIOMotorClient
from starlette.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pythonjsonlogger.json import JsonFormatter

from services import (
    amadeus_service,
    storage_service,
    rewards_service,
    locations_service,
    serpapi_hotels_service,
    date_utils,
    price_cache_service,
    log_redaction,
    quota_service,
    usage_service,
    generation_log_service,
    chat_service,
    booking_expiry_service,
    generation_expiry_service,
    index_service,
    sentry_service,
    support_agent_service,
    notification_service,
    analytics_service,
)
from services import ignav_service as duffel_service
from services.request_id_middleware import RequestIDMiddleware, RequestIDLogFilter, request_id_var

ROAD_DETOUR_MULTIPLIER = 1.3
CHILD_FARE_DISCOUNT = 0.25
SENIOR_FARE_DISCOUNT = 0.10


# Domain Routers & Shared Modules
from routes.shared import (
    db,
    client,
    limiter,
    _session_token_key,
    QuotaExceededError,
    User,
    UserSession,
    SessionExchangeRequest,
    TripPreferences,
    TripPlan,
    SavedTrip,
    ChatMessage,
    _get_current_session,
    get_current_user,
    is_user_premium,
    _hash_session_token,
    _sign_wallet_download,
    _get_gemini_client,
    _get_internal_ticket_http_client,
    _internal_ticket_api_token,
    _resolve_admin_api_key,
    ADMIN_API_KEY,
    _resolve_wallet_download_secret,
    WALLET_URL_SIGNING_SECRET,
    _resolve_revenuecat_webhook_key,
    REVENUECAT_WEBHOOK_AUTH_KEY,
    _resolve_app_version,
    APP_VERSION,
    _SERVER_STARTED_AT,
    _SERVER_PID,
    TRIP_PLAN_TYPES,
)

from routes.auth import router as auth_router
from routes.trips import (
    router as trips_router,
    _NOT_FETCHED,
    _placeholder_plan,
    _spawn_background_task,
    _generate_and_save_tier,
    _room_count,
    _haversine_km,
    _geocode_place,
    _fare_units,
    _select_tier_hotel,
    _scale_per_person_costs,
    _transport_mode_flags,
    _search_flights_cached,
    _search_hotels_cached,
    _fetch_anchor_pricing,
    generate_single_plan,
    generate_trip_plans,
    regenerate_trip_plan,
    get_user_trips,
    get_trip_quota_status,
    get_trip,
    get_trip_road_route,
    delete_trip,
    _day_sort_key,
)
from routes.chat import (
    router as chat_router,
    build_trip_context,
    _sse_data,
    SupportMessageRequest,
)
from routes.notifications import router as notifications_router
from routes.general import (
    router as general_router,
    root,
)
from routes.search import (
    router as search_router,
    FlightSearchRequest,
    HotelSearchRequest,
    TrainSearchRequest,
)
from routes.bookings import (
    router as bookings_router,
    BookingRequest,
    _FORBIDDEN_ITEM_DATA_KEYS,
    create_booking,
    book_trip_plan,
    _bookable_line_items,
)
from routes.wallet import (
    router as wallet_router,
    WalletItem,
    _sniff_wallet_content_type,
)
from routes.rewards import router as rewards_router
from routes.payments import (
    router as payments_router,
    _PREMIUM_PLANS_USD,
    _get_premium_plans,
    CreateCheckoutRequest,
    CheckoutStatusRequest,
    _ensure_stripe_configured,
    create_checkout,
    _finalize_or_alert_points_redemption,
    get_payment_status,
    _process_successful_payment,
    _process_expired_payment,
    _sync_subscription_from_stripe,
    _resolve_invoice_subscription,
    _subscription_status_payload,
    get_subscription_status,
    cancel_subscription,
    resume_subscription,
    create_subscription_portal_session,
)
from routes.webhooks import (
    router as webhooks_router,
    stripe_webhook,
    revenuecat_webhook,
    telegram_webhook,
    _telegram_preauth_marker,
)

from internal_tickets_api import router as internal_tickets_router
from internal_analytics_api import router as internal_analytics_router
from internal_jarvis_api import router as internal_jarvis_router, public_router as internal_jarvis_public_router
from admin_api import router as admin_router, get_admin_usage_summary


def _resolve_cors_origins() -> List[str]:
    origins = [o.strip() for o in os.environ.get('CORS_ORIGINS', '').split(',') if o.strip()]
    if not origins or '*' in origins:
        raise RuntimeError(
            "CORS_ORIGINS must be a comma-separated list of explicit origins "
            "(e.g. http://localhost:3000) - it is unset or contains '*', which "
            "is incompatible with allow_credentials=True. Set it in backend/.env "
            "for local dev and in Railway's service variables for deploys."
        )
    return origins


CORS_ORIGINS = _resolve_cors_origins()

app = FastAPI()

# Mount DB handles on app.state
app.state.tickets_db = db
app.state.analytics_db = db
app.state.jarvis_db = db
app.state.limiter = limiter


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    response = JSONResponse(
        status_code=429,
        content={
            "detail": "Too many requests - please slow down and try again shortly.",
            "reason": "rate_limited",
            "request_id": request_id_var.get(),
        },
    )
    try:
        item = exc.limit.limit
        response.headers["Retry-After"] = str(item.GRANULARITY[0] * item.multiples)
    except Exception:
        pass
    return response


app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)


async def quota_exceeded_handler(request: Request, exc: QuotaExceededError):
    return JSONResponse(
        status_code=429,
        content={
            "detail": (
                f"You've used your {exc.limit} free trip generations today - "
                "upgrade to Premium for unlimited planning."
            ),
            "reason": "quota_exceeded",
            "used": exc.used,
            "limit": exc.limit,
            "request_id": request_id_var.get(),
        },
    )


app.add_exception_handler(QuotaExceededError, quota_exceeded_handler)

_log_handler = logging.StreamHandler()
_log_handler.setFormatter(JsonFormatter(
    '%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s'
))
_log_handler.addFilter(RequestIDLogFilter())
logging.basicConfig(level=logging.INFO, handlers=[_log_handler])
logger = logging.getLogger(__name__)
log_redaction.install_secret_redaction()

sentry_service.init_sentry(APP_VERSION)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=exc)
    sentry_sdk.capture_exception(exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": request_id_var.get()},
    )


_booking_expiry_scheduler = AsyncIOScheduler()


@app.on_event("startup")
async def startup_event():
    global client, db
    client = AsyncIOMotorClient(os.environ['MONGO_URL'])
    db = client[os.environ['DB_NAME']]
    app.state.tickets_db = db
    app.state.analytics_db = db
    app.state.jarvis_db = db
    try:
        storage_service.init_storage()
    except Exception as e:
        logger.warning(f"Storage init failed at startup: {e}")
    try:
        await price_cache_service.ensure_indexes(db)
    except Exception as e:
        logger.warning(f"price_cache index setup failed at startup: {e}")
    try:
        await quota_service.ensure_indexes(db)
    except Exception as e:
        logger.warning(f"quota index setup failed at startup: {e}")
    try:
        await chat_service.ensure_indexes(db)
    except Exception as e:
        logger.warning(f"chat index setup failed at startup: {e}")
    try:
        await index_service.ensure_indexes(db)
    except Exception as e:
        logger.warning(f"index_service index setup failed at startup: {e}")
    try:
        await analytics_service.ensure_indexes(db)
    except Exception as e:
        logger.warning(f"analytics_service index setup failed at startup: {e}")
    try:
        await duffel_service._refresh_rates_if_stale()
    except Exception as e:
        logger.warning(f"FX rate warm-up failed at startup: {e}")
    try:
        _booking_expiry_scheduler.add_job(
            booking_expiry_service.expire_stale_pending_bookings,
            "interval",
            minutes=10,
            args=[db],
            id="expire_stale_pending_bookings",
        )
        _booking_expiry_scheduler.add_job(
            rewards_service.refund_stale_reserved_points,
            "interval",
            minutes=10,
            args=[db],
            id="refund_stale_reserved_points",
        )
        _booking_expiry_scheduler.add_job(
            generation_expiry_service.expire_stuck_generations,
            "interval",
            minutes=10,
            args=[db],
            id="expire_stuck_generations",
        )
        _booking_expiry_scheduler.start()
        logger.info("Booking-expiry scheduler started (10-minute interval)")
    except Exception as e:
        logger.warning(f"Booking-expiry scheduler failed to start: {e}")


app.include_router(auth_router)
app.include_router(rewards_router)
app.include_router(wallet_router)
app.include_router(notifications_router)
app.include_router(chat_router)
app.include_router(search_router)
app.include_router(trips_router)
app.include_router(bookings_router)
app.include_router(payments_router)
app.include_router(webhooks_router)
app.include_router(general_router)
app.include_router(internal_tickets_router)
app.include_router(internal_analytics_router)
app.include_router(internal_jarvis_public_router)
app.include_router(internal_jarvis_router)
app.include_router(admin_router)


app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RequestIDMiddleware)


@app.get("/health")
async def health_check():
    uptime_seconds = (datetime.now(timezone.utc) - _SERVER_STARTED_AT).total_seconds()
    try:
        await asyncio.wait_for(db.command('ping'), timeout=3.0)
        mongo_ok = True
    except Exception as e:
        logger.error(f"Health check: MongoDB ping failed: {e}")
        mongo_ok = False

    return JSONResponse(
        status_code=200 if mongo_ok else 503,
        content={
            "status": "ok" if mongo_ok else "degraded",
            "version": APP_VERSION,
            "uptime_seconds": round(uptime_seconds, 1),
            "mongo": "ok" if mongo_ok else "unreachable",
        },
    )


@app.on_event("shutdown")
async def shutdown_db_client():
    if getattr(_booking_expiry_scheduler, "running", False):
        try:
            _booking_expiry_scheduler.shutdown(wait=False)
        except Exception:
            pass
    client.close()


