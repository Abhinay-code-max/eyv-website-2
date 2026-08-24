"""
Auth architecture security fixes: multi-session login, session-token
hashing, session list/revoke, and wallet download-URL signing/expiry.

Imports `server` directly (like test_rate_limit_quota.py /
test_trip_regenerate.py) so a few tests can reach internal helpers
(_hash_session_token, _sign_wallet_download) that a pure HTTP client has no
legitimate way to call - e.g. crafting a correctly-signed-but-already-
expired download link without sleeping in real time for the TTL to pass.
"""
import asyncio
import concurrent.futures
import io
import os
import sys
import time
import uuid

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

import server  # noqa: E402

from conftest import seed_session, delete_session  # noqa: E402

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'http://localhost:8001').rstrip('/')
MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')


def _db():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _run(coro):
    return asyncio.run(coro)


# ---------- Token hashing ----------

def test_seeded_session_stores_hash_not_plaintext():
    user_id = "test_authsec_hash_user"
    token = f"test_authsec_hash_token_{uuid.uuid4().hex[:8]}"
    seed_session(user_id, token)
    try:
        async def _fetch():
            return await _db().user_sessions.find_one({"user_id": user_id}, {"_id": 0})
        doc = _run(_fetch())
        assert doc is not None
        assert doc["session_token"] != token
        assert doc["session_token"] == server._hash_session_token(token)
        # The raw token must still authenticate via the normal lookup path,
        # even though only its hash is stored.
        r = requests.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
    finally:
        delete_session(user_id, token)


# ---------- Multi-session login (via the real /api/auth/session flow) ----------

def _seed_oauth_ticket(email, name="Multi Session Test"):
    ticket = uuid.uuid4().hex

    async def _do():
        await _db().oauth_tickets.insert_one({
            "ticket": ticket, "email": email, "name": name, "picture": None,
            "created_at": server.datetime.now(server.timezone.utc).isoformat(),
        })
    _run(_do())
    return ticket


def test_login_twice_keeps_both_sessions():
    """Logging in a second time (e.g. a different device) must not revoke
    the first session - server.py's exchange_session used to delete_many
    all of the user's sessions before inserting the new one."""
    email = f"multisession_{uuid.uuid4().hex[:10]}@example.com"
    ticket_a = _seed_oauth_ticket(email)
    ticket_b = _seed_oauth_ticket(email)

    r_a = requests.post(f"{BASE_URL}/api/auth/session", json={"session_id": ticket_a})
    assert r_a.status_code == 200, r_a.text
    token_a = r_a.cookies.get("session_token")
    user_id = r_a.json()["user"]["user_id"]

    r_b = requests.post(f"{BASE_URL}/api/auth/session", json={"session_id": ticket_b})
    assert r_b.status_code == 200, r_b.text
    token_b = r_b.cookies.get("session_token")

    assert token_a and token_b and token_a != token_b

    try:
        # Both tokens must still authenticate - logging in as token_b must
        # not have invalidated token_a.
        me_a = requests.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {token_a}"})
        me_b = requests.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {token_b}"})
        assert me_a.status_code == 200, me_a.text
        assert me_b.status_code == 200, me_b.text

        async def _count():
            return await _db().user_sessions.count_documents({"user_id": user_id})
        assert _run(_count()) == 2
    finally:
        async def _cleanup():
            db = _db()
            await db.users.delete_many({"user_id": user_id})
            await db.user_sessions.delete_many({"user_id": user_id})
        _run(_cleanup())


def test_exchange_session_signals_new_and_returning_users():
    """exchange_session must explicitly return is_new_user: true for brand-new accounts
    and is_new_user: false for existing returning accounts."""
    email = f"signals_{uuid.uuid4().hex[:10]}@example.com"
    ticket_first = _seed_oauth_ticket(email, name="New User Signup")
    ticket_second = _seed_oauth_ticket(email, name="Returning User Login")

    # First exchange: Brand-new user record
    r_first = requests.post(f"{BASE_URL}/api/auth/session", json={"session_id": ticket_first})
    assert r_first.status_code == 200, r_first.text
    data_first = r_first.json()
    assert "is_new_user" in data_first, "Missing is_new_user signal in response"
    assert data_first["is_new_user"] is True
    user_id = data_first["user"]["user_id"]

    try:
        # Second exchange with same email: Existing returning user
        r_second = requests.post(f"{BASE_URL}/api/auth/session", json={"session_id": ticket_second})
        assert r_second.status_code == 200, r_second.text
        data_second = r_second.json()
        assert "is_new_user" in data_second, "Missing is_new_user signal in response"
        assert data_second["is_new_user"] is False
        assert data_second["user"]["user_id"] == user_id
    finally:
        async def _cleanup():
            db = _db()
            await db.users.delete_many({"user_id": user_id})
            await db.user_sessions.delete_many({"user_id": user_id})
        _run(_cleanup())


