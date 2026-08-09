"""
Tests for internal_tickets_api.py - the /api/internal/tickets/* service-
token-gated API. Uses conftest.py's in-process `client` (starlette
TestClient over server.app), not a live uvicorn process, because the
instant-revocation test (#6 below) needs to mutate INTERNAL_TICKET_API_TOKEN
in THIS process's os.environ and see the change take effect on the very
next request - that's only observable in-process; a separately-running
uvicorn process wouldn't see a monkeypatch.setenv() from the test process
at all.

Every test that hits a real Mongo collection uses its own fresh
AsyncIOMotorClient (this file's own _db()/_run()), never server.py's global
`db` directly - the same reasoning test_rewards_race.py's module docstring
documents: TestClient drives the app in a background thread with its own
event loop, and reusing one Motor client across that loop and a second
`asyncio.run()` in the main thread hits "RuntimeError: Event loop is
closed" on this stack.

INTERNAL_TICKET_API_TOKEN must already be set in the environment before
this file (or any file - server.py imports internal_tickets_api
unconditionally) is collected, exactly like CORS_ORIGINS/
WALLET_URL_SIGNING_SECRET/GEMINI_API_KEY already must be - see
internal_tickets_api.py's hard-fail-at-import check.
"""
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
VALID_TOKEN = os.environ['INTERNAL_TICKET_API_TOKEN']
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


def _recent_audit_entries(route: str = None, ticket_id: str = None, limit: int = 20):
    async def _do():
        db = _db()
        query = {}
        if route:
            query["route"] = route
        if ticket_id:
            query["ticket_id"] = ticket_id
        cursor = db.ticket_agent_audit_log.find(query).sort("timestamp", -1).limit(limit)
        return await cursor.to_list(limit)
    return _run(_do())


# ═══════════════ Auth: correct / wrong / missing token ═══════════════

def test_correct_token_succeeds(client):
    r = client.get("/api/internal/tickets/queue", headers=AUTH_HEADERS)
    assert r.status_code == 200, r.text
    assert "tickets" in r.json()


def test_wrong_token_rejected_and_logged_as_failed_attempt(client):
    r = client.get(
        "/api/internal/tickets/queue",
        headers={"Authorization": "Bearer definitely-the-wrong-token"},
    )
    assert r.status_code == 401, r.text

    entries = _recent_audit_entries(route="/api/internal/tickets/queue")
    assert entries, "expected at least one audit log entry for GET /queue"
    latest = entries[0]
    assert latest["status_code"] == 401
    assert latest["summary"].get("auth") == "rejected", (
        f"expected the failed attempt to be logged as an auth rejection, got {latest['summary']}"
    )


def test_no_token_at_all_rejected_and_logged(client):
    r = client.get("/api/internal/tickets/queue")
    assert r.status_code == 401, r.text

    entries = _recent_audit_entries(route="/api/internal/tickets/queue")
    assert entries[0]["status_code"] == 401
    assert entries[0]["summary"].get("auth") == "rejected"


# ═══════════════ Scope: can't be reused to gate an unrelated route ═══════════════

def test_valid_ticket_token_rejected_on_unrelated_route(client):
    """A valid /api/internal/tickets/* token must have zero special meaning
    anywhere else - require_ticket_agent_token is only wired onto this one
    router. GET /api/bookings expects a session token/cookie
    (get_current_user -> _get_current_session); a ticket-API token doesn't
    hash to any real session, so this must 401 exactly like any other
    garbage bearer value would."""
    r = client.get("/api/bookings", headers=AUTH_HEADERS)
    assert r.status_code == 401, r.text


