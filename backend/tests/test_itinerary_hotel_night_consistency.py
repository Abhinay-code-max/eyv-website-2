"""
Regression tests for the return_date off-by-one bug: itinerary generation
(server.py's generate_single_plan) used to charge return_date as its own
extra paid day - (return_date - departure_date).days + 1 itinerary days -
while hotel-search pricing (services/serpapi_hotels_service.py,
services/amadeus_service.py) always priced the identical date range at a
plain nights count, no +1. Same trip, two different accommodation totals
depending on which code path priced it.

Both sides now call the same function, services/date_utils.py's
trip_nights, so they can't independently drift back out of agreement with
each other the way they did before that existed - see that module's
docstring and the `nights` computation near the top of generate_single_plan.

Section A tests trip_nights directly. Section B drives generate_single_plan
end to end (Gemini mocked with a schema-valid, nights-days-exactly response -
proving post-processing PRESERVES whatever day count a correctly-shaped
response already has, it never adds/removes days) and compares its output
against amadeus_service._generate_mock_hotels's real nights/pricing for the
identical date range - both now go through trip_nights, so this is an
agreement check between two real call sites, not two copies of the same
one-line formula compared to themselves.
"""
import asyncio
import json
import os
import sys

from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server  # noqa: E402
from services import amadeus_service, date_utils  # noqa: E402

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')
USER_ID = "test_night_consistency_user"


def _db():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _run(coro):
    return asyncio.run(coro)


# ═══════════════════ Section A: trip_nights directly ═══════════════════

def test_trip_nights_is_plain_diff_no_plus_one():
    assert date_utils.trip_nights("2027-01-01", "2027-01-04") == 3
    assert date_utils.trip_nights("2027-01-01", "2027-01-02") == 1


def test_trip_nights_floors_at_one_for_same_day_or_backwards_range():
    assert date_utils.trip_nights("2027-01-01", "2027-01-01") == 1
    assert date_utils.trip_nights("2027-01-05", "2027-01-01") == 1


# ═══════════════════ Section B: generate_single_plan vs hotel search ═══════════════════

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


def _flight_anchor(flight_price, hotel_price_per_night):
    return {
        "is_train": False, "is_cruise": False, "is_road": False, "is_one_way": False,
        "road_price": 0, "road_distance_km": 0, "road_vehicle_count": 1,
        "flight_price": flight_price, "flight_airline": "Test Air", "flight_number": "TA101",
        "flight_dep_time": "09:00", "flight_arr_time": "11:30", "flight_duration": "2h 30m", "flight_stops": 0,
        "train_price": 0, "train_name": "", "train_number": "", "train_class": "", "train_duration": "",
        "cruise_price": 0, "cruise_cabin_type": "", "cruise_duration_label": "",
        "hotel_name": "Test Hotel", "hotel_price_per_night": hotel_price_per_night, "hotel_stars": 3,
        "hotel_limited_inventory": False,
    }


def _fixture_response_for_nights(nights):
    """Schema-valid response with exactly `nights` days - the shape a
    compliant Gemini response takes under generate_single_plan's own
    nights-based prompt instruction (same construction eval/run_eval.py's
    build_fixture_plan uses). Proves post-processing preserves whatever day
    count a correctly-shaped response already has - it edits values, never
    adds or removes days."""
    itinerary = {}
    for i in range(1, nights + 1):
        itinerary[f"day_{i}"] = {
            "date": "2027-06-01",
            "transportation": {"mode": "flight", "details": "placeholder", "cost": 0},
            "activities": [], "accommodation": {"name": "placeholder", "type": "hotel", "cost": 0, "location": "Goa"},
            "meals": [], "daily_total": 0, "cumulative_total": 0, "fixed_costs": 0, "variable_costs": 0,
        }
    return json.dumps({
        "plan_type": "Premium", "currency": "INR", "currency_symbol": "₹",
        "itinerary": itinerary,
        "cost_breakdown": {"transportation": 0, "accommodation": 0, "food": 0, "activities": 0, "miscellaneous": 0},
        "total_cost": 0, "highlights": ["h1"], "budget_tips": ["t1"],
    })