def test_concurrent_exchange_session_brand_new_email_creates_single_user():
    """Concurrency test for brand-new user OAuth session exchange:
    Two concurrent /api/auth/session requests for the same brand-new email
    fired simultaneously via ThreadPoolExecutor.

    Ensures:
    1. Both requests succeed with HTTP 200 (no 500 crashes from DuplicateKeyError).
    2. Exactly ONE user document is created in db.users for that email.
    3. Both sessions reference the EXACT same user_id.
    4. Exactly one request gets is_new_user: true (the insert winner) and the
       other gets is_new_user: false (the race loser recovering gracefully).
    5. Two distinct user sessions are created in db.user_sessions.
    """
    email = f"concurrent_signup_{uuid.uuid4().hex[:10]}@example.com"
    ticket_a = _seed_oauth_ticket(email, name="Concurrent Traveler A")
    ticket_b = _seed_oauth_ticket(email, name="Concurrent Traveler B")

    def _exchange(ticket):
        return requests.post(f"{BASE_URL}/api/auth/session", json={"session_id": ticket})

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        fut_a = pool.submit(_exchange, ticket_a)
        fut_b = pool.submit(_exchange, ticket_b)
        resp_a = fut_a.result(timeout=30)
        resp_b = fut_b.result(timeout=30)

    assert resp_a.status_code == 200, f"resp_a failed: {resp_a.text}"
    assert resp_b.status_code == 200, f"resp_b failed: {resp_b.text}"

    data_a = resp_a.json()
    data_b = resp_b.json()

    user_id_a = data_a["user"]["user_id"]
    user_id_b = data_b["user"]["user_id"]

    # Invariant: single consistent user_id across both responses
    assert user_id_a == user_id_b, f"User IDs differed across concurrent signups: {user_id_a} vs {user_id_b}"

    # Invariant: exactly one is_new_user == True, the other == False
    signals = sorted([data_a["is_new_user"], data_b["is_new_user"]])
    assert signals == [False, True], f"Expected exactly one True and one False is_new_user, got: {signals}"

    try:
        # Invariant: Exactly ONE user document in database
        async def _verify_db():
            db = _db()
            user_docs = await db.users.find({"email": email}).to_list(10)
            session_docs = await db.user_sessions.find({"user_id": user_id_a}).to_list(10)
            return user_docs, session_docs

        user_docs, session_docs = _run(_verify_db())
        assert len(user_docs) == 1, f"Expected 1 user document, found {len(user_docs)}"
        assert user_docs[0]["user_id"] == user_id_a
        assert len(session_docs) == 2, f"Expected 2 active sessions, found {len(session_docs)}"
    finally:
        async def _cleanup():
            db = _db()
            await db.users.delete_many({"user_id": user_id_a})
            await db.user_sessions.delete_many({"user_id": user_id_a})
        _run(_cleanup())


# ---------- Session list / revoke ----------

def test_list_and_revoke_one_session_leaves_others_active():
    user_id = "test_authsec_multi_user"
    token_a = f"test_authsec_multi_a_{uuid.uuid4().hex[:8]}"
    token_b = f"test_authsec_multi_b_{uuid.uuid4().hex[:8]}"
    seed_session(user_id, token_a)
    seed_session(user_id, token_b)
    try:
        headers_a = {"Authorization": f"Bearer {token_a}"}
        headers_b = {"Authorization": f"Bearer {token_b}"}

        r = requests.get(f"{BASE_URL}/api/auth/sessions", headers=headers_a)
        assert r.status_code == 200, r.text
        sessions = r.json()["sessions"]
        assert len(sessions) == 2
        assert all("session_token" not in s for s in sessions)
        current = next(s for s in sessions if s["is_current"])
        other = next(s for s in sessions if not s["is_current"])

        # Revoking the *other* session must not require its own token - the
        # current session's auth is enough, same as a "sign out that device"
        # button would work.
        r = requests.delete(f"{BASE_URL}/api/auth/sessions/{other['session_id']}", headers=headers_a)
        assert r.status_code == 200, r.text

        # The revoked session's token must no longer authenticate...
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=headers_b)
        assert r.status_code == 401
        # ...while the session that did the revoking is untouched.
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=headers_a)
        assert r.status_code == 200

        r = requests.get(f"{BASE_URL}/api/auth/sessions", headers=headers_a)
        assert len(r.json()["sessions"]) == 1
        assert r.json()["sessions"][0]["session_id"] == current["session_id"]
    finally:
        delete_session(user_id, token_a)
        delete_session(user_id, token_b)


