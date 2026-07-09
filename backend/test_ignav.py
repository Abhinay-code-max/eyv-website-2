"""
Test Ignav flight service directly.
"""
import asyncio
import sys
sys.path.insert(0, r"C:\Users\Abhinay Kandrika\OneDrive\Desktop\eyv-website-main\backend")

from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(r"C:\Users\Abhinay Kandrika\OneDrive\Desktop\eyv-website-main\backend\.env"))

from services import ignav_service

async def main():
    print("Testing Ignav: Delhi → Dubai on 2026-07-15...\n")
    flights = await ignav_service.search_flights("Delhi", "Dubai", "2026-07-15", travelers=1)

    if flights:
        print(f"✅ Got {len(flights)} flights:")
        for f in flights[:5]:
            print(f"  {f['airline']} {f['flight_number']} | {f['departure']['time']}→{f['arrival']['time']} | {f['stops']} stop(s) | ₹{f['price']['total']:,.0f}")
    else:
        print("❌ No flights returned")

    print("\nTesting anchor flight...")
    anchor = await ignav_service.get_anchor_flight("Delhi", "Dubai", "2026-07-15")
    if anchor:
        print(f"✅ Anchor: {anchor['airline']} {anchor['flight_number']} ₹{anchor['price']['total']:,.0f}")
    else:
        print("❌ No anchor flight")

asyncio.run(main())
