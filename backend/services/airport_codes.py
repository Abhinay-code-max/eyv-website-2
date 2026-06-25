"""
City/destination name -> IATA airport code lookup.
Covers major Indian cities (primary market) plus common international
hubs. Falls back to None if unknown - callers should handle that case
rather than guessing a wrong code.
"""
from typing import Optional

# Major Indian cities + international hubs relevant to an India-based
# travel app. Extend this list over time based on actual user destinations.
CITY_TO_IATA = {
    # Major Indian cities
    'mumbai': 'BOM',
    'delhi': 'DEL',
    'new delhi': 'DEL',
    'bangalore': 'BLR',
    'bengaluru': 'BLR',
    'hyderabad': 'HYD',
    'chennai': 'MAA',
    'kolkata': 'CCU',
    'pune': 'PNQ',
    'ahmedabad': 'AMD',
    'goa': 'GOI',
    'kochi': 'COK',
    'cochin': 'COK',
    'jaipur': 'JAI',
    'lucknow': 'LKO',
    'chandigarh': 'IXC',
    'guwahati': 'GAU',
    'bhubaneswar': 'BBI',
    'indore': 'IDR',
    'nagpur': 'NAG',
    'coimbatore': 'CJB',
    'thiruvananthapuram': 'TRV',
    'trivandrum': 'TRV',
    'varanasi': 'VNS',
    'amritsar': 'ATQ',
    'srinagar': 'SXR',
    'leh': 'IXL',
    'port blair': 'IXZ',
    'andaman': 'IXZ',
    'coorg': 'IXM',  # nearest airport: Mangalore (no airport in Coorg itself)
    'madikeri': 'IXM',
    'kodagu': 'IXM',
    'ooty': 'CJB',  # nearest airport: Coimbatore
    'munnar': 'COK',  # nearest airport: Kochi
    'shimla': 'SLV',
    'manali': 'KUU',
    'rishikesh': 'DED',  # nearest: Dehradun
    'haridwar': 'DED',
    'udaipur': 'UDR',
    'jodhpur': 'JDH',
    'agra': 'AGR',
    'varkala': 'TRV',
    'alleppey': 'COK',
    'alappuzha': 'COK',
    # International hubs
    'dubai': 'DXB',
    'singapore': 'SIN',
    'bangkok': 'BKK',
    'london': 'LHR',
    'paris': 'CDG',
    'new york': 'JFK',
    'tokyo': 'NRT',
    'sydney': 'SYD',
    'bali': 'DPS',
    'maldives': 'MLE',
    'kathmandu': 'KTM',
    'colombo': 'CMB',
}


def get_iata_code(destination: str) -> Optional[str]:
    """
    Looks up the IATA airport code for a destination name.
    Returns None if unknown - callers should handle this explicitly
    rather than falling back to a wrong/guessed code.
    """
    if not destination:
        return None

    key = destination.lower().strip()

    # Exact match first
    if key in CITY_TO_IATA:
        return CITY_TO_IATA[key]

    # Substring match (handles "Hyderabad, India" or "Coorg, Karnataka")
    for city_name, code in CITY_TO_IATA.items():
        if city_name in key or key in city_name:
            return code

    # If the input is already a 3-letter code, assume it's valid
    if len(key) == 3 and key.isalpha():
        return key.upper()

    return None
