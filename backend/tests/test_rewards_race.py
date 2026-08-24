"""
Regression tests for the rewards-points money-path race fixes:

1. create_checkout (server.py) atomically reserving points via
   rewards_service.reserve_points instead of check-then-defer-to-payment-
   success. Before the fix, two concurrent checkouts against the same
   balance could both pass an application-level "available_points >=
   use_points" check before either write landed, then both proceed to
   spend the same points twice over.

2. rewards_service.redeem_points itself, same TOCTOU shape, same fix
   shape (filtered $inc instead of read-check-write), exercised via
   POST /api/rewards/redeem.

3. server._finalize_or_alert_points_redemption (extracted from
   _process_successful_payment) no longer silently swallowing a lost
   points reservation - the old code was
   `except ValueError: pass  # Already validated at checkout`, which
   would let a user keep both the Stripe discount AND their points back
   if the reservation was refunded out from under a very-late payment
   success (e.g. by rewards_service.refund_stale_reserved_points's sweep,
   or a revived Stripe session racing _process_expired_payment).

Tests 1 and 2 fire real concurrent HTTP requests (via a thread pool, not
asyncio.gather) against the already-running live backend
(BASE_URL/requests - the same pattern test_rewards_payments.py and
test_rate_limit_quota.py already use), rather than driving requests
in-process through server.app directly the way
test_payment_webhook_race.py does. That in-process approach was tried
first here too, but touching server.py's module-level `db` (a shared
Motor client) from more than one asyncio.run() call in the same pytest
process reproducibly hits "RuntimeError: Event loop is closed" on this
stack (Python 3.14 + Windows + motor) - test_rate_limit_quota.py's own
docstring documents hitting the exact same wall and choosing the live-
server route for the same reason. Real concurrent requests against a
live async server still genuinely interleave at the server's own event
loop (that's the whole point of it being async), so this still forces
real overlap - it just does so without the test process itself ever
touching server.py's shared client.

Test 3 doesn't touch server.py's global `db` or Stripe at all: the
finalize-or-alert logic was extracted into
server._finalize_or_alert_points_redemption specifically so it takes `db`
as an explicit parameter and can be called directly against a
freshly-constructed Motor client (this file's own _db()), sidestepping
the shared-client issue entirely rather than needing Stripe-response
mocking through the live server (which can't simulate a synthetic,
never-really-created Stripe session reporting "paid").
"""
import concurrent.futures
import os
import sys
import uuid
from datetime import datetime, timezone

import asyncio
import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

import server  # noqa: E402
import sentry_sdk  # noqa: E402
from services import rewards_service  # noqa: E402

from conftest import seed_session, delete_session  # noqa: E402

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'http://localhost:8001').rstrip('/')
MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')


def _db():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _run(coro):
    return asyncio.run(coro)


def _seed_points(user_id, available_points):
    async def _do():
        db = _db()
        await db.user_rewards.update_one(
            {'user_id': user_id},
            {'$set': {
                'user_id': user_id,
                'available_points': available_points,
                'lifetime_points': available_points,
                'updated_at': datetime.now(timezone.utc),
            }},
            upsert=True,
        )
    _run(_do())


def _seed_booking(user_id, booking_id, total_amount, currency='usd'):
    async def _do():
        db = _db()
        await db.bookings.insert_one({
            'booking_id': booking_id,
            'user_id': user_id,
            'booking_type': 'flight',
            'total_amount': total_amount,
            'currency': currency,
            'status': 'pending_payment',
            'created_at': datetime.now(timezone.utc),
        })
    _run(_do())


def _cleanup(user_id, booking_ids=(), session_ids=()):
    async def _do():
        db = _db()
        await db.user_rewards.delete_many({'user_id': user_id})
        await db.rewards_transactions.delete_many({'user_id': user_id})
        if booking_ids:
            await db.bookings.delete_many({'booking_id': {'$in': list(booking_ids)}})
        if session_ids:
            await db.payment_transactions.delete_many({'session_id': {'$in': list(session_ids)}})
    _run(_do())


# ═══════════════ Fix #1: atomic reserve at checkout ═══════════════

