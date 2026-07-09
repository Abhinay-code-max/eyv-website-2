"""
Fix: After AI generates the plan JSON, override the transportation cost
with the exact Ignav anchor price in Python — don't rely on the AI to use it.
"""
import shutil
from pathlib import Path

SERVER = Path(r"C:\Users\Abhinay Kandrika\OneDrive\Desktop\eyv-website-main\backend\server.py")
shutil.copy(SERVER, SERVER.with_suffix(".py.backup_postprocess"))
server = SERVER.read_text(encoding="utf-8")

OLD = '''        # Ensure currency fields exist
        plan_data.setdefault('currency', currency)
        plan_data.setdefault('currency_symbol', currency_symbol)

        return plan_data'''

NEW = '''        # Ensure currency fields exist
        plan_data.setdefault('currency', currency)
        plan_data.setdefault('currency_symbol', currency_symbol)

        # ── Post-process: inject exact real prices into the parsed plan ──────
        try:
            if anchor_flight:
                exact_flight_price = anchor_flight['price']['total']
                exact_airline = anchor_flight['airline']
                exact_flight_num = anchor_flight['flight_number']

                # Fix cost_breakdown transportation
                if 'cost_breakdown' in plan_data:
                    plan_data['cost_breakdown']['transportation'] = exact_flight_price

                # Fix day_1 transportation cost (outbound flight)
                itinerary = plan_data.get('itinerary', {})
                days = sorted(itinerary.keys())
                if days:
                    day1 = itinerary[days[0]]
                    if 'transportation' in day1:
                        day1['transportation']['cost'] = exact_flight_price
                        day1['transportation']['details'] = (
                            f"{exact_airline} {exact_flight_num} - "
                            + day1['transportation'].get('details', '')
                        )
                    # Fix activity cost if flight is listed as activity
                    for act in day1.get('activities', []):
                        if 'flight' in act.get('activity', '').lower() or \
                           'flight' in act.get('category', '').lower():
                            act['cost'] = exact_flight_price

                # Fix last day return flight if exists
                if len(days) > 1:
                    last_day = itinerary[days[-1]]
                    if 'transportation' in last_day:
                        t = last_day['transportation']
                        if 'flight' in t.get('mode', '').lower() or \
                           'flight' in t.get('details', '').lower():
                            last_day['transportation']['cost'] = exact_flight_price

                # Recalculate total_cost
                if 'cost_breakdown' in plan_data:
                    plan_data['total_cost'] = sum(plan_data['cost_breakdown'].values())

        except Exception as e:
            logger.warning(f"Post-process price injection failed: {e}")

        return plan_data'''

if OLD in server:
    server = server.replace(OLD, NEW)
    SERVER.write_text(server, encoding="utf-8")
    print("✓ Post-processing price injection added")
    print("  Flight price will now be overridden with exact Ignav value after AI generates plan")
else:
    print("⚠ Pattern not found — checking alternatives...")
    idx = server.find("plan_data.setdefault('currency_symbol', currency_symbol)")
    if idx != -1:
        print(f"  Found at index {idx}")
        print(f"  Context: {server[idx:idx+100]}")
    else:
        print("❌ Could not find insertion point")
