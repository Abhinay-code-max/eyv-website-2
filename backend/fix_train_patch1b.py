with open(r"C:\Users\Abhinay Kandrika\OneDrive\Desktop\eyv-website-main\backend\server.py", 'r', encoding='utf-8') as f:
    content = f.read()

OLD = '''    flight_price = 0
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
            flight_stops    = af['stops']'''

NEW = '''    transport_mode = preferences.get("transportation", "flight").lower()
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
        train_tier_prices = {
            "Budget":  {"price": 450,  "class": "Sleeper (SL)",      "name": "Express Train"},
            "Premium": {"price": 1200, "class": "AC 3-Tier (3A)",    "name": "Superfast Express"},
            "Luxury":  {"price": 2800, "class": "AC 1st Class (1A)", "name": "Rajdhani / Shatabdi"},
        }
        t = train_tier_prices.get(plan_type, train_tier_prices["Budget"])
        train_price    = t["price"] * num_travelers
        train_class    = t["class"]
        train_name     = t["name"]
        train_number   = "Train"
        train_duration = "Varies by route"
        logger.info(f"{plan_type}: estimated train = {train_name} {train_class} \u20b9{train_price:,.0f}")
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
                flight_stops    = af['stops']'''

if OLD in content:
    content = content.replace(OLD, NEW, 1)
    print("PATCH 1b applied successfully")
else:
    print("PATCH 1b FAILED")
    idx = content.find("flight_price = 0")
    print(repr(content[idx-5:idx+400]))

with open(r"C:\Users\Abhinay Kandrika\OneDrive\Desktop\eyv-website-main\backend\server.py", 'w', encoding='utf-8') as f:
    f.write(content)
