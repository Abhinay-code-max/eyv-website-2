"""
Tests for Cruise trip pricing - replacing the silent flight-anchor fallback
(Cruise fell through the is_train check straight into the real Duffel flight
branch) with an honest, clearly-labeled cruise fare estimate, the same way
Train already gets a hardcoded placeholder table instead of a real fetch.

Section A calls _fetch_anchor_pricing() directly (same pattern as
test_trip_regenerate.py's Section B) - cheap and deterministic, no live
server or Gemini call needed. duffel_service.get_anchor_flight is monkey-
patched to RAISE if called at all, so this is a hard regression guard against
cruise ever silently falling back to a real flight fetch again, not just an
absence-of-evidence check.

Section B calls _bookable_line_items() directly with a synthetic plan -
proves cruise is excluded from "Book this Plan" bundling even in the
adversarial case where anchor_pricing somehow still carried a nonzero
flight_price (i.e. the guard checks is_cruise explicitly, not just "flight_
price happens to be 0").

Section C hits the live server for ONE real end-to-end generation (3 Gemini
calls total) to prove the whole stack - HTTP endpoint, background tiers,
real Gemini call, bookability - together, and leaves the trip in place for
manual/Playwright frontend verification (deleted at teardown).
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

USER_ID, SESSION = "test_cruise_pricing_user", "test_cruise_pricing_session"
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
        token_hash = server._hash_session_token(SESSION)
        await db.user_sessions.update_one(
            {"session_token": token_hash},
            {"$set": {
                "session_token": token_hash, "user_id": USER_ID,
                "session_id": token_hash[:32],
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
        await db.user_sessions.delete_many({"session_token": server._hash_session_token(SESSION)})
        await db.generation_quota.delete_many({"user_id": USER_ID})
        await db.trips.delete_many({"user_id": USER_ID})
    _run(_cleanup())


async def _no_duffel_call(*args, **kwargs):
    raise AssertionError("duffel_service.get_anchor_flight must NOT be called for a Cruise trip")


async def _fake_search_hotels(*args, **kwargs):
    return [{"name": "Test Hotel", "price": {"per_night": 4000, "currency": "INR"}, "stars": 3}]


def _get_cruise_anchor(monkeypatch, plan_type, duration_pref):
    monkeypatch.setattr(server, "db", _db())
    monkeypatch.setattr(server.duffel_service, "get_anchor_flight", _no_duffel_call)
    monkeypatch.setattr(server.serpapi_hotels_service, "search_hotels", _fake_search_hotels)

    prefs = {
        "starting_location": "Mumbai", "destination": "Goa",
        "departure_date": "2027-03-01", "return_date": "2027-03-08",
        "transportation": "Cruise",
        "cruise_duration_preference": duration_pref,
    }
    fare_units = server._fare_units(1, 0, 0)
    room_count = server._room_count(1)
    return _run(server._fetch_anchor_pricing(prefs, plan_type, USER_ID, fare_units, room_count))


# ═══════════════════ Section A: _fetch_anchor_pricing direct ═══════════════════

def test_cruise_never_calls_duffel_flight_fallback(monkeypatch):
    """The core bug fix: selecting Cruise must not silently price/anchor as
    a flight. duffel_service.get_anchor_flight raises if invoked at all."""
    anchor = _get_cruise_anchor(monkeypatch, "Budget", "Week-long (6-9 nights)")
    assert anchor["is_cruise"] is True
    assert anchor["is_train"] is False
    assert anchor["flight_price"] == 0
    assert anchor["flight_airline"] == ""
    assert anchor["flight_number"] == ""


def test_cruise_price_is_positive_and_estimate_not_zero(monkeypatch):
    anchor = _get_cruise_anchor(monkeypatch, "Premium", "Week-long (6-9 nights)")
    assert anchor["cruise_price"] > 0


@pytest.mark.parametrize("plan_type,expected_cabin", [
    ("Budget", "Interior"),
    ("Premium", "Balcony"),
    ("Luxury", "Suite"),
])
def test_tier_drives_cabin_type(monkeypatch, plan_type, expected_cabin):
    """Budget -> Interior, Premium -> Balcony, Luxury -> Suite, per the
    proposed/approved tier mapping - cabin is tier-driven, not taken from
    any user-selected cabin preference (that would break monotonic tier
    pricing)."""
    anchor = _get_cruise_anchor(monkeypatch, plan_type, "Week-long (6-9 nights)")
    assert anchor["cruise_cabin_type"] == expected_cabin


def test_cruise_price_increases_with_tier(monkeypatch):
    """Budget < Premium < Luxury for the SAME duration - proves the cabin-
    multiplier table actually orders Interior < Balcony < Suite in price,
    not just that they differ."""
    budget = _get_cruise_anchor(monkeypatch, "Budget", "Week-long (6-9 nights)")
    premium = _get_cruise_anchor(monkeypatch, "Premium", "Week-long (6-9 nights)")
    luxury = _get_cruise_anchor(monkeypatch, "Luxury", "Week-long (6-9 nights)")
    assert budget["cruise_price"] < premium["cruise_price"] < luxury["cruise_price"]


def test_cruise_price_varies_by_duration_preference(monkeypatch):
    """Same tier (same cabin), different duration preference -> different
    total price, proving the duration axis of the table is actually wired
    in, not just accepted and ignored."""
    short = _get_cruise_anchor(monkeypatch, "Premium", "Short getaway (2-5 nights)")
    extended = _get_cruise_anchor(monkeypatch, "Premium", "Extended voyage (10+ nights)")
    assert short["cruise_price"] != extended["cruise_price"]
    assert short["cruise_price"] > 0 and extended["cruise_price"] > 0


class _FakeChunk:
    def __init__(self, text):
        self.text = text


class _FakeModels:
    def __init__(self, response_json):
        self._response_json = response_json

    async def generate_content_stream(self, **kwargs):
        async def _gen():
            yield _FakeChunk(self._response_json)
        return _gen()


class _FakeGeminiClient:
    def __init__(self, response_json):
        self.aio = type("_Aio", (), {"models": _FakeModels(response_json)})()


def test_cruise_price_survives_generate_single_plan_post_processing(monkeypatch):
    """Deterministic, zero-Gemini-quota regression test for the exact bug
    caught by the live end-to-end run: generate_single_plan sets the anchor
    transport cost on BOTH day 1 (outbound) and the last day (return) and
    sums both into cost_breakdown.transportation - correct for train/flight's
    one-way fares, but a cruise voyage is one continuous price, so
    _fetch_anchor_pricing has to hand back a HALVED per-leg figure for the
    doubling to reconstruct the right total. Mocks Gemini's response
    entirely (a minimal but validly-shaped 2-day plan) so this needs no live
    API call and never touches the 20/day free-tier quota."""
    monkeypatch.setattr(server, "db", _db())

    anchor = {
        "is_train": False, "is_cruise": True,
        "flight_price": 0, "flight_airline": "", "flight_number": "",
        "flight_dep_time": "", "flight_arr_time": "", "flight_duration": "", "flight_stops": 0,
        "train_price": 0, "train_name": "", "train_number": "", "train_class": "", "train_duration": "",
        "cruise_price": 28000.0, "cruise_cabin_type": "Balcony", "cruise_duration_label": "Week-long (6-9 nights)",
        "hotel_name": "Test Hotel", "hotel_price_per_night": 4000, "hotel_stars": 3, "hotel_limited_inventory": False,
    }

    import json as _json
    fake_day = lambda date: {
        "date": date,
        "transportation": {"mode": "cruise", "details": "placeholder", "cost": 0},
        "activities": [], "accommodation": {"name": "placeholder", "type": "hotel", "cost": 0, "location": "Goa"},
        "meals": [], "daily_total": 0, "cumulative_total": 0, "fixed_costs": 0, "variable_costs": 0,
    }
    fake_response = _json.dumps({
        "plan_type": "Premium", "currency": "INR", "currency_symbol": "₹",
        "itinerary": {"day_1": fake_day("2027-04-10"), "day_2": fake_day("2027-04-11")},
        "cost_breakdown": {"transportation": 0, "accommodation": 0, "food": 0, "activities": 0, "miscellaneous": 0},
        "total_cost": 0, "highlights": ["h1"], "budget_tips": ["t1"],
    })
    monkeypatch.setattr(server, "gemini_client", _FakeGeminiClient(fake_response))

    preferences = {
        "destination": "Goa", "starting_location": "Mumbai",
        "departure_date": "2027-04-10", "return_date": "2027-04-11",
        "adults": 1, "children": 0, "seniors": 0, "num_travelers": 1,
        "transportation": "Cruise", "currency": "INR",
    }
    plan = _run(server.generate_single_plan(preferences, "Premium", "test_trip_cruise_postproc", USER_ID, anchor=anchor))

    assert plan["status"] == "ready", plan
    assert plan["cruise_placeholder_pricing"] is True
    assert "train_placeholder_pricing" not in plan
    # The regression this guards: cost_breakdown.transportation must be
    # 2x the per-leg anchor (outbound + return), matching what a real 2-day
    # itinerary produces - not 4x (the bug) and not 1x (an over-correction).
    assert plan["cost_breakdown"]["transportation"] == anchor["cruise_price"] * 2
    assert plan["itinerary"]["day_1"]["transportation"]["mode"] == "cruise"
    assert plan["itinerary"]["day_1"]["transportation"]["cost"] == anchor["cruise_price"]
    assert plan["itinerary"]["day_2"]["transportation"]["cost"] == anchor["cruise_price"]
    assert "Balcony" in plan["itinerary"]["day_1"]["transportation"]["details"]


def test_cruise_missing_duration_preference_falls_back_to_default(monkeypatch):
    """Older/malformed preferences with no cruise_duration_preference at all
    must not crash - falls back to the Week-long default, matching the
    frontend's own default for that field."""
    monkeypatch.setattr(server, "db", _db())
    monkeypatch.setattr(server.duffel_service, "get_anchor_flight", _no_duffel_call)
    monkeypatch.setattr(server.serpapi_hotels_service, "search_hotels", _fake_search_hotels)
    prefs = {
        "starting_location": "Mumbai", "destination": "Goa",
        "departure_date": "2027-03-01", "return_date": "2027-03-08",
        "transportation": "Cruise",
    }
    fare_units = server._fare_units(1, 0, 0)
    room_count = server._room_count(1)
    anchor = _run(server._fetch_anchor_pricing(prefs, "Budget", USER_ID, fare_units, room_count))
    assert anchor["cruise_price"] > 0
    assert anchor["cruise_duration_label"] == "Week-long (6-9 nights)"


