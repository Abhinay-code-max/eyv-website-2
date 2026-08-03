"""
Unit tests for _fetch_anchor_pricing's Road trip branch (server.py) - fuel
+ toll rate table, vehicle-count scaling, and the avoid-tolls flag. This
branch had zero test coverage anywhere in the suite before this file: Train/
Cruise/one-way-Flight each have dedicated pricing tests, Road never did.

Calls _fetch_anchor_pricing() directly, same pattern as test_cruise_pricing.py
Section A / test_one_way_flights.py Section A - cheap and deterministic, no
live server or Gemini call needed. _geocode_place is monkeypatched to fixed
coordinates so the distance math is deterministic and offline; the expected
distance is computed via the real server._haversine_km building block rather
than a hardcoded literal, so this test tracks the actual formula (detour
multiplier included) instead of a value that could silently drift from it.
"""
import asyncio
import math
import os
import sys

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

import server  # noqa: E402

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')

USER_ID = "test_road_pricing_user"

# Fixed, offline coordinate pair - roughly Mumbai-to-Pune distance/bearing,
# but the point is determinism, not real-world accuracy.
ORIGIN_COORDS = {"lat": 19.0760, "lng": 72.8777}
DEST_COORDS = {"lat": 18.5204, "lng": 73.8567}
ROAD_DETOUR_MULTIPLIER = 1.3  # must match server.py's own constant


def _db():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _run(coro):
    return asyncio.run(coro)


def _expected_distance_km():
    straight_line = server._haversine_km(
        ORIGIN_COORDS["lat"], ORIGIN_COORDS["lng"], DEST_COORDS["lat"], DEST_COORDS["lng"]
    )
    return round(straight_line * ROAD_DETOUR_MULTIPLIER, 1)


async def _fake_search_hotels(*args, **kwargs):
    return [{"name": "Test Hotel", "price": {"per_night": 4000, "currency": "INR"}, "stars": 3}]


def _get_road_anchor(monkeypatch, plan_type, num_travelers=1, fuel_type=None, avoidances=None, geocode_ok=True):
    monkeypatch.setattr(server, "db", _db())
    monkeypatch.setattr(server.serpapi_hotels_service, "search_hotels", _fake_search_hotels)

    async def _fake_geocode(place):
        if not geocode_ok:
            return None
        return ORIGIN_COORDS if "mumbai" in place.lower() else DEST_COORDS

    monkeypatch.setattr(server, "_geocode_place", _fake_geocode)

    prefs = {
        "starting_location": "Mumbai", "destination": "Pune",
        "departure_date": "2027-03-01", "return_date": "2027-03-03",
        "transportation": "Road", "num_travelers": num_travelers,
    }
    if fuel_type is not None:
        prefs["road_fuel_type"] = fuel_type
    if avoidances is not None:
        prefs["road_route_avoidances"] = avoidances

    fare_units = server._fare_units(num_travelers, 0, 0)
    room_count = server._room_count(num_travelers)
    return _run(server._fetch_anchor_pricing(prefs, plan_type, USER_ID, fare_units, room_count))


# ═══════════════════ distance + geocoding ═══════════════════

def test_road_distance_applies_detour_multiplier_to_great_circle(monkeypatch):
    anchor = _get_road_anchor(monkeypatch, "Budget")
    assert anchor["is_road"] is True
    assert anchor["road_distance_km"] == pytest.approx(_expected_distance_km())


def test_road_origin_and_dest_coords_are_persisted(monkeypatch):
    """Consumed later by the map-route endpoint (per the comment in
    _fetch_anchor_pricing) - must be the actual geocoded points, not
    dropped."""
    anchor = _get_road_anchor(monkeypatch, "Budget")
    assert anchor["road_origin_coords"] == ORIGIN_COORDS
    assert anchor["road_dest_coords"] == DEST_COORDS


