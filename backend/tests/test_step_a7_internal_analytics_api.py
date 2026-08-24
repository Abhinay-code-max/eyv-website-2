"""
Tests for internal_analytics_api.py - the /api/internal/analytics/*
service-token-gated, read-only API (Step A7). Mirrors
test_internal_tickets_api.py's structure closely - same auth/scope/rate-
limit test shapes, just re-pointed at this router's own token/routes/
collections. Standalone from the ticket/support-agent system (Phase 4) - no
dependency on it.

Uses `requests` against the REAL, separately-running backend process
(BASE_URL) rather than conftest.py's in-process TestClient `client` fixture
- see test_step_a7_event_tracking.py's own module docstring for the full
explanation of why: this stack has a pre-existing test-infra issue where
any SECOND file touching server.py's shared `db` client (in-process, by any
mechanism) in the same pytest session reliably breaks. Neither of this
router's two routes need any external-service mocking to test deterministically
(funnel/promotions are both pure DB reads), so the live-process route -
already used by test_new_features.py, test_rewards_payments.py,
test_trip_regenerate.py, test_booking_hygiene.py, etc. - works cleanly here
too, with the added benefit of not needing this file to avoid running
alongside test_internal_tickets_api.py at all.

INTERNAL_ANALYTICS_API_TOKEN must already be set in the environment before
this file (or any file - server.py imports internal_analytics_api
unconditionally) is collected, exactly like INTERNAL_TICKET_API_TOKEN.
"""
import asyncio
import inspect
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import requests
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'http://localhost:8001').rstrip('/')
MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')
VALID_TOKEN = os.environ['INTERNAL_ANALYTICS_API_TOKEN']
AUTH_HEADERS = {"Authorization": f"Bearer {VALID_TOKEN}"}


def _db():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _run(coro):
    return asyncio.run(coro)


def _delete_many(collection_name, query):
    async def _do():
        db = _db()
        await db[collection_name].delete_many(query)
    _run(_do())


def _recent_audit_entries(route=None, limit=20):
    async def _do():
        db = _db()
        query = {}
        if route:
            query["route"] = route
        cursor = db.analytics_agent_audit_log.find(query).sort("timestamp", -1).limit(limit)
        return await cursor.to_list(limit)
    return _run(_do())


# ═══════════════ Auth: correct / wrong / missing token ═══════════════

def test_correct_token_succeeds():
    r = requests.get(f"{BASE_URL}/api/internal/analytics/funnel", headers=AUTH_HEADERS, timeout=10)
    assert r.status_code == 200, r.text
    assert "funnel" in r.json()


def test_wrong_token_rejected_and_logged_as_failed_attempt():
    r = requests.get(
        f"{BASE_URL}/api/internal/analytics/funnel",
        headers={"Authorization": "Bearer definitely-the-wrong-token"},
        timeout=10,
    )
    assert r.status_code == 401, r.text

    entries = _recent_audit_entries(route="/api/internal/analytics/funnel")
    assert entries, "expected at least one audit log entry for GET /funnel"
    latest = entries[0]
    assert latest["status_code"] == 401
    assert latest["summary"].get("auth") == "rejected"


def test_no_token_at_all_rejected_and_logged():
    r = requests.get(f"{BASE_URL}/api/internal/analytics/funnel", timeout=10)
    assert r.status_code == 401, r.text

    entries = _recent_audit_entries(route="/api/internal/analytics/funnel")
    assert entries[0]["status_code"] == 401
    assert entries[0]["summary"].get("auth") == "rejected"


# ═══════════════ Scope ═══════════════

def test_valid_analytics_token_rejected_on_unrelated_route():
    """A valid /api/internal/analytics/* token must have zero special
    meaning anywhere else - same invariant test_internal_tickets_api.py
    checks for its own token."""
    r = requests.get(f"{BASE_URL}/api/bookings", headers=AUTH_HEADERS, timeout=10)
    assert r.status_code == 401, r.text


