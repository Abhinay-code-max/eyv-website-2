"""
Tests for services/ticket_dedup_service.py (EYV Agent System, Phase 4 Step 4.2).

Same fake-Gemini-client pattern as test_support_agent_service.py's
classification tests (a fake `.aio.models.generate_content_stream` that
streams back canned JSON text, and records every call's kwargs so a test
can inspect exactly what was sent). HTTP calls to the internal ticket API
(GET /queue, PATCH /{id}, POST /) go through a fake httpx.AsyncClient-shaped
object rather than a real in-process ASGI call through conftest.py's shared
`client` fixture - see test_support_agent_service.py's own "create_or_append_ticket"
section for why that was tried first and reverted (it corrupts the shared
TestClient's Motor client binding across a second, independently-created
event loop).
"""
import asyncio
import json
import os
import sys
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from services import ticket_dedup_service  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ═══════════════ Fake Gemini client (dedup check) ═══════════════

class _FakeModels:
    """Stands in for gemini_client.aio.models - returns one canned response
    text per call, in order (call N uses responses[N], the last entry
    reused for any further calls beyond the list), and records every
    call's kwargs so a test can inspect exactly what prompt was sent."""
    def __init__(self, responses):
        self._responses = responses
        self.call_count = 0
        self.calls: List[Dict[str, Any]] = []

    async def generate_content_stream(self, *args, **kwargs):
        self.calls.append(kwargs)
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


def _dedup_json(is_match: bool, matched_ticket_id: str = "") -> str:
    return json.dumps({"is_match": is_match, "matched_ticket_id": matched_ticket_id})


# ═══════════════ Fake internal ticket API HTTP client ═══════════════

class _FakeInternalTicketAPIClient:
    """Stands in for httpx.AsyncClient. `queue_tickets` is the canned
    GET /queue response body; `create_response`/`patch_response` are
    canned bodies for POST / and PATCH /{id} respectively (PATCH's default
    just echoes back whatever the request tried to set, layered onto the
    matched candidate, which is enough for these tests without needing a
    real Mongo round-trip). Every request is recorded for assertions."""
    def __init__(self, *, queue_tickets, create_response=None, patch_response_fn=None):
        self.queue_tickets = queue_tickets
        self.create_response = create_response or {}
        self.patch_response_fn = patch_response_fn
        self.requests: List[SimpleNamespace] = []

    async def get(self, path, *, params=None, headers=None):
        self.requests.append(SimpleNamespace(method="GET", path=path, params=params, headers=headers))
        return SimpleNamespace(
            status_code=200,
            json=lambda: {"tickets": self.queue_tickets, "status_filter": []},
            raise_for_status=lambda: None,
        )

    async def patch(self, path, *, json=None, headers=None):
        self.requests.append(SimpleNamespace(method="PATCH", path=path, json=json, headers=headers))
        if self.patch_response_fn:
            body = self.patch_response_fn(path, json)
        else:
            body = json
        return SimpleNamespace(status_code=200, json=lambda: body, raise_for_status=lambda: None)

    async def post(self, path, *, json=None, headers=None):
        self.requests.append(SimpleNamespace(method="POST", path=path, json=json, headers=headers))
        return SimpleNamespace(status_code=200, json=lambda: self.create_response, raise_for_status=lambda: None)


def _ticket(**overrides) -> Dict[str, Any]:
    ticket = {
        "id": "ticket_1",
        "title": "Refund button does nothing",
        "description": "Clicking Request Refund on a cancelled Goa hotel booking shows no confirmation and nothing happens.",
        "kind": "bug",
        "status": "reported",
        "reporter_user_ids": ["user_original"],
        "linked_chat_sessions": [],
        "first_reported_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "agent_plan": None,
        "agent_diff_summary": None,
        "approval": "pending",
        "approval_note": None,
        "implementation_commit": None,
        "notified_user_ids": [],
    }
    ticket.update(overrides)
    return ticket


# ═══════════════ Dedup matching ═══════════════

def test_same_issue_different_wording_matches():
    """The fake Gemini response IS the thing under test here (this module
    doesn't call a real model) - what's being confirmed is that a
    same-issue verdict from the model is correctly parsed, validated, and
    resolved back to the right candidate dict, and that the caller then
    appends rather than creates."""
    candidate = _ticket(id="ticket_1", title="Refund button broken", reporter_user_ids=["user_a"])
    fake_gemini = _FakeGeminiClient(_dedup_json(True, "ticket_1"))
    fake_http = _FakeInternalTicketAPIClient(queue_tickets=[candidate])

    result = _run(ticket_dedup_service.check_and_resolve_ticket(
        fake_gemini, fake_http,
        internal_ticket_api_token="tok",
        title="Cancel + refund flow is unresponsive",
        description="I tapped Request Refund on my cancelled booking and nothing happened - no error, no confirmation.",
        kind="bug",
        reporter_user_id="user_b",
    ))

    patch_requests = [r for r in fake_http.requests if r.method == "PATCH"]
    post_requests = [r for r in fake_http.requests if r.method == "POST"]
    assert len(patch_requests) == 1, "expected an append (PATCH), not a create"
    assert not post_requests, "must not create a duplicate ticket on a match"
    assert patch_requests[0].path == "/api/internal/tickets/ticket_1"
    assert patch_requests[0].json == {"reporter_user_ids": ["user_a", "user_b"]}
    assert result["reporter_user_ids"] == ["user_a", "user_b"]


