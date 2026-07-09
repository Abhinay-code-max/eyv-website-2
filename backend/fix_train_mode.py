import re

with open(r"C:\Users\Abhinay Kandrika\OneDrive\Desktop\eyv-website-main\backend\server.py", 'r', encoding='utf-8') as f:
    content = f.read()

# ── PATCH 1: After flight vars are declared, add train logic ──────────────────
# Find the block that starts fetch anchor prices and inject transport detection

OLD_STEP1 = '''    # ── Step 1: Fetch real anchor prices ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
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
        logger.warning(f"Anchor flight fetch failed for {plan_type}: {e}")'''

NEW_STEP1 = '''    # ── Step 1: Fetch real anchor prices ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
    transport_mode = preferences.get("transportation", "flight").lower()
    is_train = "train" in transport_mode

    flight_price = 0
    flight_airline = ""
    flight_number = ""
    flight_dep_time = ""
    flight_arr_time = ""
    flight_duration = ""
    flight_stops = 0

    train_price = 0
    train_name = ""
    train_number = ""
    train_class = ""
    train_duration = ""

    hotel_name = ""
    hotel_price_per_night = 0
    hotel_stars = 0

    if is_train:
        # Estimated train prices by tier (INR, realistic Indian rail fares)
        train_tier_prices = {
            "Budget":  {"price": 450,  "class": "Sleeper (SL)",       "name": "Express Train"},
            "Premium": {"price": 1200, "class": "AC 3-Tier (3A)",     "name": "Superfast Express"},
            "Luxury":  {"price": 2800, "class": "AC 1st Class (1A)",  "name": "Rajdhani / Shatabdi"},
        }
        t = train_tier_prices.get(plan_type, train_tier_prices["Budget"])
        train_price    = t["price"] * num_travelers
        train_class    = t["class"]
        train_name     = t["name"]
        train_number   = "Train"
        train_duration = "Varies by route"
        logger.info(f"{plan_type}: estimated train = {train_name} {train_class} ₹{train_price:,.0f}")
    else:
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
            logger.warning(f"Anchor flight fetch failed for {plan_type}: {e}")'''

if OLD_STEP1 in content:
    content = content.replace(OLD_STEP1, NEW_STEP1)
    print("PATCH 1 applied: transport mode detection + train pricing")
else:
    print("PATCH 1 FAILED: could not find Step 1 block")

# ── PATCH 2: Update flight_constraint to handle train too ────────────────────
OLD_CONSTRAINT = '''    flight_constraint = f"""FLIGHT (DO NOT CHANGE THESE VALUES):
  Airline: {flight_airline}
  Flight Number: {flight_number}
  Departure: {flight_dep_time}
  Arrival: {flight_arr_time}
  Duration: {flight_duration}
  Stops: {'Non-stop' if flight_stops == 0 else f'{flight_stops} stop(s)'}
  PRICE: ₹{flight_price:,.0f} (USE THIS EXACT NUMBER — do not round, inflate, or change)""" if flight_price > 0 else "Use realistic market flight prices."'''

NEW_CONSTRAINT = '''    if is_train:
        flight_constraint = f"""TRAIN (DO NOT CHANGE THESE VALUES):
  Train Name: {train_name}
  Class: {train_class}
  Duration: {train_duration}
  PRICE: ₹{train_price:,.0f} total for {num_travelers} traveler(s) (USE THIS EXACT NUMBER)""" if train_price > 0 else "Use realistic Indian train prices."
    else:
        flight_constraint = f"""FLIGHT (DO NOT CHANGE THESE VALUES):
  Airline: {flight_airline}
  Flight Number: {flight_number}
  Departure: {flight_dep_time}
  Arrival: {flight_arr_time}
  Duration: {flight_duration}
  Stops: {'Non-stop' if flight_stops == 0 else f'{flight_stops} stop(s)'}
  PRICE: ₹{flight_price:,.0f} (USE THIS EXACT NUMBER — do not round, inflate, or change)""" if flight_price > 0 else "Use realistic market flight prices."'''

