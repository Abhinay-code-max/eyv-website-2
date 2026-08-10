from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, UploadFile, File, Header, Query
from fastapi.responses import StreamingResponse, RedirectResponse, JSONResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import math
import subprocess
import functools
import hashlib
import hmac
import io
import time
from pathlib import Path

# Must run before importing any service module below - several of them read
# their API keys from os.environ at import time, so .env has to be loaded first.
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator, ValidationError
from typing import List, Optional, Dict, Any, Literal
import uuid
import secrets
from urllib.parse import urlencode
from datetime import datetime, timezone, timedelta
import httpx
import asyncio
from google import genai
from google.genai import types as genai_types
import stripe
import sentry_sdk
from PIL import Image
from pythonjsonlogger.json import JsonFormatter
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from services import amadeus_service, storage_service, rewards_service, locations_service
from services import ignav_service as duffel_service  # Ignav replaces Sky Scrapper
from services import serpapi_hotels_service
from services import date_utils
from services import price_cache_service
from services import log_redaction
from services import quota_service, usage_service, generation_log_service
from services import chat_service
from services import booking_expiry_service
from services import generation_expiry_service
from services import index_service
from services import sentry_service
from services import analytics_service
from services.request_id_middleware import RequestIDMiddleware, RequestIDLogFilter, request_id_var
# Hard-fails at import time if INTERNAL_TICKET_API_TOKEN is unset (see that
# module's own docstring) - imported here, unconditionally, so that failure
# surfaces at server startup, not the first time an agent happens to call
# /api/internal/tickets/*.
from internal_tickets_api import router as internal_tickets_router
# Same hard-fail-at-import-time reasoning, for INTERNAL_ANALYTICS_API_TOKEN
# (Step A7) - see internal_analytics_api.py's own module docstring. Entirely
# standalone from the ticket router above - no shared code or dependency
# between the two beyond this same security template.
from internal_analytics_api import router as internal_analytics_router
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
GEMINI_MODEL = "gemini-2.5-flash"  # gemini-2.0-flash/-lite return 429 (zero free-tier quota) and gemini-1.5-flash is 404 on this API key/version


@functools.lru_cache(maxsize=1)
def _get_gemini_client() -> genai.Client:
    """Lazy singleton - genai.Client(api_key=...) raises ValueError
    immediately if the key is None/blank, so constructing this eagerly at
    import time meant a missing GEMINI_API_KEY crashed the entire server
    at boot (auth, bookings, every unrelated endpoint), not just trip
    generation and chat. Now that failure only happens the first time
    something that actually needs Gemini runs, scoped to just that
    request instead of the whole process."""
    return genai.Client(api_key=GEMINI_API_KEY)
stripe.api_key = os.environ.get('STRIPE_API_KEY')

GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')
GOOGLE_REDIRECT_URI = os.environ.get('GOOGLE_REDIRECT_URI')
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:3000')
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
OAUTH_TICKET_TTL_SECONDS = 300
ADMIN_API_KEY = os.environ.get('ADMIN_API_KEY')


def _resolve_cors_origins() -> List[str]:
    """Explicit allowlist only - no wildcard fallback. Combined with the
    allow_credentials=True on the CORSMiddleware below, a "*" origin makes
    Starlette reflect back whatever Origin sent the request whenever a
    cookie is present (see CORSMiddleware.send()), letting any website ride
    a logged-in user's session_token cookie into this API. Fail loudly at
    import time instead of ever silently allowing that - a crashed deploy
    is recoverable, a silently wide-open CORS policy isn't."""
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


def _resolve_wallet_download_secret() -> str:
    """Signs short-lived wallet file download URLs (item id + expiry) so the
    download route can validate a request without needing the session
    cookie/token on it - deliberately a separate secret from session tokens
    (session tokens are opaque random values with no secret key at all) so a
    leaked download link can never be used to forge a session or vice versa.
    Required, not optional - unlike ADMIN_API_KEY-gated features, wallet
    downloads have no "disabled" fallback mode, and a per-process random
    fallback would make signed URLs fail validation on every other worker/
    restart. Set once in backend/.env locally and in Railway's service
    variables for deploys, and never rotate it without expecting all
    in-flight download links to invalidate."""
    secret = os.environ.get('WALLET_URL_SIGNING_SECRET')
    if not secret:
        raise RuntimeError(
            "WALLET_URL_SIGNING_SECRET must be set - it signs short-lived "
            "wallet file download URLs. Set it in backend/.env for local dev "
            "and in Railway's service variables for deploys."
        )
    return secret


WALLET_URL_SIGNING_SECRET = _resolve_wallet_download_secret()
WALLET_DOWNLOAD_URL_TTL_SECONDS = 180


def _hash_session_token(token: str) -> str:
    """Session tokens are already high-entropy random values (uuid4().hex),
    so a plain SHA-256 hash is sufficient here - no need for slow/salted
    hashing (bcrypt etc.) meant for low-entropy human passwords."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _sign_wallet_download(item_id: str, expires: int) -> str:
    message = f"{item_id}:{expires}".encode("utf-8")
    return hmac.new(WALLET_URL_SIGNING_SECRET.encode("utf-8"), message, hashlib.sha256).hexdigest()


app = FastAPI()
api_router = APIRouter(prefix="/api")

# internal_tickets_api.py's routes read `request.app.state.tickets_db`
# rather than closing over a module-level `db` - that module is imported
# above `db`/`app` even exist (see the import block near the top of this
# file), so it can't reference either at import time; storing db on
# app.state here (as soon as both exist) and reading it per-request is what
# avoids a circular import while still giving those routes the same live
# Motor client every other route in this file already uses.
app.state.tickets_db = db
# Same reasoning as tickets_db above, for internal_analytics_api.py (Step A7).
app.state.analytics_db = db

# Captured once at import time (i.e. whenever this worker process actually
# started running THIS copy of the code) - GET /api/ surfaces both so a
# "did my restart actually pick up fresh code" check never has to rely on
# OS-level process inspection (netstat/tasklist's reported owning PID for a
# listening socket can go stale if a worker outlives its parent, e.g. a
# multiprocessing-spawned uvicorn worker left running after its reloader
# process exited - the PID here is the actual process answering requests,
# not whatever a socket table happens to attribute the port to).
_SERVER_STARTED_AT = datetime.now(timezone.utc)
_SERVER_PID = os.getpid()


def _resolve_app_version() -> str:
    """Short commit hash the running process was built from, for GET /health
    and Sentry's `release`. APP_VERSION (set by the platform at build/deploy
    time - e.g. a Docker build ARG baking in `git rev-parse --short HEAD`, or
    Railway/Vercel's own git-sha env var) always wins so a deployed instance
    reports exactly what's live rather than whatever happened to be checked
    out wherever the image was built. Falls back to reading git directly,
    which only works when running from a working tree with .git present -
    i.e. local dev, not inside a built container image."""
    env_version = os.environ.get('APP_VERSION')
    if env_version:
        return env_version
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            cwd=ROOT_DIR, capture_output=True, text=True, timeout=2, check=True,
        )
        return result.stdout.strip()
    except Exception:
        return 'unknown'


APP_VERSION = _resolve_app_version()

# ── Rate limiting ────────────────────────────────────────────────────────
# In-memory storage: no Redis in this deployment (single process, no
# multi-worker/multi-instance setup) - if that changes, point these at
# Redis instead so limits are shared across processes.
#
# One Limiter instance, stacked twice on /trips/generate with different
# key_funcs (IP and session token) - both accumulate onto the SAME route's
# limit list and are evaluated together per request. Two *separate* Limiter
# instances would NOT both fire: slowapi's per-route wrapper sets
# request.state._rate_limiting_complete after the first one runs, and every
# later decorator on the same route (even from a different Limiter) skips
# its own check because of that flag. Keying by session token/bearer value
# (not a resolved user_id) avoids an async DB lookup inside a sync key_func;
# falls back to IP for unauthenticated requests (get_current_user rejects
# those with 401 inside the handler anyway).
#
# These are a coarse "stop scripted loops" backstop, not the main control -
# the real per-user control is the daily quota further down (quota_service),
# which Premium accounts are exempt from.
def _session_token_key(request: Request) -> str:
    token = request.cookies.get("session_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[len("Bearer "):]
    return token or get_remote_address(request)


limiter = Limiter(key_func=get_remote_address)


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    response = JSONResponse(
        status_code=429,
        content={
            "detail": "Too many requests - please slow down and try again shortly.",
            "reason": "rate_limited",
            "request_id": request_id_var.get(),
        },
    )
    # exc.limit.limit is the underlying limits.RateLimitItem (e.g. "5 per
    # minute") - GRANULARITY[0] * multiples gives the window length in
    # seconds. An approximation (window length, not exact time left in the
    # current window), but simple and always correct.
    try:
        item = exc.limit.limit
        response.headers["Retry-After"] = str(item.GRANULARITY[0] * item.multiples)
    except Exception:
        pass
    return response


app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)


# ── Daily free-tier generation quota ─────────────────────────────────────
# The durable per-user control (unlike the rate limits above, which only
# guard against short bursts). See services/quota_service.py.
class QuotaExceededError(Exception):
    def __init__(self, used: int, limit: int):
        self.used = used
        self.limit = limit


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
# SerpApi's api_key travels as a URL query param (no header alternative -
# confirmed against their docs/client source) and httpx logs full request
# URLs at INFO - scrub it before it reaches any handler, at any log level.
log_redaction.install_secret_redaction()

sentry_service.init_sentry(APP_VERSION)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all for anything that isn't a deliberately-raised HTTPException
    (those keep using FastAPI's own default handler/response shape, untouched
    here - this only fires for genuine bugs/unexpected failures). Registering
    this handler means such exceptions no longer propagate out of the ASGI
    app, so Sentry's Starlette/FastAPI integration - which only auto-captures
    exceptions that actually propagate - would otherwise miss them entirely;
    capture explicitly here instead."""
    logger.error(f"Unhandled exception: {exc}", exc_info=exc)
    sentry_sdk.capture_exception(exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": request_id_var.get()},
    )

# Models
class User(BaseModel):
    model_config = ConfigDict(extra="ignore")
    user_id: str
    email: str
    name: str
    picture: Optional[str] = None
    created_at: datetime

class UserSession(BaseModel):
    model_config = ConfigDict(extra="ignore")
    session_id: str
    user_id: str
    expires_at: datetime
    created_at: datetime
    user_agent: Optional[str] = None

class SessionExchangeRequest(BaseModel):
    session_id: str

class TripPreferences(BaseModel):
    destination: str
    starting_location: str
    departure_date: str
    return_date: str
    adults: int = Field(default=1, ge=0)
    children: int = Field(default=0, ge=0)
    seniors: int = Field(default=0, ge=0)
    # Derived server-side from adults+children+seniors below - never trusted
    # from the client, the same way price_cache_service never trusts a
    # client-supplied price. Any value sent by the client is discarded.
    num_travelers: int = Field(default=0, ge=0)
    transportation: str
    # "round_trip" (default) or "one_way" - frontend TripPlannerPage's "One-way
    # trip" checkbox (Trip Basics step). Previously absent from this model, so
    # Pydantic's extra="ignore" default silently dropped it from every request -
    # same class of bug the cruise_cabin_type comment above describes.
    trip_direction: str = "round_trip"
    budget_level: str
    accommodation: List[str]
    interests: List[str]
    dietary_preferences: Optional[str] = None
    accessibility_requirements: Optional[str] = None
    travel_pace: Optional[str] = None
    trip_type: str
    currency: str = "INR"
    budget_mode: bool = True
    # Road Trip question branch (frontend TripPlannerPage "Road Trip
    # Preferences" step) - only meaningful when transportation == "Road Trip".
    # Previously absent from this model, so FastAPI/Pydantic silently dropped
    # every one of these from every request before generate_single_plan's
    # road_flavor_block (or any real day-count math) ever saw the user's
    # actual answers - road_max_driving_hours_per_day always fell back to
    # its hardcoded default of 8 regardless of what was picked in the wizard.
    road_drivers: Optional[int] = None
    road_max_hours_before_break: Optional[int] = None
    road_break_duration_minutes: Optional[int] = None
    road_max_driving_hours_per_day: Optional[int] = None
    road_route_style: Optional[str] = None
    road_route_avoidances: List[str] = Field(default_factory=list)
    road_fuel_type: Optional[str] = None
    road_vehicle_mileage_or_model: Optional[str] = None
    road_ev_battery_percent: Optional[int] = None
    road_ev_recharge_preference: Optional[str] = None
    road_overnight_accommodation: List[str] = Field(default_factory=list)
    road_food_preference: Optional[str] = None
    road_route_attractions: List[str] = Field(default_factory=list)
    road_avoid: List[str] = Field(default_factory=list)
    # Cruise question branch (frontend TripPlannerPage "Cruise Preferences"
    # step) - only meaningful when transportation == "Cruise". Previously
    # absent from this model, so FastAPI/Pydantic silently dropped them from
    # every request before generation ever saw them.
    cruise_cabin_type: Optional[str] = None
    cruise_duration_preference: Optional[str] = None
    cruise_dining_style: Optional[str] = None
    cruise_itinerary_style: Optional[str] = None

    @model_validator(mode="after")
    def _derive_and_validate_num_travelers(self):
        self.num_travelers = self.adults + self.children + self.seniors
        if self.num_travelers < 1:
            raise ValueError("At least 1 traveler (adults + children + seniors) is required")
        return self

class TripPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")
    trip_id: str
    user_id: str
    preferences: Dict[str, Any]
    plan_type: str
    itinerary: Dict[str, Any]
    total_cost: float
    cost_breakdown: Dict[str, float]
    created_at: datetime
    status: str = "draft"

class SavedTrip(BaseModel):
    model_config = ConfigDict(extra="ignore")
    trip_id: str
    user_id: str
    trip_name: str
    preferences: Dict[str, Any]
    plans: List[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime

class ChatMessage(BaseModel):
    message: str
    trip_id: Optional[str] = None
    selected_tier: Optional[str] = None

# Auth Helper
async def _get_current_session(request: Request) -> Dict[str, Any]:
    """Resolves the raw session document for the request's session token.
    Split out from get_current_user() so session-management endpoints (list/
    revoke) can get at session_id/expires_at/etc. without a second lookup."""
    session_token = request.cookies.get("session_token")
    if not session_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            session_token = auth_header.replace("Bearer ", "")

    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    token_hash = _hash_session_token(session_token)
    session_doc = await db.user_sessions.find_one(
        {"session_token": token_hash},
        {"_id": 0}
    )

    if not session_doc:
        raise HTTPException(status_code=401, detail="Invalid session")

    expires_at = session_doc["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at < datetime.now(timezone.utc):
        await db.user_sessions.delete_one({"session_token": token_hash})
        raise HTTPException(status_code=401, detail="Session expired")

    return session_doc


async def get_current_user(request: Request) -> User:
    session_doc = await _get_current_session(request)

    user_doc = await db.users.find_one(
        {"user_id": session_doc["user_id"]},
        {"_id": 0}
    )

    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")

    if isinstance(user_doc['created_at'], str):
        user_doc['created_at'] = datetime.fromisoformat(user_doc['created_at'])

    return User(**user_doc)


async def is_user_premium(user_id: str) -> bool:
    """Stripe is the source of truth; stripe_subscription_status/
    current_period_end are a webhook-synced local cache read here so an
    access check never has to make a live Stripe API call. Never writes -
    these fields are only ever set from _sync_subscription_from_stripe
    (customer.subscription.created/updated/deleted) or the invoice webhooks,
    never guessed at from app-side date math.

    "past_due" (Stripe's own Smart Retries mid-grace-period status) counts
    as active - by the time a renewal invoice first fails, current_period_end
    has typically already lapsed (that's *why* Stripe is retrying), so this
    deliberately does NOT also require current_period_end >= now while
    past_due, or the grace period would be a no-op. Access only actually
    ends once a later customer.subscription.updated/deleted moves status to
    something else (canceled/unpaid), driven entirely by Stripe's own retry
    schedule and Dashboard-configured exhaustion action - no independent
    grace-period timer of ours."""
    user_doc = await db.users.find_one(
        {'user_id': user_id},
        {'_id': 0, 'stripe_subscription_status': 1, 'current_period_end': 1}
    )
    if not user_doc:
        return False
    status = user_doc.get('stripe_subscription_status')
    if status == 'past_due':
        return True
    if status != 'active':
        return False
    current_period_end = user_doc.get('current_period_end')
    if not current_period_end:
        return True
    if isinstance(current_period_end, str):
        current_period_end = datetime.fromisoformat(current_period_end)
    if current_period_end.tzinfo is None:
        current_period_end = current_period_end.replace(tzinfo=timezone.utc)
    return current_period_end >= datetime.now(timezone.utc)

# Auth Routes
@api_router.get("/auth/google/login")
async def google_login():
    if not GOOGLE_CLIENT_ID or not GOOGLE_REDIRECT_URI:
        raise HTTPException(status_code=500, detail="Google OAuth not configured")

    state = secrets.token_urlsafe(24)
    await db.oauth_states.insert_one({
        "state": state,
        # Native datetime (not .isoformat()) - the TTL index in
        # index_service.py needs a real BSON Date to expire these.
        "created_at": datetime.now(timezone.utc)
    })

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "prompt": "select_account",
        "state": state,
    }
    return RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")


@api_router.get("/auth/google/callback")
async def google_callback(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    if error or not code or not state:
        return RedirectResponse(f"{FRONTEND_URL}/login")

    state_doc = await db.oauth_states.find_one({"state": state})
    if not state_doc:
        return RedirectResponse(f"{FRONTEND_URL}/login")
    await db.oauth_states.delete_one({"state": state})

    try:
        async with httpx.AsyncClient() as client:
            token_resp = await client.post(GOOGLE_TOKEN_URL, data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            })
            token_resp.raise_for_status()
            tokens = token_resp.json()

            userinfo_resp = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {tokens['access_token']}"}
            )
            userinfo_resp.raise_for_status()
            profile = userinfo_resp.json()
    except Exception as e:
        logger.error(f"Google OAuth callback error: {e}")
        return RedirectResponse(f"{FRONTEND_URL}/login")

    ticket = uuid.uuid4().hex
    await db.oauth_tickets.insert_one({
        "ticket": ticket,
        "email": profile["email"],
        "name": profile.get("name", profile["email"]),
        "picture": profile.get("picture"),
        # Native datetime (not .isoformat()) - the TTL index in
        # index_service.py needs a real BSON Date to expire these.
        "created_at": datetime.now(timezone.utc)
    })

    return RedirectResponse(f"{FRONTEND_URL}/dashboard#session_id={ticket}")


