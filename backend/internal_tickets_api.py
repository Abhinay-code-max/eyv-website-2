"""
Internal ticket-agent API - /api/internal/tickets/*.

Everything security-sensitive about this route group lives in this one
file, deliberately, so the whole surface (auth, scope, audit logging, rate
limiting, routes) can be reviewed in a single pass rather than scattered
across server.py:

  1. Auth: require_ticket_agent_token, a FastAPI dependency attached at
     APIRouter-construction time (`dependencies=[...]`, not per-route) so
     a new route added to `router` below structurally CANNOT skip it.
     Compares via hmac.compare_digest, never `==`. Re-reads
     INTERNAL_TICKET_API_TOKEN from the environment on every single
     request rather than caching it in a module-level constant - see
     _current_internal_ticket_api_token's docstring for why (instant
     revocation).

  2. Scope: this module never imports or queries db.users, db.bookings, or
     db.payment_transactions - only db.tickets and db.ticket_agent_audit_log.
     Ticket documents' *_user_ids/linked_chat_sessions fields are returned
     exactly as stored (raw ID strings) - nothing here ever looks them up
     or expands them into hydrated user/chat records. If a future feature
     genuinely needs that, it belongs in a separate, separately-reviewed
     module, not bolted onto this one.

  3. Rate limiting: reuses this app's existing slowapi Limiter (see
     server.py) rather than a new library - see TICKET_API_RATE_LIMIT below
     for the chosen number and why. Two layers: TICKET_API_RATE_LIMIT
     (60/min per route, only ever checked once auth has already succeeded)
     and AUTH_GATE_RATE_LIMIT (120/min, checked on EVERY request inside
     require_ticket_agent_token itself, auth success or failure) - the
     first layer alone left wrong/no-token requests completely unbounded,
     since they never reach the endpoint function it decorates. See
     _rate_limit_marker's docstring for why that fix is a direct
     _check_request_limit() call rather than simply decorating
     require_ticket_agent_token too.

  4. Audit logging: _AuditedTicketRoute (this router's route_class) wraps
     every request - success, auth rejection, validation error, not-found,
     or unexpected exception - and writes exactly one row to
     db.ticket_agent_audit_log. Nothing here can add a route that forgets
     to log itself, because logging isn't a per-route decorator to forget -
     it's structurally part of how this router dispatches every request.
     That collection has no update/delete path anywhere in this app -
     append-only means append-only.

  5. Routes: POST / (create), GET /queue, PATCH /{id}, POST /{id}/notify -
     see each function's docstring below.
"""
import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, field_validator
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.exceptions import HTTPException as StarletteHTTPException

from db_models import TICKET_APPROVAL_STATES, TICKET_STATUSES, TicketDoc

logger = logging.getLogger(__name__)


# ── 1. Auth ──────────────────────────────────────────────────────────────

def _resolve_internal_ticket_api_token() -> str:
    """Reads INTERNAL_TICKET_API_TOKEN from the environment, raising if
    unset. Called once at import time below (hard-fail at process startup,
    same pattern as CORS_ORIGINS/WALLET_URL_SIGNING_SECRET in server.py -
    a route that's supposed to be locked down but silently isn't because
    the env var was never set is a real failure mode) AND again on every
    single request (see _current_internal_ticket_api_token) - the startup
    call only guards against "never configured at all"; the per-request
    call is what actually gates each request."""
    token = os.environ.get('INTERNAL_TICKET_API_TOKEN')
    if not token:
        raise RuntimeError(
            "INTERNAL_TICKET_API_TOKEN must be set - it authenticates every "
            "request to /api/internal/tickets/*. Set it in Railway's service "
            "variables for deploys - deliberately NOT in backend/.env (even "
            "though other secrets in this app use .env for local dev): "
            "unlike those, this token must support instant revocation "
            "without a restart (see _current_internal_ticket_api_token), so "
            "local dev/tests should export it directly as a real shell env "
            "var instead of relying on dotenv."
        )
    return token


# Hard-fail at import time - importing this module (which server.py does
# unconditionally at startup) crashes the process immediately if this was
# never configured, exactly like WALLET_URL_SIGNING_SECRET's own
# `_resolve_wallet_download_secret()` call in server.py.
_resolve_internal_ticket_api_token()


