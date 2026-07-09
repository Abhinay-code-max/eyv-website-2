"""
Complete rewrite of generate_single_plan with a much stronger LLM prompt.
Replaces the entire function in server.py.
"""
import shutil
from pathlib import Path

SERVER = Path(r"C:\Users\Abhinay Kandrika\OneDrive\Desktop\eyv-website-main\backend\server.py")
shutil.copy(SERVER, SERVER.with_suffix(".py.backup_rewrite"))

server = SERVER.read_text(encoding="utf-8")

# Find the start and end of generate_single_plan
START_MARKER = "async def generate_single_plan(preferences: Dict, plan_type: str, trip_id: str, user_id: str) -> Dict:"
END_MARKER = "@api_router.get(\"/trips\")"

start_idx = server.find(START_MARKER)
end_idx = server.find(END_MARKER)

if start_idx == -1 or end_idx == -1:
    print(f"❌ Could not find markers. start={start_idx}, end={end_idx}")
    exit()

NEW_FUNCTION = '''async def generate_single_plan(preferences: Dict, plan_type: str, trip_id: str, user_id: str) -> Dict:
    """Generate a single vacation plan using AI with real price anchoring."""
    import json

    currency = preferences.get('currency', 'INR')
    currency_symbol = '₹' if currency == 'INR' else '$'
    num_travelers = preferences.get('num_travelers', 1)

    # ── Step 1: Fetch real anchor prices ────────────────────────────────────
    flight_price = 0
    flight_airline = ""
    flight_number = ""
    flight_dep_time = ""
    flight_arr_time = ""
    flight_duration = ""
    flight_stops = 0

    hotel_name = ""
    hotel_price_per_night = 0
    hotel_stars = 0

    try:
        flight_pref = {"Budget": "cheapest", "Premium": "direct", "Luxury": "fastest"}.get(plan_type, "cheapest")
        af = await duffel_service.get_anchor_flight(
            preferences.get("starting_location", ""),
            preferences.get("destination", ""),
            preferences.get("departure_date", ""),
            travelers=num_travelers,
            preference=flight_pref,
        )
        if af:
            flight_price    = af['price']['total']
            flight_airline  = af['airline']
            flight_number   = af['flight_number']
            flight_dep_time = af['departure']['time']
            flight_arr_time = af['arrival']['time']
            flight_duration = af['duration']
            flight_stops    = af['stops']
            logger.info(f"{plan_type}: anchor flight = {flight_airline} {flight_number} ₹{flight_price:,.0f}")
    except Exception as e:
        logger.warning(f"Anchor flight fetch failed for {plan_type}: {e}")

    try:
        hotel_results = await serpapi_hotels_service.search_hotels(
            preferences.get("destination", ""),
            preferences.get("departure_date", ""),
            preferences.get("return_date", ""),
            travelers=num_travelers,
            currency="INR",
        )
        if hotel_results:
            sorted_hotels = sorted(hotel_results, key=lambda h: h["price"]["per_night"])
            if plan_type == "Budget":
                ah = sorted_hotels[0]
            elif plan_type == "Premium":
                ah = sorted_hotels[len(sorted_hotels) // 2]
            else:
                ah = sorted_hotels[-1]
            hotel_name           = ah['name']
            hotel_price_per_night = ah['price']['per_night']
            hotel_stars          = ah['stars']
            logger.info(f"{plan_type}: anchor hotel = {hotel_name} ₹{hotel_price_per_night:,.0f}/night")
    except Exception as e:
        logger.warning(f"Anchor hotel fetch failed for {plan_type}: {e}")

    # ── Step 2: Build tier-specific instructions ─────────────────────────────
    tier_rules = {
        "Budget": f"""
- Cheapest available options throughout
- Hotel: {hotel_name or 'budget guesthouse'} at EXACTLY ₹{hotel_price_per_night:,.0f}/night (use this hotel name and price)
- Public transport (metro, bus, shared rides)
- Street food and casual dining (₹150-400/meal)
- Free or low-cost attractions
- TOTAL trip cost must be the LOWEST of the three tiers
""",
        "Premium": f"""
- Mid-range comfortable options
- Hotel: {hotel_name or '4-star hotel'} at EXACTLY ₹{hotel_price_per_night:,.0f}/night (use this hotel name and price)
- Mix of metro and private transport
- Good restaurants (₹500-1200/meal)
- Mix of free and paid attractions
- TOTAL trip cost must be BETWEEN Budget and Luxury tiers
""",
        "Luxury": f"""
- Premium luxury options only
- Hotel: {hotel_name or '5-star luxury hotel'} at EXACTLY ₹{hotel_price_per_night:,.0f}/night (use this hotel name and price)
- Private transfers and premium vehicles only
- Fine dining at signature restaurants (₹1500+/meal)
- Exclusive experiences, private tours, VIP access
- TOTAL trip cost must be the HIGHEST of the three tiers
"""
    }

    # ── Step 3: Build the prompt with constraints at the TOP ─────────────────
    flight_constraint = f"""FLIGHT (DO NOT CHANGE THESE VALUES):
  Airline: {flight_airline}
  Flight Number: {flight_number}
  Departure: {flight_dep_time}
  Arrival: {flight_arr_time}
  Duration: {flight_duration}
  Stops: {'Non-stop' if flight_stops == 0 else f'{flight_stops} stop(s)'}
  PRICE: ₹{flight_price:,.0f} (USE THIS EXACT NUMBER — do not round, inflate, or change)""" if flight_price > 0 else "Use realistic market flight prices."

    hotel_constraint = f"""HOTEL (DO NOT CHANGE THESE VALUES):
  Name: {hotel_name}
  Stars: {hotel_stars}★
  PRICE PER NIGHT: ₹{hotel_price_per_night:,.0f} (USE THIS EXACT NUMBER)""" if hotel_price_per_night > 0 else "Use realistic market hotel prices."

    prompt = f"""You are a travel pricing engine. Generate a {plan_type} trip plan as valid JSON only.

╔══════════════════════════════════════════════════════╗
║  MANDATORY CONSTRAINTS — VIOLATION = INVALID OUTPUT  ║
╠══════════════════════════════════════════════════════╣
║ {flight_constraint}
║
║ {hotel_constraint}
║
║ TIER RULE: {plan_type} plan total must be
║ {'the LOWEST cost of all three tiers' if plan_type == 'Budget' else 'BETWEEN Budget and Luxury costs' if plan_type == 'Premium' else 'the HIGHEST cost of all three tiers'}
╚══════════════════════════════════════════════════════╝

TRIP DETAILS:
- Destination: {preferences['destination']}
- From: {preferences['starting_location']}
- Dates: {preferences['departure_date']} to {preferences['return_date']}
- Travelers: {num_travelers}
- Tier: {plan_type}
- Currency: {currency}

TIER GUIDELINES:
{tier_rules[plan_type]}

OUTPUT: Return ONLY valid JSON, no markdown, no explanation:
{{
  "plan_type": "{plan_type}",
  "currency": "{currency}",
  "currency_symbol": "{currency_symbol}",
  "itinerary": {{
    "day_1": {{
      "date": "{preferences['departure_date']}",
      "transportation": {{"mode": "flight", "details": "{flight_airline} {flight_number} {preferences.get('starting_location','')} to {preferences['destination']}", "cost": {flight_price if flight_price > 0 else 15000}}},
      "activities": [{{"time": "14:00", "activity": "Check-in and explore", "location": "Hotel", "cost": 0, "category": "free"}}],
      "accommodation": {{"name": "{hotel_name or 'Hotel'}", "type": "hotel", "cost": {hotel_price_per_night if hotel_price_per_night > 0 else 5000}, "location": "{preferences['destination']}"}},
      "meals": [{{"time": "dinner", "restaurant": "Local restaurant", "cuisine": "Local", "cost": 500}}],
      "daily_total": {int(flight_price + hotel_price_per_night + 500) if flight_price and hotel_price_per_night else 20000},
      "cumulative_total": {int(flight_price + hotel_price_per_night + 500) if flight_price and hotel_price_per_night else 20000},
      "fixed_costs": {int(flight_price + hotel_price_per_night) if flight_price and hotel_price_per_night else 18000},
      "variable_costs": 500
    }}
  }},
  "cost_breakdown": {{
    "transportation": {flight_price if flight_price > 0 else 15000},
    "accommodation": 0,
    "food": 0,
    "activities": 0,
    "miscellaneous": 0
  }},
  "total_cost": 0,
  "highlights": ["highlight 1", "highlight 2", "highlight 3"],
  "budget_tips": ["tip 1", "tip 2", "tip 3"]
}}

Fill in ALL days from {preferences['departure_date']} to {preferences['return_date']}.
Use EXACT prices from constraints above — especially ₹{flight_price:,.0f} for flight and ₹{hotel_price_per_night:,.0f}/night for hotel.
Generate realistic activities, meals, and local transport for each day."""

    # ── Step 4: Call LLM ─────────────────────────────────────────────────────
    try:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"{trip_id}_{plan_type}",
            system_message=(
                f"You are a travel cost calculator that outputs ONLY valid JSON. "
                f"You ALWAYS use the exact prices provided in the MANDATORY CONSTRAINTS section. "
                f"Flight cost MUST be ₹{flight_price:,.0f}. "
                f"Hotel cost MUST be ₹{hotel_price_per_night:,.0f}/night. "
                f"Never invent or change these numbers."
            )
        ).with_model("openai", "gpt-4o")

        full_response = ""
        async for event in chat.stream_message(UserMessage(text=prompt)):
            if isinstance(event, TextDelta):
                full_response += event.content
            elif isinstance(event, StreamDone):
                break

        # Parse JSON
        start_i = full_response.find('{')
        end_i   = full_response.rfind('}') + 1
        if start_i != -1 and end_i > start_i:
            plan_data = json.loads(full_response[start_i:end_i])
        else:
            raise ValueError("No JSON found in response")

        # ── Step 5: Post-process — enforce exact prices regardless of AI output
        if flight_price > 0:
            if 'cost_breakdown' in plan_data:
                plan_data['cost_breakdown']['transportation'] = flight_price

            itinerary = plan_data.get('itinerary', {})
            days = sorted(itinerary.keys())

            if days:
                # Day 1: outbound flight
                d1 = itinerary[days[0]]
                if 'transportation' in d1:
                    d1['transportation']['cost'] = flight_price
                    d1['transportation']['details'] = f"{flight_airline} {flight_number} - {d1['transportation'].get('details', '')}"
                for act in d1.get('activities', []):
                    if 'flight' in act.get('activity', '').lower() or 'depart' in act.get('activity', '').lower():
                        act['cost'] = flight_price

                # Last day: return flight if applicable
                if len(days) > 1:
                    dl = itinerary[days[-1]]
                    if 'transportation' in dl:
                        mode = dl['transportation'].get('mode', '').lower()
                        details = dl['transportation'].get('details', '').lower()
                        if 'flight' in mode or 'flight' in details or 'return' in details:
                            dl['transportation']['cost'] = flight_price

        if hotel_price_per_night > 0:
            itinerary = plan_data.get('itinerary', {})
            for day_key, day_data in itinerary.items():
                if 'accommodation' in day_data and day_data['accommodation'].get('cost', 0) > 0:
                    day_data['accommodation']['cost'] = hotel_price_per_night
                    day_data['accommodation']['name'] = hotel_name or day_data['accommodation'].get('name', 'Hotel')

        # Recalculate total
        if 'cost_breakdown' in plan_data:
            plan_data['total_cost'] = sum(plan_data['cost_breakdown'].values())

        plan_data.setdefault('currency', currency)
        plan_data.setdefault('currency_symbol', currency_symbol)
        return plan_data

    except Exception as e:
        logger.error(f"Error generating {plan_type} plan: {e}")
        return {
            "plan_type": plan_type,
            "currency": currency,
            "currency_symbol": currency_symbol,
            "itinerary": {},
            "cost_breakdown": {"transportation": 0, "accommodation": 0, "food": 0, "activities": 0, "miscellaneous": 0},
            "total_cost": 0,
            "highlights": [],
            "budget_tips": [],
            "error": str(e)
        }

'''

# Replace the old function
server = server[:start_idx] + NEW_FUNCTION + "\n" + server[end_idx:]
SERVER.write_text(server, encoding="utf-8")
print("✓ generate_single_plan completely rewritten")
print("  - Real prices fetched FIRST, stored in simple variables")
print("  - Constraints block at TOP of prompt with box drawing")
print("  - System message repeats exact prices")
print("  - Post-processing enforces prices after JSON parsed")
print("\n✅ Done! Restart the server and plan a new trip.")
