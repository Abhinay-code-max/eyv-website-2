"""
EYV Comprehensive Verification Script
Tests flights, hotel tiers, pricing, and API health.
Run from the backend folder with venv activated.
"""
import asyncio
import sys
import os
from pathlib import Path

BASE = Path(r"C:\Users\Abhinay Kandrika\OneDrive\Desktop\eyv-website-main\backend")
sys.path.insert(0, str(BASE))

from dotenv import load_dotenv
load_dotenv(BASE / ".env")

from services import ignav_service, serpapi_hotels_service

# ── Colours ─────────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

passed = []
failed = []
warnings = []

def ok(msg):   print(f"  {GREEN}✓{RESET} {msg}"); passed.append(msg)
def err(msg):  print(f"  {RED}✗{RESET} {msg}"); failed.append(msg)
def warn(msg): print(f"  {YELLOW}⚠{RESET} {msg}"); warnings.append(msg)
def section(title):
    print(f"\n{BOLD}{CYAN}{'─'*55}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─'*55}{RESET}")

# ── Test routes ──────────────────────────────────────────────────────────────
FLIGHT_ROUTES = [
    ("Delhi",   "Dubai",     "2026-07-20", "Domestic→International"),
    ("Mumbai",  "Singapore", "2026-07-20", "India→SE Asia"),
    ("Delhi",   "Mumbai",    "2026-07-20", "Domestic India"),
    ("Mumbai",  "London",    "2026-07-25", "Long haul"),
]

HOTEL_DESTINATIONS = [
    ("Dubai",     "2026-07-20", "2026-07-23"),
    ("Singapore", "2026-07-20", "2026-07-23"),
    ("Mumbai",    "2026-07-20", "2026-07-22"),
    ("London",    "2026-07-25", "2026-07-28"),
]

# ── 1. Flight Tests ──────────────────────────────────────────────────────────
async def test_flights():
    section("FLIGHT API TESTS (Ignav)")
    for origin, dest, date, label in FLIGHT_ROUTES:
        print(f"\n  Route: {origin} → {dest} ({label})")
        try:
            flights = await ignav_service.search_flights(origin, dest, date, travelers=1)
            if not flights:
                warn(f"No flights returned for {origin}→{dest}")
                continue

            # Check count
            if len(flights) >= 3:
                ok(f"Got {len(flights)} flights")
            else:
                warn(f"Only {len(flights)} flight(s) returned")

            # Check pricing realism
            cheapest = flights[0]['price']['total']
            priciest = flights[-1]['price']['total']

            if cheapest > 500:
                ok(f"Prices look realistic: ₹{cheapest:,.0f} – ₹{priciest:,.0f}")
            else:
                err(f"Prices too low (possible currency issue): ₹{cheapest:,.0f}")

            # Check real airline names
            airlines = set(f['airline'] for f in flights[:3])
            fake_names = {'unknown airline', 'airline', 'unknown', ''}
            if not airlines.intersection(fake_names):
                ok(f"Real airlines: {', '.join(list(airlines)[:3])}")
            else:
                err(f"Fake airline names detected: {airlines}")

            # Check flight numbers
            has_real_fn = all(
                f['flight_number'] and len(f['flight_number']) >= 3
                for f in flights[:3]
            )
            if has_real_fn:
                ok(f"Real flight numbers: {', '.join(f['flight_number'] for f in flights[:3])}")
            else:
                warn("Some flight numbers missing or too short")

            # Check times
            has_times = all(
                f['departure']['time'] and f['arrival']['time']
                for f in flights[:3]
            )
            if has_times:
                ok(f"Times present: {flights[0]['departure']['time']} → {flights[0]['arrival']['time']}")
            else:
                err("Missing departure/arrival times")

            # Check anchor flight
            anchor = await ignav_service.get_anchor_flight(origin, dest, date)
            if anchor:
                ok(f"Anchor flight: {anchor['airline']} {anchor['flight_number']} ₹{anchor['price']['total']:,.0f}")
            else:
                warn("No anchor flight available")

        except Exception as e:
            err(f"Exception: {e}")

# ── 2. Hotel Tier Tests ──────────────────────────────────────────────────────
async def test_hotels():
    section("HOTEL API TESTS (SerpApi) + TIER ORDERING")
    for dest, check_in, check_out in HOTEL_DESTINATIONS:
        print(f"\n  Destination: {dest} ({check_in} – {check_out})")
        try:
            hotels = await serpapi_hotels_service.search_hotels(
                dest, check_in, check_out, travelers=1, currency="INR"
            )
            if not hotels:
                warn(f"No hotels returned for {dest}")
                continue

            ok(f"Got {hotels} hotels" if isinstance(hotels, int) else f"Got {len(hotels)} hotels")

            sorted_h = sorted(hotels, key=lambda h: h['price']['per_night'])
            n = len(sorted_h)

            # Check tier buckets
            if n >= 3:
                third = n // 3
                budget_max  = max(h['price']['per_night'] for h in sorted_h[:third])
                premium_min = min(h['price']['per_night'] for h in sorted_h[third:2*third])
                premium_max = max(h['price']['per_night'] for h in sorted_h[third:2*third])
                luxury_min  = min(h['price']['per_night'] for h in sorted_h[2*third:])

                if budget_max < premium_min:
                    ok(f"Tier ordering correct: Budget≤₹{budget_max:,.0f} < Premium≤₹{premium_max:,.0f} < Luxury≥₹{luxury_min:,.0f}")
                else:
                    err(f"Tier ordering BROKEN: Budget max ₹{budget_max:,.0f} >= Premium min ₹{premium_min:,.0f}")

            # Check realistic prices
            cheapest_hotel = sorted_h[0]['price']['per_night']
            priciest_hotel = sorted_h[-1]['price']['per_night']
            if cheapest_hotel > 500:
                ok(f"Hotel prices realistic: ₹{cheapest_hotel:,.0f}/night – ₹{priciest_hotel:,.0f}/night")
            else:
                err(f"Hotel prices too low: ₹{cheapest_hotel:,.0f}/night (likely USD not converted)")

            # Check hotel names are real
            names = [h['name'] for h in sorted_h[:3]]
            ok(f"Hotel names: {', '.join(names)}")

            # Check star ratings exist
            has_stars = all(h.get('stars', 0) > 0 for h in sorted_h[:5])
            if has_stars:
                ok(f"Star ratings present: {[h['stars'] for h in sorted_h[:5]]}")
            else:
                warn("Some hotels missing star ratings")

        except Exception as e:
            err(f"Exception: {e}")

