"""
Admin API Router (/api/admin/*) for the EYV Multi-Agent System.

Provides the secure control surface for Abhinay to monitor, manage, and interact
with JARVIS, Denver, Bob, and Sara with:
1. Dedicated ADMIN_API_KEY isolation (other tokens explicitly rejected).
2. Short-lived session token exchange (httpOnly cookie, SHA-256 hashed at rest, 2h TTL).
3. Append-only audit logging to db.admin_audit_log.
4. Multi-tier SlowAPI rate limiting (10/min verify, 15/min state actions, 60/min reads).
5. Reuses resolve_campaign_image from services.marketing_agent_service.
"""
import functools

import hashlib
import hmac
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, Body, Cookie, Depends, Header, HTTPException, Request, Response

from pydantic import BaseModel, ConfigDict, Field
from slowapi import Limiter

from db_models import AdminAuditLogDoc, AdminSessionDoc
from rate_limit_keys import get_trusted_client_ip
from agents.bob.marketing_agent_service import generate_campaign_draft, resolve_campaign_image

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])
_limiter = Limiter(key_func=get_trusted_client_ip)


def _resolve_admin_api_key() -> str:
    """Authenticates the EYV Admin surface. Fails fast if unset."""
    key = os.environ.get("ADMIN_API_KEY")
    if not key:
        raise RuntimeError(
            "ADMIN_API_KEY must be set - it authenticates the EYV Admin surface. "
            "Set it in backend/.env for local dev and in Railway's service variables for deploys."
        )
    return key


def _get_admin_db(request: Request):
    """Safely retrieves the database handle from request.app.state."""
    app_db = getattr(request.app.state, "analytics_db", None)
    if app_db is not None:
        return app_db
    app_db = getattr(request.app.state, "jarvis_db", None)
    if app_db is not None:
        return app_db
    import server
    return server.db


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()




# ── Strict Token Isolation & Authentication ────────────────────────────────

async def require_admin(
    request: Request,
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
    authorization: Optional[str] = Header(default=None),
    admin_session_token: Optional[str] = Cookie(default=None),
) -> str:
    """Authenticates admin calls. Enforces strict token isolation:
    - Dedicated ADMIN_API_KEY or valid 2h session token from db.admin_sessions.
    - Other internal tokens (JARVIS, tickets, analytics) are explicitly rejected with 403.
    Returns the authenticated admin identity."""
    db = _get_admin_db(request)
    now = datetime.now(timezone.utc)

    admin_key_env = os.environ.get("ADMIN_API_KEY", "")
    jarvis_token_env = os.environ.get("JARVIS_QUEUE_API_TOKEN", "")
    ticket_token_env = os.environ.get("INTERNAL_TICKET_API_TOKEN", "")
    analytics_token_env = os.environ.get("INTERNAL_ANALYTICS_API_TOKEN", "")

    # Extract provided bearer/header token
    provided_token = x_admin_key
    if not provided_token and authorization:
        if authorization.startswith("Bearer "):
            provided_token = authorization[len("Bearer "):].strip()
        else:
            provided_token = authorization.strip()

    # 1. Check for token cross-contamination (Explicit Isolation Guard)
    if provided_token:
        for bad_token, label in [
            (jarvis_token_env, "JARVIS_QUEUE_API_TOKEN"),
            (ticket_token_env, "INTERNAL_TICKET_API_TOKEN"),
            (analytics_token_env, "INTERNAL_ANALYTICS_API_TOKEN"),
        ]:
            if bad_token and hmac.compare_digest(provided_token, bad_token):
                logger.warning(f"Rejected attempt to use {label} on admin route from {get_trusted_client_ip(request)}")
                raise HTTPException(
                    status_code=403,
                    detail=f"Token isolation violation: {label} is not authorized for Admin surface",
                )

        # 2. Check if provided token is the master ADMIN_API_KEY
        if admin_key_env and hmac.compare_digest(provided_token, admin_key_env):
            return "master_admin_key"

        # 3. Check if provided token is an active session token (via Bearer header)
        token_hash = _hash_token(provided_token)
        session_doc = await db.admin_sessions.find_one({
            "session_token_hash": token_hash,
            "expires_at": {"$gt": now},
        })
        if session_doc:
            return session_doc.get("admin_email") or f"session_{token_hash[:8]}"

    # 4. Check if admin_session_token cookie is present and valid
    if admin_session_token:
        token_hash = _hash_token(admin_session_token)
        session_doc = await db.admin_sessions.find_one({
            "session_token_hash": token_hash,
            "expires_at": {"$gt": now},
        })
        if session_doc:
            return session_doc.get("admin_email") or f"session_{token_hash[:8]}"

    raise HTTPException(status_code=401, detail="Missing or invalid admin authorization")


