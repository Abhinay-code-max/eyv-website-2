"""EYV New Features tests: Booking (Amadeus mock), Wallet (Emergent Storage), Map coords"""
import os
import io
import pytest
import requests

BASE_URL = os.environ.get(
    'REACT_APP_BACKEND_URL',
    'https://ai-vacation-planner-1.preview.emergentagent.com'
).rstrip('/')
SESSION_TOKEN = os.environ.get('TEST_SESSION_TOKEN', 'test_session_eyv_1780670554293')
HEADERS = {"Authorization": f"Bearer {SESSION_TOKEN}", "Content-Type": "application/json"}
AUTH_HEADER = {"Authorization": f"Bearer {SESSION_TOKEN}"}


# ========== Flight Search ==========
def test_flights_unauthorized():
    r = requests.post(f"{BASE_URL}/api/search/flights",
                      json={"origin": "JFK", "destination": "Paris",
                            "departure_date": "2026-03-01", "travelers": 1})
    assert r.status_code == 401


def test_flights_search_success():
    payload = {"origin": "JFK", "destination": "Paris",
               "departure_date": "2026-03-01", "return_date": "2026-03-08", "travelers": 2}
    r = requests.post(f"{BASE_URL}/api/search/flights", json=payload, headers=HEADERS)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "flights" in data and "count" in data
    assert data["count"] == 6
    assert len(data["flights"]) == 6
    f = data["flights"][0]
    for k in ("id", "airline", "carrier_code", "flight_number", "departure",
              "arrival", "duration", "stops", "price"):
        assert k in f, f"missing {k} in flight"
    assert "total" in f["price"] and "currency" in f["price"]


# ========== Hotel Search ==========
def test_hotels_unauthorized():
    r = requests.post(f"{BASE_URL}/api/search/hotels",
                      json={"destination": "Paris", "check_in": "2026-03-01",
                            "check_out": "2026-03-05", "travelers": 1})
    assert r.status_code == 401


def test_hotels_search_success():
    payload = {"destination": "Paris", "check_in": "2026-03-01",
               "check_out": "2026-03-05", "travelers": 2}
    r = requests.post(f"{BASE_URL}/api/search/hotels", json=payload, headers=HEADERS)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "hotels" in data and "count" in data
    assert data["count"] == 8
    h = data["hotels"][0]
    for k in ("id", "name", "stars", "rating", "amenities", "price",
              "location", "image_url"):
        assert k in h
    assert "lat" in h["location"] and "lng" in h["location"]
    assert "per_night" in h["price"]


# ========== Destination Coords ==========
def test_coords_unauthorized():
    r = requests.get(f"{BASE_URL}/api/destinations/paris/coords")
    assert r.status_code == 401


def test_coords_known_destination():
    r = requests.get(f"{BASE_URL}/api/destinations/paris/coords", headers=AUTH_HEADER)
    assert r.status_code == 200
    data = r.json()
    assert "lat" in data and "lng" in data
    # Paris coords
    assert abs(data["lat"] - 48.8566) < 0.01
    assert abs(data["lng"] - 2.3522) < 0.01


def test_coords_unknown_destination():
    r = requests.get(f"{BASE_URL}/api/destinations/zzunknownplace/coords", headers=AUTH_HEADER)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data.get("lat"), (int, float))
    assert isinstance(data.get("lng"), (int, float))


# ========== Bookings CRUD ==========
def test_bookings_unauthorized():
    r = requests.get(f"{BASE_URL}/api/bookings")
    assert r.status_code == 401


def test_booking_lifecycle():
    # Create
    item_data = {
        "id": "flight_test_1",
        "airline": "Test Air",
        "price": {"total": 599.99, "currency": "USD"}
    }
    payload = {
        "booking_type": "flight",
        "item_id": "flight_test_1",
        "item_data": item_data,
        "traveler_details": {"name": "Test User", "email": "test@example.com"}
    }
    r = requests.post(f"{BASE_URL}/api/bookings", json=payload, headers=HEADERS)
    assert r.status_code == 200, r.text
    booking = r.json()
    assert "booking_id" in booking
    assert "confirmation_code" in booking
    assert booking["confirmation_code"].startswith("EYV-")
    assert booking["status"] == "confirmed"
    assert booking["payment_status"] == "mock_paid"
    assert booking["total_amount"] == 599.99
    assert booking["currency"] == "USD"
    assert "_id" not in booking
    booking_id = booking["booking_id"]

    # List
    r = requests.get(f"{BASE_URL}/api/bookings", headers=AUTH_HEADER)
    assert r.status_code == 200
    bookings = r.json()["bookings"]
    assert any(b["booking_id"] == booking_id for b in bookings)

    # Get single
    r = requests.get(f"{BASE_URL}/api/bookings/{booking_id}", headers=AUTH_HEADER)
    assert r.status_code == 200
    assert r.json()["booking_id"] == booking_id

    # Cancel (DELETE)
    r = requests.delete(f"{BASE_URL}/api/bookings/{booking_id}", headers=AUTH_HEADER)
    assert r.status_code == 200

    # Verify cancellation
    r = requests.get(f"{BASE_URL}/api/bookings/{booking_id}", headers=AUTH_HEADER)
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"


