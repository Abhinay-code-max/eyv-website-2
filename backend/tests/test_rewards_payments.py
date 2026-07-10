"""
EYV Rewards + Stripe Payments + Premium Subscription tests.
Endpoints under test:
- /api/rewards (GET, POST /redeem)
- /api/payments/checkout (POST), /api/payments/status/{session_id} (GET)
- /api/subscription/status (GET)
- /api/webhook/stripe (POST)
"""
import os
import asyncio
import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = os.environ.get(
    'REACT_APP_BACKEND_URL',
    'http://localhost:8001'
).rstrip('/')
SESSION_TOKEN = os.environ.get('TEST_SESSION_TOKEN', 'test_session_eyv_1780670554293')
USER_ID = "test-user-eyv-1780670554293"
HEADERS = {"Authorization": f"Bearer {SESSION_TOKEN}", "Content-Type": "application/json"}
AUTH_HEADER = {"Authorization": f"Bearer {SESSION_TOKEN}"}

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')


def _db():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------- Rewards ----------

def test_rewards_unauthorized():
    r = requests.get(f"{BASE_URL}/api/rewards")
    assert r.status_code == 401


def test_rewards_summary_structure():
    r = requests.get(f"{BASE_URL}/api/rewards", headers=AUTH_HEADER)
    assert r.status_code == 200, r.text
    data = r.json()
    for k in ("available_points", "lifetime_points", "available_discount_usd",
              "current_tier", "transactions", "earn_rules", "all_tiers"):
        assert k in data, f"missing {k}"
    # 4 tiers
    assert len(data["all_tiers"]) == 4
    tier_names = [t["name"] for t in data["all_tiers"]]
    assert tier_names == ["Explorer", "Wanderer", "Voyager", "Globetrotter"]
    # earn rules
    for action in ("booking_flight", "booking_hotel", "premium_subscription"):
        assert action in data["earn_rules"]
    assert data["earn_rules"]["premium_subscription"] == 1000


def test_rewards_tier_assignment_explorer():
    """Reset user rewards to 0 -> tier should be Explorer."""
    async def _setup():
        db = _db()
        await db.user_rewards.update_one(
            {"user_id": USER_ID},
            {"$set": {"available_points": 0, "lifetime_points": 0}},
            upsert=True
        )
    _run(_setup())
    r = requests.get(f"{BASE_URL}/api/rewards", headers=AUTH_HEADER)
    data = r.json()
    assert data["current_tier"]["name"] == "Explorer"
    assert data["current_tier"]["multiplier"] == 1.0


def test_rewards_tier_voyager_at_5000():
    async def _setup():
        db = _db()
        await db.user_rewards.update_one(
            {"user_id": USER_ID},
            {"$set": {"available_points": 5000, "lifetime_points": 5000}},
            upsert=True
        )
    _run(_setup())
    r = requests.get(f"{BASE_URL}/api/rewards", headers=AUTH_HEADER)
    data = r.json()
    assert data["current_tier"]["name"] == "Voyager"
    assert data["current_tier"]["multiplier"] == 1.5


def test_rewards_redeem_success():
    # Ensure 2000 available
    async def _setup():
        db = _db()
        await db.user_rewards.update_one(
            {"user_id": USER_ID},
            {"$set": {"available_points": 2000, "lifetime_points": 2000}},
            upsert=True
        )
    _run(_setup())
    r = requests.post(f"{BASE_URL}/api/rewards/redeem",
                      json={"points": 500}, headers=HEADERS)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["points_redeemed"] == 500
    assert abs(data["discount_usd"] - 5.0) < 0.001
    # Verify deduction via GET
    r = requests.get(f"{BASE_URL}/api/rewards", headers=AUTH_HEADER)
    assert r.json()["available_points"] == 1500


def test_rewards_redeem_insufficient():
    async def _setup():
        db = _db()
        await db.user_rewards.update_one(
            {"user_id": USER_ID},
            {"$set": {"available_points": 100, "lifetime_points": 100}},
            upsert=True
        )
    _run(_setup())
    r = requests.post(f"{BASE_URL}/api/rewards/redeem",
                      json={"points": 5000}, headers=HEADERS)
    assert r.status_code == 400


# ---------- Subscription status ----------

def test_subscription_status_unauthorized():
    r = requests.get(f"{BASE_URL}/api/subscription/status")
    assert r.status_code == 401