if OLD_CONSTRAINT in content:
    content = content.replace(OLD_CONSTRAINT, NEW_CONSTRAINT)
    print("PATCH 2 applied: constraint block updated for train/flight")
else:
    print("PATCH 2 FAILED: could not find flight_constraint block")

# ── PATCH 3: Fix the hardcoded "mode": "flight" in the prompt ────────────────
OLD_PROMPT_TRANSPORT = '''      "transportation": {{"mode": "flight", "details": "{flight_airline} {flight_number} {preferences.get('starting_location','')} to {preferences['destination']}", "cost": {flight_price if flight_price > 0 else 15000}}},'''

NEW_PROMPT_TRANSPORT = '''      "transportation": {{"mode": "{'train' if is_train else 'flight'}", "details": "{train_name + ' ' + train_class + ' ' if is_train else flight_airline + ' ' + flight_number + ' '}{preferences.get('starting_location','')} to {preferences['destination']}", "cost": {train_price if is_train and train_price > 0 else (flight_price if flight_price > 0 else 15000)}}},'''

if OLD_PROMPT_TRANSPORT in content:
    content = content.replace(OLD_PROMPT_TRANSPORT, NEW_PROMPT_TRANSPORT)
    print("PATCH 3 applied: prompt mode fixed")
else:
    print("PATCH 3 FAILED: could not find prompt transport line")

# ── PATCH 4: Fix cost_breakdown transportation default in prompt ──────────────
OLD_COST_BREAKDOWN = '''    "transportation": {flight_price if flight_price > 0 else 15000},'''
NEW_COST_BREAKDOWN = '''    "transportation": {train_price if is_train and train_price > 0 else (flight_price if flight_price > 0 else 15000)},'''

if OLD_COST_BREAKDOWN in content:
    content = content.replace(OLD_COST_BREAKDOWN, NEW_COST_BREAKDOWN)
    print("PATCH 4 applied: cost_breakdown transportation fixed")
else:
    print("PATCH 4 FAILED")

# ── PATCH 5: Fix the daily_total calculation ─────────────────────────────────
OLD_DAILY_TOTAL = '''      "daily_total": {int(flight_price + hotel_price_per_night + 500) if flight_price and hotel_price_per_night else 20000},
      "cumulative_total": {int(flight_price + hotel_price_per_night + 500) if flight_price and hotel_price_per_night else 20000},
      "fixed_costs": {int(flight_price + hotel_price_per_night) if flight_price and hotel_price_per_night else 18000},'''

NEW_DAILY_TOTAL = '''      "daily_total": {int((train_price if is_train else flight_price) + hotel_price_per_night + 500) if (train_price if is_train else flight_price) and hotel_price_per_night else 20000},
      "cumulative_total": {int((train_price if is_train else flight_price) + hotel_price_per_night + 500) if (train_price if is_train else flight_price) and hotel_price_per_night else 20000},
      "fixed_costs": {int((train_price if is_train else flight_price) + hotel_price_per_night) if (train_price if is_train else flight_price) and hotel_price_per_night else 18000},'''

if OLD_DAILY_TOTAL in content:
    content = content.replace(OLD_DAILY_TOTAL, NEW_DAILY_TOTAL)
    print("PATCH 5 applied: daily_total uses train price when applicable")
else:
    print("PATCH 5 FAILED")

# ── PATCH 6: Update the price hint line at bottom of prompt ──────────────────
OLD_PRICE_HINT = '''Use EXACT prices from constraints above — especially ₹{flight_price:,.0f} for flight and ₹{hotel_price_per_night:,.0f}/night for hotel.'''
NEW_PRICE_HINT = '''Use EXACT prices from constraints above — especially ₹{train_price:,.0f} for train transport and ₹{hotel_price_per_night:,.0f}/night for hotel.''' + \
    ''' if is_train else f\'\'\'Use EXACT prices from constraints above — especially ₹{flight_price:,.0f} for flight and ₹{hotel_price_per_night:,.0f}/night for hotel.\'\'\'\'\'\'

# Rebuild hint properly
OLD_PRICE_HINT_REAL = "Use EXACT prices from constraints above"
'''

