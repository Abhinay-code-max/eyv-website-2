"""
Golden eval set runner for AI trip generation (backend/eval/cases.py has the
25 cases). Run with `make eval` from the repo root, or directly:

    cd backend && python eval/run_eval.py

Two modes:

  Replay (default) - generate_single_plan's Gemini call is mocked to return
  a hand-built, schema-valid canned response per case (see build_fixture_plan
  below), and flight/hotel provider pricing is bypassed entirely by passing
  a synthetic `anchor` straight into generate_single_plan (same mechanism
  the per-tier regenerate endpoint uses to skip Step 1). Zero cost, zero
  external calls, deterministic - this is what CI should run on every prompt
  change. It regression-tests the pipeline AROUND the model call: schema
  validation, day-count math, pricing-field population, and the preference-
  adherence *check logic* itself - it does NOT prove the real Gemini model
  actually honors a given prompt, because the fixture text is authored to
  satisfy the checks by construction.

  Live (--live) - hits the real Gemini API for each selected case, still
  with a synthetic anchor (so no Duffel/SerpApi spend). This is the only
  mode that actually proves prompt changes still produce preference-adherent
  output. The Gemini API key backing this app is on a 20-requests/day free
  tier shared with the rest of the app (chat, real trip generation, etc.) -
  running all 25 cases live, some of which retry up to 3x on failure, could
  exhaust the entire day's quota by itself. Use --cases to run a small,
  targeted subset live (e.g. just the preference-adherence cases most
  affected by a prompt edit) rather than the full set, and don't wire --live
  into CI.
"""
import argparse
import asyncio
import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server  # noqa: E402
from eval.cases import CASES  # noqa: E402


# ── Fake Gemini client (replay mode) - same pattern as tests/test_plan_generation_crash.py ──

class _FakeModels:
    def __init__(self, response_text):
        self._response_text = response_text

    async def generate_content_stream(self, *args, **kwargs):
        async def _gen():
            yield SimpleNamespace(text=self._response_text)
        return _gen()


class _FakeAio:
    def __init__(self, response_text):
        self.models = _FakeModels(response_text)


class _FakeGeminiClient:
    def __init__(self, response_text):
        self.aio = _FakeAio(response_text)


async def _noop(*args, **kwargs):
    return None


# ── Synthetic anchor - bypasses real Duffel/SerpApi calls in both modes ──────

def _build_anchor(case) -> dict:
    transportation = case["transportation"].lower()
    is_train = "train" in transportation
    is_cruise = "cruise" in transportation
    is_road = "road" in transportation
    is_flight = not (is_train or is_cruise or is_road)
    hotel_price = {"Budget": 2500, "Premium": 6000, "Luxury": 15000}[case["plan_type"]]
    return {
        "is_train": is_train, "is_cruise": is_cruise, "is_road": is_road, "is_one_way": False,
        "road_price": 3500 if is_road else 0, "road_distance_km": 450 if is_road else 0,
        "road_vehicle_count": 1, "road_origin_coords": None, "road_dest_coords": None,
        "flight_price": 8000 if is_flight else 0, "flight_airline": "IndiGo", "flight_number": "6E-204",
        "flight_dep_time": "08:00", "flight_arr_time": "10:15", "flight_duration": "2h 15m", "flight_stops": 0,
        "train_price": 1800 if is_train else 0, "train_name": "Superfast Express", "train_number": "12621",
        "train_class": "3AC", "train_duration": "14h",
        "cruise_price": 25000 if is_cruise else 0, "cruise_cabin_type": "Ocean View", "cruise_duration_label": "4 nights",
        "hotel_name": f"{case['destination']} Stay", "hotel_price_per_night": hotel_price, "hotel_stars": 3,
        "hotel_limited_inventory": False,
    }


def _anchor_transport(anchor):
    if anchor["is_train"]:
        return anchor["train_price"], "train", f"{anchor['train_name']} ({anchor['train_class']})"
    if anchor["is_cruise"]:
        return anchor["cruise_price"], "cruise", f"{anchor['cruise_cabin_type']} cabin cruise"
    if anchor["is_road"]:
        return anchor["road_price"], "road", f"Self-drive ({anchor['road_distance_km']:.0f} km)"
    return anchor["flight_price"], "flight", f"{anchor['flight_airline']} {anchor['flight_number']}"