def _generate(monkeypatch, departure_date, return_date, nights, flight_price=6000.0, hotel_price_per_night=4000):
    monkeypatch.setattr(server, "db", _db())

    async def _noop_log_usage(*args, **kwargs):
        return None
    monkeypatch.setattr(server.usage_service, "log_usage", _noop_log_usage)

    fake_client = _FakeGeminiClient(_fixture_response_for_nights(nights))
    monkeypatch.setattr(server, "_get_gemini_client", lambda: fake_client)

    preferences = {
        "destination": "Goa", "starting_location": "Mumbai",
        "departure_date": departure_date, "return_date": return_date,
        "adults": 1, "children": 0, "seniors": 0, "num_travelers": 1,
        "transportation": "Flight", "currency": "INR",
    }
    return _run(server.generate_single_plan(
        preferences, "Premium", "test_trip_night_consistency", USER_ID,
        anchor=_flight_anchor(flight_price, hotel_price_per_night),
    ))


def test_multi_night_itinerary_day_count_matches_hotel_search_night_count(monkeypatch):
    """The core regression: for the SAME departure/return date pair, the
    itinerary's day count and hotel-search's night count must be identical,
    and accommodation pricing computed via either path (per-night rate x
    count) must match too."""
    departure_date, return_date = "2027-06-01", "2027-06-04"  # 3 nights
    hotel_price_per_night = 4000

    expected_nights = date_utils.trip_nights(departure_date, return_date)
    assert expected_nights == 3

    plan = _generate(monkeypatch, departure_date, return_date, expected_nights,
                      hotel_price_per_night=hotel_price_per_night)
    assert plan["status"] == "ready", plan

    hotels = amadeus_service._generate_mock_hotels("Goa", departure_date, return_date, 1)
    assert hotels
    hotel_search_nights = hotels[0]["nights"]

    assert len(plan["itinerary"]) == hotel_search_nights == expected_nights
    assert plan["cost_breakdown"]["accommodation"] == hotel_price_per_night * expected_nights
    # amadeus's own mock per-night rate is randomized, so compare its total
    # against ITS OWN per-night x nights, not our fixed hotel_price_per_night -
    # the property under test is the NIGHTS COUNT the two paths agree on,
    # not that they coincidentally used the same rate.
    assert hotels[0]["price"]["total"] == hotels[0]["price"]["per_night"] * hotel_search_nights


def test_single_night_round_trip_still_prices_both_legs(monkeypatch):
    """Edge case the fix must not regress: a 1-night stay collapses to a
    single itinerary day (matching hotel-search's own 1-night count for the
    identical date range) - a round trip must still fold BOTH transport legs
    onto that one day, not silently lose the return leg just because
    there's no separate "last day" left to put it on."""
    departure_date, return_date = "2027-06-01", "2027-06-02"
    flight_price = 6000.0

    expected_nights = date_utils.trip_nights(departure_date, return_date)
    assert expected_nights == 1

    plan = _generate(monkeypatch, departure_date, return_date, expected_nights, flight_price=flight_price)
    assert plan["status"] == "ready", plan

    hotels = amadeus_service._generate_mock_hotels("Goa", departure_date, return_date, 1)
    assert hotels[0]["nights"] == 1

    assert len(plan["itinerary"]) == 1 == hotels[0]["nights"]
    assert plan["itinerary"]["day_1"]["transportation"]["cost"] == flight_price * 2
    assert plan["cost_breakdown"]["transportation"] == flight_price * 2


def test_one_way_single_night_prices_only_outbound_leg(monkeypatch):
    """Control case for the edge case above: a one-way trip has no return
    leg to fold in at all, so a 1-night one-way stay's single day must stay
    at 1x the anchor price, not 2x."""
    departure_date, return_date = "2027-06-01", "2027-06-02"
    flight_price = 6000.0
    anchor = _flight_anchor(flight_price, 4000)
    anchor["is_one_way"] = True

    monkeypatch.setattr(server, "db", _db())

    async def _noop_log_usage(*args, **kwargs):
        return None
    monkeypatch.setattr(server.usage_service, "log_usage", _noop_log_usage)
    fake_client = _FakeGeminiClient(_fixture_response_for_nights(1))
    monkeypatch.setattr(server, "_get_gemini_client", lambda: fake_client)

    preferences = {
        "destination": "Goa", "starting_location": "Mumbai",
        "departure_date": departure_date, "return_date": return_date,
        "adults": 1, "children": 0, "seniors": 0, "num_travelers": 1,
        "transportation": "Flight", "currency": "INR",
    }
    plan = _run(server.generate_single_plan(
        preferences, "Premium", "test_trip_one_way_single_night", USER_ID, anchor=anchor,
    ))

    assert plan["status"] == "ready", plan
    assert len(plan["itinerary"]) == 1
    assert plan["itinerary"]["day_1"]["transportation"]["cost"] == flight_price
    assert plan["cost_breakdown"]["transportation"] == flight_price
