with open(r"C:\Users\Abhinay Kandrika\OneDrive\Desktop\eyv-website-main\backend\server.py", 'r', encoding='utf-8') as f:
    content = f.read()

OLD = '            logger.info(f"{plan_type}: anchor flight = {flight_airline} {flight_number} \u20b9{flight_price:,.0f}")\n    except Exception as e:\n        logger.warning(f"Anchor flight fetch failed for {plan_type}: {e}")'

NEW = '            logger.info(f"{plan_type}: anchor flight = {flight_airline} {flight_number} \u20b9{flight_price:,.0f}")\n        except Exception as e:\n            logger.warning(f"Anchor flight fetch failed for {plan_type}: {e}")'

if OLD in content:
    content = content.replace(OLD, NEW, 1)
    print("Syntax fix applied successfully")
else:
    print("FAILED - checking exact bytes")
    idx = content.find("anchor flight = {flight_airline}")
    print(repr(content[idx+50:idx+200]))

with open(r"C:\Users\Abhinay Kandrika\OneDrive\Desktop\eyv-website-main\backend\server.py", 'w', encoding='utf-8') as f:
    f.write(content)
