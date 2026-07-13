"""
Group-size pricing tests for generate_single_plan() (AI trip itinerary estimates).

Confirmed bug: a 4-traveler trip generated flight/hotel/meal costs identical to
a solo trip - only train pricing multiplied by num_travelers. These tests cover
the deterministic scaling helpers directly (fast, no live API/LLM calls needed),
plus a live end-to-end check that generates real trips for 1 and 4 travelers.

Note: this is the AI itinerary estimate shown on /api/trips/generate, not the
price_cache/Stripe booking path - total_cost here is never read into an actual
booking or charge (confirmed by grep), so no re-pricing guarantees are needed
for it the way price_cache_service provides for real bookings.
"""
import os
import sys
import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from server import _room_count, _scale_per_person_costs  # noqa: E402

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'http://localhost:8001').rstrip('/')
SESSION_TOKEN = os.environ.get('TEST_SESSION_TOKEN', 'test_session_eyv_1780670554293')
HEADERS = {"Authorization": f"Bearer {SESSION_TOKEN}", "Content-Type": "application/json"}


# ---------- Room count (accommodation scales by rooms, not travelers) ----------

def test_room_count_single_traveler():
    assert _room_count(1) == 1


def test_room_count_two_travelers_share_one_room():
    assert _room_count(2) == 1


def test_room_count_four_travelers_need_two_rooms():
    assert _room_count(4) == 2


def test_room_count_odd_group_rounds_up():
    assert _room_count(5) == 3  # 2+2+1 -> 3 rooms, never round down and lose a bed


def test_room_count_never_scales_1to1_with_travelers():
    # The bug this guards against: accommodation must NOT multiply 1:1 with
    # traveler count - that would drastically overprice a shared room.
    assert _room_count(4) != 4


# ---------- Meal and activity scaling ----------

def _sample_itinerary():
    return {
        "day_1": {
            "meals": [
                {"time": "lunch", "cost": 300},
                {"time": "dinner", "cost": 800},
            ],
            "activities": [
                {"activity": "Museum entry", "cost": 200, "pricing_type": "per_person"},
                {"activity": "Private guided city tour", "cost": 3000, "pricing_type": "flat_group"},
                {"activity": "Untagged paid activity", "cost": 100},  # no pricing_type -> defaults to per_person
                {"activity": "Check-in", "cost": 0, "pricing_type": "flat_group"},
            ],
        }
    }


def test_meals_scale_by_traveler_count():
    itinerary = _sample_itinerary()
    _scale_per_person_costs(itinerary, num_travelers=4)
    meals = itinerary["day_1"]["meals"]
    assert meals[0]["cost"] == 300 * 4
    assert meals[1]["cost"] == 800 * 4


def test_meals_unchanged_for_single_traveler():
    itinerary = _sample_itinerary()
    _scale_per_person_costs(itinerary, num_travelers=1)
    meals = itinerary["day_1"]["meals"]
    assert meals[0]["cost"] == 300
    assert meals[1]["cost"] == 800


def test_per_person_activity_scales():
    itinerary = _sample_itinerary()
    _scale_per_person_costs(itinerary, num_travelers=4)
    acts = {a["activity"]: a["cost"] for a in itinerary["day_1"]["activities"]}
    assert acts["Museum entry"] == 200 * 4


def test_untagged_activity_defaults_to_per_person_and_scales():
    itinerary = _sample_itinerary()
    _scale_per_person_costs(itinerary, num_travelers=4)
    acts = {a["activity"]: a["cost"] for a in itinerary["day_1"]["activities"]}
    assert acts["Untagged paid activity"] == 100 * 4


def test_flat_group_activity_does_not_scale():
    itinerary = _sample_itinerary()
    _scale_per_person_costs(itinerary, num_travelers=4)
    acts = {a["activity"]: a["cost"] for a in itinerary["day_1"]["activities"]}
    assert acts["Private guided city tour"] == 3000  # unchanged


def test_zero_cost_activity_stays_zero_regardless_of_tag():
    itinerary = _sample_itinerary()
    _scale_per_person_costs(itinerary, num_travelers=4)
    acts = {a["activity"]: a["cost"] for a in itinerary["day_1"]["activities"]}
    assert acts["Check-in"] == 0


# ---------- Live end-to-end: 1 vs 4 travelers on the same trip ----------

@pytest.mark.timeout(400)
def test_group_pricing_scales_correctly_live():
    """Generate the same trip for 1 and 4 travelers and confirm:
    - flight cost roughly quadruples (each traveler needs their own fare)
    - accommodation scales by room count (~2x for 4 vs 1), not traveler count (~4x)
    - food cost roughly quadruples (each traveler eats their own meals)
    Tolerant ranges are used since both calls hit live flight/hotel providers
    and an LLM, so exact prices can drift slightly between the two live calls.
    """
    base_payload = {
        "destination": "Coorg",
        "starting_location": "Bangalore",
        "departure_date": "2026-07-12",
        "return_date": "2026-07-20",
        "children": 0,
        "seniors": 0,
        "transportation": "flight",
        "budget_level": "Premium",
        "accommodation": ["hotel"],
        "interests": ["nature"],
        "trip_type": "leisure",
    }

    def _generate(num_travelers):
        payload = {**base_payload, "num_travelers": num_travelers, "adults": num_travelers}
        r = requests.post(f"{BASE_URL}/api/trips/generate", json=payload, headers=HEADERS, timeout=400)
        assert r.status_code == 200, r.text
        plans = r.json()["plans"]
        plan = next(p for p in plans if p.get("plan_type") == "Premium")
        return plan["cost_breakdown"]

    solo = _generate(1)
    group = _generate(4)

    # Flight: each of the 4 travelers needs their own fare -> should be close to 4x
    assert solo["transportation"] > 0
    flight_ratio = group["transportation"] / solo["transportation"]
    assert 3.0 <= flight_ratio <= 5.0, (
        f"flight cost did not scale with travelers: solo={solo['transportation']} group={group['transportation']}"
    )

    # Accommodation: 4 travelers need 2 rooms (not 4x a single room)
    assert solo["accommodation"] > 0
    acc_ratio = group["accommodation"] / solo["accommodation"]
    assert 1.0 <= acc_ratio <= 3.0, (
        f"accommodation should scale by room count (~2x), not traveler count (~4x): "
        f"solo={solo['accommodation']} group={group['accommodation']}"
    )
    assert acc_ratio < flight_ratio, "accommodation must not scale as steeply as per-traveler pricing"

    # Food: each traveler eats their own meals -> should scale up meaningfully.
    # Wide tolerance because per-meal prices are LLM-invented independently in each
    # call (e.g. a "local eatery" might be priced 700 in one generation and 900 in
    # another) - we're checking it scales with headcount, not hitting an exact 4x.
    assert solo["food"] > 0
    food_ratio = group["food"] / solo["food"]
    assert 2.0 <= food_ratio <= 6.0, (
        f"meal cost did not scale with travelers: solo={solo['food']} group={group['food']}"
    )
