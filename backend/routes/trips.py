"""Trips API router (/api/trips/*).

NOTE: /api/trips/* routes are split across routes/trips.py and routes/bookings.py.
Trip management routes (generate, regenerate, quota, get, road-route, delete) live here in routes/trips.py.
The "Book this Plan" bundled booking route (/api/trips/{trip_id}/book/{plan_type}) lives in routes/bookings.py.
"""
import os
import re
import io
import math
import time
import json
import uuid
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Literal




import sentry_sdk
from fastapi import APIRouter, HTTPException, Request
from google.genai import types as genai_types
from pydantic import BaseModel, Field, ConfigDict, model_validator, field_validator, ValidationError




from routes.shared import (
    db,
    limiter,
    _session_token_key,
    get_current_user,
    is_user_premium,
    _get_gemini_client,
    GEMINI_MODEL,
    TripPreferences,
    TripPlan,
    SavedTrip,
    QuotaExceededError,
)
import sys
import services.ignav_service as _real_duffel_service
import services.serpapi_hotels_service as _real_serpapi_hotels_service
import services.amadeus_service as _real_amadeus_service
import services.usage_service as _real_usage_service
import services.generation_log_service as _real_generation_log_service
import services.locations_service as _real_locations_service
import services.analytics_service as _real_analytics_service
import services.quota_service as _real_quota_service
import services.price_cache_service as _real_price_cache_service
import services.date_utils as _real_date_utils


class _ServiceProxy:
    def __init__(self, fallback_module, attr_name):
        self._fallback = fallback_module
        self._attr = attr_name

    def __getattr__(self, name):
        srv = sys.modules.get("server")
        if srv is not None and hasattr(srv, self._attr):
            target = getattr(srv, self._attr)
            return getattr(target, name)
        return getattr(self._fallback, name)


duffel_service = _ServiceProxy(_real_duffel_service, "duffel_service")
serpapi_hotels_service = _ServiceProxy(_real_serpapi_hotels_service, "serpapi_hotels_service")
amadeus_service = _ServiceProxy(_real_amadeus_service, "amadeus_service")
usage_service = _ServiceProxy(_real_usage_service, "usage_service")
generation_log_service = _ServiceProxy(_real_generation_log_service, "generation_log_service")
locations_service = _ServiceProxy(_real_locations_service, "locations_service")
analytics_service = _ServiceProxy(_real_analytics_service, "analytics_service")
quota_service = _ServiceProxy(_real_quota_service, "quota_service")
price_cache_service = _ServiceProxy(_real_price_cache_service, "price_cache_service")
date_utils = _ServiceProxy(_real_date_utils, "date_utils")

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/trips", tags=["trips"])


TRIP_PLAN_TYPES = ("Budget", "Premium", "Luxury")

# Sentinel distinguishing "caller didn't pass shared raw search results,
# fetch them yourself" from "caller passed None because this trip has no
# flight leg (train/cruise/road)" - both are falsy, but only the first
# should trigger a fetch. Defined here (not next to the functions that
# default to it, further down) because default argument values are
# evaluated at `def` time - _generate_and_save_tier below needs this name
# to already exist.
_NOT_FETCHED = object()


def _placeholder_plan(plan_type: str, currency: str, currency_symbol: str) -> Dict[str, Any]:
    """Shape a tier's entry takes in the trips.plans array from the moment
    the trip is created until that tier's own generation finishes - lets the
    frontend render each tier's card independently (status: "generating" ->
    "ready"/"failed") instead of blocking on the slowest of the three."""
    return {
        "plan_type": plan_type,
        "status": "generating",
        "currency": currency,
        "currency_symbol": currency_symbol,
        "itinerary": {},
        "cost_breakdown": {"transportation": 0, "accommodation": 0, "food": 0, "activities": 0, "miscellaneous": 0},
        "total_cost": 0,
        "highlights": [],
        "budget_tips": [],
    }


# Strong references to in-flight background generation tasks - asyncio only
# holds a *weak* reference to a task once nothing else does, so a bare
# `asyncio.create_task(...)` with the result discarded risks the task being
# garbage-collected mid-generation. Each task removes itself on completion.
_background_generation_tasks: set = set()


def _spawn_background_task(coro) -> None:
    task = asyncio.create_task(coro)
    _background_generation_tasks.add(task)

    def _on_done(t: asyncio.Task) -> None:
        _background_generation_tasks.discard(t)
        if not t.cancelled() and t.exception() is not None:
            # generate_single_plan already catches and reports its own
            # failures via the "failed" plan status - this is a backstop
            # for anything unexpected escaping the update itself (e.g. a
            # DB write error), so it isn't silently dropped.
            logger.error(f"Background trip-generation task failed unexpectedly: {t.exception()}")

    task.add_done_callback(_on_done)


async def _generate_and_save_tier(
    trip_id: str, user_id: str, plan_type: str, preferences_dict: Dict, plan_index: int,
    raw_flights: Any = _NOT_FETCHED, raw_hotels: Any = _NOT_FETCHED,
) -> None:
    """Generate one tier and write only its slot in the trip's plans array -
    the same single-index update the regenerate endpoint uses, so a tier
    finishing here is indistinguishable from one finishing via regenerate."""
    # Only forwarded when the caller actually did a shared fetch - callers
    # that don't pass these (e.g. a direct/test call with just the first 5
    # positional args) get exactly the pre-existing generate_single_plan(...)
    # call shape, unchanged.
    shared_kwargs: Dict[str, Any] = {}
    if raw_flights is not _NOT_FETCHED:
        shared_kwargs["raw_flights"] = raw_flights
    if raw_hotels is not _NOT_FETCHED:
        shared_kwargs["raw_hotels"] = raw_hotels
    plan = await generate_single_plan(preferences_dict, plan_type, trip_id, user_id, **shared_kwargs)
    await db.trips.update_one(
        {"trip_id": trip_id, "user_id": user_id},
        {"$set": {f"plans.{plan_index}": plan, "updated_at": datetime.now(timezone.utc)}},
    )
    # Only a real, usable plan counts as "generated" for the funnel - a
    # "failed" tier (generate_single_plan's own graceful-degradation path)
    # never reached anything a user could act on, so it's not a funnel entry.
    if plan.get("status") == "ready":
        await analytics_service.record_event(
            db, "plan_generated", user_id,
            {"trip_id": trip_id, "plan_type": plan_type, "plan_index": plan_index},
        )


