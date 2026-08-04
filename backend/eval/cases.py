"""
The 25-case golden eval set for AI trip generation (see run_eval.py).

Each case is a dict:
  id                 - short slug, also the replay fixture's cache key
  category            "structural" (matrix coverage) or "preference" (adherence)
  destination/starting_location/departure_date/return_date/transportation/
  plan_type/adults/interests/dietary_preferences/accessibility_requirements/
  travel_pace/road_*/cruise_*  - fed straight into generate_single_plan's
                                  `preferences` dict (mirrors TripPreferences)
  expected_days       - itinerary day count generate_single_plan should
                         produce for this date range: (return_date - departure_date).days + 1.
                         generate_single_plan treats return_date as its own full
                         itinerary day (accommodation is force-charged on every
                         day key including the last - server.py's post-processing),
                         confirmed both by two live-Gemini eval runs (a 3-day gap
                         consistently produced 4 itinerary days) and by two existing
                         tests that assert on real date-to-day-count behavior:
                         tests/test_pricing_recompute_invariant.py and
                         tests/test_cruise_pricing.py (both use a 1-day gap and
                         assert day_1 AND day_2 exist, each separately charged a
                         full night's accommodation).
                         NOTE: this is NOT the same convention the hotel-search
                         path uses - services/serpapi_hotels_service.py and
                         services/amadeus_service.py compute nights as a plain
                         (check_out - check_in).days, no +1. So a hotel search for
                         a given date range prices it at N nights, but that same
                         stay folded into a generated itinerary ends up charged for
                         N+1 nights (the extra day_N+1 entry's forced accommodation
                         cost). That mismatch is a real product inconsistency -
                         flagged separately, not something this eval set's
                         expected_days should try to paper over by picking a
                         convention that doesn't match what generate_single_plan
                         (the function under eval) actually does.
  preference_check    - present only on "preference" cases, see run_eval.py
                         for the check types this drives

The first 12 cases are a 3-tier x 4-transport-mode matrix (one destination
per mode rather than every destination x mode x tier combination, which
would be 100+ cases for no extra regression-catching value) - structural
assertions only (schema valid, day count, pricing fields populated).

The remaining 13 cases each set exactly one interests/dietary_preferences/
accessibility_requirements/travel_pace/road_* value and assert it actually
shows up in the generated activities/meals/highlights/transportation text,
not just that the prompt contains the word - see the task this eval set was
built for (interests/dietary/accessibility/pace were being collected but
allegedly never wired into the prompt; auditing server.py found they
already were, via traveler_preferences_block - these cases are the
regression guard for that wiring going forward, plus the road_* sub-fields
that genuinely were unwired until this change).
"""

MEAT_KEYWORDS = ["chicken", "mutton", "beef", "pork", "lamb", "fish", "seafood", "prawn", "shrimp"]
VEGAN_EXCLUDE_KEYWORDS = MEAT_KEYWORDS + ["egg", "cheese", "paneer", "butter", "ghee", "honey", "dairy"]


def _case(id, destination, starting_location, transportation, plan_type,
          departure_date, return_date, category="structural",
          adults=2, interests=None, dietary_preferences=None,
          accessibility_requirements=None, travel_pace=None,
          preference_check=None, **road_or_cruise_fields):
    from datetime import date
    d = date.fromisoformat(departure_date)
    r = date.fromisoformat(return_date)
    return {
        "id": id,
        "category": category,
        "destination": destination,
        "starting_location": starting_location,
        "departure_date": departure_date,
        "return_date": return_date,
        "transportation": transportation,
        "plan_type": plan_type,
        "budget_level": plan_type,
        "adults": adults,
        "children": 0,
        "seniors": 0,
        "accommodation": ["Hotel"],
        "interests": interests or [],
        "dietary_preferences": dietary_preferences,
        "accessibility_requirements": accessibility_requirements,
        "travel_pace": travel_pace,
        "trip_type": "Family" if adults > 1 else "Solo",
        "currency": "INR",
        "budget_mode": True,
        "expected_days": (r - d).days + 1,
        "preference_check": preference_check,
        **road_or_cruise_fields,
    }


