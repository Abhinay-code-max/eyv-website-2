"""
Regression tests for two booking-hygiene fixes in server.py:

1. cancel_booking (DELETE /api/bookings/{id}) now guards on booking status.
   Before the fix it unconditionally flipped ANY booking (including an
   already-paid, "confirmed" one) to "cancelled" with no refund of any
   kind - the customer's money stayed charged while the record claimed a
   clean cancellation. There is no Stripe refund mechanism anywhere in
   this codebase (checked directly - no stripe.Refund/create_refund
   usage), so the fix blocks cancelling a "confirmed" booking outright
   with a clear 400 rather than silently "succeeding" with no money
   movement. Only bookings that were never actually charged
   ("pending_payment", "payment_failed") remain cancellable via this
   simple status-flip path.

2. create_booking and book_trip_plan no longer stamp a freshly-created,
   not-yet-paid booking with payment_status: "mock_paid" - a value that
   reads as already paid despite no payment having happened. They now
   use "pending", matching payment_transactions' own not-yet-paid
   convention, only ever promoted to "paid" by a real
   _process_successful_payment call.

Bookings for the cancel-guard tests are seeded directly into db.bookings
(status is all that matters there, not how the booking was created) -
same pattern as test_rewards_race.py's _seed_booking. The payment_status
tests instead hit the real creation endpoints (POST /api/bookings, POST
/api/trips/{id}/book/{plan_type}) directly, since those are the exact
code paths being fixed.
"""
import os
import sys
import uuid
from datetime import datetime, timezone

import asyncio
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from conftest import seed_session, delete_session  # noqa: E402

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'http://localhost:8001').rstrip('/')
MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')


def _db():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _run(coro):
    return asyncio.run(coro)


def _seed_booking(user_id, booking_id, status, **extra):
    async def _do():
        db = _db()
        doc = {
            'booking_id': booking_id,
            'confirmation_code': f"EYV-{uuid.uuid4().hex[:8].upper()}",
            'user_id': user_id,
            'booking_type': 'flight',
            'item_data': {},
            'traveler_details': {},
            'total_amount': 199.0,
            'currency': 'usd',
            'status': status,
            'created_at': datetime.now(timezone.utc),
        }
        doc.update(extra)
        await db.bookings.insert_one(doc)
    _run(_do())


def _get_booking(booking_id):
    async def _do():
        db = _db()
        return await db.bookings.find_one({'booking_id': booking_id}, {'_id': 0})
    return _run(_do())


def _seed_bookable_trip(trip_id, user_id):
    async def _do():
        db = _db()
        now = datetime.now(timezone.utc).isoformat()
        plan = {
            "plan_type": "Premium",
            "status": "ready",
            "currency": "INR", "currency_symbol": "₹",
            "itinerary": {},
            "cost_breakdown": {"transportation": 5000, "accommodation": 3000, "food": 0,
                               "activities": 0, "miscellaneous": 0},
            "total_cost": 8000,
            "highlights": [], "budget_tips": [],
            "anchor_pricing": {
                "is_train": False, "is_cruise": False, "is_road": False,
                "flight_price": 5000, "flight_airline": "Test Air", "flight_number": "TA100",
                "flight_dep_time": "10:00", "flight_arr_time": "12:00", "flight_duration": "2h",
                "flight_stops": 0,
                "hotel_name": "Test Hotel", "hotel_price_per_night": 3000, "hotel_stars": 4,
            },
        }
        await db.trips.update_one(
            {"trip_id": trip_id},
            {"$set": {
                "trip_id": trip_id, "user_id": user_id, "trip_name": "Bookable Test Trip",
                "preferences": {
                    "destination": "Goa", "starting_location": "Mumbai",
                    "departure_date": "2027-02-01", "return_date": "2027-02-04",
                    "transportation": "flight", "currency": "INR",
                    "num_travelers": 1, "adults": 1, "children": 0, "seniors": 0,
                    "budget_level": "Premium", "accommodation": ["hotel"], "interests": [],
                    "trip_type": "leisure",
                },
                "plans": [plan],
                "created_at": now, "updated_at": now,
            }},
            upsert=True,
        )
    _run(_do())


