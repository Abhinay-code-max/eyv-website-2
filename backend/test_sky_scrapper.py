"""
Test Sky Scrapper directly to see what data it returns.
"""
import asyncio
import sys
sys.path.insert(0, r"C:\Users\Abhinay Kandrika\OneDrive\Desktop\eyv-website-main\backend")

from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(r"C:\Users\Abhinay Kandrika\OneDrive\Desktop\eyv-website-main\backend\.env"))

from services import sky_scrapper_service

async def main():
    print("Testing Sky Scrapper airport lookup...")
    origin = await sky_scrapper_service._resolve_sky_id("Delhi")
    dest = await sky_scrapper_service._resolve_sky_id("Dubai")
    print(f"Delhi: {origin}")
    print(f"Dubai: {dest}")

    print("\nSearching flights Delhi → Dubai on 2026-07-15...")
    flights = await sky_scrapper_service.search_flights(
        "Delhi", "Dubai", "2026-07-15", travelers=1
    )
    if flights:
        print(f"Got {len(flights)} flights")
        for f in flights[:3]:
            print(f"  {f['airline']} {f['flight_number']} | {f['departure']['time']}→{f['arrival']['time']} | {f['stops']} stop(s) | ₹{f['price']['total']:,.0f}")
    else:
        print("No flights returned — will fall back to mock data")

    print("\nTesting anchor flight...")
    anchor = await sky_scrapper_service.get_anchor_flight("Delhi", "Dubai", "2026-07-15")
    if anchor:
        print(f"Anchor: {anchor['airline']} {anchor['flight_number']} ₹{anchor['price']['total']:,.0f}")
    else:
        print("No anchor flight — AI will invent prices")

asyncio.run(main())