def test_concurrent_checkout_reservation_only_one_succeeds():
    """Two bookings, one shared 100-point balance, two concurrent checkout
    requests each asking to spend 100 points (200 combined > 100
    available). Exactly one must succeed; the other must fail cleanly with
    "Insufficient points", never both succeeding and never leaving
    available_points negative."""
    user_id = f"test_race_checkout_{uuid.uuid4().hex[:10]}"
    session_token = f"test_race_checkout_token_{uuid.uuid4().hex}"
    booking_id_a = f"BK_RACE_A_{uuid.uuid4().hex[:10]}"
    booking_id_b = f"BK_RACE_B_{uuid.uuid4().hex[:10]}"
    headers = {"Authorization": f"Bearer {session_token}", "Content-Type": "application/json"}

    seed_session(user_id, session_token)
    _seed_points(user_id, 100)
    _seed_booking(user_id, booking_id_a, total_amount=50.0)
    _seed_booking(user_id, booking_id_b, total_amount=50.0)

    def _checkout(booking_id):
        return requests.post(
            f"{BASE_URL}/api/payments/checkout",
            json={"booking_id": booking_id, "origin_url": "https://example.com", "use_points": 100},
            headers=headers,
        )

    issued_session_ids = []
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            fut_a = pool.submit(_checkout, booking_id_a)
            fut_b = pool.submit(_checkout, booking_id_b)
            resp_a = fut_a.result(timeout=30)
            resp_b = fut_b.result(timeout=30)

        for r in (resp_a, resp_b):
            if r.status_code == 200:
                issued_session_ids.append(r.json()["session_id"])

        statuses = sorted([resp_a.status_code, resp_b.status_code])
        assert statuses == [200, 400], (
            f"expected exactly one 200 and one 400, got {resp_a.status_code} and "
            f"{resp_b.status_code} - {resp_a.text} / {resp_b.text}"
        )
        failed_resp = resp_a if resp_a.status_code == 400 else resp_b
        assert "insufficient" in failed_resp.json()["detail"].lower()

        async def _final_balance():
            db = _db()
            return await db.user_rewards.find_one({'user_id': user_id}, {'_id': 0})
        rewards = _run(_final_balance())

        # Exactly one reservation of 100 points landed - not zero (both
        # somehow rejected), not negative (both somehow succeeded).
        assert rewards['available_points'] == 0, (
            f"expected exactly one 100-point reservation to land (balance 0), got "
            f"{rewards['available_points']} - "
            f"{'double-spend' if rewards['available_points'] < 0 else 'both rejected'}"
        )
    finally:
        _cleanup(user_id, booking_ids=[booking_id_a, booking_id_b], session_ids=issued_session_ids)
        delete_session(user_id, session_token)


# ═══════════════ Fix #3: redeem_points atomic rewrite ═══════════════

def test_concurrent_redeem_points_only_one_succeeds():
    """Same race, direct /api/rewards/redeem endpoint (not checkout-tied) -
    covers rewards_service.redeem_points' own atomic rewrite independently
    of the checkout-reservation flow. 100 available, two concurrent
    redeem-100 requests - exactly one must succeed."""
    user_id = f"test_race_redeem_{uuid.uuid4().hex[:10]}"
    session_token = f"test_race_redeem_token_{uuid.uuid4().hex}"
    headers = {"Authorization": f"Bearer {session_token}", "Content-Type": "application/json"}

    seed_session(user_id, session_token)
    _seed_points(user_id, 100)

    def _redeem():
        return requests.post(f"{BASE_URL}/api/rewards/redeem", json={"points": 100}, headers=headers)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            fut_a = pool.submit(_redeem)
            fut_b = pool.submit(_redeem)
            resp_a = fut_a.result(timeout=30)
            resp_b = fut_b.result(timeout=30)

        statuses = sorted([resp_a.status_code, resp_b.status_code])
        assert statuses == [200, 400], (
            f"expected exactly one 200 and one 400, got {resp_a.status_code} and "
            f"{resp_b.status_code} - {resp_a.text} / {resp_b.text}"
        )

        async def _final_state():
            db = _db()
            rewards = await db.user_rewards.find_one({'user_id': user_id}, {'_id': 0})
            txns = await db.rewards_transactions.find({'user_id': user_id}, {'_id': 0}).to_list(10)
            return rewards, txns
        rewards, txns = _run(_final_state())

        assert rewards['available_points'] == 0, (
            f"expected exactly one 100-point redemption to land (balance 0), got "
            f"{rewards['available_points']}"
        )
        # Exactly one rewards_transactions row - the rejected call must not
        # have left a stray row despite losing the race.
        assert len(txns) == 1
    finally:
        _cleanup(user_id)
        delete_session(user_id, session_token)