def test_module_never_references_user_or_booking_or_payment_collections():
    """Static confirmation of the scope boundary in
    internal_tickets_api.py's module docstring (section 2): this module
    must never touch db.users/db.bookings/db.payment_transactions, even
    indirectly - it only ever queries db.tickets and
    db.ticket_agent_audit_log.

    Checks the AST, not a raw substring search - the module's own docstring
    mentions "db.users" etc. in prose (explaining exactly this invariant),
    which a plain string search would misfire on. An ast.Attribute node is
    only ever real, executable code (`db.users` as an expression) - never a
    docstring or comment, which aren't part of the parsed tree at all."""
    import ast
    import internal_tickets_api
    source = inspect.getsource(internal_tickets_api)
    tree = ast.parse(source)
    forbidden_attrs = {"users", "bookings", "payment_transactions"}
    real_references = sorted({
        node.attr for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in forbidden_attrs
    })
    assert not real_references, f"internal_tickets_api.py has real code referencing db.{real_references}"

    forbidden_imports = {"UserDoc", "SingleItemBookingDoc", "BundleBookingDoc", "PaymentTransactionDoc"}
    imported_names = {
        alias.asname or alias.name
        for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert not (imported_names & forbidden_imports), (
        f"internal_tickets_api.py unexpectedly imports {imported_names & forbidden_imports}"
    )


# ═══════════════ Routes: functional coverage ═══════════════

def test_create_ticket_sets_native_datetimes_and_default_workflow_state(client):
    r = client.post(
        "/api/internal/tickets",
        json={
            "title": "Refund button does nothing",
            "description": "Clicking Request Refund on a cancelled booking shows no confirmation and nothing happens.",
            "kind": "bug",
            "reporter_user_ids": ["user_test_reporter"],
            "linked_chat_sessions": ["chat_session_abc"],
        },
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    ticket_id = body["id"]
    try:
        assert body["status"] == "reported"
        assert body["approval"] == "pending"
        assert body["kind"] == "bug"
        assert body["reporter_user_ids"] == ["user_test_reporter"]
        assert body["linked_chat_sessions"] == ["chat_session_abc"]

        # Confirm the raw stored document uses native BSON datetimes, not
        # ISO strings - same invariant test_ticket_doc.py checks at the
        # Pydantic-model level, checked here against what actually landed
        # in Mongo via this HTTP route. db must be constructed AND queried
        # inside the same coroutine driven by one _run() call - a bare
        # `_run(_db().tickets.find_one(...))` calls find_one() synchronously
        # before any loop is running on this stack (Python 3.14 + Windows +
        # motor), raising "no current event loop".
        async def _fetch_raw():
            return await _db().tickets.find_one({"_id": ObjectId(ticket_id)})
        raw = _run(_fetch_raw())
        assert isinstance(raw["first_reported_at"], datetime)
        assert isinstance(raw["updated_at"], datetime)
        assert raw["first_reported_at"] == raw["updated_at"]

        # Queried by route, not ticket_id - POST /api/internal/tickets has
        # no {id} path param (the id doesn't exist until the handler
        # creates it), so _AuditedTicketRoute's request.path_params.get("id")
        # is always None for this route, same as it is for GET /queue
        # (see that route's own audit test above, also queried by route=).
        entries = _recent_audit_entries(route="/api/internal/tickets")
        assert entries, "expected an audit entry for this ticket's creation"
        assert entries[0]["summary"] == {"created": True, "kind": "bug"}
    finally:
        _cleanup_ticket(ticket_id)


def test_create_ticket_rejects_blank_title(client):
    r = client.post(
        "/api/internal/tickets",
        json={"title": "   ", "description": "Something is wrong", "kind": "bug"},
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 422, r.text


def test_create_ticket_rejects_unknown_field(client):
    r = client.post(
        "/api/internal/tickets",
        json={"title": "T", "description": "D", "kind": "bug", "status": "closed"},
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 422, r.text


def test_patch_ticket_updates_fields_and_records_real_diff(client):
    ticket_id = _seed_ticket()
    try:
        r = client.patch(
            f"/api/internal/tickets/{ticket_id}",
            json={"status": "triaged", "agent_plan": "Investigate the root cause"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "triaged"
        assert body["agent_plan"] == "Investigate the root cause"
        assert body["id"] == ticket_id

        entries = _recent_audit_entries(ticket_id=ticket_id)
        assert entries, "expected an audit entry for this ticket's PATCH"
        diff = entries[0]["summary"]["changed_fields"]
        assert diff["status"] == {"from": "reported", "to": "triaged"}
        assert diff["agent_plan"] == {"from": None, "to": "Investigate the root cause"}
    finally:
        _cleanup_ticket(ticket_id)


def test_patch_rejects_unknown_field(client):
    ticket_id = _seed_ticket()
    try:
        r = client.patch(
            f"/api/internal/tickets/{ticket_id}",
            json={"title": "an agent should not be able to rewrite this"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 422, r.text
    finally:
        _cleanup_ticket(ticket_id)


def test_patch_nonexistent_ticket_returns_404(client):
    fake_id = str(ObjectId())
    r = client.patch(
        f"/api/internal/tickets/{fake_id}",
        json={"status": "triaged"},
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 404, r.text


def test_patch_malformed_id_returns_400(client):
    r = client.patch(
        "/api/internal/tickets/not-a-valid-object-id",
        json={"status": "triaged"},
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 400, r.text


def test_notify_adds_user_ids_without_duplicating_existing_ones(client):
    ticket_id = _seed_ticket(notified_user_ids=["user_already_notified"])
    try:
        r = client.post(
            f"/api/internal/tickets/{ticket_id}/notify",
            json={"user_ids": ["user_already_notified", "user_brand_new"]},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200, r.text
        assert sorted(r.json()["notified_user_ids"]) == ["user_already_notified", "user_brand_new"]
    finally:
        _cleanup_ticket(ticket_id)


def test_queue_defaults_to_reported_and_filters_by_status(client):
    reported_id = _seed_ticket(status="reported")
    closed_id = _seed_ticket(status="closed")
    try:
        r_default = client.get("/api/internal/tickets/queue", headers=AUTH_HEADERS)
        assert r_default.status_code == 200, r_default.text
        ids_default = {t["id"] for t in r_default.json()["tickets"]}
        assert reported_id in ids_default
        assert closed_id not in ids_default

        r_closed = client.get("/api/internal/tickets/queue?status=closed", headers=AUTH_HEADERS)
        assert r_closed.status_code == 200, r_closed.text
        ids_closed = {t["id"] for t in r_closed.json()["tickets"]}
        assert closed_id in ids_closed
        assert reported_id not in ids_closed
    finally:
        _cleanup_ticket(reported_id)
        _cleanup_ticket(closed_id)


def test_queue_rejects_invalid_status_value(client):
    r = client.get("/api/internal/tickets/queue?status=not-a-real-status", headers=AUTH_HEADERS)
    assert r.status_code == 422, r.text


# ═══════════════ Instant revocation (#6) ═══════════════

def test_token_rotation_takes_effect_immediately(client, monkeypatch):
    """Simulates an actual rotation: token A works, the environment is
    changed to token B (no server restart - just an env var mutation, same
    as a Railway env var update would be), and token A must stop working on
    the very next request while token B starts working, proving there's no
    cached "currently valid token" anywhere that would let A keep working
    until some cache expires."""
    token_a = os.environ["INTERNAL_TICKET_API_TOKEN"]

    r1 = client.get("/api/internal/tickets/queue", headers={"Authorization": f"Bearer {token_a}"})
    assert r1.status_code == 200, f"token A should work before rotation: {r1.text}"

    token_b = f"rotated-test-token-{uuid.uuid4().hex}"
    monkeypatch.setenv("INTERNAL_TICKET_API_TOKEN", token_b)

    r2 = client.get("/api/internal/tickets/queue", headers={"Authorization": f"Bearer {token_a}"})
    assert r2.status_code == 401, (
        "old token (A) must be rejected immediately after rotation - if this "
        "passes with 200, the token is being cached somewhere instead of "
        "re-read from the environment per request"
    )

    r3 = client.get("/api/internal/tickets/queue", headers={"Authorization": f"Bearer {token_b}"})
    assert r3.status_code == 200, f"new token (B) should work immediately after rotation: {r3.text}"
    # monkeypatch automatically restores INTERNAL_TICKET_API_TOKEN to token_a
    # at teardown, so later tests (and AUTH_HEADERS, captured at module import
    # time as the original token) keep working.


# ═══════════════ Rate limiting - LAST in the file, deliberately ═══════════════
# GET /queue's rate limit (60/minute, keyed by client IP) is completely
# independent of PATCH/notify's own limits (slowapi keys each decorated
# function separately - see internal_tickets_api.py), but every test above
# that calls GET /queue shares ONE bucket with this test (same TestClient
# -> same simulated "testclient" IP). Running this test last, and sending
# comfortably more than 60 requests, makes it robust to however many of
# that budget the tests above already spent (a handful, well under 60).
#
# Both tests below also all draw from ONE additional shared bucket -
# AUTH_GATE_RATE_LIMIT (120/minute), checked inside require_ticket_agent_token
# itself for EVERY request to ANY of the three routes, auth success or
# failure (see internal_tickets_api.py's module docstring, section 3). That
# bucket is comfortably larger than what the tests above and
# test_rate_limit_enforced_on_queue_route consume combined, so it doesn't
# interfere with either - test_wrong_token_requests_are_rate_limited_too
# below sends enough requests on its own to exhaust it regardless.

def test_rate_limit_enforced_on_queue_route(client):
    """The pre-existing, per-route limit (TICKET_API_RATE_LIMIT) - only
    ever checked for requests that already passed auth."""
    statuses = []
    for _ in range(75):
        r = client.get("/api/internal/tickets/queue", headers=AUTH_HEADERS)
        statuses.append(r.status_code)
        if r.status_code == 429:
            break
    assert 429 in statuses, (
        f"expected a 429 within 75 requests once the 60/minute budget was "
        f"exhausted, got status codes: {sorted(set(statuses))}"
    )


def test_wrong_token_requests_are_rate_limited_too(client):
    """The fix: wrong-token requests never reach get_ticket_queue (and
    therefore never reach its @_limiter.limit(TICKET_API_RATE_LIMIT)
    decorator) since auth rejects them first - before this fix, that meant
    they were completely unbounded. AUTH_GATE_RATE_LIMIT (120/minute) is
    checked inside require_ticket_agent_token itself, before the token
    comparison, so it applies regardless of whether the token turns out to
    be right or wrong. Sends a generous batch (well beyond 120) of
    wrong-token requests - robust to however much of this SAME shared
    budget the tests above (including test_rate_limit_enforced_on_queue_route
    just above, which also consumes from it) already used."""
    statuses = []
    for _ in range(150):
        r = client.get(
            "/api/internal/tickets/queue",
            headers={"Authorization": "Bearer still-the-wrong-token"},
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
