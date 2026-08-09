"""
Tests for services/notification_service.py (EYV Agent System, Phase 4 Step 4.3).

HTTP calls to the internal ticket API (GET /{id}, POST /{id}/notify) go
through a fake object shaped like httpx.AsyncClient, same reasoning as
test_ticket_dedup_service.py's own fake client: a real in-process ASGI call
through conftest.py's shared `client` fixture corrupts that fixture's Motor
client binding across a second, independently-created event loop (see
test_support_agent_service.py's "create_or_append_ticket" section for the
full story). Email sends go through a fake EmailClient-shaped object -
notify_ticket_status_change only relies on email_client.send(...)'s
signature, not the real class, so a duck-typed fake is enough.

db.users (for email lookup) and db.notifications (for in-app rows) are real
Mongo, via this file's own _db()/_run() pattern (same as every other test
file that touches real collections in this suite).
"""
import asyncio
import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from services import notification_service  # noqa: E402

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')


def _db():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _run(coro):
    return asyncio.run(coro)


def _seed_user(user_id: str, email: str) -> None:
    async def _do():
        await _db().users.update_one(
            {"user_id": user_id},
            {"$set": {"user_id": user_id, "email": email, "name": "Test User",
                      "created_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
    _run(_do())


def _cleanup_user(user_id: str) -> None:
    async def _do():
        await _db().users.delete_many({"user_id": user_id})
    _run(_do())


def _cleanup_notifications(ticket_id: str) -> None:
    async def _do():
        await _db().notifications.delete_many({"ticket_id": ticket_id})
    _run(_do())


def _find_notifications(ticket_id: str) -> List[Dict[str, Any]]:
    async def _do():
        cursor = _db().notifications.find({"ticket_id": ticket_id})
        return await cursor.to_list(50)
    return _run(_do())


# ═══════════════ Fakes ═══════════════

class _FakeEmailClient:
    """Records every send; raises for any `to` address in `fail_for`,
    simulating a provider-side failure for that one recipient."""
    def __init__(self, fail_for=frozenset()):
        self.sent: List[Dict[str, Any]] = []
        self._fail_for = fail_for

    async def send(self, *, to: str, subject: str, text: str, html=None) -> None:
        if to in self._fail_for:
            raise RuntimeError(f"simulated send failure for {to}")
        self.sent.append({"to": to, "subject": subject, "text": text})


def _ticket(**overrides) -> Dict[str, Any]:
    ticket = {
        "id": "ticket_1",
        "title": "Refund button does nothing",
        "description": "Clicking Request Refund shows no confirmation.",
        "kind": "bug",
        "status": "implemented",
        "reporter_user_ids": [],
        "linked_chat_sessions": [],
        "first_reported_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "agent_plan": None,
        "agent_diff_summary": None,
        "approval": "approved",
        "approval_note": None,
        "implementation_commit": "abc123",
        "notified_user_ids": [],
    }
    ticket.update(overrides)
    return ticket


class _FakeInternalTicketAPIClient:
    """`ticket` is a mutable dict standing in for the live document -
    POST .../notify mutates it in place (merging notified_user_ids, same
    semantics as the real route's $addToSet), so a second GET .../{id}
    call within the same test reflects the first call's effect, the same
    way a real backend would."""
    def __init__(self, ticket: Dict[str, Any]):
        self.ticket = ticket
        self.requests: List[SimpleNamespace] = []

    async def get(self, path, *, headers=None):
        self.requests.append(SimpleNamespace(method="GET", path=path, headers=headers))
        return SimpleNamespace(status_code=200, json=lambda: dict(self.ticket), raise_for_status=lambda: None)

    async def post(self, path, *, json=None, headers=None):
        self.requests.append(SimpleNamespace(method="POST", path=path, json=json, headers=headers))
        merged = list(self.ticket.get("notified_user_ids") or [])
        for uid in json["user_ids"]:
            if uid not in merged:
                merged.append(uid)
        self.ticket["notified_user_ids"] = merged
        return SimpleNamespace(status_code=200, json=lambda: dict(self.ticket), raise_for_status=lambda: None)


# ═══════════════ Email templates ═══════════════

@pytest.mark.parametrize("status", ["implemented", "rejected", "backlog"])
def test_render_status_email_produces_subject_and_body_mentioning_the_ticket(status):
    subject, body = notification_service._render_status_email(
        status=status, ticket_title="Refund button does nothing", ticket_id="ticket_1",
    )
    assert "Refund button does nothing" in subject or "Refund button does nothing" in body
    assert "ticket_1" in body
    assert subject and body


def test_render_status_email_implemented_says_fixed_and_live():
    subject, body = notification_service._render_status_email(
        status="implemented", ticket_title="X", ticket_id="t1",
    )
    assert "implemented" in body and "live" in body


def test_render_status_email_rejected_says_not_moving_forward():
    subject, body = notification_service._render_status_email(
        status="rejected", ticket_title="X", ticket_id="t1",
    )
    assert "not" in body.lower() and "move forward" in body.lower()


def test_render_status_email_backlog_says_backlog():
    subject, body = notification_service._render_status_email(
        status="backlog", ticket_title="X", ticket_id="t1",
    )
    assert "backlog" in body.lower()


def test_render_status_email_includes_link_only_when_provided():
    _, body_without = notification_service._render_status_email(
        status="implemented", ticket_title="X", ticket_id="t1",
    )
    _, body_with = notification_service._render_status_email(
        status="implemented", ticket_title="X", ticket_id="t1", ticket_url="https://eyv.app/tickets/t1",
    )
    assert "https://eyv.app/tickets/t1" not in body_without
    assert "https://eyv.app/tickets/t1" in body_with


# ═══════════════ Idempotent fan-out (the critical test) ═══════════════

def test_running_fan_out_twice_sends_exactly_one_email_per_reporter():
    user_a, user_b = "user_notify_a", "user_notify_b"
    _seed_user(user_a, "a@example.com")
    _seed_user(user_b, "b@example.com")
    ticket = _ticket(reporter_user_ids=[user_a, user_b])
    fake_http = _FakeInternalTicketAPIClient(ticket)
    fake_email = _FakeEmailClient()
    try:
        async def _run_once():
            return await notification_service.notify_ticket_status_change(
                _db(), fake_http, fake_email,
                internal_ticket_api_token="tok", ticket_id="ticket_1", status="implemented",
            )

        first = _run(_run_once())
        assert sorted(first["notified_user_ids"]) == sorted([user_a, user_b])
        assert len(fake_email.sent) == 2

        second = _run(_run_once())
        assert sorted(second["notified_user_ids"]) == sorted([user_a, user_b])

        assert len(fake_email.sent) == 2, "a second run must not send duplicate emails to already-notified reporters"
        to_addresses = [m["to"] for m in fake_email.sent]
        assert sorted(to_addresses) == ["a@example.com", "b@example.com"]

        notify_posts = [r for r in fake_http.requests if r.method == "POST"]
        assert len(notify_posts) == 1, "the second run had nothing new to notify - it must not call POST /notify at all"
    finally:
        _cleanup_user(user_a)
        _cleanup_user(user_b)
        _cleanup_notifications("ticket_1")


# ═══════════════ Partial failure ═══════════════

def test_one_reporter_email_failure_does_not_block_others_or_get_marked_notified():
    user_ok, user_fails = "user_notify_ok", "user_notify_fails"
    _seed_user(user_ok, "ok@example.com")
    _seed_user(user_fails, "fails@example.com")
    ticket = _ticket(reporter_user_ids=[user_ok, user_fails])
    fake_http = _FakeInternalTicketAPIClient(ticket)
    fake_email = _FakeEmailClient(fail_for={"fails@example.com"})
    try:
        async def _do():
            return await notification_service.notify_ticket_status_change(
                _db(), fake_http, fake_email,
                internal_ticket_api_token="tok", ticket_id="ticket_1", status="rejected",
            )
        result = _run(_do())

        assert result["notified_user_ids"] == [user_ok]
        assert user_fails not in result["notified_user_ids"]

        sent_to = [m["to"] for m in fake_email.sent]
        assert sent_to == ["ok@example.com"], "the failing reporter's email must never be recorded as sent"

        # In-app row created only for the reporter whose email succeeded -
        # a reporter never marked notified shouldn't have a stray in-app
        # row either.
        rows = _find_notifications("ticket_1")
        assert {r["user_id"] for r in rows} == {user_ok}
    finally:
        _cleanup_user(user_ok)
        _cleanup_user(user_fails)
        _cleanup_notifications("ticket_1")


def test_rerunning_after_a_failure_retries_only_the_failed_reporter():
    user_ok, user_retry = "user_notify_ok2", "user_notify_retry"
    _seed_user(user_ok, "ok2@example.com")
    _seed_user(user_retry, "retry@example.com")
    ticket = _ticket(reporter_user_ids=[user_ok, user_retry])
    fake_http = _FakeInternalTicketAPIClient(ticket)
    fake_email = _FakeEmailClient(fail_for={"retry@example.com"})
    try:
        async def _do():
            return await notification_service.notify_ticket_status_change(
                _db(), fake_http, fake_email,
                internal_ticket_api_token="tok", ticket_id="ticket_1", status="backlog",
            )
        _run(_do())
        assert len(fake_email.sent) == 1

        # Fix the "provider" and re-run - only the previously-failed
        # reporter should be attempted this time.
        fake_email._fail_for = frozenset()
        second = _run(_do())

        assert sorted(second["notified_user_ids"]) == sorted([user_ok, user_retry])
        sent_to = [m["to"] for m in fake_email.sent]
        assert sent_to.count("ok2@example.com") == 1, "the already-notified reporter must not be re-sent"
        assert sent_to.count("retry@example.com") == 1
    finally:
        _cleanup_user(user_ok)
        _cleanup_user(user_retry)
        _cleanup_notifications("ticket_1")


# ═══════════════ In-app notifications + unread count ═══════════════

def test_in_app_notification_created_and_counted_as_unread():
    user_id = "user_notify_inapp"
    _seed_user(user_id, "inapp@example.com")
    ticket = _ticket(reporter_user_ids=[user_id])
    fake_http = _FakeInternalTicketAPIClient(ticket)
    fake_email = _FakeEmailClient()
    try:
        async def _do():
            await notification_service.notify_ticket_status_change(
                _db(), fake_http, fake_email,
                internal_ticket_api_token="tok", ticket_id="ticket_1", status="implemented",
            )
            notifications = await notification_service.list_notifications(_db(), user_id)
            unread = await notification_service.count_unread_notifications(_db(), user_id)
            return notifications, unread
        notifications, unread = _run(_do())

        assert len(notifications) == 1
        assert notifications[0]["user_id"] == user_id
        assert notifications[0]["ticket_id"] == "ticket_1"
        assert notifications[0]["status"] == "implemented"
        assert notifications[0]["read"] is False
        assert isinstance(notifications[0]["id"], str)
        assert unread == 1
    finally:
        _cleanup_user(user_id)
        _cleanup_notifications("ticket_1")


def test_no_pending_reporters_is_a_noop_and_makes_no_http_or_email_calls():
    """Every reporter already in notified_user_ids - nothing to do."""
    ticket = _ticket(reporter_user_ids=["user_x"], notified_user_ids=["user_x"])
    fake_http = _FakeInternalTicketAPIClient(ticket)
    fake_email = _FakeEmailClient()

    async def _do():
        return await notification_service.notify_ticket_status_change(
            _db(), fake_http, fake_email,
            internal_ticket_api_token="tok", ticket_id="ticket_1", status="implemented",
        )
    result = _run(_do())

    assert not fake_email.sent
    assert not [r for r in fake_http.requests if r.method == "POST"]
    assert result["notified_user_ids"] == ["user_x"]
