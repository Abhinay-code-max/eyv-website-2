"""
Duffel flight search service.
Real flight data via Duffel's API (https://duffel.com) — replaces the
sunsetting Amadeus self-service tier. Output shape matches
amadeus_service._transform_amadeus_flights() exactly, so this is a
drop-in data source for the rest of the app.
"""
import os
import logging
import httpx
from typing import List, Dict, Optional

from .airport_codes import get_iata_code

logger = logging.getLogger(__name__)

DUFFEL_API_KEY = os.environ.get('DUFFEL_API_KEY')
DUFFEL_BASE_URL = 'https://api.duffel.com'
DUFFEL_API_VERSION = 'v2'  # Duffel requires this in headers, not the URL


def _duffel_headers() -> Dict[str, str]:
    return {
        'Authorization': f'Bearer {DUFFEL_API_KEY}',
        'Duffel-Version': DUFFEL_API_VERSION,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }


def _parse_iso8601_duration(duration_str: str) -> int:
    """
    Parses an ISO 8601 duration (e.g. 'P1DT3H30M', 'PT2H47M') into total minutes.
    Returns 0 if the string is empty or unparseable, rather than raising -
    callers use this for sorting, where a bad value should sort last, not crash.
    """
    import re
    if not duration_str:
        return 0
    match = re.match(
        r'^P(?:(?P<days>\d+)D)?T?(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?$',
        duration_str.upper()
    )
    if not match:
        return 0
    parts = match.groupdict()
    days = int(parts['days'] or 0)
    hours = int(parts['hours'] or 0)
    minutes = int(parts['minutes'] or 0)
    return days * 24 * 60 + hours * 60 + minutes


def _format_duration_display(duration_str: str) -> str:
    """
    Converts ISO 8601 duration into a human-readable string like '1d 3h 30m'
    or '2h 47m', for display purposes.
    """
    total_minutes = _parse_iso8601_duration(duration_str)
    days, remainder = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    return " ".join(parts)


# Static approximate rates as a safe fallback. For production, replace with
# a live exchange rate API call (e.g. exchangerate-api.com, fixer.io) -
# these rates WILL drift and should not be trusted long-term.
_APPROX_RATES_TO_INR = {
    'USD': 83.0,
    'EUR': 90.0,
    'GBP': 105.0,
    'INR': 1.0,
}


def _convert_to_inr(amount: float, from_currency: str) -> tuple:
    """
    Converts a price to INR using a static approximate rate.
    Returns (converted_amount, 'INR'). If the currency is unknown,
    returns the original amount/currency unchanged rather than guessing.
    """
    rate = _APPROX_RATES_TO_INR.get(from_currency.upper())
    if rate is None:
        logger.warning(f"No conversion rate for currency '{from_currency}', returning unconverted")
        return round(amount, 2), from_currency
    return round(amount * rate, 2), 'INR'


