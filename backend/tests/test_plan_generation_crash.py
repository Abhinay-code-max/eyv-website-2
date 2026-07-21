"""
Regression tests for a crash in generate_single_plan()'s cost-correction step:

  TypeError: list indices must be integers or slices, not str

Real-world trace: a Singapore trip (2026-07-15 to 2026-07-22) crashed generating
the Premium tier right after logging "AI day_1 transport cost before fix = ...".
The AI-returned JSON matched the expected {"day_1": {...}, "day_2": {...}} shape
for day_1 (which is why that log line succeeded), but elsewhere returned a bare
`[]` where the cost-correction code assumed a `{}` - either for the top-level
"cost_breakdown" or for a later day's "transportation". The fix-up code did
`some_dict['key'] = value` without checking the AI actually gave it a dict,
so a stray list crashed the whole generation.

Because all three tiers (Budget/Premium/Luxury) call this same function with
the same fix-up code, the malformed shape is not tier-specific - any tier can
hit it depending on what shape the model happens to return that call. These
tests reproduce both confirmed variants directly against generate_single_plan,
with the Gemini call mocked to return the exact malformed shape, and confirm
generation now completes instead of crashing.

Before this fix, all attempts would fail, generate_single_plan would swallow
the error and return a "successful-looking" plan with itinerary={} and every
cost at 0 - which is what the frontend showed as a stuck "Itinerary is being
generated" placeholder. These tests also confirm that path is gone: a plan
that generates cleanly does NOT come back with generation_failed=True.
"""
import asyncio
import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server  # noqa: E402

PREFS = dict(
    destination="Singapore",
    starting_location="Mumbai",
    departure_date="2026-07-15",
    return_date="2026-07-17",
    transportation="train",  # avoids needing to mock the flight provider
    currency="INR",
    num_travelers=1,
    adults=1,
    children=0,
    seniors=0,
)


class _FakeModels:
    """Stands in for gemini_client.aio.models - streams back a single chunk
    containing the full (malformed) JSON response."""
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


async def _noop_log_usage(*args, **kwargs):
    return None


async def _no_hotels(*args, **kwargs):
    return None  # forces hotel_price_per_night = 0, skipping the hotel fix-up path


def _run_with_mocked_ai(monkeypatch, malformed_plan: dict) -> dict:
    fake_client = _FakeGeminiClient(json.dumps(malformed_plan))
    monkeypatch.setattr(server, "_get_gemini_client", lambda: fake_client)
    monkeypatch.setattr(server.usage_service, "log_usage", _noop_log_usage)
    monkeypatch.setattr(server.serpapi_hotels_service, "search_hotels", _no_hotels)
    return asyncio.run(server.generate_single_plan(dict(PREFS), "Premium", "trip_test_crash", "user_test"))


def _base_itinerary_day(cost=1200):
    return {
        "date": "2026-07-15",
        "transportation": {"mode": "train", "details": "Superfast Express", "cost": cost},
        "activities": [{"time": "14:00", "activity": "Check-in", "location": "Hotel", "cost": 0,
                         "category": "free", "pricing_type": "flat_group"}],
        "accommodation": {"name": "Hotel", "type": "hotel", "cost": 5000, "location": "Singapore"},
        "meals": [{"time": "dinner", "restaurant": "Local restaurant", "cuisine": "Local", "cost": 500}],
        "daily_total": 6700, "cumulative_total": 6700, "fixed_costs": 6200, "variable_costs": 500,
    }


def test_cost_breakdown_as_list_does_not_crash(monkeypatch):
    """Reproduces the crash when the AI returns "cost_breakdown" as a bare
    list (`[]`) instead of an object - `plan_data['cost_breakdown']['transportation'] = ...`
    used to raise "list indices must be integers or slices, not str"."""
    malformed_plan = {
        "plan_type": "Premium",
        "currency": "INR",
        "currency_symbol": "₹",
        "itinerary": {
            "day_1": _base_itinerary_day(),
            "day_2": _base_itinerary_day(),
        },
        "cost_breakdown": [],  # malformed: should be an object
        "total_cost": 0,
        "highlights": ["h1"],
        "budget_tips": ["t1"],
    }

    result = _run_with_mocked_ai(monkeypatch, malformed_plan)

    assert result.get("generation_failed") is not True, result.get("error")
    assert isinstance(result["cost_breakdown"], dict)
    assert result["cost_breakdown"]["transportation"] > 0


def test_last_day_transportation_as_list_does_not_crash(monkeypatch):
    """Reproduces the crash when a later day's "transportation" comes back as
    `[]` instead of an object - `dl['transportation']['cost'] = ...` used to
    raise the same TypeError once the fix-up code reached the return-day block."""
    malformed_plan = {
        "plan_type": "Premium",
        "currency": "INR",
        "currency_symbol": "₹",
        "itinerary": {
            "day_1": _base_itinerary_day(),
            "day_2": {
                "date": "2026-07-16",
                "transportation": [],  # malformed: should be an object
                "activities": [],
                "accommodation": {"name": "Hotel", "type": "hotel", "cost": 5000, "location": "Singapore"},
                "meals": [{"time": "dinner", "restaurant": "Local restaurant", "cuisine": "Local", "cost": 500}],
                "daily_total": 5500, "cumulative_total": 12200, "fixed_costs": 5000, "variable_costs": 500,
            },
        },
        "cost_breakdown": {"transportation": 0, "accommodation": 0, "food": 0, "activities": 0, "miscellaneous": 0},
        "total_cost": 0,
        "highlights": ["h1"],
        "budget_tips": ["t1"],
    }

    result = _run_with_mocked_ai(monkeypatch, malformed_plan)

    assert result.get("generation_failed") is not True, result.get("error")
    day_1 = result["itinerary"]["day_1"]
    day_2 = result["itinerary"]["day_2"]
    assert isinstance(day_2["transportation"], dict)
    # day_2 (last day) return transport is forced to match day_1's outbound anchor price
    assert day_2["transportation"]["cost"] == day_1["transportation"]["cost"] > 0
    # cost_breakdown is the sum of both legs (outbound + forced return)
    assert result["cost_breakdown"]["transportation"] == day_1["transportation"]["cost"] + day_2["transportation"]["cost"]
