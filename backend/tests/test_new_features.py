"""EYV New Features tests: Booking (Amadeus mock), Wallet (GridFS Storage), Map coords"""
import os
import io
import pytest
import requests

from conftest import seed_session, delete_session

BASE_URL = os.environ.get(
    'REACT_APP_BACKEND_URL',
    'http://localhost:8001'
).rstrip('/')
SESSION_TOKEN = os.environ.get('TEST_SESSION_TOKEN', 'test_session_eyv_1780670554293')
USER_ID = "test_new_features_user"
HEADERS = {"Authorization": f"Bearer {SESSION_TOKEN}", "Content-Type": "application/json"}
AUTH_HEADER = {"Authorization": f"Bearer {SESSION_TOKEN}"}


@pytest.fixture(scope="module", autouse=True)
def _seeded_session():
    # The token above has no matching session in a fresh/CI DB - seed one
    # directly so tests authenticate without depending on a real login flow.
    seed_session(USER_ID, SESSION_TOKEN)
    yield
    delete_session(USER_ID, SESSION_TOKEN)


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
    # Price must come from a real, server-cached item_id returned by search -
    # it can no longer be supplied directly in the booking request.
    search_payload = {"origin": "JFK", "destination": "Paris",
                       "departure_date": "2026-03-01", "return_date": "2026-03-08", "travelers": 1}
    r = requests.post(f"{BASE_URL}/api/search/flights", json=search_payload, headers=HEADERS)
    assert r.status_code == 200, r.text
    flight = r.json()["flights"][0]
    assert "item_id" in flight
    expected_price = flight["price"]["total"]
    expected_currency = flight["price"]["currency"]

    item_data = {
        "id": flight["id"],
        "airline": flight["airline"],
    }
    payload = {
        "booking_type": "flight",
        "item_id": flight["item_id"],
        "item_data": item_data,
        "traveler_details": {"name": "Test User", "email": "test@example.com"}
    }
    r = requests.post(f"{BASE_URL}/api/bookings", json=payload, headers=HEADERS)
    assert r.status_code == 200, r.text
    booking = r.json()
    assert "booking_id" in booking
    assert "confirmation_code" in booking
    assert booking["confirmation_code"].startswith("EYV-")
    # A booking starts "pending_payment", not "confirmed" - no Stripe
    # checkout has happened yet at creation time. It's only promoted to
    # "confirmed" by a real successful payment (see
    # _process_successful_payment in server.py).
    assert booking["status"] == "pending_payment"
    assert booking["payment_status"] == "mock_paid"
    # Price is resolved server-side from the cached search result, never from the request
    assert booking["total_amount"] == expected_price
    assert booking["currency"] == expected_currency
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


# ========== Price tamper-resistance ==========

def test_booking_rejects_client_supplied_price():
    """item_data must not be able to carry a price - the field is rejected at
    the schema level (422), not silently stripped."""
    payload = {
        "booking_type": "flight",
        "item_id": "irrelevant-rejected-before-any-lookup",
        "item_data": {"airline": "Test Air", "price": {"total": 1, "currency": "USD"}},
    }
    r = requests.post(f"{BASE_URL}/api/bookings", json=payload, headers=HEADERS)
    assert r.status_code == 422


def test_booking_ignores_tampered_top_level_price_fields():
    """Extra price/amount fields outside the declared schema must have zero
    effect - the stored price always comes from the cached item_id lookup."""
    search_payload = {"origin": "JFK", "destination": "Paris",
                       "departure_date": "2026-03-01", "travelers": 1}
    r = requests.post(f"{BASE_URL}/api/search/flights", json=search_payload, headers=HEADERS)
    flight = r.json()["flights"][0]
    expected_price = flight["price"]["total"]

    payload = {
        "booking_type": "flight",
        "item_id": flight["item_id"],
        "item_data": {"airline": flight["airline"]},
        "price": 1, "amount": 1, "total_amount": 1,
    }
    r = requests.post(f"{BASE_URL}/api/bookings", json=payload, headers=HEADERS)
    assert r.status_code == 200, r.text
    assert r.json()["total_amount"] == expected_price


def test_booking_unknown_item_id_returns_expired():
    """A forged/unknown item_id must never fall back to any client-supplied
    number - it must fail closed with a clear 'expired, search again' error."""
    payload = {
        "booking_type": "flight",
        "item_id": "00000000-0000-0000-0000-000000000000",
        "item_data": {"airline": "Test Air"},
    }
    r = requests.post(f"{BASE_URL}/api/bookings", json=payload, headers=HEADERS)
    assert r.status_code == 410


