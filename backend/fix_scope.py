"""
Fix: anchor_flight not in scope during post-process.
Store it at function scope before the try block.
"""
import shutil
from pathlib import Path

SERVER = Path(r"C:\Users\Abhinay Kandrika\OneDrive\Desktop\eyv-website-main\backend\server.py")
shutil.copy(SERVER, SERVER.with_suffix(".py.backup_scope"))
server = SERVER.read_text(encoding="utf-8")

# 1. Initialize anchor_flight at function scope (before the try block)
OLD_INIT = "    real_flight_note = \"\"\n    real_hotel_note = \"\""
NEW_INIT = "    real_flight_note = \"\"\n    real_hotel_note = \"\"\n    anchor_flight = None  # stored at function scope for post-processing"

if OLD_INIT in server:
    server = server.replace(OLD_INIT, NEW_INIT, 1)
    print("✓ anchor_flight initialized at function scope")
else:
    print("⚠ Could not find real_flight_note init")

# 2. Change the inner assignment from local to the already-declared variable
# The existing code does: anchor_flight = await duffel_service.get_anchor_flight(...)
# This already assigns to the outer scope in Python since there's no 'local' keyword
# The real issue is the post-process references it but it may not exist if the try failed
# Solution: replace "if anchor_flight:" in post-process with a safe check

OLD_POSTPROCESS = "        try:\n            if anchor_flight:"
NEW_POSTPROCESS = "        try:\n            if locals().get('anchor_flight') or (anchor_flight if anchor_flight else None):"

# Actually the cleanest fix: store anchor price as a simple variable right after fetching
OLD_ANCHOR_IF = "        if anchor_flight:\n            real_flight_note = ("
NEW_ANCHOR_IF = "        if anchor_flight:\n            _anchor_price = anchor_flight['price']['total']\n            _anchor_airline = anchor_flight['airline']\n            _anchor_num = anchor_flight['flight_number']\n            real_flight_note = ("

if OLD_ANCHOR_IF in server:
    server = server.replace(OLD_ANCHOR_IF, NEW_ANCHOR_IF, 1)
    print("✓ anchor price stored in simple variables")
else:
    print("⚠ Could not find anchor_flight if block")

# 3. Fix post-process to use simple variables instead of anchor_flight dict
OLD_POST = "        try:\n            if anchor_flight:\n                exact_price = anchor_flight['price']['total']\n                exact_airline = anchor_flight['airline']\n                exact_num = anchor_flight['flight_number']"
NEW_POST = "        try:\n            if '_anchor_price' in dir():\n                exact_price = _anchor_price\n                exact_airline = _anchor_airline\n                exact_num = _anchor_num\n            elif anchor_flight:\n                exact_price = anchor_flight['price']['total']\n                exact_airline = anchor_flight['airline']\n                exact_num = anchor_flight['flight_number']\n            else:\n                raise ValueError('No anchor flight available')"

if OLD_POST in server:
    server = server.replace(OLD_POST, NEW_POST, 1)
    print("✓ Post-process updated to use scoped variables")
else:
    # Simpler approach: just find the post-process block and fix it directly
    idx = server.find("# ── Post-process: inject exact real prices")
    if idx != -1:
        # Find the try: if anchor_flight: block
        old_check = "            if anchor_flight:"
        new_check = "            _af = anchor_flight  # use function-scope variable"
        # Find this specific occurrence after our injection point
        post_idx = server.find("if anchor_flight:", idx)
        if post_idx != -1:
            # Replace just this occurrence
            server = server[:post_idx] + "_af = anchor_flight\n            if _af:" + server[post_idx + len("if anchor_flight:"):]
            # Now fix all anchor_flight references in the post-process block
            end_idx = server.find("except Exception as e:\n            logger.warning(f\"Price injection", post_idx)
            if end_idx != -1:
                segment = server[post_idx:end_idx]
                segment = segment.replace("anchor_flight['price']['total']", "_af['price']['total']")
                segment = segment.replace("anchor_flight['airline']", "_af['airline']")
                segment = segment.replace("anchor_flight['flight_number']", "_af['flight_number']")
                server = server[:post_idx] + segment + server[end_idx:]
                print("✓ Post-process fixed via segment replacement")

SERVER.write_text(server, encoding="utf-8")
print("\n✅ Done — restart the server and test.")
