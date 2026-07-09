"""
Sky Scrapper Flight Service (RapidAPI)
Real worldwide flight data via Sky Scrapper API (Skyscanner data).
Drop-in replacement for duffel_service - same output shape.
"""
import os
import logging
import httpx
from typing import List, Dict, Optional

from .airport_codes import get_iata_code

logger = logging.getLogger(__name__)

RAPIDAPI_KEY = os.environ.get('RAPIDAPI_KEY')
SKY_SCRAPPER_HOST = "sky-scrapper.p.rapidapi.com"
BASE_URL = "https://sky-scrapper.p.rapidapi.com/api"

_APPROX_RATES_TO_INR = {
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
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": SKY_SCRAPPER_HOST,
    }


def _to_inr(amount: float, currency: str) -> float:
    rate = _APPROX_RATES_TO_INR.get(currency.upper(), 83.0)
    return round(amount * rate, 2)


async def _resolve_sky_id(city_or_iata: str) -> Optional[Dict]:
    """
    Resolve a city name or IATA code to Sky Scrapper's skyId + entityId.
    Returns dict with 'skyId' and 'entityId', or None on failure.
    """
    if not RAPIDAPI_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{BASE_URL}/v1/flights/searchAirport",
                params={"query": city_or_iata, "locale": "en-US"},
                headers=_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("data", [])
            if not results:
                return None
            # Pick the first result (most relevant)
            top = results[0]
            return {
                "skyId": top.get("skyId") or top.get("iataCode", ""),
                "entityId": top.get("entityId", ""),
                "name": top.get("presentation", {}).get("title", city_or_iata),
            }
    except Exception as e:
        logger.warning(f"Sky Scrapper airport lookup failed for '{city_or_iata}': {e}")
        return None


async def search_flights(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: Optional[str] = None,
    travelers: int = 1,
) -> List[Dict]:
    """
    Search real flights via Sky Scrapper (Skyscanner data).
    Returns same shape as duffel_service.search_flights().
    Returns empty list on failure — caller falls back to mock.
    """
    if not RAPIDAPI_KEY:
        logger.warning("RAPIDAPI_KEY not set, skipping Sky Scrapper search")
        return []

    # Resolve airport IDs
    origin_info = await _resolve_sky_id(origin)
    dest_info = await _resolve_sky_id(destination)

    if not origin_info or not dest_info:
        # Fall back to IATA code lookup
        origin_iata = get_iata_code(origin) or origin[:3].upper()
        dest_iata = get_iata_code(destination) or destination[:3].upper()
        origin_info = {"skyId": origin_iata, "entityId": ""}
        dest_info = {"skyId": dest_iata, "entityId": ""}

    try:
        params = {
            "originSkyId": origin_info["skyId"],
            "destinationSkyId": dest_info["skyId"],
            "originEntityId": origin_info.get("entityId", ""),
            "destinationEntityId": dest_info.get("entityId", ""),
            "date": departure_date,
            "adults": max(travelers, 1),
            "currency": "INR",
            "market": "IN",
            "locale": "en-IN",
            "cabinClass": "economy",
            "countryCode": "IN",
        }
        if return_date:
            params["returnDate"] = return_date

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{BASE_URL}/v2/flights/searchFlightsComplete",
                params=params,
                headers=_headers(),
            )
            resp.raise_for_status()
            data = resp.json()

        itineraries = (
            data.get("data", {})
                .get("itineraries", [])
        )

        if not itineraries:
            # Try v1 endpoint as fallback
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(
                    f"{BASE_URL}/v1/flights/searchFlights",
                    params=params,
                    headers=_headers(),
                )
                resp.raise_for_status()
                data = resp.json()
            itineraries = data.get("data", {}).get("itineraries", [])

        if not itineraries:
            logger.warning(f"Sky Scrapper returned no flights for {origin} → {destination}")
            return []

        return _transform_itineraries(itineraries, origin, destination, departure_date)

    except httpx.HTTPStatusError as e:
        logger.error(f"Sky Scrapper API error: {e.response.status_code} - {e.response.text[:300]}")
        return []
    except Exception as e:
        logger.error(f"Sky Scrapper error: {e}")
        return []


def _transform_itineraries(itineraries: List[Dict], origin: str, destination: str, date: str) -> List[Dict]:
    """Transform Sky Scrapper itineraries into EYV standard flight format."""
    flights = []

    for item in itineraries[:15]:  # cap at 15 results
        try:
            # Price
            price_obj = item.get("price", {})
            raw_price = (
                price_obj.get("raw")
                or price_obj.get("formatted", "0").replace("₹", "").replace(",", "").strip()
            )
            try:
                total_price = float(raw_price)
            except (ValueError, TypeError):
                continue

            if total_price <= 0:
                continue

            # Legs (outbound)
            legs = item.get("legs", [])
            if not legs:
                continue
            leg = legs[0]

            segments = leg.get("segments", [])
            if not segments:
                continue

            first_seg = segments[0]
            last_seg = segments[-1]

            # Carrier
            carriers = leg.get("carriers", {})
            marketing = carriers.get("marketing", [{}])
            carrier = marketing[0] if marketing else {}
            airline_name = carrier.get("name", "Unknown Airline")
            airline_code = carrier.get("alternateId", "") or carrier.get("iata", "")

            # Flight number
            flight_num = first_seg.get("flightNumber", "")
            full_flight_num = f"{airline_code}{flight_num}" if airline_code else flight_num

            # Times
            dep_time = leg.get("departure", "") or first_seg.get("departure", "")
            arr_time = leg.get("arrival", "") or last_seg.get("arrival", "")

            dep_date = dep_time[:10] if dep_time else date
            dep_time_str = dep_time[11:16] if len(dep_time) > 10 else "00:00"
            arr_date = arr_time[:10] if arr_time else date
            arr_time_str = arr_time[11:16] if len(arr_time) > 10 else "00:00"

            # Duration
            duration_mins = leg.get("durationInMinutes", 0)
            duration_str = f"{duration_mins // 60}h {duration_mins % 60}m" if duration_mins else "N/A"

            # Stops
            stop_count = leg.get("stopCount", len(segments) - 1)

            # Origin/destination airports
            origin_airport = (
                leg.get("origin", {}).get("displayCode", "")
                or first_seg.get("origin", {}).get("displayCode", origin[:3].upper())
            )
            dest_airport = (
                leg.get("destination", {}).get("displayCode", "")
                or last_seg.get("destination", {}).get("displayCode", destination[:3].upper())
            )

            flights.append({
                "id": item.get("id", f"ss_{len(flights)}"),
                "airline": airline_name,
                "carrier_code": airline_code,
                "flight_number": full_flight_num,
                "origin": origin_airport,
                "destination": dest_airport,
                "departure": {
                    "date": dep_date,
                    "time": dep_time_str,
                    "airport": origin_airport,
                },
                "arrival": {
                    "date": arr_date,
                    "time": arr_time_str,
                    "airport": dest_airport,
                },
                "duration": duration_str,
                "duration_mins": duration_mins,
                "stops": stop_count,
                "cabin_class": "Economy",
                "price": {
                    "total": total_price,
                    "per_traveler": total_price,
                    "currency": "INR",
                },
                "available_seats": 9,
                "baggage": "1 carry-on included",
                "live": True,
                "source": "skyscanner",
            })

        except Exception as e:
            logger.warning(f"Failed to parse Sky Scrapper itinerary: {e}")
            continue

    # Sort cheapest first
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

    # default: cheapest
    return min(flights, key=lambda f: f["price"]["total"])
