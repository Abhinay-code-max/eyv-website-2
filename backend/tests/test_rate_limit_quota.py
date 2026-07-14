"""
Rate limiting + daily generation quota tests.
Endpoints under test:
- POST /api/trips/generate (per-IP + per-user rate limits, daily quota)
- GET /api/locations/autocomplete (per-IP rate limit)
- POST /api/chat/stream (per-IP + per-user rate limits, no daily quota)
- GET /api/trips/quota-status
- GET /api/admin/usage-summary

IMPORTANT: no test in this file lets a request actually reach Gemini/
Duffel/SerpApi. Every /trips/generate call here hits it with the day's
quota already pre-exhausted via a direct DB write, so every response is a
fast 429 (quota or rate limit) - never a real (expensive) generation.
Quota-consumption itself (the "5th allowed, 6th blocked" behavior) is
verified by calling quota_service directly against the real test DB.

/chat/stream has no quota gate to short-circuit before its Gemini call (see
the comment on that decision in server.py), so unlike /trips/generate its
rate-limit test can't avoid real provider calls entirely. It uses a tiny
"hi" prompt against a dedicated test user and just enough rapid requests to
cross the 15/minute limit - a handful of cheap chat completions, far less
real cost than the existing test suite's several full (3x-Gemini +
flights + hotels) /trips/generate calls elsewhere in this repo.

(An in-process TestClient + mocked-Gemini approach was tried first to avoid
any real calls, but hit a reproducible Python 3.14 + Windows + anyio event-
loop conflict when run after another test in this file uses asyncio.run() -
not worth chasing given the small, bounded real cost of just hitting the
live server directly instead.)
"""
import os
import sys
import time
import asyncio
import pytest
import requests
from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

from services import quota_service  # noqa: E402
import server  # noqa: E402

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'http://localhost:8001').rstrip('/')
MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')

FREE_USER_ID = "test_ratelimit_free_user"
FREE_SESSION = "test_ratelimit_free_session"
PREMIUM_USER_ID = "test_ratelimit_premium_user"
PREMIUM_SESSION = "test_ratelimit_premium_session"

FREE_HEADERS = {"Authorization": f"Bearer {FREE_SESSION}", "Content-Type": "application/json"}
PREMIUM_HEADERS = {"Authorization": f"Bearer {PREMIUM_SESSION}", "Content-Type": "application/json"}

TRIP_PAYLOAD = {
    "destination": "Paris", "starting_location": "Delhi",
    "departure_date": "2027-01-01", "return_date": "2027-01-05",
    "adults": 1, "children": 0, "seniors": 0,
    "transportation": "Flight", "budget_level": "Budget",
    "accommodation": ["Hotel"], "interests": ["Culture"],
    "trip_type": "Solo", "currency": "INR", "budget_mode": True,
}


def _db():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _run(coro):
    # Not asyncio.get_event_loop().run_until_complete(...) (the pattern in
    # this repo's other test files) - that raises "There is no current
    # event loop in thread" on Python 3.14's tightened asyncio. asyncio.run
    # is the modern, version-safe way to run a coroutine to completion here.
    return asyncio.run(coro)


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _seed_session(user_id, session_token, premium=False):
    async def _do():
        db = _db()
        now = datetime.now(timezone.utc)
        user_doc = {
            "user_id": user_id, "email": f"{user_id}@example.com", "name": "Test",
            "created_at": now.isoformat(),
            "premium_status": "active" if premium else "inactive",
        }
        if premium:
            user_doc["premium_expires_at"] = (now + timedelta(days=30)).isoformat()
        await db.users.update_one({"user_id": user_id}, {"$set": user_doc}, upsert=True)
        await db.user_sessions.update_one(
            {"session_token": session_token},
            {"$set": {
                "session_token": session_token, "user_id": user_id,
                "expires_at": (now + timedelta(days=7)).isoformat(),
                "created_at": now.isoformat(),
            }},
            upsert=True,
        )
        await db.generation_quota.delete_many({"user_id": user_id})
    _run(_do())


def _set_quota(user_id, count):
    async def _do():
        db = _db()
        await db.generation_quota.update_one(
            {"user_id": user_id, "date": _today()},
            {"$set": {"count": count}},
            upsert=True,
        )
    _run(_do())


@pytest.fixture(scope="module", autouse=True)
def _setup_and_teardown():
    _seed_session(FREE_USER_ID, FREE_SESSION, premium=False)
    _seed_session(PREMIUM_USER_ID, PREMIUM_SESSION, premium=True)
    yield

    async def _cleanup():
        db = _db()
        await db.users.delete_many({"user_id": {"$in": [FREE_USER_ID, PREMIUM_USER_ID]}})
        await db.user_sessions.delete_many({"session_token": {"$in": [FREE_SESSION, PREMIUM_SESSION]}})
        await db.generation_quota.delete_many({"user_id": {"$in": [FREE_USER_ID, PREMIUM_USER_ID]}})
    _run(_cleanup())


# ---------- Daily quota ----------

def test_quota_status_reflects_service_layer_state():
    _set_quota(FREE_USER_ID, 3)
    r = requests.get(f"{BASE_URL}/api/trips/quota-status", headers=FREE_HEADERS)
    assert r.status_code == 200, r.text
    assert r.json() == {"is_premium": False, "used": 3, "limit": 5, "remaining": 2}


