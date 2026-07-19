"""
Tests for progressive per-tier trip generation.

POST /trips/generate used to block on asyncio.gather for all three tiers
before writing anything to the DB or returning a response - meaning the
user waited for the slowest tier (often Luxury, per real-world logs) even
when Budget/Premium had finished minutes earlier. It now saves the trip
immediately with all three tiers in status "generating" and hands each tier
off to its own background task (_generate_and_save_tier), which writes only
that tier's slot in trips.plans once it completes - independent of the
other two. The frontend polls GET /trips/{trip_id} the same way.

Section A hits the live server (same convention as test_rate_limit_quota.py
/ test_trip_regenerate.py) to prove the actual response-time and status
contract - this doesn't need a successful generation to be meaningful, so
it's unaffected by Gemini quota/availability.

Section B calls _generate_and_save_tier directly with generate_single_plan
mocked out, proving the single-index write touches only its own tier - no
live server or real Gemini call needed.
"""
import asyncio
import os
import sys
import time
from datetime import datetime, timezone, timedelta

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

import server  # noqa: E402

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'http://localhost:8001').rstrip('/')
MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')

USER_ID, SESSION = "test_progressive_gen_user", "test_progressive_gen_session"
HEADERS = {"Authorization": f"Bearer {SESSION}"}


def _db():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(scope="module", autouse=True)
def _setup_and_teardown():
    async def _seed():
        db = _db()
        now = datetime.now(timezone.utc)
        await db.users.update_one(
            {"user_id": USER_ID},
            {"$set": {
                "user_id": USER_ID, "email": f"{USER_ID}@example.com", "name": "Test",
                "created_at": now.isoformat(), "stripe_subscription_status": "inactive",
            }},
            upsert=True,
        )
        await db.user_sessions.update_one(
            {"session_token": SESSION},
            {"$set": {
                "session_token": SESSION, "user_id": USER_ID,
                "expires_at": (now + timedelta(days=7)).isoformat(), "created_at": now.isoformat(),
            }},
            upsert=True,
        )
        await db.generation_quota.delete_many({"user_id": USER_ID})
    _run(_seed())
    yield

    async def _cleanup():
        db = _db()
        await db.users.delete_many({"user_id": USER_ID})
        await db.user_sessions.delete_many({"session_token": SESSION})
        await db.generation_quota.delete_many({"user_id": USER_ID})
        await db.trips.delete_many({"user_id": USER_ID})
    _run(_cleanup())


# ═══════════ Section A: live - immediate response + placeholder contract ═══════════

def test_generate_returns_immediately_with_generating_status():
    """The whole point of the progressive-loading change: this must return
    in low single-digit seconds (trip creation + spawning background tasks),
    not the ~minutes a full 3-tier generation can take - and the caller must
    be able to tell every tier's state apart via status right away. Doesn't
    depend on Gemini actually succeeding, so it's meaningful even when the
    daily free-tier quota is exhausted."""
    payload = {
        "destination": "Prague", "starting_location": "Delhi",
        "departure_date": "2027-05-01", "return_date": "2027-05-05",
        "adults": 1, "children": 0, "seniors": 0,
        "transportation": "train", "budget_level": "Premium",
        "accommodation": ["hotel"], "interests": [], "trip_type": "leisure",
    }
    start = time.time()
    r = requests.post(f"{BASE_URL}/api/trips/generate", json=payload, headers=HEADERS, timeout=15)
    elapsed = time.time() - start

    assert r.status_code == 200, r.text
    assert elapsed < 10, f"took {elapsed:.1f}s - should return immediately, not wait on generation"
    data = r.json()
    trip_id = data["trip_id"]
    assert len(data["plans"]) == 3
    assert all(p["status"] == "generating" for p in data["plans"])
    assert {p["plan_type"] for p in data["plans"]} == {"Budget", "Premium", "Luxury"}

    # Must already be durably saved (not just returned in-memory) - a GET
    # right away has to see the same placeholder state, the way the
    # frontend's very first poll would.
    g = requests.get(f"{BASE_URL}/api/trips/{trip_id}", headers=HEADERS, timeout=10)
    assert g.status_code == 200, g.text
    assert all(p["status"] == "generating" for p in g.json()["plans"])

    requests.delete(f"{BASE_URL}/api/trips/{trip_id}", headers=HEADERS, timeout=10)


