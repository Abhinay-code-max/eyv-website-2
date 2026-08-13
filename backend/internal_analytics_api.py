"""
Internal analytics-agent API - /api/internal/analytics/*.

Step A7 (Analytics + Promotions Data): standalone, read-only aggregation
surface over db.analytics_events and db.promotions. Deliberately has NO
dependency on the ticket/support-agent system built in Phase 4
(support_agent_service.py, ticket_dedup_service.py, notification_service.py,
internal_tickets_api.py) - it exists to serve a future, separate analytics
agent (roadmap Step B4), not to extend that one.

Mirrors internal_tickets_api.py's security template exactly rather than
inventing a new one - same four pieces, same reasoning, just re-pointed at
this router's own token/collections/audit log:

  1. Auth: require_analytics_agent_token, a FastAPI dependency attached at
     APIRouter-construction time (`dependencies=[...]`, not per-route) so a
     new route added to `router` below structurally CANNOT skip it.
     Compares via hmac.compare_digest, never `==`. Re-reads
     INTERNAL_ANALYTICS_API_TOKEN from the environment on every single
     request rather than caching it - see
     _current_internal_analytics_api_token's docstring for why.

  2. Scope: this module never imports or queries db.users, db.bookings,
     db.trips, or db.payment_transactions - only db.analytics_events,
     db.promotions, and db.analytics_agent_audit_log. Every metric this
     router serves is derived entirely from AnalyticsEventDoc's own
     metadata (trip_id/booking_id references stored as plain strings, same
     convention as every *_id field in db_models.py) - never a live lookup
     against those other collections.

  3. Rate limiting: reuses this app's existing slowapi Limiter pattern (see
     server.py / internal_tickets_api.py) as its own Limiter instance,
     ANALYTICS_API_RATE_LIMIT (60/min per route, only checked once auth has
     already succeeded) plus AUTH_GATE_RATE_LIMIT (120/min, checked on
     EVERY request inside require_analytics_agent_token itself, auth
     success or failure) - same two-layer reasoning as
     internal_tickets_api.py's own comment on this (a per-route decorator
     alone leaves wrong/no-token requests completely unbounded, since they
     never reach the endpoint function it decorates).

  4. Audit logging: _AuditedAnalyticsRoute (this router's route_class)
     wraps every request - success, auth rejection, validation error,
     unexpected exception - and writes exactly one row to
     db.analytics_agent_audit_log. Structural, not a per-route decorator
     someone could add a new route without.

  5. Routes: GET /funnel (conversion-funnel metrics with drop-off counts),
     GET /promotions (promo redemption stats). Both READ-ONLY - this router
     has no POST/PATCH route anywhere, and none should be added for
     db.promotions until the eventual analytics agent (roadmap Step B4) has
     "months of trustworthy output" behind it, per the roadmap's own words.
"""
import hmac
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Set

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from fastapi.routing import APIRoute
from slowapi import Limiter
from starlette.exceptions import HTTPException as StarletteHTTPException

from db_models import PromotionDoc
from rate_limit_keys import get_bearer_token_key, get_trusted_client_ip

logger = logging.getLogger(__name__)


# ── 1. Auth ──────────────────────────────────────────────────────────────

def _resolve_internal_analytics_api_token() -> str:
    """Reads INTERNAL_ANALYTICS_API_TOKEN from the environment, raising if
    unset. Called once at import time below (hard-fail at process startup,
    same pattern as CORS_ORIGINS/WALLET_URL_SIGNING_SECRET/
    INTERNAL_TICKET_API_TOKEN) AND again on every single request (see
    _current_internal_analytics_api_token) - the startup call only guards
    against "never configured at all"; the per-request call is what
    actually gates each request."""
    token = os.environ.get('INTERNAL_ANALYTICS_API_TOKEN')
    if not token:
        raise RuntimeError(
            "INTERNAL_ANALYTICS_API_TOKEN must be set - it authenticates every "
            "request to /api/internal/analytics/*. Set it in Railway's service "
            "variables for deploys - deliberately NOT in backend/.env (same "
            "reasoning as INTERNAL_TICKET_API_TOKEN: this token must support "
            "instant revocation without a restart, so local dev/tests should "
            "export it directly as a real shell env var instead of relying on "
            "dotenv)."
        )
    return token


# Hard-fail at import time - importing this module (which server.py does
# unconditionally at startup) crashes the process immediately if this was
# never configured.
_resolve_internal_analytics_api_token()


def _current_internal_analytics_api_token() -> str:
    """Deliberately re-reads os.environ on EVERY call rather than caching
    the value - this token must support instant revocation, same reasoning
    as internal_tickets_api.py's _current_internal_ticket_api_token."""
    return _resolve_internal_analytics_api_token()


