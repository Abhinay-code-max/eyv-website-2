"""
Tests for Sara (Analytics & Business Intelligence Sub-Agent) - Task A.3.
Verifies RevenueCat webhook auth, idempotency, deterministic anomaly detection,
anomaly flood dedup, sandbox environment filtering, FX currency normalization,
null guards, and AST scope isolation.
"""
from __future__ import annotations

import ast
import asyncio
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

os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")
os.environ.setdefault("WALLET_URL_SIGNING_SECRET", "test-wallet-secret")
os.environ.setdefault("INTERNAL_TICKET_API_TOKEN", "test-internal-token")
os.environ.setdefault("INTERNAL_ANALYTICS_API_TOKEN", "test-analytics-token")
os.environ.setdefault("JARVIS_QUEUE_API_TOKEN", "test-jarvis-token")
os.environ.setdefault("REVENUECAT_WEBHOOK_AUTH_KEY", "test-revenuecat-key")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_database")

from conftest import client  # noqa: E402,F401
from server import _resolve_revenuecat_webhook_key
from services.analytics_agent_service import (
    record_revenuecat_event,
    evaluate_revenuecat_event,
    evaluate_system_anomalies,
    convert_to_usd,
)

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")
RC_AUTH_HEADERS = {"Authorization": f"Bearer {os.environ.get('REVENUECAT_WEBHOOK_AUTH_KEY', 'test-revenuecat-key')}"}


def _db():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def clean_revenuecat_test_data():
    """Wipes test revenuecat and sara queue records before each test."""
    async def _clean():
        db = _db()
        await db.revenuecat_events.delete_many({})
        await db.jarvis_queue_items.delete_many({"source_agent": "sara"})
    _run(_clean())
    yield
    _run(_clean())


# ═══════════════ 1. AST Scope Isolation Test ═══════════════

def test_analytics_agent_never_references_forbidden_collections():
    """AST check ensuring analytics_agent_service never writes or references forbidden collections."""
    service_path = BACKEND_DIR / "services" / "analytics_agent_service.py"
    source = service_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    forbidden = {"users", "bookings", "payment_transactions", "refunds", "support_turns"}
    accessed = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if node.attr in forbidden:
                accessed.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in forbidden:
                accessed.add(node.value)

    assert not accessed, f"analytics_agent_service.py violates scope discipline: accessed {accessed}"


# ═══════════════ 2. Startup Hard-Fail & Webhook Auth Tests ═══════════════

def test_startup_hard_fails_when_revenuecat_webhook_key_is_missing(monkeypatch):
    """Server boot must hard fail if REVENUECAT_WEBHOOK_AUTH_KEY is unset."""
    monkeypatch.delenv("REVENUECAT_WEBHOOK_AUTH_KEY", raising=False)
    with pytest.raises(RuntimeError, match="REVENUECAT_WEBHOOK_AUTH_KEY must be set"):
        _resolve_revenuecat_webhook_key()


def test_revenuecat_webhook_no_token_rejected_401(client):
    r = client.post("/api/webhooks/revenuecat", json={"event": {"id": "1", "type": "TEST"}})
    assert r.status_code == 401
    assert "RevenueCat webhook authorization" in r.text


def test_revenuecat_webhook_wrong_token_rejected_401(client):
    r = client.post(
        "/api/webhooks/revenuecat",
        json={"event": {"id": "1", "type": "TEST"}},
        headers={"Authorization": "Bearer wrong-revenuecat-key"},
    )
    assert r.status_code == 401


