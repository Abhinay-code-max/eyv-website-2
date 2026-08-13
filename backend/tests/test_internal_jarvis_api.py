"""
Tests for internal_jarvis_api.py - the /jarvis/* JARVIS-poller-token-gated
API. Uses conftest.py's in-process `client` (starlette TestClient over
server.app), same reasoning as test_internal_tickets_api.py's own module
docstring: this file's rate-limit tests need a real, in-process request
volume against one shared TestClient/Limiter instance, and a live uvicorn
process wouldn't let a monkeypatch-based rotation test (if one is ever
added here) observe an os.environ change from this test process anyway.

Every test that hits a real Mongo collection uses its own fresh
AsyncIOMotorClient (this file's own _db()/_run()), never server.py's global
`db` directly - same cross-loop reasoning as test_internal_tickets_api.py's
own docstring (TestClient drives the app in a background thread with its
own event loop).

JARVIS_QUEUE_API_TOKEN must already be set in the environment before this
file (or any file - server.py imports internal_jarvis_api unconditionally)
is collected, exactly like INTERNAL_TICKET_API_TOKEN/
INTERNAL_ANALYTICS_API_TOKEN already must be.
"""
import ast
import asyncio
import inspect
import os
import sys
import uuid
from datetime import datetime, timezone

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from conftest import client  # noqa: E402,F401  (fixture import)

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')
VALID_TOKEN = os.environ['JARVIS_QUEUE_API_TOKEN']
AUTH_HEADERS = {"Authorization": f"Bearer {VALID_TOKEN}"}


def _db():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _run(coro):
    return asyncio.run(coro)


def _seed_ticket(**overrides) -> str:
    async def _do():
        db = _db()
        now = datetime.now(timezone.utc)
        doc = {
            "title": "Test ticket", "description": "Something is wrong",
            "kind": "bug", "status": "reported",
            "reporter_user_ids": ["user_test_reporter"], "linked_chat_sessions": [],
            "first_reported_at": now, "updated_at": now,
            "agent_plan": None, "agent_diff_summary": None,
            "approval": "pending", "approval_note": None, "implementation_commit": None,
            "notified_user_ids": [],
        }
        doc.update(overrides)
        result = await db.tickets.insert_one(doc)
        return str(result.inserted_id)
    return _run(_do())


def _cleanup_ticket(ticket_id: str) -> None:
    async def _do():
        db = _db()
        await db.tickets.delete_one({"_id": ObjectId(ticket_id)})
    _run(_do())


def _recent_audit_entries(route: str = None, limit: int = 20):
    async def _do():
        db = _db()
        query = {}
        if route:
            query["route"] = route
        cursor = db.jarvis_agent_audit_log.find(query).sort("timestamp", -1).limit(limit)
        return await cursor.to_list(limit)
    return _run(_do())


# ═══════════════ Auth: correct / wrong / missing token ═══════════════

def test_correct_token_succeeds(client):
    r = client.get("/jarvis/queue", headers=AUTH_HEADERS)
    assert r.status_code == 200, r.text
    assert "tickets" in r.json()


def test_wrong_token_rejected_and_logged_as_failed_attempt(client):
    r = client.get(
        "/jarvis/queue",
        headers={"Authorization": "Bearer definitely-the-wrong-token"},
    )
    assert r.status_code == 401, r.text

    entries = _recent_audit_entries(route="/jarvis/queue")
    assert entries, "expected at least one audit log entry for GET /jarvis/queue"
    latest = entries[0]
    assert latest["status_code"] == 401
    assert latest["summary"].get("auth") == "rejected", (
        f"expected the failed attempt to be logged as an auth rejection, got {latest['summary']}"
    )


def test_no_token_at_all_rejected_and_logged(client):
    r = client.get("/jarvis/queue")
    assert r.status_code == 401, r.text

    entries = _recent_audit_entries(route="/jarvis/queue")
    assert entries[0]["status_code"] == 401
    assert entries[0]["summary"].get("auth") == "rejected"


# ═══════════════ Scope: token/module isolation ═══════════════

def test_valid_jarvis_token_rejected_on_unrelated_route(client):
    """A valid /jarvis/* token must have zero special meaning anywhere else
    - require_jarvis_queue_token is only wired onto this one router. GET
    /api/bookings expects a session token/cookie; a JARVIS-API token
    doesn't hash to any real session, so this must 401 like any other
    garbage bearer value would."""
    r = client.get("/api/bookings", headers=AUTH_HEADERS)
    assert r.status_code == 401, r.text