def test_genuinely_different_issue_same_kind_does_not_match():
    candidate = _ticket(id="ticket_1", title="Refund button broken")
    fake_gemini = _FakeGeminiClient(_dedup_json(False))
    create_response = _ticket(id="ticket_2", title="Currency symbol wrong for INR trips",
                               description="INR trips show a $ instead of ₹.", reporter_user_ids=["user_b"])
    fake_http = _FakeInternalTicketAPIClient(queue_tickets=[candidate], create_response=create_response)

    result = _run(ticket_dedup_service.check_and_resolve_ticket(
        fake_gemini, fake_http,
        internal_ticket_api_token="tok",
        title="Currency symbol wrong for INR trips",
        description="INR trips show a $ instead of ₹.",
        kind="bug",
        reporter_user_id="user_b",
    ))

    patch_requests = [r for r in fake_http.requests if r.method == "PATCH"]
    post_requests = [r for r in fake_http.requests if r.method == "POST"]
    assert not patch_requests, "must not append to an unrelated ticket"
    assert len(post_requests) == 1, "expected a new ticket to be created on no match"
    assert result["id"] == "ticket_2"


def test_ambiguous_case_documents_the_no_match_default():
    """Genuinely ambiguous case: 'the checkout page is slow' vs. an
    existing 'hotel search results take forever to load' ticket - related
    area, not obviously the same root cause. This module's system prompt
    (_DEDUP_SYSTEM_MESSAGE) explicitly instructs the model to answer
    no-match whenever it isn't confident, on the reasoning that a missed
    match just costs a slightly redundant ticket, while a wrong match
    would silently conflate two different problems under one ticket. This
    test documents and locks in that policy at the code level: given a
    response reflecting genuine model uncertainty (is_match=false), the
    result is a new ticket, not a forced/guessed append - it does not (and
    given the system prompt, should not) resolve ambiguity by matching."""
    candidate = _ticket(id="ticket_1", title="Hotel search results take forever to load")
    fake_gemini = _FakeGeminiClient(_dedup_json(False))
    create_response = _ticket(id="ticket_2", title="Checkout page is slow", reporter_user_ids=["user_b"])
    fake_http = _FakeInternalTicketAPIClient(queue_tickets=[candidate], create_response=create_response)

    result = _run(ticket_dedup_service.check_and_resolve_ticket(
        fake_gemini, fake_http,
        internal_ticket_api_token="tok",
        title="Checkout page is slow",
        description="The whole checkout page takes a long time to respond after I click Pay.",
        kind="bug",
        reporter_user_id="user_b",
    ))
    assert result["id"] == "ticket_2"
    assert not [r for r in fake_http.requests if r.method == "PATCH"]


def test_no_candidates_skips_gemini_call_and_creates():
    fake_gemini = _FakeGeminiClient(_dedup_json(False))
    create_response = _ticket(id="ticket_new", reporter_user_ids=["user_b"])
    fake_http = _FakeInternalTicketAPIClient(queue_tickets=[], create_response=create_response)

    result = _run(ticket_dedup_service.check_and_resolve_ticket(
        fake_gemini, fake_http, internal_ticket_api_token="tok",
        title="T", description="D", kind="bug", reporter_user_id="user_b",
    ))

    assert fake_gemini.aio.models.call_count == 0, "no candidates means nothing to compare against - Gemini shouldn't even be asked"
    assert result["id"] == "ticket_new"


def test_hallucinated_matched_ticket_id_is_treated_as_no_match():
    """The model claims a match against an id that was never in the
    candidate list sent to it - must not be trusted blindly (same "never
    silent coercion" discipline as classify_message)."""
    candidate = _ticket(id="ticket_1")
    fake_gemini = _FakeGeminiClient(_dedup_json(True, "ticket_does_not_exist"))
    create_response = _ticket(id="ticket_new", reporter_user_ids=["user_b"])
    fake_http = _FakeInternalTicketAPIClient(queue_tickets=[candidate], create_response=create_response)

    result = _run(ticket_dedup_service.check_and_resolve_ticket(
        fake_gemini, fake_http, internal_ticket_api_token="tok",
        title="T", description="D", kind="bug", reporter_user_id="user_b",
    ))
    assert result["id"] == "ticket_new"
    assert not [r for r in fake_http.requests if r.method == "PATCH"]