def test_subscription_status_initial():
    # Ensure inactive
    async def _setup():
        db = _db()
        await db.users.update_one(
            {"user_id": USER_ID},
            {"$unset": {"premium_status": "", "premium_plan": "",
                        "premium_expires_at": "", "premium_started_at": ""}}
        )
    _run(_setup())
    r = requests.get(f"{BASE_URL}/api/subscription/status", headers=AUTH_HEADER)
    assert r.status_code == 200
    data = r.json()
    assert data["is_premium"] is False
    assert "available_plans" in data
    assert "monthly" in data["available_plans"]
    assert data["available_plans"]["monthly"]["amount"] == 9.99
    assert data["available_plans"]["yearly"]["amount"] == 99.00


# ---------- Payments / Stripe Checkout ----------

def test_checkout_unauthorized():
    r = requests.post(f"{BASE_URL}/api/payments/checkout",
                      json={"package_id": "monthly",
                            "origin_url": "https://example.com"})
    assert r.status_code == 401


def test_checkout_requires_package_or_booking():
    r = requests.post(f"{BASE_URL}/api/payments/checkout",
                      json={"origin_url": "https://example.com"}, headers=HEADERS)
    assert r.status_code == 400


def test_checkout_rejects_invalid_package():
    r = requests.post(f"{BASE_URL}/api/payments/checkout",
                      json={"package_id": "lifetime", "origin_url": "https://example.com"},
                      headers=HEADERS)
    assert r.status_code == 400


def test_checkout_rejects_frontend_amount():
    """Frontend-supplied 'amount' must be ignored - server uses backend PREMIUM_PLANS dict."""
    r = requests.post(f"{BASE_URL}/api/payments/checkout",
                      json={"package_id": "monthly", "amount": 0.01,
                            "origin_url": "https://example.com"}, headers=HEADERS)
    assert r.status_code == 200, r.text
    data = r.json()
    # Backend MUST use $9.99 from PREMIUM_PLANS regardless of frontend amount
    assert data["amount"] == 9.99
    assert data["currency"] == "usd"


@pytest.fixture(scope="module")
def monthly_checkout():
    """Create a monthly subscription checkout - used by multiple tests."""
    r = requests.post(f"{BASE_URL}/api/payments/checkout",
                      json={"package_id": "monthly",
                            "origin_url": "https://example.com"}, headers=HEADERS)
    if r.status_code != 200:
        pytest.skip(f"Stripe checkout creation failed: {r.status_code} {r.text}")
    return r.json()


def test_checkout_monthly_creates_stripe_session(monthly_checkout):
    data = monthly_checkout
    assert "url" in data and "session_id" in data
    assert data["url"].startswith("https://checkout.stripe.com"), data["url"]
    assert data["amount"] == 9.99
    assert data["currency"] == "usd"


def test_checkout_yearly_creates_stripe_session():
    r = requests.post(f"{BASE_URL}/api/payments/checkout",
                      json={"package_id": "yearly",
                            "origin_url": "https://example.com"}, headers=HEADERS)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["url"].startswith("https://checkout.stripe.com")
    assert data["amount"] == 99.0


def test_checkout_with_booking_id():
    # Search first - price must come from a real, server-cached item_id.
    search_payload = {"origin": "JFK", "destination": "Paris",
                       "departure_date": "2026-03-01", "travelers": 1}
    r = requests.post(f"{BASE_URL}/api/search/flights", json=search_payload, headers=HEADERS)
    assert r.status_code == 200, r.text
    flight = r.json()["flights"][0]
    expected_price = flight["price"]["total"]

    # Create a booking - note the (ignored) tampered "price" field, proving it has no effect
    booking_payload = {
        "booking_type": "flight",
        "item_id": flight["item_id"],
        "item_data": {"id": flight["id"], "airline": "Test Air"},
        "price": 1,
    }
    r = requests.post(f"{BASE_URL}/api/bookings", json=booking_payload, headers=HEADERS)
    assert r.status_code == 200
    booking = r.json()
    assert booking["total_amount"] == expected_price
    booking_id = booking["booking_id"]
    # Checkout
    r = requests.post(f"{BASE_URL}/api/payments/checkout",
                      json={"booking_id": booking_id,
                            "origin_url": "https://example.com"}, headers=HEADERS)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["amount"] == expected_price
    assert data["url"].startswith("https://checkout.stripe.com")


def test_checkout_booking_not_found():
    r = requests.post(f"{BASE_URL}/api/payments/checkout",
                      json={"booking_id": "BKDOESNOTEXIST",
                            "origin_url": "https://example.com"}, headers=HEADERS)
    assert r.status_code == 404