def test_valid_ticket_agent_token_rejected_on_jarvis_route(client):
    """The reverse: JARVIS's token is a distinct credential from
    INTERNAL_TICKET_API_TOKEN (per B.1's design) - a valid ticket-agent
    token must not authenticate against /jarvis/*."""
    ticket_token = os.environ.get('INTERNAL_TICKET_API_TOKEN')
    if not ticket_token or ticket_token == VALID_TOKEN:
        return  # nothing meaningful to assert if the two tokens coincide
    r = client.get("/jarvis/queue", headers={"Authorization": f"Bearer {ticket_token}"})
    assert r.status_code == 401, r.text


def test_module_never_references_user_or_booking_or_payment_collections():
    """Static confirmation of the scope boundary in internal_jarvis_api.py's
    module docstring (section 2): this module must never touch
    db.users/db.bookings/db.payment_transactions, even indirectly - it only
    ever queries db.tickets and db.jarvis_agent_audit_log.

    AST-based, not a raw substring search - same reasoning as
    test_internal_tickets_api.py's own test_module_never_references_...:
    this module's own docstring mentions "db.users" etc. in prose, which a
    plain string search would misfire on."""
    import internal_jarvis_api
    source = inspect.getsource(internal_jarvis_api)
    tree = ast.parse(source)
    forbidden_attrs = {"users", "bookings", "payment_transactions"}
    real_references = sorted({
        node.attr for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in forbidden_attrs
    })
    assert not real_references, f"internal_jarvis_api.py has real code referencing db.{real_references}"

    forbidden_imports = {"UserDoc", "SingleItemBookingDoc", "BundleBookingDoc", "PaymentTransactionDoc"}
    imported_names = {
        alias.asname or alias.name
        for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert not (imported_names & forbidden_imports), (
        f"internal_jarvis_api.py unexpectedly imports {imported_names & forbidden_imports}"
    )


# ═══════════════ Route: queue behavior ═══════════════

def test_queue_only_returns_approved_tickets_by_default(client):
    """The core schema decision (see internal_jarvis_api.py's module
    docstring): JARVIS only ever sees approval="approved" tickets, even
    though a "reported" or "triaged" ticket also exists in db.tickets."""
    reported_id = _seed_ticket(status="reported", approval="pending")
    approved_id = _seed_ticket(status="approved", approval="approved")
    try:
        r = client.get("/jarvis/queue", headers=AUTH_HEADERS)
        assert r.status_code == 200, r.text
        ids = {t["id"] for t in r.json()["tickets"]}
        assert approved_id in ids
        assert reported_id not in ids
        for t in r.json()["tickets"]:
            assert t["approval"] == "approved"
    finally:
        _cleanup_ticket(reported_id)
        _cleanup_ticket(approved_id)


def test_queue_never_returns_a_ticket_whose_status_is_approved_but_approval_is_not(client):
    """approval="approved" is required unconditionally, independent of
    `status` - a ticket that reached status="approved" without a matching
    approval field (shouldn't happen via the tickets API's own PATCH route,
    but this route doesn't trust that invariant blindly) must not appear."""
    inconsistent_id = _seed_ticket(status="approved", approval="pending")
    try:
        r = client.get("/jarvis/queue", headers=AUTH_HEADERS)
        assert r.status_code == 200, r.text
        ids = {t["id"] for t in r.json()["tickets"]}
        assert inconsistent_id not in ids
    finally:
        _cleanup_ticket(inconsistent_id)


def test_queue_accepts_additional_status_values_still_gated_by_approval(client):
    """`status` can narrow/widen which approved-and-ready tickets come back
    (e.g. also including ones parked in "backlog") - but every result is
    still approval="approved" regardless of which status value matched."""
    approved_backlog_id = _seed_ticket(status="backlog", approval="approved")
    approved_id = _seed_ticket(status="approved", approval="approved")
    try:
        r = client.get("/jarvis/queue?status=approved&status=backlog", headers=AUTH_HEADERS)
        assert r.status_code == 200, r.text
        ids = {t["id"] for t in r.json()["tickets"]}
        assert approved_backlog_id in ids
        assert approved_id in ids
    finally:
        _cleanup_ticket(approved_backlog_id)
        _cleanup_ticket(approved_id)


def test_queue_filters_by_kind(client):
    bug_id = _seed_ticket(status="approved", approval="approved", kind="bug")
    feature_id = _seed_ticket(status="approved", approval="approved", kind="feature")
    try:
        r = client.get("/jarvis/queue?kind=bug", headers=AUTH_HEADERS)
        assert r.status_code == 200, r.text
        ids = {t["id"] for t in r.json()["tickets"]}
        assert bug_id in ids
        assert feature_id not in ids
    finally:
        _cleanup_ticket(bug_id)
        _cleanup_ticket(feature_id)


def test_queue_rejects_invalid_status_value(client):
    r = client.get("/jarvis/queue?status=not-a-real-status", headers=AUTH_HEADERS)
    assert r.status_code == 422, r.text


def test_queue_sorted_oldest_approved_first(client):
    """Deliberately the OPPOSITE sort order from internal_tickets_api.py's
    GET /queue (newest-first, admin view) - see this module's own docstring
    for why: FIFO so an early approval doesn't get starved."""
    now = datetime.now(timezone.utc)
    older_id = _seed_ticket(status="approved", approval="approved", updated_at=now.replace(microsecond=0))
    from datetime import timedelta
    newer_id = _seed_ticket(
        status="approved", approval="approved",
        updated_at=now.replace(microsecond=0) + timedelta(seconds=30),
    )
    try:
        r = client.get("/jarvis/queue", headers=AUTH_HEADERS)
        assert r.status_code == 200, r.text
        ids_in_order = [t["id"] for t in r.json()["tickets"] if t["id"] in (older_id, newer_id)]
        assert ids_in_order == [older_id, newer_id], (
            f"expected oldest-updated_at-first ordering, got {ids_in_order}"
        )
    finally:
        _cleanup_ticket(older_id)
        _cleanup_ticket(newer_id)


def test_queue_response_records_audit_summary(client):
    approved_id = _seed_ticket(status="approved", approval="approved", kind="bug")
    try:
        r = client.get("/jarvis/queue?kind=bug", headers=AUTH_HEADERS)
        assert r.status_code == 200, r.text
        entries = _recent_audit_entries(route="/jarvis/queue")
        assert entries, "expected an audit entry for GET /jarvis/queue"
        assert entries[0]["summary"]["kind_filter"] == "bug"
    finally:
        _cleanup_ticket(approved_id)


# ═══════════════ Rate limiting - LAST in the file, deliberately ═══════════════
# Same reasoning as test_internal_tickets_api.py's own trailing rate-limit
# tests: every GET /jarvis/queue call above (and the wrong-token calls)
# shares one bucket per limiter (keyed by the shared TestClient's simulated
# "testclient" IP), so these run last and send comfortably more than each
# budget to be robust to whatever the tests above already spent.

def test_rate_limit_enforced_on_queue_route(client):
    statuses = []
    for _ in range(75):
        r = client.get("/jarvis/queue", headers=AUTH_HEADERS)
        statuses.append(r.status_code)
        if r.status_code == 429:
            break
    assert 429 in statuses, (
        f"expected a 429 within 75 requests once the 60/minute budget was "
        f"exhausted, got status codes: {sorted(set(statuses))}"
    )


def test_wrong_token_requests_are_rate_limited_too(client):
    """The fix (reused from internal_tickets_api.py): wrong-token requests
    never reach get_jarvis_queue (and therefore never reach its own
    @_limiter.limit(JARVIS_QUEUE_API_RATE_LIMIT) decorator), so on their own
    they'd be completely unbounded. AUTH_GATE_RATE_LIMIT (120/minute) is
    checked inside require_jarvis_queue_token itself, before the token
    comparison, so it applies regardless of whether the token turns out to
    be right or wrong."""
    statuses = []
    for _ in range(150):
        r = client.get(
            "/jarvis/queue",
            headers={"Authorization": f"Bearer still-the-wrong-token-{uuid.uuid4().hex}"},
        )
        statuses.append(r.status_code)
        if r.status_code == 429:
            break
    assert 429 in statuses, (
        f"expected a 429 within 150 wrong-token requests once "
        f"AUTH_GATE_RATE_LIMIT was exhausted, got status codes: {sorted(set(statuses))}"
    )
    assert all(s in (401, 429) for s in statuses), (
        f"expected only 401 (auth rejected) or 429 (rate limited) responses "
        f"for wrong-token requests, got: {sorted(set(statuses))}"
    )