# ═══════════════════ Section B: _bookable_line_items direct ═══════════════════

def test_cruise_plan_excludes_flight_line_item():
    plan = {
        "anchor_pricing": {
            "is_train": False, "is_cruise": True,
            "flight_price": 0, "hotel_price_per_night": 4000,
            "hotel_name": "Test Hotel", "hotel_stars": 3,
        },
        "cost_breakdown": {"transportation": 63000, "accommodation": 4000},
    }
    items = server._bookable_line_items(plan)
    types = {i["type"] for i in items}
    assert "flight" not in types
    assert "cruise" not in types
    assert types == {"hotel"}


def test_cruise_plan_stays_unbookable_even_if_flight_price_leaked():
    """Adversarial regression guard: even if anchor_pricing somehow still
    carried a nonzero flight_price (e.g. a future refactor reintroduces the
    fallthrough), is_cruise=True must still suppress the flight line-item -
    the guard must check is_cruise explicitly, not just infer "not a real
    flight" from flight_price being 0."""
    plan = {
        "anchor_pricing": {
            "is_train": False, "is_cruise": True,
            "flight_price": 999999, "flight_airline": "SHOULD NOT APPEAR",
            "flight_number": "SHOULD-NOT-APPEAR",
            "hotel_price_per_night": 4000, "hotel_name": "Test Hotel", "hotel_stars": 3,
        },
        "cost_breakdown": {"transportation": 999999, "accommodation": 4000},
    }
    items = server._bookable_line_items(plan)
    assert all(i["type"] != "flight" for i in items)


