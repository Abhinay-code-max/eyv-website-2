"""
EYV Rewards + Stripe Payments + Premium Subscription tests.
Endpoints under test:
- /api/rewards (GET, POST /redeem)
- /api/payments/checkout (POST), /api/payments/status/{session_id} (GET)
- /api/subscription/status (GET)
- /api/webhook/stripe (POST)

All Stripe SDK interactions are strictly mocked (using unittest.mock and monkeypatch)
to ensure no tests ever make real network calls or create real objects in Stripe test mode.
"""
import os
import sys
import uuid
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from conftest import client, authed_client  # noqa: E402,F401  (fixture imports)

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')


def _db():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _run(coro):
    return asyncio.run(coro)


def _expected_inr(usd_amount):
    """Premium pricing is converted from USD base to INR via the live FX rate."""
    async def _compute():
        from services import ignav_service
        await ignav_service._refresh_rates_if_stale()
        return ignav_service._to_inr(usd_amount, 'USD')
    return _run(_compute())


@pytest.fixture(autouse=True)
def mock_stripe_sdk(monkeypatch):
    """Ensure Stripe SDK calls are strictly mocked across all tests in this file.
    
    Prevents tests from making real network calls to Stripe or creating
    real product / price / session objects in Stripe test mode.
    """
    import stripe

    monkeypatch.setattr(stripe, "api_key", "sk_test_mock_secret_key_123")
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_mock_secret_key_123")

    def _mock_create(**kwargs):
        session_id = f"cs_test_{uuid.uuid4().hex[:16]}"
        url = f"https://checkout.stripe.com/pay/{session_id}"
        mock_obj = MagicMock()
        mock_obj.id = session_id
        mock_obj.url = url
        mock_obj.payment_status = "unpaid"
        mock_obj.status = "open"
        return mock_obj

    def _mock_retrieve(session_id, **kwargs):
        mock_obj = MagicMock()
        mock_obj.id = session_id
        mock_obj.payment_status = "unpaid"
        mock_obj.status = "open"
        mock_obj.amount_total = 1000
        mock_obj.currency = "inr"
        mock_obj.metadata = {}
        return mock_obj

    monkeypatch.setattr(stripe.checkout.Session, "create", _mock_create)
    monkeypatch.setattr(stripe.checkout.Session, "retrieve", _mock_retrieve)


# ---------- Rewards ----------

def test_rewards_unauthorized(client):
    r = client.get("/api/rewards")
    assert r.status_code == 401


def test_rewards_summary_structure(authed_client):
    client_, user_id = authed_client
    r = client_.get("/api/rewards")
    assert r.status_code == 200, r.text
    data = r.json()
    for k in ("available_points", "lifetime_points", "available_discount_usd",
              "available_discount_inr", "current_tier", "transactions",
              "earn_rules", "all_tiers"):
        assert k in data, f"missing {k}"
    assert data["available_discount_inr"] == _expected_inr(data["available_discount_usd"])
    assert len(data["all_tiers"]) == 4
    tier_names = [t["name"] for t in data["all_tiers"]]
    assert tier_names == ["Explorer", "Wanderer", "Voyager", "Globetrotter"]
    for action in ("booking_flight", "booking_hotel", "premium_subscription"):
        assert action in data["earn_rules"]
    assert data["earn_rules"]["premium_subscription"] == 1000


def test_rewards_tier_assignment_explorer(authed_client):
    client_, user_id = authed_client
    async def _setup():
        db = _db()
        await db.user_rewards.update_one(
            {"user_id": user_id},
            {"$set": {"available_points": 0, "lifetime_points": 0}},
            upsert=True
        )
    _run(_setup())
    r = client_.get("/api/rewards")
    data = r.json()
    assert data["current_tier"]["name"] == "Explorer"
    assert data["current_tier"]["multiplier"] == 1.0


def test_rewards_tier_voyager_at_5000(authed_client):
    client_, user_id = authed_client
    async def _setup():
        db = _db()
        await db.user_rewards.update_one(
            {"user_id": user_id},
            {"$set": {"available_points": 5000, "lifetime_points": 5000}},
            upsert=True
        )
    _run(_setup())
    r = client_.get("/api/rewards")
    data = r.json()
    assert data["current_tier"]["name"] == "Voyager"
    assert data["current_tier"]["multiplier"] == 1.5


def test_rewards_redeem_success(authed_client):
    client_, user_id = authed_client
    async def _setup():
        db = _db()
        await db.user_rewards.update_one(
            {"user_id": user_id},
            {"$set": {"available_points": 2000, "lifetime_points": 2000}},
            upsert=True
        )
    _run(_setup())
    r = client_.post("/api/rewards/redeem", json={"points": 500})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["points_redeemed"] == 500
    assert abs(data["discount_usd"] - 5.0) < 0.001
    r = client_.get("/api/rewards")
    assert r.json()["available_points"] == 1500