# ── 3. Rate limiting ─────────────────────────────────────────────────────
# Same numbers and reasoning as internal_tickets_api.py's own
# TICKET_API_RATE_LIMIT/AUTH_GATE_RATE_LIMIT - this router has fewer routes
# (2, vs. tickets' 3) but the same "generous for a legitimate polling
# agent, still bounded well below a runaway loop" tradeoff applies
# identically, so there's no reason to pick different numbers.
ANALYTICS_API_RATE_LIMIT = "60/minute"
# Default key_func (used by AUTH_GATE_RATE_LIMIT below, pre-auth) is
# IP-based; the two routes below override to token-based - see
# rate_limit_keys.py for why each limit needs a different one.
_limiter = Limiter(key_func=get_trusted_client_ip)

AUTH_GATE_RATE_LIMIT = "120/minute"


@_limiter.limit(AUTH_GATE_RATE_LIMIT)
async def _rate_limit_marker(request: Request) -> None:
    """Never actually called - exists only so slowapi's .limit() decorator
    registers AUTH_GATE_RATE_LIMIT under THIS function's name in
    _limiter's internal bookkeeping. See internal_tickets_api.py's own
    _rate_limit_marker for the full explanation of why
    require_analytics_agent_token calls _limiter._check_request_limit(...)
    directly instead of decorating itself."""
    pass  # pragma: no cover - never invoked, see docstring


async def require_analytics_agent_token(request: Request) -> None:
    """The one and only auth gate for /api/internal/analytics/* - attached
    to `router` below via `dependencies=[Depends(require_analytics_agent_token)]`
    at APIRouter-construction time, not as a per-route Depends(...).

    Expects `Authorization: Bearer <token>`, same header convention as
    internal_tickets_api.py's require_ticket_agent_token. Comparison is
    hmac.compare_digest, never `==`."""
    _limiter._check_request_limit(request, _rate_limit_marker, False)

    auth_header = request.headers.get("Authorization", "")
    provided = auth_header[len("Bearer "):] if auth_header.startswith("Bearer ") else ""
    expected = _current_internal_analytics_api_token()
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing internal analytics API token")


# ── 4. Audit logging ─────────────────────────────────────────────────────

def _build_audit_summary(request: Request, status_code: int) -> Dict[str, Any]:
    summary = getattr(request.state, "audit_summary", None)
    if summary is not None:
        return summary
    if status_code in (401, 403):
        return {"auth": "rejected"}
    if status_code == 429:
        return {"rate_limited": True}
    return {"status_code": status_code}


class _AuditedAnalyticsRoute(APIRoute):
    """This router's route_class - every route defined on `router` below is
    automatically wrapped by this, so audit logging is structurally part of
    dispatch. Identical shape to internal_tickets_api.py's
    _AuditedTicketRoute, just writing to db.analytics_agent_audit_log."""

    def get_route_handler(self):
        original_route_handler = super().get_route_handler()

        async def audited_route_handler(request: Request) -> Response:
            status_code = 500
            try:
                response = await original_route_handler(request)
                status_code = response.status_code
                return response
            except StarletteHTTPException as exc:
                status_code = exc.status_code
                raise
            except RequestValidationError:
                status_code = 422
                raise
            except Exception:
                status_code = 500
                raise
            finally:
                try:
                    db = request.app.state.analytics_db
                    await db.analytics_agent_audit_log.insert_one({
                        "timestamp": datetime.now(timezone.utc),
                        "route": request.url.path,
                        "method": request.method,
                        "status_code": status_code,
                        "summary": _build_audit_summary(request, status_code),
                    })
                except Exception as log_exc:
                    logger.error(f"Failed to write analytics-agent audit log entry: {log_exc}")

        return audited_route_handler


# ── 5. Routes ────────────────────────────────────────────────────────────

router = APIRouter(
    prefix="/api/internal/analytics",
    tags=["internal-analytics"],
    dependencies=[Depends(require_analytics_agent_token)],
    route_class=_AuditedAnalyticsRoute,
    include_in_schema=False,
)


# How long a plan is given to turn into a booking before its silence counts
# as a drop-off, for the plan_generated -> plan_to_booking leg of the
# funnel below - there is no explicit "I'm not booking this" signal
# anywhere in this app (unlike the booking_completed leg, which has a real
# one - see FUNNEL leg 2's docstring below), so this leg's drop-off is
# necessarily a judgment call on how long is "long enough to call it". A
# week is long enough that a plan still silent past it is very unlikely to
# convert later, short enough that funnel numbers reflect recent behavior
# rather than perpetually counting every plan generated in the last hour
# as "still deciding".
FUNNEL_DROPOFF_WINDOW_DAYS = 7


async def _distinct_trip_ids_for_event(db, event_type: str) -> Set[str]:
    ids = await db.analytics_events.distinct(
        "metadata.trip_id", {"event_type": event_type, "metadata.trip_id": {"$ne": None}}
    )
    return set(ids)


async def _trip_ids_first_seen_before(db, event_type: str, cutoff: datetime) -> Set[str]:
    """Trip ids whose EARLIEST event of this type happened at or before
    `cutoff` - the comparison runs inside the aggregation pipeline (a
    Mongo-side BSON Date comparison), not in Python after fetching, so it's
    correct regardless of whether Motor hands back naive or aware
    datetimes (same reasoning as booking_expiry_service.py's own
    query-side cutoff comparison)."""
    pipeline = [
        {"$match": {"event_type": event_type, "metadata.trip_id": {"$ne": None}}},
        {"$group": {"_id": "$metadata.trip_id", "first_at": {"$min": "$timestamp"}}},
        {"$match": {"first_at": {"$lte": cutoff}}},
    ]
    return {doc["_id"] async for doc in db.analytics_events.aggregate(pipeline)}