def _current_internal_ticket_api_token() -> str:
    """Deliberately re-reads os.environ on EVERY call rather than caching
    the value in a module-level constant the way every other secret in this
    app does (WALLET_URL_SIGNING_SECRET, ADMIN_API_KEY, ...) - this token
    must support instant revocation: rotating it in the environment
    (a Railway env var update, or a test's monkeypatch.setenv) must
    invalidate the old value on the very next request, not just on the
    next process restart/redeploy. See
    tests/test_internal_tickets_api.py::test_token_rotation_takes_effect_immediately
    for the test that actually proves this, not just a comment claiming it."""
    return _resolve_internal_ticket_api_token()


# ── 3. Rate limiting ─────────────────────────────────────────────────────
# Reuses slowapi (the same library/pattern server.py's own `limiter` already
# uses for /trips/generate etc.), as its own Limiter instance scoped to this
# router - slowapi's per-route `.limit(...)` decorator checks against
# whichever Limiter instance it was called on, independent of any other
# route's limiter, so this doesn't need to share server.py's global
# instance to work correctly or to plug into the app's existing
# RateLimitExceeded exception handler (that handler is registered on the
# exception class itself, not tied to one Limiter instance).
#
# 60/minute, applied identically to all three routes below: generous enough
# for a legitimate polling agent (checking the queue every few seconds is
# comfortably under 60/min) while still bounding a runaway/looping local
# agent well before it could meaningfully hammer production - a script
# polling every 100ms (600/min) gets cut off at 10% of that rate. Keyed by
# IP (get_remote_address), same as server.py's default - there's no
# per-user session concept here, just a single shared service token, so IP
# is the only meaningful axis to key on.
#
# This only ever runs AFTER require_ticket_agent_token has already let a
# request through, though - it decorates the endpoint functions themselves
# (get_ticket_queue/patch_ticket/notify_ticket below), and FastAPI resolves
# router-level Depends() (the auth check) BEFORE calling the endpoint at
# all. A wrong/no-token request never reaches these decorators, so on its
# own this limit does nothing to bound repeated bad-token attempts - see
# AUTH_GATE_RATE_LIMIT immediately below for the check that closes that gap.
TICKET_API_RATE_LIMIT = "60/minute"
_limiter = Limiter(key_func=get_remote_address)

# Bounds EVERY request that reaches require_ticket_agent_token, auth success
# or failure - the fix for the gap above. 120/minute, not 60: this one
# check is shared by all three routes (require_ticket_agent_token is the
# single dependency attached to the whole router, not one per route), so it
# needs headroom for legitimate combined traffic across all three endpoints
# (each already independently capped at 60/min) rather than choking a real
# agent that's, say, polling /queue near its own limit while also making
# occasional PATCH/notify calls in the same window. Still a real ceiling:
# a runaway loop at 600/min is cut to 20% throughput, one at 1000+/min to
# barely over 10%. A brief overlap of a few stale-token failures during a
# token rotation is nowhere near enough requests to matter against a
# 120/minute budget.
AUTH_GATE_RATE_LIMIT = "120/minute"


@_limiter.limit(AUTH_GATE_RATE_LIMIT)
async def _rate_limit_marker(request: Request) -> None:
    """Never actually called - exists only so slowapi's .limit() decorator
    registers AUTH_GATE_RATE_LIMIT under THIS function's name in
    _limiter's internal bookkeeping. require_ticket_agent_token below calls
    _limiter._check_request_limit(request, _rate_limit_marker, False)
    directly instead of decorating itself with @_limiter.limit(...) - that
    would seem like the obvious fix, but slowapi's decorator wrapper sets
    request.state._rate_limiting_complete = True after its own check, and
    that flag is shared across EVERY slowapi check on a given request
    regardless of which Limiter instance set it (confirmed by server.py's
    own comment on its /trips/generate two-decorator stack: "even from a
    different Limiter"). Decorating require_ticket_agent_token directly
    would set that flag the moment auth ran - which is BEFORE the endpoint
    - silently disabling get_ticket_queue/patch_ticket/notify_ticket's own
    @_limiter.limit(TICKET_API_RATE_LIMIT) checks the instant this one ran
    first, on every single request. Calling _check_request_limit directly
    (bypassing the decorator's wrapper entirely) performs the same
    check-and-raise-RateLimitExceeded-if-exceeded behavior without ever
    touching that flag, so the per-route checks below still run normally
    afterward."""
    pass  # pragma: no cover - never invoked, see docstring


