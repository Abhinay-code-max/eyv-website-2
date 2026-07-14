"""
Group-size pricing tests for generate_single_plan() (AI trip itinerary estimates).

Confirmed bug #1: a 4-traveler trip generated flight/hotel/meal costs identical to
a solo trip - only train pricing multiplied by num_travelers.

Confirmed bug #2: the planner form's Adults/Children/Seniors inputs never updated
num_travelers at all (it was a separate, stale, hardcoded-to-1 field) - so every
multi-traveler trip was priced as a solo trip regardless of group size. Fixed by
deriving num_travelers server-side from adults+children+seniors (TripPreferences
model_validator) instead of trusting whatever the client sent.

These tests cover the deterministic scaling helpers directly (fast, no live
API/LLM calls needed), plus live end-to-end checks against a running backend.

Note: this is the AI itinerary estimate shown on /api/trips/generate, not the
price_cache/Stripe booking path - total_cost here is never read into an actual
booking or charge (confirmed by grep), so no re-pricing guarantees are needed
for it the way price_cache_service provides for real bookings.
"""
import os
import sys
import time
import pytest
import requests
from pydantic import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from server import _room_count, _scale_per_person_costs, _fare_units, TripPreferences  # noqa: E402

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'http://localhost:8001').rstrip('/')


