"""
Internal JARVIS-poller & coordination API - /jarvis/*.

Task A.1 of EYV Agent System roadmap:
Communication is laptop-initiated polling only. JARVIS (Claude coordinator brain
running on Abhinay's laptop) polls /jarvis/queue for work enqueued by EYV
backend sub-agents (Denver/Bob/Sara), submits decisions back via
POST /jarvis/decisions, and requests human sign-off via POST /jarvis/approvals.

Mirrors internal_tickets_api.py's security template:
  1. Auth: require_jarvis_queue_token, a FastAPI dependency attached at
     APIRouter-construction time (`dependencies=[...]`, not per-route) so a
     new route added to `router` below structurally CANNOT skip it.
     Compares via hmac.compare_digest, never `==`. Re-reads
     JARVIS_QUEUE_API_TOKEN from the environment on every single request
     rather than caching it. Deliberately a distinct env var/credential from
     INTERNAL_TICKET_API_TOKEN / INTERNAL_ANALYTICS_API_TOKEN.

  2. Scope: this module never imports or queries db.users, db.bookings, or
     db.payment_transactions - only db.jarvis_queue_items, db.jarvis_decisions,
     db.jarvis_approvals, and db.jarvis_agent_audit_log.
     Checked via AST test in tests/test_internal_jarvis_api.py.

  3. Rate limiting: its own slowapi Limiter instance with JARVIS_QUEUE_API_RATE_LIMIT
     (60/min, bearer-token keyed per route) plus AUTH_GATE_RATE_LIMIT
     (120/min, checked on EVERY request inside require_jarvis_queue_token itself,
     pre-auth IP-keyed).

  4. Audit logging: _AuditedJarvisRoute wraps every request and writes exactly
     one row to db.jarvis_agent_audit_log. Append-only.

  5. Security & Idempotency:
     - Approval tokens are stored hashed (SHA-256) at rest with 24-hour expiration TTL.
     - GET /jarvis/approvals/resolve only renders a review & confirmation UI (no state mutation on GET - protects against email link pre-fetchers).
     - Only explicit POST /jarvis/approvals/resolve executes the approval state mutation.
"""
import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, field_validator
from slowapi import Limiter
from starlette.exceptions import HTTPException as StarletteHTTPException

from db_models import (
    JARVIS_APPROVAL_STATUSES,
    JARVIS_QUEUE_STATUSES,
    JarvisApprovalDoc,
    JarvisDecisionDoc,
    JarvisQueueItemDoc,
)
from rate_limit_keys import get_bearer_token_key, get_trusted_client_ip
from services.jarvis_queue_service import (
    create_jarvis_approval,
    get_approval_by_raw_token,
    resolve_jarvis_approval,
)

logger = logging.getLogger(__name__)


# ── 1. Auth ──────────────────────────────────────────────────────────────

def _resolve_jarvis_queue_api_token() -> str:
    """Reads JARVIS_QUEUE_API_TOKEN from the environment, raising if unset.
    Called once at import time (hard-fail at process startup) AND again on
    every single request for instant revocation."""
    token = os.environ.get('JARVIS_QUEUE_API_TOKEN')
    if not token:
        raise RuntimeError(
            "JARVIS_QUEUE_API_TOKEN must be set - it authenticates every "
            "request to /jarvis/*. Set it in Railway's service variables for "
            "deploys. Distinct credential from other internal API tokens."
        )
    return token


# Hard-fail at import time
_resolve_jarvis_queue_api_token()


def _current_jarvis_queue_api_token() -> str:
    """Re-reads os.environ on EVERY call for instant revocation support."""
    return _resolve_jarvis_queue_api_token()


# ── 3. Rate limiting ─────────────────────────────────────────────────────

JARVIS_QUEUE_API_RATE_LIMIT = "60/minute"
AUTH_GATE_RATE_LIMIT = "120/minute"

_limiter = Limiter(key_func=get_trusted_client_ip)


@_limiter.limit(AUTH_GATE_RATE_LIMIT)
async def _rate_limit_marker(request: Request) -> None:
    """Marker function for slowapi auth-gate rate limiting."""
    pass  # pragma: no cover