def _flavor_text(pref: dict) -> str:
    if not pref:
        return ""
    if pref["type"] == "keyword_present":
        return pref["keywords"][0]
    if pref["type"] == "meal_keywords" and pref.get("should_present"):
        return pref["should_present"][0]
    return ""


def build_fixture_plan(case: dict, anchor: dict) -> dict:
    """A hand-built, schema-valid canned Gemini response for replay mode -
    see the module docstring for what this does and doesn't prove."""
    days = max(case["expected_days"], 1)
    transport_price, transport_mode, transport_detail = _anchor_transport(anchor)
    hotel_price = anchor["hotel_price_per_night"]
    pref = case.get("preference_check")
    flavor = _flavor_text(pref)

    itinerary = {}
    for i in range(1, days + 1):
        activity_text = f"Explore {case['destination']} - day {i} highlights"
        meal_cuisine = "Local"
        if flavor:
            if pref["type"] == "meal_keywords":
                meal_cuisine = flavor
            else:
                activity_text = f"{activity_text}, including {flavor}"

        activities = [{
            "time": "10:00", "activity": activity_text, "location": case["destination"],
            "cost": 500, "category": "sightseeing", "pricing_type": "per_person",
        }]
        if pref and pref["type"] == "activity_density":
            target = 4 if "min_avg_per_day" in pref else 1
            while len(activities) < target:
                n = len(activities) + 1
                activities.append({
                    "time": f"{9 + n * 2}:00", "activity": f"{case['destination']} activity {n}",
                    "location": case["destination"], "cost": 300, "category": "leisure", "pricing_type": "per_person",
                })

        itinerary[f"day_{i}"] = {
            "date": case["departure_date"],
            "transportation": {
                "mode": transport_mode, "details": transport_detail,
                "cost": transport_price if i in (1, days) else 0,
            },
            "activities": activities,
            "accommodation": {"name": anchor["hotel_name"], "type": "hotel", "cost": hotel_price, "location": case["destination"]},
            "meals": [{"time": "dinner", "restaurant": f"{case['destination']} Restaurant", "cuisine": meal_cuisine, "cost": 400}],
        }

    return {
        "plan_type": case["plan_type"], "currency": "INR", "currency_symbol": "₹",
        "itinerary": itinerary,
        "cost_breakdown": {
            "transportation": transport_price, "accommodation": hotel_price * days,
            "food": 400 * days, "activities": 500 * days, "miscellaneous": 0,
        },
        "total_cost": transport_price + hotel_price * days + 400 * days + 500 * days,
        "highlights": [f"{case['destination']} highlight" + (f" - {flavor}" if flavor else "")],
        "budget_tips": ["Book in advance", "Travel off-season"],
    }


# ── Assertions ─────────────────────────────────────────────────────────────

def _all_text(result: dict) -> str:
    parts = list(result.get("highlights", [])) + list(result.get("budget_tips", []))
    for day in result.get("itinerary", {}).values():
        parts.append(day.get("transportation", {}).get("details", ""))
        parts.append(day.get("accommodation", {}).get("name", ""))
        for act in day.get("activities", []):
            parts.append(act.get("activity", ""))
            parts.append(act.get("category", ""))
        for meal in day.get("meals", []):
            parts.append(meal.get("cuisine", ""))
            parts.append(meal.get("restaurant", ""))
    return " ".join(str(p) for p in parts).lower()


def _meal_text(result: dict) -> str:
    parts = []
    for day in result.get("itinerary", {}).values():
        for meal in day.get("meals", []):
            parts.append(meal.get("cuisine", ""))
            parts.append(meal.get("restaurant", ""))
    return " ".join(str(p) for p in parts).lower()


def check_structural(case: dict, result: dict) -> list:
    if result.get("generation_failed") or result.get("status") != "ready":
        return [f"generation failed: {result.get('error')}"]
    problems = []
    itinerary = result.get("itinerary", {})
    if len(itinerary) != case["expected_days"]:
        problems.append(f"day count = {len(itinerary)}, expected {case['expected_days']}")
    if not (result.get("total_cost") or 0) > 0:
        problems.append(f"total_cost not populated: {result.get('total_cost')}")
    cb = result.get("cost_breakdown", {})
    for key in ("transportation", "accommodation", "food", "activities", "miscellaneous"):
        if key not in cb:
            problems.append(f"cost_breakdown missing '{key}'")
    return problems


