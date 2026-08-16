"""
Tests for Telegram Bot Bridge Service - Multi-Agent Push & Control Center.
Verifies pre-auth rate limiting, secret header verification, chat ID authorization,
fault isolation, callback approval loop, ticket resolution, command validation,
and AST scope isolation.
"""
from __future__ import annotations

import ast
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import httpx
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
os.environ["TELEGRAM_BOT_TOKEN"] = "test-telegram-bot-token"
os.environ["TELEGRAM_SECRET_TOKEN"] = "test-telegram-secret-token"
os.environ["ADMIN_TELEGRAM_CHAT_ID"] = "987654321"
os.environ["BUFFER_SANDBOX_MODE"] = "true"
os.environ["MONGO_URL"] = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
os.environ["DB_NAME"] = os.environ.get("DB_NAME", "test_database")

from conftest import client  # noqa: E402,F401
from server import limiter

from services.telegram_bot_service import (
    send_telegram_message,
    send_queue_alert,
    process_telegram_update,
    handle_telegram_callback_query,
    handle_telegram_command,
)

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")
TG_SECRET_HEADERS = {"X-Telegram-Bot-Api-Secret-Token": "test-telegram-secret-token"}
ADMIN_CHAT_ID = "987654321"


def _db():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def cleanup_telegram_test_records():
    """Wipes test records between runs."""
    try:
        limiter._storage.reset()
    except Exception:
        pass
    yield
    try:
        limiter._storage.reset()
    except Exception:
        pass



# ═══════════════ 1. AST Scope Isolation ═══════════════

def test_telegram_bot_never_directly_writes_forbidden_collections():
    """AST check ensuring telegram_bot_service never directly writes to users, bookings, or payments."""
    service_path = BACKEND_DIR / "services" / "telegram_bot_service.py"
    source = service_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    forbidden_writes = {"users", "bookings", "payment_transactions", "refunds"}
    accessed = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if node.attr in forbidden_writes:
                accessed.add(node.attr)

    assert not accessed, f"telegram_bot_service.py violates scope discipline: accessed {accessed}"


# ═══════════════ 2. Secret Header Auth & Chat ID Whitelist ═══════════════

def test_telegram_webhook_missing_secret_token_returns_401(client):
    r = client.post("/api/webhooks/telegram", json={"update_id": 123})
    assert r.status_code == 401
    assert "Invalid Telegram webhook secret token" in r.text


def test_telegram_webhook_wrong_secret_token_returns_401(client):
    r = client.post(
        "/api/webhooks/telegram",
        json={"update_id": 123},
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"},
    )
    assert r.status_code == 401


def test_telegram_webhook_unauthorized_chat_id_rejected(client):
    """Messages from non-whitelisted Telegram chat IDs are rejected."""
    payload = {
        "update_id": 124,
        "message": {
            "message_id": 1,
            "from": {"id": 111222333, "first_name": "Attacker"},
            "chat": {"id": 111222333},
            "text": "/status",
        },
    }
    r = client.post("/api/webhooks/telegram", json=payload, headers=TG_SECRET_HEADERS)
    assert r.status_code == 200
    assert r.json()["status"] == "unauthorized"


# ═══════════════ 3. Fault-Isolation & Timeout Guard ═══════════════

def test_send_telegram_message_fault_isolation_on_network_error():
    """Simulated 500 or connection error returns gracefully without raising exception."""
    class FailingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Telegram Server Error")

    async def _test():
        async with httpx.AsyncClient(transport=FailingTransport()) as fake_client:
            res = await send_telegram_message(
                chat_id=ADMIN_CHAT_ID,
                text="Test alert",
                http_client=fake_client,
            )
            assert res["success"] is False
            assert res["status_code"] == 500
    _run(_test())


# ═══════════════ 4. Closed-Loop Campaign Approval via Telegram ═══════════════

