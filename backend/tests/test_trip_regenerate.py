"""
Tests for POST /api/trips/{trip_id}/regenerate/{plan_type} - re-runs
generation for a single tier of an already-saved trip (e.g. after that
tier's original generation failed) without touching the other two tiers.

Section A hits the live server directly with `requests`, mirroring the
convention in test_rate_limit_quota.py: an in-process TestClient + mocked
Gemini was tried first here too and hit the same reproducible Python 3.14 +
Windows + anyio event-loop conflict noted there, so this file also drives a
real running backend instead. All the fast/cheap paths (auth, ownership,
plan_type validation, quota) are pre-set up via direct DB writes so they
short-circuit before any provider call - only test_regenerate_updates_only_
target_tier below makes a real (single, cheap) Gemini call, and even that
one avoids real Duffel/SerpApi calls by seeding a valid cached anchor for
the endpoint to reuse (train mode + a pre-filled anchor_pricing block).

Section B calls generate_single_plan() directly (same pattern as
test_plan_generation_crash.py) to precisely and cheaply prove the
anchor-reuse contract itself: given a cached anchor, Duffel/SerpApi must
never be hit at all.
"""
import asyncio
import os
import sys
import time
import uuid
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

import server  # noqa: E402

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'http://localhost:8001').rstrip('/')
MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')

# Dedicated users per concern below, so hammering one endpoint's rate limit
# or quota never bleeds into (and breaks) an unrelated assertion elsewhere
# in this file.
OWNER_USER_ID, OWNER_SESSION = "test_regen_owner", "test_regen_owner_session"
OTHER_USER_ID, OTHER_SESSION = "test_regen_other", "test_regen_other_session"
STRESS_USER_ID, STRESS_SESSION = "test_regen_stress", "test_regen_stress_session"
REAL_USER_ID, REAL_SESSION = "test_regen_real", "test_regen_real_session"

OWNER_HEADERS = {"Authorization": f"Bearer {OWNER_SESSION}"}
OTHER_HEADERS = {"Authorization": f"Bearer {OTHER_SESSION}"}
STRESS_HEADERS = {"Authorization": f"Bearer {STRESS_SESSION}"}
REAL_HEADERS = {"Authorization": f"Bearer {REAL_SESSION}"}

ALL_TEST_USER_IDS = [OWNER_USER_ID, OTHER_USER_ID, STRESS_USER_ID, REAL_USER_ID]
ALL_TEST_SESSIONS = [OWNER_SESSION, OTHER_SESSION, STRESS_SESSION, REAL_SESSION]


def _db():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _run(coro):
    # asyncio.run (not get_event_loop().run_until_complete) - see the note
    # in test_rate_limit_quota.py on why, for Python 3.14 on Windows.
    return asyncio.run(coro)


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _seed_session(user_id, session_token):
    async def _do():
        db = _db()
        now = datetime.now(timezone.utc)
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {
                "user_id": user_id, "email": f"{user_id}@example.com", "name": "Test",
                "created_at": now.isoformat(), "stripe_subscription_status": "inactive",
            }},
            upsert=True,
        )
        await db.user_sessions.update_one(
            {"session_token": session_token},
            {"$set": {
                "session_token": session_token, "user_id": user_id,
                "expires_at": (now + timedelta(days=7)).isoformat(),
                "created_at": now.isoformat(),
            }},
            upsert=True,
        )
        await db.generation_quota.delete_many({"user_id": user_id})
    _run(_do())


def _set_quota(user_id, count):
    async def _do():
        db = _db()
        await db.generation_quota.update_one(
            {"user_id": user_id, "date": _today()},
            {"$set": {"count": count}},
            upsert=True,
        )
    _run(_do())


def _dummy_plan(plan_type):
    return {
        "plan_type": plan_type,
        "currency": "INR", "currency_symbol": "₹",
        "itinerary": {"day_1": {"date": "2027-02-01", "transportation": {"mode": "train", "cost": 999},
                                 "activities": [], "accommodation": {"name": "Existing Hotel", "cost": 3000},
                                 "meals": [], "daily_total": 3999, "cumulative_total": 3999}},
        "cost_breakdown": {"transportation": 999, "accommodation": 3000, "food": 0, "activities": 0, "miscellaneous": 0},
        "total_cost": 3999,
        "highlights": ["pre-existing highlight"],
        "budget_tips": ["pre-existing tip"],
    }


