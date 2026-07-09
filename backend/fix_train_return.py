with open(r"C:\Users\Abhinay Kandrika\OneDrive\Desktop\eyv-website-main\backend\server.py", 'r', encoding='utf-8') as f:
    content = f.read()

OLD = '''                # Last day: return transport if applicable
                if len(days) > 1:
                    dl = itinerary[days[-1]]
                    if 'transportation' in dl:
                        mode = dl['transportation'].get('mode', '').lower()
                        details = dl['transportation'].get('details', '').lower()
                        if anchor_transport_label in mode or anchor_transport_label in details or 'return' in details:
                            dl['transportation']['cost'] = anchor_transport_price
                            dl['transportation']['mode'] = anchor_transport_label'''

NEW = '''                # Last day: always force return transport to match outbound
                if len(days) > 1:
                    dl = itinerary[days[-1]]
                    if 'transportation' not in dl:
                        dl['transportation'] = {}
                    dl['transportation']['cost'] = anchor_transport_price
                    dl['transportation']['mode'] = anchor_transport_label
                    if is_train:
                        dl['transportation']['details'] = f"{train_name} ({train_class}) - {preferences['destination']} to {preferences.get('starting_location','')}"
                    else:
                        dl['transportation']['details'] = f"Return {flight_airline} {flight_number} - {preferences['destination']} to {preferences.get('starting_location','')}"'''

if OLD in content:
    content = content.replace(OLD, NEW, 1)
    print("Return transport fix applied")
else:
    print("FAILED")
    idx = content.find("Last day: return transport")
    if idx != -1:
        print(repr(content[idx:idx+300]))

with open(r"C:\Users\Abhinay Kandrika\OneDrive\Desktop\eyv-website-main\backend\server.py", 'w', encoding='utf-8') as f:
    f.write(content)