async def require_jarvis_queue_token(request: Request) -> None:
    """Auth gate for internal /jarvis/* endpoints."""
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
    """Wraps every route on the internal JARVIS router with append-only audit logging."""

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


# ── 5. Router & Request Models ───────────────────────────────────────────

router = APIRouter(
    prefix="/jarvis",
    tags=["internal-jarvis"],
    dependencies=[Depends(require_jarvis_queue_token)],
    route_class=_AuditedJarvisRoute,
    include_in_schema=False,
)

JARVIS_QUEUE_MAX_RESULTS = 200


def _parse_object_id(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail=f"Invalid ID format: {id_str}")


class JarvisQueueItemCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_agent: str
    item_type: str
    payload: Optional[Dict[str, Any]] = None
    priority: int = Field(default=5, ge=1, le=10)

    @field_validator("source_agent", "item_type")
    @classmethod
    def _non_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v.strip()


class JarvisDecisionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    queue_item_id: Optional[str] = None
    source_agent: str = "jarvis"
    decision_type: Optional[str] = None
    action: Optional[Any] = None
    reason: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    details: Optional[Dict[str, Any]] = Field(default_factory=dict)
    resolution_status: Optional[Literal[JARVIS_QUEUE_STATUSES]] = "resolved"


class JarvisApprovalCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    queue_item_id: Optional[str] = None
    decision_id: Optional[str] = None
    action_type: str
    title: str
    description: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    requester_agent: str = "jarvis"

    @field_validator("action_type", "title", "description")
    @classmethod
    def _non_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v.strip()


class JarvisApprovalResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approved", "rejected"]
    note: Optional[str] = None


class JarvisPublicResolvePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    token: str
    decision: Literal["approved", "rejected"]
    note: Optional[str] = None


# ── 6. Endpoints ─────────────────────────────────────────────────────────

@router.get("/queue")
@_limiter.limit(JARVIS_QUEUE_API_RATE_LIMIT, key_func=get_bearer_token_key)
async def get_jarvis_queue(
    request: Request,
    status: List[Literal[JARVIS_QUEUE_STATUSES]] = Query(default=["pending"]),
    source_agent: Optional[str] = Query(default=None),
    item_type: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=JARVIS_QUEUE_MAX_RESULTS),
) -> Dict[str, Any]:
    """JARVIS polls this endpoint for unresolved work items enqueued by
    Denver, Bob, and Sara. Sorted oldest/highest priority first (priority ASC,
    created_at ASC)."""
    db = request.app.state.jarvis_db
    query: Dict[str, Any] = {"status": {"$in": status}}
    if source_agent:
        query["source_agent"] = source_agent
    if item_type:
        query["item_type"] = item_type

    cursor = db.jarvis_queue_items.find(query).sort([("priority", 1), ("created_at", 1)]).limit(limit)
    raw_docs = await cursor.to_list(limit)
    items = [JarvisQueueItemDoc(**doc).model_dump(mode="json") for doc in raw_docs]

    request.state.audit_summary = {
        "status_filter": status,
        "source_agent_filter": source_agent,
        "item_type_filter": item_type,
        "result_count": len(items),
    }
    return {
        "items": items,
        "count": len(items),
        "status_filter": status,
        "source_agent_filter": source_agent,
        "item_type_filter": item_type,
    }


@router.post("/queue")
@_limiter.limit(JARVIS_QUEUE_API_RATE_LIMIT, key_func=get_bearer_token_key)
async def post_jarvis_queue_item(
    request: Request,
    req: JarvisQueueItemCreateRequest,
) -> Dict[str, Any]:
    """Sub-agents (Denver, Bob, Sara) enqueue work items for JARVIS through this endpoint."""
    db = request.app.state.jarvis_db
    from services.jarvis_queue_service import enqueue_jarvis_item
    item = await enqueue_jarvis_item(
        db,
        source_agent=req.source_agent,
        item_type=req.item_type,
        payload=req.payload,
        priority=req.priority,
    )
    request.state.audit_summary = {
        "queue_item_id": item.id,
        "source_agent": req.source_agent,
        "item_type": req.item_type,
        "priority": req.priority,
    }
    return {"item": item.model_dump(mode="json"), "status": "enqueued"}


