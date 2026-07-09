"""
Fix: tell the AI to use the real airline name from the anchor flight,
not just the price.
"""
import shutil
from pathlib import Path

SERVER = Path(r"C:\Users\Abhinay Kandrika\OneDrive\Desktop\eyv-website-main\backend\server.py")
shutil.copy(SERVER, SERVER.with_suffix(".py.backup_airline"))
server = SERVER.read_text(encoding="utf-8")

OLD = (
    'f"Use this EXACT price for the flight cost in your plan."'
)
NEW = (
    'f"Use this EXACT airline name ({anchor_flight[\'airline\']}) and price in your itinerary. '
    'Do NOT say \'budget airline\' or invent a carrier — always use the real airline name provided."'
)

if OLD in server:
    server = server.replace(OLD, NEW)
    SERVER.write_text(server, encoding="utf-8")
    print("✓ Fixed — AI will now use real airline name from Sky Scrapper")
else:
    print("⚠ Pattern not found — may already be patched or wording differs")
    # Show context around the anchor flight note for debugging
    idx = server.find("Use this EXACT price")
    if idx != -1:
        print("Found similar text at:", server[idx:idx+120])
