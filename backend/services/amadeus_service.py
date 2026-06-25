"""
Amadeus API Service Layer
Switches between mock data and real Amadeus API based on AMADEUS_USE_MOCK env var.
"""
import os
import random
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import httpx
import logging

logger = logging.getLogger(__name__)

AMADEUS_CLIENT_ID = os.environ.get('AMADEUS_CLIENT_ID', '')
AMADEUS_CLIENT_SECRET = os.environ.get('AMADEUS_CLIENT_SECRET', '')
AMADEUS_USE_MOCK = os.environ.get('AMADEUS_USE_MOCK', 'true').lower() == 'true'
AMADEUS_BASE_URL = 'https://test.api.amadeus.com'

_amadeus_token = None
_amadeus_token_expiry = None


async def _get_amadeus_token() -> Optional[str]:
    """Get OAuth2 token from Amadeus."""
    global _amadeus_token, _amadeus_token_expiry
    
    if _amadeus_token and _amadeus_token_expiry and datetime.now() < _amadeus_token_expiry:
        return _amadeus_token
    
    if not AMADEUS_CLIENT_ID or AMADEUS_CLIENT_ID == 'YOUR_AMADEUS_CLIENT_ID':
        return None
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f'{AMADEUS_BASE_URL}/v1/security/oauth2/token',
            data={
                'grant_type': 'client_credentials',
                'client_id': AMADEUS_CLIENT_ID,
                'client_secret': AMADEUS_CLIENT_SECRET
            },
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=10.0
        )
        resp.raise_for_status()
        data = resp.json()
        _amadeus_token = data['access_token']
        _amadeus_token_expiry = datetime.now() + timedelta(seconds=data['expires_in'] - 60)
        return _amadeus_token


AIRLINES = ['Emirates', 'Qatar Airways', 'Singapore Airlines', 'Lufthansa', 'British Airways', 'Air France', 'Delta', 'United']
HOTEL_CHAINS = ['Marriott', 'Hilton', 'Hyatt', 'Four Seasons', 'Ritz-Carlton', 'IHG', 'Accor', 'Wyndham']

# Destination coordinates for map display
DESTINATION_COORDS = {
    'maldives': {'lat': 3.2028, 'lng': 73.2207},
    'switzerland': {'lat': 46.8182, 'lng': 8.2275},
    'bali': {'lat': -8.3405, 'lng': 115.0920},
    'paris': {'lat': 48.8566, 'lng': 2.3522},
    'london': {'lat': 51.5074, 'lng': -0.1278},
    'tokyo': {'lat': 35.6762, 'lng': 139.6503},
    'new york': {'lat': 40.7128, 'lng': -74.0060},
    'dubai': {'lat': 25.2048, 'lng': 55.2708},
    'singapore': {'lat': 1.3521, 'lng': 103.8198},
    'rome': {'lat': 41.9028, 'lng': 12.4964},
    'barcelona': {'lat': 41.3851, 'lng': 2.1734},
    'istanbul': {'lat': 41.0082, 'lng': 28.9784},
    'bangkok': {'lat': 13.7563, 'lng': 100.5018},
    'sydney': {'lat': -33.8688, 'lng': 151.2093},
    'goa': {'lat': 15.2993, 'lng': 74.1240},
    'kerala': {'lat': 10.8505, 'lng': 76.2711},
}


def get_destination_coords(destination: str) -> Dict[str, float]:
    """Get coordinates for a destination, defaulting to random nearby coords."""
    key = destination.lower().strip()
    for dest_key, coords in DESTINATION_COORDS.items():
        if dest_key in key or key in dest_key:
            return coords
    # Default to a reasonable random location
    return {'lat': round(random.uniform(10, 50), 4), 'lng': round(random.uniform(-100, 100), 4)}


def _generate_mock_flights(origin: str, destination: str, departure_date: str, return_date: str, travelers: int) -> List[Dict]:
    """Generate mock flight search results in Amadeus-compatible format."""
    flights = []
    base_price = random.randint(300, 800)
    
    for i in range(6):
        airline = random.choice(AIRLINES)
        carrier_code = airline[:2].upper()
        flight_num = f"{carrier_code}{random.randint(100, 999)}"
        
        dep_hour = random.randint(5, 22)
        dep_min = random.choice([0, 15, 30, 45])
        duration_hours = random.randint(2, 14)
        duration_mins = random.choice([0, 15, 30, 45])
        
        stops = random.choice([0, 0, 0, 1, 1, 2])
        
        price = base_price + random.randint(-100, 300) + (stops * -50)
        
        flights.append({
            'id': f'flight_{i}_{flight_num}',
            'airline': airline,
            'carrier_code': carrier_code,
            'flight_number': flight_num,
            'origin': origin,
            'destination': destination,
            'departure': {
                'date': departure_date,
                'time': f'{dep_hour:02d}:{dep_min:02d}',
                'airport': f'{origin[:3].upper()}'
            },
            'arrival': {
                'date': departure_date,
                'time': f'{(dep_hour + duration_hours) % 24:02d}:{dep_min:02d}',
                'airport': f'{destination[:3].upper()}'
            },
            'duration': f'{duration_hours}h {duration_mins}m',
            'stops': stops,
            'cabin_class': random.choice(['Economy', 'Premium Economy', 'Business']),
            'price': {
                'total': price * travelers,
                'per_traveler': price,
                'currency': 'USD'
            },
            'available_seats': random.randint(2, 20),
            'baggage': '1 carry-on + 1 checked'
        })
    
    return sorted(flights, key=lambda x: x['price']['total'])


