"""
Tests for db_models.TicketDoc (the new db.tickets collection) and its
startup-time index creation (services/index_service.py).

No migration exists for this collection - confirmed nothing tickets-shaped
exists anywhere in this app to backfill (grepped server.py/services/*.py/
backend/data/ for "ticket"/"tickets" before writing this - the only hits
are the pre-existing, unrelated db.oauth_tickets collection and "entry
tickets" itinerary-pricing text, neither of which is this feature).
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

import pytest
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import ValidationError

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from db_models import TicketDoc  # noqa: E402
from services import index_service  # noqa: E402

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')


def _db():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _run(coro):
    return asyncio.run(coro)


def _valid_ticket_kwargs(**overrides):
    now = datetime.now(timezone.utc)
    kwargs = {
        "title": "Regenerate CTA never appears for stuck generations",
        "description": "A trip generation stuck in 'generating' past the TTL never surfaces a retry option.",
        "kind": "bug",
        "status": "reported",
        "reporter_user_ids": ["user_abc123"],
        "linked_chat_sessions": ["64f1a2b3c4d5e6f7a8b9c0d1"],
        "first_reported_at": now,
        "updated_at": now,
        "agent_plan": None,
        "agent_diff_summary": None,
        "approval": "pending",
        "approval_note": None,
        "implementation_commit": None,
        "notified_user_ids": [],
    }
    kwargs.update(overrides)
    return kwargs


# ═══════════════ Model validation ═══════════════

def test_valid_ticket_validates():
    ticket = TicketDoc(**_valid_ticket_kwargs())
    assert ticket.kind == "bug"
    assert ticket.status == "reported"
    assert ticket.approval == "pending"
    assert ticket.reporter_user_ids == ["user_abc123"]
    assert ticket.id is None  # not yet persisted - no _id assigned


def test_object_id_is_stringified_for_id_field():
    """A real Mongo document's _id round-trips as a raw bson.ObjectId - must
    be coerced to str here, matching every other *_id-shaped field in
    db_models.py (user_id, trip_id, booking_id, ... - never a raw
    ObjectId)."""
    oid = ObjectId()
    ticket = TicketDoc(_id=oid, **_valid_ticket_kwargs())
    assert ticket.id == str(oid)
    assert isinstance(ticket.id, str)


@pytest.mark.parametrize("bad_kind", ["issue", "enhancement", "", "Bug"])
def test_invalid_kind_rejected(bad_kind):
    with pytest.raises(ValidationError):
        TicketDoc(**_valid_ticket_kwargs(kind=bad_kind))


@pytest.mark.parametrize("bad_status", ["open", "done", "", "Reported"])
def test_invalid_status_rejected(bad_status):
    with pytest.raises(ValidationError):
        TicketDoc(**_valid_ticket_kwargs(status=bad_status))


@pytest.mark.parametrize("bad_approval", ["yes", "no", "", "Pending"])
def test_invalid_approval_rejected(bad_approval):
    with pytest.raises(ValidationError):
        TicketDoc(**_valid_ticket_kwargs(approval=bad_approval))


def test_every_valid_status_accepted():
    for status in ("reported", "triaged", "awaiting_approval", "approved",
                   "implemented", "closed", "rejected", "backlog"):
        TicketDoc(**_valid_ticket_kwargs(status=status))


def test_every_valid_approval_accepted():
    for approval in ("pending", "approved", "rejected", "deferred"):
        TicketDoc(**_valid_ticket_kwargs(approval=approval))


def test_missing_required_field_rejected():
    kwargs = _valid_ticket_kwargs()
    del kwargs["title"]
    with pytest.raises(ValidationError):
        TicketDoc(**kwargs)


def test_optional_fields_default_correctly():
    kwargs = _valid_ticket_kwargs()
    for key in ("agent_plan", "agent_diff_summary", "approval_note", "implementation_commit",
                "reporter_user_ids", "linked_chat_sessions", "notified_user_ids"):
        del kwargs[key]
    ticket = TicketDoc(**kwargs)
    assert ticket.agent_plan is None
    assert ticket.agent_diff_summary is None
    assert ticket.approval_note is None
    assert ticket.implementation_commit is None
    assert ticket.reporter_user_ids == []
    assert ticket.linked_chat_sessions == []
    assert ticket.notified_user_ids == []


# ═══════════════ Index creation (services/index_service.py) ═══════════════

def test_ensure_indexes_creates_ticket_indexes():
    """ensure_indexes is idempotent/safe to call directly against a real
    Mongo instance - the same call server.py's startup_event makes.
    Confirms the four required indexes (status, kind, updated_at
    descending, reporter_user_ids) actually exist afterward."""
    # Both awaits share one asyncio.run() call / one fresh client - a second
    # separate _run() reusing the same Motor client hits "RuntimeError: Event
    # loop is closed" on this stack (Python 3.14 + Windows + motor binds a
    # client to whichever event loop first used it; a second asyncio.run()
    # spins up a new loop the old client can't use) - see
    # test_rewards_race.py's module docstring for the same wall hit first.
    async def _do():
        db = _db()
        await index_service.ensure_indexes(db)
        return await db.tickets.index_information()
    info = _run(_do())

    def _has_index(key_spec):
        return any(details["key"] == key_spec for details in info.values())

    assert _has_index([("status", 1)]), f"no plain 'status' index found in {info}"
    assert _has_index([("kind", 1)]), f"no plain 'kind' index found in {info}"
    assert _has_index([("updated_at", -1)]), f"no descending 'updated_at' index found in {info}"
    assert _has_index([("reporter_user_ids", 1)]), f"no 'reporter_user_ids' index found in {info}"
