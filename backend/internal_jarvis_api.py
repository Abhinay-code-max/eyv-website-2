"""
Internal JARVIS-poller API - /jarvis/*.

eyv_poller (a standalone Python service running on the JARVIS laptop, NOT
part of this repo) polls GET /jarvis/queue on a fixed interval with a
dedicated bearer token. Mounted at the bare "/jarvis" prefix (not under
"/api/internal/..." like internal_tickets_api.py/internal_analytics_api.py)
because eyv_poller already exists and already polls that exact path - this
is EYV-side-only work catching up to an already-fixed client contract, not a
free choice of URL shape.

Mirrors internal_tickets_api.py's security template exactly rather than
inventing a new one - same four pieces, same reasoning, just re-pointed at
this router's own token/collections/audit log:

  1. Auth: require_jarvis_queue_token, a FastAPI dependency attached at
     APIRouter-construction time (`dependencies=[...]`, not per-route) so a
     new route added to `router` below structurally CANNOT skip it.
     Compares via hmac.compare_digest, never `==`. Re-reads
     JARVIS_QUEUE_API_TOKEN from the environment on every single request
     rather than caching it - see _current_jarvis_queue_api_token's
     docstring for why. Deliberately a distinct env var/credential from
     INTERNAL_TICKET_API_TOKEN (per B.1's design: JARVIS is a separate
     consumer from the support-agent, with its own revocable token, not a
     shared secret) even though both routers end up reading db.tickets.

  2. Scope: this module never imports or queries db.users, db.bookings, or
     db.payment_transactions - only db.tickets and db.jarvis_agent_audit_log.
     Same discipline as internal_tickets_api.py/internal_analytics_api.py,
     checked the same way (AST-based, not string search - see
     tests/test_internal_jarvis_api.py).

  3. Rate limiting: its own slowapi Limiter instance, same two-layer shape
     as internal_tickets_api.py - JARVIS_QUEUE_API_RATE_LIMIT (60/min, only
     checked once auth has already succeeded) plus AUTH_GATE_RATE_LIMIT
     (120/min, checked on EVERY request inside require_jarvis_queue_token
     itself, auth success or failure) - the fix for wrong/no-token requests
     otherwise being completely unbounded, since they never reach the
     endpoint function decorated with the per-route limit. See
     internal_tickets_api.py's _rate_limit_marker docstring for the full
     explanation of why this is a direct _limiter._check_request_limit(...)
     call rather than a second decorator on require_jarvis_queue_token.

  4. Audit logging: _AuditedJarvisRoute (this router's route_class) wraps
     every request - success, auth rejection, validation error, unexpected
     exception - and writes exactly one row to db.jarvis_agent_audit_log.
     Structural, not a per-route decorator someone could add a new route
     without. Append-only, same as ticket_agent_audit_log/
     analytics_agent_audit_log - no update/delete path exists for it.

  5. Routes: GET /queue only, for now.

═══════════════════ SCHEMA DECISION: GET /jarvis/queue ═══════════════════

This is the one piece B.1 was actually blocked on - eyv_poller's own
schema.py was built as an isolated seam specifically because this hadn't
been decided yet. Decided here, explicitly, rather than silently reusing
internal_tickets_api.py's GET /queue shape as-is:

  SAME underlying collection (db.tickets), DIFFERENT default filter and
  DIFFERENT sort order than internal_tickets_api.py's GET /queue - not a
  distinct "queue" concept/collection of its own. Reusing db.tickets (vs.
  inventing a parallel "jarvis_queue" collection) means a ticket has exactly
  one lifecycle, visible identically to a human triager (via the tickets
  API) and to JARVIS (via this route) - no risk of the two views drifting
  out of sync with each other.

  WHY the default filter differs: internal_tickets_api.py's GET /queue
  defaults to status=["reported"] - the human/support-agent triage view,
  "what's new and needs a look". JARVIS is a downstream consumer that only
  acts AFTER a human has approved a ticket for implementation - polling
  "reported" tickets would hand JARVIS work nobody has actually signed off
  on yet. This route instead defaults to status=["approved"], with
  approval="approved" additionally required unconditionally (not just as
  the default statu - see the query below) - a ticket only ever reaches
  status="approved" via that same approval gate in practice, but the extra
  explicit approval="approved" check makes that invariant load-bearing here
  rather than assumed, since correctness of what JARVIS autonomously acts on
  matters more than defense-in-depth would for a human-facing read.

  Filtering conventions carried over from internal_tickets_api.py, so
  eyv_poller can ask for exactly what it needs:
    - `status`: repeated query param (?status=approved&status=backlog),
      Literal[TICKET_STATUSES], defaults to ["approved"]. Every requested
      status still requires approval="approved" underneath (see above) -
      this can narrow which approved-and-ready tickets come back (e.g. by
      also including approved items parked in "backlog"), it can never be
      used to pull unapproved work by asking for a different status.
    - `kind`: optional exact-match filter, Literal["bug", "feature"] -
      identical semantics to internal_tickets_api.py's own `kind` filter.

  Sort order DIFFERS deliberately: updated_at ASCENDING (oldest-approved-
  first), not descending like internal_tickets_api.py's admin-facing view.
  A human triager wants "what's most recently active" at the top; an
  autonomous agent working through a to-do list wants FIFO - oldest
  approved ticket first - so a ticket approved early doesn't get starved
  behind a stream of newer approvals if JARVIS never gets through the
  whole result set in one poll.

  Pagination: fixed cap (JARVIS_QUEUE_MAX_RESULTS, 200), no cursor - same
  "low-volume internal tool, not a public paginated API" reasoning as
  internal_tickets_api.py's QUEUE_MAX_RESULTS/internal_analytics_api.py's
  PROMOTIONS_MAX_RESULTS.

  Response shape (pinned down for eyv_poller's schema.py):
    {
      "tickets": [
        {
          "id": str,                        # Mongo _id, stringified
          "title": str,
          "description": str,
          "kind": "bug" | "feature",
          "status": str,                     # one of TICKET_STATUSES
          "reporter_user_ids": [str, ...],    # opaque ids, never expanded
          "linked_chat_sessions": [str, ...], # opaque ids, never expanded
          "first_reported_at": str,          # ISO 8601 UTC
          "updated_at": str,                 # ISO 8601 UTC
          "agent_plan": str | null,          # set by the support agent, if any
          "agent_diff_summary": str | null,
          "approval": "approved",            # always "approved" in this response
          "approval_note": str | null,
          "implementation_commit": str | null,
          "notified_user_ids": [str, ...]
        },
        ...
      ],
      "status_filter": [str, ...],  # the effective `status` values requested
      "kind_filter": str | null     # the effective `kind` value requested, if any
    }
  Every ticket field is TicketDoc's full shape (same model
  internal_tickets_api.py serializes with) - not a JARVIS-specific subset -
  so a future field added to TicketDoc shows up here automatically rather
  than needing this route updated in lockstep. `approval` will always read
  "approved" in a response from this route (by construction of the query
  above); it's still included, rather than dropped, so eyv_poller's
  schema.py can validate against the exact same TicketDoc-shaped object
  regardless of which internal API it came from.
"""
import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from fastapi.routing import APIRoute
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.exceptions import HTTPException as StarletteHTTPException