def _seed_trip(trip_id, user_id, plans, preferences=None):
    async def _do():
        db = _db()
        now = datetime.now(timezone.utc).isoformat()
        await db.trips.update_one(
            {"trip_id": trip_id},
            {"$set": {
                "trip_id": trip_id, "user_id": user_id, "trip_name": "Test Trip",
                "preferences": preferences or {
                    "destination": "Goa", "starting_location": "Mumbai",
                    "departure_date": "2027-02-01", "return_date": "2027-02-04",
                    "transportation": "train", "currency": "INR",
                    "num_travelers": 1, "adults": 1, "children": 0, "seniors": 0,
                    "budget_level": "Premium", "accommodation": ["hotel"], "interests": [],
                    "trip_type": "leisure",
                },
                "plans": plans,
                "created_at": now, "updated_at": now,
            }},
            upsert=True,
        )
    _run(_do())


def _fetch_trip(trip_id):
    async def _do():
        return await _db().trips.find_one({"trip_id": trip_id}, {"_id": 0})
    return _run(_do())


@pytest.fixture(scope="module", autouse=True)
def _setup_and_teardown():
    for uid, sess in zip(ALL_TEST_USER_IDS, ALL_TEST_SESSIONS):
        _seed_session(uid, sess)
    yield

    async def _cleanup():
        db = _db()
        await db.users.delete_many({"user_id": {"$in": ALL_TEST_USER_IDS}})
        await db.user_sessions.delete_many({"session_token": {"$in": ALL_TEST_SESSIONS}})
        await db.generation_quota.delete_many({"user_id": {"$in": ALL_TEST_USER_IDS}})
        await db.trips.delete_many({"user_id": {"$in": ALL_TEST_USER_IDS}})
    _run(_cleanup())


# ═══════════════════ Section A: live endpoint behavior ═══════════════════

def test_regenerate_nonexistent_trip_returns_404():
    r = requests.post(f"{BASE_URL}/api/trips/does_not_exist_{uuid.uuid4().hex[:8]}/regenerate/Premium",
                       headers=OWNER_HEADERS, timeout=10)
    assert r.status_code == 404, r.text


def test_regenerate_trip_owned_by_another_user_returns_404():
    """Ownership, not just existence, must be checked - a trip that exists
    but belongs to someone else must 404 the same way a missing one does,
    not e.g. 403 (which would confirm the trip_id is valid to a non-owner)."""
    trip_id = f"test_regen_trip_other_owner_{uuid.uuid4().hex[:8]}"
    plans = [_dummy_plan("Budget"), _dummy_plan("Premium"), _dummy_plan("Luxury")]
    _seed_trip(trip_id, OTHER_USER_ID, plans)

    r = requests.post(f"{BASE_URL}/api/trips/{trip_id}/regenerate/Premium", headers=OWNER_HEADERS, timeout=10)
    assert r.status_code == 404, r.text

    # The other user's trip must be completely untouched by the attempt.
    trip_doc = _fetch_trip(trip_id)
    assert trip_doc["plans"] == plans


def test_regenerate_invalid_plan_type_returns_400():
    trip_id = f"test_regen_trip_badtype_{uuid.uuid4().hex[:8]}"
    _seed_trip(trip_id, OWNER_USER_ID, [_dummy_plan("Budget"), _dummy_plan("Premium"), _dummy_plan("Luxury")])

    r = requests.post(f"{BASE_URL}/api/trips/{trip_id}/regenerate/NotATier", headers=OWNER_HEADERS, timeout=10)
    assert r.status_code == 400, r.text