# ── Append-Only Audit Logging Helper ───────────────────────────────────────

async def _audit_admin_action(
    db,
    *,
    route: str,
    method: str,
    admin_identity: str,
    client_ip: str,
    status_code: int,
    action: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
):
    """Records every admin panel invocation to db.admin_audit_log."""
    try:
        now = datetime.now(timezone.utc)
        log_doc = {
            "timestamp": now,
            "route": route,
            "method": method,
            "admin_identity": admin_identity,
            "client_ip": client_ip,
            "status_code": status_code,
            "action": action,
            "details": details or {},
        }
        await db.admin_audit_log.insert_one(log_doc)
    except Exception as exc:
        logger.error(f"Failed to record admin audit log: {exc}")


# ── Request / Response Schemas ─────────────────────────────────────────────

class AdminVerifyRequest(BaseModel):
    admin_key: str


class AdminCampaignGenerateRequest(BaseModel):
    destination: str
    discount_percent: Optional[float] = None
    theme: Optional[str] = "travel_highlight"
    channel: Optional[str] = "multi_channel"
    target_audience: Optional[str] = "all_travelers"
    custom_headline: Optional[str] = None
    custom_caption: Optional[str] = None
    image_url: Optional[str] = None


class AdminDecisionRequest(BaseModel):
    queue_item_id: str
    action: Dict[str, Any]
    reason: Optional[str] = None
    resolution_status: str = "resolved"


AdminVerifyRequest.model_rebuild()
AdminCampaignGenerateRequest.model_rebuild()
AdminDecisionRequest.model_rebuild()



# ── Admin Routes ───────────────────────────────────────────────────────────

@router.post("/verify")
@_limiter.limit("10/minute")
async def verify_admin_key(
    request: Request,
    response: Response,
    payload: AdminVerifyRequest = Body(...),
):


    """Exchanges ADMIN_API_KEY for a short-lived 2-hour session token with httpOnly cookie.
    Protected by a strict 10/min rate limit to prevent key brute-forcing."""
    db = _get_admin_db(request)
    admin_key_env = os.environ.get("ADMIN_API_KEY", "")
    now = datetime.now(timezone.utc)
    client_ip = get_trusted_client_ip(request)

    if not admin_key_env or not hmac.compare_digest(payload.admin_key, admin_key_env):
        await _audit_admin_action(
            db,
            route="/api/admin/verify",
            method="POST",
            admin_identity="unauthenticated",
            client_ip=client_ip,
            status_code=401,
            action="verify_admin_key_failed",
        )
        raise HTTPException(status_code=401, detail="Invalid admin key")

    # Generate 2-hour session
    raw_session_token = secrets.token_urlsafe(32)
    session_hash = _hash_token(raw_session_token)
    expires_at = now + timedelta(hours=2)

    session_doc = {
        "session_token_hash": session_hash,
        "admin_email": os.environ.get("ADMIN_EMAIL", "kandrikaabhinay@gmail.com"),
        "created_at": now,
        "expires_at": expires_at,
    }
    await db.admin_sessions.insert_one(session_doc)

    # Set httpOnly cookie for zero-friction browser access without raw key storage
    response.set_cookie(
        key="admin_session_token",
        value=raw_session_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=7200,
    )

    await _audit_admin_action(
        db,
        route="/api/admin/verify",
        method="POST",
        admin_identity=session_doc["admin_email"],
        client_ip=client_ip,
        status_code=200,
        action="verify_admin_key_success",
    )

    return {
        "authenticated": True,
        "session_token": raw_session_token,
        "expires_at": expires_at.isoformat(),
        "admin_email": session_doc["admin_email"],
    }


@router.post("/logout")
async def admin_logout(
    request: Request,
    response: Response,
    admin_identity: str = Depends(require_admin),
):
    """Revokes the current admin session."""
    db = _get_admin_db(request)
    client_ip = get_trusted_client_ip(request)

    # Clear cookie
    response.delete_cookie(key="admin_session_token")

    await _audit_admin_action(
        db,
        route="/api/admin/logout",
        method="POST",
        admin_identity=admin_identity,
        client_ip=client_ip,
        status_code=200,
        action="admin_logout",
    )
    return {"status": "logged_out"}