def test_rewards_redeem_insufficient(authed_client):
    client_, user_id = authed_client
    async def _setup():
        db = _db()
        await db.user_rewards.update_one(
            {"user_id": user_id},
            {"$set": {"available_points": 100, "lifetime_points": 100}},
            upsert=True
        )
    _run(_setup())
    r = client_.post("/api/rewards/redeem", json={"points": 5000})
    assert r.status_code == 400


# ---------- Subscription status ----------

def test_subscription_status_unauthorized(client):
    r = client.get("/api/subscription/status")
    assert r.status_code == 401


def test_subscription_status_initial(authed_client):
    client_, user_id = authed_client
    async def _setup():
        db = _db()
        await db.users.update_one(
            {"user_id": user_id},
            {"$unset": {"stripe_subscription_status": "", "premium_plan": "",
                        "current_period_end": "", "premium_started_at": "",
                        "stripe_subscription_id": "", "stripe_customer_id": "",
                        "cancel_at_period_end": ""}}
        )
    _run(_setup())
    r = client_.get("/api/subscription/status")
    assert r.status_code == 200
    data = r.json()
    assert data["is_premium"] is False
    assert "available_plans" in data
    assert "monthly" in data["available_plans"]
    assert data["available_plans"]["monthly"]["amount"] == _expected_inr(9.99)
    assert data["available_plans"]["monthly"]["currency"] == "inr"
    assert data["available_plans"]["yearly"]["amount"] == _expected_inr(99.00)


# ---------- Payments / Stripe Checkout ----------

def test_checkout_unauthorized(client):
    r = client.post("/api/payments/checkout",
                    json={"package_id": "monthly",
                          "origin_url": "https://example.com"})
    assert r.status_code == 401


def test_checkout_requires_package_or_booking(authed_client):
    client_, user_id = authed_client
    r = client_.post("/api/payments/checkout",
                     json={"origin_url": "https://example.com"})
    assert r.status_code == 400


def test_checkout_rejects_invalid_package(authed_client):
    client_, user_id = authed_client
    r = client_.post("/api/payments/checkout",
                     json={"package_id": "lifetime", "origin_url": "https://example.com"})
    assert r.status_code == 400