def test_regenerate_quota_exceeded_blocks_before_real_work():
    """Same pattern as test_quota_exceeded_blocks_generate_endpoint_before_any_real_work:
    pre-exhaust the quota via a direct DB write, confirm the endpoint rejects
    fast (never reaching generate_single_plan / any provider call)."""
    trip_id = f"test_regen_trip_quota_{uuid.uuid4().hex[:8]}"
    _seed_trip(trip_id, OWNER_USER_ID, [_dummy_plan("Budget"), _dummy_plan("Premium"), _dummy_plan("Luxury")])
    _set_quota(OWNER_USER_ID, 5)

    start = time.time()
    r = requests.post(f"{BASE_URL}/api/trips/{trip_id}/regenerate/Premium", headers=OWNER_HEADERS, timeout=10)
    elapsed = time.time() - start

    assert r.status_code == 429, r.text
    data = r.json()
    assert data["reason"] in ("quota_exceeded", "rate_limited"), data
    if data["reason"] == "quota_exceeded":
        assert data["used"] == 5 and data["limit"] == 5
    assert elapsed < 5, f"took {elapsed:.1f}s - should short-circuit before any provider/Gemini call"

    # Confirm nothing was written - a blocked request must not touch the trip.
    trip_doc = _fetch_trip(trip_id)
    assert trip_doc["plans"][1]["plan_type"] == "Premium"
    assert trip_doc["plans"][1] == _dummy_plan("Premium")


def test_regenerate_rate_limit_kicks_in():
    """Dedicated user/session so this doesn't interfere with (or get
    interfered with by) the quota test above. Quota is pre-exhausted too, so
    every one of these stays a fast 429 regardless of which limit fires."""
    trip_id = f"test_regen_trip_ratelimit_{uuid.uuid4().hex[:8]}"
    _seed_trip(trip_id, STRESS_USER_ID, [_dummy_plan("Budget"), _dummy_plan("Premium"), _dummy_plan("Luxury")])
    _set_quota(STRESS_USER_ID, 5)

    reasons = []
    for _ in range(8):
        r = requests.post(f"{BASE_URL}/api/trips/{trip_id}/regenerate/Premium", headers=STRESS_HEADERS, timeout=10)
        assert r.status_code == 429, r.text
        reasons.append(r.json()["reason"])
    assert "rate_limited" in reasons, f"expected the per-minute limit to eventually trip: {reasons}"


@pytest.mark.timeout(60)
def test_regenerate_updates_only_target_tier():
    """End-to-end against the real Gemini call: seeds a trip where Premium
    previously failed (generation_failed=True, itinerary={}) with a valid
    cached anchor_pricing, regenerates just Premium, and confirms Budget/
    Luxury are byte-for-byte untouched while Premium now has a real plan.

    transportation="train" plus a pre-filled anchor_pricing means this makes
    exactly one real network call for the whole test (Gemini) - no Duffel,
    no SerpApi - since the endpoint should reuse the cached anchor rather
    than refetch pricing that's already known.
    """
    trip_id = f"test_regen_trip_real_{uuid.uuid4().hex[:8]}"
    budget_plan = _dummy_plan("Budget")
    luxury_plan = _dummy_plan("Luxury")
    premium_plan_before = {
        "plan_type": "Premium",
        "currency": "INR", "currency_symbol": "₹",
        "itinerary": {},
        "cost_breakdown": {"transportation": 0, "accommodation": 0, "food": 0, "activities": 0, "miscellaneous": 0},
        "total_cost": 0,
        "highlights": [], "budget_tips": [],
        "generation_failed": True,
        "error": "Premium plan generation failed, please try again.",
        "anchor_pricing": {
            "is_train": True,
            "flight_price": 0, "flight_airline": "", "flight_number": "",
            "flight_dep_time": "", "flight_arr_time": "", "flight_duration": "", "flight_stops": 0,
            "train_price": 1200.0, "train_name": "Superfast Express", "train_number": "Train",
            "train_class": "AC 3-Tier (3A)", "train_duration": "Varies by route",
            "hotel_name": "Test Anchor Hotel", "hotel_price_per_night": 5000.0,
            "hotel_stars": 4, "hotel_limited_inventory": False,
        },
    }
    preferences = {
        "destination": "Goa", "starting_location": "Mumbai",
        "departure_date": "2027-02-01", "return_date": "2027-02-04",
        "transportation": "train", "currency": "INR",
        "num_travelers": 1, "adults": 1, "children": 0, "seniors": 0,
        "budget_level": "Premium", "accommodation": ["hotel"], "interests": [],
        "trip_type": "leisure",
    }
    _seed_trip(trip_id, REAL_USER_ID, [budget_plan, premium_plan_before, luxury_plan], preferences=preferences)

    r = requests.post(f"{BASE_URL}/api/trips/{trip_id}/regenerate/Premium", headers=REAL_HEADERS, timeout=60)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["plan_type"] == "Premium"
    regenerated = body["plan"]
    assert regenerated.get("generation_failed") is not True, regenerated.get("error")
    assert regenerated["itinerary"], "regenerated plan should have a real itinerary, not the old empty one"
    assert regenerated["cost_breakdown"]["transportation"] > 0

    trip_doc = _fetch_trip(trip_id)
    plans_by_type = {p["plan_type"]: p for p in trip_doc["plans"]}
    assert plans_by_type["Budget"] == budget_plan, "Budget must be untouched by a Premium-only regenerate"
    assert plans_by_type["Luxury"] == luxury_plan, "Luxury must be untouched by a Premium-only regenerate"
    assert plans_by_type["Premium"].get("generation_failed") is not True
    assert plans_by_type["Premium"]["itinerary"]