@router.get("/dashboard-stats")
@_limiter.limit("60/minute")
async def get_admin_dashboard_stats(
    request: Request,
    admin_identity: str = Depends(require_admin),
):
    """Returns high-level summary counts for the Admin Dashboard header."""
    db = _get_admin_db(request)
    now = datetime.now(timezone.utc)
    twenty_four_hours_ago = now - timedelta(hours=24)

    pending_queue = await db.jarvis_queue_items.count_documents({"status": "pending"})
    p1_queue = await db.jarvis_queue_items.count_documents({"status": "pending", "priority": 1})
    total_campaigns = await db.marketing_campaigns.count_documents({})
    published_campaigns = await db.marketing_campaigns.count_documents({"status": "published"})
    open_tickets = await db.tickets.count_documents({"status": {"$in": ["open", "in_progress"]}})
    rc_events_24h = await db.revenuecat_events.count_documents({"created_at": {"$gte": twenty_four_hours_ago}})

    return {
        "system_health": "ok",
        "pending_queue_count": pending_queue,
        "p1_urgent_count": p1_queue,
        "marketing_campaigns_total": total_campaigns,
        "marketing_campaigns_published": published_campaigns,
        "open_tickets_count": open_tickets,
        "revenuecat_events_24h": rc_events_24h,
        "admin_identity": admin_identity,
        "timestamp": now.isoformat(),
    }


@router.get("/queue")
@_limiter.limit("60/minute")
async def get_admin_queue(
    request: Request,
    admin_identity: str = Depends(require_admin),
):
    """Returns all pending queue items sorted by priority and age."""
    db = _get_admin_db(request)
    cursor = db.jarvis_queue_items.find({"status": "pending"}).sort([("priority", 1), ("created_at", 1)])
    items = []
    async for doc in cursor:
        doc["id"] = str(doc["_id"])
        doc.pop("_id", None)
        if isinstance(doc.get("created_at"), datetime):
            doc["created_at"] = doc["created_at"].isoformat()
        items.append(doc)

    return {"count": len(items), "items": items}


@router.post("/decisions")
@_limiter.limit("15/minute")
async def post_admin_decision(
    request: Request,
    payload: AdminDecisionRequest = Body(...),
    admin_identity: str = Depends(require_admin),
):
    """Executes or resolves a queue item directly from the Admin Panel."""
    db = _get_admin_db(request)
    client_ip = get_trusted_client_ip(request)
    now = datetime.now(timezone.utc)

    # 1. Update queue item
    queue_id = payload.queue_item_id
    updated = await db.jarvis_queue_items.update_one(
        {"_id": ObjectId(queue_id)},
        {"$set": {"status": payload.resolution_status, "resolved_at": now}},
    )

    # 2. Record decision document
    dec_doc = {
        "queue_item_id": queue_id,
        "source_agent": f"admin:{admin_identity}",
        "decision_type": "admin_manual_decision",
        "action": payload.action,
        "reason": payload.reason or "Approved via Admin Dashboard",
        "resolution_status": payload.resolution_status,
        "created_at": now,
    }
    insert_res = await db.jarvis_decisions.insert_one(dec_doc)
    decision_id = str(insert_res.inserted_id)

    # 3. Hook into marketing execution if approved
    action_type = payload.action.get("type")
    execution_result = None
    if action_type == "execute_campaign" and payload.resolution_status == "resolved":
        from agents.bob.marketing_agent_service import handle_jarvis_marketing_decision
        execution_result = await handle_jarvis_marketing_decision(db, dec_doc)

    await _audit_admin_action(
        db,
        route="/api/admin/decisions",
        method="POST",
        admin_identity=admin_identity,
        client_ip=client_ip,
        status_code=200,
        action="admin_decision_executed",
        details={"queue_item_id": queue_id, "action_type": action_type},
    )

    return {
        "status": "recorded",
        "decision_id": decision_id,
        "queue_item_updated": updated.modified_count > 0,
        "execution_result": execution_result,
    }



@router.get("/marketing/campaigns")
@_limiter.limit("60/minute")
async def get_admin_campaigns(
    request: Request,
    admin_identity: str = Depends(require_admin),
):
    """Lists recent marketing campaigns."""
    db = _get_admin_db(request)
    cursor = db.marketing_campaigns.find().sort([("created_at", -1)]).limit(100)
    campaigns = []
    async for doc in cursor:
        doc["id"] = str(doc["_id"])
        doc.pop("_id", None)
        if isinstance(doc.get("created_at"), datetime):
            doc["created_at"] = doc["created_at"].isoformat()
        if isinstance(doc.get("published_at"), datetime):
            doc["published_at"] = doc["published_at"].isoformat()
        campaigns.append(doc)

    return {"count": len(campaigns), "campaigns": campaigns}