def test_checkout_rejects_frontend_amount(authed_client):
    """Frontend-supplied 'amount' must be ignored - server computes the
    premium price itself (USD base converted to INR via the live rate)."""
    client_, user_id = authed_client
    r = client_.post("/api/payments/checkout",
                     json={"package_id": "monthly", "amount": 0.01,
                           "origin_url": "https://example.com"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["amount"] == _expected_inr(9.99)
    assert data["currency"] == "inr"


def test_checkout_monthly_creates_stripe_session(authed_client):
    client_, user_id = authed_client
    r = client_.post("/api/payments/checkout",
                     json={"package_id": "monthly",
                           "origin_url": "https://example.com"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert "url" in data and "session_id" in data
    assert data["url"].startswith("https://checkout.stripe.com"), data["url"]
    assert data["amount"] == _expected_inr(9.99)
    assert data["currency"] == "inr"


def test_checkout_yearly_creates_stripe_session(authed_client):
    client_, user_id = authed_client
    r = client_.post("/api/payments/checkout",
                     json={"package_id": "yearly",
                           "origin_url": "https://example.com"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["url"].startswith("https://checkout.stripe.com")
    assert data["amount"] == _expected_inr(99.00)


def test_checkout_with_booking_id(authed_client):
    client_, user_id = authed_client
    booking_id = f"BK_TEST_{uuid.uuid4().hex[:8]}"
    item_id = f"flight_{uuid.uuid4().hex[:8]}"
    expected_price = 450.0

    async def _setup():
        db = _db()
        await db.bookings.insert_one({
            "booking_id": booking_id,
            "user_id": user_id,
            "booking_type": "flight",
            "item_id": item_id,
            "total_amount": expected_price,
            "currency": "usd",
            "status": "pending_payment",
            "payment_status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    _run(_setup())

    r = client_.post("/api/payments/checkout",
                     json={"booking_id": booking_id,
                           "origin_url": "https://example.com"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["amount"] == expected_price
    assert data["url"].startswith("https://checkout.stripe.com")


def test_checkout_booking_not_found(authed_client):
    client_, user_id = authed_client
    r = client_.post("/api/payments/checkout",
                     json={"booking_id": "BKDOESNOTEXIST",
                           "origin_url": "https://example.com"})
    assert r.status_code == 404


def test_payment_status_pending(authed_client):
    client_, user_id = authed_client
    r_chk = client_.post("/api/payments/checkout",
                        json={"package_id": "monthly",
                              "origin_url": "https://example.com"})
    assert r_chk.status_code == 200, r_chk.text
    session_id = r_chk.json()["session_id"]

    r = client_.get(f"/api/payments/status/{session_id}")
    assert r.status_code == 200, r.text
    data = r.json()
    assert "payment_status" in data
    assert "status" in data
    assert data["payment_status"] in ("unpaid", "pending", "no_payment_required", "paid")


def test_payment_status_not_found(authed_client):
    client_, user_id = authed_client
    r = client_.get("/api/payments/status/cs_DOES_NOT_EXIST")
    assert r.status_code == 404


# ---------- Idempotency + post-payment side effects ----------

def test_idempotent_post_payment_processing(authed_client):
    """Simulate a successful subscription payment, then call status twice to
    ensure rewards aren't double-applied.
    """
    client_, user_id = authed_client
    r = client_.post("/api/payments/checkout",
                     json={"package_id": "yearly",
                           "origin_url": "https://example.com"})
    assert r.status_code == 200
    session_id = r.json()["session_id"]

    async def _setup():
        db = _db()
        await db.user_rewards.update_one(
            {"user_id": user_id},
            {"$set": {"available_points": 0, "lifetime_points": 0}}, upsert=True)

        current_period_end = datetime.now(timezone.utc) + timedelta(days=365)
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {
                "stripe_customer_id": "cus_test_idempotency",
                "stripe_subscription_id": "sub_test_idempotency",
                "stripe_subscription_status": "active",
                "cancel_at_period_end": False,
                "premium_plan": "yearly",
                "current_period_end": current_period_end.isoformat(),
                "premium_started_at": datetime.now(timezone.utc).isoformat(),
            }}
        )

        txn = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})
        assert txn is not None
        await db.payment_transactions.update_one(
            {"session_id": session_id},
            {"$set": {"payment_status": "paid", "status": "completed"}}
        )
        from services import rewards_service
        await rewards_service.award_points(
            db, user_id, "premium_subscription", reference_id=session_id,
            description="Premium yearly subscription bonus"
        )
    _run(_setup())

    # Verify subscription is active
    r = client_.get("/api/subscription/status")
    data = r.json()
    assert data["is_premium"] is True
    assert data["premium_plan"] == "yearly"
    assert data["subscription_status"] == "active"
    assert data["current_period_end"] is not None
    assert data["cancel_at_period_end"] is False

    # Verify 1000 points awarded
    r = client_.get("/api/rewards")
    data = r.json()
    assert data["available_points"] == 1000
    assert data["lifetime_points"] == 1000

    # Call status endpoint - paid txn should NOT re-trigger awards
    r = client_.get(f"/api/payments/status/{session_id}")
    assert r.status_code == 200
    assert r.json()["payment_status"] == "paid"

    # Points should still be 1000 (not 2000)
    r = client_.get("/api/rewards")
    assert r.json()["available_points"] == 1000


def test_tier_multiplier_applied():
    """Wanderer tier (1000+ lifetime) should yield 1.25x multiplier on flight booking points (100 base)."""
    user_id = f"test_tier_mult_{uuid.uuid4().hex[:8]}"
    async def _setup():
        db = _db()
        await db.user_rewards.update_one(
            {"user_id": user_id},
            {"$set": {"available_points": 0, "lifetime_points": 1500}}, upsert=True)
        from services import rewards_service
        result = await rewards_service.award_points(
            db, user_id, "booking_flight", reference_id="TEST_TIER_BK",
            description="Tier multiplier test")
        return result
    result = _run(_setup())
    assert result["points_awarded"] == 125
    assert result["tier"] == "Wanderer"


def test_payment_transaction_recorded(authed_client):
    """Verify payment_transactions collection has the row with correct fields."""
    client_, user_id = authed_client
    r = client_.post("/api/payments/checkout",
                     json={"package_id": "monthly",
                           "origin_url": "https://example.com"})
    assert r.status_code == 200
    session_id = r.json()["session_id"]

    async def _check():
        db = _db()
        txn = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})
        return txn
    txn = _run(_check())
    assert txn is not None
    assert txn["payment_status"] == "pending"
    assert txn["amount"] == _expected_inr(9.99)
    assert txn["payment_type"] == "subscription"
    assert txn["metadata"]["package_id"] == "monthly"
    assert txn["metadata"]["user_id"] == user_id
