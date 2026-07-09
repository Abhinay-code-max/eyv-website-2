"""
Fix: LLM session ID is reused across trips causing cached responses.
Make session_id unique per generation using uuid.
Also add logging to confirm post-processing is firing.
"""
import shutil
from pathlib import Path

SERVER = Path(r"C:\Users\Abhinay Kandrika\OneDrive\Desktop\eyv-website-main\backend\server.py")
shutil.copy(SERVER, SERVER.with_suffix(".py.backup_session"))
server = SERVER.read_text(encoding="utf-8")

# Fix 1: Make session_id unique per generation
OLD_SESSION = 'session_id=f"{trip_id}_{plan_type}",'
NEW_SESSION = 'session_id=f"{trip_id}_{plan_type}_{uuid.uuid4().hex[:8]}",'

count = server.count(OLD_SESSION)
if count > 0:
    server = server.replace(OLD_SESSION, NEW_SESSION)
    print(f"✓ Fixed session_id to be unique ({count} occurrence(s))")
else:
    print("⚠ session_id pattern not found")

# Fix 2: Add logging before and after post-processing
OLD_POST_START = "        # ── Step 5: Post-process — enforce exact prices regardless of AI output"
NEW_POST_START = """        # ── Step 5: Post-process — enforce exact prices regardless of AI output
        logger.info(f"{plan_type}: flight_price={flight_price}, hotel_price={hotel_price_per_night}")
        logger.info(f"{plan_type}: AI day_1 transport cost before fix = {plan_data.get('itinerary', {}).get('day_1', {}).get('transportation', {}).get('cost', 'N/A')}")"""

if OLD_POST_START in server:
    server = server.replace(OLD_POST_START, NEW_POST_START)
    print("✓ Added debug logging to post-process")
else:
    print("⚠ Post-process start marker not found")

# Fix 3: Add logging AFTER post-processing to confirm it ran
OLD_POST_END = "        # Recalculate total\n        if 'cost_breakdown' in plan_data:\n            plan_data['total_cost'] = sum(plan_data['cost_breakdown'].values())"
NEW_POST_END = """        # Recalculate total
        if 'cost_breakdown' in plan_data:
            plan_data['total_cost'] = sum(plan_data['cost_breakdown'].values())
        logger.info(f"{plan_type}: day_1 transport cost AFTER fix = {plan_data.get('itinerary', {}).get('day_1', {}).get('transportation', {}).get('cost', 'N/A')}")"""

if OLD_POST_END in server:
    server = server.replace(OLD_POST_END, NEW_POST_END)
    print("✓ Added post-fix logging")
else:
    print("⚠ Post-process end marker not found")

SERVER.write_text(server, encoding="utf-8")
print("\n✅ Done — restart server, plan a new trip, then check the server terminal logs.")
print("   Look for lines like: 'Budget: day_1 transport cost AFTER fix = 14110.0'")