def _cleanup(user_id=None, booking_ids=(), trip_ids=()):
    async def _do():
        db = _db()
        if booking_ids:
            await db.bookings.delete_many({'booking_id': {'$in': list(booking_ids)}})
        if trip_ids:
            await db.trips.delete_many({'trip_id': {'$in': list(trip_ids)}})
    _run(_do())


class _Session:
    """Self-seeded user+session per test, same idiom as test_rewards_race.py."""

    def __enter__(self):
        self.user_id = f"test_booking_hygiene_{uuid.uuid4().hex[:10]}"
        self.token = f"test_booking_hygiene_token_{uuid.uuid4().hex}"
        self.headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        seed_session(self.user_id, self.token)
        return self

    def __exit__(self, *exc):
        delete_session(self.user_id, self.token)


# ═══════════════ Fix #1: cancel_booking guarded by status ═══════════════

def test_cancel_confirmed_booking_is_blocked_not_silently_succeeded():
    """The core failure mode: a paid/confirmed booking must not be
    cancellable through the no-refund status-flip path. Before the fix this
    returned 200 and flipped status to "cancelled" with zero money movement
    - the customer stayed charged while the record claimed otherwise."""
    with _Session() as s:
        booking_id = f"BK_CONFIRMED_{uuid.uuid4().hex[:10]}"
        _seed_booking(s.user_id, booking_id, status="confirmed", payment_status="paid",
                      paid_at=datetime.now(timezone.utc))
        try:
            r = requests.delete(f"{BASE_URL}/api/bookings/{booking_id}", headers=s.headers)
            assert r.status_code == 400, r.text
            assert "paid" in r.json()["detail"].lower() or "confirmed" in r.json()["detail"].lower()

            booking = _get_booking(booking_id)
            assert booking["status"] == "confirmed", (
                "a blocked cancel must not have mutated status at all"
            )
            assert booking.get("cancelled_at") is None
        finally:
            _cleanup(booking_ids=[booking_id])


def test_cancel_pending_payment_booking_succeeds():
    """Control case: a booking that was never actually charged remains
    cancellable via the simple status-flip path - the guard must not be
    overly broad."""
    with _Session() as s:
        booking_id = f"BK_PENDING_{uuid.uuid4().hex[:10]}"
        _seed_booking(s.user_id, booking_id, status="pending_payment", payment_status="pending")
        try:
            r = requests.delete(f"{BASE_URL}/api/bookings/{booking_id}", headers=s.headers)
            assert r.status_code == 200, r.text

            booking = _get_booking(booking_id)
            assert booking["status"] == "cancelled"
            assert booking.get("cancelled_at") is not None
        finally:
            _cleanup(booking_ids=[booking_id])


def test_cancel_payment_failed_booking_succeeds():
    """A booking whose payment already failed was never charged either -
    also cancellable via the simple path (pure record cleanup, no money
    at stake)."""
    with _Session() as s:
        booking_id = f"BK_FAILED_{uuid.uuid4().hex[:10]}"
        _seed_booking(s.user_id, booking_id, status="payment_failed", payment_status="pending")
        try:
            r = requests.delete(f"{BASE_URL}/api/bookings/{booking_id}", headers=s.headers)
            assert r.status_code == 200, r.text
            assert _get_booking(booking_id)["status"] == "cancelled"
        finally:
            _cleanup(booking_ids=[booking_id])


