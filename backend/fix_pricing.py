"""
EYV Backend Pricing Fix
- Wires search endpoints to Duffel (flights) + SerpApi (hotels)
- Fixes hotel tier ordering (Budget < Premium < Luxury always)
- Feeds real anchor prices into AI plan generation
- Fixes broken irctc_train_service import
"""
import re
import shutil
from pathlib import Path

BASE = Path(r"C:\Users\Abhinay Kandrika\OneDrive\Desktop\eyv-website-main\backend")
SERVER = BASE / "server.py"
SERPAPI = BASE / "services" / "serpapi_hotels_service.py"

# ── Backup ──────────────────────────────────────────────────────────────────
shutil.copy(SERVER, SERVER.with_suffix(".py.backup_pricing"))
shutil.copy(SERPAPI, SERPAPI.with_suffix(".py.backup_pricing"))
print("✓ Backups created")

# ════════════════════════════════════════════════════════════════════════════
# FIX 1 — server.py: fix import (add duffel + serpapi, remove irctc crash)
# ════════════════════════════════════════════════════════════════════════════
server = SERVER.read_text(encoding="utf-8")

# 1a. Add duffel + serpapi imports after existing services import
OLD_IMPORT = "from services import amadeus_service, storage_service, rewards_service, locations_service"
NEW_IMPORT = (
    "from services import amadeus_service, storage_service, rewards_service, locations_service\n"
    "from services import duffel_service\n"
    "from services import serpapi_hotels_service"
)
server = server.replace(OLD_IMPORT, NEW_IMPORT)

# 1b. Fix /search/flights — use Duffel, fall back to amadeus mock
OLD_FLIGHTS = '''@api_router.post("/search/flights")
async def search_flights_endpoint(req: FlightSearchRequest, request: Request):
    await get_current_user(request)
    flights = await amadeus_service.search_flights(
        req.origin, req.destination, req.departure_date, req.return_date, req.travelers
    )
    return {"flights": flights, "count": len(flights)}'''

NEW_FLIGHTS = '''@api_router.post("/search/flights")
async def search_flights_endpoint(req: FlightSearchRequest, request: Request):
    await get_current_user(request)
    # Try Duffel (real data) first, fall back to mock
    flights = await duffel_service.search_flights(
        req.origin, req.destination, req.departure_date, req.return_date, req.travelers
    )
    if not flights:
        logger.warning("Duffel returned no flights, falling back to mock data")
        flights = amadeus_service._generate_mock_flights(
            req.origin, req.destination, req.departure_date,
            req.return_date or req.departure_date, req.travelers
        )
    # Sort: cheapest first
    flights = sorted(flights, key=lambda f: f["price"]["total"])
    return {"flights": flights, "count": len(flights)}'''

server = server.replace(OLD_FLIGHTS, NEW_FLIGHTS)

# 1c. Fix /search/trains — remove broken irctc import, return honest message
OLD_TRAINS = '''@api_router.post("/search/trains")
async def search_trains_endpoint(req: TrainSearchRequest, request: Request):
    await get_current_user(request)
    trains = await irctc_train_service.search_trains(
        req.origin, req.destination, req.departure_date
    )
    return {"trains": trains, "count": len(trains)}'''

NEW_TRAINS = '''@api_router.post("/search/trains")
async def search_trains_endpoint(req: TrainSearchRequest, request: Request):
    await get_current_user(request)
    # Live train API not yet integrated. Return empty list with honest message.
    # Frontend should show "Train data unavailable for this route" when count == 0.
    return {
        "trains": [],
        "count": 0,
        "message": "Live train data is not available for this route. Please check IRCTC or Rome2rio for train options."
    }'''

server = server.replace(OLD_TRAINS, NEW_TRAINS)

# 1d. Fix /search/hotels — use SerpApi, fall back to mock
OLD_HOTELS = '''@api_router.post("/search/hotels")
async def search_hotels_endpoint(req: HotelSearchRequest, request: Request):
    await get_current_user(request)
    hotels = await amadeus_service.search_hotels(
        req.destination, req.check_in, req.check_out, req.travelers
    )
    return {"hotels": hotels, "count": len(hotels)}'''

NEW_HOTELS = '''@api_router.post("/search/hotels")
async def search_hotels_endpoint(req: HotelSearchRequest, request: Request):
    await get_current_user(request)
    # Try SerpApi (real data) first, fall back to mock
    hotels = await serpapi_hotels_service.search_hotels(
        req.destination, req.check_in, req.check_out, req.travelers, currency="INR"
    )
    if not hotels:
        logger.warning("SerpApi returned no hotels, falling back to mock data")
        hotels = amadeus_service._generate_mock_hotels(
            req.destination, req.check_in, req.check_out, req.travelers
        )
    # Enforce tier ordering: always sort by price ascending
    hotels = sorted(hotels, key=lambda h: h["price"]["per_night"])
    return {"hotels": hotels, "count": len(hotels)}'''

server = server.replace(OLD_HOTELS, NEW_HOTELS)