def test_ticket_agent_token_has_no_meaning_on_analytics_router():
    """The two internal routers' tokens are independent secrets - a valid
    /api/internal/tickets/* token must not also authenticate against this
    router."""
    ticket_token = os.environ.get('INTERNAL_TICKET_API_TOKEN', '')
    r = requests.get(
        f"{BASE_URL}/api/internal/analytics/funnel",
        headers={"Authorization": f"Bearer {ticket_token}"},
        timeout=10,
    )
    assert r.status_code == 401, r.text


def test_module_never_references_user_trips_bookings_or_payment_collections():
    """Static confirmation of the scope boundary in
    internal_analytics_api.py's module docstring (section 2): every metric
    this router serves is derived entirely from db.analytics_events'
    metadata - it never queries db.users/db.bookings/db.trips/
    db.payment_transactions directly, even though those are where that
    metadata originated. Pure source inspection - no server import needed
    beyond the module itself, no I/O at all."""
    import ast
    import internal_analytics_api
    source = inspect.getsource(internal_analytics_api)
    tree = ast.parse(source)
    forbidden_attrs = {"users", "bookings", "trips", "payment_transactions"}
    real_references = sorted({
        node.attr for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in forbidden_attrs
    })
    assert not real_references, f"internal_analytics_api.py has real code referencing db.{real_references}"


# ═══════════════ Routes: funnel ═══════════════

def _seed_event(event_type, user_id, metadata, timestamp):
    async def _do():
        db = _db()
        await db.analytics_events.insert_one({
            "event_type": event_type, "user_id": user_id, "timestamp": timestamp, "metadata": metadata,
        })
    _run(_do())