def test_revenuecat_webhook_correct_token_accepted_200(client):
    event_id = f"rc_evt_{uuid.uuid4().hex[:10]}"
    payload = {
        "event": {
            "id": event_id,
            "type": "TEST",
            "app_user_id": "test_user_01",
            "environment": "SANDBOX",
        }
    }
    r = client.post("/api/webhooks/revenuecat", json=payload, headers=RC_AUTH_HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "test_event_recorded"
    assert data["event_id"] == event_id


# ═══════════════ 3. Sandbox Environment Filtering Test ═══════════════

def test_sandbox_environment_events_never_trigger_alarms(client):
    """Events marked environment: SANDBOX (even critical types) must never enqueue to JARVIS."""
    event_id = f"rc_sb_{uuid.uuid4().hex[:10]}"
    payload = {
        "event": {
            "id": event_id,
            "type": "CANCELLATION",
            "environment": "SANDBOX",
            "app_user_id": "sandbox_user_99",
            "price_in_purchased_currency": 500.0,
        }
    }
    r = client.post("/api/webhooks/revenuecat", json=payload, headers=RC_AUTH_HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "test_event_recorded"
    assert data["anomaly_detected"] is False

    async def _check():
        db = _db()
        q_count = await db.jarvis_queue_items.count_documents({"source_agent": "sara"})
        assert q_count == 0  # Zero queue pollution from sandbox events
    _run(_check())


# ═══════════════ 4. Idempotency & Routine Event Tests ═══════════════

def test_revenuecat_webhook_idempotent_on_duplicate_event_id(client):
    event_id = f"rc_dup_{uuid.uuid4().hex[:10]}"
    payload = {
        "event": {
            "id": event_id,
            "type": "RENEWAL",
            "app_user_id": "user_renew_123",
            "price_in_purchased_currency": 9.99,
        }
    }

    # First delivery
    r1 = client.post("/api/webhooks/revenuecat", json=payload, headers=RC_AUTH_HEADERS)
    assert r1.status_code == 200
    assert r1.json()["status"] == "recorded"

    # Duplicate redelivery
    r2 = client.post("/api/webhooks/revenuecat", json=payload, headers=RC_AUTH_HEADERS)
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate_ignored"

    # Routine renewal should produce ZERO queue items
    async def _check():
        db = _db()
        q_count = await db.jarvis_queue_items.count_documents({
            "source_agent": "sara",
            "payload.app_user_id": "user_renew_123",
        })
        assert q_count == 0  # No queue pollution
    _run(_check())


# ═══════════════ 5. Anomaly Flood Deduplication Test ═══════════════

def test_anomaly_flood_dedup_does_not_spam_duplicate_queue_items(client):
    """Multiple billing failures during an outage reuse the single pending queue item."""
    async def _test():
        db = _db()
        now = datetime.now(timezone.utc)

        # Seed 2 recent billing issues
        for i in range(2):
            await db.revenuecat_events.insert_one({
                "event_id": f"rc_seed_bill_{i}_{uuid.uuid4().hex[:8]}",
                "event_type": "BILLING_ISSUE",
                "app_user_id": f"user_seed_{i}",
                "environment": "PRODUCTION",
                "created_at": now - timedelta(minutes=10 * (i + 1)),
            })

        # 3rd event crosses threshold -> creates queue item
        r3 = client.post("/api/webhooks/revenuecat", json={
            "event": {
                "id": f"rc_bill_3_{uuid.uuid4().hex[:8]}",
                "type": "BILLING_ISSUE",
                "app_user_id": "user_3",
            }
        }, headers=RC_AUTH_HEADERS)
        assert r3.status_code == 200
        first_queue_id = r3.json()["queue_item_id"]

        # 4th and 5th billing issues arrive during the ongoing outage
        for k in range(4, 6):
            rk = client.post("/api/webhooks/revenuecat", json={
                "event": {
                    "id": f"rc_bill_{k}_{uuid.uuid4().hex[:8]}",
                    "type": "BILLING_ISSUE",
                    "app_user_id": f"user_{k}",
                }
            }, headers=RC_AUTH_HEADERS)
            assert rk.status_code == 200
            assert rk.json()["queue_item_id"] == first_queue_id  # Reuses existing open item!

        # Confirm exactly 1 queue item exists in db.jarvis_queue_items
        q_count = await db.jarvis_queue_items.count_documents({
            "source_agent": "sara",
            "item_type": "billing_issue_spike",
        })
        assert q_count == 1  # Flood prevented!

    _run(_test())


# ═══════════════ 6. Currency Normalization & Null Price Guards ═══════════════

def test_currency_conversion_and_null_guards():
    """Verifies FX rates and safe handling of nulls/invalid types."""
    assert convert_to_usd(None, "USD") == 0.0
    assert convert_to_usd(-10.0, "USD") == 0.0
    assert convert_to_usd("invalid", "USD") == 0.0
    assert convert_to_usd(100.0, "USD") == 100.0
    assert convert_to_usd(5000.0, "INR") == 60.0  # 5000 * 0.012 = $60
    assert convert_to_usd(2000.0, "INR") == 24.0  # 2000 * 0.012 = $24 (below $50)


def test_inr_currency_whale_churn_threshold(client):
    """5000 INR (~$60 USD) triggers high value churn, 2000 INR (~$24 USD) does not."""
    # Sub-50 USD equivalent cancellation (2000 INR = ~$24 USD) -> No anomaly
    r1 = client.post("/api/webhooks/revenuecat", json={
        "event": {
            "id": f"rc_inr_sub50_{uuid.uuid4().hex[:8]}",
            "type": "CANCELLATION",
            "app_user_id": "inr_user_small",
            "price_in_purchased_currency": 2000.0,
            "currency": "INR",
        }
    }, headers=RC_AUTH_HEADERS)
    assert r1.status_code == 200
    assert r1.json()["anomaly_detected"] is False

    # Over-50 USD equivalent cancellation (5000 INR = ~$60 USD) -> Priority 1 anomaly
    r2 = client.post("/api/webhooks/revenuecat", json={
        "event": {
            "id": f"rc_inr_whale_{uuid.uuid4().hex[:8]}",
            "type": "CANCELLATION",
            "app_user_id": "inr_user_whale",
            "price_in_purchased_currency": 5000.0,
            "currency": "INR",
        }
    }, headers=RC_AUTH_HEADERS)
    assert r2.status_code == 200
    assert r2.json()["anomaly_detected"] is True
    assert r2.json()["anomaly_type"] == "high_value_cancellation"


# ═══════════════ 7. System Promotion Capacity Warning ═══════════════

def test_system_promotion_capacity_warning():
    """Sara detects promotion approaching capacity limit (>= 85%) and raises Priority 5 warning."""
    async def _test():
        db = _db()
        now = datetime.now(timezone.utc)
        code = f"TESTCAP{int(now.timestamp())}"
        
        # Seed a promotion with 90/100 redemptions (90% capacity)
        promo_doc = {
            "code": code,
            "discount_type": "percent",
            "discount_value": 15.0,
            "valid_from": now,
            "valid_until": now + timedelta(days=30),
            "usage_cap": 100,
            "redemption_count": 90,
            "created_at": now,
        }
        await db.promotions.insert_one(promo_doc)

        anomalies = await evaluate_system_anomalies(db)
        cap_anomalies = [a for a in anomalies if a.anomaly_type == "promo_capacity_near_limit" and a.details.get("code") == code]
        assert len(cap_anomalies) == 1
        assert cap_anomalies[0].priority == 5

        # Cleanup
        await db.promotions.delete_one({"code": code})
    _run(_test())