@api_router.post("/auth/session")
async def exchange_session(request: SessionExchangeRequest, response: Response, http_request: Request):
    try:
        ticket_doc = await db.oauth_tickets.find_one(
            {"ticket": request.session_id}, {"_id": 0}
        )
        if not ticket_doc:
            raise HTTPException(status_code=401, detail="Invalid session ID")
        await db.oauth_tickets.delete_one({"ticket": request.session_id})

        ticket_created_at = ticket_doc["created_at"]
        if isinstance(ticket_created_at, str):
            ticket_created_at = datetime.fromisoformat(ticket_created_at)
        if ticket_created_at.tzinfo is None:
            ticket_created_at = ticket_created_at.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - ticket_created_at).total_seconds() > OAUTH_TICKET_TTL_SECONDS:
            raise HTTPException(status_code=401, detail="Session ID expired")

        session_data = ticket_doc

        existing_user = await db.users.find_one(
            {"email": session_data["email"]},
            {"_id": 0}
        )

        if existing_user:
            user_id = existing_user["user_id"]
            await db.users.update_one(
                {"user_id": user_id},
                {"$set": {
                    "name": session_data["name"],
                    "picture": session_data.get("picture")
                }}
            )
        else:
            user_id = f"user_{uuid.uuid4().hex[:12]}"
            user_doc = {
                "user_id": user_id,
                "email": session_data["email"],
                "name": session_data["name"],
                "picture": session_data.get("picture"),
                "created_at": datetime.now(timezone.utc),
            }
            await db.users.insert_one(user_doc)

        session_token = uuid.uuid4().hex
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)

        # Each login inserts its own session rather than deleting the user's
        # existing ones - logging in on a phone shouldn't kill a laptop
        # session. Sessions are only ever removed individually now: by
        # /auth/logout (this token only), /auth/sessions/{id} (explicit
        # revoke), or the TTL index once expires_at passes.
        session_doc = {
            "session_id": uuid.uuid4().hex,
            # Plaintext tokens in this collection would let anyone with DB
            # read access impersonate any live session - store only a
            # SHA-256 hash and compare hashes on every lookup instead.
            "session_token": _hash_session_token(session_token),
            "user_id": user_id,
            # Native datetime (not .isoformat()) - the TTL index in
            # index_service.py needs a real BSON Date to expire these.
            "expires_at": expires_at,
            "created_at": datetime.now(timezone.utc),
            "user_agent": http_request.headers.get("user-agent"),
        }
        await db.user_sessions.insert_one(session_doc)

        response.set_cookie(
            key="session_token",
            value=session_token,
            httponly=True,
            secure=True,
            samesite="none",
            path="/",
            max_age=7*24*60*60
        )


        user_doc = await db.users.find_one({"user_id": user_id}, {"_id": 0})
        if isinstance(user_doc['created_at'], str):
            user_doc['created_at'] = datetime.fromisoformat(user_doc['created_at'])

        return {"user": User(**user_doc).model_dump(mode='json'), "message": "Authentication successful"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Session exchange error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/auth/me")
async def get_me(request: Request):
    user = await get_current_user(request)
    return user.model_dump(mode='json')

@api_router.post("/auth/logout")
async def logout(request: Request, response: Response):
    session_token = request.cookies.get("session_token")
    if not session_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            session_token = auth_header.replace("Bearer ", "")
    if session_token:
        # Only this one session/device - not db.user_sessions.delete_many,
        # which would also sign the user out everywhere else.
        await db.user_sessions.delete_one({"session_token": _hash_session_token(session_token)})

    response.delete_cookie(key="session_token", path="/")
    return {"message": "Logged out successfully"}


@api_router.get("/auth/sessions")
async def list_sessions(request: Request):
    """All of the current user's active sessions (e.g. phone + laptop both
    logged in at once) - never includes the token hash itself."""
    current_session = await _get_current_session(request)
    docs = await db.user_sessions.find(
        {"user_id": current_session["user_id"]},
        {"_id": 0, "session_token": 0}
    ).sort("created_at", -1).to_list(100)
    for doc in docs:
        doc["is_current"] = doc.get("session_id") == current_session.get("session_id")
    return {"sessions": docs}


@api_router.delete("/auth/sessions/{session_id}")
async def revoke_session(session_id: str, request: Request):
    """Revoke one specific session (e.g. a lost/stolen device) without
    touching any of the user's other active sessions."""
    current_session = await _get_current_session(request)
    result = await db.user_sessions.delete_one(
        {"session_id": session_id, "user_id": current_session["user_id"]}
    )
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"message": "Session revoked"}

TRIP_PLAN_TYPES = ("Budget", "Premium", "Luxury")

# Sentinel distinguishing "caller didn't pass shared raw search results,
# fetch them yourself" from "caller passed None because this trip has no
# flight leg (train/cruise/road)" - both are falsy, but only the first
# should trigger a fetch. Defined here (not next to the functions that
# default to it, further down) because default argument values are
# evaluated at `def` time - _generate_and_save_tier below needs this name
# to already exist.
_NOT_FETCHED = object()


def _placeholder_plan(plan_type: str, currency: str, currency_symbol: str) -> Dict[str, Any]:
    """Shape a tier's entry takes in the trips.plans array from the moment
    the trip is created until that tier's own generation finishes - lets the
    frontend render each tier's card independently (status: "generating" ->
    "ready"/"failed") instead of blocking on the slowest of the three."""
    return {
        "plan_type": plan_type,
        "status": "generating",
        "currency": currency,
        "currency_symbol": currency_symbol,
        "itinerary": {},
        "cost_breakdown": {"transportation": 0, "accommodation": 0, "food": 0, "activities": 0, "miscellaneous": 0},
        "total_cost": 0,
        "highlights": [],
        "budget_tips": [],
    }


# Strong references to in-flight background generation tasks - asyncio only
# holds a *weak* reference to a task once nothing else does, so a bare
# `asyncio.create_task(...)` with the result discarded risks the task being
# garbage-collected mid-generation. Each task removes itself on completion.
_background_generation_tasks: set = set()


def _spawn_background_task(coro) -> None:
    task = asyncio.create_task(coro)
    _background_generation_tasks.add(task)

    def _on_done(t: asyncio.Task) -> None:
        _background_generation_tasks.discard(t)
        if not t.cancelled() and t.exception() is not None:
            # generate_single_plan already catches and reports its own
            # failures via the "failed" plan status - this is a backstop
            # for anything unexpected escaping the update itself (e.g. a
            # DB write error), so it isn't silently dropped.
            logger.error(f"Background trip-generation task failed unexpectedly: {t.exception()}")

    task.add_done_callback(_on_done)


async def _generate_and_save_tier(
    trip_id: str, user_id: str, plan_type: str, preferences_dict: Dict, plan_index: int,
    raw_flights: Any = _NOT_FETCHED, raw_hotels: Any = _NOT_FETCHED,
) -> None:
    """Generate one tier and write only its slot in the trip's plans array -
    the same single-index update the regenerate endpoint uses, so a tier
    finishing here is indistinguishable from one finishing via regenerate."""
    # Only forwarded when the caller actually did a shared fetch - callers
    # that don't pass these (e.g. a direct/test call with just the first 5
    # positional args) get exactly the pre-existing generate_single_plan(...)
    # call shape, unchanged.
    shared_kwargs: Dict[str, Any] = {}
    if raw_flights is not _NOT_FETCHED:
        shared_kwargs["raw_flights"] = raw_flights
    if raw_hotels is not _NOT_FETCHED:
        shared_kwargs["raw_hotels"] = raw_hotels
    plan = await generate_single_plan(preferences_dict, plan_type, trip_id, user_id, **shared_kwargs)
    await db.trips.update_one(
        {"trip_id": trip_id, "user_id": user_id},
        {"$set": {f"plans.{plan_index}": plan, "updated_at": datetime.now(timezone.utc)}},
    )
    # Only a real, usable plan counts as "generated" for the funnel - a
    # "failed" tier (generate_single_plan's own graceful-degradation path)
    # never reached anything a user could act on, so it's not a funnel entry.
    if plan.get("status") == "ready":
        await analytics_service.record_event(
            db, "plan_generated", user_id,
            {"trip_id": trip_id, "plan_type": plan_type, "plan_index": plan_index},
        )


