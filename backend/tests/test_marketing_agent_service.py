"""
Tests for Bob (Marketing & Promotion Sub-Agent) - Task A.4.
Verifies campaign draft generation, queue enqueuing, priority assignment,
campaign execution, promo code creation, closed-loop JARVIS execution,
and AST scope isolation.
"""
from __future__ import annotations

import ast
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

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
os.environ["MONGO_URL"] = "mongodb://localhost:27017"
os.environ["DB_NAME"] = "test_eyv_marketing"

from conftest import client  # noqa: E402,F401
from services.marketing_agent_service import (
    generate_campaign_draft,
    execute_approved_campaign,
    handle_jarvis_marketing_decision,
)
from services.marketing_channels.buffer_client import BufferClient
from services.marketing_channels.instagram_client import InstagramClient
from services.marketing_channels.whatsapp_client import WhatsAppClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_eyv_marketing")
AUTH_HEADERS = {"Authorization": "Bearer test-jarvis-queue-token"}


def _db():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _run(coro):
    return asyncio.run(coro)


# ═══════════════ 1. AST Scope Isolation Test ═══════════════

def test_marketing_agent_never_references_forbidden_collections():
    """AST check ensuring marketing_agent_service never accesses forbidden collections."""
    service_path = BACKEND_DIR / "services" / "marketing_agent_service.py"
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

    assert not accessed, f"marketing_agent_service.py violates scope discipline: accessed {accessed}"


# ═══════════════ 2. Campaign Generation & Queue Enqueue Tests ═══════════════

def test_generate_campaign_draft_enqueues_for_jarvis():
    """Bob drafts a campaign, saves it in db.marketing_campaigns, and enqueues to db.jarvis_queue_items."""
    async def _test():
        db = _db()
        result = await generate_campaign_draft(
            db,
            title="Goa Monsoon Getaway",
            channel="instagram",
            destination="Goa",
            theme="monsoon_discounts",
            discount_percent=15.0,
        )

        assert result.status == "pending_approval"
        assert result.campaign_id is not None
        assert result.queue_item_id is not None

        # Verify campaign document in db.marketing_campaigns
        camp_doc = await db.marketing_campaigns.find_one({"_id": ObjectId(result.campaign_id)})
        assert camp_doc is not None
        assert camp_doc["title"] == "Goa Monsoon Getaway"
        assert camp_doc["channel"] == "instagram"
        assert camp_doc["status"] == "pending_approval"
        assert isinstance(camp_doc["created_at"], datetime)

        # Verify work item in db.jarvis_queue_items
        q_doc = await db.jarvis_queue_items.find_one({"_id": ObjectId(result.queue_item_id)})
        assert q_doc is not None
        assert q_doc["source_agent"] == "bob"
        assert q_doc["item_type"] == "marketing_campaign_approval"
        assert q_doc["priority"] == 5  # Normal discount <= 25%
        assert q_doc["status"] == "pending"

        # Cleanup
        await db.marketing_campaigns.delete_one({"_id": camp_doc["_id"]})
        await db.jarvis_queue_items.delete_one({"_id": q_doc["_id"]})

    _run(_test())


def test_high_discount_campaign_enqueued_at_priority_1():
    """Campaigns with high discount (>25%) get priority 1 for urgent review."""
    async def _test():
        db = _db()
        result = await generate_campaign_draft(
            db,
            title="Flash Sale 30% Off",
            channel="whatsapp",
            destination="Manali",
            discount_percent=30.0,
        )

        q_doc = await db.jarvis_queue_items.find_one({"_id": ObjectId(result.queue_item_id)})
        assert q_doc["priority"] == 1  # Critical/High Priority

        # Cleanup
        await db.marketing_campaigns.delete_one({"_id": ObjectId(result.campaign_id)})
        await db.jarvis_queue_items.delete_one({"_id": q_doc["_id"]})

    _run(_test())


# ═══════════════ 3. Campaign Execution Tests ═══════════════