def test_self_contradictory_response_retries_then_falls_back_to_no_match():
    """is_match=true with an empty matched_ticket_id fails DedupResult's
    own consistency check - retried, and since every attempt here is
    equally broken, this must fall back to 'no match' (create a new
    ticket) rather than raising and blocking ticket creation entirely."""
    candidate = _ticket(id="ticket_1")
    fake_gemini = _FakeGeminiClient(
        json.dumps({"is_match": True, "matched_ticket_id": ""}),
        "not json at all",
        json.dumps({"is_match": True, "matched_ticket_id": ""}),
    )
    create_response = _ticket(id="ticket_new", reporter_user_ids=["user_b"])
    fake_http = _FakeInternalTicketAPIClient(queue_tickets=[candidate], create_response=create_response)

    result = _run(ticket_dedup_service.check_and_resolve_ticket(
        fake_gemini, fake_http, internal_ticket_api_token="tok",
        title="T", description="D", kind="bug", reporter_user_id="user_b",
    ))
    assert fake_gemini.aio.models.call_count == 3
    assert result["id"] == "ticket_new"


# ═══════════════ Candidate-list cap ═══════════════

def test_candidate_list_capped_at_thirty_even_with_larger_backlog():
    backlog = [_ticket(id=f"ticket_{i}", title=f"Issue number {i}") for i in range(75)]
    fake_http = _FakeInternalTicketAPIClient(queue_tickets=backlog)

    candidates = _run(ticket_dedup_service._fetch_open_candidates(
        fake_http, internal_ticket_api_token="tok", kind="bug",
    ))
    assert len(candidates) == ticket_dedup_service.CANDIDATE_LIMIT == 30

    get_requests = [r for r in fake_http.requests if r.method == "GET"]
    assert len(get_requests) == 1, "must be a single queue call, not one per status"
    statuses_requested = [v for k, v in get_requests[0].params if k == "status"]
    assert set(statuses_requested) == set(ticket_dedup_service.OPEN_TICKET_STATUSES)


def test_candidate_list_cap_reflected_in_what_gemini_actually_sees():
    """End-to-end version of the cap test above: even with 75 open tickets
    of the same kind in the (fake) queue, the dedup prompt actually sent to
    Gemini never mentions more than 30 candidate ids."""
    backlog = [_ticket(id=f"ticket_{i}", title=f"Issue number {i}") for i in range(75)]
    fake_gemini = _FakeGeminiClient(_dedup_json(False))
    create_response = _ticket(id="ticket_new", reporter_user_ids=["user_b"])
    fake_http = _FakeInternalTicketAPIClient(queue_tickets=backlog, create_response=create_response)

    _run(ticket_dedup_service.check_and_resolve_ticket(
        fake_gemini, fake_http, internal_ticket_api_token="tok",
        title="T", description="D", kind="bug", reporter_user_id="user_b",
    ))

    assert fake_gemini.aio.models.call_count == 1
    sent_prompt = fake_gemini.aio.models.calls[0]["contents"]
    for i in range(30, 75):
        assert f"ticket_{i}" not in sent_prompt


# ═══════════════ Idempotency ═══════════════

def test_append_reporter_is_a_noop_when_already_present():
    ticket = _ticket(id="ticket_1", reporter_user_ids=["user_a", "user_b"])
    fake_http = _FakeInternalTicketAPIClient(queue_tickets=[])

    result = _run(ticket_dedup_service._append_reporter(
        fake_http, internal_ticket_api_token="tok", ticket=ticket, reporter_user_id="user_b",
    ))
    assert result == ticket
    assert not fake_http.requests, "no PATCH should be sent when the reporter is already on the ticket"


def test_same_user_same_issue_reported_twice_appears_exactly_once():
    """The task's own idempotency requirement: submitting the same report
    from the same user twice must not duplicate them in reporter_user_ids.
    Simulates two full check_and_resolve_ticket calls for the same
    user/issue - the queue snapshot between calls reflects the first
    call's PATCH having already landed (same as it would against a real
    Mongo-backed API), and the second call must recognize the reporter is
    already present and skip the write."""
    ticket_state = _ticket(id="ticket_1", reporter_user_ids=["user_original"])

    def patch_response_fn(path, body):
        ticket_state.update(body)
        return dict(ticket_state)

    fake_gemini = _FakeGeminiClient(_dedup_json(True, "ticket_1"), _dedup_json(True, "ticket_1"))
    fake_http = _FakeInternalTicketAPIClient(queue_tickets=[ticket_state], patch_response_fn=patch_response_fn)

    async def _report_once():
        return await ticket_dedup_service.check_and_resolve_ticket(
            fake_gemini, fake_http, internal_ticket_api_token="tok",
            title="Refund button broken", description="Same issue, reported again.",
            kind="bug", reporter_user_id="user_new",
        )

    first = _run(_report_once())
    assert first["reporter_user_ids"] == ["user_original", "user_new"]

    second = _run(_report_once())
    assert second["reporter_user_ids"].count("user_new") == 1
    assert second["reporter_user_ids"] == ["user_original", "user_new"]

    patch_requests = [r for r in fake_http.requests if r.method == "PATCH"]
    assert len(patch_requests) == 1, "the second report of the same issue by the same user must not send a second PATCH"