# Trip Planning Routes
@api_router.post("/trips/generate")
@limiter.limit("5/minute")  # per-IP - stops a scripted loop from one source
@limiter.limit("5/minute", key_func=_session_token_key)  # per-authenticated-user
async def generate_trip_plans(preferences: TripPreferences, request: Request):
    user = await get_current_user(request)

    # Daily free-tier quota - the durable control, not just a burst guard.
    # Premium accounts are exempt entirely.
    if not await is_user_premium(user.user_id):
        quota = await quota_service.try_consume_trip_generation(db, user.user_id)
        if not quota["allowed"]:
            raise QuotaExceededError(used=quota["used"], limit=quota["limit"])

    trip_id = f"trip_{uuid.uuid4().hex[:12]}"

    # Store preferences
    preferences_dict = preferences.model_dump()
    currency = preferences_dict.get('currency', 'INR')
    currency_symbol = '₹' if currency == 'INR' else '$'

    # Save the trip immediately with all three tiers in "generating" status,
    # then kick off each tier's generation as an independent background task
    # instead of blocking this request on asyncio.gather for all three.
    # Budget/Premium typically finish well before Luxury (larger, denser
    # itinerary -> more prone to needing a retry) - this lets the frontend
    # show each tier the moment *it* is done rather than gating all three on
    # the slowest, and lets the client navigate to the results page and
    # start rendering almost immediately instead of waiting minutes.
    placeholder_plans = [_placeholder_plan(plan_type, currency, currency_symbol) for plan_type in TRIP_PLAN_TYPES]
    saved_trip = {
        "trip_id": trip_id,
        "user_id": user.user_id,
        "trip_name": f"{preferences.destination} Trip",
        "preferences": preferences_dict,
        "plans": placeholder_plans,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    await db.trips.insert_one(saved_trip)

    # Fetch flight/hotel search results ONCE here, shared by all three tiers
    # below - each tier's anchor price is a SELECTION from this single
    # response (cheapest/median/most-expensive hotel; cheapest/direct/
    # fastest flight - see _select_tier_hotel / select_anchor_flight), not a
    # fresh search of its own. Previously each of the three background tasks
    # below called _fetch_anchor_pricing independently, tripling real Duffel/
    # SerpApi calls for parameters that never varied between tiers.
    is_train, is_cruise, is_road = _transport_mode_flags(preferences_dict)
    raw_hotels = await _search_hotels_cached(
        preferences_dict.get("destination", ""),
        preferences_dict.get("departure_date", ""),
        preferences_dict.get("return_date", ""),
        ROOM_OCCUPANCY, "INR", user.user_id,
    )
    raw_flights = None
    if not (is_train or is_cruise or is_road):
        raw_flights = await _search_flights_cached(
            preferences_dict.get("starting_location", ""),
            preferences_dict.get("destination", ""),
            preferences_dict.get("departure_date", ""),
            1, user.user_id,
        )

    for plan_index, plan_type in enumerate(TRIP_PLAN_TYPES):
        _spawn_background_task(_generate_and_save_tier(
            trip_id, user.user_id, plan_type, preferences_dict, plan_index,
            raw_flights=raw_flights, raw_hotels=raw_hotels,
        ))

    return {"trip_id": trip_id, "plans": placeholder_plans}


@api_router.post("/trips/{trip_id}/regenerate/{plan_type}")
@limiter.limit("5/minute")  # per-IP - same guard as /trips/generate, still a real Gemini call
@limiter.limit("5/minute", key_func=_session_token_key)  # per-authenticated-user
async def regenerate_trip_plan(trip_id: str, plan_type: str, request: Request):
    """Re-run generation for a single tier of an existing trip (e.g. after
    that tier's original generation failed) without touching the other two
    tiers or re-fetching flight/hotel anchor data that already succeeded."""
    user = await get_current_user(request)

    if plan_type not in TRIP_PLAN_TYPES:
        raise HTTPException(status_code=400, detail=f"plan_type must be one of {list(TRIP_PLAN_TYPES)}")

    # Scoping the lookup to user_id doubles as the ownership check - a
    # trip_id that doesn't exist and one that belongs to someone else both
    # come back as the same 404, so this never leaks whether a given
    # trip_id exists for another account.
    trip = await db.trips.find_one(
        {"trip_id": trip_id, "user_id": user.user_id},
        {"_id": 0}
    )
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    plans = trip.get("plans", [])
    plan_index = next((i for i, p in enumerate(plans) if p.get("plan_type") == plan_type), None)
    if plan_index is None:
        raise HTTPException(status_code=404, detail=f"No {plan_type} plan found on this trip")

    # Daily free-tier quota - regenerating one tier is still a real Gemini
    # call, gated the same way as the original /trips/generate. Premium
    # accounts are exempt entirely, same as generate_trip_plans above.
    if not await is_user_premium(user.user_id):
        quota = await quota_service.try_consume_trip_generation(db, user.user_id)
        if not quota["allowed"]:
            raise QuotaExceededError(used=quota["used"], limit=quota["limit"])

    # Reuse the previously-fetched flight/train + hotel anchor for this tier
    # if we have one - avoids an unnecessary Duffel/SerpApi call for pricing
    # that hasn't changed. Older trips saved before anchor_pricing existed
    # fall back to a fresh fetch inside generate_single_plan.
    cached_anchor = plans[plan_index].get("anchor_pricing")

    regenerated = await generate_single_plan(
        trip["preferences"], plan_type, trip_id, user.user_id, anchor=cached_anchor
    )

    await db.trips.update_one(
        {"trip_id": trip_id, "user_id": user.user_id},
        {"$set": {f"plans.{plan_index}": regenerated, "updated_at": datetime.now(timezone.utc)}},
    )
    # Same plan_generated event as _generate_and_save_tier's initial
    # generation - a regenerated tier is still "a plan generated" for the
    # funnel, and re-firing it for the same trip_id doesn't double-count
    # anything downstream (the funnel counts DISTINCT trip_ids per stage).
    if regenerated.get("status") == "ready":
        await analytics_service.record_event(
            db, "plan_generated", user.user_id,
            {"trip_id": trip_id, "plan_type": plan_type, "plan_index": plan_index, "regenerated": True},
        )

    return {"trip_id": trip_id, "plan_type": plan_type, "plan": regenerated}


ROOM_OCCUPANCY = 2  # standard double-occupancy hotel room


def _room_count(num_travelers: int, occupancy: int = ROOM_OCCUPANCY) -> int:
    """Rooms a group needs at standard double occupancy. This is deliberately
    NOT the same as traveler count - 4 travelers need 2 rooms, not 4x the
    price of a single room."""
    return max(1, math.ceil(num_travelers / occupancy))


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two coordinates, in km."""
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


async def _geocode_place(place: str) -> Optional[Dict[str, float]]:
    """Geocode a place name using the same fallback chain as the
    /destinations/{destination}/coords endpoint: curated list + Nominatim
    first (locations_service), then amadeus_service's mock coords as a last
    resort so callers always get *something* to plot rather than nothing."""
    coords = await locations_service.geocode_destination(place)
    if not coords:
        coords = amadeus_service.get_destination_coords(place)
    return coords


# Neither Ignav (flights) nor SerpApi (hotels) exposes separate child/senior
# fares - both only accept a flat adults/travelers count. These are
# project-defined fallback discounts, not provider-verified rates.
CHILD_FARE_DISCOUNT = 0.25   # children pay 75% of the adult fare
SENIOR_FARE_DISCOUNT = 0.10  # seniors pay 90% of the adult fare


def _fare_units(adults: int, children: int, seniors: int) -> float:
    """Age-weighted traveler count used to scale flight/train/meal prices.
    Deliberately NOT used for hotel room count - rooms are priced per-room,
    not per-person, so age has no bearing on how many rooms are needed."""
    return adults * 1.0 + children * (1 - CHILD_FARE_DISCOUNT) + seniors * (1 - SENIOR_FARE_DISCOUNT)


def _select_tier_hotel(hotels_sorted: List[Dict], plan_type: str) -> tuple:
    """Pick the anchor hotel for a Budget/Premium/Luxury plan by SELECTING a
    real hotel from the provider's own price-sorted results - Budget gets the
    cheapest, Premium the median, Luxury the most expensive. Every field on
    the returned hotel (name, price, stars, ...) is untouched provider data.

    Returns (hotel, limited_inventory) where limited_inventory is True when
    the destination doesn't have enough genuinely distinct prices to make
    Budget/Premium/Luxury meaningfully different - callers should say so
    rather than pretend the tiers are more separated than they really are.
    """
    if not hotels_sorted:
        return None, True

    if plan_type == "Budget":
        hotel = hotels_sorted[0]
    elif plan_type == "Premium":
        hotel = hotels_sorted[len(hotels_sorted) // 2]
    else:
        hotel = hotels_sorted[-1]

    # "Limited inventory" means the destination doesn't have enough genuine
    # price spread to make three tiers meaningfully different - either there
    # aren't 3 distinct prices at all, or the cheapest and priciest real
    # hotels are within 15% of each other.
    distinct_prices = {h["price"]["per_night"] for h in hotels_sorted}
    cheapest = hotels_sorted[0]["price"]["per_night"]
    priciest = hotels_sorted[-1]["price"]["per_night"]
    price_spread = (priciest / cheapest - 1) if cheapest else 0
    limited_inventory = len(distinct_prices) < 3 or price_spread < 0.15

    return hotel, limited_inventory


def _scale_per_person_costs(itinerary: Dict[str, Any], num_travelers: int) -> None:
    """Meals and per-person activities are generated by the AI as a single
    person's cost - scale them up to the full traveler count. Activities the
    AI tags pricing_type="flat_group" (a hired guide, a private car, a
    chartered boat) are one fixed cost regardless of group size and are left
    untouched. Callers are expected to have already validated `itinerary`
    against GeneratedPlanResponse, so every day/meal/activity here is
    guaranteed present and correctly typed."""
    for day_data in itinerary.values():
        for meal in day_data['meals']:
            meal['cost'] = meal['cost'] * num_travelers
        for activity in day_data['activities']:
            cost = activity['cost']
            if cost <= 0 or activity.get('pricing_type') == 'flat_group':
                continue
            activity['cost'] = cost * num_travelers


# Enforces the plan JSON's shape at generation time (Gemini structured
# output - response_mime_type="application/json" + response_json_schema).
# Structured output has occasionally been observed to still deviate from
# this schema (e.g. under retries/edge-case prompts), so the parsed response
# is also validated against GeneratedPlanResponse (below) before
# generate_single_plan trusts it - a response that doesn't match either
# schema is a real failure (raises, feeding the existing retry loop), not
# something silently coerced into shape.
#
# "itinerary" keeps its existing day_1/day_2/... dict shape (verified live
# against the Gemini API that additionalProperties correctly constrains
# each day's value rather than the model falling back to an array) so no
# downstream code, prompt example, or stored-data shape has to change.
_DAY_SCHEMA = {
    "type": "object",
    "properties": {
        "date": {"type": "string"},
        "transportation": {
            "type": "object",
            "properties": {
                "mode": {"type": "string"},
                "details": {"type": "string"},
                "cost": {"type": "number"},
            },
            "required": ["mode", "cost"],
        },
        "activities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "time": {"type": "string"},
                    "activity": {"type": "string"},
                    "location": {"type": "string"},
                    "cost": {"type": "number"},
                    "category": {"type": "string"},
                    "pricing_type": {"type": "string", "enum": ["per_person", "flat_group"]},
                },
                "required": ["activity", "cost"],
            },
        },
        "accommodation": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "type": {"type": "string"},
                "cost": {"type": "number"},
                "location": {"type": "string"},
            },
            "required": ["name", "cost"],
        },
        "meals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "time": {"type": "string"},
                    "restaurant": {"type": "string"},
                    "cuisine": {"type": "string"},
                    "cost": {"type": "number"},
                },
                "required": ["cost"],
            },
        },
        "daily_total": {"type": "number"},
        "cumulative_total": {"type": "number"},
        "fixed_costs": {"type": "number"},
        "variable_costs": {"type": "number"},
    },
    "required": ["date", "transportation", "accommodation", "meals", "activities"],
}

PLAN_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "plan_type": {"type": "string"},
        "currency": {"type": "string"},
        "currency_symbol": {"type": "string"},
        "itinerary": {
            "type": "object",
            "additionalProperties": _DAY_SCHEMA,
            "minProperties": 1,
        },
        "cost_breakdown": {
            "type": "object",
            "properties": {
                "transportation": {"type": "number"},
                "accommodation": {"type": "number"},
                "food": {"type": "number"},
                "activities": {"type": "number"},
                "miscellaneous": {"type": "number"},
            },
            "required": ["transportation", "accommodation", "food", "activities", "miscellaneous"],
        },
        "total_cost": {"type": "number"},
        "highlights": {"type": "array", "items": {"type": "string"}},
        "budget_tips": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["plan_type", "currency", "currency_symbol", "itinerary", "cost_breakdown", "total_cost", "highlights", "budget_tips"],
}


# Pydantic mirror of _DAY_SCHEMA/PLAN_RESPONSE_SCHEMA above, used to validate
# the *parsed* response after generation completes. This is a second
# definition of the same shape kept in sync by hand rather than derived from
# one another: the raw dicts above have to stay exactly as they are because
# they're proven to work as a Gemini response_json_schema (Gemini's
# structured-output schema support does not accept Pydantic's $defs/$ref
# nesting), while this model is what actually gates whether a response is
# accepted. A response that parses as JSON but fails validation here is a
# real generation failure - it's raised and caught by generate_single_plan's
# retry loop, the same as any other exception from the Gemini call itself,
# instead of being silently patched into a plausible-looking shape.
class _GeneratedTransportation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    mode: str
    details: str = ""
    cost: float


class _GeneratedActivity(BaseModel):
    model_config = ConfigDict(extra="ignore")
    activity: str
    cost: float
    time: str = ""
    location: str = ""
    category: str = ""
    pricing_type: Optional[Literal["per_person", "flat_group"]] = None


class _GeneratedAccommodation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    cost: float
    type: str = ""
    location: str = ""


class _GeneratedMeal(BaseModel):
    model_config = ConfigDict(extra="ignore")
    cost: float
    time: str = ""
    restaurant: str = ""
    cuisine: str = ""


class _GeneratedDay(BaseModel):
    model_config = ConfigDict(extra="ignore")
    date: str
    transportation: _GeneratedTransportation
    accommodation: _GeneratedAccommodation
    meals: List[_GeneratedMeal]
    activities: List[_GeneratedActivity]
    daily_total: Optional[float] = None
    cumulative_total: Optional[float] = None
    fixed_costs: Optional[float] = None
    variable_costs: Optional[float] = None


class _GeneratedCostBreakdown(BaseModel):
    model_config = ConfigDict(extra="ignore")
    transportation: float
    accommodation: float
    food: float
    activities: float
    miscellaneous: float


class GeneratedPlanResponse(BaseModel):
    """Validated shape of generate_single_plan's parsed Gemini response -
    see the comment above _GeneratedTransportation for why this exists
    alongside PLAN_RESPONSE_SCHEMA rather than being derived from it."""
    model_config = ConfigDict(extra="ignore")
    plan_type: str
    currency: str
    currency_symbol: str
    itinerary: Dict[str, _GeneratedDay]
    cost_breakdown: _GeneratedCostBreakdown
    total_cost: float
    highlights: List[str]
    budget_tips: List[str]

    @model_validator(mode="after")
    def _require_at_least_one_day(self):
        if not self.itinerary:
            raise ValueError("itinerary must contain at least one day")
        return self


def _transport_mode_flags(preferences: Dict) -> tuple:
    """Train/cruise/road/flight are mutually exclusive - shared by
    generate_trip_plans (deciding whether a flight search is even needed
    before the shared fetch) and _fetch_anchor_pricing (deciding which
    pricing branch to run)."""
    transport_mode = preferences.get("transportation", "flight").lower()
    return "train" in transport_mode, "cruise" in transport_mode, "road" in transport_mode


async def _search_flights_cached(origin: str, destination: str, departure_date: str, travelers: int, user_id: str) -> List[Dict]:
    """The one place anchor-pricing hits Ignav for flights. Checks the
    short-TTL search cache first (see price_cache_service) so a second
    generation with the same route/date/traveler count within the TTL
    window costs zero real provider calls - usage is only logged on an
    actual cache miss, so provider_usage stays an accurate count of real
    calls, not attempted ones."""
    params = {"origin": origin, "destination": destination, "departure_date": departure_date, "travelers": travelers}
    cached = await price_cache_service.get_cached_search(db, "flight", params)
    if cached is not None:
        return cached
    flights = await duffel_service.search_flights(origin, destination, departure_date, travelers=travelers)
    await usage_service.log_usage(db, "duffel", user_id=user_id, meta={"context": "generate_single_plan"})
    await price_cache_service.cache_search_response(db, "flight", params, flights)
    return flights


async def _search_hotels_cached(destination: str, check_in: str, check_out: str, travelers: int, currency: str, user_id: str) -> List[Dict]:
    """Same caching contract as _search_flights_cached above, for SerpApi
    hotel search."""
    params = {"destination": destination, "check_in": check_in, "check_out": check_out, "travelers": travelers, "currency": currency}
    cached = await price_cache_service.get_cached_search(db, "hotel", params)
    if cached is not None:
        return cached
    hotels = await serpapi_hotels_service.search_hotels(destination, check_in, check_out, travelers=travelers, currency=currency)
    await usage_service.log_usage(db, "serpapi", user_id=user_id, meta={"context": "generate_single_plan"})
    await price_cache_service.cache_search_response(db, "hotel", params, hotels)
    return hotels


async def _fetch_anchor_pricing(
    preferences: Dict, plan_type: str, user_id: str, fare_units: float, room_count: int,
    raw_flights: Any = _NOT_FETCHED, raw_hotels: Any = _NOT_FETCHED,
) -> Dict[str, Any]:
    """Fetch real flight/train + hotel anchor prices for one tier. Split out
    of generate_single_plan so a single-tier regenerate can reuse a
    previously-fetched anchor (see the "anchor" param there) instead of
    hitting Duffel/SerpApi again for tiers that already anchored fine.

    raw_flights/raw_hotels: pre-fetched, not-yet-tier-selected search
    results shared across all three tiers of one generation (see
    generate_trip_plans) - passing these turns Budget/Premium/Luxury from
    three independent searches into three SELECTIONS from the same single
    search. Left at the _NOT_FETCHED sentinel, this fetches for itself
    (single-tier callers like regenerate-without-a-cached-anchor)."""
    is_train, is_cruise, is_road = _transport_mode_flags(preferences)
    # One-way only has an observable effect on flights - train/cruise/road are
    # all hardcoded/computed estimates already priced as a single leg (see
    # their branches below), not a real fare that return-leg booking changes.
    is_one_way = (not is_train and not is_cruise and not is_road
                  and preferences.get("trip_direction") == "one_way")

    flight_price = 0
    flight_airline = ""
    flight_number = ""
    flight_dep_time = ""
    flight_arr_time = ""
    flight_duration = ""
    flight_stops = 0

    train_price = 0
    train_name = ""
    train_number = ""
    train_class = ""
    train_duration = ""

    cruise_price = 0
    cruise_cabin_type = ""
    cruise_duration_label = ""

    road_price = 0
    road_distance_km = 0
    road_vehicle_count = 1
    road_origin_coords = None
    road_dest_coords = None

    hotel_name = ""
    hotel_price_per_night = 0
    hotel_stars = 0
    hotel_limited_inventory = False

    if is_train:
        train_tier_prices = {
            "Budget":  {"price": 450,  "class": "Sleeper (SL)",      "name": "Express Train"},
            "Premium": {"price": 1200, "class": "AC 3-Tier (3A)",    "name": "Superfast Express"},
            "Luxury":  {"price": 2800, "class": "AC 1st Class (1A)", "name": "Rajdhani / Shatabdi"},
        }
        t = train_tier_prices.get(plan_type, train_tier_prices["Budget"])
        train_price    = t["price"] * fare_units
        train_class    = t["class"]
        train_name     = t["name"]
        train_number   = "Train"
        train_duration = "Varies by route"
        logger.info(f"{plan_type}: estimated train = {train_name} {train_class} ₹{train_price:,.0f}")
    elif is_cruise:
        # No accessible developer API exists for real cruise pricing
        # (enterprise-only vendors) - same "no real inventory" situation as
        # trains, so this is a hardcoded estimate table, not a live fetch.
        # Cabin type is TIER-driven (mirrors how train class is tier-driven),
        # not taken from the user's own cruise_cabin_type answer - letting a
        # single user answer skew cabin choice would break the "Budget is
        # cheapest, Luxury priciest" ordering the prompt enforces below.
        # Duration IS taken from the user's answer - trip length is a date-
        # range fact shared by all three tiers, not a luxury-level fact.
        cruise_tier_cabin = {"Budget": "Interior", "Premium": "Balcony", "Luxury": "Suite"}
        cruise_cabin_multiplier = {"Interior": 1.0, "Ocean View": 1.5, "Balcony": 2.2, "Suite": 3.75}
        cruise_duration_rates = {
            "Short getaway (2-5 nights)":   {"base_per_night": 9000, "typical_nights": 4},
            "Week-long (6-9 nights)":       {"base_per_night": 8000, "typical_nights": 7},
            "Extended voyage (10+ nights)": {"base_per_night": 7000, "typical_nights": 12},
        }
        cruise_cabin_type = cruise_tier_cabin.get(plan_type, "Interior")
        cruise_duration_label = preferences.get("cruise_duration_preference") or "Week-long (6-9 nights)"
        rates = cruise_duration_rates.get(cruise_duration_label, cruise_duration_rates["Week-long (6-9 nights)"])
        price_per_traveler = rates["base_per_night"] * rates["typical_nights"] * cruise_cabin_multiplier[cruise_cabin_type]
        # Halved: generate_single_plan sets this same anchor price on BOTH
        # day 1 and the last day (outbound + return leg) and sums both into
        # cost_breakdown.transportation, exactly like it does for train_price/
        # flight_price - correct there because those really are one-way fares
        # doubled into a round trip. A cruise voyage is one continuous price,
        # not two separate legs, so it has to start out halved here or the
        # single-voyage estimate gets silently double-counted downstream.
        cruise_price = (price_per_traveler / 2) * fare_units
        logger.info(f"{plan_type}: estimated cruise = {cruise_cabin_type} cabin, {cruise_duration_label} ₹{cruise_price:,.0f} (per leg; ₹{price_per_traveler * fare_units:,.0f} full voyage)")
    elif is_road:
        # No accessible real driving-distance/fuel-price API is wired into
        # this app - like train/cruise, this is a computed estimate, not a
        # live quote. Unlike train/cruise it's grounded in the trip's real
        # origin/destination via geocoding (locations_service - same
        # curated-list + Nominatim fallback chain the /destinations/{d}/coords
        # endpoint already uses, with amadeus_service's mock coords as the
        # final fallback) since fuel cost genuinely scales with distance in
        # a way seat class doesn't.
        try:
            origin_coords = await _geocode_place(preferences.get("starting_location", ""))
            dest_coords = await _geocode_place(preferences.get("destination", ""))

            if origin_coords and dest_coords:
                # Persisted alongside the price estimate so a later map-route
                # request (see /trips/{trip_id}/road-route) can reuse this
                # same geocode instead of hitting Nominatim again for the
                # same two place names.
                road_origin_coords = origin_coords
                road_dest_coords = dest_coords

                # Great-circle distance undercounts real road distance since
                # roads bend - 1.3x is a commonly-used rule-of-thumb ratio of
                # road distance to straight-line distance for regional/
                # intercity trips.
                ROAD_DETOUR_MULTIPLIER = 1.3
                straight_line_km = _haversine_km(
                    origin_coords["lat"], origin_coords["lng"], dest_coords["lat"], dest_coords["lng"]
                )
                road_distance_km = round(straight_line_km * ROAD_DETOUR_MULTIPLIER, 1)

                # Blended ₹/km rate (fuel + running cost), not separate
                # price-per-liter x mileage - varies by the user's own
                # road_fuel_type answer rather than assuming one vehicle type.
                fuel_rate_per_km = {
                    "Petrol": 7.0,
                    "Diesel": 6.0,
                    "CNG": 4.0,
                    "Hybrid": 4.5,
                    "Electric": 2.0,
                }.get(preferences.get("road_fuel_type"), 7.0)

                # Rough Indian national-highway toll average, zeroed out when
                # the user explicitly asked to avoid tolls.
                toll_rate_per_km = 0.0 if "Avoid tolls" in (preferences.get("road_route_avoidances") or []) else 2.0

                # Fuel/toll cost is per-VEHICLE, not per-seat (unlike
                # flight/train) - scale in discrete vehicle-capacity jumps as
                # the group grows, the same "rooms not heads" logic
                # _room_count already applies to hotels.
                road_vehicle_count = max(1, math.ceil(preferences.get("num_travelers", 1) / 4))
                road_price = (fuel_rate_per_km + toll_rate_per_km) * road_distance_km * road_vehicle_count
                logger.info(
                    f"{plan_type}: estimated road trip = {road_distance_km}km x {road_vehicle_count} "
                    f"vehicle(s) @ ₹{fuel_rate_per_km + toll_rate_per_km:.1f}/km = ₹{road_price:,.0f}"
                )
            else:
                logger.warning(f"Road distance estimate skipped for {plan_type}: could not geocode origin/destination")
        except Exception as e:
            logger.warning(f"Road distance estimate failed for {plan_type}: {e}")
    else:
        try:
            flight_pref = {"Budget": "cheapest", "Premium": "direct", "Luxury": "fastest"}.get(plan_type, "cheapest")
            # Always query for a single traveler - Ignav's own price.total already scales
            # with the "travelers" we pass it (confirmed: requesting travelers=4 returns
            # ~4x the travelers=1 fare), so if we passed num_travelers here we'd double it
            # by multiplying again below. Querying at 1 gives us a clean per-seat fare that
            # WE scale, the same way train_price already does with its fixed base rate.
            if raw_flights is _NOT_FETCHED:
                raw_flights = await _search_flights_cached(
                    preferences.get("starting_location", ""),
                    preferences.get("destination", ""),
                    preferences.get("departure_date", ""),
                    1, user_id,
                )
            af = duffel_service.select_anchor_flight(raw_flights or [], preference=flight_pref)
            if af:
                # Each traveler needs their own seat/fare, discounted by age
                # (Ignav has no separate child/senior fare - see _fare_units).
                flight_price    = af['price']['total'] * fare_units
                flight_airline  = af['airline']
                flight_number   = af['flight_number']
                flight_dep_time = af['departure']['time']
                flight_arr_time = af['arrival']['time']
                flight_duration = af['duration']
                flight_stops    = af['stops']
            logger.info(f"{plan_type}: anchor flight = {flight_airline} {flight_number} ₹{flight_price:,.0f}")
        except Exception as e:
            logger.warning(f"Anchor flight fetch failed for {plan_type}: {e}")

    try:
        # Always query at standard double occupancy - SerpApi/Google Hotels already
        # adjusts rate_per_night based on the "adults" we pass it (confirmed: the same
        # property's rate for 4 adults came back 1.5x-7x its 1-adult rate, inconsistently
        # depending on room type), so passing the true num_travelers here and then
        # multiplying by room_count below would double-count on top of whatever the
        # provider already adjusted. Querying at ROOM_OCCUPANCY gives a stable per-room
        # rate that WE scale by room count, which we fully control.
        if raw_hotels is _NOT_FETCHED:
            raw_hotels = await _search_hotels_cached(
                preferences.get("destination", ""),
                preferences.get("departure_date", ""),
                preferences.get("return_date", ""),
                ROOM_OCCUPANCY, "INR", user_id,
            )
        hotel_results = raw_hotels
        if hotel_results:
            # hotel_results is already price-sorted ascending by the service -
            # SELECT the tier's hotel from real data, never edit its fields.
            ah, hotel_limited_inventory = _select_tier_hotel(hotel_results, plan_type)
            # Group accommodation cost is by room count, not traveler count - 4 people
            # share 2 double-occupancy rooms, not 4x the price of a single room.
            hotel_name           = ah['name']
            hotel_price_per_night = ah['price']['per_night'] * room_count
            hotel_stars          = ah['stars']
            logger.info(
                f"{plan_type}: anchor hotel = {hotel_name} ₹{ah['price']['per_night']:,.0f}/night "
                f"x {room_count} room(s) = ₹{hotel_price_per_night:,.0f}/night"
                f"{' [limited hotel inventory for this destination]' if hotel_limited_inventory else ''}"
            )
    except Exception as e:
        logger.warning(f"Anchor hotel fetch failed for {plan_type}: {e}")

    return {
        "is_train": is_train,
        "is_cruise": is_cruise,
        "is_road": is_road,
        "is_one_way": is_one_way,
        "road_price": road_price,
        "road_distance_km": road_distance_km,
        "road_vehicle_count": road_vehicle_count,
        "road_origin_coords": road_origin_coords,
        "road_dest_coords": road_dest_coords,
        "flight_price": flight_price,
        "flight_airline": flight_airline,
        "flight_number": flight_number,
        "flight_dep_time": flight_dep_time,
        "flight_arr_time": flight_arr_time,
        "flight_duration": flight_duration,
        "flight_stops": flight_stops,
        "train_price": train_price,
        "train_name": train_name,
        "train_number": train_number,
        "train_class": train_class,
        "train_duration": train_duration,
        "cruise_price": cruise_price,
        "cruise_cabin_type": cruise_cabin_type,
        "cruise_duration_label": cruise_duration_label,
        "hotel_name": hotel_name,
        "hotel_price_per_night": hotel_price_per_night,
        "hotel_stars": hotel_stars,
        "hotel_limited_inventory": hotel_limited_inventory,
    }


async def generate_single_plan(
    preferences: Dict, plan_type: str, trip_id: str, user_id: str, anchor: Optional[Dict[str, Any]] = None,
    raw_flights: Any = _NOT_FETCHED, raw_hotels: Any = _NOT_FETCHED,
) -> Dict:
    """Generate a single vacation plan using AI with real price anchoring.

    `anchor`, when provided, skips Step 1's Duffel/SerpApi calls entirely and
    reuses that already-fetched flight/train + hotel pricing - used by the
    per-tier regenerate endpoint so retrying just the AI portion for one tier
    doesn't re-hit paid providers for pricing that hasn't changed.

    `raw_flights`/`raw_hotels`, when provided (and anchor is None), are
    passed straight through to _fetch_anchor_pricing - see its docstring.
    Used by generate_trip_plans to share one flight search + one hotel
    search across all three tiers instead of each tier searching for itself.
    """
    import json

    currency = preferences.get('currency', 'INR')
    currency_symbol = '₹' if currency == 'INR' else '$'
    num_travelers = preferences.get('num_travelers', 1)
    room_count = _room_count(num_travelers)
    # Age-weighted count for flight/train/meal pricing (room count above stays
    # on raw headcount - occupancy isn't age-discounted).
    fare_units = _fare_units(
        preferences.get('adults', num_travelers),
        preferences.get('children', 0),
        preferences.get('seniors', 0),
    )
    # Single shared nights computation (services/date_utils.py) - also used
    # by serpapi_hotels_service.py/amadeus_service.py's hotel-search pricing,
    # so the itinerary below and hotel pricing can never independently drift
    # back out of agreement with each other.
    nights = date_utils.trip_nights(preferences['departure_date'], preferences['return_date'])

    # ── Step 1: Fetch real anchor prices (or reuse a previously-fetched one)
    if anchor is None:
        anchor = await _fetch_anchor_pricing(
            preferences, plan_type, user_id, fare_units, room_count,
            raw_flights=raw_flights, raw_hotels=raw_hotels,
        )

    is_train = anchor["is_train"]
    is_cruise = anchor["is_cruise"]
    is_road = anchor["is_road"]
    # .get() with a default (unlike the direct indexing above) so an
    # already-cached anchor_pricing dict from before this field existed
    # (e.g. a regenerate reusing an old stored plan's anchor) doesn't KeyError -
    # it just falls back to "has a return leg", the previous universal behavior.
    is_one_way = anchor.get("is_one_way", False)
    road_price = anchor["road_price"]
    road_distance_km = anchor["road_distance_km"]
    road_vehicle_count = anchor["road_vehicle_count"]
    flight_price = anchor["flight_price"]
    flight_airline = anchor["flight_airline"]
    flight_number = anchor["flight_number"]
    flight_dep_time = anchor["flight_dep_time"]
    flight_arr_time = anchor["flight_arr_time"]
    flight_duration = anchor["flight_duration"]
    flight_stops = anchor["flight_stops"]
    train_price = anchor["train_price"]
    train_name = anchor["train_name"]
    train_number = anchor["train_number"]
    train_class = anchor["train_class"]
    train_duration = anchor["train_duration"]
    cruise_price = anchor["cruise_price"]
    cruise_cabin_type = anchor["cruise_cabin_type"]
    cruise_duration_label = anchor["cruise_duration_label"]
    hotel_name = anchor["hotel_name"]
    hotel_price_per_night = anchor["hotel_price_per_night"]
    hotel_stars = anchor["hotel_stars"]
    hotel_limited_inventory = anchor["hotel_limited_inventory"]

    # Single source of truth for "the anchor transport leg" for this trip -
    # train/cruise/flight are mutually exclusive - used everywhere below
    # (prompt constraints, JSON template, system message, post-processing)
    # instead of repeating a train-or-flight-only ternary in a dozen places,
    # which is what broke when cruise silently fell through to flight.
    if is_train:
        anchor_transport_price = train_price
        anchor_transport_label = "train"
        transport_details_prefix = f"{train_name} {train_class} "
    elif is_cruise:
        anchor_transport_price = cruise_price
        anchor_transport_label = "cruise"
        transport_details_prefix = f"{cruise_cabin_type} cabin cruise "
    elif is_road:
        anchor_transport_price = road_price
        anchor_transport_label = "road"
        transport_details_prefix = f"Self-drive road trip ({road_distance_km:.0f} km, {road_vehicle_count} vehicle(s)) "
    else:
        anchor_transport_price = flight_price
        anchor_transport_label = "flight"
        transport_details_prefix = f"{flight_airline} {flight_number} "

    # ── Step 2: Build tier-specific instructions ─────────────────────────────
    tier_rules = {
        "Budget": f"""
- Cheapest available options throughout
- Hotel: {hotel_name or 'budget guesthouse'} at EXACTLY ₹{hotel_price_per_night:,.0f}/night (use this hotel name and price)
- Public transport (metro, bus, shared rides)
- Street food and casual dining (₹150-400/meal)
- Free or low-cost attractions
- TOTAL trip cost must be the LOWEST of the three tiers
""",
        "Premium": f"""
- Mid-range comfortable options
- Hotel: {hotel_name or '4-star hotel'} at EXACTLY ₹{hotel_price_per_night:,.0f}/night (use this hotel name and price)
- Mix of metro and private transport
- Good restaurants (₹500-1200/meal)
- Mix of free and paid attractions
- TOTAL trip cost must be BETWEEN Budget and Luxury tiers
""",
        "Luxury": f"""
- Premium luxury options only
- Hotel: {hotel_name or '5-star luxury hotel'} at EXACTLY ₹{hotel_price_per_night:,.0f}/night (use this hotel name and price)
- Private transfers and premium vehicles only
- Fine dining at signature restaurants (₹1500+/meal)
- Exclusive experiences, private tours, VIP access
- TOTAL trip cost must be the HIGHEST of the three tiers
"""
    }

    # ── Step 3: Build the prompt with constraints at the TOP ─────────────────
    if is_train:
        transport_constraint = f"""TRAIN (DO NOT CHANGE THESE VALUES):
  Train Name: {train_name}
  Class: {train_class}
  Duration: {train_duration}
  PRICE: ₹{train_price:,.0f} total for {num_travelers} traveler(s) (USE THIS EXACT NUMBER)""" if train_price > 0 else "Use realistic Indian train prices."
    elif is_cruise:
        transport_constraint = f"""CRUISE (DO NOT CHANGE THESE VALUES):
  Cabin Type: {cruise_cabin_type}
  Voyage Length: {cruise_duration_label}
  PRICE: ₹{cruise_price:,.0f} total for {num_travelers} traveler(s) (USE THIS EXACT NUMBER)""" if cruise_price > 0 else "Use realistic cruise fare estimates."
    elif is_road:
        transport_constraint = f"""ROAD TRIP FUEL + TOLL ESTIMATE (DO NOT CHANGE THIS VALUE — this is an ESTIMATE, not a real quoted price):
  Estimated driving distance: {road_distance_km:.0f} km (one-way)
  Vehicle(s) needed: {road_vehicle_count}
  PRICE: ₹{road_price:,.0f} total for {num_travelers} traveler(s), one-way (USE THIS EXACT NUMBER)""" if road_price > 0 else "Use a realistic estimated fuel + toll cost for a road trip of this distance — present it clearly as an estimate, not a real quote."
    else:
        transport_constraint = f"""FLIGHT (DO NOT CHANGE THESE VALUES):
  Airline: {flight_airline}
  Flight Number: {flight_number}
  Departure: {flight_dep_time}
  Arrival: {flight_arr_time}
  Duration: {flight_duration}
  Stops: {'Non-stop' if flight_stops == 0 else f'{flight_stops} stop(s)'}
  PRICE: ₹{flight_price:,.0f} (USE THIS EXACT NUMBER — do not round, inflate, or change)""" if flight_price > 0 else "Use realistic market flight prices."

    hotel_constraint = f"""HOTEL (DO NOT CHANGE THESE VALUES):
  Name: {hotel_name}
  Stars: {hotel_stars}★
  PRICE PER NIGHT: ₹{hotel_price_per_night:,.0f} total for {room_count} room(s) accommodating {num_travelers} traveler(s) (USE THIS EXACT NUMBER)""" if hotel_price_per_night > 0 else "Use realistic market hotel prices."

    # Cruise-only descriptive flavor for the itinerary text (activities/
    # highlights) - deliberately NOT part of the pricing constraints above.
    # cruise_cabin_type here is the tier-driven cabin (see _fetch_anchor_pricing),
    # used for narrative color; dining/itinerary style come straight from the
    # user's own Cruise Preferences answers.
    cruise_flavor_block = ""
    if is_cruise:
        dining_style = preferences.get("cruise_dining_style") or "Flexible anytime dining"
        itinerary_style = preferences.get("cruise_itinerary_style") or "No preference"
        if itinerary_style == "Island-hopping":
            itinerary_guidance = "favor multiple ports of call / island-hopping stops across the voyage"
        elif itinerary_style == "Single destination focus":
            itinerary_guidance = "favor a single destination/port focus with more time onshore there"
        elif "Relaxation" in itinerary_style:
            itinerary_guidance = "favor onboard relaxation with fewer, shorter port stops"
        else:
            itinerary_guidance = "no strong itinerary-style preference - use your judgment"
        cruise_flavor_block = f"""
CRUISE PREFERENCES (reflect these in the itinerary's activities/highlights text - they do not change the price above):
- Cabin type: {cruise_cabin_type}
- Dining style: {dining_style}
- Itinerary style: {itinerary_style} - {itinerary_guidance}
"""

    # Road-only descriptive flavor for the itinerary text (activities/
    # highlights/driving notes) - same "narrative color, not pricing" role as
    # cruise_flavor_block above. Pulls from the road_* wizard fields, which
    # exist on the frontend (TripPlannerPage.jsx) but were previously never
    # read anywhere in this file.
    road_flavor_block = ""
    if is_road:
        route_style = preferences.get("road_route_style") or "Fastest"
        drivers = preferences.get("road_drivers") or 1
        max_driving_hours_per_day = preferences.get("road_max_driving_hours_per_day") or 8
        road_lines = [
            f"- Route style: {route_style}",
            f"- Driving: {drivers} driver(s), max {max_driving_hours_per_day} hours/day - break the trip into "
            "realistic driving days/stops instead of one long haul, and mention driving time between stops",
        ]
        route_avoidances = preferences.get("road_route_avoidances") or []
        if route_avoidances:
            road_lines.append(f"- Route avoidances: {', '.join(route_avoidances)}")
        avoid = preferences.get("road_avoid") or []
        if avoid:
            road_lines.append(f"- Avoid on route: {', '.join(avoid)}")
        overnight_accommodation = preferences.get("road_overnight_accommodation") or []
        road_lines.append(
            f"- Overnight waypoint stays: {', '.join(overnight_accommodation) if overnight_accommodation else 'no preference'}"
        )
        food_preference = preferences.get("road_food_preference") or "Mix of everything"
        road_lines.append(f"- Food along the route: {food_preference}")
        route_attractions = preferences.get("road_route_attractions") or []
        if route_attractions:
            road_lines.append(f"- Route attractions to favor: {', '.join(route_attractions)}")
        vehicle_note = (preferences.get("road_vehicle_mileage_or_model") or "").strip()
        if vehicle_note:
            road_lines.append(f"- Vehicle: {vehicle_note}")
        max_hours_before_break = preferences.get("road_max_hours_before_break")
        break_duration_minutes = preferences.get("road_break_duration_minutes")
        if max_hours_before_break or break_duration_minutes:
            hours_part = f"every {max_hours_before_break} hour(s)" if max_hours_before_break else "regularly"
            duration_part = f" for {break_duration_minutes} minute(s)" if break_duration_minutes else ""
            road_lines.append(f"- Breaks: stop {hours_part}{duration_part} - reflect these stops in the day's activities")
        fuel_type = (preferences.get("road_fuel_type") or "").strip()
        if fuel_type:
            road_lines.append(f"- Fuel type: {fuel_type}")
        ev_battery_percent = preferences.get("road_ev_battery_percent")
        if ev_battery_percent is not None:
            road_lines.append(f"- Starting EV battery: {ev_battery_percent}% - factor in charging stops if the route needs them")
        ev_recharge_preference = (preferences.get("road_ev_recharge_preference") or "").strip()
        if ev_recharge_preference:
            road_lines.append(f"- EV recharge preference: {ev_recharge_preference}")
        road_flavor_block = (
            "ROAD TRIP PREFERENCES (reflect these in the itinerary's activities/highlights text - "
            "they do not change the price above):\n" + "\n".join(road_lines) + "\n"
        )

    # Mode-agnostic descriptive flavor for the itinerary text (activities/
    # meals/highlights) - same "narrative color, not pricing" role as
    # cruise_flavor_block above, but applies to every transport mode since
    # interests/dietary_preferences/accessibility_requirements/travel_pace
    # are collected in the same "Interests" and "Additional Details" wizard
    # steps regardless of transportation choice. interests and travel_pace
    # are structured fields with sensible defaults from the UI, so they're
    # included whenever present; dietary_preferences and
    # accessibility_requirements are free-text and blank for most users, so
    # they're only added when the user actually wrote something - otherwise
    # this block would print "Accessibility needs: none" into nearly every
    # prompt for no benefit.
    traveler_preference_lines = []
    interests = preferences.get("interests") or []
    if interests:
        traveler_preference_lines.append(
            f"- Interests: {', '.join(interests)} - weave activities and highlights toward these where it fits naturally"
        )
    travel_pace = preferences.get("travel_pace")
    if travel_pace:
        pace_guidance = {
            "Relaxed": "favor a lighter schedule - fewer activities per day, more downtime",
            "Fast-paced": "pack more activities into each day, minimize downtime",
        }.get(travel_pace, "a balanced, moderate number of activities per day")
        traveler_preference_lines.append(f"- Pace: {travel_pace} - {pace_guidance}")
    dietary_preferences = (preferences.get("dietary_preferences") or "").strip()
    if dietary_preferences:
        traveler_preference_lines.append(f"- Dietary: {dietary_preferences} - factor into meal suggestions")
    accessibility_requirements = (preferences.get("accessibility_requirements") or "").strip()
    if accessibility_requirements:
        traveler_preference_lines.append(
            f"- Accessibility: {accessibility_requirements} - factor into activity and accommodation choices"
        )
    traveler_preferences_block = ""
    if traveler_preference_lines:
        traveler_preferences_block = (
            "TRAVELER PREFERENCES (reflect these in the itinerary's activities/meals/highlights "
            "text - they do not change the prices above):\n" + "\n".join(traveler_preference_lines)
        )

    prompt = f"""You are a travel pricing engine. Generate a {plan_type} trip plan as valid JSON only.

╔══════════════════════════════════════════════════════╗
║  MANDATORY CONSTRAINTS — VIOLATION = INVALID OUTPUT  ║
╠══════════════════════════════════════════════════════╣
║ {transport_constraint}
║
║ {hotel_constraint}
║
║ TIER RULE: {plan_type} plan total must be
║ {'the LOWEST cost of all three tiers' if plan_type == 'Budget' else 'BETWEEN Budget and Luxury costs' if plan_type == 'Premium' else 'the HIGHEST cost of all three tiers'}
╚══════════════════════════════════════════════════════╝

TRIP DETAILS:
- Destination: {preferences['destination']}
- From: {preferences['starting_location']}
- Dates: {preferences['departure_date']} to {preferences['return_date']} ({nights} night(s))
- Travelers: {num_travelers}
- Tier: {plan_type}
- Currency: {currency}

TIER GUIDELINES:
{tier_rules[plan_type]}
{cruise_flavor_block}
{road_flavor_block}
{traveler_preferences_block}
OUTPUT: Return ONLY valid JSON, no markdown, no explanation:
{{
  "plan_type": "{plan_type}",
  "currency": "{currency}",
  "currency_symbol": "{currency_symbol}",
  "itinerary": {{
    "day_1": {{
      "date": "{preferences['departure_date']}",
      "transportation": {{"mode": "{anchor_transport_label}", "details": "{transport_details_prefix}{preferences.get('starting_location','')} to {preferences['destination']}", "cost": {anchor_transport_price if anchor_transport_price > 0 else 15000}}},
      "activities": [{{"time": "14:00", "activity": "Check-in and explore", "location": "Hotel", "cost": 0, "category": "free", "pricing_type": "flat_group"}}],
      "accommodation": {{"name": "{hotel_name or 'Hotel'}", "type": "hotel", "cost": {hotel_price_per_night if hotel_price_per_night > 0 else 5000}, "location": "{preferences['destination']}"}},
      "meals": [{{"time": "dinner", "restaurant": "Local restaurant", "cuisine": "Local", "cost": 500}}],
      "daily_total": {int(anchor_transport_price + hotel_price_per_night + 500) if anchor_transport_price and hotel_price_per_night else 20000},
      "cumulative_total": {int(anchor_transport_price + hotel_price_per_night + 500) if anchor_transport_price and hotel_price_per_night else 20000},
      "fixed_costs": {int(anchor_transport_price + hotel_price_per_night) if anchor_transport_price and hotel_price_per_night else 18000},
      "variable_costs": 500
    }}
  }},
  "cost_breakdown": {{
    "transportation": {anchor_transport_price if anchor_transport_price > 0 else 15000},
    "accommodation": 0,
    "food": 0,
    "activities": 0,
    "miscellaneous": 0
  }},
  "total_cost": 0,
  "highlights": ["highlight 1", "highlight 2", "highlight 3"],
  "budget_tips": ["tip 1", "tip 2", "tip 3"]
}}

Fill in EXACTLY {nights} itinerary day(s) - one per night of the stay, dated {preferences['departure_date']} through the night before the {preferences['return_date']} return. Do NOT add a separate day for {preferences['return_date']} itself - the traveler checks out and travels home that morning, so it is not its own paid day; fold the return leg's transportation cost into the final day above instead.
Use EXACT prices from constraints above — especially ₹{anchor_transport_price:,.0f} for {anchor_transport_label} and ₹{hotel_price_per_night:,.0f}/night for hotel.
Generate realistic activities, meals, and local transport for each day.

MEAL AND ACTIVITY PRICING (group size = {num_travelers}):
- Every meal "cost" must be the PER-PERSON price of that meal only (e.g. a ₹400 thali is "cost": 400,
  regardless of group size). Do NOT multiply meal costs by the traveler count yourself — the system
  does that automatically afterward.
- Every activity with cost > 0 must include a "pricing_type" field:
  - "per_person" for anything charged per visitor (entry tickets, adventure sports, rides, per-head
    experiences). Report the PER-PERSON price only - do not multiply by traveler count yourself.
  - "flat_group" for anything with one fixed price regardless of group size (a private car/driver,
    a hired guide, a chartered boat). Report the actual total price for the whole group.
  - If unsure whether something is per-person or a flat group rate, use "per_person" - it's the more
    common case for tickets and experiences."""

    # ── Step 4: Call LLM (retry with backoff on failure) ──────────────────────
    max_attempts = 3
    last_error = None
    for attempt in range(max_attempts):
      try:
        if attempt > 0:
            backoff_seconds = 2 ** (attempt - 1)  # 1s, 2s, ...
            logger.warning(f"Retrying {plan_type} plan generation (attempt {attempt + 1}/{max_attempts}) after {backoff_seconds}s...")
            await asyncio.sleep(backoff_seconds)
        system_message = (
            f"You are a travel cost calculator that outputs ONLY valid JSON. "
            f"You ALWAYS use the exact prices provided in the MANDATORY CONSTRAINTS section. "
            f"{anchor_transport_label.capitalize()} transport cost MUST be ₹{anchor_transport_price:,.0f}. "
            f"Hotel cost MUST be ₹{hotel_price_per_night:,.0f}/night. "
            f"Never invent or change these numbers."
        )

        stream = await _get_gemini_client().aio.models.generate_content_stream(
            model=GEMINI_MODEL,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                system_instruction=system_message,
                response_mime_type="application/json",
                response_json_schema=PLAN_RESPONSE_SCHEMA,
            ),
        )
        await usage_service.log_usage(db, "gemini", user_id=user_id, meta={"context": "generate_single_plan", "plan_type": plan_type})

        full_response = ""
        async for chunk in stream:
            if chunk.text:
                full_response += chunk.text

        # Parse + validate. response_mime_type="application/json" already
        # constrains Gemini's token-level output, so the raw text is expected
        # to be clean JSON - no substring extraction needed. model_validate
        # against GeneratedPlanResponse is the real gate: a response that
        # parses as JSON but doesn't match the expected shape (wrong types,
        # missing required fields, zero days) raises here and is caught by
        # the except block below, feeding the same retry-then-fail path as
        # any other generation failure - it is never silently coerced into a
        # plausible-looking plan.
        plan_data_raw = json.loads(full_response)
        try:
            validated = GeneratedPlanResponse.model_validate(plan_data_raw)
        except ValidationError as e:
            raise ValueError(f"{plan_type}: response failed schema validation: {e}") from e
        plan_data = validated.model_dump()

        await generation_log_service.log_generation_attempt(
            db, trip_id=trip_id, plan_type=plan_type, attempt=attempt + 1, model=GEMINI_MODEL,
            status="success", prompt=prompt, response_text=full_response,
            dietary_preferences=dietary_preferences, accessibility_requirements=accessibility_requirements,
        )

        # ── Step 5: Post-process — enforce exact prices regardless of AI output
        logger.info(f"{plan_type}: anchor {anchor_transport_label}_price={anchor_transport_price}, hotel_price={hotel_price_per_night}")
        logger.info(f"{plan_type}: AI day_1 transport cost before fix = {plan_data.get('itinerary', {}).get('day_1', {}).get('transportation', {}).get('cost', 'N/A')}")

        # Every day/transportation/accommodation/meal/activity below is
        # guaranteed present and correctly typed by GeneratedPlanResponse
        # validation above - no isinstance guards needed here anymore.
        itinerary = plan_data['itinerary']

        if anchor_transport_price > 0:
            plan_data['cost_breakdown']['transportation'] = anchor_transport_price

            days = sorted(itinerary.keys())

            if days:
                # Day 1: outbound transport
                d1 = itinerary[days[0]]
                d1['transportation']['cost'] = anchor_transport_price
                d1['transportation']['mode'] = anchor_transport_label
                if is_train:
                    d1['transportation']['details'] = f"{train_name} ({train_class}) - {preferences.get('starting_location','')} to {preferences['destination']}"
                elif is_cruise:
                    d1['transportation']['details'] = f"{cruise_cabin_type} cabin cruise - {preferences.get('starting_location','')} to {preferences['destination']}"
                elif is_road:
                    d1['transportation']['details'] = f"Self-drive - {preferences.get('starting_location','')} to {preferences['destination']} (~{road_distance_km:.0f} km)"
                else:
                    d1['transportation']['details'] = f"{flight_airline} {flight_number} - {d1['transportation'].get('details', '')}"
                for act in d1['activities']:
                    kw = anchor_transport_label
                    if kw in act.get('activity', '').lower() or 'depart' in act.get('activity', '').lower():
                        act['cost'] = anchor_transport_price

                # Last day: always force return transport to match outbound -
                # unless this is a one-way flight, where there's no return leg
                # to price. Zeroing it out here (rather than leaving whatever
                # number the AI invented) is what keeps the cost_breakdown
                # recompute below at 1x anchor_transport_price instead of the
                # round-trip 2x - it sums every day's transportation.cost, so
                # a zeroed last leg is the whole fix, no separate total-side
                # change needed.
                if len(days) > 1:
                    dl = itinerary[days[-1]]
                    if is_one_way:
                        dl['transportation']['cost'] = 0
                        dl['transportation']['mode'] = anchor_transport_label
                        dl['transportation']['details'] = "No return flight booked (one-way trip)"
                    else:
                        dl['transportation']['cost'] = anchor_transport_price
                        dl['transportation']['mode'] = anchor_transport_label
                        if is_train:
                            dl['transportation']['details'] = f"{train_name} ({train_class}) - {preferences['destination']} to {preferences.get('starting_location','')}"
                        elif is_cruise:
                            dl['transportation']['details'] = f"{cruise_cabin_type} cabin cruise - {preferences['destination']} to {preferences.get('starting_location','')}"
                        elif is_road:
                            dl['transportation']['details'] = f"Self-drive - {preferences['destination']} to {preferences.get('starting_location','')} (~{road_distance_km:.0f} km)"
                        else:
                            dl['transportation']['details'] = f"Return {flight_airline} {flight_number} - {preferences['destination']} to {preferences.get('starting_location','')}"
                elif not is_one_way:
                    # A single-night stay has only one itinerary day (matching
                    # nights, not nights+1 - see the `nights` computation
                    # above), and that one day is simultaneously the outbound
                    # AND the return day. The outbound leg was already priced
                    # on d1 above (d1 IS this day, since len(days) == 1) - add
                    # the return leg's cost on top rather than overwrite it,
                    # so a round trip still ends up priced at the correct
                    # round-trip total (2x anchor_transport_price) instead of
                    # silently losing the return leg just because it has
                    # nowhere else to live. One-way skips this entirely (no
                    # return leg exists to add).
                    d1['transportation']['cost'] = anchor_transport_price * 2

        if hotel_price_per_night > 0:
            for day_data in itinerary.values():
                day_data['accommodation']['cost'] = hotel_price_per_night
                day_data['accommodation']['name'] = hotel_name or day_data['accommodation'].get('name', 'Hotel')

        # Meals and per-person activities come back from the AI as a single person's
        # cost regardless of what the prompt asked - enforce the group scaling here
        # rather than trust the AI to have done the multiplication itself. Age-weighted
        # (fare_units), not raw headcount, so child/senior discounts apply here too.
        _scale_per_person_costs(itinerary, fare_units)

        # Recalculate per-day totals AND the top-level cost_breakdown/total_cost from
        # the same pass over the (now anchor-corrected) itinerary, so the two can never
        # drift apart the way AI-authored daily_total/cumulative_total can.
        day_keys_sorted = sorted(itinerary.keys())

        real_transport = 0
        real_accommodation = 0
        real_food = 0
        real_activities = 0
        running_cumulative = 0

        for day_key in day_keys_sorted:
            day_data = itinerary[day_key]

            day_transport = day_data['transportation']['cost']
            day_accommodation = day_data['accommodation']['cost']
            day_food = sum(meal['cost'] for meal in day_data['meals'])
            day_activities = sum(act['cost'] for act in day_data['activities'])

            day_fixed = day_transport + day_accommodation
            day_variable = day_food + day_activities

            day_data['fixed_costs'] = day_fixed
            day_data['variable_costs'] = day_variable
            day_data['daily_total'] = day_fixed + day_variable

            running_cumulative += day_data['daily_total']
            day_data['cumulative_total'] = running_cumulative

            real_transport += day_transport
            real_accommodation += day_accommodation
            real_food += day_food
            real_activities += day_activities

        plan_data['cost_breakdown'] = {
            'transportation': real_transport,
            'accommodation': real_accommodation,
            'food': real_food,
            'activities': real_activities,
            'miscellaneous': 0,
        }
        plan_data['total_cost'] = running_cumulative
        logger.info(f"{plan_type}: day_1 transport cost AFTER fix = {plan_data.get('itinerary', {}).get('day_1', {}).get('transportation', {}).get('cost', 'N/A')}")
        logger.info(f"{plan_type}: recalculated total = {plan_data['total_cost']}")

        # Force plan_type rather than trust the AI echoed it correctly - the
        # regenerate-single-tier endpoint identifies/replaces a plan in the
        # saved trip by this field, so it must always match what was asked for.
        plan_data['plan_type'] = plan_type
        plan_data['status'] = 'ready'
        plan_data['anchor_pricing'] = anchor
        plan_data.setdefault('currency', currency)
        plan_data.setdefault('currency_symbol', currency_symbol)
        if hotel_limited_inventory:
            plan_data['hotel_inventory_note'] = (
                "Limited hotel options are available for this destination - "
                "Budget/Premium/Luxury tiers may share the same or similarly priced hotel."
            )
        if is_train:
            plan_data['train_placeholder_pricing'] = True
        if is_cruise:
            plan_data['cruise_placeholder_pricing'] = True
        if is_road:
            plan_data['road_placeholder_pricing'] = True
        return plan_data

      except Exception as e:
            last_error = e
            logger.warning(f"Attempt {attempt + 1}/{max_attempts} failed for {plan_type} plan: {e}")
            await generation_log_service.log_generation_attempt(
                db, trip_id=trip_id, plan_type=plan_type, attempt=attempt + 1, model=GEMINI_MODEL,
                status="failed", prompt=prompt, response_text=locals().get('full_response', ''), error=str(e),
                dietary_preferences=dietary_preferences, accessibility_requirements=accessibility_requirements,
            )

    # All attempts genuinely failed - surface this as a distinct failure state
    # rather than a "successful" zero-cost plan. The zero-cost shape used to be
    # indistinguishable from a real (if oddly priced) plan, so it got persisted
    # and shown to the user as if generation had succeeded.
    logger.error(f"All {max_attempts} attempts failed for {plan_type} plan: {last_error}")
    sentry_sdk.capture_exception(last_error, tags={"provider": "gemini", "plan_type": plan_type})
    return {
        "plan_type": plan_type,
        "status": "failed",
        "currency": currency,
        "currency_symbol": currency_symbol,
        "itinerary": {},
        "cost_breakdown": {"transportation": 0, "accommodation": 0, "food": 0, "activities": 0, "miscellaneous": 0},
        "total_cost": 0,
        "highlights": [],
        "budget_tips": [],
        "generation_failed": True,
        "error": f"{plan_type} plan generation failed, please try again.",
        # The anchor fetch (Step 1) runs before the retry loop and never
        # raises out of this function, so it's always available here too -
        # a later regenerate call can reuse it even after a failed attempt.
        "anchor_pricing": anchor,
    }


@api_router.get("/trips")
async def get_user_trips(request: Request):
    user = await get_current_user(request)
    
    trips = await db.trips.find(
        {"user_id": user.user_id},
        {"_id": 0}
    ).sort("created_at", -1).to_list(100)
    
    return {"trips": trips}


@api_router.get("/trips/quota-status")
async def get_trip_quota_status(request: Request):
    """Lets the trip planner show remaining free generations before the
    user hits the wall, rather than only surfacing it as an error."""
    user = await get_current_user(request)
    is_premium = await is_user_premium(user.user_id)
    if is_premium:
        return {"is_premium": True, "used": 0, "limit": None, "remaining": None}
    status = await quota_service.get_quota_status(db, user.user_id)
    return {"is_premium": False, **status}


@api_router.get("/trips/{trip_id}")
async def get_trip(trip_id: str, request: Request):
    user = await get_current_user(request)
    
    trip = await db.trips.find_one(
        {"trip_id": trip_id, "user_id": user.user_id},
        {"_id": 0}
    )
    
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    return trip


@api_router.get("/trips/{trip_id}/road-route")
async def get_trip_road_route(trip_id: str, request: Request):
    """Real driving route (polyline + distance/duration) between a Road
    trip's origin and destination - Phase 1 of the Road Trip map feature
    (route + waypoints/rendering only; live position tracking and proximity
    alerts are a later phase, not this one).

    Reuses road_origin_coords/road_dest_coords already geocoded and
    persisted on any generated tier's anchor_pricing (see
    _fetch_anchor_pricing's is_road branch) instead of re-geocoding the same
    two place names again on every map view - falls back to a fresh geocode
    only for older trips saved before those fields existed.
    """
    user = await get_current_user(request)

    trip = await db.trips.find_one(
        {"trip_id": trip_id, "user_id": user.user_id},
        {"_id": 0}
    )
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    preferences = trip.get("preferences", {})
    if "road" not in (preferences.get("transportation") or "").lower():
        raise HTTPException(status_code=400, detail="This trip is not a Road trip")

    origin_coords = None
    dest_coords = None
    for plan in trip.get("plans", []):
        anchor = plan.get("anchor_pricing") or {}
        if anchor.get("road_origin_coords") and anchor.get("road_dest_coords"):
            origin_coords = anchor["road_origin_coords"]
            dest_coords = anchor["road_dest_coords"]
            break

    if not origin_coords or not dest_coords:
        origin_coords = await _geocode_place(preferences.get("starting_location", ""))
        dest_coords = await _geocode_place(preferences.get("destination", ""))

    if not origin_coords or not dest_coords:
        raise HTTPException(status_code=502, detail="Could not geocode this trip's origin/destination")

    route = await locations_service.get_driving_route(origin_coords, dest_coords)

    return {
        "origin": {
            "lat": origin_coords["lat"], "lng": origin_coords["lng"],
            "name": preferences.get("starting_location", ""),
        },
        "destination": {
            "lat": dest_coords["lat"], "lng": dest_coords["lng"],
            "name": preferences.get("destination", ""),
        },
        # None if OSRM failed - frontend falls back to a straight line
        # between origin and destination.
        "route": route,
    }


@api_router.delete("/trips/{trip_id}")
async def delete_trip(trip_id: str, request: Request):
    user = await get_current_user(request)
    
    result = await db.trips.delete_one(
        {"trip_id": trip_id, "user_id": user.user_id}
    )
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Trip not found")
    
    return {"message": "Trip deleted successfully"}


def _day_sort_key(day_key: str):
    # "day_2" before "day_10" - a plain string sort would put day_10 first.
    try:
        return (0, int(day_key.rsplit("_", 1)[-1]))
    except (ValueError, IndexError):
        return (1, day_key)


def build_trip_context(trip: dict, tier: Optional[str] = None) -> str:
    """Compact plain-text summary of a trip doc for the chat system prompt.

    trip.plans holds three parallel tiers (Budget/Premium/Luxury). `tier`
    identifies which one is currently on screen (e.g. the tab selected on
    TripResultsPage) and drives both the itinerary summarized here and the
    "Budget: X" label, so the two never contradict each other. If `tier`
    is omitted or doesn't match any generated plan, falls back to the
    trip's originally-requested preferences.budget_level, then to any tier
    that has one generated. destination/dates/travelers are trip-level
    (from preferences) and don't vary by tier. Each day's transportation
    line (flights, transfers) is included alongside its activities, so
    logistics questions ("how do I get from the airport to the hotel")
    can be answered from what's already booked instead of the model
    reaching for general knowledge. Only populated fields are included -
    nothing prints as "None" - and the itinerary digest is capped at a
    handful of days so a long trip can't balloon the prompt.

    Example: build_trip_context({"preferences": {"destination": "Goa",
    "departure_date": "2026-08-10", "return_date": "2026-08-14",
    "adults": 2, "budget_level": "Budget"}, "plans": [{"plan_type": "Budget",
    "itinerary": {"day_1": {"transportation": {"details": "Flight to Goa"},
    "activities": [{"activity": "Arrival"}]}}}]}, tier="Budget")
    -> "Trip: Goa | Dates: 2026-08-10 to 2026-08-14 | Travelers: 2 adults |
    Budget: Budget | Itinerary so far (Budget, 1 day(s)): Day 1 - Transport:
    Flight to Goa; Arrival"
    """
    prefs = trip.get("preferences") or {}
    parts = []

    destination = prefs.get("destination")
    if destination:
        parts.append(f"Trip: {destination}")

    departure_date = prefs.get("departure_date")
    return_date = prefs.get("return_date")
    if departure_date and return_date:
        parts.append(f"Dates: {departure_date} to {return_date}")
    elif departure_date:
        parts.append(f"Dates: from {departure_date}")

    traveler_bits = [
        f"{prefs[key]} {label}"
        for key, label in (("adults", "adults"), ("children", "children"), ("seniors", "seniors"))
        if prefs.get(key)
    ]
    if traveler_bits:
        parts.append(f"Travelers: {', '.join(traveler_bits)}")

    plans = trip.get("plans") or []
    target_tier = tier or prefs.get("budget_level")
    chosen = next((p for p in plans if p.get("plan_type") == target_tier and p.get("itinerary")), None)
    if not chosen:
        chosen = next((p for p in plans if p.get("itinerary")), None)

    budget_level = chosen.get("plan_type") if chosen else prefs.get("budget_level")
    if budget_level:
        parts.append(f"Budget: {budget_level}")

    if chosen:
        itinerary = chosen.get("itinerary") or {}
        day_keys = sorted(itinerary.keys(), key=_day_sort_key)
        MAX_DAYS_SHOWN = 6
        day_summaries = []
        for day_key in day_keys[:MAX_DAYS_SHOWN]:
            day = itinerary.get(day_key) or {}
            bits = []
            # Transport (flights/transfers already booked as part of this
            # day) goes first so the model sees it before activities - it's
            # the detail logistics questions ("how do I get from the
            # airport to the hotel") actually need, and it was previously
            # dropped from this summary entirely.
            transport_details = (day.get("transportation") or {}).get("details")
            if transport_details:
                bits.append(f"Transport: {transport_details}")
            activities = day.get("activities") or []
            themes = [a["activity"] for a in activities[:2] if a.get("activity")]
            if themes:
                bits.append(" + ".join(themes))
            label = day_key.replace("_", " ").capitalize()
            day_summaries.append(f"{label} - {'; '.join(bits)}" if bits else label)
        itinerary_line = "; ".join(day_summaries)
        if len(day_keys) > MAX_DAYS_SHOWN:
            itinerary_line += f"; plus {len(day_keys) - MAX_DAYS_SHOWN} more day(s)"
        parts.append(f"Itinerary so far ({chosen.get('plan_type')}, {len(day_keys)} day(s)): {itinerary_line}")
    else:
        parts.append("No itinerary planned yet")

    return " | ".join(parts)


def _sse_data(text: str) -> str:
    """Encode `text` as a spec-compliant SSE data event.

    A naive f"data: {text}\\n\\n" breaks the moment `text` contains an
    embedded newline (e.g. a paragraph break within a single Gemini
    stream chunk): per the SSE spec, every line of a multi-line data
    payload needs its own "data:" prefix, or a line-by-line client
    parser (like the one in TripResultsPage.jsx) silently drops any
    continuation line that lacks the prefix - the response looks
    truncated in the UI even though the full text was sent and saved.
    """
    return "".join(f"data: {line}\n" for line in text.split("\n")) + "\n"


# AI Assistant Chat
@api_router.post("/chat/stream")
@limiter.limit("15/minute")  # per-IP - a live back-and-forth chat is bursty by nature
@limiter.limit("15/minute", key_func=_session_token_key)  # per-authenticated-user
async def chat_stream(chat_msg: ChatMessage, request: Request):
    user = await get_current_user(request)

    # Chat-history trip-ownership guard: prevents one user from reading or
    # polluting another user's chat_sessions by passing an arbitrary trip_id.
    # Fetches the full doc (not just _id) so it can be reused below for trip
    # context - avoids a second identical query.
    trip = None
    if chat_msg.trip_id:
        trip = await db.trips.find_one(
            {"trip_id": chat_msg.trip_id, "user_id": user.user_id},
            {"_id": 0}
        )
        if not trip:
            raise HTTPException(status_code=403, detail="Forbidden")

    system_message = "You are a helpful AI travel assistant for EYV (Enjoy Your Vacation). Help users with travel planning, recommendations, itinerary changes, and travel-related questions. Be friendly, knowledgeable, and concise."

    if trip:
        trip_context = build_trip_context(trip, chat_msg.selected_tier)
        system_message += (
            f"\n\nYou are a travel assistant helping with the following trip:\n{trip_context}"
            f"\n\nUse this context to answer questions about the trip. If the user asks something "
            f"unrelated to this trip, answer normally. For logistics questions (airport transfers, "
            f"travel times, getting between locations), check this trip's own transportation and "
            f"itinerary data first - the user may already have a flight or transfer booked that "
            f"answers the question - and only fall back to general travel knowledge if the trip "
            f"data doesn't cover it."
        )

    history = await chat_service.get_recent_messages(db, user.user_id, chat_msg.trip_id, limit=20)
    gemini_contents = [
        {"role": msg["role"], "parts": [{"text": msg["content"]}]} for msg in history
    ]
    gemini_contents.append({"role": "user", "parts": [{"text": chat_msg.message}]})

    async def event_generator():
        full_response = ""
        try:
            stream = await _get_gemini_client().aio.models.generate_content_stream(
                model=GEMINI_MODEL,
                contents=gemini_contents,
                config=genai_types.GenerateContentConfig(
                    system_instruction=system_message,
                ),
            )
            await usage_service.log_usage(db, "gemini", user_id=user.user_id, meta={"context": "chat_stream"})

            async for chunk in stream:
                if chunk.text:
                    full_response += chunk.text
                    yield _sse_data(chunk.text)
            await chat_service.append_exchange(db, user.user_id, chat_msg.trip_id, chat_msg.message, full_response)
            yield _sse_data("[DONE]")
        except Exception as e:
            logger.error(f"Chat stream error: {e}")
            yield _sse_data(f"Error: {str(e)}")
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive"
        }
    )

@api_router.get("/chat/{trip_id}")
async def get_chat_history(trip_id: str, request: Request):
    """Chat history for a (user, trip) pair. trip_id == "none" means general
    chat with no trip attached (stored as trip_id = null)."""
    user = await get_current_user(request)
    resolved_trip_id = None if trip_id == "none" else trip_id

    if resolved_trip_id:
        owned_trip = await db.trips.find_one(
            {"trip_id": resolved_trip_id, "user_id": user.user_id},
            {"_id": 1}
        )
        if not owned_trip:
            raise HTTPException(status_code=403, detail="Forbidden")

    messages = await chat_service.get_all_messages(db, user.user_id, resolved_trip_id)
    return {
        "messages": [
            {"role": m["role"], "content": m["content"], "timestamp": m["timestamp"].isoformat()}
            for m in messages
        ]
    }


@api_router.get("/")
async def root():
    return {
        "message": "EYV API - Enjoy Your Vacation",
        "server_started_at": _SERVER_STARTED_AT.isoformat(),
        "server_pid": _SERVER_PID,
    }


# ==================== Booking Search Endpoints ====================

class FlightSearchRequest(BaseModel):
    origin: str
    destination: str
    departure_date: str
    return_date: Optional[str] = None
    travelers: int = 1


class HotelSearchRequest(BaseModel):
    destination: str
    check_in: str
    check_out: str
    travelers: int = 1


# Keys that carry a price/amount. Rejected outright on BookingRequest.item_data so
# it's structurally impossible for a client to smuggle a price into a booking -
# the server always determines price by looking up item_id in price_cache.
_FORBIDDEN_ITEM_DATA_KEYS = {
    "price", "amount", "total_amount", "total_price",
    "unit_amount", "unit_price", "cost", "fare",
}


class BookingRequest(BaseModel):
    booking_type: str  # 'flight' or 'hotel'
    item_id: str  # price_cache key returned by /search/flights or /search/hotels
    item_data: Dict[str, Any] = Field(default_factory=dict)  # display-only fields, no price
    trip_id: Optional[str] = None
    traveler_details: Optional[Dict[str, Any]] = None

    @field_validator("item_data")
    @classmethod
    def _reject_price_fields(cls, v):
        found = _FORBIDDEN_ITEM_DATA_KEYS & v.keys()
        if found:
            raise ValueError(
                f"item_data must not contain price fields ({', '.join(sorted(found))}); "
                "price is always determined server-side from item_id"
            )
        return v


@api_router.post("/search/flights")
async def search_flights_endpoint(req: FlightSearchRequest, request: Request):
    user = await get_current_user(request)
    # Try Duffel (real data) first, fall back to mock
    flights = await duffel_service.search_flights(
        req.origin, req.destination, req.departure_date, req.return_date, req.travelers
    )
    await usage_service.log_usage(db, "duffel", user_id=user.user_id, meta={"context": "search_flights_endpoint"})
    provider = "ignav"
    if not flights:
        logger.warning("Duffel returned no flights, falling back to mock data")
        flights = amadeus_service._generate_mock_flights(
            req.origin, req.destination, req.departure_date,
            req.return_date or req.departure_date, req.travelers
        )
        provider = "mock"
    # Sort: cheapest first
    flights = sorted(flights, key=lambda f: f["price"]["total"])
    # Cache the authoritative price per result and stamp an item_id - the
    # client only ever gets to reference that id back, never the price itself.
    await price_cache_service.cache_search_results(
        db, flights, "flight", provider,
        {
            "origin": req.origin, "destination": req.destination,
            "departure_date": req.departure_date, "return_date": req.return_date,
            "travelers": req.travelers,
        },
    )
    return {"flights": flights, "count": len(flights)}

class TrainSearchRequest(BaseModel):
    origin: str
    destination: str
    departure_date: str
    travelers: int = 1

@api_router.post("/search/trains")
async def search_trains_endpoint(req: TrainSearchRequest, request: Request):
    await get_current_user(request)
    # Live train API not yet integrated. Return empty list with honest message.
    # Frontend should show "Train data unavailable for this route" when count == 0.
    return {
        "trains": [],
        "count": 0,
        "message": "Live train data is not available for this route. Please check IRCTC or Rome2rio for train options."
    }



@api_router.post("/search/hotels")
async def search_hotels_endpoint(req: HotelSearchRequest, request: Request):
    user = await get_current_user(request)
    # Try SerpApi (real data) first, fall back to mock
    hotels = await serpapi_hotels_service.search_hotels(
        req.destination, req.check_in, req.check_out, req.travelers, currency="INR"
    )
    await usage_service.log_usage(db, "serpapi", user_id=user.user_id, meta={"context": "search_hotels_endpoint"})
    provider = "serpapi"
    if not hotels:
        logger.warning("SerpApi returned no hotels, falling back to mock data")
        hotels = amadeus_service._generate_mock_hotels(
            req.destination, req.check_in, req.check_out, req.travelers
        )
        provider = "mock"
    # Enforce tier ordering: always sort by price ascending
    hotels = sorted(hotels, key=lambda h: h["price"]["per_night"])
    # Cache the authoritative price per result and stamp an item_id - the
    # client only ever gets to reference that id back, never the price itself.
    await price_cache_service.cache_search_results(
        db, hotels, "hotel", provider,
        {
            "destination": req.destination, "check_in": req.check_in,
            "check_out": req.check_out, "travelers": req.travelers,
        },
    )
    return {"hotels": hotels, "count": len(hotels)}


@api_router.get("/destinations/{destination}/coords")
async def get_destination_coords_endpoint(destination: str, request: Request):
    await get_current_user(request)
    coords = await locations_service.geocode_destination(destination)
    if coords:
        return {**coords, "geocoded": True}
    # Final fallback: amadeus_service.get_destination_coords never returns
    # None - worst case it hands back a random point anywhere on the globe.
    # That's still useful as SOMETHING to plot, but it's a guess, not a real
    # geocode, and looks identical to a correct pin unless callers are told
    # otherwise - geocoded: False lets the frontend say so instead of
    # silently centering the map on a location that has nothing to do with
    # the actual destination.
    coords = amadeus_service.get_destination_coords(destination)
    return {**coords, "geocoded": False}


@api_router.get("/locations/venue-coords")
async def get_venue_coords_endpoint(request: Request, name: str, city: str = ""):
    """Geocode a named venue (hotel/restaurant/landmark) - NOT the same as
    /destinations/{destination}/coords above, which is city-level only and
    would short-circuit "venue, city"-style queries straight to the city's
    curated centroid (see geocode_venue's docstring). Used by the Road Trip
    map's per-day hotel waypoint markers (TripResultsPage.jsx)."""
    await get_current_user(request)
    coords = await locations_service.geocode_venue(name, city)
    if not coords:
        coords = amadeus_service.get_destination_coords(city or name)
    return coords


@api_router.get("/locations/autocomplete")
@limiter.limit("25/minute")  # per-IP - generous enough for live typeahead, still bounded
async def locations_autocomplete(request: Request, q: str = Query("", min_length=0)):
    """Autocomplete location suggestions. Returns popular destinations matching query.
    Public endpoint - used on landing page as well."""
    suggestions = locations_service.search_locations(q, limit=8)
    return {"suggestions": suggestions}


# ==================== Booking Management ====================

@api_router.post("/bookings")
async def create_booking(req: BookingRequest, request: Request):
    """Create a booking. Price is never trusted from the client - it's resolved
    server-side from price_cache (set at search time) by req.item_id."""
    user = await get_current_user(request)

    resolved = await price_cache_service.resolve_price(db, req.item_id)
    if not resolved:
        raise HTTPException(
            status_code=410,
            detail="This offer has expired. Please search again.",
        )

    booking_id = f"BK{uuid.uuid4().hex[:10].upper()}"
    confirmation_code = f"EYV-{uuid.uuid4().hex[:8].upper()}"

    booking_doc = {
        "booking_id": booking_id,
        "confirmation_code": confirmation_code,
        "user_id": user.user_id,
        "trip_id": req.trip_id,
        "booking_type": req.booking_type,
        "item_data": req.item_data,
        "traveler_details": req.traveler_details or {},
        # Not "confirmed" - no Stripe checkout has even started yet at this
        # point. Only _process_successful_payment (on a real
        # checkout.session.completed / polling-confirmed payment) ever
        # promotes this to "confirmed" - see that function and
        # _process_expired_payment for the rest of the state machine.
        # payment_status mirrors payment_transactions' own convention
        # ("pending" until a real payment lands, then "paid") - it used to
        # be hardcoded "mock_paid" here regardless of whether any payment
        # had happened, which read as an already-paid booking to anything
        # that inspected the field directly.
        "status": "pending_payment",
        "payment_status": "pending",
        "total_amount": resolved["price"],
        "currency": resolved["currency"],
        "created_at": datetime.now(timezone.utc),
    }

    await db.bookings.insert_one(booking_doc)
    booking_doc.pop("_id", None)
    # A plan -> booking conversion only when this booking actually
    # references a generated trip (req.trip_id set) - a standalone
    # flight/hotel booked with no trip_id never went through a generated
    # plan at all, so it isn't a conversion of one.
    if req.trip_id:
        await analytics_service.record_event(
            db, "plan_to_booking", user.user_id,
            {"trip_id": req.trip_id, "booking_id": booking_id, "booking_type": req.booking_type},
        )
    return booking_doc


def _bookable_line_items(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Identify the real, reservable items in a generated plan tier - flights
    and hotels only, for a "Book this Plan" bundle. Activities/meals/
    shopping are never included: nothing in the AI-authored itinerary
    carries a provider/booking reference, so there's no reliable "bookable"
    signal for them at all (this isn't a heuristic that might miss some -
    none of them are ever bookable, by construction).

    Bookability is judged from anchor_pricing (the real Duffel/Ignav +
    SerpApi fetch done at generation time - see _fetch_anchor_pricing):
      - flight: anchor_pricing.flight_price > 0 AND not is_train AND not
        is_cruise AND not is_road. None of trains, cruises, or road trips
        have any real inventory anywhere in this app (POST /search/trains
        always returns empty; there is no cruise search at all; road trips
        are a geocoded-distance fuel/toll estimate, not a provider quote) -
        all three are computed/hardcoded estimates, not provider quotes -
        see train_placeholder_pricing / cruise_placeholder_pricing /
        road_placeholder_pricing. "type": "train"/"cruise"/"road" are
        deliberately never produced here, though the field is a free
        string so any could be added later without a schema change if
        that ever becomes real.
      - hotel: anchor_pricing.hotel_price_per_night > 0. In both cases, 0
        means the real fetch failed and the AI was told to invent a
        placeholder number instead - not tied to any real fare/rate, so
        not bookable.

    The charged PRICE per item comes from cost_breakdown, not from
    anchor_pricing's raw fields - cost_breakdown.transportation/
    accommodation are the plan's own already-computed, already-displayed
    per-category totals (summed across every day's forced-to-anchor
    transportation/accommodation cost), so this always matches exactly
    what the user already saw on screen rather than re-deriving the same
    per-leg/per-night scaling independently and risking drift.
    """
    anchor = plan.get('anchor_pricing') or {}
    cost_breakdown = plan.get('cost_breakdown') or {}
    line_items = []

    if (
        not anchor.get('is_train') and not anchor.get('is_cruise') and not anchor.get('is_road')
        and anchor.get('flight_price', 0) > 0
    ):
        transport_price = cost_breakdown.get('transportation', 0)
        if transport_price > 0:
            line_items.append({
                'type': 'flight',
                'price': transport_price,
                'details': {
                    'airline': anchor.get('flight_airline', ''),
                    'flight_number': anchor.get('flight_number', ''),
                    'departure_time': anchor.get('flight_dep_time', ''),
                    'arrival_time': anchor.get('flight_arr_time', ''),
                    'duration': anchor.get('flight_duration', ''),
                    'stops': anchor.get('flight_stops', 0),
                },
            })

    if anchor.get('hotel_price_per_night', 0) > 0:
        hotel_price = cost_breakdown.get('accommodation', 0)
        if hotel_price > 0:
            line_items.append({
                'type': 'hotel',
                'price': hotel_price,
                'details': {
                    'name': anchor.get('hotel_name', ''),
                    'stars': anchor.get('hotel_stars', 0),
                },
            })

    return line_items


@api_router.post("/trips/{trip_id}/book/{plan_type}")
async def book_trip_plan(trip_id: str, plan_type: str, request: Request):
    """Create ONE bundled booking covering every real bookable item (flight +
    hotel) in a generated plan tier, for a single combined Stripe charge -
    "Book this Plan". Mirrors create_booking's state machine exactly:
    status="pending_payment" at creation (never "confirmed" - the same bug
    class Problem 1 fixed for single-item bookings), promoted only by a
    real payment via the existing, unmodified webhook/polling/scheduler
    machinery below, which operates generically on booking_id/status and
    doesn't care whether a booking has one item_data object or a
    line_items array.
    """
    user = await get_current_user(request)

    if plan_type not in TRIP_PLAN_TYPES:
        raise HTTPException(status_code=400, detail=f"plan_type must be one of {list(TRIP_PLAN_TYPES)}")

    # Scoping to user_id doubles as the ownership check, same pattern as
    # regenerate_trip_plan - a trip_id that doesn't exist and one owned by
    # someone else both 404 identically.
    trip = await db.trips.find_one(
        {"trip_id": trip_id, "user_id": user.user_id},
        {"_id": 0}
    )
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    plans = trip.get("plans", [])
    plan = next((p for p in plans if p.get("plan_type") == plan_type), None)
    if not plan:
        raise HTTPException(status_code=404, detail=f"No {plan_type} plan found on this trip")
    if plan.get("status") != "ready":
        raise HTTPException(status_code=400, detail=f"{plan_type} plan is not ready to book")

    line_items = _bookable_line_items(plan)
    if not line_items:
        raise HTTPException(status_code=400, detail="Nothing in this plan is currently bookable")

    total_amount = sum(item['price'] for item in line_items)
    preferences = trip.get('preferences', {})

    booking_id = f"BK{uuid.uuid4().hex[:10].upper()}"
    confirmation_code = f"EYV-{uuid.uuid4().hex[:8].upper()}"

    booking_doc = {
        "booking_id": booking_id,
        "confirmation_code": confirmation_code,
        "user_id": user.user_id,
        "trip_id": trip_id,
        "booking_type": "bundle",
        "plan_type": plan_type,
        "trip_summary": {
            "destination": preferences.get("destination"),
            "departure_date": preferences.get("departure_date"),
            "return_date": preferences.get("return_date"),
        },
        "line_items": line_items,
        "traveler_details": {},
        # Same not-yet-paid convention as create_booking above - "pending"
        # until a real payment lands, never a value that reads as "paid"
        # before any payment has happened.
        "status": "pending_payment",
        "payment_status": "pending",
        "total_amount": total_amount,
        "currency": plan.get('currency', 'INR'),
        "created_at": datetime.now(timezone.utc),
    }

    await db.bookings.insert_one(booking_doc)
    booking_doc.pop("_id", None)
    # "Book this Plan" always has a trip_id - this IS the plan -> booking
    # conversion path.
    await analytics_service.record_event(
        db, "plan_to_booking", user.user_id,
        {"trip_id": trip_id, "booking_id": booking_id, "booking_type": "bundle", "plan_type": plan_type},
    )
    return booking_doc


@api_router.get("/bookings")
async def list_bookings(request: Request):
    user = await get_current_user(request)
    bookings = await db.bookings.find(
        {"user_id": user.user_id},
        {"_id": 0}
    ).sort("created_at", -1).to_list(100)
    return {"bookings": bookings}


@api_router.get("/bookings/{booking_id}")
async def get_booking(booking_id: str, request: Request):
    user = await get_current_user(request)
    booking = await db.bookings.find_one(
        {"booking_id": booking_id, "user_id": user.user_id},
        {"_id": 0}
    )
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    return booking


@api_router.delete("/bookings/{booking_id}")
async def cancel_booking(booking_id: str, request: Request):
    """Cancel a booking via a simple status flip - only valid for a booking
    that was never actually charged (status "pending_payment" or
    "payment_failed"). A "confirmed" booking has already been paid via a
    real Stripe checkout (_process_successful_payment) and there is no
    Stripe refund call anywhere in this codebase (checked: no
    stripe.Refund/create_refund usage anywhere) - flipping status to
    "cancelled" here would silently leave the customer's money gone while
    the record claims a clean cancellation, so that path is blocked with a
    clear error instead until a real refund flow exists.

    The status filter lives in the update itself, not a separate
    read-then-write, so a cancel racing a payment success (or two
    concurrent cancels) can't both observe "still pending_payment" and let
    one through that should have been blocked - same atomic-filtered-update
    shape as the rewards/payment race fixes elsewhere in this file. The
    follow-up find_one below only runs to build a specific error message
    for the caller; it never gates the mutation itself."""
    user = await get_current_user(request)
    result = await db.bookings.update_one(
        {
            "booking_id": booking_id,
            "user_id": user.user_id,
            "status": {"$in": ["pending_payment", "payment_failed"]},
        },
        {"$set": {"status": "cancelled", "cancelled_at": datetime.now(timezone.utc)}}
    )
    if result.matched_count == 0:
        booking = await db.bookings.find_one(
            {"booking_id": booking_id, "user_id": user.user_id}, {"_id": 0, "status": 1}
        )
        if booking is None:
            raise HTTPException(status_code=404, detail="Booking not found")
        if booking["status"] == "confirmed":
            raise HTTPException(
                status_code=400,
                detail=(
                    "This booking is already paid and confirmed. Cancelling a paid "
                    "booking isn't supported yet - contact support for a refund."
                ),
            )
        raise HTTPException(
            status_code=400,
            detail=f"Booking cannot be cancelled from its current status ('{booking['status']}').",
        )
    return {"message": "Booking cancelled successfully"}


# ==================== Travel Wallet (File Storage) ====================

class WalletItem(BaseModel):
    item_id: str
    user_id: str
    file_path: str
    original_filename: str
    content_type: str
    size: int
    category: str  # 'boarding_pass', 'ticket', 'voucher', 'document'
    title: str
    description: Optional[str] = None
    trip_id: Optional[str] = None
    created_at: str


# Only what the frontend upload widget actually offers (accept=".pdf,.jpg,
# .jpeg,.png,.gif,.webp" in WalletPage.jsx) - never trust the client's
# Content-Type header for this: an HTML file uploaded with a spoofed
# "image/jpeg" header would otherwise get served back with that same
# spoofed type later, a stored-XSS foothold if anything ever renders it
# inline. The extension used for GridFS's storage path is derived from the
# sniffed type below too, not the client-supplied filename.
_WALLET_MIME_TO_EXT = {
    "image/jpeg": "jpg", "image/png": "png", "image/gif": "gif",
    "image/webp": "webp", "application/pdf": "pdf",
}
_WALLET_PDF_MAGIC = b"%PDF-"
_PILLOW_FORMAT_TO_MIME = {"JPEG": "image/jpeg", "PNG": "image/png", "GIF": "image/gif", "WEBP": "image/webp"}


def _sniff_wallet_content_type(data: bytes) -> Optional[str]:
    """Identify the real file type from its bytes, never the client-supplied
    Content-Type. PDFs are checked by header magic bytes (the same signature
    every PDF reader relies on); images are opened with Pillow, which parses
    real header structure rather than trusting an extension - Image.open()
    already raises for anything that isn't a genuine image of a format it
    knows, and .verify() additionally checks the file isn't truncated/
    corrupt. Returns None (rejected) for anything else, including a
    same-named-but-wrong-content file like an HTML page saved as "x.jpg"."""
    if data.startswith(_WALLET_PDF_MAGIC):
        return "application/pdf"
    try:
        img = Image.open(io.BytesIO(data))
        fmt = img.format
        img.verify()
    except Exception:
        return None
    return _PILLOW_FORMAT_TO_MIME.get(fmt)


@api_router.post("/wallet/upload")
async def upload_wallet_item(
    request: Request,
    file: UploadFile = File(...),
    category: str = "document",
    title: str = "",
    description: str = "",
    trip_id: Optional[str] = None
):
    user = await get_current_user(request)

    data = await file.read()

    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 10MB)")

    content_type = _sniff_wallet_content_type(data)
    if content_type not in _WALLET_MIME_TO_EXT:
        raise HTTPException(
            status_code=415,
            detail="Unsupported file type - only JPEG, PNG, GIF, WEBP images and PDF are accepted",
        )

    storage_path = storage_service.build_path(user.user_id, _WALLET_MIME_TO_EXT[content_type])

    try:
        result = await storage_service.put_object(storage_path, data, content_type)
    except Exception as e:
        logger.error(f"Storage upload error: {e}")
        raise HTTPException(status_code=500, detail="File upload failed")

    item_id = f"wallet_{uuid.uuid4().hex[:12]}"
    item_doc = {
        "item_id": item_id,
        "user_id": user.user_id,
        "file_path": result["path"],
        "original_filename": file.filename,
        "content_type": content_type,
        "size": result.get("size", len(data)),
        "category": category,
        "title": title or file.filename,
        "description": description,
        "trip_id": trip_id,
        "is_deleted": False,
        "created_at": datetime.now(timezone.utc),
    }
    await db.wallet_items.insert_one(item_doc)
    item_doc.pop("_id", None)
    return item_doc


@api_router.get("/wallet")
async def list_wallet_items(request: Request, category: Optional[str] = None, trip_id: Optional[str] = None):
    user = await get_current_user(request)
    
    query = {"user_id": user.user_id, "is_deleted": False}
    if category:
        query["category"] = category
    if trip_id:
        query["trip_id"] = trip_id
    
    items = await db.wallet_items.find(query, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"items": items}


@api_router.get("/wallet/{item_id}/download-url")
async def get_wallet_download_url(item_id: str, request: Request):
    """Mints a short-lived signed download link for this item. Session-
    authenticated (ownership is checked here, once) so the actual download
    route below never needs the session cookie/token at all - it previously
    accepted the raw session_token as a URL query param, which leaks into
    server logs, browser history, and any proxy in the path. The signature
    is scoped to this specific item_id + expiry, so it can't be replayed for
    a different item or after it expires."""
    user = await get_current_user(request)
    item = await db.wallet_items.find_one(
        {"item_id": item_id, "user_id": user.user_id, "is_deleted": False},
        {"_id": 0}
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    expires = int(time.time()) + WALLET_DOWNLOAD_URL_TTL_SECONDS
    signature = _sign_wallet_download(item_id, expires)
    return {"item_id": item_id, "expires": expires, "signature": signature}


@api_router.get("/wallet/{item_id}/download")
async def download_wallet_item(
    item_id: str,
    expires: int = Query(...),
    signature: str = Query(...),
):
    if int(time.time()) > expires:
        raise HTTPException(status_code=401, detail="Download link expired")
    if not hmac.compare_digest(_sign_wallet_download(item_id, expires), signature):
        raise HTTPException(status_code=401, detail="Invalid download link")

    item = await db.wallet_items.find_one(
        {"item_id": item_id, "is_deleted": False},
        {"_id": 0}
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    try:
        data, content_type = await storage_service.get_object(item["file_path"])
    except Exception as e:
        logger.error(f"Storage download error: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve file")

    # attachment (not inline) + nosniff so a mis-classified or since-changed
    # file can never be rendered inline by the browser, even as a
    # defense-in-depth backstop to the upload-time content sniffing above.
    safe_filename = os.path.basename(item["original_filename"]).replace('"', "'").replace("\r", "").replace("\n", "")
    return Response(
        content=data,
        media_type=item.get("content_type", content_type),
        headers={
            "Content-Disposition": f'attachment; filename="{safe_filename}"',
            "X-Content-Type-Options": "nosniff",
        }
    )


@api_router.delete("/wallet/{item_id}")
async def delete_wallet_item(item_id: str, request: Request):
    user = await get_current_user(request)
    result = await db.wallet_items.update_one(
        {"item_id": item_id, "user_id": user.user_id},
        {"$set": {"is_deleted": True, "deleted_at": datetime.now(timezone.utc)}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"message": "Item deleted successfully"}


# ==================== Travel Rewards System ====================

@api_router.get("/rewards")
async def get_rewards(request: Request):
    user = await get_current_user(request)
    return await rewards_service.get_user_rewards_summary(db, user.user_id)


class RedeemPointsRequest(BaseModel):
    points: int
    reference_id: Optional[str] = None


@api_router.post("/rewards/redeem")
async def redeem_rewards(req: RedeemPointsRequest, request: Request):
    user = await get_current_user(request)
    try:
        result = await rewards_service.redeem_points(
            db, user.user_id, req.points, req.reference_id, "Discount applied to booking"
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==================== Stripe Payments ====================

# Fixed packages - amounts defined ONLY on backend. USD is the canonical
# base price; customers are charged in INR, converted at read time via the
# app's live FX rate (services.ignav_service._to_inr) rather than a second
# hardcoded INR number that would drift out of sync with the rate used
# everywhere else. See _get_premium_plans().
#
# "interval" drives the recurring Checkout Session (mode='subscription',
# price_data.recurring.interval) - confirmed against Stripe's current API
# docs that price_data.recurring is valid for subscription-mode Checkout
# Sessions, no pre-created Price object required, consistent with how
# bookings already price everything via inline price_data.
_PREMIUM_PLANS_USD = {
    "monthly": {"name": "EYV Premium Monthly", "amount_usd": 9.99, "interval": "month"},
    "yearly": {"name": "EYV Premium Yearly", "amount_usd": 99.00, "interval": "year"},
}


async def _get_premium_plans() -> Dict[str, Dict[str, Any]]:
    """Premium plans priced in INR, converted from the canonical USD base
    above using the app's live FX rate - no Stripe Price objects are
    involved anywhere in this app (premium and bookings both already use
    dynamic price_data), so there's nothing on the Stripe side to keep in
    sync; this is the sole source of truth for the charged amount."""
    await duffel_service._refresh_rates_if_stale()
    return {
        package_id: {
            "name": plan["name"],
            "amount": duffel_service._to_inr(plan["amount_usd"], "USD"),
            "currency": "inr",
            "interval": plan["interval"],
        }
        for package_id, plan in _PREMIUM_PLANS_USD.items()
    }


class CreateCheckoutRequest(BaseModel):
    package_id: Optional[str] = None  # For premium subscriptions
    booking_id: Optional[str] = None  # For booking payments
    origin_url: str
    use_points: int = 0


class CheckoutStatusRequest(BaseModel):
    session_id: str


def _ensure_stripe_configured():
    if not stripe.api_key:
        raise HTTPException(status_code=500, detail="Stripe not configured")


@api_router.post("/payments/checkout")
async def create_checkout(req: CreateCheckoutRequest, request: Request):
    user = await get_current_user(request)

    # Only ever set >0 in the booking branch below (points redemption isn't
    # offered on subscription checkouts) - defined here, before the
    # package_id/booking_id branch, so it's always bound regardless of
    # which branch runs; referenced later for the refund-on-Stripe-failure
    # path and for tagging the stored transaction.
    points_reserved = 0

    # Determine amount based on backend logic
    if req.package_id:
        # Premium subscription
        premium_plans = await _get_premium_plans()
        if req.package_id not in premium_plans:
            raise HTTPException(status_code=400, detail="Invalid package")
        plan = premium_plans[req.package_id]
        amount = plan['amount']
        currency = plan['currency']
        description = plan['name']
        payment_type = 'subscription'
        metadata = {
            'user_id': user.user_id,
            'package_id': req.package_id,
            'payment_type': payment_type,
        }
    elif req.booking_id:
        # Booking payment
        booking = await db.bookings.find_one(
            {'booking_id': req.booking_id, 'user_id': user.user_id},
            {'_id': 0}
        )
        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found")
        amount = float(booking['total_amount'])
        currency = booking.get('currency', 'usd').lower()
        description = f"Booking {booking['booking_id']}"
        payment_type = 'booking'
        
        # Apply points discount if requested. Reserved atomically right here
        # via rewards_service.reserve_points - not just checked, with the
        # actual deduction deferred to payment success. Two concurrent
        # checkouts against the same balance could previously both pass a
        # check-then-later-deduct race and jointly overspend (both read
        # "sufficient" before either write landed); the filtered $inc inside
        # reserve_points either atomically claims the points or fails
        # cleanly, with no window where both requests observe a stale
        # balance. If this checkout never completes, the reservation is
        # given back - either by _process_expired_payment (Stripe's
        # checkout.session.expired webhook, or the /payments/status poll
        # detecting expiry) or, if neither ever fires,
        # rewards_service.refund_stale_reserved_points's periodic sweep
        # (mirrors services.booking_expiry_service.expire_stale_pending_bookings's
        # own missed-webhook backstop, same STALE_PENDING_TTL).
        if req.use_points > 0:
            # POINTS_TO_USD is a USD-denominated canonical point value ("100
            # points = $1") - it must be converted into the booking's own
            # `currency` before being subtracted from `amount`, which is in
            # that same native currency. Reuses the same FX table already
            # live for real Ignav flight-price INR conversion (duffel_service
            # is services.ignav_service under its historical alias) instead
            # of a second, separate hardcoded rate.
            await duffel_service._refresh_rates_if_stale()
            discount_usd = req.use_points * rewards_service.POINTS_TO_USD
            if currency == 'usd':
                discount = discount_usd
            elif currency == 'inr':
                discount = duffel_service._to_inr(discount_usd, 'USD')
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Points redemption is not supported for currency '{currency}'",
                )
            reserved = await rewards_service.reserve_points(db, user.user_id, req.use_points)
            if not reserved:
                raise HTTPException(status_code=400, detail="Insufficient points")
            points_reserved = req.use_points
            amount = max(0.50, amount - discount)  # Minimum charge $0.50

        metadata = {
            'user_id': user.user_id,
            'booking_id': req.booking_id,
            'payment_type': payment_type,
            'points_used': str(req.use_points),
        }
    else:
        raise HTTPException(status_code=400, detail="Must provide package_id or booking_id")
    
    # Build URLs
    origin = req.origin_url.rstrip('/')
    success_url = f"{origin}/payment-success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{origin}/payment-cancel"
    
    price_data = {
        'currency': currency,
        'product_data': {'name': description},
        'unit_amount': int(round(amount * 100)),
    }

    session_kwargs = dict(
        line_items=[{'price_data': price_data, 'quantity': 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata=metadata,
    )

    if payment_type == 'subscription':
        # Real recurring billing (Problem 2 fix) - price_data.recurring is
        # valid for subscription-mode Checkout Sessions per Stripe's current
        # API (verified against docs.stripe.com/api/checkout/sessions/create
        # rather than assumed), so this still needs no pre-created Stripe
        # Price object, consistent with how bookings already price
        # everything. payment_method_types is deliberately omitted (Stripe
        # best practice for subscription Checkout - hardcoding ['card'] here
        # would block other eligible payment methods Stripe could otherwise
        # offer dynamically). subscription_data.metadata (not just the
        # top-level metadata below) is required so the Subscription object
        # Stripe creates carries user_id/package_id - customer.subscription.*
        # and invoice.* webhook events reference that Subscription/Invoice,
        # never this Checkout Session, so without this they'd have no way
        # to resolve which user they belong to.
        price_data['recurring'] = {'interval': plan['interval']}
        session_kwargs['mode'] = 'subscription'
        session_kwargs['subscription_data'] = {'metadata': metadata}
    else:
        session_kwargs['mode'] = 'payment'
        session_kwargs['payment_method_types'] = ['card']

    _ensure_stripe_configured()
    try:
        session = await asyncio.to_thread(stripe.checkout.Session.create, **session_kwargs)
    except Exception:
        # Points were already reserved above (if any) - a failed Checkout
        # Session means there's no checkout for that reservation to ever be
        # confirmed or expired against, so it must be given back here
        # rather than held indefinitely.
        if points_reserved:
            await rewards_service.refund_points(db, user.user_id, points_reserved)
        raise

    # Store transaction
    transaction = {
        'session_id': session.id,
        'user_id': user.user_id,
        'amount': amount,
        'currency': currency,
        'description': description,
        'payment_type': payment_type,
        'metadata': metadata,
        'payment_status': 'pending',
        'status': 'initiated',
        'points_used': req.use_points,
        'created_at': datetime.now(timezone.utc),
    }
    if points_reserved:
        transaction['points_reservation_status'] = 'reserved'
    await db.payment_transactions.insert_one(transaction)
    
    return {
        'url': session.url,
        'session_id': session.id,
        'amount': amount,
        'currency': currency,
    }


@api_router.get("/payments/status/{session_id}")
async def get_payment_status(session_id: str, request: Request):
    user = await get_current_user(request)
    
    # Find the transaction
    transaction = await db.payment_transactions.find_one(
        {'session_id': session_id, 'user_id': user.user_id},
        {'_id': 0}
    )
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    # If already processed, return immediately (idempotency)
    if transaction['payment_status'] in ('paid', 'failed', 'expired'):
        return {
            'payment_status': transaction['payment_status'],
            'status': transaction['status'],
            'amount': transaction['amount'],
            'currency': transaction['currency'],
            'metadata': transaction['metadata'],
        }
    
    # Poll Stripe
    _ensure_stripe_configured()
    status_response = await asyncio.to_thread(stripe.checkout.Session.retrieve, session_id)

    # Update transaction (idempotent - only process once). The webhook above
    # can be racing this exact request for the same session_id (Stripe fires
    # checkout.session.completed independently of whether/when the frontend
    # happens to poll this endpoint) - a plain read-this-Python-variable-then-
    # write is NOT enough to prevent double-processing (_process_successful_payment
    # awarding points twice, etc.): both requests could read payment_status
    # as still-pending before either one's write lands. The filter on
    # payment_status in the update itself is what makes this atomic - only
    # whichever request's update Mongo actually applies first gets a non-None
    # result back, so only that one calls the (non-idempotent) side effects.
    if status_response.payment_status == 'paid':
        updated = await db.payment_transactions.find_one_and_update(
            {'session_id': session_id, 'payment_status': {'$ne': 'paid'}},
            {'$set': {
                'payment_status': 'paid',
                'status': 'completed',
                'completed_at': datetime.now(timezone.utc),
            }}
        )
        if updated is not None:
            # Trigger post-payment actions
            await _process_successful_payment(transaction)
    elif status_response.status == 'expired':
        updated = await db.payment_transactions.find_one_and_update(
            {'session_id': session_id, 'payment_status': {'$nin': ['paid', 'expired']}},
            {'$set': {'payment_status': 'expired', 'status': 'expired'}}
        )
        if updated is not None:
            await _process_expired_payment(transaction)
    
    return {
        'payment_status': status_response.payment_status,
        'status': status_response.status,
        'amount': status_response.amount_total / 100 if status_response.amount_total else transaction['amount'],
        'currency': status_response.currency or transaction['currency'],
        'metadata': status_response.metadata or transaction['metadata'],
    }


async def _finalize_or_alert_points_redemption(db, transaction: Dict, user_id: str, points_used: int, booking_id: str) -> None:
    """Finalize the points reservation made atomically at checkout
    (create_checkout -> rewards_service.reserve_points). available_points
    was already decremented there, so this must NOT call
    redeem_points/re-deduct - that would spend the balance a second time.
    This only needs to flip the reservation reserved -> finalized (a
    filtered transition, the same shape as the payment_status race fix in
    get_payment_status/stripe_webhook - only whichever caller actually
    flips it proceeds) and record the permanent rewards_transactions audit
    row.

    If the flip fails (the reservation isn't "reserved" anymore - already
    refunded by rewards_service.refund_stale_reserved_points's sweep, or by
    _process_expired_payment on a since-revived Stripe session, either
    possibly racing this very late success), the Stripe charge still
    reflects the points discount but the points are no longer held - a
    real money-losing inconsistency. This used to be a silent
    `except ValueError: pass  # Already validated at checkout` in
    _process_successful_payment, which swallowed exactly this case. Now
    it's logged and sent to Sentry for manual reconciliation instead of
    disappearing - never silently ignored.

    Takes `db` as an explicit parameter (not the module-level `db` global)
    so it can be exercised directly in tests against a freshly-constructed
    Motor client, without going through the full HTTP/Stripe-mocking path
    - see tests/test_rewards_race.py."""
    finalized_txn = await db.payment_transactions.find_one_and_update(
        {'session_id': transaction['session_id'], 'points_reservation_status': 'reserved'},
        {'$set': {'points_reservation_status': 'finalized'}},
    )
    if finalized_txn is None:
        logger.error(
            f"Points reservation for booking {booking_id} (user {user_id}, "
            f"{points_used} points) was not in 'reserved' state at payment "
            f"success - the Stripe charge already reflects the points discount "
            f"but the points are no longer held. Needs manual reconciliation."
        )
        sentry_sdk.capture_exception(
            RuntimeError(f"Points reservation lost before payment success for booking {booking_id}"),
            tags={"area": "rewards_points_finalize"},
        )
    else:
        try:
            await rewards_service.finalize_reserved_points(
                db, user_id, points_used, booking_id, f"Discount on booking {booking_id}"
            )
        except Exception as e:
            logger.error(
                f"Failed to record points-redemption audit row for booking "
                f"{booking_id} (user {user_id}, {points_used} points): {e}"
            )
            sentry_sdk.capture_exception(e, tags={"area": "rewards_points_finalize"})


async def _process_successful_payment(transaction: Dict):
    """Process successful payment - subscription or booking."""
    metadata = transaction.get('metadata', {})
    payment_type = metadata.get('payment_type')
    user_id = metadata.get('user_id') or transaction.get('user_id')
    
    if payment_type == 'subscription':
        # checkout.session.completed for a subscription-mode Checkout
        # Session only ever fires once Stripe has actually collected the
        # first payment (unlike the raw Subscription API, hosted Checkout
        # doesn't complete on an unpaid/incomplete subscription) - so it's
        # safe to award the one-time signup bonus here. Everything about
        # the subscription's *ongoing* state (status, current_period_end,
        # stripe_subscription_id/customer_id) is owned entirely by
        # customer.subscription.created/updated (_sync_subscription_from_stripe)
        # instead of being set here - this event doesn't carry the
        # subscription object at all, and per the state-tracking design,
        # local fields are only ever written from the webhook that is
        # actually authoritative for them.
        package_id = metadata.get('package_id')
        await rewards_service.award_points(
            db, user_id, 'premium_subscription',
            reference_id=transaction['session_id'],
            description=f"Premium {package_id} subscription bonus"
        )
    
    elif payment_type == 'booking':
        booking_id = metadata.get('booking_id')
        points_used = int(metadata.get('points_used', 0))
        
        # Mark booking as paid AND confirmed. Deliberately unconditional on
        # the booking's current status (filtered only by booking_id) - a
        # genuinely successful payment must always win, even if this fires
        # after _process_expired_payment already flipped the same booking to
        # "payment_failed" (e.g. the user's Stripe Checkout tab was still
        # open and they completed payment within Stripe's 24h session
        # window, well after our own much shorter stale-pending TTL gave up
        # on it - see the scheduler in services/booking_expiry_service.py).
        # Money received must never be overridden by a stale-cleanup job.
        booking = await db.bookings.find_one({'booking_id': booking_id}, {'_id': 0})
        if booking:
            await db.bookings.update_one(
                {'booking_id': booking_id},
                {'$set': {
                    'status': 'confirmed',
                    'payment_status': 'paid',
                    'paid_at': datetime.now(timezone.utc),
                }}
            )
            await analytics_service.record_event(
                db, "booking_completed", user_id,
                {
                    "booking_id": booking_id,
                    "trip_id": booking.get("trip_id"),
                    "amount": booking.get("total_amount"),
                    "currency": booking.get("currency"),
                },
            )

            # Finalize the points reservation made atomically at checkout -
            # see _finalize_or_alert_points_redemption's own docstring for
            # why this must never be a silent no-op.
            if points_used > 0:
                await _finalize_or_alert_points_redemption(db, transaction, user_id, points_used, booking_id)
            
            # Award points for the booking. A bundle earns points for each
            # bookable type it actually contains (same as booking a flight
            # and a hotel separately would have) rather than falling into
            # the single-item flight/hotel branch below, which only ever
            # awards one type.
            if booking.get('booking_type') == 'bundle':
                for line_item in booking.get('line_items', []):
                    item_type = line_item.get('type')
                    action = 'booking_flight' if item_type == 'flight' else 'booking_hotel'
                    await rewards_service.award_points(
                        db, user_id, action,
                        reference_id=f"{booking_id}:{item_type}",
                        description=f"Earned for {item_type} in bundled booking"
                    )
            else:
                action = 'booking_flight' if booking.get('booking_type') == 'flight' else 'booking_hotel'
                await rewards_service.award_points(
                    db, user_id, action,
                    reference_id=booking_id,
                    description=f"Earned for {booking.get('booking_type')} booking"
                )


async def _process_expired_payment(transaction: Dict):
    """Process an abandoned/declined checkout whose Stripe session expired
    without completing. Mirrors _process_successful_payment's dispatch
    shape, but only ever moves a booking OUT of "pending_payment" - the
    update filter includes status: "pending_payment" so it can never
    clobber a booking _process_successful_payment already confirmed (that
    write is unconditional and always wins - see the comment there). Called
    from both the checkout.session.expired webhook and the polling
    /payments/status path, same as the success side.

    No-op for premium/subscription checkouts - Problem 2 (real
    subscriptions) is a separate, later effort, and premium access is only
    ever granted on success, never provisionally, so there's no pending
    state to roll back here.

    Also refunds any points reserved at checkout (create_checkout ->
    rewards_service.reserve_points) - filtered reserved -> refunded
    transition on the transaction's own points_reservation_status, the same
    atomic-transition shape as the payment_status race fix above, so this
    can never double-refund a reservation
    rewards_service.refund_stale_reserved_points's periodic sweep already
    caught (or vice versa) - only whichever caller's update actually flips
    the status gets to call refund_points."""
    metadata = transaction.get('metadata', {})
    if metadata.get('payment_type') != 'booking':
        return

    booking_id = metadata.get('booking_id')
    points_used = int(metadata.get('points_used', 0))
    user_id = metadata.get('user_id') or transaction.get('user_id')

    if booking_id:
        result = await db.bookings.update_one(
            {'booking_id': booking_id, 'status': 'pending_payment'},
            {'$set': {
                'status': 'payment_failed',
                'payment_failed_at': datetime.now(timezone.utc),
            }}
        )
        # Only when this call actually made the pending -> payment_failed
        # transition (not a no-op racing an already-confirmed/already-failed
        # booking) - the one explicit abandonment signal this app has, used
        # as the drop-off count for the plan_to_booking -> booking_completed
        # leg of the funnel (see AnalyticsEventDoc's own docstring).
        if result.matched_count > 0:
            await analytics_service.record_event(
                db, "booking_abandoned", user_id, {"booking_id": booking_id},
            )

    if points_used > 0:
        updated = await db.payment_transactions.find_one_and_update(
            {'session_id': transaction['session_id'], 'points_reservation_status': 'reserved'},
            {'$set': {'points_reservation_status': 'refunded'}},
        )
        if updated is not None:
            await rewards_service.refund_points(db, user_id, points_used)


async def _sync_subscription_from_stripe(subscription_obj: Dict):
    """Sync local subscription-state fields from a Stripe Subscription
    object - shared by customer.subscription.created/updated/deleted, since
    a .deleted event's object is itself just a subscription with
    status="canceled" (there's nothing event-specific to branch on; this is
    the one place that ever writes these fields, matching the rest of this
    app's rule that local state is always downstream of Stripe, never
    guessed at). A bare overwrite of the current Stripe-reported values is
    inherently idempotent - unlike the checkout success/expiry paths there
    are no side effects here (no points awarded, nothing granted) that a
    duplicate delivery could double-apply, so no extra "already processed"
    guard is needed.

    current_period_end lives on the subscription's line item, not the
    subscription itself, as of recent Stripe API versions (verified against
    docs.stripe.com/api/subscriptions/object rather than assumed) - reading
    the old top-level field would have silently returned nothing.
    """
    user_id = (subscription_obj.get('metadata') or {}).get('user_id')
    if not user_id:
        logger.warning(
            f"customer.subscription event for {subscription_obj.get('id')} "
            "has no user_id in metadata - cannot sync, skipping"
        )
        return

    update = {
        'stripe_customer_id': subscription_obj.get('customer'),
        'stripe_subscription_id': subscription_obj.get('id'),
        'stripe_subscription_status': subscription_obj.get('status'),
        'cancel_at_period_end': bool(subscription_obj.get('cancel_at_period_end')),
    }
    package_id = (subscription_obj.get('metadata') or {}).get('package_id')
    if package_id:
        update['premium_plan'] = package_id

    items = (subscription_obj.get('items') or {}).get('data') or []
    if items and items[0].get('current_period_end'):
        update['current_period_end'] = datetime.fromtimestamp(
            items[0]['current_period_end'], tz=timezone.utc
        )

    # Set once, the first time this subscription is ever observed active -
    # not overwritten on every sync, so a later past_due/active flap on
    # renewal doesn't reset "member since".
    if subscription_obj.get('status') == 'active':
        existing = await db.users.find_one({'user_id': user_id}, {'_id': 0, 'premium_started_at': 1})
        if not existing or not existing.get('premium_started_at'):
            update['premium_started_at'] = datetime.now(timezone.utc)

    await db.users.update_one({'user_id': user_id}, {'$set': update})


def _resolve_invoice_subscription(invoice_obj: Dict) -> tuple:
    """Returns (user_id, subscription_id) for an invoice.paid/payment_failed
    event. parent.subscription_details is where both the subscription
    reference AND its metadata live as of recent Stripe API versions
    (verified against docs.stripe.com/api/invoices/object - the old flat
    invoice.subscription field is gone). Metadata is preferred when present
    (avoids a DB lookup race against customer.subscription.created for the
    very first invoice on a brand-new subscription); falling back to a
    stripe_subscription_id match covers subscriptions old enough to predate
    Stripe populating this metadata (documented as only present from
    2023-06-29 onward), which isn't a real concern for this app but is a
    one-line safety net.
    """
    sub_details = (invoice_obj.get('parent') or {}).get('subscription_details') or {}
    subscription_id = sub_details.get('subscription')
    user_id = (sub_details.get('metadata') or {}).get('user_id')
    return user_id, subscription_id


@api_router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events."""
    body = await request.body()
    signature = request.headers.get('Stripe-Signature', '')
    webhook_secret = os.environ.get('STRIPE_WEBHOOK_SECRET')

    try:
        _ensure_stripe_configured()
        if not webhook_secret:
            raise HTTPException(status_code=500, detail="Stripe webhook secret not configured")
        event = stripe.Webhook.construct_event(body, signature, webhook_secret)

        if event['type'] == 'checkout.session.completed':
            session_obj = event['data']['object']
            transaction = await db.payment_transactions.find_one(
                {'session_id': session_obj['id']},
                {'_id': 0}
            )
            # Atomic find_one_and_update, not a read-then-write - this can
            # race the /payments/status poll endpoint for the same
            # session_id (Stripe's webhook delivery and the frontend's own
            # poll are entirely independent of each other), and
            # _process_successful_payment's side effects (awarding points,
            # confirming bookings) are not themselves idempotent. Filtering
            # payment_status into the update means only whichever request
            # Mongo actually applies first gets a non-None result and
            # proceeds to the side effects - see the matching comment on
            # get_payment_status.
            if transaction:
                updated = await db.payment_transactions.find_one_and_update(
                    {'session_id': session_obj['id'], 'payment_status': {'$ne': 'paid'}},
                    {'$set': {
                        'payment_status': 'paid',
                        'status': 'completed',
                        'completed_at': datetime.now(timezone.utc),
                    }}
                )
                if updated is not None:
                    await _process_successful_payment(transaction)

        elif event['type'] == 'checkout.session.expired':
            session_obj = event['data']['object']
            transaction = await db.payment_transactions.find_one(
                {'session_id': session_obj['id']},
                {'_id': 0}
            )
            # Same atomic-update reasoning as checkout.session.completed above.
            # Guards against reprocessing on Stripe's at-least-once webhook
            # redelivery, against racing the /payments/status poll endpoint,
            # and against a stray/duplicate expired event ever touching a
            # transaction a (possibly since-arrived) success event already
            # marked paid.
            if transaction:
                updated = await db.payment_transactions.find_one_and_update(
                    {'session_id': session_obj['id'], 'payment_status': {'$nin': ['paid', 'expired']}},
                    {'$set': {'payment_status': 'expired', 'status': 'expired'}}
                )
                if updated is not None:
                    await _process_expired_payment(transaction)

        elif event['type'] in (
            'customer.subscription.created',
            'customer.subscription.updated',
            'customer.subscription.deleted',
        ):
            await _sync_subscription_from_stripe(event['data']['object'])

        elif event['type'] == 'invoice.paid':
            invoice_obj = event['data']['object']
            user_id, subscription_id = _resolve_invoice_subscription(invoice_obj)
            filter_query = {'user_id': user_id} if user_id else (
                {'stripe_subscription_id': subscription_id} if subscription_id else None
            )
            if filter_query:
                # Confirms a successful (renewal or initial) charge - status
                # reflects active/current again even if a previous cycle's
                # invoice.payment_failed had marked this past_due.
                await db.users.update_one(filter_query, {'$set': {'stripe_subscription_status': 'active'}})

        elif event['type'] == 'invoice.payment_failed':
            invoice_obj = event['data']['object']
            user_id, subscription_id = _resolve_invoice_subscription(invoice_obj)
            filter_query = {'user_id': user_id} if user_id else (
                {'stripe_subscription_id': subscription_id} if subscription_id else None
            )
            if filter_query:
                # Grace period starts here - access stays on (is_user_premium
                # treats past_due as active) for as long as Stripe's own
                # Smart Retries keep retrying (~2 weeks by default). No
                # custom timer: whatever Stripe/the Dashboard's configured
                # exhaustion action eventually does (cancel / mark unpaid /
                # leave past_due) arrives as its own
                # customer.subscription.updated/deleted event and is synced
                # by _sync_subscription_from_stripe like any other change.
                await db.users.update_one(filter_query, {'$set': {'stripe_subscription_status': 'past_due'}})

        return {"received": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        sentry_sdk.capture_exception(e, tags={"provider": "stripe"})
        # Return non-2xx so Stripe retries the webhook
        raise HTTPException(status_code=400, detail=f"Webhook processing failed: {str(e)}")


# ==================== Admin: Usage Summary ====================
# Backup signal for eyeballing provider call volume without waiting on a
# provider dashboard alert - NOT a replacement for actually configuring
# spend/quota alarms in the Gemini and SerpApi consoles (that's dashboard-side
# and still needs to be done manually).

@api_router.get("/admin/usage-summary")
async def get_admin_usage_summary(x_admin_key: Optional[str] = Header(default=None)):
    if not ADMIN_API_KEY or x_admin_key != ADMIN_API_KEY:
        raise HTTPException(status_code=403, detail="Not authorized")
    return await usage_service.get_usage_summary(db)


# ==================== Premium Subscription Status ====================

async def _subscription_status_payload(user_id: str) -> Dict[str, Any]:
    """Shared response shape for GET /subscription/status and the cancel/
    resume endpoints below - one definition of what "subscription status"
    means to a client, rather than three near-identical hand-rolled dicts.
    Pure read, no write-back - see the note on the GET endpoint for why."""
    user_doc = await db.users.find_one(
        {'user_id': user_id},
        {
            '_id': 0, 'stripe_subscription_status': 1, 'premium_plan': 1,
            'current_period_end': 1, 'premium_started_at': 1, 'cancel_at_period_end': 1,
        }
    )
    return {
        'is_premium': await is_user_premium(user_id),
        'subscription_status': user_doc.get('stripe_subscription_status') if user_doc else None,
        'premium_plan': user_doc.get('premium_plan') if user_doc else None,
        'current_period_end': user_doc.get('current_period_end') if user_doc else None,
        'cancel_at_period_end': bool(user_doc.get('cancel_at_period_end')) if user_doc else False,
        'available_plans': await _get_premium_plans(),
    }


@api_router.get("/subscription/status")
async def get_subscription_status(request: Request):
    user = await get_current_user(request)
    # Pure read - no write-back here. Under the old design this endpoint
    # self-healed a stale "active" status by computing expiry itself and
    # writing "expired" back on read; that's exactly the app-guessing-at-
    # expiry pattern this rebuild replaces. stripe_subscription_status is
    # only ever current because a webhook (_sync_subscription_from_stripe /
    # invoice.paid / invoice.payment_failed) keeps it that way.
    return await _subscription_status_payload(user.user_id)


@api_router.post("/subscription/cancel")
async def cancel_subscription(request: Request):
    """Cancel-at-period-end, not an immediate cancel - the user keeps
    access through the period they already paid for (product decision).
    Stripe's synchronous response from Subscription.modify is fed straight
    into _sync_subscription_from_stripe (the same function
    customer.subscription.updated uses) so the local cancel_at_period_end
    flag is correct immediately, without waiting on that webhook's round
    trip - it still arrives moments later and just re-syncs the same
    values, harmlessly, since that function is idempotent by construction.
    _sync_subscription_from_stripe stays the only place these fields are
    ever written, whether triggered by a webhook or (as here) directly by
    the user's own request."""
    user = await get_current_user(request)
    user_doc = await db.users.find_one(
        {'user_id': user.user_id},
        {'_id': 0, 'stripe_subscription_id': 1, 'stripe_subscription_status': 1}
    )
    if not user_doc or not user_doc.get('stripe_subscription_id'):
        raise HTTPException(status_code=400, detail="No subscription to cancel")
    if user_doc.get('stripe_subscription_status') not in ('active', 'past_due'):
        raise HTTPException(status_code=400, detail="No active subscription to cancel")

    _ensure_stripe_configured()
    subscription = await asyncio.to_thread(
        stripe.Subscription.modify,
        user_doc['stripe_subscription_id'],
        cancel_at_period_end=True,
    )
    await _sync_subscription_from_stripe(subscription)
    return await _subscription_status_payload(user.user_id)


@api_router.post("/subscription/resume")
async def resume_subscription(request: Request):
    """Undo a pending cancel-at-period-end before the period actually ends
    - standard SaaS UX (a user who clicked cancel and changed their mind
    shouldn't have to resubscribe from scratch through checkout again).
    Only meaningful while cancel_at_period_end is still true and the
    subscription hasn't actually ended yet; once customer.subscription.deleted
    has fired there's nothing left to resume and the user needs a new
    checkout instead."""
    user = await get_current_user(request)
    user_doc = await db.users.find_one(
        {'user_id': user.user_id},
        {'_id': 0, 'stripe_subscription_id': 1, 'stripe_subscription_status': 1, 'cancel_at_period_end': 1}
    )
    if not user_doc or not user_doc.get('stripe_subscription_id'):
        raise HTTPException(status_code=400, detail="No subscription to resume")
    if user_doc.get('stripe_subscription_status') not in ('active', 'past_due'):
        raise HTTPException(status_code=400, detail="Subscription has already ended - start a new one instead")
    if not user_doc.get('cancel_at_period_end'):
        raise HTTPException(status_code=400, detail="Subscription is not scheduled to cancel")

    _ensure_stripe_configured()
    subscription = await asyncio.to_thread(
        stripe.Subscription.modify,
        user_doc['stripe_subscription_id'],
        cancel_at_period_end=False,
    )
    await _sync_subscription_from_stripe(subscription)
    return await _subscription_status_payload(user.user_id)


class CreatePortalSessionRequest(BaseModel):
    return_url: str


@api_router.post("/subscription/portal")
async def create_subscription_portal_session(req: CreatePortalSessionRequest, request: Request):
    """Stripe-hosted Customer Portal session - used for the past_due
    "update payment method" action (Part 5) rather than building custom
    card-update UI. Also lets a user see invoices/payment history for
    free, without any more of our own UI. Requires a portal configuration
    to already exist for this account (Dashboard > Settings > Billing >
    Customer portal, or stripe.billingPortal.Configuration.create) -
    Stripe returns a clear error naming exactly that if none exists yet,
    which this deliberately doesn't paper over by auto-creating one."""
    user = await get_current_user(request)
    user_doc = await db.users.find_one(
        {'user_id': user.user_id}, {'_id': 0, 'stripe_customer_id': 1}
    )
    if not user_doc or not user_doc.get('stripe_customer_id'):
        raise HTTPException(status_code=400, detail="No billing account to manage")

    _ensure_stripe_configured()
    portal_session = await asyncio.to_thread(
        stripe.billing_portal.Session.create,
        customer=user_doc['stripe_customer_id'],
        return_url=req.return_url,
    )
    return {'url': portal_session.url}


# Stale-pending-booking sweep - a safety net for missed/undelivered
# checkout.session.expired webhooks (e.g. the user closing the tab before
# Stripe Checkout even loaded, so no session-level event ever fires; or a
# dropped webhook delivery). See services/booking_expiry_service.py. In-
# process only (no Redis/external broker in this single-process deployment
# - same reasoning as the rate limiter above), so this only runs in
# whichever single worker process is up.
_booking_expiry_scheduler = AsyncIOScheduler()


@app.on_event("startup")
async def startup_event():
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
        # Warm the FX rate cache eagerly so the first real request doesn't
        # pay the fetch latency - _refresh_rates_if_stale() also runs lazily
        # from every conversion call site, so this is a nice-to-have, not
        # load-bearing (a failure here just means the first live call does it).
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
        # Same missed-webhook backstop as the job above, for points
        # reserved at checkout rather than booking status - see
        # rewards_service.refund_stale_reserved_points. Reuses this same
        # scheduler instance rather than a second AsyncIOScheduler (same
        # single-process reasoning noted above the scheduler's definition).
        _booking_expiry_scheduler.add_job(
            rewards_service.refund_stale_reserved_points,
            "interval",
            minutes=10,
            args=[db],
            id="refund_stale_reserved_points",
        )
        # Same missed-cleanup backstop, for trip-plan tiers stuck in
        # status "generating" after a crash/restart mid-generation rather
        # than a missed webhook - see generation_expiry_service. Reuses
        # this same scheduler instance for the same single-process reason
        # noted above the scheduler's definition.
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


app.include_router(api_router)
app.include_router(internal_tickets_router)
app.include_router(internal_analytics_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Added last so it ends up outermost in the middleware stack (Starlette
# wraps in reverse add-order) - the request ID needs to be established
# before anything else touches the request, and the X-Request-ID header
# needs to be the last thing added before the response actually leaves.
app.add_middleware(RequestIDMiddleware)


@app.get("/health")
async def health_check():
    """Deliberately at bare /health, not /api/health - this is what an
    infra layer (Railway healthcheckPath, UptimeRobot) polls, and those
    conventionally expect a stable, unversioned root-level path regardless
    of whatever the app's own API prefix happens to be."""
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
    _booking_expiry_scheduler.shutdown(wait=False)
    client.close()
