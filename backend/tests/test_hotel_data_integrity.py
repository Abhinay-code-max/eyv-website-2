"""
Regression tests for the hotel-price/rating fabrication bug.

Root cause: _transform_serpapi_hotels() used to split price-sorted SerpApi
results into thirds and then, whenever a bucket didn't already satisfy
Budget < Premium < Luxury, overwrote real hotels' price['per_night'] /
price['total'] (x1.4 / x1.6) and stars (forced to >=4 / >=5) so the three
tiers always looked separated. That mutated real, named, bookable hotels'
provider-supplied data - a user clicking through to the booking_url would
see different numbers than EYV displayed.

Fix: _transform_serpapi_hotels() now only sorts by real price - it never
edits a hotel's fields. Tier selection (server._select_tier_hotel) picks
cheapest/median/most-expensive from that untouched, real list instead.

These tests are fast and network-free: they feed synthetic SerpApi-shaped
`properties` payloads directly into the transform function.
"""
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

from services.serpapi_hotels_service import _transform_serpapi_hotels  # noqa: E402
from server import _select_tier_hotel  # noqa: E402


def _prop(name, price_inr, stars, rating_5, reviews=100, link="https://example.com/book"):
    """Build a synthetic SerpApi 'properties' entry."""
    return {
        "name": name,
        "property_token": name.replace(" ", "_").lower(),
        "rate_per_night": {"lowest": f"₹{price_inr:,}", "currency": "INR"},
        "hotel_class": f"{stars}-star hotel",
        "overall_rating": rating_5,
        "reviews": reviews,
        "link": link,
        "gps_coordinates": {"latitude": 12.9, "longitude": 77.6},
        "amenities": ["Free WiFi"],
        "images": [],
    }


# ---------- Hotel Price & Rating Integrity ----------

def test_transform_preserves_exact_price():
    props = [_prop("Hotel Alpha", 7200, 4, 4.0)]
    hotels = _transform_serpapi_hotels(props, nights=1, currency="INR")
    assert hotels[0]["price"]["per_night"] == 7200
    assert hotels[0]["price"]["total"] == 7200 * 1
    assert hotels[0]["price"]["currency"] == "INR"


def test_transform_preserves_exact_stars_and_name():
    props = [_prop("Hotel Alpha", 7200, 4, 4.0)]
    hotels = _transform_serpapi_hotels(props, nights=1, currency="INR")
    assert hotels[0]["name"] == "Hotel Alpha"
    assert hotels[0]["stars"] == 4


def test_transform_preserves_booking_url():
    props = [_prop("Hotel Alpha", 7200, 4, 4.0, link="https://provider.example/hotel/alpha")]
    hotels = _transform_serpapi_hotels(props, nights=1, currency="INR")
    assert hotels[0]["booking_url"] == "https://provider.example/hotel/alpha"


def test_no_price_inflation_across_three_tiers():
    """The exact scenario the old bug mutated: 3 hotels close in price used
    to get Premium/Luxury bumped by x1.4/x1.6 and stars forced up. Now every
    hotel's price and stars must equal what was fed in."""
    props = [
        _prop("Budget Inn", 3000, 3, 3.5),
        _prop("Mid Hotel", 3100, 3, 3.6),
        _prop("Top Hotel", 3200, 3, 3.7),
    ]
    hotels = _transform_serpapi_hotels(props, nights=2, currency="INR")
    by_name = {h["name"]: h for h in hotels}

    assert by_name["Budget Inn"]["price"]["per_night"] == 3000
    assert by_name["Mid Hotel"]["price"]["per_night"] == 3100
    assert by_name["Top Hotel"]["price"]["per_night"] == 3200

    # Old bug would have forced Mid/Top stars to 4 and 5 respectively.
    assert by_name["Budget Inn"]["stars"] == 3
    assert by_name["Mid Hotel"]["stars"] == 3
    assert by_name["Top Hotel"]["stars"] == 3


def test_rating_matches_provider_overall_rating():
    # overall_rating is out of 5 on SerpApi; our scale is out of 10 (x2) -
    # a straightforward, documented unit conversion, not a fabrication.
    props = [_prop("Hotel Alpha", 5000, 4, 4.2)]
    hotels = _transform_serpapi_hotels(props, nights=1, currency="INR")
    assert hotels[0]["rating"] == round(4.2 * 2, 1)


