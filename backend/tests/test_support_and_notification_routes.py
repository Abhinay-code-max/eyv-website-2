"""
Tests for the new user-facing routes added in Step 4.4 (EYV Agent System,
Phase 4): POST /api/support/message, GET /api/notifications,
PATCH /api/notifications/read - all in server.py, session-authenticated
(conftest.py's `authed_client` fixture), wrapping support_agent_service.py/
notification_service.py, neither of which has an HTTP surface of its own.

Uses the in-process `client`/`authed_client` fixtures (starlette TestClient
over server.app) synchronously, the same way test_internal_tickets_api.py
does - no asyncio.run() of this file's own driving these calls, so there's
no risk of the cross-loop Motor-client corruption test_support_agent_service.py's
own tests had to work around (that only happened when a test drove the
shared TestClient from within a SEPARATELY-created event loop).

Gemini is mocked via monkeypatching server._get_gemini_client, same pattern
test_plan_generation_crash.py uses for generate_single_plan - a fake
`.aio.models.generate_content_stream` that streams back canned text, so
POST /api/support/message's classification step doesn't depend on a real
model call. Since a fresh test user has no existing tickets, the
ticket-dedup step (Step 4.2) never has candidates to compare against and
skips its own Gemini call entirely - confirmed by
test_ticket_dedup_service.py's own test_no_candidates_skips_gemini_call_and_creates
- so a bug/feature test only needs to supply ONE canned classification
response.
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from conftest import authed_client, client  # noqa: E402,F401  (fixture imports)

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')


def _db():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _run(coro):
    return asyncio.run(coro)


def _cleanup_tickets_reported_by(user_id: str) -> None:
    async def _do():
        await _db().tickets.delete_many({"reporter_user_ids": user_id})
    _run(_do())


def _cleanup_generation_logs_for(user_id: str) -> None:
    async def _do():
        await _db().generation_logs.delete_many({"trip_id": f"support_{user_id}"})
    _run(_do())


def _seed_notification(**overrides):
    async def _do():
        now = datetime.now(timezone.utc)
        doc = {
            "user_id": "placeholder", "ticket_id": "ticket_placeholder",
            "status": "implemented", "title": "Fixed: your report",
            "body": "Your report has been implemented.", "read": False,
            "created_at": now,
        }
        doc.update(overrides)
        result = await _db().notifications.insert_one(doc)
        return str(result.inserted_id)
    return _run(_do())


def _cleanup_notifications_for(user_id: str) -> None:
    async def _do():
        await _db().notifications.delete_many({"user_id": user_id})
    _run(_do())


# ═══════════════ Fake Gemini client ═══════════════

class _FakeModels:
    def __init__(self, responses):
        self._responses = responses
        self.call_count = 0

    async def generate_content_stream(self, *args, **kwargs):
        idx = min(self.call_count, len(self._responses) - 1)
        text = self._responses[idx]
        self.call_count += 1
        async def _gen():
            yield SimpleNamespace(text=text)
        return _gen()


class _FakeAio:
    def __init__(self, responses):
        self.models = _FakeModels(responses)


class _FakeGeminiClient:
    def __init__(self, *responses):
        self.aio = _FakeAio(list(responses))


def _classification_json(category: str) -> str:
    return json.dumps({"category": category})


def _mock_gemini(monkeypatch, *responses):
    import server as server_module
    fake_client = _FakeGeminiClient(*responses)
    monkeypatch.setattr(server_module, "_get_gemini_client", lambda: fake_client)
    return fake_client


# ═══════════════ POST /api/support/message ═══════════════

def test_support_message_requires_auth(client):
    r = client.post("/api/support/message", json={"message": "hello"})
    assert r.status_code == 401, r.text


def test_support_message_question_returns_conversational_answer_no_ticket(authed_client, monkeypatch):
    client_, user_id = authed_client
    _mock_gemini(monkeypatch, _classification_json("question"), "Refunds take 5-10 business days.")
    try:
        r = client_.post(
            "/api/support/message",
            json={"message": "How long do refunds take?"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["category"] == "question"
        assert body["ticket"] is None
        assert body["escalated"] is False
        assert "refund" in body["reply"].lower() or body["reply"]
    finally:
        _cleanup_generation_logs_for(user_id)


def test_support_message_bug_report_files_a_ticket(authed_client, monkeypatch):
    client_, user_id = authed_client
    _mock_gemini(monkeypatch, _classification_json("bug"))
    try:
        r = client_.post(
            "/api/support/message",
            json={"message": "The refund button does nothing when I click it."},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["category"] == "bug"
        assert body["ticket"] is not None
        assert body["ticket"]["kind"] == "bug"
        assert user_id in body["ticket"]["reporter_user_ids"]
        assert body["ticket"]["status"] == "reported"
    finally:
        _cleanup_tickets_reported_by(user_id)
        _cleanup_generation_logs_for(user_id)


def test_support_message_rejects_blank_message(authed_client, monkeypatch):
    client_, user_id = authed_client
    _mock_gemini(monkeypatch, _classification_json("other"))
    r = client_.post("/api/support/message", json={"message": "   "})
    assert r.status_code == 422, r.text


# ═══════════════ GET /api/notifications, PATCH /api/notifications/read ═══════

def test_notifications_requires_auth(client):
    r = client.get("/api/notifications")
    assert r.status_code == 401, r.text


def test_get_notifications_returns_unread_count_and_list(authed_client):
    client_, user_id = authed_client
    n1 = _seed_notification(user_id=user_id, status="implemented", title="Fixed: A")
    n2 = _seed_notification(user_id=user_id, status="rejected", title="Update: B", read=True)
    try:
        r = client_.get("/api/notifications")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["unread_count"] == 1
        ids = {n["id"] for n in body["notifications"]}
        assert {n1, n2} == ids
    finally:
        _cleanup_notifications_for(user_id)


def test_get_notifications_never_returns_another_users_notifications(authed_client):
    client_, user_id = authed_client
    other_user_id = f"user_other_{ObjectId()}"
    _seed_notification(user_id=other_user_id, status="implemented")
    try:
        r = client_.get("/api/notifications")
        assert r.status_code == 200, r.text
        assert r.json()["notifications"] == []
        assert r.json()["unread_count"] == 0
    finally:
        _cleanup_notifications_for(other_user_id)


def test_mark_notifications_read_updates_unread_count(authed_client):
    client_, user_id = authed_client
    _seed_notification(user_id=user_id, status="implemented")
    _seed_notification(user_id=user_id, status="backlog")
    try:
        before = client_.get("/api/notifications").json()
        assert before["unread_count"] == 2

        r = client_.patch("/api/notifications/read")
        assert r.status_code == 200, r.text
        assert r.json()["marked_read"] == 2

        after = client_.get("/api/notifications").json()
        assert after["unread_count"] == 0
        assert all(n["read"] for n in after["notifications"])
    finally:
        _cleanup_notifications_for(user_id)


def test_mark_notifications_read_only_affects_calling_users_notifications(authed_client):
    client_, user_id = authed_client
    other_user_id = f"user_other_{ObjectId()}"
    _seed_notification(user_id=other_user_id, status="implemented")
    try:
        r = client_.patch("/api/notifications/read")
        assert r.status_code == 200, r.text
        assert r.json()["marked_read"] == 0

        async def _fetch_other():
            return await _db().notifications.find_one({"user_id": other_user_id})
        other_doc = _run(_fetch_other())
        assert other_doc["read"] is False
    finally:
        _cleanup_notifications_for(other_user_id)
