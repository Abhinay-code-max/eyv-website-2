"""
Location autocomplete + geocoding service.
Uses curated popular destinations list + Nominatim (OpenStreetMap) for geocoding.
"""
import logging
from typing import List, Dict, Optional
import httpx

logger = logging.getLogger(__name__)

# Curated popular destinations - prioritized for India + worldwide
POPULAR_DESTINATIONS = [
    # India - Major cities & tourist spots
    {"name": "Mumbai", "country": "India", "type": "city", "lat": 19.0760, "lng": 72.8777, "popularity": 100},
    {"name": "Delhi", "country": "India", "type": "city", "lat": 28.6139, "lng": 77.2090, "popularity": 100},
    {"name": "Bangalore", "country": "India", "type": "city", "lat": 12.9716, "lng": 77.5946, "popularity": 95},
    {"name": "Goa", "country": "India", "type": "state", "lat": 15.2993, "lng": 74.1240, "popularity": 98},
    {"name": "Palolem Beach, Goa", "country": "India", "type": "beach", "lat": 15.0099, "lng": 74.0233, "popularity": 90},
    {"name": "Baga Beach, Goa", "country": "India", "type": "beach", "lat": 15.5557, "lng": 73.7516, "popularity": 92},
    {"name": "Jaipur", "country": "India", "type": "city", "lat": 26.9124, "lng": 75.7873, "popularity": 95},
    {"name": "Hawa Mahal, Jaipur", "country": "India", "type": "landmark", "lat": 26.9239, "lng": 75.8267, "popularity": 88},
    {"name": "Amer Fort, Jaipur", "country": "India", "type": "landmark", "lat": 26.9855, "lng": 75.8513, "popularity": 87},
    {"name": "Agra", "country": "India", "type": "city", "lat": 27.1767, "lng": 78.0081, "popularity": 96},
    {"name": "Taj Mahal, Agra", "country": "India", "type": "landmark", "lat": 27.1751, "lng": 78.0421, "popularity": 99},
    {"name": "Udaipur", "country": "India", "type": "city", "lat": 24.5854, "lng": 73.7125, "popularity": 92},
    {"name": "Jodhpur", "country": "India", "type": "city", "lat": 26.2389, "lng": 73.0243, "popularity": 88},
    {"name": "Jaisalmer", "country": "India", "type": "city", "lat": 26.9157, "lng": 70.9083, "popularity": 85},
    {"name": "Manali", "country": "India", "type": "hill-station", "lat": 32.2396, "lng": 77.1887, "popularity": 94},
    {"name": "Shimla", "country": "India", "type": "hill-station", "lat": 31.1048, "lng": 77.1734, "popularity": 93},
    {"name": "Dharamshala", "country": "India", "type": "hill-station", "lat": 32.2190, "lng": 76.3234, "popularity": 88},
    {"name": "Mcleodganj", "country": "India", "type": "hill-station", "lat": 32.2390, "lng": 76.3231, "popularity": 86},
    {"name": "Leh, Ladakh", "country": "India", "type": "hill-station", "lat": 34.1526, "lng": 77.5771, "popularity": 90},
    {"name": "Srinagar", "country": "India", "type": "city", "lat": 34.0837, "lng": 74.7973, "popularity": 88},
    {"name": "Rishikesh", "country": "India", "type": "spiritual", "lat": 30.0869, "lng": 78.2676, "popularity": 92},
    {"name": "Haridwar", "country": "India", "type": "spiritual", "lat": 29.9457, "lng": 78.1642, "popularity": 87},
    {"name": "Varanasi", "country": "India", "type": "spiritual", "lat": 25.3176, "lng": 82.9739, "popularity": 91},
    {"name": "Kerala", "country": "India", "type": "state", "lat": 10.8505, "lng": 76.2711, "popularity": 96},
    {"name": "Munnar, Kerala", "country": "India", "type": "hill-station", "lat": 10.0889, "lng": 77.0595, "popularity": 91},
    {"name": "Alleppey, Kerala", "country": "India", "type": "city", "lat": 9.4981, "lng": 76.3388, "popularity": 89},
    {"name": "Kochi, Kerala", "country": "India", "type": "city", "lat": 9.9312, "lng": 76.2673, "popularity": 87},
    {"name": "Ooty", "country": "India", "type": "hill-station", "lat": 11.4102, "lng": 76.6950, "popularity": 88},
    {"name": "Coorg", "country": "India", "type": "hill-station", "lat": 12.3375, "lng": 75.8069, "popularity": 86},
    {"name": "Mysore", "country": "India", "type": "city", "lat": 12.2958, "lng": 76.6394, "popularity": 84},
    {"name": "Chennai", "country": "India", "type": "city", "lat": 13.0827, "lng": 80.2707, "popularity": 88},
    {"name": "Pondicherry", "country": "India", "type": "city", "lat": 11.9416, "lng": 79.8083, "popularity": 87},
    {"name": "Hyderabad", "country": "India", "type": "city", "lat": 17.3850, "lng": 78.4867, "popularity": 89},
    {"name": "Kolkata", "country": "India", "type": "city", "lat": 22.5726, "lng": 88.3639, "popularity": 88},
    {"name": "Darjeeling", "country": "India", "type": "hill-station", "lat": 27.0360, "lng": 88.2627, "popularity": 87},
    {"name": "Gangtok, Sikkim", "country": "India", "type": "hill-station", "lat": 27.3389, "lng": 88.6065, "popularity": 84},
    {"name": "Andaman Islands", "country": "India", "type": "beach", "lat": 11.7401, "lng": 92.6586, "popularity": 86},
    {"name": "Pushkar", "country": "India", "type": "spiritual", "lat": 26.4899, "lng": 74.5511, "popularity": 82},
    {"name": "Mount Abu", "country": "India", "type": "hill-station", "lat": 24.5926, "lng": 72.7156, "popularity": 80},
    {"name": "Hampi", "country": "India", "type": "landmark", "lat": 15.3350, "lng": 76.4600, "popularity": 84},
    {"name": "Ahmedabad", "country": "India", "type": "city", "lat": 23.0225, "lng": 72.5714, "popularity": 82},
    {"name": "Pune", "country": "India", "type": "city", "lat": 18.5204, "lng": 73.8567, "popularity": 85},
    {"name": "Lonavala", "country": "India", "type": "hill-station", "lat": 18.7546, "lng": 73.4068, "popularity": 83},
    {"name": "Mahabaleshwar", "country": "India", "type": "hill-station", "lat": 17.9237, "lng": 73.6584, "popularity": 81},
    {"name": "Lakshadweep", "country": "India", "type": "beach", "lat": 10.5667, "lng": 72.6417, "popularity": 80},

    # International - Popular destinations
    {"name": "Dubai", "country": "UAE", "type": "city", "lat": 25.2048, "lng": 55.2708, "popularity": 95},
    {"name": "Bangkok", "country": "Thailand", "type": "city", "lat": 13.7563, "lng": 100.5018, "popularity": 94},
    {"name": "Phuket", "country": "Thailand", "type": "beach", "lat": 7.8804, "lng": 98.3923, "popularity": 90},
    {"name": "Singapore", "country": "Singapore", "type": "city", "lat": 1.3521, "lng": 103.8198, "popularity": 94},
    {"name": "Bali", "country": "Indonesia", "type": "island", "lat": -8.3405, "lng": 115.0920, "popularity": 95},
    {"name": "Kuala Lumpur", "country": "Malaysia", "type": "city", "lat": 3.1390, "lng": 101.6869, "popularity": 88},
    {"name": "Maldives", "country": "Maldives", "type": "island", "lat": 3.2028, "lng": 73.2207, "popularity": 92},
    {"name": "Paris", "country": "France", "type": "city", "lat": 48.8566, "lng": 2.3522, "popularity": 97},
    {"name": "London", "country": "United Kingdom", "type": "city", "lat": 51.5074, "lng": -0.1278, "popularity": 96},
    {"name": "Tokyo", "country": "Japan", "type": "city", "lat": 35.6762, "lng": 139.6503, "popularity": 95},
    {"name": "New York", "country": "USA", "type": "city", "lat": 40.7128, "lng": -74.0060, "popularity": 96},
    {"name": "Rome", "country": "Italy", "type": "city", "lat": 41.9028, "lng": 12.4964, "popularity": 92},
    {"name": "Barcelona", "country": "Spain", "type": "city", "lat": 41.3851, "lng": 2.1734, "popularity": 91},
    {"name": "Istanbul", "country": "Turkey", "type": "city", "lat": 41.0082, "lng": 28.9784, "popularity": 90},
    {"name": "Sydney", "country": "Australia", "type": "city", "lat": -33.8688, "lng": 151.2093, "popularity": 89},
    {"name": "Switzerland", "country": "Switzerland", "type": "country", "lat": 46.8182, "lng": 8.2275, "popularity": 90},
    {"name": "Zurich", "country": "Switzerland", "type": "city", "lat": 47.3769, "lng": 8.5417, "popularity": 86},
    {"name": "Kathmandu", "country": "Nepal", "type": "city", "lat": 27.7172, "lng": 85.3240, "popularity": 85},
    {"name": "Pokhara", "country": "Nepal", "type": "city", "lat": 28.2096, "lng": 83.9856, "popularity": 86},
    {"name": "Colombo", "country": "Sri Lanka", "type": "city", "lat": 6.9271, "lng": 79.8612, "popularity": 84},
    {"name": "Hong Kong", "country": "Hong Kong", "type": "city", "lat": 22.3193, "lng": 114.1694, "popularity": 87},
]