from db_models import TICKET_STATUSES, TicketDoc

logger = logging.getLogger(__name__)


# ── 1. Auth ──────────────────────────────────────────────────────────────

def _resolve_jarvis_queue_api_token() -> str:
    """Reads JARVIS_QUEUE_API_TOKEN from the environment, raising if unset.
    Called once at import time below (hard-fail at process startup, same
    pattern as INTERNAL_TICKET_API_TOKEN/INTERNAL_ANALYTICS_API_TOKEN) AND
    again on every single request (see _current_jarvis_queue_api_token) -
    the startup call only guards against "never configured at all"; the
    per-request call is what actually gates each request."""
    token = os.environ.get('JARVIS_QUEUE_API_TOKEN')
    if not token:
        raise RuntimeError(
            "JARVIS_QUEUE_API_TOKEN must be set - it authenticates every "
            "request to /jarvis/*. Set it in Railway's service variables for "
            "deploys - deliberately NOT in backend/.env (same reasoning as "
            "INTERNAL_TICKET_API_TOKEN: this token must support instant "
            "revocation without a restart, so local dev/tests should export "
            "it directly as a real shell env var instead of relying on "
            "dotenv). This is a distinct credential from "
            "INTERNAL_TICKET_API_TOKEN/INTERNAL_ANALYTICS_API_TOKEN - JARVIS "
            "gets its own token, not a shared one, so it can be individually "
            "rotated/revoked without affecting the other internal APIs. "
            "After generating it here, it gets pasted manually into "
            "eyv_poller's local ~/.jarvis/eyv_poller/queue_token.txt - no "
            "intermediate copies."
        )
    return token