@router.get("/queue/stats")
@_limiter.limit(JARVIS_QUEUE_API_RATE_LIMIT, key_func=get_bearer_token_key)
async def get_jarvis_queue_stats(request: Request) -> Dict[str, Any]:
    """Summary counts of queue items for /status and /stats operational commands."""
    db = request.app.state.jarvis_db
    pending = await db.jarvis_queue_items.count_documents({"status": "pending"})
    resolved = await db.jarvis_queue_items.count_documents({"status": "resolved"})
    total = await db.jarvis_queue_items.count_documents({})
    request.state.audit_summary = {"pending": pending, "resolved": resolved, "total": total}
    return {"pending": pending, "resolved": resolved, "total": total}


@router.post("/decisions")
@_limiter.limit(JARVIS_QUEUE_API_RATE_LIMIT, key_func=get_bearer_token_key)
async def post_jarvis_decision(
    request: Request,
    req: JarvisDecisionCreateRequest,
) -> Dict[str, Any]:
    """JARVIS / marketing_client.py submits back what it decided. If queue_item_id
    is provided, marks that queue item as resolved (or resolution_status) and sets resolved_at."""
    db = request.app.state.jarvis_db
    queue_item_updated = False
    now = datetime.now(timezone.utc)

    # Determine decision_type if omitted
    decision_type = req.decision_type
    if not decision_type:
        if isinstance(req.action, dict) and "type" in req.action:
            decision_type = str(req.action["type"])
        elif req.reason:
            decision_type = "marketing_action"
        else:
            decision_type = "general"

    if req.queue_item_id:
        try:
            obj_id = ObjectId(req.queue_item_id)
            match_query = {"_id": obj_id}
        except (InvalidId, TypeError):
            match_query = {"$or": [{"_id": req.queue_item_id}, {"id": req.queue_item_id}, {"payload.ticket_id": req.queue_item_id}]}

        existing = await db.jarvis_queue_items.find_one(match_query)
        if existing:
            await db.jarvis_queue_items.update_one(
                {"_id": existing["_id"]},
                {"$set": {"status": req.resolution_status or "resolved", "resolved_at": now}},
            )
            queue_item_updated = True

    decision_dict = {
        "queue_item_id": req.queue_item_id,
        "source_agent": req.source_agent,
        "decision_type": decision_type,
        "action": req.action,
        "reason": req.reason,
        "context": req.context or {},
        "details": req.details or {},
        "created_at": now,
    }
    result = await db.jarvis_decisions.insert_one(decision_dict)
    decision_dict["_id"] = str(result.inserted_id)

    # Trigger marketing agent execution if this decision specifies a marketing action
    try:
        from agents.bob.marketing_agent_service import handle_jarvis_marketing_decision
        await handle_jarvis_marketing_decision(db, decision_dict)
    except Exception as m_exc:
        logger.warning(f"Marketing execution hook error: {m_exc}")

    request.state.audit_summary = {
        "decision_type": decision_type,
        "queue_item_id": req.queue_item_id,
        "queue_item_updated": queue_item_updated,
    }
    return {
        "decision": JarvisDecisionDoc(**decision_dict).model_dump(mode="json"),
        "queue_item_updated": queue_item_updated,
        "status": "recorded",
    }




@router.post("/approvals")
@_limiter.limit(JARVIS_QUEUE_API_RATE_LIMIT, key_func=get_bearer_token_key)
async def post_jarvis_approval(
    request: Request,
    req: JarvisApprovalCreateRequest,
) -> Dict[str, Any]:
    """JARVIS creates a pending approval record requiring human sign-off.
    Generates capability token (hashed at rest with 24h TTL) and triggers notification."""
    db = request.app.state.jarvis_db
    approval, raw_token = await create_jarvis_approval(
        db,
        action_type=req.action_type,
        title=req.title,
        description=req.description,
        payload=req.payload,
        requester_agent=req.requester_agent,
        queue_item_id=req.queue_item_id,
        decision_id=req.decision_id,
    )
    request.state.audit_summary = {
        "approval_id": approval.id,
        "action_type": req.action_type,
        "title": req.title,
    }
    return {
        "approval": approval.model_dump(mode="json"),
        "approval_token": raw_token,
    }