async def require_ticket_agent_token(request: Request) -> None:
    """The one and only auth gate for /api/internal/tickets/* - attached to
    `router` below via `dependencies=[Depends(require_ticket_agent_token)]`
    at APIRouter-construction time, not as a per-route Depends(...), so a
    route added to this router later cannot forget it.

    Deliberately narrow and deliberately NOT named something generic like
    `verify_internal_access`: this function (and the token it checks) has
    exactly one purpose - gating this one router - and must never be
    reused to gate anything else. A generic-sounding name is exactly what
    would invite that scope creep later.

    Expects `Authorization: Bearer <token>`, same header convention this
    app's own session tokens already use (see server.py's
    _get_current_session). Comparison is hmac.compare_digest, never `==`
    or `!=` - a naive comparison leaks how many leading characters matched
    via response-time differences."""
    # Runs before the token check below, and before anything about this
    # request's auth outcome is known - see _rate_limit_marker's docstring
    # for why this is a direct _check_request_limit call rather than a
    # decorator on this function. Raises slowapi.errors.RateLimitExceeded
    # (a starlette.exceptions.HTTPException subclass, status 429) once
    # AUTH_GATE_RATE_LIMIT is exceeded - caught and logged like any other
    # HTTPException by _AuditedTicketRoute below.
    _limiter._check_request_limit(request, _rate_limit_marker, False)

    auth_header = request.headers.get("Authorization", "")
    provided = auth_header[len("Bearer "):] if auth_header.startswith("Bearer ") else ""
    expected = _current_internal_ticket_api_token()
    # Always called, unconditionally - never short-circuited on `provided`
    # being empty, so an empty/missing token takes exactly the same code
    # path (and the same constant-time comparison) as a wrong one.
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing internal ticket API token")


# ── 4. Audit logging ─────────────────────────────────────────────────────

def _build_audit_summary(request: Request, status_code: int) -> Dict[str, Any]:
    """Falls back to a generic summary when the route handler itself never
    got far enough to set request.state.audit_summary (auth rejected,
    request failed validation, unexpected exception, ...) - every request
    still gets exactly one meaningful audit row either way."""
    summary = getattr(request.state, "audit_summary", None)
    if summary is not None:
        return summary
    if status_code in (401, 403):
        return {"auth": "rejected"}
    if status_code == 429:
        return {"rate_limited": True}
    return {"status_code": status_code}


class _AuditedTicketRoute(APIRoute):
    """This router's route_class - every route defined on `router` below
    (via @router.get/@router.patch/@router.post) is automatically wrapped
    by this, so audit logging is structurally part of dispatch, not a
    per-route decorator someone could add a new route without."""

    def get_route_handler(self):
        original_route_handler = super().get_route_handler()

        async def audited_route_handler(request: Request) -> Response:
            status_code = 500
            try:
                response = await original_route_handler(request)
                status_code = response.status_code
                return response
            except StarletteHTTPException as exc:
                # Covers fastapi.HTTPException (401/403/404/400/... raised
                # by this module's own code) AND slowapi's RateLimitExceeded
                # (429) - both are starlette.exceptions.HTTPException
                # subclasses.
                status_code = exc.status_code
                raise
            except RequestValidationError:
                status_code = 422
                raise
            except Exception:
                status_code = 500
                raise
            finally:
                # Audit logging must never be able to break the actual
                # request - a Mongo hiccup writing this row shouldn't turn
                # into a 500 for what was otherwise a successful ticket
                # update. Logged via the normal app logger, not silently
                # swallowed.
                try:
                    db = request.app.state.tickets_db
                    await db.ticket_agent_audit_log.insert_one({
                        "timestamp": datetime.now(timezone.utc),
                        "route": request.url.path,
                        "method": request.method,
                        "ticket_id": request.path_params.get("id"),
                        "status_code": status_code,
                        "summary": _build_audit_summary(request, status_code),
                    })
                except Exception as log_exc:
                    logger.error(f"Failed to write ticket-agent audit log entry: {log_exc}")

        return audited_route_handler


