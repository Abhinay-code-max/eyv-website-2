"""
Shared trip date-range math - currently just trip_nights, the single source
of truth for "how many nights does this trip have" used by both itinerary
generation (server.py's generate_single_plan) and hotel-search pricing
(serpapi_hotels_service.py, amadeus_service.py). Before this existed, the
two sides computed this independently and had drifted apart: itinerary
generation charged return_date as its own extra paid day (nights + 1),
while hotel search never did (plain nights, no +1) - same trip, two
different accommodation totals depending on which code path priced it.
Both now call the one function below so they can't silently re-diverge.
"""
from datetime import datetime


def trip_nights(departure_date: str, return_date: str) -> int:
    """Nights of accommodation for a departure/return date pair (ISO
    "YYYY-MM-DD" strings) - one night per day of the stay, NOT counting the
    return date itself: the traveler checks out and travels home that
    morning, not stays another night. Floored at 1 so a same-day or
    malformed (return before departure) date pair still produces a sane
    one-night trip rather than an empty or negative one.

    Raises ValueError for a date string that isn't valid ISO format -
    callers that need to tolerate bad input (e.g. serpapi_hotels_service's
    "fall back to a 3-night estimate" path) catch that themselves rather
    than this function silently guessing a default.
    """
    return max((datetime.fromisoformat(return_date) - datetime.fromisoformat(departure_date)).days, 1)