# Hard-fail at import time - importing this module (which server.py does
# unconditionally at startup) crashes the process immediately if this was
# never configured, exactly like INTERNAL_TICKET_API_TOKEN/
# INTERNAL_ANALYTICS_API_TOKEN's own import-time checks.
_resolve_jarvis_queue_api_token()


def _current_jarvis_queue_api_token() -> str:
    """Deliberately re-reads os.environ on EVERY call rather than caching
    the value - this token must support instant revocation, same reasoning
    as internal_tickets_api.py's _current_internal_ticket_api_token."""
    return _resolve_jarvis_queue_api_token()


# ── 3. Rate limiting ─────────────────────────────────────────────────────
# Same numbers and reasoning as internal_tickets_api.py's own
# TICKET_API_RATE_LIMIT/AUTH_GATE_RATE_LIMIT - this router only has one
# route today, but the same "generous for a legitimate polling agent, still
# bounded well below a runaway loop" tradeoff applies identically, so
# there's no reason to pick different numbers, and headroom stays in place
# if a second /jarvis/* route is added later.
JARVIS_QUEUE_API_RATE_LIMIT = "60/minute"
_limiter = Limiter(key_func=get_remote_address)

# Bounds EVERY request that reaches require_jarvis_queue_token, auth success
# or failure - see internal_tickets_api.py's AUTH_GATE_RATE_LIMIT comment
# for the full reasoning (a per-route decorator alone leaves wrong/no-token
# requests completely unbounded, since they never reach the endpoint
# function it decorates).
AUTH_GATE_RATE_LIMIT = "120/minute"


@_limiter.limit(AUTH_GATE_RATE_LIMIT)
async def _rate_limit_marker(request: Request) -> None:
    """Never actually called - exists only so slowapi's .limit() decorator
    registers AUTH_GATE_RATE_LIMIT under THIS function's name in
    _limiter's internal bookkeeping. See internal_tickets_api.py's own
    _rate_limit_marker for the full explanation of why
    require_jarvis_queue_token calls _limiter._check_request_limit(...)
    directly instead of decorating itself."""
    pass  # pragma: no cover - never invoked, see docstring


async def require_jarvis_queue_token(request: Request) -> None:
    """The one and only auth gate for /jarvis/* - attached to `router` below
    via `dependencies=[Depends(require_jarvis_queue_token)]` at
    APIRouter-construction time, not as a per-route Depends(...).

    Expects `Authorization: Bearer <token>`, same header convention as
    internal_tickets_api.py's require_ticket_agent_token. Comparison is
    hmac.compare_digest, never `==`."""
    _limiter._check_request_limit(request, _rate_limit_marker, False)

    auth_header = request.headers.get("Authorization", "")
    provided = auth_header[len("Bearer "):] if auth_header.startswith("Bearer ") else ""
    expected = _current_jarvis_queue_api_token()
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing JARVIS queue API token")


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


