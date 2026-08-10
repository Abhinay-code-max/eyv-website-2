"""
Event-write tests for Step A7 (Analytics + Promotions Data). Standalone
from the ticket/support-agent system (Phase 4) - no dependency on it.

FILE NAMING NOTE: named test_step_a7_* (sorting after test_internal_tickets_api.py
alphabetically) and, more importantly, structured to NEVER touch server.py's
module-level `db` (a shared Motor client) or run any request through
server.app in-process, deliberately. This stack (Python 3.14 + Windows +
motor) has a pre-existing, already-documented test-infra issue: once ANY
file in a pytest session binds that shared client to its own event loop
(conftest.py's session-scoped `client` TestClient fixture does this - see
test_internal_tickets_api.py, the one file that already relies on it),
EVERY OTHER later touch of that same client - via the same TestClient
fixture, via a fresh ASGITransport, or via a bare direct async call to a
server.py function - reproducibly raises "attached to a different loop"
RuntimeErrors for the rest of the pytest process. This was verified
directly while building this file (an exact duplicate of
test_internal_tickets_api.py fails ~50% of its own tests when run as a
second client-fixture file in the same session; the same happens with a
fresh per-test ASGITransport instead). Not something this step should try
to fix - see the project's own notes on this pre-existing issue - so this
file is designed to avoid the trap entirely rather than race it:

  1. Unit tests for services/analytics_service.py's record_event() directly
     against a freshly-constructed, isolated AsyncIOMotorClient (this
     file's own _db()) - a completely different object from server.db, so
     always safe regardless of what any other file already did.
  2. Static source checks confirming each of the four server.py call sites
     (_generate_and_save_tier / regenerate_trip_plan, create_booking /
     book_trip_plan, _process_successful_payment, _process_expired_payment)
     actually calls analytics_service.record_event(...) with the right
     event_type, under the right guard condition - `import server` and
     `inspect.getsource(...)` never touch server.db either (Motor clients
     are lazy - no I/O happens at construction), so this is equally safe.
  3. True end-to-end HTTP tests, via `requests` against the REAL, separately-
     running backend process (BASE_URL) - not server.app in-process - for
     plan_to_booking (create_booking, book_trip_plan). This is the one
     event type fully testable this way with no external-service mocking
     needed (price is resolved from a directly-seeded price_cache entry,
     no live flight/hotel search required), matching the exact pattern
     test_booking_hygiene.py already uses for these same two endpoints.
     plan_generated/booking_completed/booking_abandoned would need
     in-process monkeypatching of generate_single_plan/
     stripe.checkout.Session.retrieve to be deterministic without spending
     real Gemini/Stripe quota - not reachable from a separate live process,
     so those three are covered by (1)+(2) above instead.
"""
import asyncio
import inspect
import os
import sys
import uuid
from datetime import datetime, timezone

import requests
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server  # noqa: E402 - only for inspect.getsource(...) below, never called
from services import analytics_service, price_cache_service  # noqa: E402

from conftest import seed_session, delete_session  # noqa: E402

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'http://localhost:8001').rstrip('/')
MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')


def _db():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _run(coro):
    return asyncio.run(coro)


def _delete_many(collection_name, query):
    async def _do():
        db = _db()
        await db[collection_name].delete_many(query)
    _run(_do())


def _events_for(event_type, **metadata_filters):
    async def _do():
        db = _db()
        query = {"event_type": event_type}
        for k, v in metadata_filters.items():
            query[f"metadata.{k}"] = v
        return await db.analytics_events.find(query).sort("timestamp", -1).to_list(20)
    return _run(_do())


# ═══════════════ 1. analytics_service.record_event unit tests ═══════════════

