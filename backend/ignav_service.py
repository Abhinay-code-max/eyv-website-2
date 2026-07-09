"""
Ignav Flight Service — https://ignav.com
Real worldwide flight fares via Ignav REST API.
Drop-in replacement for duffel_service / sky_scrapper_service.
Same output shape as all previous flight services.
"""
import os
import logging
import httpx
from typing import List, Dict, Optional

from .airport_codes import get_iata_code

logger = logging.getLogger(__name__)

IGNAV_API_KEY = os.environ.get('IGNAV_API_KEY')
IGNAV_BASE_URL = "https://ignav.com/api/fares"

_RATES_TO_INR = {
    'USD': 83.0,
    'EUR': 90.0,
    'GBP': 105.0,
    'AED': 22.6,
    'SGD': 62.0,
    'AUD': 54.0,
    'JPY': 0.56,
    'INR': 1.0,
}


def _headers() -> Dict[str, str]:
    return {
        "X-Api-Key": IGNAV_API_KEY,
        "Content-Type": "application/json",
    }


def _to_inr(amount: float, currency: str) -> float:
    rate = _RATES_TO_INR.get(currency.upper(), 83.0)
    return round(amount * rate, 2)


def _resolve_iata(location: str) -> str:
    """Resolve city/airport name to IATA code."""
    code = get_iata_code(location)
    if code:
        return code
    # If it looks like an IATA code already (3 letters), use it directly
    if len(location) == 3 and location.isalpha():
        return location.upper()
    # Take first 3 letters as last resort
    return location[:3].upper()


async def search_flights(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: Optional[str] = None,
    travelers: int = 1,
) -> List[Dict]:
    """
    Search real flights via Ignav API.
    Returns same shape as duffel_service.search_flights().
    Returns empty list on failure — caller falls back to mock.
    """
    if not IGNAV_API_KEY:
        logger.warning("IGNAV_API_KEY not set")
        return []

    origin_iata = _resolve_iata(origin)
    dest_iata = _resolve_iata(destination)

    try:
        if return_date:
            endpoint = f"{IGNAV_BASE_URL}/round-trip"
            payload = {
                "origin": origin_iata,
                "destination": dest_iata,
                "departure_date": departure_date,
                "return_date": return_date,
                "adults": max(travelers, 1),
                "cabin_class": "economy",
            }
        else:
            endpoint = f"{IGNAV_BASE_URL}/one-way"
            payload = {
                "origin": origin_iata,
                "destination": dest_iata,
                "departure_date": departure_date,
                "adults": max(travelers, 1),
                "cabin_class": "economy",
            }

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(endpoint, json=payload, headers=_headers())
            resp.raise_for_status()
            data = resp.json()

        itineraries = data.get("itineraries", [])
        if not itineraries:
            logger.warning(f"Ignav returned no flights for {origin_iata} → {dest_iata}")
            return []

        return _transform(itineraries, origin_iata, dest_iata)

    except httpx.HTTPStatusError as e:
        logger.error(f"Ignav API error: {e.response.status_code} - {e.response.text[:300]}")
        return []
    except Exception as e:
        logger.error(f"Ignav error: {e}")
        return []


def _transform(itineraries: List[Dict], origin: str, destination: str) -> List[Dict]:
    """Transform Ignav itineraries into EYV standard flight format."""
    flights = []

    for item in itineraries[:15]:
        try:
            price_obj = item.get("price", {})
            amount = float(price_obj.get("amount", 0))
            currency = price_obj.get("currency", "USD")
            if amount <= 0:
                continue

            price_inr = _to_inr(amount, currency)

            outbound = item.get("outbound", {})
            segments = outbound.get("segments", [])
            if not segments:
                continue

            first_seg = segments[0]
            last_seg = segments[-1]

            airline_name = (
                first_seg.get("operating_carrier_name")
                or first_seg.get("marketing_carrier_code", "Unknown Airline")
            )
            carrier_code = first_seg.get("marketing_carrier_code", "")
            flight_number = f"{carrier_code}{first_seg.get('flight_number', '')}"

            dep_time_raw = first_seg.get("departure_time_local", "")
            arr_time_raw = last_seg.get("arrival_time_local", "")

            dep_date = dep_time_raw[:10] if dep_time_raw else ""
            dep_time = dep_time_raw[11:16] if len(dep_time_raw) > 10 else "00:00"
            arr_date = arr_time_raw[:10] if arr_time_raw else ""
            arr_time = arr_time_raw[11:16] if len(arr_time_raw) > 10 else "00:00"

            duration_mins = outbound.get("duration_minutes", 0)
            duration_str = f"{duration_mins // 60}h {duration_mins % 60}m" if duration_mins else "N/A"

            stops = max(len(segments) - 1, 0)

            dep_airport = first_seg.get("departure_airport", origin)
            arr_airport = last_seg.get("arrival_airport", destination)
            aircraft = first_seg.get("aircraft", "")

            flights.append({
                "id": item.get("ignav_id", f"ignav_{len(flights)}"),
                "airline": airline_name,
                "carrier_code": carrier_code,
                "flight_number": flight_number,
                "aircraft": aircraft,
                "origin": dep_airport,
                "destination": arr_airport,
                "departure": {
                    "date": dep_date,
                    "time": dep_time,
                    "airport": dep_airport,
                },
                "arrival": {
                    "date": arr_date,
                    "time": arr_time,
                    "airport": arr_airport,
                },
                "duration": duration_str,
                "duration_mins": duration_mins,
                "stops": stops,
                "cabin_class": item.get("cabin_class", "Economy").title(),
                "price": {
                    "total": price_inr,
                    "per_traveler": price_inr,
                    "currency": "INR",
                    "original_amount": amount,
                    "original_currency": currency,
                },
                "available_seats": 9,
                "baggage": "1 carry-on included",
                "booking_id": item.get("ignav_id"),
                "live": True,
                "source": "ignav",
            })

        except Exception as e:
            logger.warning(f"Failed to parse Ignav itinerary: {e}")
            continue

    return sorted(flights, key=lambda f: f["price"]["total"])


async def get_anchor_flight(
    origin: str,
    destination: str,
    departure_date: str,
    travelers: int = 1,
    preference: str = "cheapest",
) -> Optional[Dict]:
    """
    Get a single representative flight for AI plan price anchoring.
    Same interface as duffel_service.get_anchor_flight().
    """
    flights = await search_flights(origin, destination, departure_date, travelers=travelers)
    if not flights:
        return None

    if preference == "direct":
        direct = [f for f in flights if f["stops"] == 0]
        candidates = direct if direct else flights
        return min(candidates, key=lambda f: f["price"]["total"])

    if preference == "fastest":
        return min(flights, key=lambda f: f.get("duration_mins", 9999))

    return min(flights, key=lambda f: f["price"]["total"])