# Simpler approach for patch 6
OLD_HINT = "Use EXACT prices from constraints above — especially ₹{flight_price:,.0f} for flight and ₹{hotel_price_per_night:,.0f}/night for hotel."
NEW_HINT = "Use EXACT prices from constraints above — especially ₹{train_price if is_train else flight_price:,.0f} for {'train' if is_train else 'flight'} and ₹{hotel_price_per_night:,.0f}/night for hotel."

if OLD_HINT in content:
    content = content.replace(OLD_HINT, NEW_HINT)
    print("PATCH 6 applied: price hint updated")
else:
    print("PATCH 6 FAILED")

# ── PATCH 7: Post-processing — enforce train price ────────────────────────────
OLD_POSTPROCESS = '''        if flight_price > 0:
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
                            dl['transportation']['cost'] = flight_price'''

NEW_POSTPROCESS = '''        anchor_transport_price = train_price if is_train else flight_price
        anchor_transport_label = "train" if is_train else "flight"

        if anchor_transport_price > 0:
            if 'cost_breakdown' in plan_data:
                plan_data['cost_breakdown']['transportation'] = anchor_transport_price

            itinerary = plan_data.get('itinerary', {})
            days = sorted(itinerary.keys())

            if days:
                # Day 1: outbound transport
                d1 = itinerary[days[0]]
                if 'transportation' in d1:
                    d1['transportation']['cost'] = anchor_transport_price
                    d1['transportation']['mode'] = anchor_transport_label
                    if is_train:
                        d1['transportation']['details'] = f"{train_name} ({train_class}) - {preferences.get('starting_location','')} to {preferences['destination']}"
                    else:
                        d1['transportation']['details'] = f"{flight_airline} {flight_number} - {d1['transportation'].get('details', '')}"
                for act in d1.get('activities', []):
                    kw = anchor_transport_label
                    if kw in act.get('activity', '').lower() or 'depart' in act.get('activity', '').lower():
                        act['cost'] = anchor_transport_price

                # Last day: return transport if applicable
                if len(days) > 1:
                    dl = itinerary[days[-1]]
                    if 'transportation' in dl:
                        mode = dl['transportation'].get('mode', '').lower()
                        details = dl['transportation'].get('details', '').lower()
                        if anchor_transport_label in mode or anchor_transport_label in details or 'return' in details:
                            dl['transportation']['cost'] = anchor_transport_price
                            dl['transportation']['mode'] = anchor_transport_label'''

if OLD_POSTPROCESS in content:
    content = content.replace(OLD_POSTPROCESS, NEW_POSTPROCESS)
    print("PATCH 7 applied: post-processing handles train correctly")
else:
    print("PATCH 7 FAILED: could not find post-processing block")

# ── PATCH 8: system message references flight price ──────────────────────────
OLD_SYSMSG = '''                f"You are a travel cost calculator that outputs ONLY valid JSON. "
                f"You ALWAYS use the exact prices provided in the MANDATORY CONSTRAINTS section. "
                f"Flight cost MUST be ₹{flight_price:,.0f}. "
                f"Hotel cost MUST be ₹{hotel_price_per_night:,.0f}/night. "
                f"Never invent or change these numbers."'''

NEW_SYSMSG = '''                f"You are a travel cost calculator that outputs ONLY valid JSON. "
                f"You ALWAYS use the exact prices provided in the MANDATORY CONSTRAINTS section. "
                f"{'Train' if is_train else 'Flight'} transport cost MUST be ₹{(train_price if is_train else flight_price):,.0f}. "
                f"Hotel cost MUST be ₹{hotel_price_per_night:,.0f}/night. "
                f"Never invent or change these numbers."'''

if OLD_SYSMSG in content:
    content = content.replace(OLD_SYSMSG, NEW_SYSMSG)
    print("PATCH 8 applied: system message updated")
else:
    print("PATCH 8 FAILED")

with open(r"C:\Users\Abhinay Kandrika\OneDrive\Desktop\eyv-website-main\backend\server.py", 'w', encoding='utf-8') as f:
    f.write(content)

print("\nAll patches written to server.py")
