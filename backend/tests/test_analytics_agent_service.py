"""
Tests for Sara (Analytics & Business Intelligence Sub-Agent) - Task A.3.
Verifies RevenueCat webhook auth, idempotency, deterministic anomaly detection,
selective JARVIS queue production, sandbox event handling, and AST scope isolation.
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

os.environ["CORS_ORIGINS"] = "http://localhost:3000"
os.environ["WALLET_URL_SIGNING_SECRET"] = "test-wallet-secret"
os.environ["INTERNAL_TICKET_API_TOKEN"] = "test-ticket-token"
os.environ["INTERNAL_ANALYTICS_API_TOKEN"] = "test-analytics-token"
os.environ["JARVIS_QUEUE_API_TOKEN"] = "test-jarvis-queue-token"
os.environ["REVENUECAT_WEBHOOK_AUTH_KEY"] = "test-revenuecat-secret-key"
os.environ["MONGO_URL"] = "mongodb://localhost:27017"
os.environ["DB_NAME"] = "test_eyv_analytics"

from conftest import client  # noqa: E402,F401
from services.analytics_agent_service import (
    record_revenuecat_event,
    evaluate_revenuecat_event,
    evaluate_system_anomalies,
)

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_eyv_analytics")
RC_AUTH_HEADERS = {"Authorization": "Bearer test-revenuecat-secret-key"}


def _db():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _run(coro):
    return asyncio.run(coro)


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


# ═══════════════ 2. RevenueCat Webhook Authentication Tests ═══════════════

def test_revenuecat_webhook_no_token_rejected_401(client):
    r = client.post("/api/webhooks/revenuecat", json={"event": {"id": "1", "type": "TEST"}})
    assert r.status_code == 401
    assert "Invalid or missing RevenueCat webhook authorization" in r.text


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

    # Cleanup
    async def _clean():
        db = _db()
        await db.revenuecat_events.delete_one({"event_id": event_id})
    _run(_clean())


# ═══════════════ 3. Idempotency & Routine Event Tests ═══════════════

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
    async def _check_and_clean():
        db = _db()
        q_count = await db.jarvis_queue_items.count_documents({
            "source_agent": "sara",
            "payload.app_user_id": "user_renew_123",
        })
        assert q_count == 0  # No queue pollution

        await db.revenuecat_events.delete_many({"event_id": event_id})
    _run(_check_and_clean())


# ═══════════════ 4. Deterministic Anomaly Detection Tests ═══════════════

def test_single_billing_issue_does_not_enqueue_below_threshold(client):
    """1 single billing issue is normal transient noise -> 0 queue items."""
    event_id = f"rc_bill_single_{uuid.uuid4().hex[:10]}"
    payload = {
        "event": {
            "id": event_id,
            "type": "BILLING_ISSUE",
            "app_user_id": "user_single_bill",
            "price_in_purchased_currency": 9.99,
        }
    }
    r = client.post("/api/webhooks/revenuecat", json=payload, headers=RC_AUTH_HEADERS)
    assert r.status_code == 200
    assert r.json()["anomaly_detected"] is False

    async def _clean():
        db = _db()
        await db.revenuecat_events.delete_one({"event_id": event_id})
    _run(_clean())


def test_billing_issue_spike_triggers_priority_1_anomaly(client):
    """>= 3 billing issues within 1 hour triggers a Priority 1 emergency queue item."""
    async def _test():
        db = _db()
        now = datetime.now(timezone.utc)

        # Seed 2 recent billing issues in DB
        event_ids = []
        for i in range(2):
            eid = f"rc_seed_bill_{i}_{uuid.uuid4().hex[:8]}"
            event_ids.append(eid)
            await db.revenuecat_events.insert_one({
                "event_id": eid,
                "event_type": "BILLING_ISSUE",
                "app_user_id": f"user_seed_{i}",
                "created_at": now - timedelta(minutes=15 * (i + 1)),
            })

        # Send the 3rd billing issue via webhook (crosses threshold >= 3)
        third_id = f"rc_third_bill_{uuid.uuid4().hex[:8]}"
        event_ids.append(third_id)
        payload = {
            "event": {
                "id": third_id,
                "type": "BILLING_ISSUE",
                "app_user_id": "user_third_impacted",
                "price_in_purchased_currency": 19.99,
            }
        }
        r = client.post("/api/webhooks/revenuecat", json=payload, headers=RC_AUTH_HEADERS)
        assert r.status_code == 200
        data = r.json()
        assert data["anomaly_detected"] is True
        assert data["anomaly_type"] == "billing_issue_spike"
        assert data["queue_item_id"] is not None

        # Verify Priority 1 queue item in db.jarvis_queue_items
        q_item = await db.jarvis_queue_items.find_one({"_id": ObjectId(data["queue_item_id"])})
        assert q_item is not None
        assert q_item["source_agent"] == "sara"
        assert q_item["priority"] == 1  # Critical
        assert q_item["item_type"] == "billing_issue_spike"
        assert "billing failure spike" in q_item["payload"]["summary"]

        # Cleanup
        await db.revenuecat_events.delete_many({"event_id": {"$in": event_ids}})
        await db.jarvis_queue_items.delete_one({"_id": q_item["_id"]})

    _run(_test())


def test_high_value_subscriber_cancellation_triggers_priority_1(client):
    """Cancellation of a high-value ($50+) subscriber triggers Priority 1 attention."""
    event_id = f"rc_whale_cancel_{uuid.uuid4().hex[:8]}"
    payload = {
        "event": {
            "id": event_id,
            "type": "CANCELLATION",
            "app_user_id": "vip_user_44",
            "price_in_purchased_currency": 99.00,
            "currency": "USD",
            "cancel_reason": "CUSTOMER_SUPPORT",
            "product_id": "annual_vip_membership",
        }
    }
    r = client.post("/api/webhooks/revenuecat", json=payload, headers=RC_AUTH_HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data["anomaly_detected"] is True
    assert data["anomaly_type"] == "high_value_cancellation"

    async def _check_and_clean():
        db = _db()
        q_item = await db.jarvis_queue_items.find_one({"_id": ObjectId(data["queue_item_id"])})
        assert q_item is not None
        assert q_item["source_agent"] == "sara"
        assert q_item["priority"] == 1
        assert q_item["payload"]["price"] == 99.00

        await db.revenuecat_events.delete_one({"event_id": event_id})
        await db.jarvis_queue_items.delete_one({"_id": q_item["_id"]})
    _run(_check_and_clean())


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
        if cap_anomalies[0].queue_item_id:
            await db.jarvis_queue_items.delete_one({"_id": ObjectId(cap_anomalies[0].queue_item_id)})

    _run(_test())