def check_preference(case: dict, result: dict) -> tuple:
    pref = case["preference_check"]
    if pref["type"] == "keyword_present":
        text = _all_text(result)
        found = any(k.lower() in text for k in pref["keywords"])
        return found, "" if found else f"expected one of {pref['keywords']} in generated text"

    if pref["type"] == "meal_keywords":
        text = _meal_text(result)
        absent_violations = [k for k in pref["must_absent"] if k.lower() in text]
        present_ok = not pref["should_present"] or any(k.lower() in text for k in pref["should_present"])
        detail = []
        if absent_violations:
            detail.append(f"found disallowed meal keywords: {absent_violations}")
        if not present_ok:
            detail.append(f"expected one of {pref['should_present']} in meal text")
        return (not absent_violations and present_ok), "; ".join(detail)

    if pref["type"] == "activity_density":
        itinerary = result.get("itinerary", {})
        total_activities = sum(len(d.get("activities", [])) for d in itinerary.values())
        avg = total_activities / max(len(itinerary), 1)
        if "max_avg_per_day" in pref:
            ok = avg <= pref["max_avg_per_day"]
            return ok, "" if ok else f"avg activities/day = {avg:.2f}, expected <= {pref['max_avg_per_day']}"
        ok = avg >= pref["min_avg_per_day"]
        return ok, "" if ok else f"avg activities/day = {avg:.2f}, expected >= {pref['min_avg_per_day']}"

    raise ValueError(f"unknown preference_check type: {pref['type']}")


# ── Runner ─────────────────────────────────────────────────────────────────

_NON_PREFERENCE_KEYS = ("id", "category", "expected_days", "preference_check", "plan_type")


async def run_case(case: dict, live: bool) -> list:
    anchor = _build_anchor(case)
    preferences = {k: v for k, v in case.items() if k not in _NON_PREFERENCE_KEYS}
    preferences["num_travelers"] = preferences["adults"] + preferences["children"] + preferences["seniors"]

    original_get_client = server._get_gemini_client
    original_log_usage = server.usage_service.log_usage
    server.usage_service.log_usage = _noop
    if not live:
        fake_client = _FakeGeminiClient(json.dumps(build_fixture_plan(case, anchor)))
        server._get_gemini_client = lambda: fake_client
    try:
        result = await server.generate_single_plan(
            preferences, case["plan_type"], f"eval_{case['id']}", "eval_user", anchor=anchor,
        )
    finally:
        server._get_gemini_client = original_get_client
        server.usage_service.log_usage = original_log_usage

    problems = check_structural(case, result)
    if not problems and case.get("preference_check"):
        ok, detail = check_preference(case, result)
        if not ok:
            problems.append(f"preference check failed: {detail}")
    return problems


def main():
    parser = argparse.ArgumentParser(description="Golden eval set for AI trip generation")
    parser.add_argument("--live", action="store_true", help="Hit the real Gemini API instead of replaying "
                         "canned fixtures - costs real quota, see this module's docstring.")
    parser.add_argument("--cases", default="all", help="Comma-separated case ids to run, or 'all' (default).")
    args = parser.parse_args()

    selected = CASES if args.cases == "all" else [c for c in CASES if c["id"] in args.cases.split(",")]
    if not selected:
        print(f"No cases matched --cases={args.cases!r}")
        sys.exit(1)

    if args.live:
        print(f"** --live: making up to {len(selected) * 3} real Gemini API calls (each case retries up to "
              f"3x on failure) against the free-tier 20-requests/day quota. Ctrl-C now to abort. **\n")

    async def _run_all():
        results = []
        for case in selected:
            problems = await run_case(case, args.live)
            status = "PASS" if not problems else "FAIL"
            print(f"[{status}] {case['id']} ({case['category']})")
            for p in problems:
                print(f"    - {p}")
            results.append(problems)
        return results

    # One event loop for the whole batch, not one per case - db (the module-
    # level Motor client server.py constructs at import time) is bound to
    # whichever event loop first uses it, and Motor connections don't
    # survive being reused across a new asyncio.run() per case (surfaces as
    # silent "Event loop is closed" warnings from generation_log_service's
    # fire-and-forget error handling, not a test failure, but real writes
    # were being dropped).
    all_problems = asyncio.run(_run_all())
    failures = sum(1 for problems in all_problems if problems)

    mode = "live" if args.live else "replay"
    print(f"\n{len(selected) - failures}/{len(selected)} passed ({mode} mode)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