def _get_funnel():
    r = requests.get(f"{BASE_URL}/api/internal/analytics/funnel", headers=AUTH_HEADERS, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    return {s["stage"]: s for s in body["funnel"]}, body


def test_funnel_counts_and_dropoffs_with_seeded_data():
    """Seeds a known set of events and asserts on the DELTA the funnel
    endpoint reports before vs. after - not on absolute counts, which
    aren't isolated to this test in a shared test database. Four synthetic
    trips, each exercising a different path through the funnel:

      trip_a: plan_generated only, long enough ago to be past the
              drop-off window -> counts as a plan_to_booking-stage drop-off.
      trip_b: plan_generated only, just now (still within the drop-off
              window) -> must NOT count as a drop-off yet.
      trip_c: plan_generated -> plan_to_booking -> booking_completed ->
              reaches every stage.
      trip_d: plan_generated -> plan_to_booking -> booking_abandoned (the
              explicit signal) -> counts as a booking_completed-stage
              drop-off.
    """
    marker = uuid.uuid4().hex[:8]
    user_id = f"test_funnel_user_{marker}"
    old_ts = datetime.now(timezone.utc) - timedelta(days=30)
    recent_ts = datetime.now(timezone.utc)

    trip_a = f"trip_funnel_a_{marker}"
    trip_b = f"trip_funnel_b_{marker}"
    trip_c = f"trip_funnel_c_{marker}"
    trip_d = f"trip_funnel_d_{marker}"
    booking_c = f"BK_FUNNEL_C_{marker}"
    booking_d = f"BK_FUNNEL_D_{marker}"

    before, _ = _get_funnel()

    _seed_event("plan_generated", user_id, {"trip_id": trip_a, "plan_type": "Budget"}, old_ts)
    _seed_event("plan_generated", user_id, {"trip_id": trip_b, "plan_type": "Budget"}, recent_ts)
    _seed_event("plan_generated", user_id, {"trip_id": trip_c, "plan_type": "Budget"}, old_ts)
    _seed_event("plan_to_booking", user_id, {"trip_id": trip_c, "booking_id": booking_c}, old_ts)
    _seed_event("booking_completed", user_id, {"trip_id": trip_c, "booking_id": booking_c}, old_ts)
    _seed_event("plan_generated", user_id, {"trip_id": trip_d, "plan_type": "Budget"}, old_ts)
    _seed_event("plan_to_booking", user_id, {"trip_id": trip_d, "booking_id": booking_d}, old_ts)
    _seed_event("booking_abandoned", user_id, {"booking_id": booking_d}, old_ts)

    try:
        after, body = _get_funnel()

        assert after["plan_generated"]["count"] - before["plan_generated"]["count"] == 4
        assert after["plan_to_booking"]["count"] - before["plan_to_booking"]["count"] == 2
        assert after["booking_completed"]["count"] - before["booking_completed"]["count"] == 1
        # Only trip_a is old enough AND never booked - trip_b is too recent
        # to count yet.
        assert after["plan_to_booking"]["drop_off_count"] - before["plan_to_booking"]["drop_off_count"] == 1
        # Only booking_d's explicit abandonment.
        assert after["booking_completed"]["drop_off_count"] - before["booking_completed"]["drop_off_count"] == 1
        assert body["drop_off_window_days"] > 0
    finally:
        _delete_many("analytics_events", {"metadata.trip_id": {"$in": [trip_a, trip_b, trip_c, trip_d]}})


# ═══════════════ Routes: promotions ═══════════════

def test_promotions_endpoint_returns_seeded_promotion_with_usage_ratio():
    code = f"TESTFUNNEL{uuid.uuid4().hex[:6].upper()}"
    now = datetime.now(timezone.utc)

    async def _seed():
        db = _db()
        await db.promotions.insert_one({
            "code": code, "discount_type": "percent", "discount_value": 20,
            "valid_from": now, "valid_until": now + timedelta(days=30),
            "usage_cap": 50, "redemption_count": 5, "created_at": now,
        })
    _run(_seed())

    try:
        r = requests.get(f"{BASE_URL}/api/internal/analytics/promotions", headers=AUTH_HEADERS, timeout=10)
        assert r.status_code == 200, r.text
        promos = {p["code"]: p for p in r.json()["promotions"]}
        assert code in promos
        assert promos[code]["redemption_count"] == 5
        assert promos[code]["usage_cap"] == 50
        assert promos[code]["usage_ratio"] == 0.1
    finally:
        _delete_many("promotions", {"code": code})


def test_promotions_endpoint_usage_ratio_null_when_no_cap():
    code = f"TESTNOCAP{uuid.uuid4().hex[:6].upper()}"
    now = datetime.now(timezone.utc)

    async def _seed():
        db = _db()
        await db.promotions.insert_one({
            "code": code, "discount_type": "fixed", "discount_value": 15,
            "valid_from": now, "valid_until": now + timedelta(days=30),
            "usage_cap": None, "redemption_count": 3, "created_at": now,
        })
    _run(_seed())

    try:
        r = requests.get(f"{BASE_URL}/api/internal/analytics/promotions", headers=AUTH_HEADERS, timeout=10)
        assert r.status_code == 200, r.text
        promos = {p["code"]: p for p in r.json()["promotions"]}
        assert promos[code]["usage_ratio"] is None
    finally:
        _delete_many("promotions", {"code": code})


def test_promotions_endpoint_rejects_missing_token():
    r = requests.get(f"{BASE_URL}/api/internal/analytics/promotions", timeout=10)
    assert r.status_code == 401, r.text


# ═══════════════ Rate limiting - LAST in the file, deliberately ═══════════════
# Same shared-bucket reasoning as test_internal_tickets_api.py's own
# rate-limit tests at the bottom of that file.

def test_rate_limit_enforced_on_funnel_route():
    # A plain `requests.get(...)` per call opens a fresh TCP connection each
    # time - real, measurable overhead against a live localhost process
    # (unlike test_internal_tickets_api.py's in-process TestClient
    # equivalent, which pays none of that). Reusing one requests.Session
    # (keep-alive) is what keeps 75 real HTTP round trips comfortably
    # inside slowapi's 60/minute rolling window - without it, the window
    # can roll over before the count ever reaches the limit, making the
    # rate limit look like it never triggers when it actually did, just
    # too slowly for this test to observe within one window.
    statuses = []
    with requests.Session() as s:
        for _ in range(75):
            r = s.get(f"{BASE_URL}/api/internal/analytics/funnel", headers=AUTH_HEADERS, timeout=10)
            statuses.append(r.status_code)
            if r.status_code == 429:
                break
    assert 429 in statuses, (
        f"expected a 429 within 75 requests once the 60/minute budget was "
        f"exhausted, got status codes: {sorted(set(statuses))}"
    )


def test_wrong_token_requests_are_rate_limited_too():
    statuses = []
    with requests.Session() as s:
        for _ in range(150):
            r = s.get(
                f"{BASE_URL}/api/internal/analytics/funnel",
                headers={"Authorization": "Bearer still-the-wrong-token"},
                timeout=10,
            )
            statuses.append(r.status_code)
            if r.status_code == 429:
                break
    assert 429 in statuses, (
        f"expected a 429 within 150 wrong-token requests once "
        f"AUTH_GATE_RATE_LIMIT was exhausted, got status codes: {sorted(set(statuses))}"
    )
    assert all(s in (401, 429) for s in statuses), (
        f"expected only 401 (auth rejected) or 429 (rate limited) responses "
        f"for wrong-token requests, got: {sorted(set(statuses))}"
    )


def test_post_promotion_creates_code():
    code = f"TEST_PROMO_{uuid.uuid4().hex[:6].upper()}"
    try:
        r = requests.post(
            f"{BASE_URL}/api/internal/analytics/promotions",
            json={"code": code, "discount_type": "percent", "discount_value": 15.0, "valid_days": 10, "usage_cap": 50},
            headers=AUTH_HEADERS,
            timeout=10,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "created"
        assert data["promotion"]["code"] == code
        assert data["promotion"]["discount_value"] == 15.0
    finally:
        _delete_many("promotions", {"code": code})


def test_campaign_crud_lifecycle():
    title = f"Test Campaign {uuid.uuid4().hex[:6]}"
    # 1. Create
    r = requests.post(
        f"{BASE_URL}/api/internal/analytics/campaigns",
        json={"title": title, "channel": "buffer", "status": "pending_approval", "content": {"caption": "Explore Goa!"}},
        headers=AUTH_HEADERS,
        timeout=10,
    )
    assert r.status_code == 200, r.text
    camp = r.json()
    camp_id = camp["campaign_id"]

    try:
        # 2. Get single
        r_get = requests.get(f"{BASE_URL}/api/internal/analytics/campaigns/{camp_id}", headers=AUTH_HEADERS, timeout=10)
        assert r_get.status_code == 200, r_get.text
        assert r_get.json()["campaign"]["title"] == title

        # 3. Patch
        r_patch = requests.patch(
            f"{BASE_URL}/api/internal/analytics/campaigns/{camp_id}",
            json={"status": "published", "external_post_id": "buf_12345"},
            headers=AUTH_HEADERS,
            timeout=10,
        )
        assert r_patch.status_code == 200, r_patch.text
        assert r_patch.json()["campaign"]["status"] == "published"
        assert r_patch.json()["campaign"]["external_post_id"] == "buf_12345"

        # 4. Stats
        r_stats = requests.get(f"{BASE_URL}/api/internal/analytics/campaigns/stats", headers=AUTH_HEADERS, timeout=10)
        assert r_stats.status_code == 200, r_stats.text
        stats = r_stats.json()
        assert "total" in stats
        assert "published" in stats
        assert "pending" in stats
    finally:
        from bson import ObjectId
        _delete_many("marketing_campaigns", {"_id": ObjectId(camp_id)})

