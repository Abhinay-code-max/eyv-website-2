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
import sys
import uuid
from datetime import datetime, timezone, timedelta

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")
os.environ.setdefault("WALLET_URL_SIGNING_SECRET", "test-wallet-secret")
os.environ.setdefault("INTERNAL_TICKET_API_TOKEN", "test-internal-token")
os.environ.setdefault("INTERNAL_ANALYTICS_API_TOKEN", "test-analytics-token")
os.environ.setdefault("JARVIS_QUEUE_API_TOKEN", "test-jarvis-token")
os.environ.setdefault("ADMIN_API_KEY", "test-master-admin-key-secret")
os.environ.setdefault("REVENUECAT_WEBHOOK_AUTH_KEY", "test-revenuecat-key")



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


# ─────────────────────────────────────────────────────────────────────────
# In-process fixtures (new) - the pattern above (real uvicorn process +
# `requests` + BASE_URL) is what every existing test file in this directory
# still uses and stays untouched. These fixtures are an additive, parallel
# path for new tests: FastAPI's TestClient talks to `server.app` directly
# over ASGI, in the same process, against the same real Mongo this file's
# helpers already write to - no subprocess, no port, no /health poll.
#
# `import server` is deliberately kept inside the fixture bodies rather than
# at module level - conftest.py is auto-loaded for every file under tests/,
# and server.py raises at import time if CORS_ORIGINS/WALLET_URL_SIGNING_SECRET
# aren't set (see server.py's _resolve_cors_origins/_resolve_wallet_download_secret).
# Fixtures are only evaluated when a test actually requests them, so a test
# file that only needs seed_session/delete_session above still never pays
# that import cost or those env-var requirements.
# ─────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def client():
    """In-process FastAPI TestClient - `with` form so startup/shutdown
    lifespan events actually run (index_service.ensure_indexes, the FX-rate
    warm-up, the booking-expiry scheduler), same as a real server boot."""
    from starlette.testclient import TestClient
    import server as server_module
    with TestClient(server_module.app) as c:
        yield c


@pytest.fixture()
def authed_client(client):
    """A real authenticated session, created in-process - not a hardcoded
    token. Seeds users/user_sessions the same way seed_session above does
    (same collections, same hashing), but with a fresh uuid4 user_id/token
    per test so tests never share or race over identity, and sets the
    session as a cookie on `client` (matching how the real frontend
    authenticates - see server._get_current_session, cookie checked before
    the Authorization-header fallback the older HTTP tests use).

    Yields (client, user_id) - most tests only need `client`, but the user_id
    is handy for asserting against DB state the test itself seeded."""
    user_id = f"test_inproc_{uuid.uuid4().hex[:12]}"
    token = f"test_inproc_token_{uuid.uuid4().hex}"
    seed_session(user_id, token)
    client.cookies.set("session_token", token)
    try:
        yield client, user_id
    finally:
        client.cookies.delete("session_token")
        delete_session(user_id, token)
