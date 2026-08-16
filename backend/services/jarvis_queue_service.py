"""
JARVIS Queue & Coordination Service - Task A.1 of EYV Agent System.

Provides helper functions for backend sub-agents (Denver/Bob/Sara) to enqueue
work for JARVIS (Claude coordinator brain) and manage approval flows.

Security:
- Approval capability tokens are hashed at rest via SHA-256 (same pattern as user_sessions).
- Approvals have a strict 24-hour expiration TTL (expires_at).
- GET endpoints render a confirmation review page; state mutations only happen on POST.
"""
import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

from bson import ObjectId
from bson.errors import InvalidId

from db_models import (
    JARVIS_APPROVAL_STATUSES,
    JARVIS_QUEUE_STATUSES,
    JarvisApprovalDoc,
    JarvisDecisionDoc,
    JarvisQueueItemDoc,
)
from services.notification_service import EmailClient, get_email_client

logger = logging.getLogger(__name__)

DEFAULT_APPROVAL_TTL_HOURS = 24


def hash_approval_token(raw_token: str) -> str:
    """Computes SHA-256 hex digest of raw approval token for at-rest storage."""
    return hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()


async def enqueue_jarvis_item(
    db,
    *,
    source_agent: str,
    item_type: str,
    payload: Optional[Dict[str, Any]] = None,
    priority: int = 5,
) -> JarvisQueueItemDoc:
    """Inserts a new queue item for JARVIS into db.jarvis_queue_items.
    Priority: 1 (highest/critical) -> 5 (normal) -> 10 (low)."""
    now = datetime.now(timezone.utc)
    item_dict = {
        "source_agent": source_agent,
        "item_type": item_type,
        "payload": payload or {},
        "priority": priority,
        "status": "pending",
        "created_at": now,
        "resolved_at": None,
    }
    result = await db.jarvis_queue_items.insert_one(item_dict)
    item_dict["_id"] = str(result.inserted_id)
    return JarvisQueueItemDoc(**item_dict)


async def resolve_jarvis_item(
    db,
    *,
    item_id: str,
    status: Literal[JARVIS_QUEUE_STATUSES] = "resolved",
) -> Optional[JarvisQueueItemDoc]:
    """Updates a queue item's status and records resolved_at timestamp."""
    try:
        obj_id = ObjectId(item_id)
    except (InvalidId, TypeError):
        return None

    now = datetime.now(timezone.utc)
    updated = await db.jarvis_queue_items.find_one_and_update(
        {"_id": obj_id},
        {"$set": {"status": status, "resolved_at": now}},
        return_document=True,
    )
    if not updated:
        return None
    return JarvisQueueItemDoc(**updated)


async def create_jarvis_approval(
    db,
    *,
    action_type: str,
    title: str,
    description: str,
    payload: Optional[Dict[str, Any]] = None,
    requester_agent: str = "jarvis",
    queue_item_id: Optional[str] = None,
    decision_id: Optional[str] = None,
    ttl_hours: int = DEFAULT_APPROVAL_TTL_HOURS,
    email_client: Optional[EmailClient] = None,
    admin_email: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Tuple[JarvisApprovalDoc, str]:
    """Creates a pending approval record in db.jarvis_approvals with sha256
    token hashing and expiration TTL. Returns (JarvisApprovalDoc, raw_token)."""
    now = datetime.now(timezone.utc)
    raw_token = secrets.token_urlsafe(32)
    token_hash = hash_approval_token(raw_token)
    expires_at = now + timedelta(hours=ttl_hours)

    doc_dict = {
        "queue_item_id": queue_item_id,
        "decision_id": decision_id,
        "action_type": action_type,
        "title": title,
        "description": description,
        "payload": payload or {},
        "requester_agent": requester_agent,
        "approval_token_hash": token_hash,
        "status": "pending",
        "resolution_note": None,
        "created_at": now,
        "expires_at": expires_at,
        "resolved_at": None,
    }
    result = await db.jarvis_approvals.insert_one(doc_dict)
    doc_dict["_id"] = str(result.inserted_id)
    approval = JarvisApprovalDoc(**doc_dict)

    # Fan-out notification (best-effort, failure doesn't fail approval creation)
    try:
        client = email_client or get_email_client()
        target_email = admin_email or os.environ.get("ADMIN_EMAIL") or os.environ.get("ALERT_EMAIL")
        site_url = (base_url or os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/")
        # URL points to the review & confirm page (GET)
        approve_url = f"{site_url}/jarvis/approvals/resolve?token={raw_token}&decision=approved"
        reject_url = f"{site_url}/jarvis/approvals/resolve?token={raw_token}&decision=rejected"

        if target_email:
            subject = f"[JARVIS Approval Required] {title}"
            body = (
                f"JARVIS has requested human sign-off for the following action:\n\n"
                f"Action Type: {action_type}\n"
                f"Requester: {requester_agent}\n"
                f"Title: {title}\n"
                f"Description: {description}\n"
                f"Expires In: {ttl_hours} hours\n\n"
                f"Review & Actions:\n"
                f"Approve: {approve_url}\n"
                f"Reject:  {reject_url}\n\n"
                f"Approval ID: {approval.id}"
            )
            html = (
                f"<h2>JARVIS Approval Required</h2>"
                f"<p><strong>Action Type:</strong> {action_type}</p>"
                f"<p><strong>Requester:</strong> {requester_agent}</p>"
                f"<p><strong>Title:</strong> {title}</p>"
                f"<p><strong>Description:</strong> {description}</p>"
                f"<p><em>Expires at: {expires_at.isoformat()} (24 hours)</em></p>"
                f"<div style='margin-top: 20px;'>"
                f"<a href='{approve_url}' style='background-color:#16a34a;color:white;padding:10px 18px;text-decoration:none;border-radius:6px;margin-right:12px;'>Review & Approve</a>"
                f"<a href='{reject_url}' style='background-color:#dc2626;color:white;padding:10px 18px;text-decoration:none;border-radius:6px;'>Review & Reject</a>"
                f"</div>"
            )
            await client.send(to=target_email, subject=subject, text=body, html=html)
    except Exception as exc:
        logger.error(f"Failed to dispatch approval notification for {approval.id}: {exc}")

    return approval, raw_token


async def get_approval_by_raw_token(db, raw_token: str) -> Optional[JarvisApprovalDoc]:
    """Finds an active, non-expired approval by its raw capability token."""
    if not raw_token or not raw_token.strip():
        return None

    token_hash = hash_approval_token(raw_token)
    doc = await db.jarvis_approvals.find_one({"approval_token_hash": token_hash})
    if not doc:
        return None
    return JarvisApprovalDoc(**doc)


async def resolve_jarvis_approval(
    db,
    *,
    token: str,
    decision: Literal["approved", "rejected"],
    note: Optional[str] = None,
) -> Optional[JarvisApprovalDoc]:
    """Resolves an approval using its raw capability token after verifying
    hash match, pending status, and expiration."""
    if not token or not token.strip():
        return None

    now = datetime.now(timezone.utc)
    token_hash = hash_approval_token(token)
    updated = await db.jarvis_approvals.find_one_and_update(
        {
            "approval_token_hash": token_hash,
            "status": "pending",
            "expires_at": {"$gt": now},
        },
        {"$set": {"status": decision, "resolution_note": note, "resolved_at": now}},
        return_document=True,
    )
    if not updated:
        return None
    return JarvisApprovalDoc(**updated)