def test_direct_concurrent_redeem_points_function_only_one_succeeds():
    """Direct service-level concurrency test: calls rewards_service.redeem_points
    concurrently from two asyncio tasks against a fresh Motor client.
    With an initial balance of 150 points and two concurrent redemptions of 100 points
    (total 200 > 150), exactly one coroutine must succeed and one must raise ValueError('Insufficient points').
    The final available_points must be 50, and exactly 1 transaction must be recorded."""
    user_id = f"test_direct_race_redeem_{uuid.uuid4().hex[:10]}"
    _seed_points(user_id, 150)

    async def _concurrent_redeem():
        db = _db()
        results = []
        errors = []

        async def _call():
            try:
                res = await rewards_service.redeem_points(db, user_id, 100)
                results.append(res)
            except ValueError as e:
                errors.append(e)

        await asyncio.gather(_call(), _call())
        return results, errors

    try:
        results, errors = _run(_concurrent_redeem())
        assert len(results) == 1, f"Expected exactly 1 successful redemption, got {len(results)}"
        assert len(errors) == 1, f"Expected exactly 1 error, got {len(errors)}"
        assert "insufficient" in str(errors[0]).lower()

        async def _final_state():
            db = _db()
            rewards = await db.user_rewards.find_one({'user_id': user_id}, {'_id': 0})
            txns = await db.rewards_transactions.find({'user_id': user_id}, {'_id': 0}).to_list(10)
            return rewards, txns

        rewards, txns = _run(_final_state())
        assert rewards['available_points'] == 50
        assert len(txns) == 1
        assert txns[0]['points'] == -100
    finally:
        _cleanup(user_id)


# ═══════════════ Fix #2: no silent swallow on lost reservation ═══════════════

def test_late_payment_success_after_stale_refund_is_not_silently_swallowed(monkeypatch, caplog):
    """Simulates the exact edge case fix #2 closes: a checkout's points
    reservation was already refunded (points_reservation_status flipped to
    'refunded' - as rewards_service.refund_stale_reserved_points's sweep or
    a revived-session _process_expired_payment would do), and *then* the
    payment is confirmed as genuinely paid - the real-world shape of this
    race, and the same "money received always wins" scenario
    _process_expired_payment's own docstring describes for booking status.

    Calls server._finalize_or_alert_points_redemption directly against a
    freshly-constructed Motor client (this file's own _db()) rather than
    driving it through server.app/server.db - see this file's module
    docstring for why. sentry_sdk.capture_exception and the logging module
    are plain synchronous Python, not event-loop-bound, so monkeypatching/
    caplog work identically either way.

    Before the fix, the lost reservation hit `except ValueError: pass  #
    Already validated at checkout` and disappeared with no trace, leaving
    the user with both the Stripe discount and their points back. After
    the fix, this must be logged and reported to Sentry - not silently
    ignored - and must NOT finalize a rewards_transactions row (the
    reservation is gone; there is nothing valid left to finalize)."""
    import logging

    user_id = f"test_late_success_{uuid.uuid4().hex[:10]}"
    booking_id = f"BK_LATE_{uuid.uuid4().hex[:10]}"
    session_id = f"cs_test_late_{uuid.uuid4().hex[:16]}"
    points_used = 100

    async def _seed():
        db = _db()
        await db.payment_transactions.insert_one({
            'session_id': session_id,
            'user_id': user_id,
            'amount': 49.0,
            'currency': 'usd',
            'description': f"Booking {booking_id}",
            'payment_type': 'booking',
            'metadata': {
                'user_id': user_id,
                'booking_id': booking_id,
                'payment_type': 'booking',
                'points_used': str(points_used),
            },
            'payment_status': 'paid',
            'status': 'completed',
            'points_used': points_used,
            'points_reservation_status': 'refunded',  # already given back
            'created_at': datetime.now(timezone.utc),
        })
        return await db.payment_transactions.find_one({'session_id': session_id}, {'_id': 0})
    transaction = _run(_seed())

    captured = []
    monkeypatch.setattr(sentry_sdk, "capture_exception", lambda exc, **kw: captured.append((exc, kw)))

    try:
        with caplog.at_level(logging.ERROR):
            _run(server._finalize_or_alert_points_redemption(_db(), transaction, user_id, points_used, booking_id))

        # Must have surfaced, not vanished.
        assert captured, "expected sentry_sdk.capture_exception to be called - the failure was silently swallowed"
        assert captured[0][1].get("tags", {}).get("area") == "rewards_points_finalize"
        assert any("reconciliation" in rec.message.lower() or "reservation" in rec.message.lower()
                   for rec in caplog.records), "expected an ERROR log describing the lost reservation"

        # Must not have finalized a transaction for a reservation that's gone.
        async def _final_state():
            db = _db()
            txns = await db.rewards_transactions.find({'user_id': user_id}, {'_id': 0}).to_list(10)
            txn = await db.payment_transactions.find_one({'session_id': session_id}, {'_id': 0})
            return txns, txn
        txns, txn = _run(_final_state())
        assert txns == [], "must not record a redeem transaction for a reservation that was already refunded"
        assert txn['points_reservation_status'] == 'refunded', "must not overwrite the refunded status to finalized"
    finally:
        _cleanup(user_id, session_ids=[session_id])


