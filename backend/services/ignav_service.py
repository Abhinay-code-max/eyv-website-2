"""
Ignav Flight Service — https://ignav.com
Real worldwide flight fares via Ignav REST API.
Drop-in replacement for duffel_service / sky_scrapper_service.
Same output shape as all previous flight services.
"""
import os
import logging
import httpx
import sentry_sdk
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional

from .airport_codes import get_iata_code

logger = logging.getLogger(__name__)

IGNAV_API_KEY = os.environ.get('IGNAV_API_KEY')
IGNAV_BASE_URL = "https://ignav.com/api/fares"

# Hardcoded safety-net rates - only used if a live rate has NEVER been
# fetched successfully (fresh deploy with the FX API unreachable since
# startup). Normal operation uses _cached_rates below, refreshed daily
# from a real FX source - see _refresh_rates_if_stale().
_FALLBACK_RATES_TO_INR = {
    'USD': 83.0,
    'EUR': 90.0,
    'GBP': 105.0,
    'AED': 22.6,
    'SGD': 62.0,
    'AUD': 54.0,
    'JPY': 0.56,
    'INR': 1.0,
}

# open.er-api.com's key-free endpoint - no signup, no API key, updated
# daily. Returns all currencies against a USD base in one call, which we
# convert into "multiply by this to get INR" rates for every currency it
# knows about (not just the 8 above) - so a new pair like EUR->INR needs
# no code change, just _to_inr("...", "EUR") on already-cached data.
_FX_API_URL = "https://open.er-api.com/v6/latest/USD"
_REFRESH_INTERVAL = timedelta(hours=24)
_RETRY_BACKOFF = timedelta(minutes=5)  # don't hammer the API while it's down

_cached_rates: Optional[Dict[str, float]] = None
_last_fetch_success: Optional[datetime] = None
_last_fetch_attempt: Optional[datetime] = None


async def _refresh_rates_if_stale() -> None:
    """Refresh the live FX table roughly once a day.

    Cheap no-op after the first call each day (a couple of datetime
    comparisons), so it's safe to call from every conversion-using
    endpoint without worrying about hammering the FX API. On failure,
    retries back off to once every _RETRY_BACKOFF rather than firing on
    every request while the API is down - _to_inr keeps using the last
    known-good cached rate in the meantime, or the hardcoded
    _FALLBACK_RATES_TO_INR (loudly logged as degraded) if a rate has
    never been fetched successfully at all.
    """
    global _cached_rates, _last_fetch_success, _last_fetch_attempt
    now = datetime.now(timezone.utc)

    if _last_fetch_success is not None and now - _last_fetch_success < _REFRESH_INTERVAL:
        return
    if _last_fetch_attempt is not None and now - _last_fetch_attempt < _RETRY_BACKOFF:
        return

    _last_fetch_attempt = now
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(_FX_API_URL)
            resp.raise_for_status()
            data = resp.json()

        if data.get("result") != "success":
            raise ValueError(f"FX API returned non-success result: {data.get('result')!r}")

        usd_rates = data["rates"]
        inr_per_usd = usd_rates["INR"]
        _cached_rates = {
            code: round(inr_per_usd / rate, 6)
            for code, rate in usd_rates.items()
            if rate
        }
        _last_fetch_success = now
        logger.info(
            f"FX rates refreshed from {_FX_API_URL}: 1 USD = {_cached_rates['USD']:.4f} INR"
        )
    except Exception as e:
        if _cached_rates is not None:
            logger.warning(
                f"FX rate refresh failed ({e}); continuing with the last successfully "
                f"fetched rate from {_last_fetch_success.isoformat() if _last_fetch_success else 'unknown'}"
            )
        else:
            logger.warning(
                f"FX rate refresh failed ({e}) and no rate has ever been fetched "
                f"successfully - falling back to hardcoded safety-net rates "
                f"(USD->INR = {_FALLBACK_RATES_TO_INR['USD']}). DEGRADED MODE."
            )


def _headers() -> Dict[str, str]:
    return {
        "X-Api-Key": IGNAV_API_KEY,
        "Content-Type": "application/json",
    }


def _to_inr(amount: float, currency: str) -> float:
    currency = currency.upper()
    rates = _cached_rates if _cached_rates is not None else _FALLBACK_RATES_TO_INR
    rate = rates.get(currency, rates.get('USD', 83.0))
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

    await _refresh_rates_if_stale()

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
        sentry_sdk.capture_exception(e, tags={"provider": "ignav"})
        return []
    except Exception as e:
        logger.error(f"Ignav error: {e}")
        sentry_sdk.capture_exception(e, tags={"provider": "ignav"})
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