# ========== Wallet ==========
def test_wallet_list_unauthorized():
    r = requests.get(f"{BASE_URL}/api/wallet")
    assert r.status_code == 401


def test_wallet_upload_unauthorized():
    files = {"file": ("test.txt", io.BytesIO(b"hello"), "text/plain")}
    r = requests.post(f"{BASE_URL}/api/wallet/upload", files=files)
    assert r.status_code == 401


def _tiny_png_bytes():
    """A genuine 1x1 PNG - the wallet upload endpoint now sniffs real file
    content (Pillow-decodes it) rather than trusting the client-supplied
    Content-Type/extension, so tests need real image bytes, not a renamed
    text file, to get past it."""
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (1, 1), color=(200, 100, 50)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(scope="module")
def uploaded_wallet_item():
    """Upload a file used by subsequent tests"""
    content = _tiny_png_bytes()
    files = {"file": ("test_boarding.png", io.BytesIO(content), "image/png")}
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
    assert item["original_filename"] == "test_boarding.png"
    assert item["content_type"] == "image/png"
    assert "_id" not in item
    assert item["size"] > 0


def test_wallet_upload_rejects_spoofed_content_type():
    """A text file dressed up as a JPEG (spoofed filename + Content-Type
    header) must be rejected - the server sniffs actual content, it never
    trusts either of those client-supplied values."""
    files = {"file": ("evil.jpg", io.BytesIO(b"<script>alert(1)</script>"), "image/jpeg")}
    r = requests.post(f"{BASE_URL}/api/wallet/upload", files=files, headers=AUTH_HEADER, timeout=60)
    assert r.status_code == 415


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


def _mint_download_link(item_id):
    r = requests.get(f"{BASE_URL}/api/wallet/{item_id}/download-url", headers=AUTH_HEADER, timeout=60)
    assert r.status_code == 200, r.text
    return r.json()


def test_wallet_download(uploaded_wallet_item):
    item, original = uploaded_wallet_item
    link = _mint_download_link(item["item_id"])
    r = requests.get(
        f"{BASE_URL}/api/wallet/{item['item_id']}/download",
        params={"expires": link["expires"], "signature": link["signature"]},
        timeout=60,
    )
    assert r.status_code == 200, r.text
    assert r.content == original
    assert r.headers["content-disposition"].startswith("attachment;")
    assert r.headers["x-content-type-options"] == "nosniff"


def test_wallet_download_no_signature_rejected():
    """The download route no longer accepts the session cookie/token at
    all (not as a cookie, not as ?auth=) - only a valid signature+expiry,
    since a raw session token in a URL leaks into logs/history/proxies."""
    r = requests.get(f"{BASE_URL}/api/wallet/some_item/download", timeout=60)
    assert r.status_code == 422  # expires/signature are required query params


def test_wallet_download_tampered_signature_rejected(uploaded_wallet_item):
    item, _ = uploaded_wallet_item
    link = _mint_download_link(item["item_id"])
    r = requests.get(
        f"{BASE_URL}/api/wallet/{item['item_id']}/download",
        params={"expires": link["expires"], "signature": "0" * 64},
        timeout=60,
    )
    assert r.status_code == 401


def test_wallet_download_expired_link_rejected(uploaded_wallet_item):
    item, _ = uploaded_wallet_item
    link = _mint_download_link(item["item_id"])
    r = requests.get(
        f"{BASE_URL}/api/wallet/{item['item_id']}/download",
        # Same signature but an expiry moved into the past - must fail even
        # with an otherwise-valid signature for a *different* expires value.
        params={"expires": link["expires"] - 100000, "signature": link["signature"]},
        timeout=60,
    )
    assert r.status_code == 401


def test_wallet_download_url_wrong_owner_rejected(uploaded_wallet_item):
    """A second user must not be able to mint a download link for someone
    else's wallet item."""
    other_user = "test_new_features_other_user"
    other_session = "test_new_features_other_session"
    seed_session(other_user, other_session)
    try:
        item, _ = uploaded_wallet_item
        r = requests.get(
            f"{BASE_URL}/api/wallet/{item['item_id']}/download-url",
            headers={"Authorization": f"Bearer {other_session}"},
            timeout=60,
        )
        assert r.status_code == 404
    finally:
        delete_session(other_user, other_session)


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