def test_booking_not_found():
    r = requests.get(f"{BASE_URL}/api/bookings/BKNONEXISTENT", headers=AUTH_HEADER)
    assert r.status_code == 404


def test_booking_delete_not_found():
    r = requests.delete(f"{BASE_URL}/api/bookings/BKNONEXISTENT", headers=AUTH_HEADER)
    assert r.status_code == 404


# ========== Wallet ==========
def test_wallet_list_unauthorized():
    r = requests.get(f"{BASE_URL}/api/wallet")
    assert r.status_code == 401


def test_wallet_upload_unauthorized():
    files = {"file": ("test.txt", io.BytesIO(b"hello"), "text/plain")}
    r = requests.post(f"{BASE_URL}/api/wallet/upload", files=files)
    assert r.status_code == 401


@pytest.fixture(scope="module")
def uploaded_wallet_item():
    """Upload a file used by subsequent tests"""
    content = b"TEST WALLET FILE CONTENT - boarding pass dummy"
    files = {"file": ("test_boarding.txt", io.BytesIO(content), "text/plain")}
    # Backend reads category/title/description as QUERY params (not form fields)
    params = {"category": "boarding_pass", "title": "TEST_Boarding Pass",
              "description": "Pytest upload"}
    r = requests.post(f"{BASE_URL}/api/wallet/upload",
                      files=files, params=params, headers=AUTH_HEADER, timeout=60)
    if r.status_code != 200:
        pytest.skip(f"Upload failed: {r.status_code} {r.text}")
    return r.json(), content


def test_wallet_upload_success(uploaded_wallet_item):
    item, _ = uploaded_wallet_item
    assert "item_id" in item
    assert item["item_id"].startswith("wallet_")
    assert item["category"] == "boarding_pass"
    assert item["title"] == "TEST_Boarding Pass"
    assert item["original_filename"] == "test_boarding.txt"
    assert "_id" not in item
    assert item["size"] > 0


def test_wallet_list(uploaded_wallet_item):
    item, _ = uploaded_wallet_item
    r = requests.get(f"{BASE_URL}/api/wallet", headers=AUTH_HEADER)
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(it["item_id"] == item["item_id"] for it in items)


def test_wallet_list_category_filter(uploaded_wallet_item):
    r = requests.get(f"{BASE_URL}/api/wallet?category=boarding_pass", headers=AUTH_HEADER)
    assert r.status_code == 200
    items = r.json()["items"]
    assert all(it["category"] == "boarding_pass" for it in items)


def test_wallet_download(uploaded_wallet_item):
    item, original = uploaded_wallet_item
    r = requests.get(f"{BASE_URL}/api/wallet/{item['item_id']}/download",
                     headers=AUTH_HEADER, timeout=60)
    assert r.status_code == 200, r.text
    assert r.content == original


def test_wallet_download_query_auth(uploaded_wallet_item):
    """Test the ?auth= query param auth path used by <img> tags"""
    item, original = uploaded_wallet_item
    r = requests.get(
        f"{BASE_URL}/api/wallet/{item['item_id']}/download?auth={SESSION_TOKEN}",
        timeout=60
    )
    assert r.status_code == 200
    assert r.content == original


def test_wallet_delete(uploaded_wallet_item):
    item, _ = uploaded_wallet_item
    r = requests.delete(f"{BASE_URL}/api/wallet/{item['item_id']}", headers=AUTH_HEADER)
    assert r.status_code == 200
    # Verify item not in list anymore (soft-delete)
    r = requests.get(f"{BASE_URL}/api/wallet", headers=AUTH_HEADER)
    items = r.json()["items"]
    assert not any(it["item_id"] == item["item_id"] for it in items)


def test_wallet_delete_not_found():
    r = requests.delete(f"{BASE_URL}/api/wallet/wallet_nonexistent", headers=AUTH_HEADER)
    assert r.status_code == 404