def test_road_price_is_zero_when_geocoding_fails(monkeypatch):
    """Graceful degradation, not a crash or a silent fallback to flight
    pricing - is_road must stay True even with no distance estimate."""
    anchor = _get_road_anchor(monkeypatch, "Budget", geocode_ok=False)
    assert anchor["is_road"] is True
    assert anchor["road_price"] == 0
    assert anchor["road_distance_km"] == 0


# ═══════════════════ fuel type + toll rate ═══════════════════

def test_default_fuel_type_is_petrol_rate(monkeypatch):
    anchor = _get_road_anchor(monkeypatch, "Budget", fuel_type=None)
    expected = (7.0 + 2.0) * _expected_distance_km() * 1  # 1 vehicle for 1 traveler
    assert anchor["road_price"] == pytest.approx(expected)


def test_unknown_fuel_type_falls_back_to_petrol_rate(monkeypatch):
    known = _get_road_anchor(monkeypatch, "Budget", fuel_type="Petrol")
    unknown = _get_road_anchor(monkeypatch, "Budget", fuel_type="Hovercraft")
    assert unknown["road_price"] == pytest.approx(known["road_price"])


@pytest.mark.parametrize("fuel_type,rate_per_km", [
    ("Petrol", 7.0),
    ("Diesel", 6.0),
    ("CNG", 4.0),
    ("Hybrid", 4.5),
    ("Electric", 2.0),
])
def test_fuel_type_rate_table(monkeypatch, fuel_type, rate_per_km):
    anchor = _get_road_anchor(monkeypatch, "Budget", fuel_type=fuel_type)
    expected = (rate_per_km + 2.0) * _expected_distance_km() * 1
    assert anchor["road_price"] == pytest.approx(expected)


def test_avoid_tolls_removes_toll_rate_from_price(monkeypatch):
    with_tolls = _get_road_anchor(monkeypatch, "Budget", fuel_type="Petrol", avoidances=[])
    no_tolls = _get_road_anchor(monkeypatch, "Budget", fuel_type="Petrol", avoidances=["Avoid tolls"])

    expected_no_tolls = 7.0 * _expected_distance_km() * 1
    assert no_tolls["road_price"] == pytest.approx(expected_no_tolls)
    assert no_tolls["road_price"] < with_tolls["road_price"]


def test_avoid_highways_alone_does_not_remove_tolls(monkeypatch):
    """Only the literal "Avoid tolls" option zeroes the toll rate -
    "Avoid highways" is a separate, unrelated route-style avoidance."""
    anchor = _get_road_anchor(monkeypatch, "Budget", fuel_type="Petrol", avoidances=["Avoid highways"])
    expected_with_tolls = (7.0 + 2.0) * _expected_distance_km() * 1
    assert anchor["road_price"] == pytest.approx(expected_with_tolls)


# ═══════════════════ vehicle-count scaling ═══════════════════

@pytest.mark.parametrize("num_travelers,expected_vehicles", [
    (1, 1), (2, 1), (3, 1), (4, 1),
    (5, 2), (6, 2), (7, 2), (8, 2),
    (9, 3), (12, 3), (13, 4),
])
def test_vehicle_count_scales_in_groups_of_four(monkeypatch, num_travelers, expected_vehicles):
    anchor = _get_road_anchor(monkeypatch, "Budget", num_travelers=num_travelers)
    assert anchor["road_vehicle_count"] == expected_vehicles


def test_price_is_per_vehicle_not_per_seat(monkeypatch):
    """5 travelers need 2 vehicles, not 5x the 1-traveler rate - road cost
    scales in discrete vehicle jumps, unlike flight/train's per-seat
    pricing."""
    one_traveler = _get_road_anchor(monkeypatch, "Budget", num_travelers=1, fuel_type="Petrol")
    five_travelers = _get_road_anchor(monkeypatch, "Budget", num_travelers=5, fuel_type="Petrol")
    assert five_travelers["road_vehicle_count"] == 2
    assert five_travelers["road_price"] == pytest.approx(one_traveler["road_price"] * 2)
    assert five_travelers["road_price"] != pytest.approx(one_traveler["road_price"] * 5)
