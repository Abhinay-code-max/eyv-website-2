"""Search & Locations API router (/api/search/*, /api/destinations/*, /api/locations/*).
"""
import logging
import random
from typing import Optional
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from routes.shared import db, limiter, get_current_user
from services import (
    ignav_service as duffel_service,
    amadeus_service,
    serpapi_hotels_service,
    price_cache_service,
    locations_service,
    usage_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["search", "locations"])


class FlightSearchRequest(BaseModel):
    origin: str
    destination: str
    departure_date: str
    return_date: Optional[str] = None
    travelers: int = 1


class HotelSearchRequest(BaseModel):
    destination: str
    check_in: str
    check_out: str
    travelers: int = 1


class TrainSearchRequest(BaseModel):
    origin: str
    destination: str
    departure_date: str
    travelers: int = 1


@router.post("/search/flights")
async def search_flights_endpoint(req: FlightSearchRequest, request: Request):
    user = await get_current_user(request)
    # Try Duffel (real data) first, fall back to mock
    flights = await duffel_service.search_flights(
        req.origin, req.destination, req.departure_date, req.return_date, req.travelers
    )
    await usage_service.log_usage(db, "duffel", user_id=user.user_id, meta={"context": "search_flights_endpoint"})
    provider = "ignav"
    if not flights:
        logger.warning("Duffel returned no flights, falling back to mock data")
        flights = amadeus_service._generate_mock_flights(
            req.origin, req.destination, req.departure_date,
            req.return_date or req.departure_date, req.travelers
        )
        provider = "mock"
    # Sort: cheapest first
    flights = sorted(flights, key=lambda f: f["price"]["total"])
    # Cache the authoritative price per result and stamp an item_id - the
    # client only ever gets to reference that id back, never the price itself.
    await price_cache_service.cache_search_results(
        db, flights, "flight", provider,
        {
            "origin": req.origin, "destination": req.destination,
            "departure_date": req.departure_date, "return_date": req.return_date,
            "travelers": req.travelers,
        },
    )
    return {"flights": flights, "count": len(flights)}


@router.post("/search/trains")
async def search_trains_endpoint(req: TrainSearchRequest, request: Request):
    await get_current_user(request)
    # Live train API not yet integrated. Return empty list with honest message.
    # Frontend should show "Train data unavailable for this route" when count == 0.
    return {
        "trains": [],
        "count": 0,
        "message": "Live train data is not available for this route. Please check IRCTC or Rome2rio for train options."
    }


@router.post("/search/hotels")
async def search_hotels_endpoint(req: HotelSearchRequest, request: Request):
    user = await get_current_user(request)
    # Try SerpApi (real data) first, fall back to mock
    hotels = await serpapi_hotels_service.search_hotels(
        req.destination, req.check_in, req.check_out, req.travelers, currency="INR"
    )
    await usage_service.log_usage(db, "serpapi", user_id=user.user_id, meta={"context": "search_hotels_endpoint"})
    provider = "serpapi"
    if not hotels:
        logger.warning("SerpApi returned no hotels, falling back to mock data")
        hotels = amadeus_service._generate_mock_hotels(
            req.destination, req.check_in, req.check_out, req.travelers
        )
        provider = "mock"
    # Enforce tier ordering: always sort by price ascending
    hotels = sorted(hotels, key=lambda h: h["price"]["per_night"])
    # Cache the authoritative price per result and stamp an item_id - the
    # client only ever gets to reference that id back, never the price itself.
    await price_cache_service.cache_search_results(
        db, hotels, "hotel", provider,
        {
            "destination": req.destination, "check_in": req.check_in,
            "check_out": req.check_out, "travelers": req.travelers,
        },
    )
    return {"hotels": hotels, "count": len(hotels)}


@router.get("/destinations/{destination}/coords")
async def get_destination_coords_endpoint(destination: str, request: Request):
    await get_current_user(request)
    coords = await locations_service.geocode_destination(destination)
    if coords:
        return {**coords, "geocoded": True}
    coords = amadeus_service.get_destination_coords(destination)
    if coords:
        return {**coords, "geocoded": False}
    # Final fallback for single-destination overview map pin:
    # return an approximate random point flagged with geocoded: False so the
    # frontend displays an "uncertain location" warning to the user.
    coords = {'lat': round(random.uniform(10, 50), 4), 'lng': round(random.uniform(-100, 100), 4)}
    return {**coords, "geocoded": False}



@router.get("/locations/venue-coords")
async def get_venue_coords_endpoint(request: Request, name: str, city: str = ""):
    """Geocode a named venue (hotel/restaurant/landmark) - NOT the same as
    /destinations/{destination}/coords above, which is city-level only and
    would short-circuit "venue, city"-style queries straight to the city's
    curated centroid (see geocode_venue's docstring). Used by the Road Trip
    map's per-day hotel waypoint markers (TripResultsPage.jsx)."""
    await get_current_user(request)
    coords = await locations_service.geocode_venue(name, city)
    if not coords:
        coords = amadeus_service.get_destination_coords(city or name)
    return coords


@router.get("/locations/autocomplete")
@limiter.limit("25/minute")  # per-IP - generous enough for live typeahead, still bounded
async def locations_autocomplete(request: Request, q: str = Query("", min_length=0)):
    """Autocomplete location suggestions. Returns popular destinations matching query.
    Public endpoint - used on landing page as well."""
    suggestions = locations_service.search_locations(q, limit=8)
    return {"suggestions": suggestions}


@router.get("/locations/reverse-geocode")
@limiter.limit("10/minute")  # per-IP - lower than autocomplete; only called once per geolocation request
async def reverse_geocode_endpoint(request: Request, lat: float = Query(...), lng: float = Query(...)):
    """Reverse-geocode a lat/lng to a human-readable city/country name.
    Used by the 'Use my current location' feature in TripPlannerPage to convert
    browser Geolocation API coordinates into a Starting Location display name.
    Requires authentication (same as all other location endpoints)."""
    await get_current_user(request)
    result = await locations_service.reverse_geocode(lat, lng)
    if not result:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Could not resolve location from coordinates")
    return result
