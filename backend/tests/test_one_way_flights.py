"""
Tests for the "One-way trip" checkbox (frontend TripPlannerPage Trip Basics
step, formData.trip_direction) - previously absent from TripPreferences, so
Pydantic's extra="ignore" default silently dropped it from every request and
the checkbox had zero effect on generation, same class of bug the
cruise_cabin_type/road_* fields comments in server.py describe already
having hit.

Section A calls _fetch_anchor_pricing() directly (same pattern as
test_cruise_pricing.py's Section A) - cheap and deterministic, no live
server or Gemini call needed. Proves trip_direction="one_way" only flips
is_one_way for flight-anchored trips - train/cruise/road are all
hardcoded/computed single-leg estimates already, not a real fare that
return-leg booking changes.

Section B calls generate_single_plan() directly with a synthetic anchor and
a mocked Gemini response - proves a one-way trip's cost_breakdown.transportation
ends up 1x the anchor flight price (not the round-trip 2x) and the last
day's transportation cost is zeroed rather than left at whatever the AI
invented for a "return" leg that was never booked. Also covers the backward-
compat path: an old cached anchor_pricing dict with no "is_one_way" key at
all (pre-dating this field) must not crash and must fall back to round-trip
behavior - the same stale-fixture failure mode already seen with is_cruise.
"""
import asyncio
import os
import sys

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

import server  # noqa: E402

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')

USER_ID = "test_one_way_flights_user"


def _db():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _run(coro):
    return asyncio.run(coro)


async def _fake_search_flights(origin, destination, departure_date, return_date=None, travelers=1):
    return [{
        "airline": "Test Air", "flight_number": "TA101",
        "departure": {"time": "09:00"}, "arrival": {"time": "11:30"},
        "duration": "2h 30m", "duration_mins": 150, "stops": 0,
        "price": {"total": 6000.0},
    }]


async def _fake_search_hotels(*args, **kwargs):
    return [{"name": "Test Hotel", "price": {"per_night": 4000, "currency": "INR"}, "stars": 3}]


# ═══════════════════ Section A: _fetch_anchor_pricing direct ═══════════════════

def _get_flight_anchor(monkeypatch, trip_direction):
    monkeypatch.setattr(server, "db", _db())
    monkeypatch.setattr(server.duffel_service, "search_flights", _fake_search_flights)
    monkeypatch.setattr(server.serpapi_hotels_service, "search_hotels", _fake_search_hotels)

    prefs = {
        "starting_location": "Mumbai", "destination": "Goa",
        "departure_date": "2027-03-01", "return_date": "2027-03-08",
        "transportation": "Flight", "trip_direction": trip_direction,
    }
    fare_units = server._fare_units(1, 0, 0)
    room_count = server._room_count(1)
    return _run(server._fetch_anchor_pricing(prefs, "Budget", USER_ID, fare_units, room_count))


def test_one_way_preference_sets_is_one_way_flag(monkeypatch):
    anchor = _get_flight_anchor(monkeypatch, "one_way")
    assert anchor["is_one_way"] is True
    assert anchor["flight_price"] > 0


def test_round_trip_is_default_and_not_one_way(monkeypatch):
    anchor = _get_flight_anchor(monkeypatch, "round_trip")
    assert anchor["is_one_way"] is False


def test_missing_trip_direction_defaults_to_round_trip(monkeypatch):
    """No trip_direction at all (older/malformed preferences) must not crash
    and must behave like round_trip, matching the model's own default."""
    monkeypatch.setattr(server, "db", _db())
    monkeypatch.setattr(server.duffel_service, "search_flights", _fake_search_flights)
    monkeypatch.setattr(server.serpapi_hotels_service, "search_hotels", _fake_search_hotels)
    prefs = {
        "starting_location": "Mumbai", "destination": "Goa",
        "departure_date": "2027-03-01", "return_date": "2027-03-08",
        "transportation": "Flight",
    }
    fare_units = server._fare_units(1, 0, 0)
    room_count = server._room_count(1)
    anchor = _run(server._fetch_anchor_pricing(prefs, "Budget", USER_ID, fare_units, room_count))
    assert anchor["is_one_way"] is False


def test_one_way_has_no_effect_outside_flight_mode(monkeypatch):
    """trip_direction="one_way" on a Train trip must not set is_one_way - only
    flight is a real fare that a return leg changes; train/cruise/road are
    already single-leg hardcoded/computed estimates."""
    monkeypatch.setattr(server, "db", _db())
    monkeypatch.setattr(server.serpapi_hotels_service, "search_hotels", _fake_search_hotels)
    prefs = {
        "starting_location": "Mumbai", "destination": "Goa",
        "departure_date": "2027-03-01", "return_date": "2027-03-08",
        "transportation": "Train", "trip_direction": "one_way",
    }
    fare_units = server._fare_units(1, 0, 0)
    room_count = server._room_count(1)
    anchor = _run(server._fetch_anchor_pricing(prefs, "Budget", USER_ID, fare_units, room_count))
    assert anchor["is_train"] is True
    assert anchor["is_one_way"] is False


# ═══════════════════ Section B: generate_single_plan post-processing ═══════════════════

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


