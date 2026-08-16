"""
Tests for Admin API (/api/admin/*) - Multi-Agent Dashboard Control Surface.
Verifies token isolation, session token exchange, SHA-256 hashing at rest,
append-only audit logging, multi-tier rate limiting, and campaign execution.
"""
from __future__ import annotations

import ast
import asyncio
import hashlib
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ["CORS_ORIGINS"] = "http://localhost:3000"
os.environ["WALLET_URL_SIGNING_SECRET"] = "test-wallet-secret"
os.environ["INTERNAL_TICKET_API_TOKEN"] = "test-ticket-token"
os.environ["INTERNAL_ANALYTICS_API_TOKEN"] = "test-analytics-token"
os.environ["JARVIS_QUEUE_API_TOKEN"] = "test-jarvis-queue-token"
os.environ["ADMIN_API_KEY"] = "test-master-admin-key-secret"
os.environ["REVENUECAT_WEBHOOK_AUTH_KEY"] = "test-revenuecat-secret-key"
os.environ["ADMIN_EMAIL"] = "kandrikaabhinay@gmail.com"
os.environ["MONGO_URL"] = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
os.environ["DB_NAME"] = os.environ.get("DB_NAME", "test_database")

from conftest import client  # noqa: E402,F401
from admin_api import _resolve_admin_api_key, _limiter

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")
ADMIN_HEADERS = {"X-Admin-Key": "test-master-admin-key-secret"}


def _db():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def cleanup_admin_test_records():
    """Wipes test admin sessions and audit logs between tests."""
    async def _clean():
        db = _db()
        await db.admin_sessions.delete_many({})
    _run(_clean())
    try:
        _limiter._storage.reset()
    except Exception:
        pass
    yield
    _run(_clean())
    try:
        _limiter._storage.reset()
    except Exception:
        pass


# ═══════════════ 1. AST Scope Isolation ═══════════════

def test_admin_api_never_directly_writes_forbidden_collections():
    """AST check ensuring admin_api.py never directly writes to users, bookings, or payments."""
    service_path = BACKEND_DIR / "admin_api.py"
    source = service_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    forbidden_writes = {"users", "bookings", "payment_transactions", "refunds"}
    accessed = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if node.attr in forbidden_writes:
                accessed.add(node.attr)

    assert not accessed, f"admin_api.py violates scope discipline: accessed {accessed}"


# ═══════════════ 2. Token Isolation & Startup Fail-Fast ═══════════════

def test_startup_hard_fails_if_admin_api_key_is_missing(monkeypatch):
    """Server startup must hard-fail if ADMIN_API_KEY is not configured."""
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ADMIN_API_KEY must be set"):
        _resolve_admin_api_key()


def test_unauthenticated_admin_call_returns_401(client):
    r = client.get("/api/admin/dashboard-stats")
    assert r.status_code == 401
    assert "Missing or invalid admin authorization" in r.text


def test_jarvis_token_rejected_on_admin_route_403(client):
    """JARVIS_QUEUE_API_TOKEN must NEVER grant access to Admin surface."""
    r = client.get(
        "/api/admin/dashboard-stats",
        headers={"Authorization": "Bearer test-jarvis-queue-token"},
    )
    assert r.status_code == 403
    assert "Token isolation violation" in r.text
    assert "JARVIS_QUEUE_API_TOKEN" in r.text


def test_ticket_agent_token_rejected_on_admin_route_403(client):
    """INTERNAL_TICKET_API_TOKEN must NEVER grant access to Admin surface."""
    r = client.get(
        "/api/admin/dashboard-stats",
        headers={"X-Admin-Key": "test-ticket-token"},
    )
    assert r.status_code == 403
    assert "Token isolation violation" in r.text


# ═══════════════ 3. Session Token Exchange & Hashing at Rest ═══════════════

def test_verify_exchanges_key_for_hashed_session_cookie(client):
    """POST /api/admin/verify validates key, sets httpOnly cookie, and stores SHA-256 hash."""
    payload = {"admin_key": "test-master-admin-key-secret"}
    r = client.post("/api/admin/verify", json=payload)
    assert r.status_code == 200, f"Got {r.status_code}: {r.text}"
    data = r.json()

    assert data["authenticated"] is True
    raw_session_token = data["session_token"]
    assert raw_session_token is not None

    # Check cookie
    assert "admin_session_token" in r.cookies
    assert r.cookies["admin_session_token"] == raw_session_token

    # Verify document in db.admin_sessions
    async def _check():
        db = _db()
        expected_hash = hashlib.sha256(raw_session_token.encode("utf-8")).hexdigest()
        session_doc = await db.admin_sessions.find_one({"session_token_hash": expected_hash})
        assert session_doc is not None
        assert "session_token" not in session_doc  # Raw token NEVER in DB
        assert session_doc["admin_email"] == "kandrikaabhinay@gmail.com"
        assert session_doc["expires_at"] > session_doc["created_at"]
    _run(_check())