@router.get("/approvals/{id}")
@_limiter.limit(JARVIS_QUEUE_API_RATE_LIMIT, key_func=get_bearer_token_key)
async def get_jarvis_approval(
    request: Request,
    id: str,
) -> Dict[str, Any]:
    """JARVIS polls this endpoint to check if an approval has been resolved."""
    db = request.app.state.jarvis_db
    obj_id = _parse_object_id(id)
    doc = await db.jarvis_approvals.find_one({"_id": obj_id})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Approval {id} not found")

    approval_data = JarvisApprovalDoc(**doc).model_dump(mode="json")
    request.state.audit_summary = {
        "approval_id": id,
        "status": approval_data["status"],
    }
    return {"approval": approval_data}


@router.post("/approvals/{id}/resolve")
@_limiter.limit(JARVIS_QUEUE_API_RATE_LIMIT, key_func=get_bearer_token_key)
async def post_resolve_jarvis_approval_internal(
    request: Request,
    id: str,
    req: JarvisApprovalResolveRequest,
) -> Dict[str, Any]:
    """Internal/admin endpoint to resolve an approval via API."""
    db = request.app.state.jarvis_db
    obj_id = _parse_object_id(id)
    now = datetime.now(timezone.utc)
    updated = await db.jarvis_approvals.find_one_and_update(
        {"_id": obj_id, "status": "pending"},
        {"$set": {"status": req.decision, "resolution_note": req.note, "resolved_at": now}},
        return_document=True,
    )
    if not updated:
        doc = await db.jarvis_approvals.find_one({"_id": obj_id})
        if not doc:
            raise HTTPException(status_code=404, detail=f"Approval {id} not found")
        raise HTTPException(status_code=409, detail=f"Approval {id} is already {doc['status']}")

    approval_data = JarvisApprovalDoc(**updated).model_dump(mode="json")
    request.state.audit_summary = {
        "approval_id": id,
        "decision": req.decision,
    }
    return {"approval": approval_data, "status": "resolved"}


# ── 7. Public Capability-Token Resolution Router ─────────────────────────

public_router = APIRouter(
    prefix="/jarvis/approvals",
    tags=["internal-jarvis-public"],
    include_in_schema=False,
)