def _fake_two_day_response():
    import json as _json
    fake_day = lambda date, transport_cost: {
        "date": date,
        "transportation": {"mode": "flight", "details": "placeholder", "cost": transport_cost},
        "activities": [], "accommodation": {"name": "placeholder", "type": "hotel", "cost": 0, "location": "Goa"},
        "meals": [], "daily_total": 0, "cumulative_total": 0, "fixed_costs": 0, "variable_costs": 0,
    }
    return _json.dumps({
        "plan_type": "Premium", "currency": "INR", "currency_symbol": "₹",
        # The AI is never told this is one-way (no such prompt instruction
        # exists yet) - it invents its own nonzero "return flight" cost on
        # day_2, same as it always does for round trips. The fix has to
        # override that invented number down to 0, not just trust an AI
        # that was never asked to omit it.
        "itinerary": {"day_1": fake_day("2027-04-10", 0), "day_2": fake_day("2027-04-11", 5500)},
        "cost_breakdown": {"transportation": 0, "accommodation": 0, "food": 0, "activities": 0, "miscellaneous": 0},
        "total_cost": 0, "highlights": ["h1"], "budget_tips": ["t1"],
    })


def _flight_anchor(is_one_way):
    return {
        "is_train": False, "is_cruise": False, "is_road": False, "is_one_way": is_one_way,
        "road_price": 0, "road_distance_km": 0, "road_vehicle_count": 1,
        "flight_price": 6000.0, "flight_airline": "Test Air", "flight_number": "TA101",
        "flight_dep_time": "09:00", "flight_arr_time": "11:30", "flight_duration": "2h 30m", "flight_stops": 0,
        "train_price": 0, "train_name": "", "train_number": "", "train_class": "", "train_duration": "",
        "cruise_price": 0, "cruise_cabin_type": "", "cruise_duration_label": "",
        "hotel_name": "Test Hotel", "hotel_price_per_night": 4000, "hotel_stars": 3, "hotel_limited_inventory": False,
    }


def _run_generate(monkeypatch, anchor):
    monkeypatch.setattr(server, "db", _db())
    # server.gemini_client no longer exists as a plain module attribute since
    # the lazy-client refactor (_get_gemini_client(), an lru_cache-wrapped
    # factory) - patch that instead of the stale "server.gemini_client"
    # pattern the older cruise/regenerate tests still use (and currently
    # fail on for exactly this reason).
    fake_client = _FakeGeminiClient(_fake_two_day_response())
    monkeypatch.setattr(server, "_get_gemini_client", lambda: fake_client)

    async def _noop_log_usage(*args, **kwargs):
        return None
    monkeypatch.setattr(server.usage_service, "log_usage", _noop_log_usage)

    preferences = {
        "destination": "Goa", "starting_location": "Mumbai",
        "departure_date": "2027-04-10", "return_date": "2027-04-11",
        "adults": 1, "children": 0, "seniors": 0, "num_travelers": 1,
        "transportation": "Flight", "currency": "INR",
    }
    return _run(server.generate_single_plan(
        preferences, "Premium", "test_trip_one_way", USER_ID, anchor=anchor
    ))


def test_one_way_flight_zeroes_return_leg_and_total(monkeypatch):
    plan = _run_generate(monkeypatch, _flight_anchor(is_one_way=True))

    assert plan["status"] == "ready", plan
    assert plan["itinerary"]["day_2"]["transportation"]["cost"] == 0
    assert "one-way" in plan["itinerary"]["day_2"]["transportation"]["details"].lower()
    # The regression this guards: cost_breakdown.transportation must be 1x
    # the anchor flight price (day 1 only) - not 2x (the round-trip default)
    # and not the AI-invented 5500 the mocked response tried to sneak onto
    # day_2 above.
    assert plan["cost_breakdown"]["transportation"] == 6000.0
    assert plan["itinerary"]["day_1"]["transportation"]["cost"] == 6000.0


def test_round_trip_flight_still_doubles_return_leg(monkeypatch):
    """Regression guard: round-trip (is_one_way=False) behavior must be
    completely unchanged by this fix - both legs still get the anchor
    price, summing to 2x."""
    plan = _run_generate(monkeypatch, _flight_anchor(is_one_way=False))

    assert plan["status"] == "ready", plan
    assert plan["itinerary"]["day_1"]["transportation"]["cost"] == 6000.0
    assert plan["itinerary"]["day_2"]["transportation"]["cost"] == 6000.0
    assert plan["cost_breakdown"]["transportation"] == 12000.0


def test_stale_anchor_missing_is_one_way_key_falls_back_to_round_trip(monkeypatch):
    """Old cached anchor_pricing (e.g. a regenerate reusing a plan stored
    before this field existed) has no "is_one_way" key at all - must not
    KeyError, must behave like round-trip (the previous universal
    behavior), same stale-fixture shape as the pre-existing is_cruise gap."""
    anchor = _flight_anchor(is_one_way=False)
    del anchor["is_one_way"]

    plan = _run_generate(monkeypatch, anchor)

    assert plan["status"] == "ready", plan
    assert plan["itinerary"]["day_2"]["transportation"]["cost"] == 6000.0
    assert plan["cost_breakdown"]["transportation"] == 12000.0