class _AuditedJarvisRoute(APIRoute):
    """This router's route_class - every route defined on `router` below is
    automatically wrapped by this, so audit logging is structurally part of
    dispatch. Identical shape to internal_tickets_api.py's
    _AuditedTicketRoute/internal_analytics_api.py's _AuditedAnalyticsRoute,
    just writing to db.jarvis_agent_audit_log."""

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
                # Audit logging must never be able to break the actual
                # response - a Mongo hiccup writing this row shouldn't turn
                # into a 500 for what was otherwise a successful poll.
                try:
                    db = request.app.state.jarvis_db
                    await db.jarvis_agent_audit_log.insert_one({
                        "timestamp": datetime.now(timezone.utc),
                        "route": request.url.path,
                        "method": request.method,
                        "status_code": status_code,
                        "summary": _build_audit_summary(request, status_code),
                    })
                except Exception as log_exc:
                    logger.error(f"Failed to write JARVIS-agent audit log entry: {log_exc}")

        return audited_route_handler


# ── 5. Routes ────────────────────────────────────────────────────────────

# include_in_schema=False - same reasoning as internal_tickets_api.py's own
# router: no reason to advertise an internal-only API's existence/shape on
# the public /docs page just because auto-schema-generation isn't itself
# gated by this router's auth dependency.
router = APIRouter(
    prefix="/jarvis",
    tags=["internal-jarvis"],
    dependencies=[Depends(require_jarvis_queue_token)],
    route_class=_AuditedJarvisRoute,
    include_in_schema=False,
)


def _serialize_ticket(raw_doc: Dict[str, Any]) -> Dict[str, Any]:
    """Same TicketDoc validate-then-dump used by internal_tickets_api.py's
    own _serialize_ticket - duplicated here (rather than imported from that
    module) so this router stays a standalone, separately-reviewable unit,
    same discipline internal_analytics_api.py's module docstring documents
    for why it has no dependency on the ticket/support-agent system."""
    return TicketDoc(**raw_doc).model_dump(mode="json")


# Fixed cap, not a client-configurable page size - same "low-volume internal
# agent tool" reasoning as internal_tickets_api.py's QUEUE_MAX_RESULTS.
JARVIS_QUEUE_MAX_RESULTS = 200


@router.get("/queue")
@_limiter.limit(JARVIS_QUEUE_API_RATE_LIMIT)
async def get_jarvis_queue(
    request: Request,
    status: List[Literal[TICKET_STATUSES]] = Query(default=["approved"]),
    kind: Optional[Literal["bug", "feature"]] = Query(default=None),
) -> Dict[str, Any]:
    """JARVIS's work queue - see this module's own docstring
    ("SCHEMA DECISION") for the full reasoning. Every result unconditionally
    has approval="approved" (JARVIS only ever sees tickets a human has
    signed off on), regardless of which `status` value(s) are requested;
    `status` (defaults to ["approved"]) and `kind` only narrow further
    within that already-approved set. Sorted oldest-approved-first
    (updated_at ascending) so an early approval never gets starved behind a
    stream of newer ones, capped at JARVIS_QUEUE_MAX_RESULTS."""
    db = request.app.state.jarvis_db
    query: Dict[str, Any] = {"status": {"$in": status}, "approval": "approved"}
    if kind is not None:
        query["kind"] = kind
    cursor = db.tickets.find(query).sort("updated_at", 1).limit(JARVIS_QUEUE_MAX_RESULTS)
    raw_docs = await cursor.to_list(JARVIS_QUEUE_MAX_RESULTS)
    tickets = [_serialize_ticket(doc) for doc in raw_docs]
    request.state.audit_summary = {"status_filter": status, "kind_filter": kind, "result_count": len(tickets)}
    return {"tickets": tickets, "status_filter": status, "kind_filter": kind}
