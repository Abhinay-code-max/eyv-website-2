with open(r"C:\Users\Abhinay Kandrika\OneDrive\Desktop\eyv-website-main\backend\server.py", 'r', encoding='utf-8') as f:
    content = f.read()

# The logger.info and except are at wrong indentation inside the else block
# Fix: add proper indentation to logger.info and except inside else:
OLD = '''            if af:
                flight_price    = af['price']['total']
                flight_airline  = af['airline']
                flight_number   = af['flight_number']
                flight_dep_time = af['departure']['time']
                flight_arr_time = af['arrival']['time']
                flight_duration = af['duration']
                flight_stops    = af['stops']
            logger.info(f"{plan_type}: anchor flight = {flight_airline} {flight_number} \u00e2\u20ac\u00b9{flight_price:,.0f}")
    except Exception as e:
        logger.warning(f"Anchor flight fetch failed for {plan_type}: {e}")'''

NEW = '''            if af:
                flight_price    = af['price']['total']
                flight_airline  = af['airline']
                flight_number   = af['flight_number']
                flight_dep_time = af['departure']['time']
                flight_arr_time = af['arrival']['time']
                flight_duration = af['duration']
                flight_stops    = af['stops']
            logger.info(f"{plan_type}: anchor flight = {flight_airline} {flight_number} \u20b9{flight_price:,.0f}")
        except Exception as e:
            logger.warning(f"Anchor flight fetch failed for {plan_type}: {e}")'''

if OLD in content:
    content = content.replace(OLD, NEW, 1)
    print("Syntax fix applied successfully")
else:
    # Try finding the garbled rupee symbol variant
    idx = content.find("anchor flight = {flight_airline}")
    if idx != -1:
        print("Found logger line, showing context:")
        print(repr(content[idx-200:idx+200]))
    else:
        print("Could not find anchor flight logger line")

with open(r"C:\Users\Abhinay Kandrika\OneDrive\Desktop\eyv-website-main\backend\server.py", 'w', encoding='utf-8') as f:
    f.write(content)
