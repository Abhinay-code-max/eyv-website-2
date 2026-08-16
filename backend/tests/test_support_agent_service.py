"""
Tests for services/support_agent_service.py (EYV Agent System, Phase 4 Step 4.1).

Classification tests mock the Gemini client the same way
test_plan_generation_crash.py does (a fake `.aio.models.generate_content_stream`
that streams back canned text) - classify_message takes `gemini_client` as a
plain parameter rather than fetching a module-level singleton itself, so no
monkeypatching is needed to substitute it.

Ticket-creation tests for create_or_append_ticket use a fake HTTP client
(no real network, no in-process ASGI call) - see the "create_or_append_ticket"
section below for why a real in-process call through conftest.py's shared
`client` fixture was tried first and reverted. Tool-scope and redaction
tests use conftest.py's real Mongo `_db()`/`_run()` pattern (same as
test_ticket_doc.py / test_internal_tickets_api.py).
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict

import httpx
import pytest
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from services import support_agent_service  # noqa: E402

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')


def _db():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _run(coro):
    return asyncio.run(coro)


def _cleanup_generation_logs(conversation_id: str) -> None:
    async def _do():
        await _db().generation_logs.delete_many({"trip_id": conversation_id})
    _run(_do())


def _find_generation_log(conversation_id: str):
    async def _do():
        return await _db().generation_logs.find_one({"trip_id": conversation_id})
    return _run(_do())


# ═══════════════ Fake Gemini client (classification) ═══════════════

class _FakeModels:
    """Stands in for gemini_client.aio.models - returns one canned response
    text per call, in order (call N uses responses[N], the last entry is
    reused for any further calls beyond the list)."""
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


# ═══════════════ Step 1: classification ═══════════════

@pytest.mark.parametrize("category, message", [
    ("bug", "The refund button on my cancelled Goa booking does nothing when I click it - no confirmation, no error."),
    ("question", "How many days before departure can I still get a full refund on a flight booking?"),
    ("feature", "Could you add a way to split a bundle booking's cost between multiple travelers' cards?"),
])
def test_classify_clear_cases(category, message):
    fake_client = _FakeGeminiClient(_classification_json(category))
    result = _run(support_agent_service.classify_message(fake_client, message))
    assert result.category == category


def test_classify_ambiguous_case_returns_a_valid_category():
    """A message that could plausibly read as either a bug report or a
    question ("my booking says pending but I was charged - is that normal
    or is something wrong?") - not asserting which category a real model
    would pick (that's a model-quality question, not this module's
    contract), only that whatever valid category the model settles on comes
    back validated and untouched, never silently remapped to something
    else."""
    fake_client = _FakeGeminiClient(_classification_json("bug"))
    message = "My booking status still says pending even though I was charged - is that normal or did something break?"
    result = _run(support_agent_service.classify_message(fake_client, message))
    assert result.category in support_agent_service.SUPPORT_CATEGORIES


def test_classify_retries_on_malformed_json_then_succeeds():
    """Real-world ambiguity can also show up as the model itself waffling
    between a clean answer and junk output. First attempt returns
    unparseable text (not JSON at all); the second attempt returns a valid
    classification. This must be retried, not silently repaired into a
    guessed category - confirms both that a retry happens AND that the
    eventual result is the real second-attempt value."""
    fake_client = _FakeGeminiClient("not json at all", _classification_json("question"))
    result = _run(support_agent_service.classify_message(fake_client, "Where is my booking confirmation email?"))
    assert result.category == "question"
    assert fake_client.aio.models.call_count == 2


def test_classify_retries_on_invalid_category_then_succeeds():
    """Second flavor of malformed output: valid JSON, but a category value
    outside the Literal enum (e.g. the model inventing "spam" or
    "complaint"). Must retry rather than coercing to some default."""
    fake_client = _FakeGeminiClient(_classification_json("complaint"), _classification_json("other"))
    result = _run(support_agent_service.classify_message(fake_client, "lol ok"))
    assert result.category == "other"
    assert fake_client.aio.models.call_count == 2


def test_classify_raises_after_exhausting_retries_on_persistently_malformed_output():
    """Every attempt returns garbage - classify_message must raise, not
    return some default/fabricated category (the 'never silent coercion'
    rule)."""
    fake_client = _FakeGeminiClient("still not json", "also not json", "nope")
    with pytest.raises(ValueError):
        _run(support_agent_service.classify_message(fake_client, "???", max_attempts=3))
    assert fake_client.aio.models.call_count == 3


# ═══════════════ HARD CONSTRAINT: tool-scope tests ═══════════════

def test_tool_registry_has_exactly_one_write_tool():
    """Literal check on TOOL_REGISTRY (the task's own framing: 'the tool
    registry for this service contains zero write-capable tools touching
    bookings/payments/wallet'). Only create_or_append_ticket is writable,
    and it writes via the internal ticket API over HTTP, never any of the
    three forbidden collections directly (confirmed separately by the
    AST-based test below)."""
    write_tools = [
        name for name, meta in support_agent_service.TOOL_REGISTRY.items()
        if not meta["read_only"]
    ]
    assert write_tools == ["create_or_append_ticket"]


def test_no_write_path_to_bookings_payments_or_wallet():
    """AST-based (not string search) confirmation that support_agent_service.py
    contains no write call against db.bookings/db.payment_transactions/
    db.wallet_items anywhere in its source - mirrors
    test_internal_tickets_api.py::test_module_never_references_user_or_booking_or_payment_collections's
    AST-over-string-search approach, adapted to flag WRITE calls
    specifically (rather than any reference at all), since this service
    legitimately *reads* db.bookings via lookup_booking."""
    import ast
    import inspect

    source = inspect.getsource(support_agent_service)
    tree = ast.parse(source)

    forbidden_collections = {"bookings", "payment_transactions", "wallet_items"}
    write_methods = {
        "insert_one", "insert_many", "update_one", "update_many",
        "delete_one", "delete_many", "replace_one",
        "find_one_and_update", "find_one_and_delete", "find_one_and_replace",
        "bulk_write",
    }

    violations = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in write_methods:
            continue
        target = node.func.value
        if isinstance(target, ast.Attribute) and target.attr in forbidden_collections:
            violations.append(f"{target.attr}.{node.func.attr}")

    assert not violations, f"support_agent_service.py contains write call(s) to forbidden collections: {violations}"


def test_module_never_imports_write_capable_booking_or_payment_models():
    """Complements the AST call-site check above: this module also must
    never import the raw doc models that would make constructing a
    bookings/payment_transactions/wallet_items write easy to add later
    without it showing up as a `db.<collection>.<write_method>()` call
    site (e.g. building a doc via BookingLineItem and inserting it through
    a helper)."""
    import ast
    import inspect

    source = inspect.getsource(support_agent_service)
    tree = ast.parse(source)
    forbidden_imports = {
        "SingleItemBookingDoc", "BundleBookingDoc", "BookingDoc", "BookingLineItem",
        "PaymentTransactionDoc", "WalletItemDoc",
    }
    imported_names = {
        alias.asname or alias.name
        for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert not (imported_names & forbidden_imports), (
        f"support_agent_service.py unexpectedly imports {imported_names & forbidden_imports}"
    )


# ═══════════════ create_or_append_ticket ═══════════════
#
# Two separate concerns, deliberately tested in two separate places:
#   - "does POST /api/internal/tickets actually persist native datetimes,
#     not ISO strings" is a question about internal_tickets_api.py's route,
#     answered by
#     test_internal_tickets_api.py::test_create_ticket_sets_native_datetimes_and_default_workflow_state
#     (which inspects the raw Mongo document that route wrote).
#   - "does create_or_append_ticket send the right request and correctly
#     validate the response" is a question about THIS module's own
#     contract, answered by the two tests below, against a fake HTTP client
#     - not a second real in-process ASGI call through the shared `client`
#     fixture. That was tried first (both a raw ASGITransport client and a
#     to_thread-wrapped call through the real `client` fixture) and both
#     reproducibly corrupted every later test_internal_tickets_api.py test
#     in the same pytest session ("Future ... attached to a different
#     loop", then every subsequent index-creation/audit-log write against
#     server.app's shared Motor client failing) - server.app's Motor client
#     binds to whichever event loop first drives it, and this module's own
#     asyncio.run() calls (needed to drive create_or_append_ticket, an
#     async function) are a second, independently-created loop from
#     conftest.py's TestClient portal, no matter how the actual HTTP call
#     to it is threaded.

def _fake_ticket_response(**overrides) -> Dict[str, Any]:
    now_iso = datetime.now(timezone.utc).isoformat()
    payload = {
        "id": str(ObjectId()),
        "title": "Cannot download wallet pass",
        "description": "Tapping 'Download to wallet' on a confirmed hotel booking spins forever and never downloads.",
        "kind": "bug",
        "status": "reported",
        "reporter_user_ids": ["user_support_test"],
        "linked_chat_sessions": ["conv_support_test_1"],
        "first_reported_at": now_iso,
        "updated_at": now_iso,
        "agent_plan": None,
        "agent_diff_summary": None,
        "approval": "pending",
        "approval_note": None,
        "implementation_commit": None,
        "notified_user_ids": [],
    }
    payload.update(overrides)
    return payload


class _FakeTicketAPIHTTPClient:
    """Stands in for httpx.AsyncClient - records the request it received and
    returns a canned response shaped exactly like internal_tickets_api.py's
    create_ticket route response (_serialize_ticket's TicketDoc.model_dump(mode="json")
    output - ISO-string timestamps over the wire, same as any JSON API;
    what matters is what lands in Mongo, covered separately - see section
    header above)."""
    def __init__(self, response_json):
        self._response_json = response_json
        self.requests = []

    async def post(self, path, *, json=None, headers=None):
        self.requests.append(SimpleNamespace(path=path, json=json, headers=headers))
        return httpx.Response(
            200, json=self._response_json,
            request=httpx.Request("POST", "http://internal" + path),
        )


def test_create_or_append_ticket_sends_correct_request_and_validates_response():
    fake_response = _fake_ticket_response()
    http_client = _FakeTicketAPIHTTPClient(fake_response)

    async def _do():
        return await support_agent_service.create_or_append_ticket(
            http_client,
            internal_ticket_api_token="a-test-token",
            title="Cannot download wallet pass",
            description="Tapping 'Download to wallet' on a confirmed hotel booking spins forever and never downloads.",
            kind="bug",
            reporter_user_id="user_support_test",
            chat_session_id="conv_support_test_1",
        )

    ticket = _run(_do())

    assert len(http_client.requests) == 1
    req = http_client.requests[0]
    assert req.path == "/api/internal/tickets"
    assert req.headers == {"Authorization": "Bearer a-test-token"}
    assert req.json == {
        "title": "Cannot download wallet pass",
        "description": "Tapping 'Download to wallet' on a confirmed hotel booking spins forever and never downloads.",
        "kind": "bug",
        "reporter_user_ids": ["user_support_test"],
        "linked_chat_sessions": ["conv_support_test_1"],
    }
    assert ticket["id"] == fake_response["id"]
    assert ticket["status"] == "reported"


def test_create_or_append_ticket_validates_response_against_ticket_doc():
    """A response that doesn't match TicketDoc's shape (here: an invalid
    `kind`) must raise, not silently pass through a malformed ticket -
    consistent with this codebase's "validate every boundary, no silent
    coercion" rule."""
    from pydantic import ValidationError
    bad_response = _fake_ticket_response(kind="not-a-real-kind")
    http_client = _FakeTicketAPIHTTPClient(bad_response)

    async def _do():
        return await support_agent_service.create_or_append_ticket(
            http_client, internal_ticket_api_token="a-test-token",
            title="T", description="D", kind="bug",
        )

    with pytest.raises(ValidationError):
        _run(_do())


# ═══════════════ Step 4.2 wiring: bug/feature goes through dedup ═══════════

def test_bug_report_is_routed_through_ticket_dedup_service_not_created_directly(monkeypatch):
    """handle_support_message must no longer decide create-vs-append itself
    for a bug/feature report - it hands the candidate report to
    ticket_dedup_service.check_and_resolve_ticket and that module makes the
    call. Confirmed here by replacing check_and_resolve_ticket with a spy:
    if handle_support_message still called create_or_append_ticket
    directly instead, this spy would simply never fire and the test would
    fail on the call-count assertion below."""
    calls = []

    async def fake_check_and_resolve_ticket(gemini_client, http_client, **kwargs):
        calls.append(kwargs)
        return support_agent_service.TicketDoc(
            id="ticket_from_dedup", title=kwargs["title"], description=kwargs["description"],
            kind=kwargs["kind"], status="reported",
            reporter_user_ids=[kwargs["reporter_user_id"]], linked_chat_sessions=[],
            first_reported_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
            approval="pending", notified_user_ids=[],
        ).model_dump(mode="json")

    monkeypatch.setattr(
        support_agent_service.ticket_dedup_service, "check_and_resolve_ticket", fake_check_and_resolve_ticket,
    )

    fake_gemini = _FakeGeminiClient(_classification_json("bug"))
    conversation_id = f"conv_dedup_wiring_test_{ObjectId()}"
    try:
        async def _do():
            return await support_agent_service.handle_support_message(
                _db(), fake_gemini, http_client=None,
                internal_ticket_api_token="tok", user_id="user_dedup_test",
                conversation_id=conversation_id,
                message="The refund button does nothing when I click it.",
            )
        result = _run(_do())
    finally:
        _cleanup_generation_logs(conversation_id)

    assert len(calls) == 1, "expected exactly one call to check_and_resolve_ticket"
    assert calls[0]["kind"] == "bug"
    assert calls[0]["reporter_user_id"] == "user_dedup_test"
    assert result.ticket["id"] == "ticket_from_dedup"
    assert result.category == "bug"


# ═══════════════ generation_logs redaction ═══════════════

def test_log_support_turn_redacts_email_and_phone_from_stored_message():
    conversation_id = f"conv_redaction_test_{ObjectId()}"
    sensitive_message = (
        "Please refund my booking, my email is jane.traveler@example.com "
        "and you can reach me at +1 (415) 555-0199 if needed."
    )
    try:
        async def _do():
            await support_agent_service.log_support_turn(
                _db(),
                conversation_id=conversation_id,
                status="bug:ticket_created",
                message=sensitive_message,
                response_text="Thanks - I've filed a ticket.",
            )
        _run(_do())
        stored = _find_generation_log(conversation_id)
        assert stored is not None, "expected a generation_logs entry for this conversation"
        assert "jane.traveler@example.com" not in stored["prompt"]
        assert "415" not in stored["prompt"] or "555-0199" not in stored["prompt"]
        assert "[REDACTED]" in stored["prompt"]
        assert stored["plan_type"] == "support_agent"
        assert stored["trip_id"] == conversation_id
        assert isinstance(stored["created_at"], datetime)
    finally:
        _cleanup_generation_logs(conversation_id)


def test_log_support_turn_leaves_non_sensitive_text_untouched():
    conversation_id = f"conv_redaction_test_{ObjectId()}"
    message = "The itinerary page shows the wrong currency symbol for INR trips."
    try:
        async def _do():
            await support_agent_service.log_support_turn(
                _db(), conversation_id=conversation_id, status="bug:ticket_created",
                message=message, response_text="Thanks - I've filed a ticket.",
            )
        _run(_do())
        stored = _find_generation_log(conversation_id)
        assert stored["prompt"] == message
    finally:
        _cleanup_generation_logs(conversation_id)


# ═══════════════ Task A.3: Denver Producer Wiring (jarvis_queue_items) ═══════════════

def test_bug_report_enqueues_ticket_review_for_jarvis(monkeypatch):
    """When Denver files a bug ticket, it must enqueue a ticket_review item for JARVIS."""
    ticket_id = f"ticket_{ObjectId()}"

    async def fake_check_and_resolve_ticket(gemini_client, http_client, **kwargs):
        return support_agent_service.TicketDoc(
            id=ticket_id, title=kwargs["title"], description=kwargs["description"],
            kind=kwargs["kind"], status="reported",
            reporter_user_ids=[kwargs["reporter_user_id"]], linked_chat_sessions=[kwargs["chat_session_id"]],
            first_reported_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
            approval="pending", notified_user_ids=[],
        ).model_dump(mode="json")

    monkeypatch.setattr(
        support_agent_service.ticket_dedup_service, "check_and_resolve_ticket", fake_check_and_resolve_ticket,
    )

    fake_gemini = _FakeGeminiClient(_classification_json("bug"))
    conversation_id = f"conv_jarvis_producer_test_{ObjectId()}"
    try:
        async def _do():
            return await support_agent_service.handle_support_message(
                _db(), fake_gemini, http_client=None,
                internal_ticket_api_token="tok", user_id="user_producer_test",
                conversation_id=conversation_id,
                message="Font size on itinerary page is too small.",
            )
        result = _run(_do())
        assert result.category == "bug"

        # Verify Denver enqueued a jarvis_queue_items record
        async def _check_queue():
            db = _db()
            item = await db.jarvis_queue_items.find_one({"source_agent": "denver", "item_type": "ticket_review", "payload.ticket_id": ticket_id})
            assert item is not None, "expected a jarvis_queue_items entry from Denver"
            assert item["priority"] == 5  # normal priority
            assert item["status"] == "pending"
            assert item["payload"]["title"] == "Font size on itinerary page is too small."
            assert item["payload"]["conversation_id"] == conversation_id
        _run(_check_queue())
    finally:
        _cleanup_generation_logs(conversation_id)
        async def _cleanup_q():
            await _db().jarvis_queue_items.delete_many({"source_agent": "denver", "payload.ticket_id": ticket_id})
        _run(_cleanup_q())


def test_critical_keyword_enqueues_with_priority_1(monkeypatch):
    """When a bug report involves payments/checkout/auth, Denver sets priority=1."""
    ticket_id = f"ticket_crit_{ObjectId()}"

    async def fake_check_and_resolve_ticket(gemini_client, http_client, **kwargs):
        return support_agent_service.TicketDoc(
            id=ticket_id, title=kwargs["title"], description=kwargs["description"],
            kind=kwargs["kind"], status="reported",
            reporter_user_ids=[kwargs["reporter_user_id"]], linked_chat_sessions=[],
            first_reported_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
            approval="pending", notified_user_ids=[],
        ).model_dump(mode="json")

    monkeypatch.setattr(
        support_agent_service.ticket_dedup_service, "check_and_resolve_ticket", fake_check_and_resolve_ticket,
    )

    fake_gemini = _FakeGeminiClient(_classification_json("bug"))
    conversation_id = f"conv_jarvis_crit_test_{ObjectId()}"
    try:
        async def _do():
            return await support_agent_service.handle_support_message(
                _db(), fake_gemini, http_client=None,
                internal_ticket_api_token="tok", user_id="user_crit_test",
                conversation_id=conversation_id,
                message="Stripe checkout payment failed with error 500.",
            )
        result = _run(_do())
        assert result.category == "bug"

        # Verify priority is 1
        async def _check_queue():
            db = _db()
            item = await db.jarvis_queue_items.find_one({"source_agent": "denver", "payload.ticket_id": ticket_id})
            assert item is not None
            assert item["priority"] == 1, "expected priority 1 for payment/checkout keyword"
        _run(_check_queue())
    finally:
        _cleanup_generation_logs(conversation_id)
        async def _cleanup_q():
            await _db().jarvis_queue_items.delete_many({"source_agent": "denver", "payload.ticket_id": ticket_id})
        _run(_cleanup_q())


def test_support_escalation_enqueues_escalation_for_jarvis(monkeypatch):
    """When ticket creation fails, Denver enqueues a priority=1 support_escalation item."""
    async def fake_failing_check(*args, **kwargs):
        raise RuntimeError("Ticket API unavailable")

    monkeypatch.setattr(
        support_agent_service.ticket_dedup_service, "check_and_resolve_ticket", fake_failing_check,
    )

    fake_gemini = _FakeGeminiClient(_classification_json("bug"))
    conversation_id = f"conv_jarvis_escalate_test_{ObjectId()}"
    try:
        async def _do():
            return await support_agent_service.handle_support_message(
                _db(), fake_gemini, http_client=None,
                internal_ticket_api_token="tok", user_id="user_escalate_test",
                conversation_id=conversation_id,
                message="Something is completely broken.",
            )
        result = _run(_do())
        assert result.escalated is True

        # Verify support_escalation queue item
        async def _check_queue():
            db = _db()
            item = await db.jarvis_queue_items.find_one({"source_agent": "denver", "item_type": "support_escalation", "payload.conversation_id": conversation_id})
            assert item is not None, "expected support_escalation item enqueued for JARVIS"
            assert item["priority"] == 1
            assert "ticket creation failed" in item["payload"]["reason"]
        _run(_check_queue())
    finally:
        _cleanup_generation_logs(conversation_id)
        async def _cleanup_q():
            await _db().jarvis_queue_items.delete_many({"source_agent": "denver", "payload.conversation_id": conversation_id})
        _run(_cleanup_q())


def test_duplicate_report_does_not_reenqueue_existing_item(monkeypatch):
    """When a bug report is appended to an existing ticket, Denver must NOT create a duplicate queue item."""
    ticket_id = f"ticket_dup_{ObjectId()}"

    async def fake_check_and_resolve_ticket(gemini_client, http_client, **kwargs):
        return support_agent_service.TicketDoc(
            id=ticket_id, title="Button broken", description="Button broken",
            kind="bug", status="reported",
            reporter_user_ids=["user_1", "user_2"], linked_chat_sessions=[],
            first_reported_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
            approval="pending", notified_user_ids=[],
        ).model_dump(mode="json")

    monkeypatch.setattr(
        support_agent_service.ticket_dedup_service, "check_and_resolve_ticket", fake_check_and_resolve_ticket,
    )

    fake_gemini = _FakeGeminiClient(_classification_json("bug"), _classification_json("bug"))
    conv_1 = f"conv_dup_test_1_{ObjectId()}"
    conv_2 = f"conv_dup_test_2_{ObjectId()}"
    try:
        async def _do():
            # First turn -> creates queue item
            await support_agent_service.handle_support_message(
                _db(), fake_gemini, http_client=None, internal_ticket_api_token="tok",
                user_id="user_1", conversation_id=conv_1, message="Button broken",
            )
            # Second turn (duplicate) -> should NOT create a second queue item
            await support_agent_service.handle_support_message(
                _db(), fake_gemini, http_client=None, internal_ticket_api_token="tok",
                user_id="user_2", conversation_id=conv_2, message="Button broken",
            )
        _run(_do())

        # Verify exactly ONE queue item exists
        async def _check_count():
            db = _db()
            count = await db.jarvis_queue_items.count_documents({
                "source_agent": "denver",
                "item_type": "ticket_review",
                "payload.ticket_id": ticket_id,
            })
            assert count == 1, f"expected 1 queue item, got {count}"
        _run(_check_count())
    finally:
        _cleanup_generation_logs(conv_1)
        _cleanup_generation_logs(conv_2)
        async def _cleanup_q():
            await _db().jarvis_queue_items.delete_many({"source_agent": "denver", "payload.ticket_id": ticket_id})
        _run(_cleanup_q())


def test_duplicate_report_boosts_priority_when_reporter_count_reaches_three(monkeypatch):
    """When 3 or more users report the same issue, priority is boosted to 1."""
    ticket_id = f"ticket_boost_{ObjectId()}"
    reporters = ["u1"]

    async def fake_check_and_resolve_ticket(gemini_client, http_client, **kwargs):
        return support_agent_service.TicketDoc(
            id=ticket_id, title="Itinerary lag", description="Itinerary lag",
            kind="bug", status="reported",
            reporter_user_ids=list(reporters), linked_chat_sessions=[],
            first_reported_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
            approval="pending", notified_user_ids=[],
        ).model_dump(mode="json")

    monkeypatch.setattr(
        support_agent_service.ticket_dedup_service, "check_and_resolve_ticket", fake_check_and_resolve_ticket,
    )

    fake_gemini = _FakeGeminiClient(_classification_json("bug"), _classification_json("bug"))
    conv_1 = f"conv_boost_test_1_{ObjectId()}"
    conv_3 = f"conv_boost_test_3_{ObjectId()}"
    try:
        async def _do():
            # First turn: 1 reporter -> priority 5
            await support_agent_service.handle_support_message(
                _db(), fake_gemini, http_client=None, internal_ticket_api_token="tok",
                user_id="u1", conversation_id=conv_1, message="Itinerary page has lag",
            )
            item_initial = await _db().jarvis_queue_items.find_one({"payload.ticket_id": ticket_id})
            assert item_initial["priority"] == 5

            # Third reporter joins
            reporters.extend(["u2", "u3"])
            await support_agent_service.handle_support_message(
                _db(), fake_gemini, http_client=None, internal_ticket_api_token="tok",
                user_id="u3", conversation_id=conv_3, message="Itinerary page has lag",
            )

            # Priority boosted to 1
            item_boosted = await _db().jarvis_queue_items.find_one({"payload.ticket_id": ticket_id})
            assert item_boosted["priority"] == 1
            assert len(item_boosted["payload"]["reporter_user_ids"]) == 3
        _run(_do())
    finally:
        _cleanup_generation_logs(conv_1)
        _cleanup_generation_logs(conv_3)
        async def _cleanup_q():
            await _db().jarvis_queue_items.delete_many({"source_agent": "denver", "payload.ticket_id": ticket_id})
        _run(_cleanup_q())


def test_escalation_flood_prevention_does_not_duplicate_pending_escalations(monkeypatch):
    """Multiple error turns in the same conversation do not spam duplicate pending escalations."""
    async def fake_failing_check(*args, **kwargs):
        raise RuntimeError("DB connection timeout")

    monkeypatch.setattr(
        support_agent_service.ticket_dedup_service, "check_and_resolve_ticket", fake_failing_check,
    )

    fake_gemini = _FakeGeminiClient(_classification_json("bug"), _classification_json("bug"))
    conv_id = f"conv_flood_test_{ObjectId()}"
    try:
        async def _do():
            # Turn 1 -> enqueues escalation
            await support_agent_service.handle_support_message(
                _db(), fake_gemini, http_client=None, internal_ticket_api_token="tok",
                user_id="u_flood", conversation_id=conv_id, message="Error 1",
            )
            # Turn 2 -> should not create second escalation
            await support_agent_service.handle_support_message(
                _db(), fake_gemini, http_client=None, internal_ticket_api_token="tok",
                user_id="u_flood", conversation_id=conv_id, message="Error 2",
            )

            count = await _db().jarvis_queue_items.count_documents({
                "source_agent": "denver",
                "item_type": "support_escalation",
                "payload.conversation_id": conv_id,
            })
            assert count == 1
        _run(_do())
    finally:
        _cleanup_generation_logs(conv_id)
        async def _cleanup_q():
            await _db().jarvis_queue_items.delete_many({"source_agent": "denver", "payload.conversation_id": conv_id})
        _run(_cleanup_q())


def test_transient_quota_error_does_not_enqueue_emergency_escalation(monkeypatch):
    """When Gemini throws a 429 quota error, Denver returns a gentle retry message and does not page JARVIS."""
    async def fake_quota_error(*args, **kwargs):
        raise RuntimeError("429 ResourceExhausted: Quota exceeded for model gemini-2.5-flash")

    monkeypatch.setattr(
        support_agent_service, "classify_message", fake_quota_error,
    )

    conv_id = f"conv_quota_test_{ObjectId()}"
    try:
        async def _do():
            result = await support_agent_service.handle_support_message(
                _db(), None, http_client=None, internal_ticket_api_token="tok",
                user_id="u_quota", conversation_id=conv_id, message="Hello support",
            )
            assert result.category == "other"
            assert "high load" in result.reply
            assert result.escalated is False

            count = await _db().jarvis_queue_items.count_documents({
                "source_agent": "denver",
                "payload.conversation_id": conv_id,
            })
            assert count == 0, "Quota errors should not enqueue queue items"
        _run(_do())
    finally:
        _cleanup_generation_logs(conv_id)


def test_word_boundary_avoids_keyword_false_positives(monkeypatch):
    """Words like 'author' should not trigger priority 1 'auth' keyword matching."""
    ticket_id = f"ticket_kw_{ObjectId()}"

    async def fake_check_and_resolve_ticket(gemini_client, http_client, **kwargs):
        return support_agent_service.TicketDoc(
            id=ticket_id, title=kwargs["title"], description=kwargs["description"],
            kind=kwargs["kind"], status="reported",
            reporter_user_ids=["u_kw"], linked_chat_sessions=[],
            first_reported_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
            approval="pending", notified_user_ids=[],
        ).model_dump(mode="json")

    monkeypatch.setattr(
        support_agent_service.ticket_dedup_service, "check_and_resolve_ticket", fake_check_and_resolve_ticket,
    )

    fake_gemini = _FakeGeminiClient(_classification_json("feature"))
    conv_id = f"conv_kw_test_{ObjectId()}"
    try:
        async def _do():
            await support_agent_service.handle_support_message(
                _db(), fake_gemini, http_client=None, internal_ticket_api_token="tok",
                user_id="u_kw", conversation_id=conv_id,
                message="I am the author of a guidebook and would like a blog integration",
            )
            item = await _db().jarvis_queue_items.find_one({"payload.ticket_id": ticket_id})
            assert item is not None
            assert item["priority"] == 5, "expected priority 5 (normal) because 'author' != 'auth'"
        _run(_do())
    finally:
        _cleanup_generation_logs(conv_id)
        async def _cleanup_q():
            await _db().jarvis_queue_items.delete_many({"source_agent": "denver", "payload.ticket_id": ticket_id})
        _run(_cleanup_q())


