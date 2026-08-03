"""
Regression test for a real race condition between POST /api/webhook/stripe
(checkout.session.completed) and GET /api/payments/status/{session_id} - both
can independently decide a payment just turned "paid" and call
_process_successful_payment, which is NOT idempotent (rewards_service.award_points
unconditionally inserts a new rewards_transactions row and $incs the user's
balance every time it's called - there's no dedupe on reference_id).

Before the fix, both handlers did read-transaction -> check-payment_status-in-
Python -> write. That's a classic TOCTOU: if both requests read the
transaction while it's still "pending" before either one's write lands, both
proceed to call the (non-idempotent) side effects. The fix replaces the
plain update_one with an atomic find_one_and_update filtered on
payment_status != 'paid' (mirroring the pattern _process_expired_payment's
own update already used) - only whichever request's update Mongo actually
applies gets a non-None result back and is allowed to run the side effects.

This test drives both endpoints through the real ASGI app - httpx.AsyncClient
+ ASGITransport, not starlette's (synchronous) TestClient - specifically
because asyncio.gather()'ing two real requests is what lets them interleave
at their internal `await db....` points the same way two independent real
HTTP requests would. A sync TestClient can't do that; two sequential
.post()/.get() calls would never overlap.

Natural scheduling alone isn't a reliable way to *prove* the race, though:
the poll endpoint's get_current_user dependency does two DB round trips
before it even reads the transaction, while the webhook handler reads it
almost immediately - so left alone, the webhook request usually finishes
its entire read-decide-write-process sequence before the poll request has
even done its own read, and the poll request's early "already processed"
exit (payment_status already 'paid') then correctly short-circuits it with
no race in sight, regardless of whether the underlying fix is present. That
would make this test pass even against the buggy code for the wrong
reason. Instead, db.payment_transactions.find_one is wrapped with a small
rendezvous barrier (see _install_read_barrier) so both requests are forced
to complete their read of the transaction - both seeing the same still-
"pending" state - before either is allowed to proceed to its write. That's
the actual race window the bug lives in, reproduced deterministically
instead of by timing luck.
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

import httpx
import pytest
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

import server  # noqa: E402
import stripe  # noqa: E402

from conftest import seed_session, delete_session  # noqa: E402

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')


def _db():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _run(coro):
    return asyncio.run(coro)


class _FakeStripeSession:
    """Stand-in for the object stripe.checkout.Session.retrieve() returns -
    only the fields get_payment_status actually reads."""
    def __init__(self, payment_status, status, amount_total, currency, metadata):
        self.payment_status = payment_status
        self.status = status
        self.amount_total = amount_total
        self.currency = currency
        self.metadata = metadata


def _seed_transaction(session_id, user_id, metadata):
    async def _do():
        db = _db()
        await db.payment_transactions.insert_one({
            'session_id': session_id,
            'user_id': user_id,
            'amount': 999.0,
            'currency': 'usd',
            'description': 'Race-condition test subscription',
            'payment_type': 'subscription',
            'metadata': metadata,
            'payment_status': 'pending',
            'status': 'initiated',
            'points_used': 0,
            'created_at': datetime.now(timezone.utc).isoformat(),
        })
        await db.user_rewards.delete_many({'user_id': user_id})
    _run(_do())


def _cleanup(session_id, user_id):
    async def _do():
        db = _db()
        await db.payment_transactions.delete_many({'session_id': session_id})
        await db.user_rewards.delete_many({'user_id': user_id})
        await db.rewards_transactions.delete_many({'user_id': user_id})
    _run(_do())


def _install_read_barrier(monkeypatch, session_id):
    """Wrap AsyncIOMotorCollection.find_one (patched on the *class*, not a
    specific db.payment_transactions instance - motor/pymongo hand back a
    fresh Collection wrapper on every `db.payment_transactions` attribute
    access, so an instance-level patch would silently miss whichever of the
    two request handlers happens to grab a different wrapper) so the first
    two calls looking up `session_id` in the payment_transactions collection
    rendezvous before either returns. Both the webhook handler's and the
    poll handler's find_one land in the barrier, and neither is released
    until both have arrived - guaranteeing both read the same still-
    "pending" transaction, deterministically reproducing the race window
    instead of hoping real request scheduling happens to line up."""
    from motor.motor_asyncio import AsyncIOMotorCollection
    original_find_one = AsyncIOMotorCollection.find_one
    arrived = 0
    release = asyncio.Event()
    lock = asyncio.Lock()

    async def _gated_find_one(self, query, *args, **kwargs):
        nonlocal arrived
        result = await original_find_one(self, query, *args, **kwargs)
        if self.name == 'payment_transactions' and isinstance(query, dict) and query.get('session_id') == session_id:
            async with lock:
                arrived += 1
                first = arrived == 1
            if first:
                await asyncio.wait_for(release.wait(), timeout=5)
            else:
                release.set()
        return result

    monkeypatch.setattr(AsyncIOMotorCollection, "find_one", _gated_find_one)


def test_concurrent_webhook_and_poll_apply_payment_exactly_once(monkeypatch):
    user_id = f"test_race_user_{uuid.uuid4().hex[:10]}"
    session_token = f"test_race_token_{uuid.uuid4().hex}"
    session_id = f"cs_test_race_{uuid.uuid4().hex[:16]}"
    metadata = {'payment_type': 'subscription', 'user_id': user_id, 'package_id': 'monthly'}

    seed_session(user_id, session_token)
    _seed_transaction(session_id, user_id, metadata)

    monkeypatch.setattr(stripe, "api_key", "sk_test_fake_for_race_test")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_fake_for_race_test")

    fake_event = {
        'type': 'checkout.session.completed',
        'data': {'object': {'id': session_id}},
    }
    monkeypatch.setattr(stripe.Webhook, "construct_event", lambda payload, sig_header, secret: fake_event)

    def _fake_retrieve(sid, **kw):
        return _FakeStripeSession('paid', 'complete', 99900, 'usd', metadata)

    monkeypatch.setattr(stripe.checkout.Session, "retrieve", _fake_retrieve)
    _install_read_barrier(monkeypatch, session_id)

    async def _scenario():
        transport = httpx.ASGITransport(app=server.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            ac.cookies.set("session_token", session_token)
            webhook_call = ac.post(
                "/api/webhook/stripe",
                content=b'{"type": "checkout.session.completed"}',
                headers={"Stripe-Signature": "test-signature"},
            )
            poll_call = ac.get(f"/api/payments/status/{session_id}")
            return await asyncio.gather(webhook_call, poll_call)

    try:
        webhook_resp, poll_resp = _run(_scenario())

        assert webhook_resp.status_code == 200, webhook_resp.text
        assert poll_resp.status_code == 200, poll_resp.text

        async def _final_state():
            db = _db()
            transaction = await db.payment_transactions.find_one({'session_id': session_id}, {'_id': 0})
            rewards_txns = await db.rewards_transactions.find({'user_id': user_id}, {'_id': 0}).to_list(10)
            user_rewards = await db.user_rewards.find_one({'user_id': user_id}, {'_id': 0})
            return transaction, rewards_txns, user_rewards

        transaction, rewards_txns, user_rewards = _run(_final_state())

        # The transaction itself must have settled into "paid" exactly (not
        # left "pending", not corrupted by two interleaved writes).
        assert transaction['payment_status'] == 'paid'
        assert transaction['status'] == 'completed'

        # The core assertion: exactly ONE rewards_transactions row for this
        # payment, not two. Before the fix this reliably comes back as 2 -
        # both the webhook and the poll call _process_successful_payment ->
        # rewards_service.award_points, and award_points has no dedupe on
        # reference_id (session_id here), so a second call just inserts a
        # second row and $incs the balance again.
        assert len(rewards_txns) == 1, (
            f"expected exactly 1 rewards_transactions row for session {session_id}, "
            f"got {len(rewards_txns)} - payment was double-processed"
        )
        assert rewards_txns[0]['reference_id'] == session_id

        # available_points/lifetime_points must reflect a single award, not
        # double. premium_subscription = 1000 base points, Explorer tier
        # (fresh user, 0 lifetime points) multiplier = 1.0.
        assert user_rewards['lifetime_points'] == 1000
        assert user_rewards['available_points'] == 1000
    finally:
        _cleanup(session_id, user_id)
        delete_session(user_id, session_token)
