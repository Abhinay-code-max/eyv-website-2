"""
Tests the core money-path invariant behind generate_single_plan's post-
processing: cost_breakdown, total_cost, and every day's daily_total/
cumulative_total are ALWAYS recomputed server-side from the real per-line-
item costs (transportation/accommodation forced from the real anchor price,
food/activities summed from the day's own meals/activities entries) - never
trusted from whatever total-shaped numbers the AI itself put in its
response. See the comment above the recompute loop in server.py:
"Recalculate per-day totals AND the top-level cost_breakdown/total_cost from
the same pass over the (now anchor-corrected) itinerary, so the two can
never drift apart the way AI-authored daily_total/cumulative_total can."

Existing tests (test_cruise_pricing.py, test_one_way_flights.py) each prove
a slice of this for their own transport mode's anchor price specifically.
This test isolates the general mechanism: feeds a mocked Gemini response
whose day-level daily_total/cumulative_total AND top-level cost_breakdown/
total_cost are all deliberately wrong (an AI arithmetic mistake, or - worse -
an adversarial response trying to under/over-report the price), with only
the leaf-level numbers (meal costs, activity costs) correct, and asserts the
server's own recompute wins everywhere, not the AI's numbers.
"""
import asyncio
import json
import os
import sys

from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

import server  # noqa: E402

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')
USER_ID = "test_recompute_invariant_user"


def _db():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _run(coro):
    return asyncio.run(coro)


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


# Deliberately wrong on every total-shaped field the AI controls - each of
# these values would flow straight into what a user is billed if the server
# trusted them. Leaf-level meal/activity costs (which the server never
# recomputes independently of what the AI reported for them, only sums) are
# realistic so the expected recomputed totals are known/hand-computable.
FAKE_RESPONSE = json.dumps({
    "plan_type": "Premium", "currency": "INR", "currency_symbol": "₹",
    "itinerary": {
        "day_1": {
            "date": "2027-05-01",
            "transportation": {"mode": "flight", "details": "placeholder", "cost": 1},
            "accommodation": {"name": "placeholder", "type": "hotel", "cost": 1, "location": "Goa"},
            "meals": [{"time": "lunch", "restaurant": "A", "cuisine": "Local", "cost": 300},
                      {"time": "dinner", "restaurant": "B", "cuisine": "Local", "cost": 700}],
            "activities": [{"time": "10:00", "activity": "Museum", "location": "Goa", "cost": 200, "category": "paid", "pricing_type": "per_person"},
                           {"time": "16:00", "activity": "Beach walk", "location": "Goa", "cost": 150, "category": "paid", "pricing_type": "per_person"}],
            # Deliberately nonsense - must be overwritten by the recompute,
            # not trusted.
            "daily_total": 1, "cumulative_total": 1, "fixed_costs": 1, "variable_costs": 1,
        },
        "day_2": {
            "date": "2027-05-02",
            "transportation": {"mode": "flight", "details": "placeholder", "cost": 1},
            "accommodation": {"name": "placeholder", "type": "hotel", "cost": 1, "location": "Goa"},
            "meals": [{"time": "dinner", "restaurant": "C", "cuisine": "Local", "cost": 500}],
            "activities": [{"time": "11:00", "activity": "Market", "location": "Goa", "cost": 100, "category": "paid", "pricing_type": "per_person"}],
            "daily_total": 1, "cumulative_total": 1, "fixed_costs": 1, "variable_costs": 1,
        },
    },
    # Deliberately wrong/adversarial top-level totals - an under-reported
    # total_cost here is exactly the kind of thing that would undercharge a
    # real booking if the server ever trusted it outright.
    "cost_breakdown": {"transportation": 1, "accommodation": 1, "food": 1, "activities": 1, "miscellaneous": 99999},
    "total_cost": 1,
    "highlights": ["h1"], "budget_tips": ["t1"],
})


def _flight_anchor():
    return {
        "is_train": False, "is_cruise": False, "is_road": False, "is_one_way": False,
        "road_price": 0, "road_distance_km": 0, "road_vehicle_count": 1,
        "flight_price": 6000.0, "flight_airline": "Test Air", "flight_number": "TA101",
        "flight_dep_time": "09:00", "flight_arr_time": "11:30", "flight_duration": "2h 30m", "flight_stops": 0,
        "train_price": 0, "train_name": "", "train_number": "", "train_class": "", "train_duration": "",
        "cruise_price": 0, "cruise_cabin_type": "", "cruise_duration_label": "",
        "hotel_name": "Test Hotel", "hotel_price_per_night": 4000, "hotel_stars": 3, "hotel_limited_inventory": False,
    }


def test_server_recompute_overrides_wrong_ai_totals_everywhere(monkeypatch):
    monkeypatch.setattr(server, "db", _db())
    monkeypatch.setattr(server, "_get_gemini_client", lambda: _FakeGeminiClient(FAKE_RESPONSE))

    async def _noop_log_usage(*args, **kwargs):
        return None
    monkeypatch.setattr(server.usage_service, "log_usage", _noop_log_usage)

    preferences = {
        "destination": "Goa", "starting_location": "Mumbai",
        "departure_date": "2027-05-01", "return_date": "2027-05-02",
        "adults": 1, "children": 0, "seniors": 0, "num_travelers": 1,
        "transportation": "Flight", "currency": "INR",
    }
    plan = _run(server.generate_single_plan(
        preferences, "Premium", "test_trip_recompute_invariant", USER_ID, anchor=_flight_anchor()
    ))

    assert plan["status"] == "ready", plan

    # Hand-computed from the real anchor (flight 6000/leg, hotel 4000/night)
    # plus the leaf-level meal/activity costs above - transportation and
    # accommodation are forced per-day from the anchor (round-trip, so both
    # days), food/activities are summed from each day's own entries.
    day1 = plan["itinerary"]["day_1"]
    day2 = plan["itinerary"]["day_2"]

    assert day1["transportation"]["cost"] == 6000.0
    assert day1["accommodation"]["cost"] == 4000
    assert day1["daily_total"] == 6000.0 + 4000 + (300 + 700) + (200 + 150)  # 11350
    assert day1["cumulative_total"] == day1["daily_total"]

    assert day2["daily_total"] == 6000.0 + 4000 + 500 + 100  # 10600
    assert day2["cumulative_total"] == day1["daily_total"] + day2["daily_total"]  # 21950

    # Top-level cost_breakdown/total_cost must be the sum of the REAL
    # per-day numbers above, not the AI's "1"s, and not its 99999
    # "miscellaneous" - miscellaneous is always hardcoded 0 by the recompute,
    # never taken from the AI at all.
    assert plan["cost_breakdown"] == {
        "transportation": 12000.0,
        "accommodation": 8000,
        "food": 1500,
        "activities": 450,
        "miscellaneous": 0,
    }
    assert plan["total_cost"] == day2["cumulative_total"]
    assert plan["total_cost"] == 21950