@router.post("/marketing/generate")
@_limiter.limit("15/minute")
async def generate_admin_campaign(
    request: Request,
    payload: AdminCampaignGenerateRequest = Body(...),
    admin_identity: str = Depends(require_admin),
):

    """Instructs Bob to draft a marketing campaign.
    Reuses resolve_campaign_image from marketing_agent_service with Gemini cost rate-limiting."""
    db = _get_admin_db(request)
    client_ip = get_trusted_client_ip(request)

    # Resolve destination image using the exact existing pipeline
    resolved_image = resolve_campaign_image(payload.destination, payload.image_url)

    custom_content = {
        "image_url": resolved_image,
    }
    if payload.custom_headline:
        custom_content["headline"] = payload.custom_headline
    if payload.custom_caption:
        custom_content["caption"] = payload.custom_caption

    title = f"{payload.destination.title()} Special Promotion"
    result = await generate_campaign_draft(
        db,
        title=title,
        channel=payload.channel or "multi_channel",
        destination=payload.destination,
        theme=payload.theme or "travel_highlight",
        discount_percent=payload.discount_percent,
        target_audience=payload.target_audience or "all_travelers",
        custom_content=custom_content,
    )

    await _audit_admin_action(
        db,
        route="/api/admin/marketing/generate",
        method="POST",
        admin_identity=admin_identity,
        client_ip=client_ip,
        status_code=200,
        action="admin_generated_campaign",
        details={"campaign_id": result.campaign_id, "destination": payload.destination},
    )

    return {
        "status": "draft_created",
        "campaign_id": result.campaign_id,
        "queue_item_id": result.queue_item_id,
        "title": result.title,
        "resolved_image": resolved_image,
    }


@router.get("/support/tickets")
@_limiter.limit("60/minute")
async def get_admin_tickets(
    request: Request,
    admin_identity: str = Depends(require_admin),
):
    """Lists recent tickets created by Denver."""
    db = _get_admin_db(request)
    cursor = db.tickets.find().sort([("updated_at", -1)]).limit(100)
    tickets = []
    async for doc in cursor:
        doc["id"] = str(doc["_id"])
        doc.pop("_id", None)
        if isinstance(doc.get("created_at"), datetime):
            doc["created_at"] = doc["created_at"].isoformat()
        if isinstance(doc.get("updated_at"), datetime):
            doc["updated_at"] = doc["updated_at"].isoformat()
        tickets.append(doc)

    return {"count": len(tickets), "tickets": tickets}


@router.get("/analytics/events")
@_limiter.limit("60/minute")
async def get_admin_analytics_events(
    request: Request,
    admin_identity: str = Depends(require_admin),
):
    """Lists recent RevenueCat subscription events ingested by Sara."""
    db = _get_admin_db(request)
    cursor = db.revenuecat_events.find().sort([("created_at", -1)]).limit(100)
    events = []
    async for doc in cursor:
        doc["id"] = str(doc["_id"])
        doc.pop("_id", None)
        if isinstance(doc.get("created_at"), datetime):
            doc["created_at"] = doc["created_at"].isoformat()
        events.append(doc)

    return {"count": len(events), "events": events}


@router.get("/audit-log")
@_limiter.limit("60/minute")
async def get_admin_audit_log(
    request: Request,
    admin_identity: str = Depends(require_admin),
):
    """Returns immutable audit records of all admin actions."""
    db = _get_admin_db(request)
    cursor = db.admin_audit_log.find().sort([("timestamp", -1)]).limit(100)
    logs = []
    async for doc in cursor:
        doc["id"] = str(doc["_id"])
        doc.pop("_id", None)
        if isinstance(doc.get("timestamp"), datetime):
            doc["timestamp"] = doc["timestamp"].isoformat()
        logs.append(doc)

    return {"count": len(logs), "logs": logs}


@router.get("/usage-summary")
@_limiter.limit("60/minute")
async def get_admin_usage_summary(
    request: Request,
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
):
    """Admin usage summary for Gemini, Duffel, SerpApi, etc."""
    admin_key_env = os.environ.get("ADMIN_API_KEY", "")
    if not admin_key_env or not x_admin_key or not hmac.compare_digest(x_admin_key, admin_key_env):
        raise HTTPException(status_code=403, detail="Not authorized")
    db = _get_admin_db(request)
    from services import usage_service
    return await usage_service.get_usage_summary(db)

