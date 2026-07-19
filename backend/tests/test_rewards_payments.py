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


def _expected_inr(usd_amount):
    """Premium pricing is now converted from a USD base to INR via the
    app's live FX rate at read time (see server._get_premium_plans), not a
    fixed number - so tests compute the expected value the same way the
    server does, rather than asserting a stale hardcoded literal."""
    async def _compute():
        from services import ignav_service
        await ignav_service._refresh_rates_if_stale()
        return ignav_service._to_inr(usd_amount, 'USD')
    return _run(_compute())


def _run(coro):
    # asyncio.run, not get_event_loop().run_until_complete(...) - the latter
    # raises "There is no current event loop in thread" on Python 3.14's
    # tightened asyncio (see test_rate_limit_quota.py, which already made
    # this exact fix). Encountered while touching this file for the
    # subscription-state field rename below - fixing it here too since
    # otherwise there's no way to actually run test_idempotent_post_payment_processing
    # to verify that rewrite.
    return asyncio.run(coro)


# ---------- Rewards ----------

def test_rewards_unauthorized():
    r = requests.get(f"{BASE_URL}/api/rewards")
    assert r.status_code == 401


def test_rewards_summary_structure():
    r = requests.get(f"{BASE_URL}/api/rewards", headers=AUTH_HEADER)
    assert r.status_code == 200, r.text
    data = r.json()
    for k in ("available_points", "lifetime_points", "available_discount_usd",
              "available_discount_inr", "current_tier", "transactions",
              "earn_rules", "all_tiers"):
        assert k in data, f"missing {k}"
    # available_discount_inr is available_discount_usd converted via the
    # same live FX rate everything else uses - not a second/new conversion.
    assert data["available_discount_inr"] == _expected_inr(data["available_discount_usd"])
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
            {"$unset": {"stripe_subscription_status": "", "premium_plan": "",
                        "current_period_end": "", "premium_started_at": "",
                        "stripe_subscription_id": "", "stripe_customer_id": "",
                        "cancel_at_period_end": ""}}
        )
    _run(_setup())
    r = requests.get(f"{BASE_URL}/api/subscription/status", headers=AUTH_HEADER)
    assert r.status_code == 200
    data = r.json()
    assert data["is_premium"] is False
    assert "available_plans" in data
    assert "monthly" in data["available_plans"]
    assert data["available_plans"]["monthly"]["amount"] == _expected_inr(9.99)
    assert data["available_plans"]["monthly"]["currency"] == "inr"
    assert data["available_plans"]["yearly"]["amount"] == _expected_inr(99.00)


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
    """Frontend-supplied 'amount' must be ignored - server computes the
    premium price itself (USD base converted to INR via the live rate)."""
    r = requests.post(f"{BASE_URL}/api/payments/checkout",
                      json={"package_id": "monthly", "amount": 0.01,
                            "origin_url": "https://example.com"}, headers=HEADERS)
    assert r.status_code == 200, r.text
    data = r.json()
    # Backend MUST compute from its own USD base + live rate, regardless of frontend amount
    assert data["amount"] == _expected_inr(9.99)
    assert data["currency"] == "inr"


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
    assert data["amount"] == _expected_inr(9.99)
    assert data["currency"] == "inr"


def test_checkout_yearly_creates_stripe_session():
    r = requests.post(f"{BASE_URL}/api/payments/checkout",
                      json={"package_id": "yearly",
                            "origin_url": "https://example.com"}, headers=HEADERS)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["url"].startswith("https://checkout.stripe.com")
    assert data["amount"] == _expected_inr(99.00)


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
    """Simulate a successful subscription payment, then call status twice to
    ensure rewards aren't double-applied.

    Under the current design, subscription *activation* (stripe_subscription_status,
    current_period_end, etc.) is owned entirely by customer.subscription.created/
    updated (server._sync_subscription_from_stripe), not by checkout completing.
    This test simulates that webhook's DB effect directly (a fresh _db()
    connection, the same pattern every other test in this file already
    uses) rather than importing and calling server._sync_subscription_from_stripe
    itself - doing the latter was tried and reverted: it binds server.py's
    own module-level Motor client to *this* asyncio.run()'s event loop,
    which asyncio.run() then closes on return, breaking any later test in
    ANY file in the same pytest session that calls a server.* async
    function directly (test_rate_limit_quota.py does exactly that) with
    "RuntimeError: Event loop is closed" - a genuine cross-file regression
    caught by running the full suite together, not something visible
    running this file alone.
    """
    # Create checkout
    r = requests.post(f"{BASE_URL}/api/payments/checkout",
                      json={"package_id": "yearly",
                            "origin_url": "https://example.com"}, headers=HEADERS)
    assert r.status_code == 200
    session_id = r.json()["session_id"]

    async def _setup():
        db = _db()
        await db.user_rewards.update_one(
            {"user_id": USER_ID},
            {"$set": {"available_points": 0, "lifetime_points": 0}}, upsert=True)

        # Simulate customer.subscription.created's DB effect directly -
        # same fields _sync_subscription_from_stripe would write from a
        # real Stripe Subscription object shaped like this (including the
        # two fields that moved in recent Stripe API versions:
        # items.data[].current_period_end is read from, not a top-level
        # field, though here we just write the end result).
        from datetime import datetime, timezone, timedelta
        current_period_end = datetime.now(timezone.utc) + timedelta(days=365)
        await db.users.update_one(
            {"user_id": USER_ID},
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

        # Simulate checkout.session.completed's remaining job under the
        # current design - just the one-time signup bonus (activation
        # itself, above, is no longer this event's responsibility).
        txn = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})
        assert txn is not None
        await db.payment_transactions.update_one(
            {"session_id": session_id},
            {"$set": {"payment_status": "paid", "status": "completed"}}
        )
        from services import rewards_service
        await rewards_service.award_points(
            db, USER_ID, "premium_subscription", reference_id=session_id,
            description="Premium yearly subscription bonus"
        )
    _run(_setup())

    # Verify subscription is active, with the new field names
    r = requests.get(f"{BASE_URL}/api/subscription/status", headers=AUTH_HEADER)
    data = r.json()
    assert data["is_premium"] is True
    assert data["premium_plan"] == "yearly"
    assert data["subscription_status"] == "active"
    assert data["current_period_end"] is not None
    assert data["cancel_at_period_end"] is False

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
    assert txn["amount"] == _expected_inr(9.99)
    assert txn["payment_type"] == "subscription"
    assert txn["metadata"]["package_id"] == "monthly"
    assert txn["metadata"]["user_id"] == USER_ID