def test_quota_5th_generation_allowed_6th_blocked():
    """Exercises quota_service directly against the real test DB - never
    calls /trips/generate for real, which would burn real provider credits
    for what is purely our own counting logic."""
    async def _check():
        db = _db()
        await db.generation_quota.delete_many({"user_id": FREE_USER_ID})
        results = [
            await quota_service.try_consume_trip_generation(db, FREE_USER_ID, limit=5)
            for _ in range(6)
        ]
        await db.generation_quota.delete_many({"user_id": FREE_USER_ID})
        return results
    results = _run(_check())
    assert [r["allowed"] for r in results] == [True, True, True, True, True, False]
    assert results[4]["used"] == 5   # 5th call brings the count to 5
    assert results[5]["used"] == 5   # 6th call: rejected, count unchanged


def test_quota_exceeded_blocks_generate_endpoint_before_any_real_work():
    """Pre-exhausts the quota via a direct DB write (not five real calls to
    /trips/generate), then confirms the endpoint itself rejects - fast,
    proving it short-circuits before any Gemini/Duffel/SerpApi call.

    Reason is normally "quota_exceeded", but if this file was already run
    within the last minute the per-IP/per-user rate limit from that earlier
    run's rapid-fire test may still be cooling down, in which case
    "rate_limited" fires first instead - both are a correct 429 rejection
    of the same request, so both are accepted here. The quota-specific
    fields are only asserted when quota_exceeded is what actually fired.
    """
    _set_quota(FREE_USER_ID, 5)
    start = time.time()
    r = requests.post(f"{BASE_URL}/api/trips/generate", json=TRIP_PAYLOAD, headers=FREE_HEADERS, timeout=10)
    elapsed = time.time() - start
    assert r.status_code == 429, r.text
    data = r.json()
    assert data["reason"] in ("quota_exceeded", "rate_limited"), data
    if data["reason"] == "quota_exceeded":
        assert data["used"] == 5 and data["limit"] == 5
        assert "Premium" in data["detail"]
    assert elapsed < 5, f"took {elapsed:.1f}s - should short-circuit before any provider call either way"


def test_premium_user_bypasses_daily_quota():
    _set_quota(PREMIUM_USER_ID, 5)  # would be exhausted for a free user
    r = requests.get(f"{BASE_URL}/api/trips/quota-status", headers=PREMIUM_HEADERS)
    assert r.status_code == 200, r.text
    assert r.json()["is_premium"] is True
    # Same helper /trips/generate itself uses to decide whether to even
    # look at the quota.
    assert _run(server.is_user_premium(PREMIUM_USER_ID)) is True


# ---------- Rate limiting ----------

def test_autocomplete_rate_limit_returns_429_with_retry_after():
    """Autocomplete is a pure in-memory lookup (zero external cost), so
    hammering it for real is safe and cheap."""
    statuses = []
    last_429 = None
    for _ in range(35):
        r = requests.get(f"{BASE_URL}/api/locations/autocomplete", params={"q": "par"})
        statuses.append(r.status_code)
        if r.status_code == 429:
            last_429 = r
    assert 429 in statuses, f"never hit the rate limit across 35 rapid requests: {statuses}"
    assert last_429.json()["reason"] == "rate_limited"
    assert "Retry-After" in last_429.headers


def test_generate_endpoint_rate_limit_kicks_in():
    """Quota is pre-exhausted so every one of these is a fast 429 (never a
    real generation) - once the per-minute cap is hit, the reason flips
    from quota_exceeded to rate_limited."""
    _set_quota(FREE_USER_ID, 5)
    reasons = []
    for _ in range(8):
        r = requests.post(f"{BASE_URL}/api/trips/generate", json=TRIP_PAYLOAD, headers=FREE_HEADERS, timeout=10)
        assert r.status_code == 429, r.text
        reasons.append(r.json()["reason"])
    assert "rate_limited" in reasons, f"expected the per-minute limit to eventually trip: {reasons}"


def test_chat_stream_rate_limit_kicks_in():
    """No quota gate to short-circuit before the Gemini call here (see the
    comment in server.py on why chat has no daily quota), so - unlike every
    other test in this file - this one does make a small number of real,
    cheap Gemini calls (a one-word prompt, ~15 of them before the limit
    trips) to reliably prove the 15/minute limit fires. Far less real cost
    than the existing test suite's full /trips/generate calls elsewhere."""
    responses = []
    for _ in range(18):
        r = requests.post(
            f"{BASE_URL}/api/chat/stream",
            json={"message": "hi"},
            headers=FREE_HEADERS,
            timeout=30,
        )
        responses.append(r)
    statuses = [r.status_code for r in responses]
    assert 429 in statuses, f"never hit the rate limit across 18 rapid requests: {statuses}"
    limited = next(r for r in responses if r.status_code == 429)
    assert limited.json()["reason"] == "rate_limited"
    assert "Retry-After" in limited.headers


# ---------- Admin usage summary ----------

def test_admin_usage_summary_requires_key():
    r = requests.get(f"{BASE_URL}/api/admin/usage-summary")
    assert r.status_code == 403
    r = requests.get(f"{BASE_URL}/api/admin/usage-summary", headers={"X-Admin-Key": "definitely-wrong"})
    assert r.status_code == 403


def test_admin_usage_summary_structure_with_valid_key():
    admin_key = os.environ.get("TEST_ADMIN_API_KEY")
    if not admin_key:
        pytest.skip("TEST_ADMIN_API_KEY not set in this environment")
    r = requests.get(f"{BASE_URL}/api/admin/usage-summary", headers={"X-Admin-Key": admin_key})
    assert r.status_code == 200, r.text
    data = r.json()
    for key in ("today", "last_7_days", "generated_at"):
        assert key in data
    for provider in ("gemini", "duffel", "serpapi"):
        assert provider in data["today"]
        assert provider in data["last_7_days"]