# ---------- Tier Selection (selection only, no mutation) ----------

def test_tier_selection_picks_real_distinct_prices():
    props = [
        _prop("Cheap Stay", 3000, 3, 3.5),
        _prop("Mid Stay", 5000, 4, 4.0),
        _prop("Lux Stay", 8000, 5, 4.5),
    ]
    hotels = _transform_serpapi_hotels(props, nights=1, currency="INR")

    budget, budget_limited = _select_tier_hotel(hotels, "Budget")
    premium, premium_limited = _select_tier_hotel(hotels, "Premium")
    luxury, luxury_limited = _select_tier_hotel(hotels, "Luxury")

    assert budget["price"]["per_night"] == 3000
    assert premium["price"]["per_night"] == 5000
    assert luxury["price"]["per_night"] == 8000
    assert not budget_limited and not premium_limited and not luxury_limited


def test_tier_selection_never_mutates_source_list():
    props = [
        _prop("Cheap Stay", 3000, 3, 3.5),
        _prop("Mid Stay", 5000, 4, 4.0),
        _prop("Lux Stay", 8000, 5, 4.5),
    ]
    hotels = _transform_serpapi_hotels(props, nights=1, currency="INR")
    before = [dict(h["price"]) for h in hotels]

    for plan_type in ("Budget", "Premium", "Luxury"):
        _select_tier_hotel(hotels, plan_type)

    after = [dict(h["price"]) for h in hotels]
    assert before == after


# ---------- Limited Inventory ----------

def test_limited_inventory_flagged_when_prices_are_bunched():
    props = [
        _prop("Inn A", 3000, 3, 3.5),
        _prop("Inn B", 3200, 3, 3.5),
        _prop("Inn C", 3300, 3, 3.5),
    ]
    hotels = _transform_serpapi_hotels(props, nights=1, currency="INR")
    _, limited = _select_tier_hotel(hotels, "Luxury")
    assert limited is True


def test_limited_inventory_does_not_fabricate_separation():
    """Even when flagged as limited inventory, the selected hotel's price
    must be a real, unmodified provider price - never invented."""
    props = [
        _prop("Inn A", 3000, 3, 3.5),
        _prop("Inn B", 3200, 3, 3.5),
        _prop("Inn C", 3300, 3, 3.5),
    ]
    hotels = _transform_serpapi_hotels(props, nights=1, currency="INR")
    luxury, limited = _select_tier_hotel(hotels, "Luxury")
    assert limited is True
    assert luxury["price"]["per_night"] == 3300  # real price, not inflated


def test_single_hotel_result_is_not_fabricated_into_three_tiers():
    props = [_prop("Only Hotel", 4000, 3, 4.0)]
    hotels = _transform_serpapi_hotels(props, nights=1, currency="INR")

    budget, b_limited = _select_tier_hotel(hotels, "Budget")
    premium, p_limited = _select_tier_hotel(hotels, "Premium")
    luxury, l_limited = _select_tier_hotel(hotels, "Luxury")

    for h in (budget, premium, luxury):
        assert h["price"]["per_night"] == 4000
        assert h["stars"] == 3
    assert b_limited and p_limited and l_limited


def test_empty_hotel_results_flagged_limited_no_crash():
    hotel, limited = _select_tier_hotel([], "Budget")
    assert hotel is None
    assert limited is True


# ---------- Regression: multiplier/forced-rating logic must not return ----------

def test_no_multiplier_patterns_in_serpapi_service_source():
    """Static guard: fail loudly if anyone re-introduces the
    inflate-to-force-ordering pattern into the transform function."""
    src_path = os.path.join(BACKEND_DIR, "services", "serpapi_hotels_service.py")
    with open(src_path, "r", encoding="utf-8") as f:
        source = f.read()

    banned_snippets = [
        "* 1.4", "* 1.6", "budget_bucket", "premium_bucket", "luxury_bucket",
        "max(h['stars']", 'max(h["stars"]',
    ]
    for snippet in banned_snippets:
        assert snippet not in source, f"fabrication pattern reintroduced: {snippet!r}"