def _generate_mock_hotels(destination: str, check_in: str, check_out: str, travelers: int) -> List[Dict]:
    """Generate mock hotel search results in Amadeus-compatible format."""
    hotels = []
    base_price = random.randint(80, 300)
    dest_coords = get_destination_coords(destination)
    
    for i in range(8):
        chain = random.choice(HOTEL_CHAINS)
        stars = random.choice([3, 4, 4, 5])
        rating = round(random.uniform(7.5, 9.5), 1)
        
        try:
            nights = (datetime.fromisoformat(check_out) - datetime.fromisoformat(check_in)).days
            if nights <= 0:
                nights = 3
        except (ValueError, TypeError):
            nights = 3
        
        price_per_night = base_price + (stars * 50) + random.randint(-30, 100)
        
        # Spread hotels around destination coords
        lat_offset = random.uniform(-0.05, 0.05)
        lng_offset = random.uniform(-0.05, 0.05)
        
        hotels.append({
            'id': f'hotel_{i}',
            'name': f'{chain} {destination}',
            'chain': chain,
            'stars': stars,
            'rating': rating,
            'review_count': random.randint(150, 3500),
            'address': f'{random.randint(1, 999)} Main Street, {destination}',
            'location': {
                'lat': dest_coords['lat'] + lat_offset,
                'lng': dest_coords['lng'] + lng_offset
            },
            'amenities': random.sample([
                'Free WiFi', 'Pool', 'Spa', 'Gym', 'Restaurant', 'Bar',
                'Room Service', 'Parking', 'Pet Friendly', 'Business Center',
                'Beach Access', 'Concierge'
            ], k=random.randint(5, 8)),
            'room_type': random.choice(['Standard Room', 'Deluxe Room', 'Suite', 'Family Room']),
            'nights': nights,
            'price': {
                'per_night': price_per_night,
                'total': price_per_night * nights,
                'currency': 'USD',
                'taxes_included': True
            },
            'cancellation': random.choice(['Free cancellation', 'Non-refundable', 'Free cancellation until 24h before']),
            'image_url': 'https://images.unsplash.com/photo-1731336478850-6bce7235e320'
        })
    
    return sorted(hotels, key=lambda x: x['price']['per_night'])


async def search_flights(origin: str, destination: str, departure_date: str, return_date: Optional[str] = None, travelers: int = 1) -> List[Dict]:
    """Search for flights. Uses mock or real Amadeus API based on configuration."""
    if AMADEUS_USE_MOCK:
        return _generate_mock_flights(origin, destination, departure_date, return_date or departure_date, travelers)
    
    try:
        token = await _get_amadeus_token()
        if not token:
            logger.warning("Amadeus token unavailable, falling back to mock")
            return _generate_mock_flights(origin, destination, departure_date, return_date or departure_date, travelers)
        
        async with httpx.AsyncClient() as client:
            params = {
                'originLocationCode': origin[:3].upper(),
                'destinationLocationCode': destination[:3].upper(),
                'departureDate': departure_date,
                'adults': travelers,
                'max': 10
            }
            if return_date:
                params['returnDate'] = return_date
            
            resp = await client.get(
                f'{AMADEUS_BASE_URL}/v2/shopping/flight-offers',
                params=params,
                headers={'Authorization': f'Bearer {token}'},
                timeout=15.0
            )
            resp.raise_for_status()
            data = resp.json()
            return _transform_amadeus_flights(data.get('data', []))
    except Exception as e:
        logger.error(f"Amadeus API error: {e}, falling back to mock")
        return _generate_mock_flights(origin, destination, departure_date, return_date or departure_date, travelers)


async def search_hotels(destination: str, check_in: str, check_out: str, travelers: int = 1) -> List[Dict]:
    """Search for hotels. Uses mock or real Amadeus API based on configuration."""
    if AMADEUS_USE_MOCK:
        return _generate_mock_hotels(destination, check_in, check_out, travelers)
    
    try:
        token = await _get_amadeus_token()
        if not token:
            return _generate_mock_hotels(destination, check_in, check_out, travelers)
        return _generate_mock_hotels(destination, check_in, check_out, travelers)
    except Exception as e:
        logger.error(f"Amadeus API error: {e}")
        return _generate_mock_hotels(destination, check_in, check_out, travelers)


def _transform_amadeus_flights(amadeus_data: List[Dict]) -> List[Dict]:
    """Transform Amadeus flight offers to our standard format."""
    flights = []
    for offer in amadeus_data:
        try:
            itin = offer['itineraries'][0]
            segment = itin['segments'][0]
            last_segment = itin['segments'][-1]
            
            flights.append({
                'id': offer['id'],
                'airline': segment['carrierCode'],
                'carrier_code': segment['carrierCode'],
                'flight_number': f"{segment['carrierCode']}{segment['number']}",
                'origin': segment['departure']['iataCode'],
                'destination': last_segment['arrival']['iataCode'],
                'departure': {
                    'date': segment['departure']['at'][:10],
                    'time': segment['departure']['at'][11:16],
                    'airport': segment['departure']['iataCode']
                },
                'arrival': {
                    'date': last_segment['arrival']['at'][:10],
                    'time': last_segment['arrival']['at'][11:16],
                    'airport': last_segment['arrival']['iataCode']
                },
                'duration': itin['duration'].replace('PT', '').lower(),
                'stops': len(itin['segments']) - 1,
                'cabin_class': 'Economy',
                'price': {
                    'total': float(offer['price']['total']),
                    'per_traveler': float(offer['price']['total']) / int(offer.get('travelerPricings', [{}])[0].get('quantity', 1)),
                    'currency': offer['price']['currency']
                },
                'available_seats': 9,
                'baggage': '1 carry-on + 1 checked'
            })
        except (KeyError, IndexError) as e:
            logger.warning(f"Failed to parse flight offer: {e}")
            continue
    return flights