# ═══════════════════ Section C: one real end-to-end generation ═══════════════════

def test_cruise_end_to_end_generation_and_booking():
    """The one real (Gemini-calling) test in this file: generates a real
    3-tier Cruise trip through the live HTTP endpoint, waits for all tiers,
    and confirms no flight-anchor leakage anywhere in the persisted plans,
    then confirms bundled booking excludes the cruise line-item. Left in
    the DB until teardown so it can also be used for a frontend/Playwright
    screenshot check of the same trip_id."""
    payload = {
        "destination": "Goa", "starting_location": "Mumbai",
        "departure_date": "2027-04-10", "return_date": "2027-04-17",
        "adults": 1, "children": 0, "seniors": 0,
        "transportation": "Cruise",
        "cruise_cabin_type": "Balcony",
        "cruise_duration_preference": "Week-long (6-9 nights)",
        "cruise_dining_style": "Specialty dining focus",
        "cruise_itinerary_style": "Island-hopping",
        "budget_level": "Premium", "accommodation": ["Hotel"], "interests": ["Beaches"],
        "trip_type": "Solo",
    }
    r = requests.post(f"{BASE_URL}/api/trips/generate", json=payload, headers=HEADERS, timeout=15)
    assert r.status_code == 200, r.text
    trip_id = r.json()["trip_id"]

    # Poll until all three tiers leave "generating" (ready or failed).
    deadline = time.time() + 120
    plans = []
    while time.time() < deadline:
        g = requests.get(f"{BASE_URL}/api/trips/{trip_id}", headers=HEADERS, timeout=10)
        assert g.status_code == 200, g.text
        plans = g.json()["plans"]
        if all(p["status"] != "generating" for p in plans):
            break
        time.sleep(3)

    assert all(p["status"] != "generating" for p in plans), "generation did not finish in time"
    ready_plans = [p for p in plans if p["status"] == "ready"]
    assert ready_plans, f"no tier finished successfully: {[(p['plan_type'], p.get('error')) for p in plans]}"

    cabin_by_tier = {}
    for p in ready_plans:
        anchor = p.get("anchor_pricing", {})
        assert anchor.get("is_cruise") is True, f"{p['plan_type']}: is_cruise not set"
        assert anchor.get("is_train") is False
        assert anchor.get("flight_price", 0) == 0, f"{p['plan_type']}: flight-anchor leakage, flight_price={anchor.get('flight_price')}"
        assert anchor.get("flight_airline", "") == "", f"{p['plan_type']}: flight-anchor leakage, flight_airline={anchor.get('flight_airline')}"
        assert anchor.get("cruise_price", 0) > 0
        assert p.get("cruise_placeholder_pricing") is True
        # cruise_price is a per-leg (half-voyage) anchor, deliberately halved
        # in _fetch_anchor_pricing because generate_single_plan sets it on
        # BOTH day 1 (outbound) and the last day (return) and sums both into
        # cost_breakdown.transportation - same mechanism as train/flight's
        # one-way fares doubling into a round-trip total. This is a multi-
        # day trip (2027-04-10 to 2027-04-17), so the doubling applies.
        assert p["cost_breakdown"]["transportation"] == anchor["cruise_price"] * 2
        cabin_by_tier[p["plan_type"]] = anchor["cruise_cabin_type"]

    expected_cabin = {"Budget": "Interior", "Premium": "Balcony", "Luxury": "Suite"}
    for plan_type, cabin in cabin_by_tier.items():
        assert cabin == expected_cabin[plan_type], f"{plan_type}: expected cabin {expected_cabin[plan_type]}, got {cabin}"

    # Bundled booking must never include a cruise/flight line-item, matching
    # whatever the real hotel fetch actually returned for this tier.
    booked_tier = ready_plans[0]
    anchor = booked_tier.get("anchor_pricing", {})
    b = requests.post(f"{BASE_URL}/api/trips/{trip_id}/book/{booked_tier['plan_type']}", headers=HEADERS, timeout=10)
    if anchor.get("hotel_price_per_night", 0) > 0 and booked_tier["cost_breakdown"].get("accommodation", 0) > 0:
        assert b.status_code == 200, b.text
        line_item_types = {i["type"] for i in b.json()["line_items"]}
        assert line_item_types == {"hotel"}, f"expected hotel-only bundle, got {line_item_types}"
    else:
        # Real hotel fetch failed for this run (external dependency) - then
        # nothing at all should be bookable, which is still a pass of the
        # "cruise itself is never bookable" invariant.
        assert b.status_code == 400, b.text

    requests.delete(f"{BASE_URL}/api/trips/{trip_id}", headers=HEADERS, timeout=10)
