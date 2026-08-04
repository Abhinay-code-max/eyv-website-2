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

generate_single_plan now validates the parsed response against
GeneratedPlanResponse (a Pydantic model, see server.py) before any of that
cost-correction code runs. A malformed shape - including both variants that
caused the original crash - now fails validation and is treated as a real
generation failure, feeding the existing retry loop, the same as a network
error from Gemini would. This is a deliberate behavior change from an
earlier version of these tests: malformed shapes used to be silently
coerced into an empty dict and the generation allowed to "succeed" with
degraded content; they now fail cleanly instead. Since the fake Gemini
client below returns the same malformed shape on every retry, all 3
attempts are exhausted and generate_single_plan returns its documented
failure shape (generation_failed=True) - what these tests confirm is that
this happens instead of an unhandled crash, and that a well-formed response
still succeeds normally.
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
    containing the full JSON response on every call, and counts how many
    times generation was attempted."""
    def __init__(self, response_text):
        self._response_text = response_text
        self.call_count = 0

    async def generate_content_stream(self, *args, **kwargs):
        self.call_count += 1
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


async def _noop_log_generation(*args, **kwargs):
    return None


async def _no_hotels(*args, **kwargs):
    return None  # forces hotel_price_per_night = 0, skipping the hotel fix-up path


def _run_with_mocked_ai(monkeypatch, plan: dict) -> tuple:
    """Returns (result, fake_client) so callers can assert on both the
    returned plan and how many times generation was attempted."""
    fake_client = _FakeGeminiClient(json.dumps(plan))
    monkeypatch.setattr(server, "_get_gemini_client", lambda: fake_client)
    monkeypatch.setattr(server.usage_service, "log_usage", _noop_log_usage)
    monkeypatch.setattr(server.generation_log_service, "log_generation_attempt", _noop_log_generation)
    monkeypatch.setattr(server.serpapi_hotels_service, "search_hotels", _no_hotels)
    result = asyncio.run(server.generate_single_plan(dict(PREFS), "Premium", "trip_test_crash", "user_test"))
    return result, fake_client


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


def test_cost_breakdown_as_list_fails_cleanly_not_crash(monkeypatch):
    """Reproduces the original crash trigger - "cost_breakdown" as a bare
    list (`[]`) instead of an object. Now caught by schema validation before
    the cost-correction code (which used to crash on it) ever runs."""
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

    result, fake_client = _run_with_mocked_ai(monkeypatch, malformed_plan)

    # No unhandled exception (asyncio.run above would have raised one), and
    # every retry was genuinely attempted rather than giving up early.
    assert fake_client.aio.models.call_count == 3
    assert result["status"] == "failed"
    assert result["generation_failed"] is True
    assert result["itinerary"] == {}


def test_last_day_transportation_as_list_fails_cleanly_not_crash(monkeypatch):
    """Reproduces the other original crash trigger - a later day's
    "transportation" as `[]` instead of an object."""
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

    result, fake_client = _run_with_mocked_ai(monkeypatch, malformed_plan)

    assert fake_client.aio.models.call_count == 3
    assert result["status"] == "failed"
    assert result["generation_failed"] is True


def test_well_formed_response_still_succeeds(monkeypatch):
    """Guards the happy path against the validation change above - a
    correctly-shaped response must still produce a ready plan, not a false
    positive failure."""
    valid_plan = {
        "plan_type": "Premium",
        "currency": "INR",
        "currency_symbol": "₹",
        "itinerary": {
            "day_1": _base_itinerary_day(),
            "day_2": _base_itinerary_day(),
        },
        "cost_breakdown": {"transportation": 1200, "accommodation": 5000, "food": 500, "activities": 0, "miscellaneous": 0},
        "total_cost": 6700,
        "highlights": ["h1"],
        "budget_tips": ["t1"],
    }

    result, fake_client = _run_with_mocked_ai(monkeypatch, valid_plan)

    # Succeeds on the first attempt - no retries needed for a valid response.
    assert fake_client.aio.models.call_count == 1
    assert result.get("generation_failed") is not True, result.get("error")
    assert result["status"] == "ready"
    day_1 = result["itinerary"]["day_1"]
    day_2 = result["itinerary"]["day_2"]
    assert isinstance(day_2["transportation"], dict)
    # day_2 (last day) return transport is forced to match day_1's outbound anchor price
    assert day_2["transportation"]["cost"] == day_1["transportation"]["cost"] > 0
    # cost_breakdown is the sum of both legs (outbound + forced return)
    assert result["cost_breakdown"]["transportation"] == day_1["transportation"]["cost"] + day_2["transportation"]["cost"]