# ═══════════ Section B: _generate_and_save_tier writes only its own slot ═══════════

async def _fake_generate_single_plan(preferences, plan_type, trip_id, user_id, anchor=None):
    return {
        "plan_type": plan_type, "status": "ready",
        "currency": "INR", "currency_symbol": "₹",
        "itinerary": {"day_1": {"date": "2027-05-01"}},
        "cost_breakdown": {"transportation": 100, "accommodation": 200, "food": 50, "activities": 0, "miscellaneous": 0},
        "total_cost": 350, "highlights": [], "budget_tips": [],
    }


def _placeholder(plan_type):
    return {
        "plan_type": plan_type, "status": "generating",
        "currency": "INR", "currency_symbol": "₹",
        "itinerary": {},
        "cost_breakdown": {"transportation": 0, "accommodation": 0, "food": 0, "activities": 0, "miscellaneous": 0},
        "total_cost": 0, "highlights": [], "budget_tips": [],
    }


def test_generate_and_save_tier_updates_only_its_own_slot(monkeypatch):
    """Seeds a trip with all three tiers still "generating", runs
    _generate_and_save_tier for just Premium (index 1) with
    generate_single_plan mocked out, and confirms only that slot changed -
    Budget/Luxury must be untouched, proving tiers really do complete
    independently rather than all being written together."""
    trip_id = "test_progressive_slot_trip"

    async def _seed_and_run():
        # _generate_and_save_tier writes through the module-level server.db,
        # which was constructed at import time outside of any event loop -
        # using it from a *different* loop (the one asyncio.run() creates
        # for this test) is the same cross-loop Motor conflict the rest of
        # this suite avoids (see test_rate_limit_quota.py's docstring).
        # Point server.db at a client built inside this loop instead, same
        # as the one _db() would normally hand back.
        db = _db()
        monkeypatch.setattr(server, "db", db)

        plans = [_placeholder("Budget"), _placeholder("Premium"), _placeholder("Luxury")]
        now = datetime.now(timezone.utc).isoformat()
        await db.trips.update_one(
            {"trip_id": trip_id},
            {"$set": {
                "trip_id": trip_id, "user_id": USER_ID, "trip_name": "Test",
                "preferences": {}, "plans": plans, "created_at": now, "updated_at": now,
            }},
            upsert=True,
        )
        monkeypatch.setattr(server, "generate_single_plan", _fake_generate_single_plan)
        await server._generate_and_save_tier(trip_id, USER_ID, "Premium", {}, 1)
        return await db.trips.find_one({"trip_id": trip_id}, {"_id": 0})

    trip = _run(_seed_and_run())

    async def _delete():
        await _db().trips.delete_one({"trip_id": trip_id})
    _run(_delete())

    plans_by_type = {p["plan_type"]: p for p in trip["plans"]}
    assert plans_by_type["Premium"]["status"] == "ready"
    assert plans_by_type["Premium"]["total_cost"] == 350
    assert plans_by_type["Budget"]["status"] == "generating"
    assert plans_by_type["Luxury"]["status"] == "generating"


def test_placeholder_plan_shape():
    placeholder = server._placeholder_plan("Luxury", "INR", "₹")
    assert placeholder["plan_type"] == "Luxury"
    assert placeholder["status"] == "generating"
    assert placeholder["itinerary"] == {}
    assert placeholder["total_cost"] == 0
    assert "generation_failed" not in placeholder