def test_revoke_session_requires_ownership():
    user_a = "test_authsec_owner_a"
    user_b = "test_authsec_owner_b"
    token_a = f"test_authsec_owner_a_tok_{uuid.uuid4().hex[:8]}"
    token_b = f"test_authsec_owner_b_tok_{uuid.uuid4().hex[:8]}"
    seed_session(user_a, token_a)
    seed_session(user_b, token_b)
    try:
        sessions_a = requests.get(
            f"{BASE_URL}/api/auth/sessions", headers={"Authorization": f"Bearer {token_a}"}
        ).json()["sessions"]
        session_id_a = sessions_a[0]["session_id"]

        # user_b must not be able to revoke user_a's session.
        r = requests.delete(
            f"{BASE_URL}/api/auth/sessions/{session_id_a}",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert r.status_code == 404

        # user_a's session is still alive.
        r = requests.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {token_a}"})
        assert r.status_code == 200
    finally:
        delete_session(user_a, token_a)
        delete_session(user_b, token_b)


def test_logout_only_revokes_current_session():
    user_id = "test_authsec_logout_user"
    token_a = f"test_authsec_logout_a_{uuid.uuid4().hex[:8]}"
    token_b = f"test_authsec_logout_b_{uuid.uuid4().hex[:8]}"
    seed_session(user_id, token_a)
    seed_session(user_id, token_b)
    try:
        r = requests.post(f"{BASE_URL}/api/auth/logout", headers={"Authorization": f"Bearer {token_a}"})
        assert r.status_code == 200

        r = requests.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {token_a}"})
        assert r.status_code == 401
        r = requests.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {token_b}"})
        assert r.status_code == 200
    finally:
        delete_session(user_id, token_a)
        delete_session(user_id, token_b)


# ---------- Wallet download URL signing / expiry ----------

def _upload_test_image(headers):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), color=(10, 20, 30)).save(buf, format="PNG")
    files = {"file": ("authsec_test.png", io.BytesIO(buf.getvalue()), "image/png")}
    r = requests.post(f"{BASE_URL}/api/wallet/upload", files=files, headers=headers, timeout=60)
    assert r.status_code == 200, r.text
    return r.json()


def test_download_url_genuinely_expired_link_rejected():
    """A link whose signature is valid *for its own (past) expiry* must
    still be rejected - this is the real "TTL passed" case, as opposed to
    a tampered expires value with a now-mismatched signature."""
    user_id = "test_authsec_wallet_user"
    token = f"test_authsec_wallet_tok_{uuid.uuid4().hex[:8]}"
    seed_session(user_id, token)
    try:
        headers = {"Authorization": f"Bearer {token}"}
        item = _upload_test_image(headers)
        past_expires = int(time.time()) - 5
        valid_signature_for_past = server._sign_wallet_download(item["item_id"], past_expires)

        r = requests.get(
            f"{BASE_URL}/api/wallet/{item['item_id']}/download",
            params={"expires": past_expires, "signature": valid_signature_for_past},
            timeout=60,
        )
        assert r.status_code == 401
    finally:
        delete_session(user_id, token)


def test_download_url_signature_scoped_to_item_id():
    """A signature minted for one item must not work for a different one,
    even with a matching (unexpired) expiry."""
    user_id = "test_authsec_wallet_scope_user"
    token = f"test_authsec_wallet_scope_tok_{uuid.uuid4().hex[:8]}"
    seed_session(user_id, token)
    try:
        headers = {"Authorization": f"Bearer {token}"}
        item_1 = _upload_test_image(headers)
        item_2 = _upload_test_image(headers)

        link = requests.get(
            f"{BASE_URL}/api/wallet/{item_1['item_id']}/download-url", headers=headers, timeout=60
        ).json()

        r = requests.get(
            f"{BASE_URL}/api/wallet/{item_2['item_id']}/download",
            params={"expires": link["expires"], "signature": link["signature"]},
            timeout=60,
        )
        assert r.status_code == 401
    finally:
        delete_session(user_id, token)


# ---------- MIME whitelist ----------

def test_upload_rejects_pdf_disguised_as_executable_content():
    """Genuine PDF magic bytes are accepted even with a misleading
    filename/Content-Type - detection is by content, not by name."""
    user_id = "test_authsec_mime_user"
    token = f"test_authsec_mime_tok_{uuid.uuid4().hex[:8]}"
    seed_session(user_id, token)
    try:
        headers = {"Authorization": f"Bearer {token}"}
        pdf_bytes = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"
        files = {"file": ("doc.bin", io.BytesIO(pdf_bytes), "application/octet-stream")}
        r = requests.post(f"{BASE_URL}/api/wallet/upload", files=files, headers=headers, timeout=60)
        assert r.status_code == 200, r.text
        assert r.json()["content_type"] == "application/pdf"
    finally:
        delete_session(user_id, token)


def test_upload_rejects_unsupported_type():
    user_id = "test_authsec_mime_reject_user"
    token = f"test_authsec_mime_reject_tok_{uuid.uuid4().hex[:8]}"
    seed_session(user_id, token)
    try:
        headers = {"Authorization": f"Bearer {token}"}
        files = {"file": ("data.csv", io.BytesIO(b"a,b,c\n1,2,3\n"), "text/csv")}
        r = requests.post(f"{BASE_URL}/api/wallet/upload", files=files, headers=headers, timeout=60)
        assert r.status_code == 415
    finally:
        delete_session(user_id, token)
