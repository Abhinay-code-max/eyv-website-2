"""
Direct fix: rewrite the anchor flight fetching + post-processing
in generate_single_plan to properly store and inject the real price.
"""
import shutil
from pathlib import Path

SERVER = Path(r"C:\Users\Abhinay Kandrika\OneDrive\Desktop\eyv-website-main\backend\server.py")
shutil.copy(SERVER, SERVER.with_suffix(".py.backup_direct"))
server = SERVER.read_text(encoding="utf-8")

# Find the entire anchor flight fetching block and replace it cleanly
OLD = '''    real_flight_note = ""
    real_hotel_note = ""
    anchor_flight = None  # stored at function scope for post-processing
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
            _anchor_price = anchor_flight['price']['total']
            _anchor_airline = anchor_flight['airline']
            _anchor_num = anchor_flight['flight_number']
            real_flight_note = ('''

NEW = '''    real_flight_note = ""
    real_hotel_note = ""
    # Function-scope anchor variables — set here, used in post-processing below
    _anchor_price = 0
    _anchor_airline = ""
    _anchor_num = ""
    try:
        flight_pref = {"Budget": "cheapest", "Premium": "direct", "Luxury": "fastest"}.get(plan_type, "cheapest")
        _af = await duffel_service.get_anchor_flight(
            preferences.get("starting_location", ""),
            preferences.get("destination", ""),
            preferences.get("departure_date", ""),
            travelers=preferences.get("num_travelers", 1),
            preference=flight_pref,
        )
        if _af:
            _anchor_price = _af['price']['total']
            _anchor_airline = _af['airline']
            _anchor_num = _af['flight_number']
            anchor_flight = _af  # keep for compatibility
            real_flight_note = ('''

if OLD in server:
    server = server.replace(OLD, NEW, 1)
    print("✓ Anchor flight block rewritten")
else:
    print("⚠ Old anchor block not found — trying without _anchor_price line...")
    # Try without the _anchor_price lines (pre-fix version)
    OLD2 = '''    real_flight_note = ""
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
            real_flight_note = ('''
    if OLD2 in server:
        server = server.replace(OLD2, NEW, 1)
        print("✓ Anchor flight block rewritten (alt pattern)")
    else:
        print("❌ Could not find anchor flight block")

# Now fix the post-process block to use _anchor_price directly
OLD_POST = '''        try:
            if '_anchor_price' in dir():
                exact_price = _anchor_price
                exact_airline = _anchor_airline
                exact_num = _anchor_num
            elif anchor_flight:
                exact_price = anchor_flight['price']['total']
                exact_airline = anchor_flight['airline']
                exact_num = anchor_flight['flight_number']
            else:
                raise ValueError('No anchor flight available')'''

NEW_POST = '''        try:
            if _anchor_price > 0:
                exact_price = _anchor_price
                exact_airline = _anchor_airline
                exact_num = _anchor_num
            else:
                raise ValueError('No anchor flight available')'''

if OLD_POST in server:
    server = server.replace(OLD_POST, NEW_POST, 1)
    print("✓ Post-process block fixed to use _anchor_price")
else:
    # Try the segment replacement approach
    idx = server.find("# ── Post-process: inject exact real prices")
    if idx != -1:
        post_try = server.find("try:", idx)
        if post_try != -1:
            post_except = server.find("except Exception as e:\n            logger.warning(f\"Price injection", post_try)
            if post_except != -1:
                old_segment = server[post_try:post_except]
                new_segment = '''try:
            if _anchor_price > 0:
                exact_price = _anchor_price
                exact_airline = _anchor_airline
                exact_num = _anchor_num
                if 'cost_breakdown' in plan_data:
                    plan_data['cost_breakdown']['transportation'] = exact_price
                itinerary = plan_data.get('itinerary', {})
                days = sorted(itinerary.keys())
                if days:
                    d1 = itinerary[days[0]]
                    if 'transportation' in d1:
                        d1['transportation']['cost'] = exact_price
                        d1['transportation']['details'] = f"{exact_airline} {exact_num} - " + d1['transportation'].get('details', '')
                    for act in d1.get('activities', []):
                        if 'flight' in act.get('activity', '').lower():
                            act['cost'] = exact_price
                if len(days) > 1:
                    dl = itinerary[days[-1]]
                    if 'transportation' in dl and 'flight' in dl['transportation'].get('mode', '').lower():
                        dl['transportation']['cost'] = exact_price
                if 'cost_breakdown' in plan_data:
                    plan_data['total_cost'] = sum(plan_data['cost_breakdown'].values())
            '''
                server = server[:post_try] + new_segment + server[post_except:]
                print("✓ Post-process block rewritten via segment replacement")

SERVER.write_text(server, encoding="utf-8")
print("\n✅ Done — restart the server and test.")
