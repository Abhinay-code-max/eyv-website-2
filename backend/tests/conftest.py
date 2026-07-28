"""Shared pytest helpers for the backend test suite.

seed_session/delete_session mirror the fixture pattern already proven in
test_trip_regenerate.py / test_rate_limit_quota.py / test_progressive_generation.py:
directly write matching users + user_sessions documents so a test file can
authenticate against a live backend without depending on a real login flow
or a hardcoded token string that happens to still exist in whatever DB the
suite is pointed at. Each login now inserts its own session (multi-session
support) rather than wiping the user's other sessions, so a captured token
no longer goes stale just because someone else logs in later - it still
expires after 7 days or on explicit logout/revoke, same as before.

user_sessions.session_token stores sha256(token), not the raw token (see
_hash_session_token in server.py) - hash_session_token() here is the same
algorithm, duplicated rather than imported from server.py so importing this
module doesn't force the full server.py import (Mongo client, required env
vars like WALLET_URL_SIGNING_SECRET, etc.) on test files that only need the
DB-seeding helpers.
"""
import asyncio
import hashlib
import os
from datetime import datetime, timezone, timedelta

from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')


def hash_session_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _db():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _run(coro):
    # asyncio.run, not get_event_loop().run_until_complete(...) - the latter
    # raises "There is no current event loop in thread" on Python 3.14's
    # tightened asyncio (see test_rate_limit_quota.py, which found this first).
    return asyncio.run(coro)


def seed_session(user_id, session_token, premium=False):
    """Write matching users + user_sessions documents so `session_token`
    authenticates as `user_id` against a live backend. Also clears any
    leftover daily generation quota for user_id so a prior test run's
    exhausted quota can't cause a spurious 429 here."""
    async def _do():
        db = _db()
        now = datetime.now(timezone.utc)
        user_doc = {
            "user_id": user_id, "email": f"{user_id}@example.com", "name": "Test",
            "created_at": now.isoformat(),
            "stripe_subscription_status": "active" if premium else "inactive",
        }
        if premium:
            user_doc["current_period_end"] = (now + timedelta(days=30)).isoformat()
        await db.users.update_one({"user_id": user_id}, {"$set": user_doc}, upsert=True)
        token_hash = hash_session_token(session_token)
        await db.user_sessions.update_one(
            {"session_token": token_hash},
            {"$set": {
                "session_token": token_hash, "user_id": user_id,
                "session_id": token_hash[:32],
                "expires_at": (now + timedelta(days=7)).isoformat(),
                "created_at": now.isoformat(),
            }},
            upsert=True,
        )
        await db.generation_quota.delete_many({"user_id": user_id})
    _run(_do())


def delete_session(user_id, session_token):
    async def _do():
        db = _db()
        await db.users.delete_many({"user_id": user_id})
        await db.user_sessions.delete_many({"session_token": hash_session_token(session_token)})
        await db.generation_quota.delete_many({"user_id": user_id})
    _run(_do())