# Trip Planning Routes
@router.post("/generate")
@limiter.limit("5/minute")  # per-IP - stops a scripted loop from one source
@limiter.limit("5/minute", key_func=_session_token_key)  # per-authenticated-user
async def generate_trip_plans(preferences: TripPreferences, request: Request):
    user = await get_current_user(request)

    # Daily free-tier quota - the durable control, not just a burst guard.
    # Premium accounts are exempt entirely.
    if not await is_user_premium(user.user_id):
        quota = await quota_service.try_consume_trip_generation(db, user.user_id)
        if not quota["allowed"]:
            raise QuotaExceededError(used=quota["used"], limit=quota["limit"])

    trip_id = f"trip_{uuid.uuid4().hex[:12]}"

    # Store preferences
    preferences_dict = preferences.model_dump()
    currency = preferences_dict.get('currency', 'INR')
    currency_symbol = '₹' if currency == 'INR' else '$'

    # Save the trip immediately with all three tiers in "generating" status,
    # then kick off each tier's generation as an independent background task
    # instead of blocking this request on asyncio.gather for all three.
    # Budget/Premium typically finish well before Luxury (larger, denser
    # itinerary -> more prone to needing a retry) - this lets the frontend
    # show each tier the moment *it* is done rather than gating all three on
    # the slowest, and lets the client navigate to the results page and
    # start rendering almost immediately instead of waiting minutes.
    placeholder_plans = [_placeholder_plan(plan_type, currency, currency_symbol) for plan_type in TRIP_PLAN_TYPES]
    saved_trip = {
        "trip_id": trip_id,
        "user_id": user.user_id,
        "trip_name": f"{preferences.destination} Trip",
        "preferences": preferences_dict,
        "plans": placeholder_plans,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    await db.trips.insert_one(saved_trip)

    # Fetch flight/hotel search results ONCE here, shared by all three tiers
    # below - each tier's anchor price is a SELECTION from this single
    # response (cheapest/median/most-expensive hotel; cheapest/direct/
    # fastest flight - see _select_tier_hotel / select_anchor_flight), not a
    # fresh search of its own. Previously each of the three background tasks
    # below called _fetch_anchor_pricing independently, tripling real Duffel/
    # SerpApi calls for parameters that never varied between tiers.
    is_train, is_cruise, is_road = _transport_mode_flags(preferences_dict)
    raw_hotels = await _search_hotels_cached(
        preferences_dict.get("destination", ""),
        preferences_dict.get("departure_date", ""),
        preferences_dict.get("return_date", ""),
        ROOM_OCCUPANCY, "INR", user.user_id,
    )
    raw_flights = None
    if not (is_train or is_cruise or is_road):
        raw_flights = await _search_flights_cached(
            preferences_dict.get("starting_location", ""),
            preferences_dict.get("destination", ""),
            preferences_dict.get("departure_date", ""),
            1, user.user_id,
        )

    for plan_index, plan_type in enumerate(TRIP_PLAN_TYPES):
        _spawn_background_task(_generate_and_save_tier(
            trip_id, user.user_id, plan_type, preferences_dict, plan_index,
            raw_flights=raw_flights, raw_hotels=raw_hotels,
        ))

    return {"trip_id": trip_id, "plans": placeholder_plans}


@router.post("/{trip_id}/regenerate/{plan_type}")
@limiter.limit("5/minute")  # per-IP - same guard as /trips/generate, still a real Gemini call
@limiter.limit("5/minute", key_func=_session_token_key)  # per-authenticated-user
async def regenerate_trip_plan(trip_id: str, plan_type: str, request: Request):
    """Re-run generation for a single tier of an existing trip (e.g. after
    that tier's original generation failed) without touching the other two
    tiers or re-fetching flight/hotel anchor data that already succeeded."""
    user = await get_current_user(request)

    if plan_type not in TRIP_PLAN_TYPES:
        raise HTTPException(status_code=400, detail=f"plan_type must be one of {list(TRIP_PLAN_TYPES)}")

    # Scoping the lookup to user_id doubles as the ownership check - a
    # trip_id that doesn't exist and one that belongs to someone else both
    # come back as the same 404, so this never leaks whether a given
    # trip_id exists for another account.
    trip = await db.trips.find_one(
        {"trip_id": trip_id, "user_id": user.user_id},
        {"_id": 0}
    )
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    plans = trip.get("plans", [])
    plan_index = next((i for i, p in enumerate(plans) if p.get("plan_type") == plan_type), None)
    if plan_index is None:
        raise HTTPException(status_code=404, detail=f"No {plan_type} plan found on this trip")

    # Daily free-tier quota - regenerating one tier is still a real Gemini
    # call, gated the same way as the original /trips/generate. Premium
    # accounts are exempt entirely, same as generate_trip_plans above.
    if not await is_user_premium(user.user_id):
        quota = await quota_service.try_consume_trip_generation(db, user.user_id)
        if not quota["allowed"]:
            raise QuotaExceededError(used=quota["used"], limit=quota["limit"])

    # Reuse the previously-fetched flight/train + hotel anchor for this tier
    # if we have one - avoids an unnecessary Duffel/SerpApi call for pricing
    # that hasn't changed. Older trips saved before anchor_pricing existed
    # fall back to a fresh fetch inside generate_single_plan.
    cached_anchor = plans[plan_index].get("anchor_pricing")

    regenerated = await generate_single_plan(
        trip["preferences"], plan_type, trip_id, user.user_id, anchor=cached_anchor
    )

    await db.trips.update_one(
        {"trip_id": trip_id, "user_id": user.user_id},
        {"$set": {f"plans.{plan_index}": regenerated, "updated_at": datetime.now(timezone.utc)}},
    )
    # Same plan_generated event as _generate_and_save_tier's initial
    # generation - a regenerated tier is still "a plan generated" for the
    # funnel, and re-firing it for the same trip_id doesn't double-count
    # anything downstream (the funnel counts DISTINCT trip_ids per stage).
    if regenerated.get("status") == "ready":
        await analytics_service.record_event(
            db, "plan_generated", user.user_id,
            {"trip_id": trip_id, "plan_type": plan_type, "plan_index": plan_index, "regenerated": True},
        )

    return {"trip_id": trip_id, "plan_type": plan_type, "plan": regenerated}


ROOM_OCCUPANCY = 2  # standard double-occupancy hotel room


def _room_count(num_travelers: int, occupancy: int = ROOM_OCCUPANCY) -> int:
    """Rooms a group needs at standard double occupancy. This is deliberately
    NOT the same as traveler count - 4 travelers need 2 rooms, not 4x the
    price of a single room."""
    return max(1, math.ceil(num_travelers / occupancy))


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two coordinates, in km."""
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


async def _geocode_place(place: str) -> Optional[Dict[str, float]]:
    """Geocode a place name using the same fallback chain as the
    /destinations/{destination}/coords endpoint: curated list + Nominatim
    first (locations_service), then amadeus_service's mock coords as a last
    resort so callers always get *something* to plot rather than nothing."""
    srv = sys.modules.get("server")
    if srv is not None and hasattr(srv, "_geocode_place") and srv._geocode_place is not _geocode_place:
        return await srv._geocode_place(place)
    coords = await locations_service.geocode_destination(place)
    if not coords:
        coords = amadeus_service.get_destination_coords(place)
    return coords


# Neither Ignav (flights) nor SerpApi (hotels) exposes separate child/senior
# fares - both only accept a flat adults/travelers count. These are
# project-defined fallback discounts, not provider-verified rates.
CHILD_FARE_DISCOUNT = 0.25   # children pay 75% of the adult fare
SENIOR_FARE_DISCOUNT = 0.10  # seniors pay 90% of the adult fare


def _fare_units(adults: int, children: int, seniors: int) -> float:
    """Age-weighted traveler count used to scale flight/train/meal prices.
    Deliberately NOT used for hotel room count - rooms are priced per-room,
    not per-person, so age has no bearing on how many rooms are needed."""
    return adults * 1.0 + children * (1 - CHILD_FARE_DISCOUNT) + seniors * (1 - SENIOR_FARE_DISCOUNT)


def _select_tier_hotel(hotels_sorted: List[Dict], plan_type: str) -> tuple:
    """Pick the anchor hotel for a Budget/Premium/Luxury plan by SELECTING a
    real hotel from the provider's own price-sorted results - Budget gets the
    cheapest, Premium the median, Luxury the most expensive. Every field on
    the returned hotel (name, price, stars, ...) is untouched provider data.

    Returns (hotel, limited_inventory) where limited_inventory is True when
    the destination doesn't have enough genuinely distinct prices to make
    Budget/Premium/Luxury meaningfully different - callers should say so
    rather than pretend the tiers are more separated than they really are.
    """
    if not hotels_sorted:
        return None, True

    if plan_type == "Budget":
        hotel = hotels_sorted[0]
    elif plan_type == "Premium":
        hotel = hotels_sorted[len(hotels_sorted) // 2]
    else:
        hotel = hotels_sorted[-1]

    # "Limited inventory" means the destination doesn't have enough genuine
    # price spread to make three tiers meaningfully different - either there
    # aren't 3 distinct prices at all, or the cheapest and priciest real
    # hotels are within 15% of each other.
    distinct_prices = {h["price"]["per_night"] for h in hotels_sorted}
    cheapest = hotels_sorted[0]["price"]["per_night"]
    priciest = hotels_sorted[-1]["price"]["per_night"]
    price_spread = (priciest / cheapest - 1) if cheapest else 0
    limited_inventory = len(distinct_prices) < 3 or price_spread < 0.15

    return hotel, limited_inventory


def _scale_per_person_costs(itinerary: Dict[str, Any], num_travelers: int) -> None:
    """Meals and per-person activities are generated by the AI as a single
    person's cost - scale them up to the full traveler count. Activities the
    AI tags pricing_type="flat_group" (a hired guide, a private car, a
    chartered boat) are one fixed cost regardless of group size and are left
    untouched. Callers are expected to have already validated `itinerary`
    against GeneratedPlanResponse, so every day/meal/activity here is
    guaranteed present and correctly typed."""
    for day_data in itinerary.values():
        for meal in day_data['meals']:
            meal['cost'] = meal['cost'] * num_travelers
        for activity in day_data['activities']:
            cost = activity['cost']
            if cost <= 0 or activity.get('pricing_type') == 'flat_group':
                continue
            activity['cost'] = cost * num_travelers


# Enforces the plan JSON's shape at generation time (Gemini structured
# output - response_mime_type="application/json" + response_json_schema).
# Structured output has occasionally been observed to still deviate from
# this schema (e.g. under retries/edge-case prompts), so the parsed response
# is also validated against GeneratedPlanResponse (below) before
# generate_single_plan trusts it - a response that doesn't match either
# schema is a real failure (raises, feeding the existing retry loop), not
# something silently coerced into shape.
#
# "itinerary" keeps its existing day_1/day_2/... dict shape (verified live
# against the Gemini API that additionalProperties correctly constrains
# each day's value rather than the model falling back to an array) so no
# downstream code, prompt example, or stored-data shape has to change.
_DAY_SCHEMA = {
    "type": "object",
    "properties": {
        "date": {"type": "string"},
        "transportation": {
            "type": "object",
            "properties": {
                "mode": {"type": "string"},
                "details": {"type": "string"},
                "cost": {"type": "number"},
            },
            "required": ["mode", "cost"],
        },
        "activities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "time": {"type": "string"},
                    "activity": {"type": "string"},
                    "location": {"type": "string"},
                    "cost": {"type": "number"},
                    "category": {"type": "string"},
                    "pricing_type": {"type": "string", "enum": ["per_person", "flat_group"]},
                },
                "required": ["activity", "cost"],
            },
        },
        "accommodation": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "type": {"type": "string"},
                "cost": {"type": "number"},
                "location": {"type": "string"},
            },
            "required": ["name", "cost"],
        },
        "meals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "time": {"type": "string"},
                    "restaurant": {"type": "string"},
                    "cuisine": {"type": "string"},
                    "cost": {"type": "number"},
                },
                "required": ["cost"],
            },
        },
        "daily_total": {"type": "number"},
        "cumulative_total": {"type": "number"},
        "fixed_costs": {"type": "number"},
        "variable_costs": {"type": "number"},
    },
    "required": ["date", "transportation", "accommodation", "meals", "activities"],
}

PLAN_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "plan_type": {"type": "string"},
        "currency": {"type": "string"},
        "currency_symbol": {"type": "string"},
        "itinerary": {
            "type": "object",
            "additionalProperties": _DAY_SCHEMA,
            "minProperties": 1,
        },
        "cost_breakdown": {
            "type": "object",
            "properties": {
                "transportation": {"type": "number"},
                "accommodation": {"type": "number"},
                "food": {"type": "number"},
                "activities": {"type": "number"},
                "miscellaneous": {"type": "number"},
            },
            "required": ["transportation", "accommodation", "food", "activities", "miscellaneous"],
        },
        "total_cost": {"type": "number"},
        "highlights": {"type": "array", "items": {"type": "string"}},
        "budget_tips": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["plan_type", "currency", "currency_symbol", "itinerary", "cost_breakdown", "total_cost", "highlights", "budget_tips"],
}


# Pydantic mirror of _DAY_SCHEMA/PLAN_RESPONSE_SCHEMA above, used to validate
# the *parsed* response after generation completes. This is a second
# definition of the same shape kept in sync by hand rather than derived from
# one another: the raw dicts above have to stay exactly as they are because
# they're proven to work as a Gemini response_json_schema (Gemini's
# structured-output schema support does not accept Pydantic's $defs/$ref
# nesting), while this model is what actually gates whether a response is
# accepted. A response that parses as JSON but fails validation here is a
# real generation failure - it's raised and caught by generate_single_plan's
# retry loop, the same as any other exception from the Gemini call itself,
# instead of being silently patched into a plausible-looking shape.
class _GeneratedTransportation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    mode: str
    details: str = ""
    cost: float


class _GeneratedActivity(BaseModel):
    model_config = ConfigDict(extra="ignore")
    activity: str
    cost: float
    time: str = ""
    location: str = ""
    category: str = ""
    pricing_type: Optional[Literal["per_person", "flat_group"]] = None


class _GeneratedAccommodation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    cost: float
    type: str = ""
    location: str = ""


class _GeneratedMeal(BaseModel):
    model_config = ConfigDict(extra="ignore")
    cost: float
    time: str = ""
    restaurant: str = ""
    cuisine: str = ""


class _GeneratedDay(BaseModel):
    model_config = ConfigDict(extra="ignore")
    date: str
    transportation: _GeneratedTransportation
    accommodation: _GeneratedAccommodation
    meals: List[_GeneratedMeal]
    activities: List[_GeneratedActivity]
    daily_total: Optional[float] = None
    cumulative_total: Optional[float] = None
    fixed_costs: Optional[float] = None
    variable_costs: Optional[float] = None


class _GeneratedCostBreakdown(BaseModel):
    model_config = ConfigDict(extra="ignore")
    transportation: float
    accommodation: float
    food: float
    activities: float
    miscellaneous: float


class GeneratedPlanResponse(BaseModel):
    """Validated shape of generate_single_plan's parsed Gemini response -
    see the comment above _GeneratedTransportation for why this exists
    alongside PLAN_RESPONSE_SCHEMA rather than being derived from it."""
    model_config = ConfigDict(extra="ignore")
    plan_type: str
    currency: str
    currency_symbol: str
    itinerary: Dict[str, _GeneratedDay]
    cost_breakdown: _GeneratedCostBreakdown
    total_cost: float
    highlights: List[str]
    budget_tips: List[str]

    @model_validator(mode="after")
    def _require_at_least_one_day(self):
        if not self.itinerary:
            raise ValueError("itinerary must contain at least one day")
        return self


def _transport_mode_flags(preferences: Dict) -> tuple:
    """Train/cruise/road/flight are mutually exclusive - shared by
    generate_trip_plans (deciding whether a flight search is even needed
    before the shared fetch) and _fetch_anchor_pricing (deciding which
    pricing branch to run)."""
    transport_mode = preferences.get("transportation", "flight").lower()
    return "train" in transport_mode, "cruise" in transport_mode, "road" in transport_mode


async def _search_flights_cached(origin: str, destination: str, departure_date: str, travelers: int, user_id: str) -> List[Dict]:
    """The one place anchor-pricing hits Ignav for flights. Checks the
    short-TTL search cache first (see price_cache_service) so a second
    generation with the same route/date/traveler count within the TTL
    window costs zero real provider calls - usage is only logged on an
    actual cache miss, so provider_usage stays an accurate count of real
    calls, not attempted ones."""
    params = {"origin": origin, "destination": destination, "departure_date": departure_date, "travelers": travelers}
    cached = await price_cache_service.get_cached_search(db, "flight", params)
    if cached is not None:
        return cached
    flights = await duffel_service.search_flights(origin, destination, departure_date, travelers=travelers)
    await usage_service.log_usage(db, "duffel", user_id=user_id, meta={"context": "generate_single_plan"})
    await price_cache_service.cache_search_response(db, "flight", params, flights)
    return flights


async def _search_hotels_cached(destination: str, check_in: str, check_out: str, travelers: int, currency: str, user_id: str) -> List[Dict]:
    """Same caching contract as _search_flights_cached above, for SerpApi
    hotel search."""
    params = {"destination": destination, "check_in": check_in, "check_out": check_out, "travelers": travelers, "currency": currency}
    cached = await price_cache_service.get_cached_search(db, "hotel", params)
    if cached is not None:
        return cached
    hotels = await serpapi_hotels_service.search_hotels(destination, check_in, check_out, travelers=travelers, currency=currency)
    await usage_service.log_usage(db, "serpapi", user_id=user_id, meta={"context": "generate_single_plan"})
    await price_cache_service.cache_search_response(db, "hotel", params, hotels)
    return hotels


async def _fetch_anchor_pricing(
    preferences: Dict, plan_type: str, user_id: str, fare_units: float, room_count: int,
    raw_flights: Any = _NOT_FETCHED, raw_hotels: Any = _NOT_FETCHED,
) -> Dict[str, Any]:
    """Fetch real flight/train + hotel anchor prices for one tier. Split out
    of generate_single_plan so a single-tier regenerate can reuse a
    previously-fetched anchor (see the "anchor" param there) instead of
    hitting Duffel/SerpApi again for tiers that already anchored fine.

    raw_flights/raw_hotels: pre-fetched, not-yet-tier-selected search
    results shared across all three tiers of one generation (see
    generate_trip_plans) - passing these turns Budget/Premium/Luxury from
    three independent searches into three SELECTIONS from the same single
    search. Left at the _NOT_FETCHED sentinel, this fetches for itself
    (single-tier callers like regenerate-without-a-cached-anchor)."""
    srv = sys.modules.get("server")
    if srv is not None and hasattr(srv, "_fetch_anchor_pricing") and srv._fetch_anchor_pricing is not _fetch_anchor_pricing:
        return await srv._fetch_anchor_pricing(
            preferences, plan_type, user_id, fare_units, room_count,
            raw_flights=raw_flights, raw_hotels=raw_hotels,
        )
    is_train, is_cruise, is_road = _transport_mode_flags(preferences)
    # One-way only has an observable effect on flights - train/cruise/road are
    # all hardcoded/computed estimates already priced as a single leg (see
    # their branches below), not a real fare that return-leg booking changes.
    is_one_way = (not is_train and not is_cruise and not is_road
                  and preferences.get("trip_direction") == "one_way")

    flight_price = 0
    flight_airline = ""
    flight_number = ""
    flight_dep_time = ""
    flight_arr_time = ""
    flight_duration = ""
    flight_stops = 0

    train_price = 0
    train_name = ""
    train_number = ""
    train_class = ""
    train_duration = ""

    cruise_price = 0
    cruise_cabin_type = ""
    cruise_duration_label = ""

    road_price = 0
    road_distance_km = 0
    road_vehicle_count = 1
    road_origin_coords = None
    road_dest_coords = None

    hotel_name = ""
    hotel_price_per_night = 0
    hotel_stars = 0
    hotel_limited_inventory = False

    if is_train:
        train_tier_prices = {
            "Budget":  {"price": 450,  "class": "Sleeper (SL)",      "name": "Express Train"},
            "Premium": {"price": 1200, "class": "AC 3-Tier (3A)",    "name": "Superfast Express"},
            "Luxury":  {"price": 2800, "class": "AC 1st Class (1A)", "name": "Rajdhani / Shatabdi"},
        }
        t = train_tier_prices.get(plan_type, train_tier_prices["Budget"])
        train_price    = t["price"] * fare_units
        train_class    = t["class"]
        train_name     = t["name"]
        train_number   = "Train"
        train_duration = "Varies by route"
        logger.info(f"{plan_type}: estimated train = {train_name} {train_class} ₹{train_price:,.0f}")
    elif is_cruise:
        # No accessible developer API exists for real cruise pricing
        # (enterprise-only vendors) - same "no real inventory" situation as
        # trains, so this is a hardcoded estimate table, not a live fetch.
        # Cabin type is TIER-driven (mirrors how train class is tier-driven),
        # not taken from the user's own cruise_cabin_type answer - letting a
        # single user answer skew cabin choice would break the "Budget is
        # cheapest, Luxury priciest" ordering the prompt enforces below.
        # Duration IS taken from the user's answer - trip length is a date-
        # range fact shared by all three tiers, not a luxury-level fact.
        cruise_tier_cabin = {"Budget": "Interior", "Premium": "Balcony", "Luxury": "Suite"}
        cruise_cabin_multiplier = {"Interior": 1.0, "Ocean View": 1.5, "Balcony": 2.2, "Suite": 3.75}
        cruise_duration_rates = {
            "Short getaway (2-5 nights)":   {"base_per_night": 9000, "typical_nights": 4},
            "Week-long (6-9 nights)":       {"base_per_night": 8000, "typical_nights": 7},
            "Extended voyage (10+ nights)": {"base_per_night": 7000, "typical_nights": 12},
        }
        cruise_cabin_type = cruise_tier_cabin.get(plan_type, "Interior")
        cruise_duration_label = preferences.get("cruise_duration_preference") or "Week-long (6-9 nights)"
        rates = cruise_duration_rates.get(cruise_duration_label, cruise_duration_rates["Week-long (6-9 nights)"])
        price_per_traveler = rates["base_per_night"] * rates["typical_nights"] * cruise_cabin_multiplier[cruise_cabin_type]
        # Halved: generate_single_plan sets this same anchor price on BOTH
        # day 1 and the last day (outbound + return leg) and sums both into
        # cost_breakdown.transportation, exactly like it does for train_price/
        # flight_price - correct there because those really are one-way fares
        # doubled into a round trip. A cruise voyage is one continuous price,
        # not two separate legs, so it has to start out halved here or the
        # single-voyage estimate gets silently double-counted downstream.
        cruise_price = (price_per_traveler / 2) * fare_units
        logger.info(f"{plan_type}: estimated cruise = {cruise_cabin_type} cabin, {cruise_duration_label} ₹{cruise_price:,.0f} (per leg; ₹{price_per_traveler * fare_units:,.0f} full voyage)")
    elif is_road:
        # No accessible real driving-distance/fuel-price API is wired into
        # this app - like train/cruise, this is a computed estimate, not a
        # live quote. Unlike train/cruise it's grounded in the trip's real
        # origin/destination via geocoding (locations_service - same
        # curated-list + Nominatim fallback chain the /destinations/{d}/coords
        # endpoint already uses, with amadeus_service's mock coords as the
        # final fallback) since fuel cost genuinely scales with distance in
        # a way seat class doesn't.
        try:
            origin_coords = await _geocode_place(preferences.get("starting_location", ""))
            dest_coords = await _geocode_place(preferences.get("destination", ""))

            if origin_coords and dest_coords:
                # Persisted alongside the price estimate so a later map-route
                # request (see /trips/{trip_id}/road-route) can reuse this
                # same geocode instead of hitting Nominatim again for the
                # same two place names.
                road_origin_coords = origin_coords
                road_dest_coords = dest_coords

                # Great-circle distance undercounts real road distance since
                # roads bend - 1.3x is a commonly-used rule-of-thumb ratio of
                # road distance to straight-line distance for regional/
                # intercity trips.
                ROAD_DETOUR_MULTIPLIER = 1.3
                straight_line_km = _haversine_km(
                    origin_coords["lat"], origin_coords["lng"], dest_coords["lat"], dest_coords["lng"]
                )
                road_distance_km = round(straight_line_km * ROAD_DETOUR_MULTIPLIER, 1)

                # Blended ₹/km rate (fuel + running cost), not separate
                # price-per-liter x mileage - varies by the user's own
                # road_fuel_type answer rather than assuming one vehicle type.
                fuel_rate_per_km = {
                    "Petrol": 7.0,
                    "Diesel": 6.0,
                    "CNG": 4.0,
                    "Hybrid": 4.5,
                    "Electric": 2.0,
                }.get(preferences.get("road_fuel_type"), 7.0)

                # Rough Indian national-highway toll average, zeroed out when
                # the user explicitly asked to avoid tolls.
                toll_rate_per_km = 0.0 if "Avoid tolls" in (preferences.get("road_route_avoidances") or []) else 2.0

                # Fuel/toll cost is per-VEHICLE, not per-seat (unlike
                # flight/train) - scale in discrete vehicle-capacity jumps as
                # the group grows, the same "rooms not heads" logic
                # _room_count already applies to hotels.
                road_vehicle_count = max(1, math.ceil(preferences.get("num_travelers", 1) / 4))
                road_price = (fuel_rate_per_km + toll_rate_per_km) * road_distance_km * road_vehicle_count
                logger.info(
                    f"{plan_type}: estimated road trip = {road_distance_km}km x {road_vehicle_count} "
                    f"vehicle(s) @ ₹{fuel_rate_per_km + toll_rate_per_km:.1f}/km = ₹{road_price:,.0f}"
                )
            else:
                logger.warning(f"Road distance estimate skipped for {plan_type}: could not geocode origin/destination")
        except Exception as e:
            logger.warning(f"Road distance estimate failed for {plan_type}: {e}")
    else:
        try:
            flight_pref = {"Budget": "cheapest", "Premium": "direct", "Luxury": "fastest"}.get(plan_type, "cheapest")
            # Always query for a single traveler - Ignav's own price.total already scales
            # with the "travelers" we pass it (confirmed: requesting travelers=4 returns
            # ~4x the travelers=1 fare), so if we passed num_travelers here we'd double it
            # by multiplying again below. Querying at 1 gives us a clean per-seat fare that
            # WE scale, the same way train_price already does with its fixed base rate.
            if raw_flights is _NOT_FETCHED:
                raw_flights = await _search_flights_cached(
                    preferences.get("starting_location", ""),
                    preferences.get("destination", ""),
                    preferences.get("departure_date", ""),
                    1, user_id,
                )
            af = duffel_service.select_anchor_flight(raw_flights or [], preference=flight_pref)
            if af:
                # Each traveler needs their own seat/fare, discounted by age
                # (Ignav has no separate child/senior fare - see _fare_units).
                flight_price    = af['price']['total'] * fare_units
                flight_airline  = af['airline']
                flight_number   = af['flight_number']
                flight_dep_time = af['departure']['time']
                flight_arr_time = af['arrival']['time']
                flight_duration = af['duration']
                flight_stops    = af['stops']
            logger.info(f"{plan_type}: anchor flight = {flight_airline} {flight_number} ₹{flight_price:,.0f}")
        except Exception as e:
            logger.warning(f"Anchor flight fetch failed for {plan_type}: {e}")

    try:
        # Always query at standard double occupancy - SerpApi/Google Hotels already
        # adjusts rate_per_night based on the "adults" we pass it (confirmed: the same
        # property's rate for 4 adults came back 1.5x-7x its 1-adult rate, inconsistently
        # depending on room type), so passing the true num_travelers here and then
        # multiplying by room_count below would double-count on top of whatever the
        # provider already adjusted. Querying at ROOM_OCCUPANCY gives a stable per-room
        # rate that WE scale by room count, which we fully control.
        if raw_hotels is _NOT_FETCHED:
            raw_hotels = await _search_hotels_cached(
                preferences.get("destination", ""),
                preferences.get("departure_date", ""),
                preferences.get("return_date", ""),
                ROOM_OCCUPANCY, "INR", user_id,
            )
        hotel_results = raw_hotels
        if hotel_results:
            # hotel_results is already price-sorted ascending by the service -
            # SELECT the tier's hotel from real data, never edit its fields.
            ah, hotel_limited_inventory = _select_tier_hotel(hotel_results, plan_type)
            # Group accommodation cost is by room count, not traveler count - 4 people
            # share 2 double-occupancy rooms, not 4x the price of a single room.
            hotel_name           = ah['name']
            hotel_price_per_night = ah['price']['per_night'] * room_count
            hotel_stars          = ah['stars']
            logger.info(
                f"{plan_type}: anchor hotel = {hotel_name} ₹{ah['price']['per_night']:,.0f}/night "
                f"x {room_count} room(s) = ₹{hotel_price_per_night:,.0f}/night"
                f"{' [limited hotel inventory for this destination]' if hotel_limited_inventory else ''}"
            )
    except Exception as e:
        logger.warning(f"Anchor hotel fetch failed for {plan_type}: {e}")

    return {
        "is_train": is_train,
        "is_cruise": is_cruise,
        "is_road": is_road,
        "is_one_way": is_one_way,
        "road_price": road_price,
        "road_distance_km": road_distance_km,
        "road_vehicle_count": road_vehicle_count,
        "road_origin_coords": road_origin_coords,
        "road_dest_coords": road_dest_coords,
        "flight_price": flight_price,
        "flight_airline": flight_airline,
        "flight_number": flight_number,
        "flight_dep_time": flight_dep_time,
        "flight_arr_time": flight_arr_time,
        "flight_duration": flight_duration,
        "flight_stops": flight_stops,
        "train_price": train_price,
        "train_name": train_name,
        "train_number": train_number,
        "train_class": train_class,
        "train_duration": train_duration,
        "cruise_price": cruise_price,
        "cruise_cabin_type": cruise_cabin_type,
        "cruise_duration_label": cruise_duration_label,
        "hotel_name": hotel_name,
        "hotel_price_per_night": hotel_price_per_night,
        "hotel_stars": hotel_stars,
        "hotel_limited_inventory": hotel_limited_inventory,
    }


async def generate_single_plan(
    preferences: Dict, plan_type: str, trip_id: str, user_id: str, anchor: Optional[Dict[str, Any]] = None,
    raw_flights: Any = _NOT_FETCHED, raw_hotels: Any = _NOT_FETCHED,
) -> Dict:
    """Generate a single vacation plan using AI with real price anchoring.

    `anchor`, when provided, skips Step 1's Duffel/SerpApi calls entirely and
    reuses that already-fetched flight/train + hotel pricing - used by the
    per-tier regenerate endpoint so retrying just the AI portion for one tier
    doesn't re-hit paid providers for pricing that hasn't changed.

    `raw_flights`/`raw_hotels`, when provided (and anchor is None), are
    passed straight through to _fetch_anchor_pricing - see its docstring.
    Used by generate_trip_plans to share one flight search + one hotel
    search across all three tiers instead of each tier searching for itself.
    """
    srv = sys.modules.get("server")
    if srv is not None and hasattr(srv, "generate_single_plan") and srv.generate_single_plan is not generate_single_plan:
        try:
            return await srv.generate_single_plan(
                preferences, plan_type, trip_id, user_id, anchor=anchor,
                raw_flights=raw_flights, raw_hotels=raw_hotels,
            )
        except TypeError:
            return await srv.generate_single_plan(
                preferences, plan_type, trip_id, user_id, anchor=anchor,
            )
    import json

    currency = preferences.get('currency', 'INR')
    currency_symbol = '₹' if currency == 'INR' else '$'
    num_travelers = preferences.get('num_travelers', 1)
    room_count = _room_count(num_travelers)
    # Age-weighted count for flight/train/meal pricing (room count above stays
    # on raw headcount - occupancy isn't age-discounted).
    fare_units = _fare_units(
        preferences.get('adults', num_travelers),
        preferences.get('children', 0),
        preferences.get('seniors', 0),
    )
    # Single shared nights computation (services/date_utils.py) - also used
    # by serpapi_hotels_service.py/amadeus_service.py's hotel-search pricing,
    # so the itinerary below and hotel pricing can never independently drift
    # back out of agreement with each other.
    nights = date_utils.trip_nights(preferences['departure_date'], preferences['return_date'])

    # ── Step 1: Fetch real anchor prices (or reuse a previously-fetched one)
    if anchor is None:
        anchor = await _fetch_anchor_pricing(
            preferences, plan_type, user_id, fare_units, room_count,
            raw_flights=raw_flights, raw_hotels=raw_hotels,
        )

    is_train = anchor.get("is_train", False)
    is_cruise = anchor.get("is_cruise", False)
    is_road = anchor.get("is_road", False)
    is_one_way = anchor.get("is_one_way", False)
    road_price = anchor.get("road_price", 0)
    road_distance_km = anchor.get("road_distance_km", 0)
    road_vehicle_count = anchor.get("road_vehicle_count", 1)
    flight_price = anchor.get("flight_price", 0)
    flight_airline = anchor.get("flight_airline", "")
    flight_number = anchor.get("flight_number", "")
    flight_dep_time = anchor.get("flight_dep_time", "")
    flight_arr_time = anchor.get("flight_arr_time", "")
    flight_duration = anchor.get("flight_duration", "")
    flight_stops = anchor.get("flight_stops", 0)
    train_price = anchor.get("train_price", 0)
    train_name = anchor.get("train_name", "")
    train_number = anchor.get("train_number", "")
    train_class = anchor.get("train_class", "")
    train_duration = anchor.get("train_duration", "")
    cruise_price = anchor.get("cruise_price", 0)
    cruise_cabin_type = anchor.get("cruise_cabin_type", "")
    cruise_duration_label = anchor.get("cruise_duration_label", "")
    hotel_name = anchor.get("hotel_name", "")
    hotel_price_per_night = anchor.get("hotel_price_per_night", 0)
    hotel_stars = anchor.get("hotel_stars", 3)
    hotel_limited_inventory = anchor.get("hotel_limited_inventory", False)

    # Single source of truth for "the anchor transport leg" for this trip -
    # train/cruise/flight are mutually exclusive - used everywhere below
    # (prompt constraints, JSON template, system message, post-processing)
    # instead of repeating a train-or-flight-only ternary in a dozen places,
    # which is what broke when cruise silently fell through to flight.
    if is_train:
        anchor_transport_price = train_price
        anchor_transport_label = "train"
        transport_details_prefix = f"{train_name} {train_class} "
    elif is_cruise:
        anchor_transport_price = cruise_price
        anchor_transport_label = "cruise"
        transport_details_prefix = f"{cruise_cabin_type} cabin cruise "
    elif is_road:
        anchor_transport_price = road_price
        anchor_transport_label = "road"
        transport_details_prefix = f"Self-drive road trip ({road_distance_km:.0f} km, {road_vehicle_count} vehicle(s)) "
    else:
        anchor_transport_price = flight_price
        anchor_transport_label = "flight"
        transport_details_prefix = f"{flight_airline} {flight_number} "

    # ── Step 2: Build tier-specific instructions ─────────────────────────────
    tier_rules = {
        "Budget": f"""
- Cheapest available options throughout
- Hotel: {hotel_name or 'budget guesthouse'} at EXACTLY ₹{hotel_price_per_night:,.0f}/night (use this hotel name and price)
- Public transport (metro, bus, shared rides)
- Street food and casual dining (₹150-400/meal)
- Free or low-cost attractions
- TOTAL trip cost must be the LOWEST of the three tiers
""",
        "Premium": f"""
- Mid-range comfortable options
- Hotel: {hotel_name or '4-star hotel'} at EXACTLY ₹{hotel_price_per_night:,.0f}/night (use this hotel name and price)
- Mix of metro and private transport
- Good restaurants (₹500-1200/meal)
- Mix of free and paid attractions
- TOTAL trip cost must be BETWEEN Budget and Luxury tiers
""",
        "Luxury": f"""
- Premium luxury options only
- Hotel: {hotel_name or '5-star luxury hotel'} at EXACTLY ₹{hotel_price_per_night:,.0f}/night (use this hotel name and price)
- Private transfers and premium vehicles only
- Fine dining at signature restaurants (₹1500+/meal)
- Exclusive experiences, private tours, VIP access
- TOTAL trip cost must be the HIGHEST of the three tiers
"""
    }

    # ── Step 3: Build the prompt with constraints at the TOP ─────────────────
    if is_train:
        transport_constraint = f"""TRAIN (DO NOT CHANGE THESE VALUES):
  Train Name: {train_name}
  Class: {train_class}
  Duration: {train_duration}
  PRICE: ₹{train_price:,.0f} total for {num_travelers} traveler(s) (USE THIS EXACT NUMBER)""" if train_price > 0 else "Use realistic Indian train prices."
    elif is_cruise:
        transport_constraint = f"""CRUISE (DO NOT CHANGE THESE VALUES):
  Cabin Type: {cruise_cabin_type}
  Voyage Length: {cruise_duration_label}
  PRICE: ₹{cruise_price:,.0f} total for {num_travelers} traveler(s) (USE THIS EXACT NUMBER)""" if cruise_price > 0 else "Use realistic cruise fare estimates."
    elif is_road:
        transport_constraint = f"""ROAD TRIP FUEL + TOLL ESTIMATE (DO NOT CHANGE THIS VALUE — this is an ESTIMATE, not a real quoted price):
  Estimated driving distance: {road_distance_km:.0f} km (one-way)
  Vehicle(s) needed: {road_vehicle_count}
  PRICE: ₹{road_price:,.0f} total for {num_travelers} traveler(s), one-way (USE THIS EXACT NUMBER)""" if road_price > 0 else "Use a realistic estimated fuel + toll cost for a road trip of this distance — present it clearly as an estimate, not a real quote."
    else:
        transport_constraint = f"""FLIGHT (DO NOT CHANGE THESE VALUES):
  Airline: {flight_airline}
  Flight Number: {flight_number}
  Departure: {flight_dep_time}
  Arrival: {flight_arr_time}
  Duration: {flight_duration}
  Stops: {'Non-stop' if flight_stops == 0 else f'{flight_stops} stop(s)'}
  PRICE: ₹{flight_price:,.0f} (USE THIS EXACT NUMBER — do not round, inflate, or change)""" if flight_price > 0 else "Use realistic market flight prices."

    hotel_constraint = f"""HOTEL (DO NOT CHANGE THESE VALUES):
  Name: {hotel_name}
  Stars: {hotel_stars}★
  PRICE PER NIGHT: ₹{hotel_price_per_night:,.0f} total for {room_count} room(s) accommodating {num_travelers} traveler(s) (USE THIS EXACT NUMBER)""" if hotel_price_per_night > 0 else "Use realistic market hotel prices."

    # Cruise-only descriptive flavor for the itinerary text (activities/
    # highlights) - deliberately NOT part of the pricing constraints above.
    # cruise_cabin_type here is the tier-driven cabin (see _fetch_anchor_pricing),
    # used for narrative color; dining/itinerary style come straight from the
    # user's own Cruise Preferences answers.
    cruise_flavor_block = ""
    if is_cruise:
        dining_style = preferences.get("cruise_dining_style") or "Flexible anytime dining"
        itinerary_style = preferences.get("cruise_itinerary_style") or "No preference"
        if itinerary_style == "Island-hopping":
            itinerary_guidance = "favor multiple ports of call / island-hopping stops across the voyage"
        elif itinerary_style == "Single destination focus":
            itinerary_guidance = "favor a single destination/port focus with more time onshore there"
        elif "Relaxation" in itinerary_style:
            itinerary_guidance = "favor onboard relaxation with fewer, shorter port stops"
        else:
            itinerary_guidance = "no strong itinerary-style preference - use your judgment"
        cruise_flavor_block = f"""
CRUISE PREFERENCES (reflect these in the itinerary's activities/highlights text - they do not change the price above):
- Cabin type: {cruise_cabin_type}
- Dining style: {dining_style}
- Itinerary style: {itinerary_style} - {itinerary_guidance}
"""

    # Road-only descriptive flavor for the itinerary text (activities/
    # highlights/driving notes) - same "narrative color, not pricing" role as
    # cruise_flavor_block above. Pulls from the road_* wizard fields, which
    # exist on the frontend (TripPlannerPage.jsx) but were previously never
    # read anywhere in this file.
    road_flavor_block = ""
    if is_road:
        route_style = preferences.get("road_route_style") or "Fastest"
        drivers = preferences.get("road_drivers") or 1
        max_driving_hours_per_day = preferences.get("road_max_driving_hours_per_day") or 8
        road_lines = [
            f"- Route style: {route_style}",
            f"- Driving: {drivers} driver(s), max {max_driving_hours_per_day} hours/day - break the trip into "
            "realistic driving days/stops instead of one long haul, and mention driving time between stops",
        ]
        route_avoidances = preferences.get("road_route_avoidances") or []
        if route_avoidances:
            road_lines.append(f"- Route avoidances: {', '.join(route_avoidances)}")
        avoid = preferences.get("road_avoid") or []
        if avoid:
            road_lines.append(f"- Avoid on route: {', '.join(avoid)}")
        overnight_accommodation = preferences.get("road_overnight_accommodation") or []
        road_lines.append(
            f"- Overnight waypoint stays: {', '.join(overnight_accommodation) if overnight_accommodation else 'no preference'}"
        )
        food_preference = preferences.get("road_food_preference") or "Mix of everything"
        road_lines.append(f"- Food along the route: {food_preference}")
        route_attractions = preferences.get("road_route_attractions") or []
        if route_attractions:
            road_lines.append(f"- Route attractions to favor: {', '.join(route_attractions)}")
        vehicle_note = (preferences.get("road_vehicle_mileage_or_model") or "").strip()
        if vehicle_note:
            road_lines.append(f"- Vehicle: {vehicle_note}")
        max_hours_before_break = preferences.get("road_max_hours_before_break")
        break_duration_minutes = preferences.get("road_break_duration_minutes")
        if max_hours_before_break or break_duration_minutes:
            hours_part = f"every {max_hours_before_break} hour(s)" if max_hours_before_break else "regularly"
            duration_part = f" for {break_duration_minutes} minute(s)" if break_duration_minutes else ""
            road_lines.append(f"- Breaks: stop {hours_part}{duration_part} - reflect these stops in the day's activities")
        fuel_type = (preferences.get("road_fuel_type") or "").strip()
        if fuel_type:
            road_lines.append(f"- Fuel type: {fuel_type}")
        ev_battery_percent = preferences.get("road_ev_battery_percent")
        if ev_battery_percent is not None:
            road_lines.append(f"- Starting EV battery: {ev_battery_percent}% - factor in charging stops if the route needs them")
        ev_recharge_preference = (preferences.get("road_ev_recharge_preference") or "").strip()
        if ev_recharge_preference:
            road_lines.append(f"- EV recharge preference: {ev_recharge_preference}")
        road_flavor_block = (
            "ROAD TRIP PREFERENCES (reflect these in the itinerary's activities/highlights text - "
            "they do not change the price above):\n" + "\n".join(road_lines) + "\n"
        )

    # Mode-agnostic descriptive flavor for the itinerary text (activities/
    # meals/highlights) - same "narrative color, not pricing" role as
    # cruise_flavor_block above, but applies to every transport mode since
    # interests/dietary_preferences/accessibility_requirements/travel_pace
    # are collected in the same "Interests" and "Additional Details" wizard
    # steps regardless of transportation choice. interests and travel_pace
    # are structured fields with sensible defaults from the UI, so they're
    # included whenever present; dietary_preferences and
    # accessibility_requirements are free-text and blank for most users, so
    # they're only added when the user actually wrote something - otherwise
    # this block would print "Accessibility needs: none" into nearly every
    # prompt for no benefit.
    traveler_preference_lines = []
    interests = preferences.get("interests") or []
    if interests:
        traveler_preference_lines.append(
            f"- Interests: {', '.join(interests)} - weave activities and highlights toward these where it fits naturally"
        )
    travel_pace = preferences.get("travel_pace")
    if travel_pace:
        pace_guidance = {
            "Relaxed": "favor a lighter schedule - fewer activities per day, more downtime",
            "Fast-paced": "pack more activities into each day, minimize downtime",
        }.get(travel_pace, "a balanced, moderate number of activities per day")
        traveler_preference_lines.append(f"- Pace: {travel_pace} - {pace_guidance}")
    dietary_preferences = (preferences.get("dietary_preferences") or "").strip()
    if dietary_preferences:
        traveler_preference_lines.append(f"- Dietary: {dietary_preferences} - factor into meal suggestions")
    accessibility_requirements = (preferences.get("accessibility_requirements") or "").strip()
    if accessibility_requirements:
        traveler_preference_lines.append(
            f"- Accessibility: {accessibility_requirements} - factor into activity and accommodation choices"
        )
    traveler_preferences_block = ""
    if traveler_preference_lines:
        traveler_preferences_block = (
            "TRAVELER PREFERENCES (reflect these in the itinerary's activities/meals/highlights "
            "text - they do not change the prices above):\n" + "\n".join(traveler_preference_lines)
        )

    prompt = f"""You are a travel pricing engine. Generate a {plan_type} trip plan as valid JSON only.

╔══════════════════════════════════════════════════════╗
║  MANDATORY CONSTRAINTS — VIOLATION = INVALID OUTPUT  ║
╠══════════════════════════════════════════════════════╣
║ {transport_constraint}
║
║ {hotel_constraint}
║
║ TIER RULE: {plan_type} plan total must be
║ {'the LOWEST cost of all three tiers' if plan_type == 'Budget' else 'BETWEEN Budget and Luxury costs' if plan_type == 'Premium' else 'the HIGHEST cost of all three tiers'}
╚══════════════════════════════════════════════════════╝

TRIP DETAILS:
- Destination: {preferences['destination']}
- From: {preferences['starting_location']}
- Dates: {preferences['departure_date']} to {preferences['return_date']} ({nights} night(s))
- Travelers: {num_travelers}
- Tier: {plan_type}
- Currency: {currency}

TIER GUIDELINES:
{tier_rules[plan_type]}
{cruise_flavor_block}
{road_flavor_block}
{traveler_preferences_block}
OUTPUT: Return ONLY valid JSON, no markdown, no explanation:
{{
  "plan_type": "{plan_type}",
  "currency": "{currency}",
  "currency_symbol": "{currency_symbol}",
  "itinerary": {{
    "day_1": {{
      "date": "{preferences['departure_date']}",
      "transportation": {{"mode": "{anchor_transport_label}", "details": "{transport_details_prefix}{preferences.get('starting_location','')} to {preferences['destination']}", "cost": {anchor_transport_price if anchor_transport_price > 0 else 15000}}},
      "activities": [{{"time": "14:00", "activity": "Check-in and explore", "location": "Hotel", "cost": 0, "category": "free", "pricing_type": "flat_group"}}],
      "accommodation": {{"name": "{hotel_name or 'Hotel'}", "type": "hotel", "cost": {hotel_price_per_night if hotel_price_per_night > 0 else 5000}, "location": "{preferences['destination']}"}},
      "meals": [{{"time": "dinner", "restaurant": "Local restaurant", "cuisine": "Local", "cost": 500}}],
      "daily_total": {int(anchor_transport_price + hotel_price_per_night + 500) if anchor_transport_price and hotel_price_per_night else 20000},
      "cumulative_total": {int(anchor_transport_price + hotel_price_per_night + 500) if anchor_transport_price and hotel_price_per_night else 20000},
      "fixed_costs": {int(anchor_transport_price + hotel_price_per_night) if anchor_transport_price and hotel_price_per_night else 18000},
      "variable_costs": 500
    }}
  }},
  "cost_breakdown": {{
    "transportation": {anchor_transport_price if anchor_transport_price > 0 else 15000},
    "accommodation": 0,
    "food": 0,
    "activities": 0,
    "miscellaneous": 0
  }},
  "total_cost": 0,
  "highlights": ["highlight 1", "highlight 2", "highlight 3"],
  "budget_tips": ["tip 1", "tip 2", "tip 3"]
}}

Fill in EXACTLY {nights} itinerary day(s) - one per night of the stay, dated {preferences['departure_date']} through the night before the {preferences['return_date']} return. Do NOT add a separate day for {preferences['return_date']} itself - the traveler checks out and travels home that morning, so it is not its own paid day; fold the return leg's transportation cost into the final day above instead.
Use EXACT prices from constraints above — especially ₹{anchor_transport_price:,.0f} for {anchor_transport_label} and ₹{hotel_price_per_night:,.0f}/night for hotel.
Generate realistic activities, meals, and local transport for each day.

MEAL AND ACTIVITY PRICING (group size = {num_travelers}):
- Every meal "cost" must be the PER-PERSON price of that meal only (e.g. a ₹400 thali is "cost": 400,
  regardless of group size). Do NOT multiply meal costs by the traveler count yourself — the system
  does that automatically afterward.
- Every activity with cost > 0 must include a "pricing_type" field:
  - "per_person" for anything charged per visitor (entry tickets, adventure sports, rides, per-head
    experiences). Report the PER-PERSON price only - do not multiply by traveler count yourself.
  - "flat_group" for anything with one fixed price regardless of group size (a private car/driver,
    a hired guide, a chartered boat). Report the actual total price for the whole group.
  - If unsure whether something is per-person or a flat group rate, use "per_person" - it's the more
    common case for tickets and experiences."""

    # ── Step 4: Call LLM (retry with backoff on failure) ──────────────────────
    max_attempts = 3
    last_error = None
    for attempt in range(max_attempts):
      try:
        if attempt > 0:
            backoff_seconds = 2 ** (attempt - 1)  # 1s, 2s, ...
            logger.warning(f"Retrying {plan_type} plan generation (attempt {attempt + 1}/{max_attempts}) after {backoff_seconds}s...")
            await asyncio.sleep(backoff_seconds)
        system_message = (
            f"You are a travel cost calculator that outputs ONLY valid JSON. "
            f"You ALWAYS use the exact prices provided in the MANDATORY CONSTRAINTS section. "
            f"{anchor_transport_label.capitalize()} transport cost MUST be ₹{anchor_transport_price:,.0f}. "
            f"Hotel cost MUST be ₹{hotel_price_per_night:,.0f}/night. "
            f"Never invent or change these numbers."
        )

        stream = await _get_gemini_client().aio.models.generate_content_stream(
            model=GEMINI_MODEL,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                system_instruction=system_message,
                response_mime_type="application/json",
                response_json_schema=PLAN_RESPONSE_SCHEMA,
            ),
        )
        await usage_service.log_usage(db, "gemini", user_id=user_id, meta={"context": "generate_single_plan", "plan_type": plan_type})

        full_response = ""
        async for chunk in stream:
            if chunk.text:
                full_response += chunk.text

        # Parse + validate. response_mime_type="application/json" already
        # constrains Gemini's token-level output, so the raw text is expected
        # to be clean JSON - no substring extraction needed. model_validate
        # against GeneratedPlanResponse is the real gate: a response that
        # parses as JSON but doesn't match the expected shape (wrong types,
        # missing required fields, zero days) raises here and is caught by
        # the except block below, feeding the same retry-then-fail path as
        # any other generation failure - it is never silently coerced into a
        # plausible-looking plan.
        plan_data_raw = json.loads(full_response)
        try:
            validated = GeneratedPlanResponse.model_validate(plan_data_raw)
        except ValidationError as e:
            raise ValueError(f"{plan_type}: response failed schema validation: {e}") from e
        plan_data = validated.model_dump()

        await generation_log_service.log_generation_attempt(
            db, trip_id=trip_id, plan_type=plan_type, attempt=attempt + 1, model=GEMINI_MODEL,
            status="success", prompt=prompt, response_text=full_response,
            dietary_preferences=dietary_preferences, accessibility_requirements=accessibility_requirements,
        )

        # ── Step 5: Post-process — enforce exact prices regardless of AI output
        logger.info(f"{plan_type}: anchor {anchor_transport_label}_price={anchor_transport_price}, hotel_price={hotel_price_per_night}")
        logger.info(f"{plan_type}: AI day_1 transport cost before fix = {plan_data.get('itinerary', {}).get('day_1', {}).get('transportation', {}).get('cost', 'N/A')}")

        # Every day/transportation/accommodation/meal/activity below is
        # guaranteed present and correctly typed by GeneratedPlanResponse
        # validation above - no isinstance guards needed here anymore.
        itinerary = plan_data['itinerary']

        if anchor_transport_price > 0:
            plan_data['cost_breakdown']['transportation'] = anchor_transport_price

            days = sorted(itinerary.keys())

            if days:
                # Day 1: outbound transport
                d1 = itinerary[days[0]]
                d1['transportation']['cost'] = anchor_transport_price
                d1['transportation']['mode'] = anchor_transport_label
                if is_train:
                    d1['transportation']['details'] = f"{train_name} ({train_class}) - {preferences.get('starting_location','')} to {preferences['destination']}"
                elif is_cruise:
                    d1['transportation']['details'] = f"{cruise_cabin_type} cabin cruise - {preferences.get('starting_location','')} to {preferences['destination']}"
                elif is_road:
                    d1['transportation']['details'] = f"Self-drive - {preferences.get('starting_location','')} to {preferences['destination']} (~{road_distance_km:.0f} km)"
                else:
                    d1['transportation']['details'] = f"{flight_airline} {flight_number} - {d1['transportation'].get('details', '')}"
                for act in d1['activities']:
                    kw = anchor_transport_label
                    if kw in act.get('activity', '').lower() or 'depart' in act.get('activity', '').lower():
                        act['cost'] = anchor_transport_price

                # Last day: always force return transport to match outbound -
                # unless this is a one-way flight, where there's no return leg
                # to price. Zeroing it out here (rather than leaving whatever
                # number the AI invented) is what keeps the cost_breakdown
                # recompute below at 1x anchor_transport_price instead of the
                # round-trip 2x - it sums every day's transportation.cost, so
                # a zeroed last leg is the whole fix, no separate total-side
                # change needed.
                if len(days) > 1:
                    dl = itinerary[days[-1]]
                    if is_one_way:
                        dl['transportation']['cost'] = 0
                        dl['transportation']['mode'] = anchor_transport_label
                        dl['transportation']['details'] = "No return flight booked (one-way trip)"
                    else:
                        dl['transportation']['cost'] = anchor_transport_price
                        dl['transportation']['mode'] = anchor_transport_label
                        if is_train:
                            dl['transportation']['details'] = f"{train_name} ({train_class}) - {preferences['destination']} to {preferences.get('starting_location','')}"
                        elif is_cruise:
                            dl['transportation']['details'] = f"{cruise_cabin_type} cabin cruise - {preferences['destination']} to {preferences.get('starting_location','')}"
                        elif is_road:
                            dl['transportation']['details'] = f"Self-drive - {preferences['destination']} to {preferences.get('starting_location','')} (~{road_distance_km:.0f} km)"
                        else:
                            dl['transportation']['details'] = f"Return {flight_airline} {flight_number} - {preferences['destination']} to {preferences.get('starting_location','')}"
                elif not is_one_way:
                    # A single-night stay has only one itinerary day (matching
                    # nights, not nights+1 - see the `nights` computation
                    # above), and that one day is simultaneously the outbound
                    # AND the return day. The outbound leg was already priced
                    # on d1 above (d1 IS this day, since len(days) == 1) - add
                    # the return leg's cost on top rather than overwrite it,
                    # so a round trip still ends up priced at the correct
                    # round-trip total (2x anchor_transport_price) instead of
                    # silently losing the return leg just because it has
                    # nowhere else to live. One-way skips this entirely (no
                    # return leg exists to add).
                    d1['transportation']['cost'] = anchor_transport_price * 2

        if hotel_price_per_night > 0:
            for day_data in itinerary.values():
                day_data['accommodation']['cost'] = hotel_price_per_night
                day_data['accommodation']['name'] = hotel_name or day_data['accommodation'].get('name', 'Hotel')

        # Meals and per-person activities come back from the AI as a single person's
        # cost regardless of what the prompt asked - enforce the group scaling here
        # rather than trust the AI to have done the multiplication itself. Age-weighted
        # (fare_units), not raw headcount, so child/senior discounts apply here too.
        _scale_per_person_costs(itinerary, fare_units)

        # Recalculate per-day totals AND the top-level cost_breakdown/total_cost from
        # the same pass over the (now anchor-corrected) itinerary, so the two can never
        # drift apart the way AI-authored daily_total/cumulative_total can.
        day_keys_sorted = sorted(itinerary.keys())

        real_transport = 0
        real_accommodation = 0
        real_food = 0
        real_activities = 0
        running_cumulative = 0

        for day_key in day_keys_sorted:
            day_data = itinerary[day_key]

            day_transport = day_data['transportation']['cost']
            day_accommodation = day_data['accommodation']['cost']
            day_food = sum(meal['cost'] for meal in day_data['meals'])
            day_activities = sum(act['cost'] for act in day_data['activities'])

            day_fixed = day_transport + day_accommodation
            day_variable = day_food + day_activities

            day_data['fixed_costs'] = day_fixed
            day_data['variable_costs'] = day_variable
            day_data['daily_total'] = day_fixed + day_variable

            running_cumulative += day_data['daily_total']
            day_data['cumulative_total'] = running_cumulative

            real_transport += day_transport
            real_accommodation += day_accommodation
            real_food += day_food
            real_activities += day_activities

        plan_data['cost_breakdown'] = {
            'transportation': real_transport,
            'accommodation': real_accommodation,
            'food': real_food,
            'activities': real_activities,
            'miscellaneous': 0,
        }
        plan_data['total_cost'] = running_cumulative
        logger.info(f"{plan_type}: day_1 transport cost AFTER fix = {plan_data.get('itinerary', {}).get('day_1', {}).get('transportation', {}).get('cost', 'N/A')}")
        logger.info(f"{plan_type}: recalculated total = {plan_data['total_cost']}")

        # Force plan_type rather than trust the AI echoed it correctly - the
        # regenerate-single-tier endpoint identifies/replaces a plan in the
        # saved trip by this field, so it must always match what was asked for.
        plan_data['plan_type'] = plan_type
        plan_data['status'] = 'ready'
        plan_data['anchor_pricing'] = anchor
        plan_data.setdefault('currency', currency)
        plan_data.setdefault('currency_symbol', currency_symbol)
        if hotel_limited_inventory:
            plan_data['hotel_inventory_note'] = (
                "Limited hotel options are available for this destination - "
                "Budget/Premium/Luxury tiers may share the same or similarly priced hotel."
            )
        if is_train:
            plan_data['train_placeholder_pricing'] = True
        if is_cruise:
            plan_data['cruise_placeholder_pricing'] = True
        if is_road:
            plan_data['road_placeholder_pricing'] = True
        return plan_data

      except Exception as e:
            last_error = e
            logger.warning(f"Attempt {attempt + 1}/{max_attempts} failed for {plan_type} plan: {e}")
            await generation_log_service.log_generation_attempt(
                db, trip_id=trip_id, plan_type=plan_type, attempt=attempt + 1, model=GEMINI_MODEL,
                status="failed", prompt=prompt, response_text=locals().get('full_response', ''), error=str(e),
                dietary_preferences=dietary_preferences, accessibility_requirements=accessibility_requirements,
            )

    # All attempts genuinely failed - surface this as a distinct failure state
    # rather than a "successful" zero-cost plan. The zero-cost shape used to be
    # indistinguishable from a real (if oddly priced) plan, so it got persisted
    # and shown to the user as if generation had succeeded.
    logger.error(f"All {max_attempts} attempts failed for {plan_type} plan: {last_error}")
    sentry_sdk.capture_exception(last_error, tags={"provider": "gemini", "plan_type": plan_type})
    return {
        "plan_type": plan_type,
        "status": "failed",
        "currency": currency,
        "currency_symbol": currency_symbol,
        "itinerary": {},
        "cost_breakdown": {"transportation": 0, "accommodation": 0, "food": 0, "activities": 0, "miscellaneous": 0},
        "total_cost": 0,
        "highlights": [],
        "budget_tips": [],
        "generation_failed": True,
        "error": f"{plan_type} plan generation failed, please try again.",
        # The anchor fetch (Step 1) runs before the retry loop and never
        # raises out of this function, so it's always available here too -
        # a later regenerate call can reuse it even after a failed attempt.
        "anchor_pricing": anchor,
    }


@router.get("")
async def get_user_trips(request: Request):
    user = await get_current_user(request)
    
    trips = await db.trips.find(
        {"user_id": user.user_id},
        {"_id": 0}
    ).sort("created_at", -1).to_list(100)
    
    return {"trips": trips}


@router.get("/quota-status")
async def get_trip_quota_status(request: Request):
    """Lets the trip planner show remaining free generations before the
    user hits the wall, rather than only surfacing it as an error."""
    user = await get_current_user(request)
    is_premium = await is_user_premium(user.user_id)
    if is_premium:
        return {"is_premium": True, "used": 0, "limit": None, "remaining": None}
    status = await quota_service.get_quota_status(db, user.user_id)
    return {"is_premium": False, **status}


@router.get("/{trip_id}")
async def get_trip(trip_id: str, request: Request):
    user = await get_current_user(request)
    
    trip = await db.trips.find_one(
        {"trip_id": trip_id, "user_id": user.user_id},
        {"_id": 0}
    )
    
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    return trip


@router.get("/{trip_id}/road-route")
async def get_trip_road_route(trip_id: str, request: Request):
    """Real driving route (polyline + distance/duration) between a Road
    trip's origin and destination - Phase 1 of the Road Trip map feature
    (route + waypoints/rendering only; live position tracking and proximity
    alerts are a later phase, not this one).

    Reuses road_origin_coords/road_dest_coords already geocoded and
    persisted on any generated tier's anchor_pricing (see
    _fetch_anchor_pricing's is_road branch) instead of re-geocoding the same
    two place names again on every map view - falls back to a fresh geocode
    only for older trips saved before those fields existed.
    """
    user = await get_current_user(request)

    trip = await db.trips.find_one(
        {"trip_id": trip_id, "user_id": user.user_id},
        {"_id": 0}
    )
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    preferences = trip.get("preferences", {})
    if "road" not in (preferences.get("transportation") or "").lower():
        raise HTTPException(status_code=400, detail="This trip is not a Road trip")

    origin_coords = None
    dest_coords = None
    for plan in trip.get("plans", []):
        anchor = plan.get("anchor_pricing") or {}
        if anchor.get("road_origin_coords") and anchor.get("road_dest_coords"):
            origin_coords = anchor["road_origin_coords"]
            dest_coords = anchor["road_dest_coords"]
            break

    if not origin_coords or not dest_coords:
        origin_coords = await _geocode_place(preferences.get("starting_location", ""))
        dest_coords = await _geocode_place(preferences.get("destination", ""))

    if not origin_coords or not dest_coords:
        raise HTTPException(status_code=502, detail="Could not geocode this trip's origin/destination")

    route = await locations_service.get_driving_route(origin_coords, dest_coords)

    return {
        "origin": {
            "lat": origin_coords["lat"], "lng": origin_coords["lng"],
            "name": preferences.get("starting_location", ""),
        },
        "destination": {
            "lat": dest_coords["lat"], "lng": dest_coords["lng"],
            "name": preferences.get("destination", ""),
        },
        # None if OSRM failed - frontend falls back to a straight line
        # between origin and destination.
        "route": route,
    }


@router.delete("/{trip_id}")
async def delete_trip(trip_id: str, request: Request):
    user = await get_current_user(request)
    
    result = await db.trips.delete_one(
        {"trip_id": trip_id, "user_id": user.user_id}
    )
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Trip not found")
    
    return {"message": "Trip deleted successfully"}


def _day_sort_key(day_key: str):
    # "day_2" before "day_10" - a plain string sort would put day_10 first.
    try:
        return (0, int(day_key.rsplit("_", 1)[-1]))
    except (ValueError, IndexError):
        return (1, day_key)



