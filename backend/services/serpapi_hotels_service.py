"""
SerpApi Google Hotels search service.
Real hotel data via SerpApi's Google Hotels API - replaces the mock
hotel generator in amadeus_service. Output shape matches
amadeus_service._generate_mock_hotels() exactly, so this is a
drop-in replacement for the rest of the app.
"""
import os
import logging
import httpx
import sentry_sdk
from typing import List, Dict, Optional

from . import ignav_service

logger = logging.getLogger(__name__)

SERPAPI_KEY = os.environ.get('SERPAPI_KEY')
SERPAPI_BASE_URL = 'https://serpapi.com/search'


async def search_hotels(
    destination: str,
    check_in: str,
    check_out: str,
    travelers: int = 1,
    currency: str = 'INR',
) -> List[Dict]:
    """
    Search real hotels via SerpApi Google Hotels API.
    Returns the same shape as amadeus_service._generate_mock_hotels()
    so callers don't need to change.
    Returns empty list on failure - caller decides whether to fall back
    to mock data.
    """
    if not SERPAPI_KEY:
        logger.warning("SERPAPI_KEY not configured, returning empty hotel results")
        return []

    await ignav_service._refresh_rates_if_stale()

    try:
        # Calculate number of nights for total price
        from datetime import date
        try:
            check_in_date = date.fromisoformat(check_in)
            check_out_date = date.fromisoformat(check_out)
            nights = max((check_out_date - check_in_date).days, 1)
        except (ValueError, TypeError):
            nights = 3

        params = {
            'engine': 'google_hotels',
            'q': f'hotels in {destination}',
            'check_in_date': check_in,
            'check_out_date': check_out,
            'adults': max(travelers, 1),
            'currency': currency,
            'gl': 'in',       # India locale - better INR pricing
            'hl': 'en',
            'sort_by': '13',  # sort by most reviewed - gives well-known hotels
            'api_key': SERPAPI_KEY,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(SERPAPI_BASE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        properties = data.get('properties', [])
        if not properties:
            logger.warning(f"No hotel results from SerpApi for '{destination}'")
            return []

        return _transform_serpapi_hotels(properties, nights, currency)

    except httpx.HTTPStatusError as e:
        logger.error(f"SerpApi hotel error: {e.response.status_code} - {e.response.text[:200]}")
        sentry_sdk.capture_exception(e, tags={"provider": "serpapi"})
        return []
    except Exception as e:
        logger.error(f"SerpApi hotel error: {e}")
        sentry_sdk.capture_exception(e, tags={"provider": "serpapi"})
        return []


def _transform_serpapi_hotels(properties: List[Dict], nights: int, currency: str) -> List[Dict]:
    """
    Transform SerpApi Google Hotels results into our standard hotel format,
    matching amadeus_service._generate_mock_hotels() shape exactly.
    """
    hotels = []
    for prop in properties:
        try:
            # Extract price info
            rate_info = prop.get('rate_per_night', {}) or {}
            price_str = rate_info.get('lowest', '') or rate_info.get('extracted_lowest', '')

            # SerpApi returns prices like "₹4,500" or "$55" - extract the number
            per_night = _extract_price(price_str, prop)
            if per_night <= 0:
                continue  # skip hotels with no pricing info

            # SerpApi sometimes ignores our currency param and returns USD.
            # Detect this and convert to INR so the UI stays consistent.
            returned_currency = (rate_info.get('currency', '') or '').upper()
            if returned_currency == 'USD' or (per_night < 500 and currency == 'INR'):
                # Prices under ₹500/night are implausibly cheap - almost certainly USD.
                # Reuses the single canonical USD->INR conversion (services.ignav_service)
                # instead of a second hardcoded rate.
                per_night = ignav_service._to_inr(per_night, 'USD')

            # Star rating - SerpApi returns hotel_class as string like "3-star hotel"
            hotel_class_raw = prop.get('hotel_class', '') or ''
            stars = _extract_stars(hotel_class_raw)

            # Overall rating (out of 10 scale to match our mock format)
            raw_rating = prop.get('overall_rating', 0) or 0
            # SerpApi ratings are out of 5 - convert to our 10-point scale.
            # No rating from real review data means we report none - never
            # invent one from the star class.
            rating = round(raw_rating * 2, 1) if raw_rating > 0 else None

            # Review count
            review_count = prop.get('reviews', 0) or 0

            # Location / GPS
            gps = prop.get('gps_coordinates', {}) or {}
            lat = gps.get('latitude', 0)
            lng = gps.get('longitude', 0)

            # Amenities
            amenities_raw = prop.get('amenities', []) or []
            amenities = amenities_raw[:8] if amenities_raw else [
                'Free WiFi', 'Restaurant', 'Room Service'
            ]

            # Images - SerpApi provides images array
            images = prop.get('images', []) or []
            image_url = images[0].get('thumbnail', '') if images else \
                'https://images.unsplash.com/photo-1566073771259-6a8506099945'

            # Cancellation policy
            cancellation = 'Free cancellation' if prop.get('eco_certified') or \
                any('cancel' in str(a).lower() for a in amenities_raw) \
                else 'Check hotel policy'

            # Address - use description or neighborhood
            address = prop.get('description', '') or \
                prop.get('neighborhood', '') or \
                prop.get('name', '')

            hotels.append({
                'id': prop.get('property_token', f"hotel_{len(hotels)}"),
                'name': prop.get('name', 'Hotel'),
                'chain': _extract_chain(prop.get('name', '')),
                'stars': stars,
                'rating': rating,
                'review_count': review_count,
                'address': address,
                'location': {'lat': lat, 'lng': lng},
                'amenities': amenities,
                'room_type': _infer_room_type(stars),
                'nights': nights,
                'price': {
                    'per_night': per_night,
                    'total': per_night * nights,
                    'currency': currency,
                    'taxes_included': True,
                },
                'cancellation': cancellation,
                'image_url': image_url,
                'booking_url': prop.get('link', ''),
                'live': True,
            })
        except (KeyError, TypeError, ValueError) as e:
            logger.warning(f"Failed to parse hotel property: {e}")
            continue

    if not hotels:
        return []

    # Sort by real provider price ascending. Every field on each hotel dict
    # (name, price, stars, rating, booking_url, ...) is exactly what SerpApi
    # returned - callers that need Budget/Premium/Luxury tiers select from
    # this list (see server._select_tier_hotel), they never edit it.
    return sorted(hotels, key=lambda h: h['price']['per_night'])


def _extract_stars(hotel_class_raw: str) -> int:
    """
    Extract numeric star rating from SerpApi's hotel_class string.
    Handles formats like '3-star hotel', '4 star', '5', etc.
    Defaults to 3 if unparseable.
    """
    import re
    if not hotel_class_raw:
        return 3
    match = re.search(r'(\d)', str(hotel_class_raw))
    if match:
        return max(1, min(5, int(match.group(1))))
    return 3


def _extract_price(price_str: str, prop: Dict) -> float:
    """
    Extract a numeric price from SerpApi's price string.
    Handles formats like '₹4,500', '$55', '4500', etc.
    Falls back to extracted_lowest or total_rate if needed.
    """
    import re

    # Try the string first
    if price_str:
        digits = re.sub(r'[^\d.]', '', str(price_str))
        if digits:
            try:
                return float(digits)
            except ValueError:
                pass

    # Try extracted_lowest directly
    rate_info = prop.get('rate_per_night', {}) or {}
    extracted = rate_info.get('extracted_lowest', 0)
    if extracted:
        return float(extracted)

    # Try total_rate as last resort
    total = prop.get('total_rate', {}) or {}
    extracted_total = total.get('extracted_lowest', 0)
    if extracted_total:
        nights = prop.get('_nights', 1)
        return float(extracted_total) / max(nights, 1)

    return 0.0


def _extract_chain(hotel_name: str) -> str:
    """
    Try to identify the hotel chain from the name.
    Returns the chain name if recognized, otherwise returns the hotel name itself.
    """
    known_chains = [
        'Taj', 'Marriott', 'Hilton', 'Hyatt', 'ITC', 'Oberoi', 'Leela',
        'Radisson', 'Novotel', 'ibis', 'Holiday Inn', 'Sheraton', 'Westin',
        'Four Seasons', 'Ritz-Carlton', 'JW Marriott', 'Le Meridien',
        'Crowne Plaza', 'InterContinental', 'OYO', 'Lemon Tree', 'Treebo',
        'FabHotel', 'Ginger', 'Fortune', 'WelcomHotel',
    ]
    for chain in known_chains:
        if chain.lower() in hotel_name.lower():
            return chain
    # Return first word of name as a rough chain identifier
    return hotel_name.split()[0] if hotel_name else 'Independent'


def _infer_room_type(stars: int) -> str:
    """Infer a sensible default room type based on star rating."""
    if stars >= 5:
        return 'Deluxe Room'
    elif stars >= 4:
        return 'Superior Room'
    elif stars >= 3:
        return 'Standard Room'
    else:
        return 'Basic Room'