def test_record_event_writes_correct_shape_and_native_datetime():
    marker = f"test_writer_{uuid.uuid4().hex[:10]}"

    async def _do():
        db = _db()
        await analytics_service.record_event(db, "plan_generated", "user_123", {"trip_id": marker})
        return await db.analytics_events.find_one({"metadata.trip_id": marker})

    try:
        doc = _run(_do())
        assert doc is not None
        assert doc["event_type"] == "plan_generated"
        assert doc["user_id"] == "user_123"
        assert isinstance(doc["timestamp"], datetime)
        assert doc["metadata"] == {"trip_id": marker}
    finally:
        _delete_many("analytics_events", {"metadata.trip_id": marker})


def test_record_event_defaults_metadata_to_empty_dict():
    async def _do():
        db = _db()
        await analytics_service.record_event(db, "booking_abandoned", None, None)
        return await db.analytics_events.find_one(
            {"event_type": "booking_abandoned", "user_id": None, "metadata": {}},
            sort=[("timestamp", -1)],
        )

    doc = _run(_do())
    try:
        assert doc is not None
        assert doc["metadata"] == {}
    finally:
        if doc is not None:
            _delete_many("analytics_events", {"_id": doc["_id"]})


def test_record_event_never_raises_on_write_failure(monkeypatch):
    """Fire-and-forget: a write failure must be swallowed and logged, never
    propagated - instrumentation must never turn a real user action into a
    500 (see analytics_service.record_event's own docstring)."""
    class _BrokenCollection:
        async def insert_one(self, *a, **kw):
            raise RuntimeError("simulated Mongo failure")

    class _BrokenDb:
        analytics_events = _BrokenCollection()

    _run(analytics_service.record_event(_BrokenDb(), "plan_generated", "u1", {}))  # must not raise


# ═══════════════ 2. Static wiring checks (source-level, no I/O at all) ══════

def _source(func) -> str:
    return inspect.getsource(func)


def test_generate_and_save_tier_records_plan_generated_only_when_ready():
    src = _source(server._generate_and_save_tier)
    assert "analytics_service.record_event" in src
    assert '"plan_generated"' in src
    assert 'plan.get("status") == "ready"' in src


def test_regenerate_trip_plan_records_plan_generated_only_when_ready():
    src = _source(server.regenerate_trip_plan)
    assert "analytics_service.record_event" in src
    assert '"plan_generated"' in src
    assert 'regenerated.get("status") == "ready"' in src


def test_create_booking_records_plan_to_booking_guarded_by_trip_id():
    src = _source(server.create_booking)
    assert "analytics_service.record_event" in src
    assert '"plan_to_booking"' in src
    assert "if req.trip_id:" in src


def test_book_trip_plan_records_plan_to_booking_unconditionally():
    src = _source(server.book_trip_plan)
    assert "analytics_service.record_event" in src
    assert '"plan_to_booking"' in src


def test_process_successful_payment_records_booking_completed():
    src = _source(server._process_successful_payment)
    assert "analytics_service.record_event" in src
    assert '"booking_completed"' in src


def test_process_expired_payment_records_booking_abandoned_guarded_by_match():
    src = _source(server._process_expired_payment)
    assert "analytics_service.record_event" in src
    assert '"booking_abandoned"' in src
    assert "result.matched_count > 0" in src


# ═══════════════ 3. plan_to_booking end-to-end, via the live backend ═══════
# requests + BASE_URL against the real, separately-running backend process -
# never server.app in-process. See this file's own module docstring for why.

class _Session:
    """Self-seeded user+session per test, same idiom as
    test_booking_hygiene.py/test_rewards_race.py."""

    def __enter__(self):
        self.user_id = f"test_a7_events_{uuid.uuid4().hex[:10]}"
        self.token = f"test_a7_events_token_{uuid.uuid4().hex}"
        self.headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        seed_session(self.user_id, self.token)
        return self

    def __exit__(self, *exc):
        delete_session(self.user_id, self.token)


def _seed_price(item_type="flight", price=250.0, currency="USD"):
    async def _do():
        db = _db()
        return await price_cache_service.cache_price(db, item_type, "test-provider", {}, price=price, currency=currency)
    return _run(_do())


