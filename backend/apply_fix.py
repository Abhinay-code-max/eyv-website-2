import re

with open('server.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_function = '''async def generate_trip_plans(preferences: TripPreferences, request: Request):
    user = await get_current_user(request)
    
    trip_id = f"trip_{uuid.uuid4().hex[:12]}"
    
    # Store preferences
    preferences_dict = preferences.model_dump()
    
    # Generate 3 plans in parallel using AI
    plan_tasks = [
        generate_single_plan(preferences_dict, plan_type, trip_id, user.user_id)
        for plan_type in ["Budget", "Premium", "Luxury"]
    ]
    plans = await asyncio.gather(*plan_tasks)
    
    # Save trip
    saved_trip = {
        "trip_id": trip_id,
        "user_id": user.user_id,
        "trip_name": f"{preferences.destination} Trip",
        "preferences": preferences_dict,
        "plans": plans,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.trips.insert_one(saved_trip)
    
    return {"trip_id": trip_id, "plans": plans}'''

new_function = '''async def generate_trip_plans(preferences: TripPreferences, request: Request):
    user = await get_current_user(request)
    
    trip_id = f"trip_{uuid.uuid4().hex[:12]}"
    preferences_dict = preferences.model_dump()
    
    plan_tasks = [
        generate_single_plan(preferences_dict, plan_type, trip_id, user.user_id)
        for plan_type in ["Budget", "Premium", "Luxury"]
    ]
    plans = await asyncio.gather(*plan_tasks)
    
    plans = _enforce_price_ordering(plans)
    
    saved_trip = {
        "trip_id": trip_id,
        "user_id": user.user_id,
        "trip_name": f"{preferences.destination} Trip",
        "preferences": preferences_dict,
        "plans": plans,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.trips.insert_one(saved_trip)
    
    return {"trip_id": trip_id, "plans": plans}


def _enforce_price_ordering(plans):
    by_type = {p.get('plan_type'): p for p in plans}
    budget = by_type.get('Budget')
    premium = by_type.get('Premium')
    luxury = by_type.get('Luxury')
    
    if not (budget and premium and luxury):
        return plans
    
    b_cost = budget.get('total_cost', 0) or 0
    p_cost = premium.get('total_cost', 0) or 0
    l_cost = luxury.get('total_cost', 0) or 0
    
    if b_cost < p_cost < l_cost:
        return plans
    
    base = max(b_cost, 1)
    new_premium_total = round(base * 1.4)
    new_luxury_total = round(base * 2.2)
    
    def _rescale(plan, new_total):
        old_total = plan.get('total_cost', 0) or 1
        ratio = new_total / old_total if old_total else 1
        plan['total_cost'] = new_total
        breakdown = plan.get('cost_breakdown', {})
        for key in breakdown:
            breakdown[key] = round((breakdown[key] or 0) * ratio)
        return plan
    
    by_type['Premium'] = _rescale(premium, new_premium_total)
    by_type['Luxury'] = _rescale(luxury, new_luxury_total)
    
    return [by_type['Budget'], by_type['Premium'], by_type['Luxury']]'''

if old_function in content:
    content = content.replace(old_function, new_function)
    with open('server.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("SUCCESS: Function replaced!")
else:
    print("ERROR: Could not find exact match. Manual edit needed.")