def test_session_cookie_authenticates_admin_routes(client):
    # 1. Login
    r_login = client.post("/api/admin/verify", json={"admin_key": "test-master-admin-key-secret"})
    assert r_login.status_code == 200
    session_token = r_login.json()["session_token"]

    # 2. Access dashboard using cookie
    client.cookies.set("admin_session_token", session_token)
    r_stats = client.get("/api/admin/dashboard-stats")
    assert r_stats.status_code == 200
    stats_data = r_stats.json()
    assert stats_data["system_health"] == "ok"
    assert stats_data["admin_identity"] == "kandrikaabhinay@gmail.com"

    # 3. Logout
    r_logout = client.post("/api/admin/logout")
    assert r_logout.status_code == 200

    client.cookies.delete("admin_session_token")


# ═══════════════ 4. Append-Only Audit Logging ═══════════════

def test_admin_actions_are_recorded_in_audit_log(client):
    """Every admin call creates an immutable entry in db.admin_audit_log."""
    async def _test():
        db = _db()
        await db.admin_audit_log.delete_many({})

        # Perform admin call
        r = client.get("/api/admin/dashboard-stats", headers=ADMIN_HEADERS)
        assert r.status_code == 200

        # Also trigger a campaign generation via admin
        r_gen = client.post(
            "/api/admin/marketing/generate",
            json={"destination": "Goa", "discount_percent": 15.0},
            headers=ADMIN_HEADERS,
        )
        assert r_gen.status_code == 200

        # Query audit log
        logs = await db.admin_audit_log.find().sort([("timestamp", -1)]).to_list(10)
        assert len(logs) >= 1
        actions = [l.get("action") for l in logs]
        assert "admin_generated_campaign" in actions

        # Cleanup
        camp_id = r_gen.json()["campaign_id"]
        q_id = r_gen.json()["queue_item_id"]
        await db.marketing_campaigns.delete_one({"_id": ObjectId(camp_id)})
        if q_id:
            await db.jarvis_queue_items.delete_one({"_id": ObjectId(q_id)})

    _run(_test())


# ═══════════════ 5. Closed-Loop Campaign Creation & Decision Execution ═══════════════

def test_admin_generate_and_approve_campaign_pipeline(client, monkeypatch):
    """Full loop: Admin creates campaign via Bob -> Approves via Admin API -> Campaign published."""
    monkeypatch.setenv("BUFFER_SANDBOX_MODE", "true")
    async def _test():
        db = _db()


        # 1. Admin generates campaign draft
        r_gen = client.post(
            "/api/admin/marketing/generate",
            json={
                "destination": "Kerala",
                "discount_percent": 20.0,
                "theme": "monsoon_retreat",
                "channel": "buffer",
            },
            headers=ADMIN_HEADERS,
        )
        assert r_gen.status_code == 200
        gen_data = r_gen.json()
        campaign_id = gen_data["campaign_id"]
        queue_id = gen_data["queue_item_id"]

        # Confirm destination image resolved from marketing_agent_service pipeline
        assert gen_data["resolved_image"] == "https://enjoyyourvacation.in/images/destinations/kerala.jpg"

        # 2. View in Admin Queue
        r_queue = client.get("/api/admin/queue", headers=ADMIN_HEADERS)
        assert r_queue.status_code == 200
        queue_items = r_queue.json()["items"]
        matching = [q for q in queue_items if q["id"] == queue_id]
        assert len(matching) == 1

        # 3. Admin approves decision directly
        decision_payload = {
            "queue_item_id": queue_id,
            "action": {
                "type": "execute_campaign",
                "campaign_id": campaign_id,
            },
            "reason": "Approved Kerala promo for monsoon season",
            "resolution_status": "resolved",
        }
        r_dec = client.post("/api/admin/decisions", json=decision_payload, headers=ADMIN_HEADERS)
        assert r_dec.status_code == 200
        assert r_dec.json()["queue_item_updated"] is True

        # 4. Verify DB mutations
        camp_after = await db.marketing_campaigns.find_one({"_id": ObjectId(campaign_id)})
        assert camp_after["status"] == "published"
        assert camp_after["external_post_id"] is not None

        q_after = await db.jarvis_queue_items.find_one({"_id": ObjectId(queue_id)})
        assert q_after["status"] == "resolved"

        # Cleanup
        await db.marketing_campaigns.delete_one({"_id": ObjectId(campaign_id)})
        await db.jarvis_queue_items.delete_one({"_id": ObjectId(queue_id)})
        await db.jarvis_decisions.delete_one({"_id": ObjectId(r_dec.json()["decision_id"])})

    _run(_test())


# ═══════════════ 6. Rate Limiting on Verify ═══════════════

def test_admin_verify_rate_limited_at_10_per_min(client):
    """POST /api/admin/verify triggers 429 within 15 attempts."""
    statuses = []
    for _ in range(15):
        r = client.post("/api/admin/verify", json={"admin_key": "wrong-key"})
        statuses.append(r.status_code)
        if r.status_code == 429:
            break

    assert 429 in statuses, f"Expected 429 within 15 attempts, got {statuses}"