# ── 5. Routes ────────────────────────────────────────────────────────────

# include_in_schema=False - FastAPI's auto-generated /docs, /redoc, and
# /openapi.json are public by default (server.py never overrides
# docs_url/openapi_url), and schema visibility isn't gated by a route's own
# auth dependency - anyone hitting /docs would otherwise see this router's
# exact paths, methods, and full request/response field/enum shapes with no
# token required at all. That's not a data leak (no real ticket content is
# in a schema), but there's no reason to advertise an internal-only API's
# existence and shape on a public docs page either.
router = APIRouter(
    prefix="/api/internal/tickets",
    tags=["internal-tickets"],
    dependencies=[Depends(require_ticket_agent_token)],
    route_class=_AuditedTicketRoute,
    include_in_schema=False,
)


def _parse_ticket_object_id(id: str) -> ObjectId:
    try:
        return ObjectId(id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid ticket id")


def _serialize_ticket(raw_doc: Dict[str, Any]) -> Dict[str, Any]:
    """Validates the stored document against TicketDoc (also catches a
    document that's drifted out of the documented shape) and dumps it back
    to a plain JSON-safe dict - TicketDoc's own `id` alias/validator already
    handles turning the raw bson.ObjectId `_id` into a plain str, and
    mode="json" turns every datetime into an ISO string for the response."""
    return TicketDoc(**raw_doc).model_dump(mode="json")


# reporter_user_ids/linked_chat_sessions are the only identity a created
# ticket carries about who/what reported it - both default to empty rather
# than required, since a caller (e.g. an internal service acting on a
# system-detected condition rather than a specific user's report) may not
# always have one or the other. extra="forbid" for the same reason
# TicketPatchRequest uses it below: a typo'd field name should 422, not
# silently no-op.
class TicketCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    description: str
    kind: Literal["bug", "feature"]
    reporter_user_ids: List[str] = Field(default_factory=list)
    linked_chat_sessions: List[str] = Field(default_factory=list)

    @field_validator("title", "description")
    @classmethod
    def _non_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v


@router.post("")
@_limiter.limit(TICKET_API_RATE_LIMIT)
async def create_ticket(body: TicketCreateRequest, request: Request) -> Dict[str, Any]:
    """Creates a new ticket at the start of the reported -> triaged ->
    awaiting_approval -> approved -> implemented -> closed workflow
    (TicketDoc's own docstring) - status="reported", approval="pending".
    first_reported_at/updated_at are both set here, server-side, to the same
    `now` - this endpoint never accepts a client-supplied timestamp for
    either, matching every other *_at field in this app (see db_models.py's
    module docstring: a native datetime constructed here, never a caller's
    string).

    Always creates a brand-new document - deduplicating against an existing
    open ticket for the same issue (rather than filing a duplicate every
    time a caller reports the same thing) is a deliberately separate,
    later piece of work that sits in front of this endpoint, not inside it."""
    db = request.app.state.tickets_db
    now = datetime.now(timezone.utc)
    doc = {
        "title": body.title,
        "description": body.description,
        "kind": body.kind,
        "status": "reported",
        "reporter_user_ids": body.reporter_user_ids,
        "linked_chat_sessions": body.linked_chat_sessions,
        "first_reported_at": now,
        "updated_at": now,
        "agent_plan": None,
        "agent_diff_summary": None,
        "approval": "pending",
        "approval_note": None,
        "implementation_commit": None,
        "notified_user_ids": [],
    }
    result = await db.tickets.insert_one(doc)
    created = await db.tickets.find_one({"_id": result.inserted_id})

    request.state.audit_summary = {"created": True, "kind": body.kind}
    return _serialize_ticket(created)


# Fixed cap, not a client-configurable page size - this is a low-volume
# internal admin/agent tool, not a public paginated API, so a simple fixed
# limit (matching the sort=updated_at-desc index just added) is enough to
# bound a single query's cost without adding real pagination for no current
# need.
QUEUE_MAX_RESULTS = 200


@router.get("/queue")
@_limiter.limit(TICKET_API_RATE_LIMIT)
async def get_ticket_queue(
    request: Request,
    status: Literal[TICKET_STATUSES] = Query(default="reported"),
) -> Dict[str, Any]:
    """List tickets filtered by status, defaulting to "reported" (the
    default triage view - "what's new") rather than requiring the query
    param explicitly. Sorted by updated_at descending (most recently active
    first), capped at QUEUE_MAX_RESULTS."""
    db = request.app.state.tickets_db
    cursor = db.tickets.find({"status": status}).sort("updated_at", -1).limit(QUEUE_MAX_RESULTS)
    raw_docs = await cursor.to_list(QUEUE_MAX_RESULTS)
    tickets = [_serialize_ticket(doc) for doc in raw_docs]
    request.state.audit_summary = {"status_filter": status, "result_count": len(tickets)}
    return {"tickets": tickets, "status_filter": status}


# Only the fields an agent progressing a ticket through its lifecycle
# should ever touch via PATCH - deliberately excludes title/description/
# kind (the reporter's original content, not the agent's to rewrite),
# reporter_user_ids/linked_chat_sessions (set once at creation, not an
# agent edit), and notified_user_ids (its own dedicated /notify route
# below, not a generic field edit). extra="forbid" rejects any other field
# name outright (422) rather than silently ignoring it the way TicketDoc's
# own extra="ignore" would - a PATCH with a typo'd or unexpected field name
# should fail loudly, not silently no-op that field.
class TicketPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Optional[Literal[TICKET_STATUSES]] = None
    agent_plan: Optional[str] = None
    agent_diff_summary: Optional[str] = None
    approval: Optional[Literal[TICKET_APPROVAL_STATES]] = None
    approval_note: Optional[str] = None
    implementation_commit: Optional[str] = None


@router.patch("/{id}")
@_limiter.limit(TICKET_API_RATE_LIMIT)
async def patch_ticket(id: str, body: TicketPatchRequest, request: Request) -> Dict[str, Any]:
    """Partial update - only fields actually present in the request body
    are touched (exclude_unset=True), so omitting a field leaves it
    untouched rather than resetting it to null. Records the real before/
    after diff (not just "something changed") for the audit log."""
    db = request.app.state.tickets_db
    oid = _parse_ticket_object_id(id)

    existing = await db.tickets.find_one({"_id": oid})
    if not existing:
        raise HTTPException(status_code=404, detail="Ticket not found")

    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    diff = {
        field: {"from": existing.get(field), "to": new_value}
        for field, new_value in updates.items()
        if existing.get(field) != new_value
    }

    updates["updated_at"] = datetime.now(timezone.utc)
    await db.tickets.update_one({"_id": oid}, {"$set": updates})
    updated_doc = await db.tickets.find_one({"_id": oid})

    request.state.audit_summary = {"changed_fields": diff}
    return _serialize_ticket(updated_doc)


class TicketNotifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_ids: List[str]

    @field_validator("user_ids")
    @classmethod
    def _non_empty(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("user_ids must not be empty")
        return v


@router.post("/{id}/notify")
@_limiter.limit(TICKET_API_RATE_LIMIT)
async def notify_ticket(id: str, body: TicketNotifyRequest, request: Request) -> Dict[str, Any]:
    """Marks the given user_ids as notified on this ticket - just updates
    notified_user_ids on the document ($addToSet so calling this twice with
    an overlapping list doesn't create duplicates). Actual notification
    delivery (email, push, whatever) is a separate, later concern with no
    existing infrastructure in this app to hook into - not built here."""
    db = request.app.state.tickets_db
    oid = _parse_ticket_object_id(id)

    result = await db.tickets.update_one(
        {"_id": oid},
        {
            "$addToSet": {"notified_user_ids": {"$each": body.user_ids}},
            "$set": {"updated_at": datetime.now(timezone.utc)},
        },
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Ticket not found")

    updated_doc = await db.tickets.find_one({"_id": oid})
    request.state.audit_summary = {"notified_user_ids_added": body.user_ids}
    return _serialize_ticket(updated_doc)