CASES = [
    # ── Structural matrix: 3 tiers x 4 transport modes (12 cases) ──────────
    _case("structural_goa_flight_budget", "Goa", "Mumbai", "Flight", "Budget", "2026-09-01", "2026-09-04"),
    _case("structural_goa_flight_premium", "Goa", "Mumbai", "Flight", "Premium", "2026-09-01", "2026-09-04"),
    _case("structural_goa_flight_luxury", "Goa", "Mumbai", "Flight", "Luxury", "2026-09-01", "2026-09-04"),
    _case("structural_manali_road_budget", "Manali", "Delhi", "Road Trip", "Budget", "2026-09-10", "2026-09-14",
          road_route_style="Fastest", road_drivers=1, road_max_driving_hours_per_day=8),
    _case("structural_manali_road_premium", "Manali", "Delhi", "Road Trip", "Premium", "2026-09-10", "2026-09-14",
          road_route_style="Scenic", road_drivers=2, road_max_driving_hours_per_day=6),
    _case("structural_manali_road_luxury", "Manali", "Delhi", "Road Trip", "Luxury", "2026-09-10", "2026-09-14",
          road_route_style="Scenic", road_drivers=2, road_max_driving_hours_per_day=6),
    _case("structural_kerala_train_budget", "Kerala", "Chennai", "Train", "Budget", "2026-10-01", "2026-10-06"),
    _case("structural_kerala_train_premium", "Kerala", "Chennai", "Train", "Premium", "2026-10-01", "2026-10-06"),
    _case("structural_kerala_train_luxury", "Kerala", "Chennai", "Train", "Luxury", "2026-10-01", "2026-10-06"),
    _case("structural_andaman_cruise_budget", "Andaman Islands", "Chennai", "Cruise", "Budget", "2026-11-01", "2026-11-05",
          cruise_dining_style="Flexible anytime dining", cruise_itinerary_style="Island-hopping"),
    _case("structural_andaman_cruise_premium", "Andaman Islands", "Chennai", "Cruise", "Premium", "2026-11-01", "2026-11-05",
          cruise_dining_style="Flexible anytime dining", cruise_itinerary_style="Island-hopping"),
    _case("structural_andaman_cruise_luxury", "Andaman Islands", "Chennai", "Cruise", "Luxury", "2026-11-01", "2026-11-05",
          cruise_dining_style="Flexible anytime dining", cruise_itinerary_style="Island-hopping"),

    # ── Interest adherence (4 cases) ────────────────────────────────────────
    _case("interest_food_tours", "Bangkok", "Delhi", "Flight", "Premium", "2026-09-15", "2026-09-18",
          category="preference", interests=["Food tours"],
          preference_check={"type": "keyword_present",
                             "keywords": ["food", "cuisine", "tasting", "street food", "culinary"]}),
    _case("interest_wildlife", "Jim Corbett", "Delhi", "Road Trip", "Budget", "2026-09-20", "2026-09-23",
          category="preference", interests=["Wildlife & Nature"],
          road_route_style="Fastest", road_drivers=1,
          preference_check={"type": "keyword_present",
                             "keywords": ["wildlife", "safari", "national park", "nature", "forest", "jungle"]}),
    _case("interest_adventure_sports", "Rishikesh", "Delhi", "Road Trip", "Premium", "2026-09-25", "2026-09-28",
          category="preference", interests=["Adventure sports"],
          road_route_style="Scenic", road_drivers=1,
          preference_check={"type": "keyword_present",
                             "keywords": ["rafting", "trekking", "bungee", "zipline", "adventure", "rappelling", "kayak"]}),
    _case("interest_art_museums", "Paris", "Mumbai", "Flight", "Luxury", "2026-10-05", "2026-10-09",
          category="preference", interests=["Art & Museums"],
          preference_check={"type": "keyword_present",
                             "keywords": ["museum", "gallery", "art", "exhibit", "louvre"]}),

    # ── Dietary adherence (4 cases) ─────────────────────────────────────────
    _case("dietary_vegetarian", "Jaipur", "Delhi", "Flight", "Budget", "2026-09-12", "2026-09-15",
          category="preference", dietary_preferences="Vegetarian",
          preference_check={"type": "meal_keywords", "must_absent": MEAT_KEYWORDS,
                             "should_present": ["vegetarian", "veg"]}),
    _case("dietary_vegan", "Chennai", "Bengaluru", "Train", "Premium", "2026-09-18", "2026-09-21",
          category="preference", dietary_preferences="Vegan, no dairy or eggs",
          preference_check={"type": "meal_keywords", "must_absent": VEGAN_EXCLUDE_KEYWORDS,
                             "should_present": ["vegan"]}),
    _case("dietary_halal", "Dubai", "Mumbai", "Flight", "Premium", "2026-10-01", "2026-10-04",
          category="preference", dietary_preferences="Halal only",
          preference_check={"type": "meal_keywords", "must_absent": ["pork", "alcohol", "wine", "beer"],
                             "should_present": ["halal"]}),
    _case("dietary_gluten_free", "Rome", "Mumbai", "Flight", "Luxury", "2026-10-10", "2026-10-13",
          category="preference", dietary_preferences="Gluten-free, celiac",
          preference_check={"type": "meal_keywords", "must_absent": [],
                             "should_present": ["gluten-free", "gluten free"]}),

    # ── Accessibility adherence (2 cases) ───────────────────────────────────
    _case("accessibility_wheelchair", "Delhi", "Mumbai", "Flight", "Budget", "2026-09-08", "2026-09-11",
          category="preference", accessibility_requirements="Wheelchair user, need step-free access everywhere",
          preference_check={"type": "keyword_present",
                             "keywords": ["wheelchair", "step-free", "accessible", "ramp", "elevator"]}),
    _case("accessibility_limited_mobility", "Udaipur", "Ahmedabad", "Train", "Premium", "2026-09-22", "2026-09-25",
          category="preference", accessibility_requirements="Limited mobility, avoid long walks and stairs",
          preference_check={"type": "keyword_present",
                             "keywords": ["accessible", "minimal walking", "elevator", "avoid stairs", "short walk", "step-free"]}),

    # ── Pace adherence (2 cases) ────────────────────────────────────────────
    _case("pace_relaxed", "Maldives", "Mumbai", "Flight", "Luxury", "2026-11-10", "2026-11-14",
          category="preference", travel_pace="Relaxed",
          preference_check={"type": "activity_density", "max_avg_per_day": 2.5}),
    _case("pace_fast_paced", "Tokyo", "Delhi", "Flight", "Premium", "2026-11-15", "2026-11-19",
          category="preference", travel_pace="Fast-paced",
          preference_check={"type": "activity_density", "min_avg_per_day": 3.0}),

    # ── Road-trip sub-field adherence (1 case) - regression guard for the
    #    5 road_* fields that were genuinely unwired before this change ────
    _case("road_subfields", "Coorg", "Bengaluru", "Road Trip", "Budget", "2026-09-05", "2026-09-08",
          category="preference",
          road_food_preference="Local Karnataka cuisine", road_fuel_type="Electric",
          road_ev_battery_percent=40, road_max_hours_before_break=3, road_break_duration_minutes=20,
          preference_check={"type": "keyword_present",
                             "keywords": ["break", "charging", "ev", "electric", "recharge"]}),
]

assert len(CASES) == 25, f"expected 25 eval cases, got {len(CASES)}"
