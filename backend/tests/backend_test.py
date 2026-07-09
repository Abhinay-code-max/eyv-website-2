"""EYV Backend API tests"""
import os
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'http://localhost:8001').rstrip('/')
SESSION_TOKEN = os.environ.get('TEST_SESSION_TOKEN', 'test_session_1780479201772')
HEADERS = {"Authorization": f"Bearer {SESSION_TOKEN}", "Content-Type": "application/json"}


# Root and Auth
def test_root():
    r = requests.get(f"{BASE_URL}/api/")
    assert r.status_code == 200
    assert "EYV" in r.json().get("message", "")


def test_auth_me_unauthorized():
    r = requests.get(f"{BASE_URL}/api/auth/me")
    assert r.status_code == 401


def test_auth_me_authorized():
    r = requests.get(f"{BASE_URL}/api/auth/me", headers=HEADERS)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "user_id" in data
    assert "email" in data


def test_auth_invalid_session_id_exchange():
    r = requests.post(f"{BASE_URL}/api/auth/session", json={"session_id": "invalid-id-xyz"})
    assert r.status_code in (401, 500)


# Trips
def test_trips_list_unauthorized():
    r = requests.get(f"{BASE_URL}/api/trips")
    assert r.status_code == 401


def test_trips_list_authorized():
    r = requests.get(f"{BASE_URL}/api/trips", headers=HEADERS)
    assert r.status_code == 200
    assert "trips" in r.json()


def test_trip_not_found():
    r = requests.get(f"{BASE_URL}/api/trips/nonexistent_id", headers=HEADERS)
    assert r.status_code == 404


def test_trip_delete_not_found():
    r = requests.delete(f"{BASE_URL}/api/trips/nonexistent_id", headers=HEADERS)
    assert r.status_code == 404


# Chat
def test_chat_unauthorized():
    r = requests.post(f"{BASE_URL}/api/chat/stream", json={"message": "hi"})
    assert r.status_code == 401


def test_chat_stream_authorized():
    r = requests.post(
        f"{BASE_URL}/api/chat/stream",
        json={"message": "Say hi in 3 words"},
        headers=HEADERS,
        stream=True,
        timeout=30,
    )
    assert r.status_code == 200
    chunks = []
    for line in r.iter_lines(decode_unicode=True):
        if line:
            chunks.append(line)
        if len(chunks) > 5 or "[DONE]" in (line or ""):
            break
    assert len(chunks) > 0


# Trip generation (slow, AI-driven). Validate response shape.
@pytest.mark.timeout(180)
def test_trip_generate_and_lifecycle():
    payload = {
        "destination": "Paris",
        "starting_location": "New York",
        "departure_date": "2026-03-01",
        "return_date": "2026-03-04",
        "num_travelers": 2,
        "adults": 2,
        "children": 0,
        "seniors": 0,
        "transportation": "flight",
        "budget_level": "Premium",
        "accommodation": ["hotel"],
        "interests": ["culture", "food"],
        "trip_type": "leisure",
    }
    r = requests.post(f"{BASE_URL}/api/trips/generate", json=payload, headers=HEADERS, timeout=180)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "trip_id" in data and "plans" in data
    assert len(data["plans"]) == 3
    trip_id = data["trip_id"]

    # GET single trip
    g = requests.get(f"{BASE_URL}/api/trips/{trip_id}", headers=HEADERS)
    assert g.status_code == 200
    trip = g.json()
    assert trip["trip_id"] == trip_id
    assert "_id" not in trip

    # DELETE
    d = requests.delete(f"{BASE_URL}/api/trips/{trip_id}", headers=HEADERS)
    assert d.status_code == 200

    # Verify removed
    g2 = requests.get(f"{BASE_URL}/api/trips/{trip_id}", headers=HEADERS)
    assert g2.status_code == 404