def test_telegram_callback_approves_bob_campaign(client):
    """Abhinay taps [Approve] on Bob campaign -> publishes post and activates coupon."""
    async def _test():
        db = _db()

        # 1. Seed campaign draft
        now = datetime.now(timezone.utc)
        camp_doc = {
            "title": "Goa Sunshine Promo",
            "channel": "buffer",
            "status": "pending_approval",
            "destination": "Goa",
            "discount_config": {
                "discount_type": "percent",
                "discount_value": 20.0,
                "usage_cap": 50,
                "code": "EYVGOA20",
            },
            "content": {"caption": "Visit beautiful Goa!", "dry_run": True},
            "created_at": now,
        }
        ins_camp = await db.marketing_campaigns.insert_one(camp_doc)
        campaign_id = str(ins_camp.inserted_id)

        # 2. Seed linked queue item
        q_doc = {
            "source_agent": "bob",
            "item_type": "campaign_approval",
            "payload": {"campaign_id": campaign_id, "title": camp_doc["title"]},
            "priority": 1,
            "status": "pending",
            "created_at": now,
        }
        ins_q = await db.jarvis_queue_items.insert_one(q_doc)
        queue_id = str(ins_q.inserted_id)

        # 3. Simulate Telegram callback query
        cb_payload = {
            "update_id": 999,
            "callback_query": {
                "id": "cb_query_123",
                "from": {"id": int(ADMIN_CHAT_ID), "first_name": "Abhinay"},
                "message": {
                    "message_id": 42,
                    "chat": {"id": int(ADMIN_CHAT_ID)},
                    "text": "🤖 Bob Campaign Proposal",
                },
                "data": f"approve:{queue_id}:{campaign_id}",
            },
        }

        # Mock outbound Telegram API calls
        class MockTgTransport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
                return httpx.Response(200, json={"ok": True})

        async with httpx.AsyncClient(transport=MockTgTransport()) as mock_tg:
            res = await process_telegram_update(db, cb_payload, http_client=mock_tg)
            assert res["status"] == "approved"

        # 4. Verify DB state mutations
        camp_after = await db.marketing_campaigns.find_one({"_id": ObjectId(campaign_id)})
        assert camp_after["status"] == "published"
        assert camp_after["external_post_id"] is not None

        q_after = await db.jarvis_queue_items.find_one({"_id": ObjectId(queue_id)})
        assert q_after["status"] == "resolved"

        # Verify audit log entry
        audit_after = await db.admin_audit_log.find_one({"action": "telegram_approve_campaign"})
        assert audit_after is not None

        # Cleanup
        await db.marketing_campaigns.delete_one({"_id": ObjectId(campaign_id)})
        await db.jarvis_queue_items.delete_one({"_id": ObjectId(queue_id)})
        await db.promotions.delete_one({"code": "EYVGOA20"})

    _run(_test())


# ═══════════════ 5. Closed-Loop Ticket Resolution via Telegram ═══════════════

def test_telegram_callback_resolves_ticket_via_internal_api():
    """Abhinay taps [Mark Resolved] on Denver escalation -> resolves ticket and audits."""
    async def _test():
        db = _db()
        now = datetime.now(timezone.utc)

        # 1. Seed ticket
        ticket_id = f"tkt_test_{uuid.uuid4().hex[:8]}"
        ticket_doc = {
            "ticket_id": ticket_id,
            "category": "bug",
            "title": "Payment timeout on checkout",
            "description": "3 travelers experienced payment delay",
            "status": "open",
            "reporters_count": 3,
            "created_at": now,
            "updated_at": now,
        }
        await db.tickets.insert_one(ticket_doc)

        # 2. Simulate Telegram callback query
        cb_payload = {
            "id": "cb_query_ticket_99",
            "from": {"id": int(ADMIN_CHAT_ID), "first_name": "Abhinay"},
            "message": {
                "message_id": 88,
                "chat": {"id": int(ADMIN_CHAT_ID)},
                "text": "🆘 Denver Escalation",
            },
            "data": f"resolve_ticket:{ticket_id}",
        }

        class MockTgTransport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
                return httpx.Response(200, json={"ok": True})

        async with httpx.AsyncClient(transport=MockTgTransport()) as mock_tg:
            res = await handle_telegram_callback_query(db, cb_payload, http_client=mock_tg)
            assert res["status"] == "ticket_resolved"

        # 3. Verify ticket updated
        tkt_after = await db.tickets.find_one({"ticket_id": ticket_id})
        assert tkt_after["status"] == "resolved"
        assert "Resolved by Abhinay via Telegram Bot" in tkt_after["resolution_note"]

        # Cleanup
        await db.tickets.delete_one({"ticket_id": ticket_id})

    _run(_test())


# ═══════════════ 6. Command Parsers & Discount Validation ═══════════════

def test_telegram_campaign_command_validates_discount_bounds():
    """/campaign validates that discount is strictly between 5% and 50%."""
    async def _test():
        db = _db()
        sent_messages = []

        class CaptureTransport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
                sent_messages.append(request)
                return httpx.Response(200, json={"ok": True})

        async with httpx.AsyncClient(transport=CaptureTransport()) as mock_tg:
            # 1. Invalid high discount (80%) -> Rejected
            await handle_telegram_command(db, "/campaign Goa 80", ADMIN_CHAT_ID, http_client=mock_tg)
            assert len(sent_messages) == 1
            body = sent_messages[-1].content.decode("utf-8")
            assert "between <b>5%</b> and <b>50%</b>" in body

            # 2. Valid discount (20%) -> Draft generated
            await handle_telegram_command(db, "/campaign Goa 20", ADMIN_CHAT_ID, http_client=mock_tg)
            assert len(sent_messages) == 2
            body2 = sent_messages[-1].content.decode("utf-8")
            assert "Bob created a campaign draft for Goa" in body2

        # Cleanup
        await db.marketing_campaigns.delete_many({"destination": "Goa"})

    _run(_test())


# ═══════════════ 7. Pre-Auth Rate Limiting Gate ═══════════════

def test_telegram_webhook_pre_auth_rate_limit_flood_gate(client):
    """POST /api/webhooks/telegram triggers 429 when flooded."""
    statuses = []
    for _ in range(130):
        r = client.post("/api/webhooks/telegram", json={"update_id": 1})
        statuses.append(r.status_code)
        if r.status_code == 429:
            break

    assert 429 in statuses, f"Expected 429 within 130 requests, got: {set(statuses)}"
