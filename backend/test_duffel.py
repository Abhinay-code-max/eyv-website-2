"""
Quick standalone test for duffel_service.py.
Run this directly to confirm your DUFFEL_API_KEY works and real flight
data comes back, before wiring it into server.py.

Usage:
    python test_duffel.py
"""
import asyncio
import sys
import os

# Make sure we can import from services/ regardless of where this is run from
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from services import duffel_service


async def main():
    print("Testing Duffel flight search...")
    print(f"API key configured: {'Yes' if duffel_service.DUFFEL_API_KEY else 'NO - missing from .env!'}")
    print()

    # Use real city names now, not pre-known airport codes, to test the
    # new airport_codes lookup end-to-end.
    flights = await duffel_service.search_flights(
        origin="Hyderabad",
        destination="Port Blair",
        departure_date="2026-07-15",
        return_date=None,
        travelers=1,
    )

    if not flights:
        print("No flights returned. Check the error logs above for details.")
        return

    print(f"Got {len(flights)} flight(s) back:\n")
    for f in flights:
        print(f"  {f['airline']} {f['flight_number']}: {f['origin']} -> {f['destination']}")
        print(f"    Departs {f['departure']['date']} at {f['departure']['time']}")
        print(f"    Price: {f['price']['currency']} {f['price']['total']}")
        print(f"    Stops: {f['stops']}, Duration: {f['duration']}")
        print()

    print("=" * 50)
    print("Testing get_anchor_flight (used by AI itinerary generator)...")
    anchor = await duffel_service.get_anchor_flight(
        origin="Hyderabad",
        destination="Port Blair",
        departure_date="2026-07-15",
        preference="cheapest",
    )
    if anchor:
        print(f"Anchor flight: {anchor['airline']} {anchor['flight_number']}")
        print(f"  Price: {anchor['price']['currency']} {anchor['price']['total']}")
        print(f"  Stops: {anchor['stops']}, Duration: {anchor['duration']}")
    else:
        print("No anchor flight found (this would trigger AI fallback pricing)")


if __name__ == "__main__":
    asyncio.run(main())
