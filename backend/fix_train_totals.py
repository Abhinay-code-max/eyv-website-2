with open(r"C:\Users\Abhinay Kandrika\OneDrive\Desktop\eyv-website-main\backend\server.py", 'r', encoding='utf-8') as f:
    content = f.read()

OLD = '''        # Recalculate total
        if 'cost_breakdown' in plan_data:
            plan_data['total_cost'] = sum(plan_data['cost_breakdown'].values())
        logger.info(f"{plan_type}: day_1 transport cost AFTER fix = {plan_data.get('itinerary', {}).get('day_1', {}).get('transportation', {}).get('cost', 'N/A')}")'''

NEW = '''        # Recalculate cost_breakdown and total from actual itinerary
        itinerary = plan_data.get('itinerary', {})
        real_transport = 0
        real_accommodation = 0
        real_food = 0
        real_activities = 0

        for day_key, day_data in itinerary.items():
            t = day_data.get('transportation', {})
            if isinstance(t, dict):
                real_transport += t.get('cost', 0)
            a = day_data.get('accommodation', {})
            if isinstance(a, dict):
                real_accommodation += a.get('cost', 0)
            for meal in day_data.get('meals', []):
                real_food += meal.get('cost', 0)
            for act in day_data.get('activities', []):
                real_activities += act.get('cost', 0)

        plan_data['cost_breakdown'] = {
            'transportation': real_transport,
            'accommodation': real_accommodation,
            'food': real_food,
            'activities': real_activities,
            'miscellaneous': 0,
        }
        plan_data['total_cost'] = sum(plan_data['cost_breakdown'].values())
        logger.info(f"{plan_type}: day_1 transport cost AFTER fix = {plan_data.get('itinerary', {}).get('day_1', {}).get('transportation', {}).get('cost', 'N/A')}")
        logger.info(f"{plan_type}: recalculated total = {plan_data['total_cost']}")'''

if OLD in content:
    content = content.replace(OLD, NEW, 1)
    print("Total recalculation fix applied")
else:
    print("FAILED - searching for partial match")
    idx = content.find("# Recalculate total")
    if idx != -1:
        print(repr(content[idx:idx+200]))

with open(r"C:\Users\Abhinay Kandrika\OneDrive\Desktop\eyv-website-main\backend\server.py", 'w', encoding='utf-8') as f:
    f.write(content)