@router.get("/funnel")
@_limiter.limit(ANALYTICS_API_RATE_LIMIT, key_func=get_bearer_token_key)
async def get_conversion_funnel(request: Request) -> Dict[str, Any]:
    """Conversion funnel: plan_generated -> plan_to_booking -> booking_completed,
    with a drop-off count/definition at each transition:

      - plan_generated -> plan_to_booking: no explicit abandonment signal
        exists at this stage (nothing in the app records a user explicitly
        deciding not to book), so drop-off here is time-window based - a
        trip's plan_generated event is at least FUNNEL_DROPOFF_WINDOW_DAYS
        old and still has no plan_to_booking event.

      - plan_to_booking -> booking_completed: an explicit signal DOES exist
        - AnalyticsEventDoc's booking_abandoned event type, fired only when
          a pending booking's Stripe Checkout session actually expired
          unpaid (server.py's _process_expired_payment). Drop-off here is
          that event count directly, not a time-window guess.

    Counted by distinct trip_id (not raw event count) at every stage, so a
    regenerated tier or a since-superseded event never inflates a stage's
    number - see AnalyticsEventDoc's own docstring on why re-firing
    plan_generated for a regenerated tier is safe."""
    db = request.app.state.analytics_db

    plan_generated_ids = await _distinct_trip_ids_for_event(db, "plan_generated")
    plan_to_booking_ids = await _distinct_trip_ids_for_event(db, "plan_to_booking")
    booking_completed_ids = await _distinct_trip_ids_for_event(db, "booking_completed")
    # Only bookings that actually passed through THIS funnel's own
    # plan_to_booking stage count toward its completed stage - a completed
    # booking whose trip somehow never recorded plan_to_booking (shouldn't
    # happen given the instrumented call sites, but this keeps the funnel
    # internally consistent regardless) doesn't inflate this stage.
    completed_from_booked_ids = plan_to_booking_ids & booking_completed_ids

    cutoff = datetime.now(timezone.utc) - timedelta(days=FUNNEL_DROPOFF_WINDOW_DAYS)
    aged_plan_generated_ids = await _trip_ids_first_seen_before(db, "plan_generated", cutoff)
    dropped_after_plan_ids = aged_plan_generated_ids - plan_to_booking_ids

    abandoned_booking_ids = await db.analytics_events.distinct(
        "metadata.booking_id", {"event_type": "booking_abandoned", "metadata.booking_id": {"$ne": None}}
    )

    funnel = [
        {
            "stage": "plan_generated",
            "count": len(plan_generated_ids),
        },
        {
            "stage": "plan_to_booking",
            "count": len(plan_to_booking_ids),
            "drop_off_count": len(dropped_after_plan_ids),
            "drop_off_definition": (
                f"plan generated but no booking created within "
                f"{FUNNEL_DROPOFF_WINDOW_DAYS} days (time-window based - no "
                f"explicit abandonment signal exists at this stage)"
            ),
        },
        {
            "stage": "booking_completed",
            "count": len(completed_from_booked_ids),
            "drop_off_count": len(abandoned_booking_ids),
            "drop_off_definition": (
                "booking's Stripe Checkout session expired unpaid "
                "(explicit signal - server.py's _process_expired_payment)"
            ),
        },
    ]
    request.state.audit_summary = {"funnel_queried": True}
    return {"funnel": funnel, "drop_off_window_days": FUNNEL_DROPOFF_WINDOW_DAYS}


# Fixed cap, not a client-configurable page size - same "low-volume
# internal admin/agent tool" reasoning as internal_tickets_api.py's own
# QUEUE_MAX_RESULTS.
PROMOTIONS_MAX_RESULTS = 200


@router.get("/promotions")
@_limiter.limit(ANALYTICS_API_RATE_LIMIT, key_func=get_bearer_token_key)
async def get_promotion_stats(request: Request) -> Dict[str, Any]:
    """Promo redemption stats, per code: usage (redemption_count) vs.
    usage_cap. Read-only - see this module's own docstring for why no
    write route exists here."""
    db = request.app.state.analytics_db
    cursor = db.promotions.find({}).sort("created_at", -1).limit(PROMOTIONS_MAX_RESULTS)
    raw_docs = await cursor.to_list(PROMOTIONS_MAX_RESULTS)

    promotions = []
    for doc in raw_docs:
        parsed = PromotionDoc(**doc).model_dump(mode="json")
        usage_cap = parsed.get("usage_cap")
        parsed["usage_ratio"] = (parsed["redemption_count"] / usage_cap) if usage_cap else None
        promotions.append(parsed)

    request.state.audit_summary = {"promotions_queried": True, "result_count": len(promotions)}
    return {"promotions": promotions}
