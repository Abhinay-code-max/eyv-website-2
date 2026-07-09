"""
Fix: inject exact Ignav price after AI plan generation.
Uses correct 3-space indentation found in the file.
"""
import shutil
from pathlib import Path

SERVER = Path(r"C:\Users\Abhinay Kandrika\OneDrive\Desktop\eyv-website-main\backend\server.py")
shutil.copy(SERVER, SERVER.with_suffix(".py.backup_postprocess3"))
server = SERVER.read_text(encoding="utf-8")

# Find exact location and replace
idx = server.find("plan_data.setdefault('currency_symbol', currency_symbol)")
if idx == -1:
    print("❌ Could not find target line")
else:
    # Find the 'return plan_data' after this point
    ret_idx = server.find("return plan_data", idx)
    if ret_idx == -1:
        print("❌ Could not find return plan_data")
    else:
        # Get the indentation of the return statement
        line_start = server.rfind('\n', 0, ret_idx) + 1
        indent = ''
        for ch in server[line_start:]:
            if ch in (' ', '\t'):
                indent += ch
            else:
                break

        print(f"Found return at index {ret_idx}, indent={repr(indent)}")

        injection = f"""
{indent}# ── Post-process: inject exact real prices ──────────────────────────
{indent}try:
{indent}    if anchor_flight:
{indent}        exact_price = anchor_flight['price']['total']
{indent}        exact_airline = anchor_flight['airline']
{indent}        exact_num = anchor_flight['flight_number']
{indent}        if 'cost_breakdown' in plan_data:
{indent}            plan_data['cost_breakdown']['transportation'] = exact_price
{indent}        itinerary = plan_data.get('itinerary', {{}})
{indent}        days = sorted(itinerary.keys())
{indent}        if days:
{indent}            d1 = itinerary[days[0]]
{indent}            if 'transportation' in d1:
{indent}                d1['transportation']['cost'] = exact_price
{indent}                d1['transportation']['details'] = f"{{exact_airline}} {{exact_num}} - " + d1['transportation'].get('details', '')
{indent}            for act in d1.get('activities', []):
{indent}                if 'flight' in act.get('activity', '').lower():
{indent}                    act['cost'] = exact_price
{indent}        if len(days) > 1:
{indent}            dl = itinerary[days[-1]]
{indent}            if 'transportation' in dl and 'flight' in dl['transportation'].get('mode', '').lower():
{indent}                dl['transportation']['cost'] = exact_price
{indent}        if 'cost_breakdown' in plan_data:
{indent}            plan_data['total_cost'] = sum(plan_data['cost_breakdown'].values())
{indent}except Exception as e:
{indent}    logger.warning(f"Price injection failed: {{e}}")

{indent}"""

        # Insert before the return statement
        server = server[:ret_idx] + injection.lstrip('\n') + server[ret_idx:]
        SERVER.write_text(server, encoding="utf-8")
        print("✓ Post-processing price injection added successfully")