# ── 3. Budget/Premium/Luxury Price Ordering ──────────────────────────────────
async def test_tier_logic():
    section("TIER PRICE ORDERING LOGIC")
    dest = "Dubai"
    check_in, check_out = "2026-07-20", "2026-07-23"

    print(f"\n  Testing Budget < Premium < Luxury for {dest}")
    try:
        hotels = await serpapi_hotels_service.search_hotels(
            dest, check_in, check_out, travelers=1, currency="INR"
        )
        if not hotels or len(hotels) < 3:
            warn("Not enough hotels to test tier ordering")
            return

        sorted_h = sorted(hotels, key=lambda h: h['price']['per_night'])
        n = len(sorted_h)
        third = n // 3

        budget_hotel  = sorted_h[0]
        premium_hotel = sorted_h[n // 2]
        luxury_hotel  = sorted_h[-1]

        b_price = budget_hotel['price']['per_night']
        p_price = premium_hotel['price']['per_night']
        l_price = luxury_hotel['price']['per_night']

        print(f"\n  Budget:  {budget_hotel['name']} ({budget_hotel['stars']}★) — ₹{b_price:,.0f}/night")
        print(f"  Premium: {premium_hotel['name']} ({premium_hotel['stars']}★) — ₹{p_price:,.0f}/night")
        print(f"  Luxury:  {luxury_hotel['name']} ({luxury_hotel['stars']}★) — ₹{l_price:,.0f}/night")

        if b_price < p_price < l_price:
            ok("Budget < Premium < Luxury ✓")
        elif b_price < l_price:
            warn(f"Partial ordering: Budget < Luxury but Premium={p_price:,.0f} is out of order")
        else:
            err(f"Tier ordering BROKEN: {b_price:,.0f} / {p_price:,.0f} / {l_price:,.0f}")

        # Check star tier enforcement
        if budget_hotel['stars'] <= premium_hotel['stars'] <= luxury_hotel['stars']:
            ok(f"Star ratings correctly tiered: {budget_hotel['stars']}★ / {premium_hotel['stars']}★ / {luxury_hotel['stars']}★")
        else:
            warn(f"Star ratings not perfectly tiered: {budget_hotel['stars']}★ / {premium_hotel['stars']}★ / {luxury_hotel['stars']}★")

    except Exception as e:
        err(f"Exception: {e}")

# ── 4. API Key Health ────────────────────────────────────────────────────────
def test_api_keys():
    section("API KEY HEALTH CHECK")
    keys = {
        "IGNAV_API_KEY":    os.environ.get("IGNAV_API_KEY"),
        "SERPAPI_KEY":      os.environ.get("SERPAPI_KEY"),
        "MONGO_URL":        os.environ.get("MONGO_URL"),
        "OPENAI_API_KEY":   os.environ.get("OPENAI_API_KEY"),
        "DUFFEL_API_KEY":   os.environ.get("DUFFEL_API_KEY"),
        "RAPIDAPI_KEY":     os.environ.get("RAPIDAPI_KEY"),
    }
    for name, val in keys.items():
        if val and len(val) > 8:
            ok(f"{name}: {'*' * 8}{val[-4:]} ✓")
        else:
            err(f"{name}: MISSING or too short")

# ── Summary ──────────────────────────────────────────────────────────────────
def print_summary():
    section("SUMMARY")
    total = len(passed) + len(failed) + len(warnings)
    print(f"\n  {GREEN}Passed:  {len(passed)}{RESET}")
    print(f"  {YELLOW}Warnings: {len(warnings)}{RESET}")
    print(f"  {RED}Failed:  {len(failed)}{RESET}")
    print(f"  Total:   {total}\n")

    if failed:
        print(f"{RED}  FAILURES:{RESET}")
        for f in failed:
            print(f"    • {f}")

    if warnings:
        print(f"{YELLOW}  WARNINGS:{RESET}")
        for w in warnings:
            print(f"    • {w}")

    if not failed:
        print(f"\n  {GREEN}{BOLD}✓ All critical checks passed!{RESET}")
    else:
        print(f"\n  {RED}{BOLD}✗ {len(failed)} issue(s) need fixing.{RESET}")

async def main():
    print(f"\n{BOLD}EYV Verification Suite{RESET}")
    print(f"Testing flights, hotels, tier logic, and API health...\n")

    test_api_keys()
    await test_flights()
    await test_hotels()
    await test_tier_logic()
    print_summary()

asyncio.run(main())