def test_cancel_already_cancelled_booking_is_rejected_not_silently_reapplied():
    """An already-cancelled booking falls outside the cancellable-status
    set too - re-cancelling should be rejected with a clear error, not
    silently re-applied (which would also just be a no-op success masking
    that nothing changed)."""
    with _Session() as s:
        booking_id = f"BK_ALREADY_CANCELLED_{uuid.uuid4().hex[:10]}"
        _seed_booking(s.user_id, booking_id, status="cancelled")
        try:
            r = requests.delete(f"{BASE_URL}/api/bookings/{booking_id}", headers=s.headers)
            assert r.status_code == 400, r.text
        finally:
            _cleanup(booking_ids=[booking_id])


def test_cancel_nonexistent_booking_404s():
    with _Session() as s:
        r = requests.delete(f"{BASE_URL}/api/bookings/BK_DOES_NOT_EXIST", headers=s.headers)
        assert r.status_code == 404, r.text


def test_cancel_another_users_booking_404s():
    """Ownership scoping still applies identically regardless of the new
    status guard - a booking that exists but belongs to someone else must
    404, not 400 (which would leak that the booking_id is valid)."""
    with _Session() as owner, _Session() as attacker:
        booking_id = f"BK_OWNED_{uuid.uuid4().hex[:10]}"
        _seed_booking(owner.user_id, booking_id, status="pending_payment")
        try:
            r = requests.delete(f"{BASE_URL}/api/bookings/{booking_id}", headers=attacker.headers)
            assert r.status_code == 404, r.text
            assert _get_booking(booking_id)["status"] == "pending_payment"
        finally:
            _cleanup(booking_ids=[booking_id])


# ═══════════════ Fix #2: no "mock_paid" stamp on creation ═══════════════

def test_create_booking_never_reads_as_already_paid():
    """POST /api/bookings (single-item flight/hotel booking) - a freshly
    created booking must never carry a payment_status that reads as
    already-paid ("paid" or the old hardcoded "mock_paid") before any
    Stripe payment has actually happened."""
    with _Session() as s:
        search_payload = {"origin": "JFK", "destination": "Paris",
                          "departure_date": "2026-03-01", "return_date": "2026-03-08",
                          "travelers": 1}
        r = requests.post(f"{BASE_URL}/api/search/flights", json=search_payload, headers=s.headers)
        assert r.status_code == 200, r.text
        flight = r.json()["flights"][0]

        payload = {
            "booking_type": "flight",
            "item_id": flight["item_id"],
            "item_data": {"id": flight["id"], "airline": flight["airline"]},
        }
        r = requests.post(f"{BASE_URL}/api/bookings", json=payload, headers=s.headers)
        assert r.status_code == 200, r.text
        booking = r.json()
        try:
            assert booking["status"] == "pending_payment"
            assert booking["payment_status"] not in ("paid", "mock_paid"), (
                f"freshly created booking must not read as already-paid, got "
                f"payment_status={booking['payment_status']!r}"
            )
            assert booking["payment_status"] == "pending"
        finally:
            _cleanup(booking_ids=[booking["booking_id"]])


def test_book_trip_plan_never_reads_as_already_paid():
    """POST /trips/{id}/book/{plan_type} ("Book this Plan" bundle) - same
    guarantee for the bundled-booking creation path, which had its own
    independent "mock_paid" stamp."""
    with _Session() as s:
        trip_id = f"test_booking_hygiene_trip_{uuid.uuid4().hex[:10]}"
        _seed_bookable_trip(trip_id, s.user_id)
        try:
            r = requests.post(f"{BASE_URL}/api/trips/{trip_id}/book/Premium", headers=s.headers)
            assert r.status_code == 200, r.text
            booking = r.json()
            try:
                assert booking["status"] == "pending_payment"
                assert booking["payment_status"] not in ("paid", "mock_paid"), (
                    f"freshly created bundle booking must not read as already-paid, got "
                    f"payment_status={booking['payment_status']!r}"
                )
                assert booking["payment_status"] == "pending"
            finally:
                _cleanup(booking_ids=[booking["booking_id"]])
        finally:
            _cleanup(trip_ids=[trip_id])