def test_reservation_still_held_at_payment_success_finalizes_normally(caplog):
    """Control case for the test above - when the reservation is still
    validly "reserved" (the normal path), finalizing must succeed quietly:
    record exactly one rewards_transactions row, flip the status to
    "finalized", and raise no alert."""
    import logging

    user_id = f"test_normal_finalize_{uuid.uuid4().hex[:10]}"
    booking_id = f"BK_NORMAL_{uuid.uuid4().hex[:10]}"
    session_id = f"cs_test_normal_{uuid.uuid4().hex[:16]}"
    points_used = 100

    async def _seed():
        db = _db()
        await db.payment_transactions.insert_one({
            'session_id': session_id,
            'user_id': user_id,
            'amount': 49.0,
            'currency': 'usd',
            'payment_type': 'booking',
            'metadata': {'user_id': user_id, 'booking_id': booking_id, 'payment_type': 'booking',
                         'points_used': str(points_used)},
            'payment_status': 'paid',
            'status': 'completed',
            'points_used': points_used,
            'points_reservation_status': 'reserved',
            'created_at': datetime.now(timezone.utc),
        })
        return await db.payment_transactions.find_one({'session_id': session_id}, {'_id': 0})
    transaction = _run(_seed())

    try:
        with caplog.at_level(logging.ERROR):
            _run(server._finalize_or_alert_points_redemption(_db(), transaction, user_id, points_used, booking_id))

        assert not any(rec.levelno >= logging.ERROR for rec in caplog.records), \
            "finalizing a still-valid reservation must not log an error"

        async def _final_state():
            db = _db()
            txns = await db.rewards_transactions.find({'user_id': user_id}, {'_id': 0}).to_list(10)
            txn = await db.payment_transactions.find_one({'session_id': session_id}, {'_id': 0})
            return txns, txn
        txns, txn = _run(_final_state())
        assert len(txns) == 1
        assert txns[0]['reference_id'] == booking_id
        assert txn['points_reservation_status'] == 'finalized'
    finally:
        _cleanup(user_id, session_ids=[session_id])


def test_concurrent_first_time_user_get_or_create_and_redeem_creates_single_document():
    """Concurrency test for a brand-new user with NO existing user_rewards document:
    Runs simultaneous get_or_create_rewards and redeem_points calls via asyncio.gather.
    Confirms:
    1. Only ONE user_rewards document is created for user_id (no DuplicateKeyError crash, no duplicate docs).
    2. Document correctly initializes at 0 points.
    3. Both redeem calls cleanly handle the 0 balance (both raise ValueError('Insufficient points') without crashing or corrupting data)."""
    user_id = f"test_brand_new_user_{uuid.uuid4().hex[:10]}"

    async def _test():
        db = _db()
        # Verify document does NOT exist initially
        initial = await db.user_rewards.find_one({'user_id': user_id})
        assert initial is None

        # Two concurrent calls to get_or_create_rewards for a brand-new user
        res1, res2 = await asyncio.gather(
            rewards_service.get_or_create_rewards(db, user_id),
            rewards_service.get_or_create_rewards(db, user_id),
        )
        assert res1['user_id'] == user_id
        assert res2['user_id'] == user_id

        # Verify exactly ONE document exists in DB
        docs = await db.user_rewards.find({'user_id': user_id}).to_list(10)
        assert len(docs) == 1

        # Now test concurrent redeem_points for a brand-new user with 0 points
        errors = []
        async def _try_redeem():
            try:
                await rewards_service.redeem_points(db, user_id, 100)
            except ValueError as e:
                errors.append(e)

        await asyncio.gather(_try_redeem(), _try_redeem())
        assert len(errors) == 2
        assert all("insufficient" in str(err).lower() for err in errors)

        # Still exactly ONE document with 0 points
        docs = await db.user_rewards.find({'user_id': user_id}).to_list(10)
        assert len(docs) == 1
        assert docs[0]['available_points'] == 0

    try:
        _run(_test())
    finally:
        _cleanup(user_id)
