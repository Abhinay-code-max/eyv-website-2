"""
Fix two issues in generate_single_plan:
1. Move CRITICAL PRICING RULE to TOP of prompt so AI can't ignore it
2. Fix budget_instructions to only apply to Budget tier, not all tiers
   (was causing Budget > Premium price inversions)
"""
import shutil
from pathlib import Path

SERVER = Path(r"C:\Users\Abhinay Kandrika\OneDrive\Desktop\eyv-website-main\backend\server.py")
shutil.copy(SERVER, SERVER.with_suffix(".py.backup_tierfix"))
server = SERVER.read_text(encoding="utf-8")

# ── FIX 1: Replace budget_instructions block ─────────────────────────────────
# Old: budget_instructions applied regardless of plan_type
# New: each tier gets its own cost guidance

OLD_BUDGET_BLOCK = '''    budget_instructions = ""
    if budget_mode:
        budget_instructions = """
**BUDGET OPTIMIZATION RULES (CRITICAL):**
- Prioritize the MINIMUM possible cost for every recommendation
- Suggest budget hostels, dormitories, homestays, or guesthouses (₹500-₹1500/night)
- Recommend public transport: state buses, sleeper trains (3AC/SL), local metro, shared autos
- Avoid private taxis unless absolutely necessary; prefer shared rides
- Suggest free attractions (temples, beaches, parks, viewpoints) and skip expensive entry fees where possible
- Recommend local street food and dhabas for meals (₹100-₹250 per meal)
- For flights: only when train/bus would take 24+ hours, otherwise prefer rail
- Cap daily expenditure to absolute minimum - aim for ₹2000-₹3500 per person/day
- Clearly mark free activities with cost: 0
- Distinguish FIXED costs (travel, accommodation) vs VARIABLE costs (food, activities)
"""'''

NEW_BUDGET_BLOCK = '''    # Tier-specific cost instructions — each tier must cost MORE than the previous
    if plan_type == "Budget":
        budget_instructions = """
**BUDGET TIER RULES:**
- Use the cheapest available flights (economy, low-cost carriers)
- Suggest budget hotels/guesthouses (₹800-₹2000/night)
- Recommend public transport (metro, bus, shared rides)
- Local street food and affordable restaurants (₹150-₹400/meal)
- Free or low-cost attractions where possible
- Target total trip cost: LOWEST of the three tiers
"""
    elif plan_type == "Premium":
        budget_instructions = """
**PREMIUM TIER RULES:**
- Use mid-range flights (full-service carriers, direct routes preferred)
- Suggest 4-star hotels (₹4000-₹8000/night)
- Mix of private transport and metro
- Good restaurants and cafes (₹500-₹1200/meal)
- Mix of free and paid attractions
- Target total trip cost: MIDDLE tier — must cost MORE than Budget, LESS than Luxury
"""
    else:  # Luxury
        budget_instructions = """
**LUXURY TIER RULES:**
- Use premium flights (business class or best available direct)
- Suggest 5-star hotels (₹10000+/night, e.g. Atlantis, Four Seasons, Taj)
- Private transfers and premium transport only
- Fine dining and signature restaurants (₹1500+/meal)
- Exclusive experiences and premium attractions
- Target total trip cost: HIGHEST of the three tiers — must cost MORE than Premium
"""'''

if OLD_BUDGET_BLOCK in server:
    server = server.replace(OLD_BUDGET_BLOCK, NEW_BUDGET_BLOCK)
    print("✓ Fixed tier-specific budget instructions")
else:
    # Try with different quote style
    OLD_BUDGET_BLOCK2 = OLD_BUDGET_BLOCK.replace("'", "\u2019")
    if OLD_BUDGET_BLOCK2 in server:
        server = server.replace(OLD_BUDGET_BLOCK2, NEW_BUDGET_BLOCK)
        print("✓ Fixed tier-specific budget instructions (alt quotes)")
    else:
        print("⚠ budget_instructions block not found by exact match — trying partial replace")
        # Find and replace just the if block
        idx = server.find('    budget_instructions = ""\n    if budget_mode:')
        if idx != -1:
            end_idx = server.find('\n    # ── Fetch real anchor', idx)
            if end_idx != -1:
                server = server[:idx] + NEW_BUDGET_BLOCK + '\n' + server[end_idx:]
                print("✓ Fixed via partial replace")
            else:
                print("❌ Could not find end of budget_instructions block")
        else:
            print("❌ Could not find budget_instructions block at all")

# ── FIX 2: Move CRITICAL PRICING RULE to TOP of prompt ──────────────────────
# Find the prompt f-string start and inject pricing rules right after preferences

OLD_PROMPT_HEADER = '''    prompt = f"""You are an expert Indian travel planner specialized in BUDGET-CONSCIOUS itineraries. Create a detailed {plan_type} vacation plan based on these preferences:

Destination: {preferences['destination']}'''

NEW_PROMPT_HEADER = '''    # Build pricing constraints to inject at TOP of prompt
    pricing_constraints = ""
    if anchor_flight if 'anchor_flight' in dir() else False:
        pass  # will be set below
    # (anchor_flight and anchor_hotel are set above, referenced in real_flight_note/real_hotel_note)

    prompt = f"""You are an expert travel planner. Create a detailed {plan_type} vacation plan.

=== MANDATORY PRICING RULES (READ FIRST — DO NOT IGNORE) ===
{real_flight_note.strip() if real_flight_note else "Use realistic market prices for flights."}
{real_hotel_note.strip() if real_hotel_note else "Use realistic market prices for hotels."}
The TOTAL cost of this {plan_type} plan MUST be {"the lowest" if plan_type == "Budget" else "the middle value" if plan_type == "Premium" else "the highest"} among the three tiers (Budget < Premium < Luxury).
Do NOT change the flight price or airline name provided above.
=== END MANDATORY RULES ===

Destination: {preferences['destination']}'''

if OLD_PROMPT_HEADER in server:
    server = server.replace(OLD_PROMPT_HEADER, NEW_PROMPT_HEADER)
    print("✓ Moved pricing rules to top of prompt")
else:
    print("⚠ Prompt header not found by exact match")
    idx = server.find("prompt = f\"\"\"You are an expert")
    if idx != -1:
        print(f"  Found prompt at index {idx}, context: {server[idx:idx+80]}")

# ── FIX 3: Remove the duplicate real_flight_note at END of prompt ────────────
# Since we now inject it at the TOP, remove it from the end to avoid duplication
OLD_END = "Provide REALISTIC Indian market prices in {currency}. Be specific with restaurant/hotel names. Generate one day for each day of the trip duration.{real_flight_note}{real_hotel_note}\"\"\""
NEW_END = "Provide REALISTIC prices. Be specific with restaurant/hotel names. Generate one day per day of the trip.\"\"\""

if OLD_END in server:
    server = server.replace(OLD_END, NEW_END)
    print("✓ Removed duplicate pricing note from end of prompt")
else:
    print("⚠ End of prompt pattern not found — may already be cleaned up")

SERVER.write_text(server, encoding="utf-8")
print("\n✅ Done! Restart the backend and plan a new trip.")