def _seed_bookable_trip(user_id, trip_id, plan_type="Budget"):
    async def _do():
        db = _db()
        now = datetime.now(timezone.utc)
        plan = {
            "plan_type": plan_type, "status": "ready", "currency": "USD",
            "anchor_pricing": {
                "flight_price": 200, "hotel_price_per_night": 100,
                "is_train": False, "is_cruise": False, "is_road": False,
                "flight_airline": "Test Air", "flight_number": "TA123",
                "flight_dep_time": "10:00", "flight_arr_time": "12:00",
                "flight_duration": "2h", "flight_stops": 0,
                "hotel_name": "Test Hotel", "hotel_stars": 4,
            },
            "cost_breakdown": {"transportation": 200, "accommodation": 300},
        }
        await db.trips.insert_one({
            "trip_id": trip_id, "user_id": user_id, "trip_name": "Test Trip",
            "preferences": {"destination": "Paris", "departure_date": "2026-09-01", "return_date": "2026-09-05"},
            "plans": [plan], "created_at": now, "updated_at": now,
        })
    _run(_do())


def test_create_booking_records_plan_to_booking_when_trip_id_set():
    with _Session() as s:
        trip_id = f"trip_test_{uuid.uuid4().hex[:10]}"
        item_id = _seed_price()
        try:
            r = requests.post(
                f"{BASE_URL}/api/bookings",
                json={"booking_type": "flight", "item_id": item_id, "trip_id": trip_id},
                headers=s.headers,
            )
            assert r.status_code == 200, r.text
            booking_id = r.json()["booking_id"]

            events = _events_for("plan_to_booking", trip_id=trip_id)
            assert len(events) == 1, f"expected exactly one plan_to_booking event, got {len(events)}"
            assert events[0]["metadata"]["booking_id"] == booking_id
            assert events[0]["metadata"]["booking_type"] == "flight"
            assert events[0]["user_id"] == s.user_id
            assert isinstance(events[0]["timestamp"], datetime)
        finally:
            _delete_many("bookings", {"trip_id": trip_id})
            _delete_many("price_cache", {"item_id": item_id})
            _delete_many("analytics_events", {"metadata.trip_id": trip_id})


def test_create_booking_records_no_event_without_trip_id():
    with _Session() as s:
        item_id = _seed_price()
        r = requests.post(
            f"{BASE_URL}/api/bookings",
            json={"booking_type": "flight", "item_id": item_id},
            headers=s.headers,
        )
        assert r.status_code == 200, r.text
        booking_id = r.json()["booking_id"]
        try:
            events = _events_for("plan_to_booking", booking_id=booking_id)
            assert events == [], "a booking with no trip_id must not be a plan_to_booking conversion"
        finally:
            _delete_many("bookings", {"booking_id": booking_id})
            _delete_many("price_cache", {"item_id": item_id})


def test_book_trip_plan_records_plan_to_booking_event():
    with _Session() as s:
        trip_id = f"trip_test_{uuid.uuid4().hex[:10]}"
        _seed_bookable_trip(s.user_id, trip_id, "Budget")
        try:
            r = requests.post(f"{BASE_URL}/api/trips/{trip_id}/book/Budget", headers=s.headers)
            assert r.status_code == 200, r.text
            booking_id = r.json()["booking_id"]

            events = _events_for("plan_to_booking", trip_id=trip_id)
            assert len(events) == 1
            assert events[0]["metadata"]["booking_id"] == booking_id
            assert events[0]["metadata"]["booking_type"] == "bundle"
            assert events[0]["metadata"]["plan_type"] == "Budget"
        finally:
            _delete_many("trips", {"trip_id": trip_id})
            _delete_many("bookings", {"trip_id": trip_id})
            _delete_many("analytics_events", {"metadata.trip_id": trip_id})
