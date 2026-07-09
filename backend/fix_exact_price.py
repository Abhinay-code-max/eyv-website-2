"""
Fix: enforce exact flight price in AI prompt.
The AI was inflating the Ignav price slightly — this makes it stricter.
"""
import shutil
from pathlib import Path

SERVER = Path(r"C:\Users\Abhinay Kandrika\OneDrive\Desktop\eyv-website-main\backend\server.py")
shutil.copy(SERVER, SERVER.with_suffix(".py.backup_exactprice"))
server = SERVER.read_text(encoding="utf-8")

OLD = (
    'f"Use this EXACT airline name ({anchor_flight[\'airline\']}) and price in your itinerary. '
    'Do NOT say \'budget airline\' or invent a carrier — always use the real airline name provided."'
)

NEW = (
    'f"CRITICAL PRICING RULE: The flight for this plan MUST cost EXACTLY ₹{anchor_flight[\'price\'][\'total\']:,.0f} — '
    'do not round, inflate, or change this number under any circumstances. '
    'The airline is {anchor_flight[\'airline\']} and the flight number is {anchor_flight[\'flight_number\']}. '
    'Use these exact values in the transportation section and activity cost. '
    'Do NOT say \'budget airline\', do NOT invent prices — use ONLY the values provided above."'
)

if OLD in server:
    server = server.replace(OLD, NEW)
    SERVER.write_text(server, encoding="utf-8")
    print("✓ Fixed — AI will now use exact Ignav price and airline name")
else:
    print("⚠ Pattern not found — searching for similar text...")
    idx = server.find("EXACT airline name")
    if idx != -1:
        print("Context:", server[idx-50:idx+200])
    else:
        print("Not found at all — may need manual check")