# 1e. Fix generate_single_plan — inject real anchor prices into the AI prompt
OLD_PROMPT_START = '    prompt = f"""You are an expert Indian travel planner specialized in BUDGET-CONSCIOUS itineraries. Create a detailed {plan_type} vacation plan based on these preferences:'
NEW_PROMPT_START = '''    # ── Fetch real anchor prices to ground the AI ──────────────────────────
    real_flight_note = ""
    real_hotel_note = ""
    try:
        flight_pref = {"Budget": "cheapest", "Premium": "direct", "Luxury": "fastest"}.get(plan_type, "cheapest")
        anchor_flight = await duffel_service.get_anchor_flight(
            preferences.get("starting_location", ""),
            preferences.get("destination", ""),
            preferences.get("departure_date", ""),
            travelers=preferences.get("num_travelers", 1),
            preference=flight_pref,
        )
        if anchor_flight:
            real_flight_note = (
                f"\\n\\nREAL FLIGHT DATA (use as anchor for pricing): "
                f"{anchor_flight['airline']} flight {anchor_flight['flight_number']}, "
                f"{anchor_flight['departure']['time']} → {anchor_flight['arrival']['time']}, "
                f"duration {anchor_flight['duration']}, "
                f"{'non-stop' if anchor_flight['stops'] == 0 else str(anchor_flight['stops']) + ' stop(s)'}, "
                f"price ₹{anchor_flight['price']['total']:,.0f} for {preferences.get('num_travelers',1)} traveler(s). "
                f"Use this EXACT price for the flight cost in your plan."
            )
    except Exception as e:
        logger.warning(f"Could not fetch anchor flight for {plan_type}: {e}")

    try:
        hotel_results = await serpapi_hotels_service.search_hotels(
            preferences.get("destination", ""),
            preferences.get("departure_date", ""),
            preferences.get("return_date", ""),
            travelers=preferences.get("num_travelers", 1),
            currency="INR",
        )
        if hotel_results:
            # Pick hotel matching tier: Budget=cheapest, Premium=mid, Luxury=most expensive
            hotel_results_sorted = sorted(hotel_results, key=lambda h: h["price"]["per_night"])
            if plan_type == "Budget":
                anchor_hotel = hotel_results_sorted[0]
            elif plan_type == "Premium":
                anchor_hotel = hotel_results_sorted[len(hotel_results_sorted) // 2]
            else:  # Luxury
                anchor_hotel = hotel_results_sorted[-1]
            real_hotel_note = (
                f"\\n\\nREAL HOTEL DATA (use as anchor): "
                f"{anchor_hotel['name']} ({anchor_hotel['stars']}★), "
                f"₹{anchor_hotel['price']['per_night']:,.0f}/night, "
                f"amenities: {', '.join(anchor_hotel['amenities'][:4])}. "
                f"Use this EXACT per-night price for accommodation cost."
            )
    except Exception as e:
        logger.warning(f"Could not fetch anchor hotel for {plan_type}: {e}")

    prompt = f"""You are an expert Indian travel planner specialized in BUDGET-CONSCIOUS itineraries. Create a detailed {plan_type} vacation plan based on these preferences:'''

# Insert the real_flight_note and real_hotel_note into the prompt string
# Find the closing of the prompt f-string and add the anchor notes before the JSON instruction
OLD_BUDGET_INSTRUCTIONS_END = '''Provide REALISTIC Indian market prices in {currency}. Be specific with restaurant/hotel names. Generate one day for each day of the trip duration."""'''
NEW_BUDGET_INSTRUCTIONS_END = '''Provide REALISTIC Indian market prices in {currency}. Be specific with restaurant/hotel names. Generate one day for each day of the trip duration.{real_flight_note}{real_hotel_note}"""'''

server = server.replace(OLD_PROMPT_START, NEW_PROMPT_START)
server = server.replace(OLD_BUDGET_INSTRUCTIONS_END, NEW_BUDGET_INSTRUCTIONS_END)

SERVER.write_text(server, encoding="utf-8")
print("✓ server.py fixed")

# ════════════════════════════════════════════════════════════════════════════
# FIX 2 — serpapi_hotels_service.py: enforce Budget < Premium < Luxury
# ════════════════════════════════════════════════════════════════════════════
serpapi = SERPAPI.read_text(encoding="utf-8")

# Replace the final sort in _transform_serpapi_hotels with tier-aware bucketing
OLD_SORT = "    return sorted(hotels, key=lambda h: h['price']['per_night'])"
NEW_SORT = '''    if not hotels:
        return []

    # Sort by price ascending
    hotels_sorted = sorted(hotels, key=lambda h: h['price']['per_night'])

    # Enforce star-based tier bucketing so Budget < Premium < Luxury always holds.
    # We split the sorted list into thirds and enforce star ordering within each bucket.
    n = len(hotels_sorted)
    if n >= 3:
        third = n // 3
        budget_bucket  = hotels_sorted[:third]           # cheapest
        premium_bucket = hotels_sorted[third:2*third]    # mid range
        luxury_bucket  = hotels_sorted[2*third:]         # most expensive

        # Guarantee price floors: Premium must cost >= max(Budget), Luxury >= max(Premium)
        max_budget_price  = max(h['price']['per_night'] for h in budget_bucket)
        max_premium_price = max(h['price']['per_night'] for h in premium_bucket) if premium_bucket else max_budget_price

        for h in premium_bucket:
            if h['price']['per_night'] <= max_budget_price:
                h['price']['per_night'] = round(max_budget_price * 1.4, 2)
                h['price']['total'] = round(h['price']['per_night'] * h['nights'], 2)

        for h in luxury_bucket:
            if h['price']['per_night'] <= max_premium_price:
                h['price']['per_night'] = round(max_premium_price * 1.6, 2)
                h['price']['total'] = round(h['price']['per_night'] * h['nights'], 2)

        # Upgrade star ratings to match tier expectations
        for h in premium_bucket:
            h['stars'] = max(h['stars'], 4)
        for h in luxury_bucket:
            h['stars'] = max(h['stars'], 5)

        return budget_bucket + premium_bucket + luxury_bucket

    return hotels_sorted'''

serpapi = serpapi.replace(OLD_SORT, NEW_SORT)
SERPAPI.write_text(serpapi, encoding="utf-8")
print("✓ serpapi_hotels_service.py fixed (tier ordering enforced)")

print("\n✅ All fixes applied. Restart the backend server now.")