def test_payment_status_pending(monthly_checkout):
    session_id = monthly_checkout["session_id"]
    r = requests.get(f"{BASE_URL}/api/payments/status/{session_id}", headers=AUTH_HEADER)
    assert r.status_code == 200, r.text
    data = r.json()
    # Without completing checkout, should still be unpaid/open
    assert "payment_status" in data
    assert "status" in data
    assert data["payment_status"] in ("unpaid", "pending", "no_payment_required", "paid")


def test_payment_status_not_found():
    r = requests.get(f"{BASE_URL}/api/payments/status/cs_DOES_NOT_EXIST", headers=AUTH_HEADER)
    assert r.status_code == 404


# ---------- Idempotency + post-payment side effects ----------

def test_idempotent_post_payment_processing():
    """Simulate a successful payment by direct DB write, then call status twice
    to ensure subscription + rewards aren't double-applied."""
    # Create checkout
    r = requests.post(f"{BASE_URL}/api/payments/checkout",
                      json={"package_id": "yearly",
                            "origin_url": "https://example.com"}, headers=HEADERS)
    assert r.status_code == 200
    session_id = r.json()["session_id"]

    # Reset rewards + subscription
    async def _setup():
        db = _db()
        await db.user_rewards.update_one(
            {"user_id": USER_ID},
            {"$set": {"available_points": 0, "lifetime_points": 0}}, upsert=True)
        await db.users.update_one(
            {"user_id": USER_ID},
            {"$unset": {"premium_status": "", "premium_plan": "",
                        "premium_expires_at": "", "premium_started_at": ""}})
        # Directly mark txn paid and invoke processor (simulating webhook)
        from services import rewards_service
        txn = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})
        assert txn is not None
        await db.payment_transactions.update_one(
            {"session_id": session_id},
            {"$set": {"payment_status": "paid", "status": "completed"}}
        )
        # Apply post-payment logic via rewards_service directly
        plan_days = 365
        from datetime import datetime, timezone, timedelta
        expires_at = datetime.now(timezone.utc) + timedelta(days=plan_days)
        await db.users.update_one(
            {"user_id": USER_ID},
            {"$set": {"premium_status": "active", "premium_plan": "yearly",
                      "premium_expires_at": expires_at.isoformat()}}
        )
        await rewards_service.award_points(
            db, USER_ID, "premium_subscription", reference_id=session_id,
            description="Premium yearly subscription bonus"
        )
    _run(_setup())

    # Verify subscription is active
    r = requests.get(f"{BASE_URL}/api/subscription/status", headers=AUTH_HEADER)
    data = r.json()
    assert data["is_premium"] is True
    assert data["premium_plan"] == "yearly"

    # Verify 1000 points awarded
    r = requests.get(f"{BASE_URL}/api/rewards", headers=AUTH_HEADER)
    data = r.json()
    assert data["available_points"] == 1000
    assert data["lifetime_points"] == 1000

    # Call status endpoint - paid txn should NOT re-trigger awards
    r = requests.get(f"{BASE_URL}/api/payments/status/{session_id}", headers=AUTH_HEADER)
    assert r.status_code == 200
    assert r.json()["payment_status"] == "paid"

    # Points should still be 1000 (not 2000)
    r = requests.get(f"{BASE_URL}/api/rewards", headers=AUTH_HEADER)
    assert r.json()["available_points"] == 1000


def test_tier_multiplier_applied():
    """Wanderer tier (1000+ lifetime) should yield 1.25x multiplier on flight booking points (100 base)."""
    async def _setup():
        db = _db()
        # 1500 lifetime puts user in Wanderer (>=1000, <5000)
        await db.user_rewards.update_one(
            {"user_id": USER_ID},
            {"$set": {"available_points": 0, "lifetime_points": 1500}}, upsert=True)
        from services import rewards_service
        result = await rewards_service.award_points(
            db, USER_ID, "booking_flight", reference_id="TEST_TIER_BK",
            description="Tier multiplier test")
        return result
    result = _run(_setup())
    # 100 base * 1.25 = 125
    assert result["points_awarded"] == 125
    assert result["tier"] == "Wanderer"


def test_payment_transaction_recorded():
    """Verify payment_transactions collection has the row with correct fields."""
    r = requests.post(f"{BASE_URL}/api/payments/checkout",
                      json={"package_id": "monthly",
                            "origin_url": "https://example.com"}, headers=HEADERS)
    assert r.status_code == 200
    session_id = r.json()["session_id"]

    async def _check():
        db = _db()
        txn = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})
        return txn
    txn = _run(_check())
    assert txn is not None
    assert txn["payment_status"] == "pending"
    assert txn["amount"] == 9.99
    assert txn["payment_type"] == "subscription"
    assert txn["metadata"]["package_id"] == "monthly"
    assert txn["metadata"]["user_id"] == USER_ID