# ═══════════ Section B: anchor-reuse contract (no live server, no cost) ═══════════

class _FakeModels:
    def __init__(self, response_text):
        self._response_text = response_text

    async def generate_content_stream(self, *args, **kwargs):
        async def _gen():
            yield SimpleNamespace(text=self._response_text)
        return _gen()


class _FakeGeminiClient:
    def __init__(self, response_text):
        self.aio = SimpleNamespace(models=_FakeModels(response_text))


async def _noop_log_usage(*args, **kwargs):
    return None


def _raise_if_called(name):
    async def _fn(*args, **kwargs):
        raise AssertionError(f"{name} should not be called when a cached anchor is supplied")
    return _fn


def test_generate_single_plan_reuses_cached_anchor_without_refetching(monkeypatch):
    """The whole point of caching anchor_pricing on each plan is so a
    single-tier regenerate skips Duffel/SerpApi - assert directly that
    passing `anchor=` means neither provider is ever touched, regardless of
    what generate_single_plan would otherwise have fetched."""
    import json

    well_formed_response = json.dumps({
        "plan_type": "Premium",
        "currency": "INR", "currency_symbol": "₹",
        "itinerary": {
            "day_1": {"date": "2027-02-01",
                      "transportation": {"mode": "train", "details": "Superfast Express", "cost": 1200},
                      "activities": [], "accommodation": {"name": "Test Anchor Hotel", "cost": 5000},
                      "meals": [{"time": "dinner", "restaurant": "Local", "cuisine": "Local", "cost": 500}],
                      "daily_total": 6700, "cumulative_total": 6700},
        },
        "cost_breakdown": {"transportation": 1200, "accommodation": 5000, "food": 500, "activities": 0, "miscellaneous": 0},
        "total_cost": 6700,
        "highlights": ["h1"], "budget_tips": ["t1"],
    })
    monkeypatch.setattr(server, "gemini_client", _FakeGeminiClient(well_formed_response))
    monkeypatch.setattr(server.usage_service, "log_usage", _noop_log_usage)
    monkeypatch.setattr(server.duffel_service, "get_anchor_flight", _raise_if_called("duffel_service.get_anchor_flight"))
    monkeypatch.setattr(server.serpapi_hotels_service, "search_hotels", _raise_if_called("serpapi_hotels_service.search_hotels"))

    cached_anchor = {
        "is_train": True,
        "flight_price": 0, "flight_airline": "", "flight_number": "",
        "flight_dep_time": "", "flight_arr_time": "", "flight_duration": "", "flight_stops": 0,
        "train_price": 1200.0, "train_name": "Superfast Express", "train_number": "Train",
        "train_class": "AC 3-Tier (3A)", "train_duration": "Varies by route",
        "hotel_name": "Test Anchor Hotel", "hotel_price_per_night": 5000.0,
        "hotel_stars": 4, "hotel_limited_inventory": False,
    }
    preferences = dict(
        destination="Goa", starting_location="Mumbai",
        departure_date="2027-02-01", return_date="2027-02-04",
        transportation="flight",  # deliberately mismatched vs. cached anchor's is_train=True -
                                  # proves the cached anchor wins and no fresh fetch is attempted
        currency="INR", num_travelers=1, adults=1, children=0, seniors=0,
    )

    result = asyncio.run(server.generate_single_plan(
        preferences, "Premium", "trip_test_regen", "user_test", anchor=cached_anchor
    ))

    assert result.get("generation_failed") is not True, result.get("error")
    assert result["anchor_pricing"] == cached_anchor
    assert result["cost_breakdown"]["transportation"] == 1200.0