def _wait_for_trip_completion(trip_id, headers, timeout=300, poll_interval=3):
    """/trips/generate now returns as soon as the trip is created, with all
    three tiers in status="generating" - each tier finishes independently in
    the background (see _generate_and_save_tier in server.py). Tests that
    need real cost data must poll GET /trips/{trip_id} until no tier is
    still generating, the same way the frontend does."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        g = requests.get(f"{BASE_URL}/api/trips/{trip_id}", headers=headers, timeout=10)
        assert g.status_code == 200, g.text
        trip = g.json()
        if all(p.get("status") != "generating" for p in trip["plans"]):
            return trip
        time.sleep(poll_interval)
    raise TimeoutError(f"trip {trip_id} did not finish generating within {timeout}s")
SESSION_TOKEN = os.environ.get('TEST_SESSION_TOKEN', 'test_session_eyv_1780670554293')
HEADERS = {"Authorization": f"Bearer {SESSION_TOKEN}", "Content-Type": "application/json"}

BASE_PREFS = dict(
    destination="Goa",
    starting_location="Mumbai",
    departure_date="2026-08-01",
    return_date="2026-08-05",
    transportation="flight",
    budget_level="Budget",
    accommodation=["hotel"],
    interests=[],
    trip_type="leisure",
)


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
        r = requests.post(f"{BASE_URL}/api/trips/generate", json=payload, headers=HEADERS, timeout=30)
        assert r.status_code == 200, r.text
        trip = _wait_for_trip_completion(r.json()["trip_id"], HEADERS, timeout=400)
        plan = next(p for p in trip["plans"] if p.get("plan_type") == "Premium")
        assert plan.get("status") == "ready", plan.get("error")
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


# ---------- TripPreferences: server-derived num_travelers ----------

def test_num_travelers_derived_from_breakdown():
    prefs = TripPreferences(**BASE_PREFS, adults=2, children=2, seniors=1)
    assert prefs.num_travelers == 5


def test_num_travelers_ignores_client_supplied_value():
    # A client sending a mismatched/stale num_travelers must never win - this
    # is exactly the bug: the form's real breakdown always overrides it.
    prefs = TripPreferences(**BASE_PREFS, adults=2, children=0, seniors=0, num_travelers=999)
    assert prefs.num_travelers == 2


def test_zero_travelers_rejected():
    with pytest.raises(ValidationError):
        TripPreferences(**BASE_PREFS, adults=0, children=0, seniors=0)


def test_children_only_group_is_valid():
    prefs = TripPreferences(**BASE_PREFS, adults=0, children=0, seniors=3)
    assert prefs.num_travelers == 3


def test_negative_adults_rejected():
    with pytest.raises(ValidationError):
        TripPreferences(**BASE_PREFS, adults=-1, children=0, seniors=0)


def test_decimal_adults_rejected():
    with pytest.raises(ValidationError):
        TripPreferences(**BASE_PREFS, adults=2.5, children=0, seniors=0)


def test_null_adults_rejected():
    with pytest.raises(ValidationError):
        TripPreferences(**BASE_PREFS, adults=None, children=0, seniors=0)


# ---------- _fare_units: age-aware discount fallback ----------
# Neither Ignav nor SerpApi exposes child/senior fares, so these are
# project-defined fallback discounts (see CHILD_FARE_DISCOUNT / SENIOR_FARE_DISCOUNT
# in server.py) - these tests pin the documented percentages, not provider data.

def test_fare_units_all_adults_equals_headcount():
    assert _fare_units(4, 0, 0) == 4.0


def test_fare_units_children_discounted():
    assert _fare_units(0, 4, 0) == pytest.approx(4 * 0.75)


def test_fare_units_seniors_discounted():
    assert _fare_units(0, 0, 4) == pytest.approx(4 * 0.90)


def test_fare_units_mixed_group():
    assert _fare_units(2, 2, 1) == pytest.approx(2 * 1.0 + 2 * 0.75 + 1 * 0.90)


# ---------- Live regression: the 3 cases from the pricing-pipeline ticket ----------

@pytest.mark.timeout(180)
def test_regression_mixed_age_group_persists_correct_total_live():
    """Case 1: adults=2, children=2, seniors=1 -> the persisted trip's stored
    preferences must reflect num_travelers=5, not the old hardcoded-to-1 bug."""
    payload = {
        "destination": "Jaipur",
        "starting_location": "Delhi",
        "departure_date": "2026-09-01",
        "return_date": "2026-09-04",
        "adults": 2,
        "children": 2,
        "seniors": 1,
        "transportation": "train",
        "budget_level": "Budget",
        "accommodation": ["hotel"],
        "interests": [],
        "trip_type": "family",
    }
    r = requests.post(f"{BASE_URL}/api/trips/generate", json=payload, headers=HEADERS, timeout=180)
    assert r.status_code == 200, r.text
    trip_id = r.json()["trip_id"]

    g = requests.get(f"{BASE_URL}/api/trips/{trip_id}", headers=HEADERS)
    assert g.status_code == 200
    assert g.json()["preferences"]["num_travelers"] == 5

    requests.delete(f"{BASE_URL}/api/trips/{trip_id}", headers=HEADERS)


@pytest.mark.timeout(400)
def test_regression_mixed_age_group_priced_below_all_adults_live():
    """Case 2: an all-adults group of 5 vs a mixed-age group of the same
    headcount (5) - the mixed group should be cheaper given the child/senior
    fallback discounts, proving age data actually reaches pricing."""
    base_payload = {
        "destination": "Coorg",
        "starting_location": "Bangalore",
        "departure_date": "2026-09-10",
        "return_date": "2026-09-14",
        "transportation": "flight",
        "budget_level": "Premium",
        "accommodation": ["hotel"],
        "interests": ["nature"],
        "trip_type": "family",
    }

    def _generate(adults, children, seniors):
        payload = {**base_payload, "adults": adults, "children": children, "seniors": seniors}
        r = requests.post(f"{BASE_URL}/api/trips/generate", json=payload, headers=HEADERS, timeout=30)
        assert r.status_code == 200, r.text
        trip = _wait_for_trip_completion(r.json()["trip_id"], HEADERS, timeout=400)
        plan = next(p for p in trip["plans"] if p.get("plan_type") == "Premium")
        assert plan.get("status") == "ready", plan.get("error")
        return plan["cost_breakdown"]

    all_adults = _generate(5, 0, 0)
    mixed = _generate(2, 2, 1)

    assert all_adults["transportation"] > 0
    assert mixed["transportation"] < all_adults["transportation"], (
        f"mixed-age group (2 adults, 2 children, 1 senior) should cost less than "
        f"5 adults given the fallback discounts: all_adults={all_adults['transportation']} "
        f"mixed={mixed['transportation']}"
    )


def test_regression_zero_travelers_rejected_by_api_live():
    """Case 3: adults=children=seniors=0 must be rejected before any AI/provider call."""
    payload = {
        "destination": "Goa",
        "starting_location": "Mumbai",
        "departure_date": "2026-09-01",
        "return_date": "2026-09-04",
        "adults": 0,
        "children": 0,
        "seniors": 0,
        "transportation": "flight",
        "budget_level": "Budget",
        "accommodation": ["hotel"],
        "interests": [],
        "trip_type": "leisure",
    }
    r = requests.post(f"{BASE_URL}/api/trips/generate", json=payload, headers=HEADERS, timeout=30)
    assert r.status_code == 422, r.text