@public_router.get("/resolve", response_class=HTMLResponse)
async def review_approval_one_click(
    request: Request,
    token: str = Query(...),
    decision: Literal["approved", "rejected"] = Query(default="approved"),
    note: Optional[str] = Query(default=None),
) -> HTMLResponse:
    """Renders a confirmation review page without mutating database state.
    Protects against automated email link pre-fetchers and scanners."""
    db = request.app.state.jarvis_db
    approval = await get_approval_by_raw_token(db, token)
    if not approval:
        return HTMLResponse(
            status_code=400,
            content="""<!DOCTYPE html>
<html>
<head><title>Invalid Link</title><style>body{font-family:sans-serif;padding:40px;text-align:center;background:#0f172a;color:#f8fafc;}</style></head>
<body><h2>Link Expired or Invalid</h2><p>This approval link is invalid, expired (24h TTL), or already resolved.</p></body>
</html>""",
        )

    if approval.status != "pending":
        return HTMLResponse(
            status_code=200,
            content=f"""<!DOCTYPE html>
<html>
<head><title>Already Resolved</title><style>body{{font-family:sans-serif;padding:40px;text-align:center;background:#0f172a;color:#f8fafc;}}</style></head>
<body><h2>Approval Already {approval.status.upper()}</h2><p>This request was previously resolved at {approval.resolved_at}.</p></body>
</html>""",
        )

    action_color = "#16a34a" if decision == "approved" else "#dc2626"
    action_name = "Approve Action" if decision == "approved" else "Reject Action"

    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Confirm JARVIS Action</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; }}
        .card {{ background: #1e293b; border-radius: 12px; padding: 32px; max-width: 520px; width: 100%; box-shadow: 0 10px 25px rgba(0,0,0,0.5); border: 1px solid #334155; }}
        h2 {{ margin-top: 0; color: #38bdf8; }}
        .meta {{ background: #0f172a; border-radius: 8px; padding: 16px; margin: 20px 0; border: 1px solid #334155; font-size: 14px; }}
        .meta p {{ margin: 6px 0; }}
        .btn {{ display: block; width: 100%; background: {action_color}; color: white; border: none; padding: 14px; border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer; transition: opacity 0.2s; }}
        .btn:hover {{ opacity: 0.9; }}
        .input-note {{ width: 100%; box-sizing: border-box; background: #0f172a; border: 1px solid #334155; color: white; padding: 10px; border-radius: 6px; margin-bottom: 16px; }}
    </style>
</head>
<body>
    <div class="card">
        <h2>Confirm JARVIS Sign-Off</h2>
        <div class="meta">
            <p><strong>Action:</strong> {approval.action_type}</p>
            <p><strong>Requester:</strong> {approval.requester_agent}</p>
            <p><strong>Title:</strong> {approval.title}</p>
            <p><strong>Description:</strong> {approval.description}</p>
            <p><strong>Decision:</strong> <span style="color:{action_color};font-weight:bold;">{decision.upper()}</span></p>
        </div>
        <form method="POST" action="/jarvis/approvals/resolve">
            <input type="hidden" name="token" value="{token}">
            <input type="hidden" name="decision" value="{decision}">
            <label style="font-size:13px;color:#94a3b8;display:block;margin-bottom:6px;">Optional Note:</label>
            <input type="text" name="note" class="input-note" placeholder="e.g. Approved after reviewing test metrics" value="{note or ''}">
            <button type="submit" class="btn">{action_name}</button>
        </form>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html_content)


@public_router.post("/resolve")
async def execute_approval_resolution(
    request: Request,
    token: Optional[str] = Form(default=None),
    decision: Optional[Literal["approved", "rejected"]] = Form(default=None),
    note: Optional[str] = Form(default=None),
) -> Response:
    """Executes the state mutation for approval resolution. Supports both Form-POST
    from the review page and JSON payload from API callers."""
    db = request.app.state.jarvis_db

    # Handle JSON payload fallback if not sent as form
    if not token or not decision:
        try:
            body = await request.json()
            token = body.get("token")
            decision = body.get("decision")
            note = body.get("note")
        except Exception:
            pass

    if not token or not decision:
        raise HTTPException(status_code=400, detail="Missing token or decision")

    resolved = await resolve_jarvis_approval(db, token=token, decision=decision, note=note)
    if not resolved:
        raise HTTPException(status_code=400, detail="Invalid, expired (24h TTL), or already resolved approval token")

    # If browser submitted HTML form, return a clean HTML success page
    if "text/html" in request.headers.get("accept", ""):
        color = "#16a34a" if decision == "approved" else "#dc2626"
        return HTMLResponse(content=f"""<!DOCTYPE html>
<html>
<head>
    <title>Decision Recorded</title>
    <style>body{{font-family:sans-serif;padding:40px;text-align:center;background:#0f172a;color:#f8fafc;}} .badge{{color:{color};font-weight:bold;font-size:20px;}}</style>
</head>
<body>
    <h2>Action Sign-Off Recorded</h2>
    <p class="badge">Status: {decision.upper()}</p>
    <p>Approval ID: {resolved.id}</p>
    <p>Resolved At: {resolved.resolved_at.isoformat() if resolved.resolved_at else ''}</p>
</body>
</html>""")

    return Response(
        content=JarvisApprovalDoc(**resolved.model_dump()).model_dump_json(),
        media_type="application/json",
    )