def search_locations(query: str, limit: int = 8) -> List[Dict]:
    """Search popular destinations by name prefix/substring (case-insensitive)."""
    if not query or len(query.strip()) < 1:
        return []
    
    q = query.lower().strip()
    matches = []
    
    for dest in POPULAR_DESTINATIONS:
        name_lower = dest['name'].lower()
        country_lower = dest['country'].lower()
        # Prefix match scores higher than substring
        if name_lower.startswith(q):
            matches.append((dest, 2, dest['popularity']))
        elif q in name_lower or q in country_lower:
            matches.append((dest, 1, dest['popularity']))
    
    # Sort by match-quality (prefix > substring) then popularity
    matches.sort(key=lambda x: (-x[1], -x[2]))
    
    return [
        {
            "name": d['name'],
            "country": d['country'],
            "type": d['type'],
            "lat": d['lat'],
            "lng": d['lng'],
            "display_name": f"{d['name']}, {d['country']}",
        }
        for d, _, _ in matches[:limit]
    ]


async def geocode_destination(destination: str) -> Optional[Dict[str, float]]:
    """
    Get coords for a destination.
    1. Check curated popular destinations first (exact and substring match)
    2. Fall back to Nominatim (OpenStreetMap) for unknown locations
    """
    if not destination:
        return None
    
    q = destination.lower().strip()
    
    # Try exact name match first
    for dest in POPULAR_DESTINATIONS:
        if dest['name'].lower() == q:
            return {"lat": dest['lat'], "lng": dest['lng'], "name": dest['name']}
    
    # Try substring/contains match
    for dest in POPULAR_DESTINATIONS:
        if q in dest['name'].lower() or dest['name'].lower() in q:
            return {"lat": dest['lat'], "lng": dest['lng'], "name": dest['name']}
    
    # Fall back to Nominatim geocoding (free, no API key)
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": destination, "format": "json", "limit": 1},
                headers={"User-Agent": "EYV-Travel-App/1.0"},
                timeout=10.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data and len(data) > 0:
                    result = data[0]
                    return {
                        "lat": float(result["lat"]),
                        "lng": float(result["lon"]),
                        "name": result.get("display_name", destination).split(",")[0],
                    }
    except Exception as e:
        logger.warning(f"Nominatim geocode failed for '{destination}': {e}")
    
    return None