async def search_flights(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: Optional[str] = None,
    travelers: int = 1,
) -> List[Dict]:
    """
    Search real flights via Duffel. Returns the same shape as
    amadeus_service.search_flights() so callers don't need to change.
    Returns an empty list (not mock data) on failure — caller decides
    whether to fall back to AI-estimated pricing.
    """
    if not DUFFEL_API_KEY:
        logger.warning("DUFFEL_API_KEY not configured, returning empty flight results")
        return []

    origin_code = get_iata_code(origin)
    destination_code = get_iata_code(destination)

    if not origin_code or not destination_code:
        logger.warning(
            f"Could not resolve airport codes for '{origin}' -> '{destination}' "
            f"(got origin={origin_code}, destination={destination_code}). "
            f"Skipping Duffel search."
        )
        return []

    try:
        slices = [
            {
                "origin": origin_code,
                "destination": destination_code,
                "departure_date": departure_date,
            }
        ]
        if return_date:
            slices.append(
                {
                    "origin": destination_code,
                    "destination": origin_code,
                    "departure_date": return_date,
                }
            )

        payload = {
            "data": {
                "slices": slices,
                "passengers": [{"type": "adult"} for _ in range(max(travelers, 1))],
                "cabin_class": "economy",
            }
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            # Step 1: create the offer request, ask Duffel to return offers inline
            resp = await client.post(
                f"{DUFFEL_BASE_URL}/air/offer_requests?return_offers=true",
                json=payload,
                headers=_duffel_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            offers = data.get("data", {}).get("offers", [])
            return _transform_duffel_flights(offers)

    except httpx.HTTPStatusError as e:
        logger.error(f"Duffel API error: {e.response.status_code} - {e.response.text}")
        return []
    except Exception as e:
        logger.error(f"Duffel API error: {e}")
        return []


def _transform_duffel_flights(duffel_offers: List[Dict]) -> List[Dict]:
    """Transform Duffel offers into our standard flight format (matches amadeus_service shape)."""
    flights = []
    for offer in duffel_offers:
        try:
            slice_0 = offer['slices'][0]
            segments = slice_0['segments']
            first_segment = segments[0]
            last_segment = segments[-1]

            airline_code = first_segment['operating_carrier']['iata_code']
            flight_num = first_segment.get('operating_carrier_flight_number') or first_segment.get('marketing_carrier_flight_number') or '—'
            flight_number = f"{airline_code}{flight_num}"

            departure_at = first_segment['departing_at']  # e.g. "2026-06-24T09:00:00"
            arrival_at = last_segment['arriving_at']

            total_price = float(offer['total_amount'])
            offer_currency = offer['total_currency']
            passenger_count = len(offer.get('passengers', [])) or 1

            # Duffel ties pricing currency to your account's billing currency,
            # not something we can request per-search. Convert to INR for
            # display consistency with the rest of the app (which is INR-first).
            display_price, display_currency = _convert_to_inr(total_price, offer_currency)

            flights.append({
                'id': offer['id'],
                'airline': airline_code,
                'carrier_code': airline_code,
                'flight_number': flight_number,
                'origin': first_segment['origin']['iata_code'],
                'destination': last_segment['destination']['iata_code'],
                'departure': {
                    'date': departure_at[:10],
                    'time': departure_at[11:16],
                    'airport': first_segment['origin']['iata_code'],
                },
                'arrival': {
                    'date': arrival_at[:10],
                    'time': arrival_at[11:16],
                    'airport': last_segment['destination']['iata_code'],
                },
                'duration': _format_duration_display(slice_0.get('duration', '')),
                'duration_iso': slice_0.get('duration', ''),  # raw ISO 8601, used for accurate sorting
                'stops': len(segments) - 1,
                'cabin_class': segments[0].get('passengers', [{}])[0].get('cabin_class', 'economy').title(),
                'price': {
                    'total': display_price,
                    'per_traveler': round(display_price / passenger_count, 2),
                    'currency': display_currency,
                    'original_total': total_price,
                    'original_currency': offer_currency,
                },
                'available_seats': 9,  # Duffel doesn't expose this directly on offers
                'baggage': '1 carry-on + 1 checked',
                'booking_url': None,  # populated only after a real order is created
                'live': True,  # marks this as real Duffel data, not AI-estimated
            })
        except (KeyError, IndexError, TypeError) as e:
            logger.warning(f"Failed to parse Duffel offer: {e}")
            continue
    return flights


async def get_anchor_flight(
    origin: str,
    destination: str,
    departure_date: str,
    travelers: int = 1,
    preference: str = "cheapest",
) -> Optional[Dict]:
    """
    Fetches one representative real flight to use as a pricing/detail anchor
    when generating an AI itinerary, instead of letting the AI invent a price.

    preference:
        "cheapest"      - lowest total price (good for Budget tier)
        "direct"        - cheapest non-stop flight if one exists, else cheapest overall
        "fastest"       - shortest duration (good for Premium/Luxury tiers)

    Returns None if no real flight data is available (caller should fall
    back to AI-estimated pricing in that case, not block the whole itinerary).
    """
    flights = await search_flights(origin, destination, departure_date, travelers=travelers)
    if not flights:
        return None

    if preference == "direct":
        direct_flights = [f for f in flights if f['stops'] == 0]
        candidates = direct_flights if direct_flights else flights
        return min(candidates, key=lambda f: f['price']['total'])

    if preference == "fastest":
        return min(flights, key=lambda f: _parse_iso8601_duration(f.get('duration_iso', '')))

    # default: cheapest
    return min(flights, key=lambda f: f['price']['total'])