def test_execute_approved_campaign_creates_promo_and_publishes():
    """Executing an approved campaign creates the PromotionDoc in db.promotions and publishes to channel."""
    async def _test():
        db = _db()
        draft = await generate_campaign_draft(
            db,
            title="Kerala Backwaters Promo",
            channel="buffer",
            destination="Kerala",
            discount_percent=20.0,
        )

        # Execute the campaign
        exec_res = await execute_approved_campaign(
            db,
            campaign_id=draft.campaign_id,
            buffer_client=BufferClient(dry_run=True),
        )

        assert exec_res.status == "published"
        assert exec_res.external_post_id is not None
        assert exec_res.promo_code is not None

        # Verify campaign state in DB
        camp_doc = await db.marketing_campaigns.find_one({"_id": ObjectId(draft.campaign_id)})
        assert camp_doc["status"] == "published"
        assert camp_doc["external_post_id"] == exec_res.external_post_id
        assert isinstance(camp_doc["published_at"], datetime)

        # Verify PromotionDoc in db.promotions
        promo_doc = await db.promotions.find_one({"code": exec_res.promo_code})
        assert promo_doc is not None
        assert promo_doc["discount_type"] == "percent"
        assert promo_doc["discount_value"] == 20.0
        assert isinstance(promo_doc["created_at"], datetime)

        # Cleanup
        await db.marketing_campaigns.delete_one({"_id": camp_doc["_id"]})
        await db.promotions.delete_one({"_id": promo_doc["_id"]})
        await db.jarvis_queue_items.delete_one({"_id": ObjectId(draft.queue_item_id)})

    _run(_test())


# ═══════════════ 4. Closed-Loop Agent-to-JARVIS Execution ═══════════════

def test_full_bob_to_jarvis_decision_loop(client):
    """End-to-end flow: Bob drafts campaign -> JARVIS polls queue -> JARVIS POSTs decision -> Campaign executes."""
    # 1. Bob generates draft
    draft = _run(generate_campaign_draft(
        _db(),
        title="Jaipur Royal Heritage",
        channel="instagram",
        destination="Jaipur",
        discount_percent=10.0,
    ))

    # 2. JARVIS polls queue
    r_queue = client.get("/jarvis/queue?source_agent=bob", headers=AUTH_HEADERS)
    assert r_queue.status_code == 200
    items = r_queue.json()["items"]
    bob_items = [it for it in items if it["id"] == draft.queue_item_id]
    assert len(bob_items) == 1

    # 3. JARVIS reasons and POSTs approval decision to /jarvis/decisions
    decision_payload = {
        "queue_item_id": draft.queue_item_id,
        "source_agent": "jarvis",
        "decision_type": "marketing_action",
        "action": {
            "type": "execute_campaign",
            "campaign_id": draft.campaign_id,
        },
        "reason": "High user interest in Rajasthan heritage trips",
        "resolution_status": "resolved",
    }

    r_dec = client.post("/jarvis/decisions", json=decision_payload, headers=AUTH_HEADERS)
    assert r_dec.status_code == 200
    dec_data = r_dec.json()
    assert dec_data["queue_item_updated"] is True

    # 4. Confirm campaign is now published and queue item resolved in DB
    async def _check():
        db = _db()
        camp_doc = await db.marketing_campaigns.find_one({"_id": ObjectId(draft.campaign_id)})
        assert camp_doc["status"] == "published"
        assert camp_doc["external_post_id"] is not None

        q_doc = await db.jarvis_queue_items.find_one({"_id": ObjectId(draft.queue_item_id)})
        assert q_doc["status"] == "resolved"

        # Cleanup
        await db.marketing_campaigns.delete_one({"_id": camp_doc["_id"]})
        await db.jarvis_queue_items.delete_one({"_id": q_doc["_id"]})
        await db.jarvis_decisions.delete_one({"_id": ObjectId(dec_data["decision"]["id"])})

    _run(_check())
