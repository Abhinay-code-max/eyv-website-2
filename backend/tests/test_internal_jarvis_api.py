"""
Tests for internal_jarvis_api.py - the /jarvis/* JARVIS-poller & coordination API (Task A.1).
Uses conftest.py's in-process `client` (starlette TestClient over server.app).

Every test that hits a real Mongo collection uses its own fresh AsyncIOMotorClient
(_db()/_run()).

JARVIS_QUEUE_API_TOKEN must already be set in the environment before this file
is collected.
"""
import ast
import asyncio
import hashlib
import inspect
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

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


def _seed_queue_item(**overrides) -> str:
    async def _do():
        db = _db()
        now = datetime.now(timezone.utc)
        doc = {
            "source_agent": "denver",
            "item_type": "ticket_review",
            "payload": {"ticket_id": "test_ticket_123", "title": "Payment bug"},
            "priority": 5,
            "status": "pending",
            "created_at": now,
            "resolved_at": None,
        }
        doc.update(overrides)
        result = await db.jarvis_queue_items.insert_one(doc)
        return str(result.inserted_id)
    return _run(_do())


def _cleanup_queue_item(item_id: str) -> None:
    async def _do():
        db = _db()
        await db.jarvis_queue_items.delete_one({"_id": ObjectId(item_id)})
    _run(_do())


def _cleanup_approval(approval_id: str) -> None:
    async def _do():
        db = _db()
        await db.jarvis_approvals.delete_one({"_id": ObjectId(approval_id)})
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
    assert "items" in r.json()


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
    assert latest["summary"].get("auth") == "rejected"


def test_no_token_at_all_rejected_and_logged(client):
    r = client.get("/jarvis/queue")
    assert r.status_code == 401, r.text

    entries = _recent_audit_entries(route="/jarvis/queue")
    assert entries[0]["status_code"] == 401
    assert entries[0]["summary"].get("auth") == "rejected"


# ═══════════════ Scope: token/module isolation ═══════════════

def test_valid_jarvis_token_rejected_on_unrelated_route(client):
    r = client.get("/api/bookings", headers=AUTH_HEADERS)
    assert r.status_code == 401, r.text


def test_valid_ticket_agent_token_rejected_on_jarvis_route(client):
    ticket_token = os.environ.get('INTERNAL_TICKET_API_TOKEN')
    if not ticket_token or ticket_token == VALID_TOKEN:
        return
    r = client.get("/jarvis/queue", headers={"Authorization": f"Bearer {ticket_token}"})
    assert r.status_code == 401, r.text


def test_module_never_references_user_or_booking_or_payment_collections():
    """AST confirmation: internal_jarvis_api.py must never touch db.users/bookings/payment_transactions."""
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


# ═══════════════ Route: Queue Behavior (A.1.1, A.1.2) ═══════════════

def test_queue_only_returns_pending_items_by_default(client):
    pending_id = _seed_queue_item(status="pending")
    resolved_id = _seed_queue_item(status="resolved", resolved_at=datetime.now(timezone.utc))
    try:
        r = client.get("/jarvis/queue", headers=AUTH_HEADERS)
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert pending_id in ids
        assert resolved_id not in ids
    finally:
        _cleanup_queue_item(pending_id)
        _cleanup_queue_item(resolved_id)


def test_queue_sorted_highest_priority_and_oldest_first(client):
    now = datetime.now(timezone.utc)
    # Priority 1 (critical) created later vs Priority 5 (normal) created earlier
    item_p5 = _seed_queue_item(priority=5, created_at=now.replace(microsecond=0))
    item_p1 = _seed_queue_item(priority=1, created_at=now.replace(microsecond=0) + timedelta(seconds=10))
    # Priority 1 created even later
    item_p1_later = _seed_queue_item(priority=1, created_at=now.replace(microsecond=0) + timedelta(seconds=20))
    try:
        r = client.get("/jarvis/queue", headers=AUTH_HEADERS)
        assert r.status_code == 200, r.text
        ids_in_order = [item["id"] for item in r.json()["items"] if item["id"] in (item_p5, item_p1, item_p1_later)]
        assert ids_in_order == [item_p1, item_p1_later, item_p5], (
            f"expected [item_p1, item_p1_later, item_p5], got {ids_in_order}"
        )
    finally:
        _cleanup_queue_item(item_p5)
        _cleanup_queue_item(item_p1)
        _cleanup_queue_item(item_p1_later)


def test_queue_filters_by_source_agent_and_item_type(client):
    denver_id = _seed_queue_item(source_agent="denver", item_type="ticket_review")
    bob_id = _seed_queue_item(source_agent="bob", item_type="marketing_campaign")
    try:
        r = client.get("/jarvis/queue?source_agent=bob", headers=AUTH_HEADERS)
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert bob_id in ids
        assert denver_id not in ids

        r_type = client.get("/jarvis/queue?item_type=ticket_review", headers=AUTH_HEADERS)
        assert r_type.status_code == 200, r_type.text
        type_ids = {item["id"] for item in r_type.json()["items"]}
        assert denver_id in type_ids
        assert bob_id not in type_ids
    finally:
        _cleanup_queue_item(denver_id)
        _cleanup_queue_item(bob_id)


# ═══════════════ Route: Decisions (A.1.3 & jarvis_core marketing_client) ═══════════════

def test_post_decision_resolves_queue_item(client):
    item_id = _seed_queue_item(status="pending")
    try:
        payload = {
            "queue_item_id": item_id,
            "source_agent": "jarvis",
            "decision_type": "ticket_fix",
            "action": "Opened PR #482 to fix payment bug",
            "details": {"pr_url": "https://github.com/eyv/repo/pull/482"},
            "resolution_status": "resolved",
        }
        r = client.post("/jarvis/decisions", json=payload, headers=AUTH_HEADERS)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["queue_item_updated"] is True
        assert data["decision"]["action"] == payload["action"]

        # Confirm queue item is now resolved in DB
        async def _check():
            db = _db()
            doc = await db.jarvis_queue_items.find_one({"_id": ObjectId(item_id)})
            assert doc["status"] == "resolved"
            assert doc["resolved_at"] is not None
        _run(_check())
    finally:
        _cleanup_queue_item(item_id)


def test_post_decision_from_marketing_client_contract_succeeds(client):
    """Tests the exact contract sent by jarvis_core's marketing_client.py."""
    payload = {
        "queue_item_id": "test-marketing-queue-001",
        "action": {"type": "instagram_post", "caption": "Explore Goa this weekend!"},
        "reason": "Boost bookings for August",
        "context": {"source": "sara_analytics_report"},
    }
    r = client.post("/jarvis/decisions", json=payload, headers=AUTH_HEADERS)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "recorded"
    assert data["decision"]["decision_type"] == "instagram_post"
    assert data["decision"]["action"]["caption"] == "Explore Goa this weekend!"
    assert data["decision"]["reason"] == "Boost bookings for August"

    # Confirm record in db.jarvis_decisions with native datetime
    async def _check():
        db = _db()
        dec_doc = await db.jarvis_decisions.find_one({"_id": ObjectId(data["decision"]["id"])})
        assert dec_doc is not None
        assert isinstance(dec_doc["created_at"], datetime)
        assert dec_doc["queue_item_id"] == "test-marketing-queue-001"
        await db.jarvis_decisions.delete_one({"_id": dec_doc["_id"]})
    _run(_check())


def test_post_decision_extra_field_rejected_422(client):
    """extra='forbid' must reject unexpected/malformed fields with 422."""
    payload = {
        "queue_item_id": "123",
        "action": "valid action",
        "rogue_unexpected_field": "disallowed",
    }
    r = client.post("/jarvis/decisions", json=payload, headers=AUTH_HEADERS)
    assert r.status_code == 422, r.text



# ═══════════════ Route: Approvals, Prefetch Protection & Token Hashing (A.1.4, A.1.5) ═══════════════

def test_post_approval_and_poll(client):
    payload = {
        "action_type": "marketing_campaign",
        "title": "August Discount Campaign",
        "description": "Bob wants to publish 20% discount on Instagram",
        "payload": {"discount_percent": 20, "platform": "instagram"},
        "requester_agent": "bob",
    }
    r = client.post("/jarvis/approvals", json=payload, headers=AUTH_HEADERS)
    assert r.status_code == 200, r.text
    res_data = r.json()
    approval = res_data["approval"]
    approval_id = approval["id"]
    approval_token = res_data["approval_token"]
    assert approval["status"] == "pending"

    try:
        # 1. JARVIS polls the approval -> pending
        poll_res = client.get(f"/jarvis/approvals/{approval_id}", headers=AUTH_HEADERS)
        assert poll_res.status_code == 200, poll_res.text
        assert poll_res.json()["approval"]["status"] == "pending"

        # 2. GET /jarvis/approvals/resolve (Email Scanner / Prefetch Simulation)
        # MUST ONLY render HTML review form and NEVER mutate state
        get_res = client.get(f"/jarvis/approvals/resolve?token={approval_token}&decision=approved")
        assert get_res.status_code == 200
        assert "text/html" in get_res.headers["content-type"]
        assert "Confirm JARVIS Sign-Off" in get_res.text

        # Verify status is STILL pending after GET
        poll_res_after_get = client.get(f"/jarvis/approvals/{approval_id}", headers=AUTH_HEADERS)
        assert poll_res_after_get.json()["approval"]["status"] == "pending"

        # 3. Explicit POST /jarvis/approvals/resolve (Form Submission)
        post_res = client.post(
            "/jarvis/approvals/resolve",
            data={"token": approval_token, "decision": "approved", "note": "Looks great"},
            headers={"Accept": "text/html"},
        )
        assert post_res.status_code == 200
        assert "Action Sign-Off Recorded" in post_res.text

        # 4. JARVIS polls again -> observes status flipped to approved
        poll_res_after_post = client.get(f"/jarvis/approvals/{approval_id}", headers=AUTH_HEADERS)
        assert poll_res_after_post.status_code == 200
        polled_data = poll_res_after_post.json()["approval"]
        assert polled_data["status"] == "approved"
        assert polled_data["resolution_note"] == "Looks great"
        assert polled_data["resolved_at"] is not None
    finally:
        _cleanup_approval(approval_id)


def test_approval_token_is_hashed_at_rest_and_expires(client):
    """Verifies that the raw token is never stored in DB plaintext, and expired tokens fail."""
    payload = {
        "action_type": "code_deploy",
        "title": "Deploy hotfix",
        "description": "Deploy emergency hotfix to production",
    }
    r = client.post("/jarvis/approvals", json=payload, headers=AUTH_HEADERS)
    assert r.status_code == 200
    res_data = r.json()
    approval_id = res_data["approval"]["id"]
    raw_token = res_data["approval_token"]

    try:
        # Check DB directly
        async def _check_db():
            db = _db()
            doc = await db.jarvis_approvals.find_one({"_id": ObjectId(approval_id)})
            assert "approval_token" not in doc, "Raw token must not be stored in document"
            assert "approval_token_hash" in doc, "approval_token_hash must be present"
            expected_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
            assert doc["approval_token_hash"] == expected_hash
            assert doc["expires_at"] is not None
            assert doc["expires_at"] > doc["created_at"]
        _run(_check_db())

        # Test expiration: set expires_at in the past
        async def _expire_approval():
            db = _db()
            past = datetime.now(timezone.utc) - timedelta(hours=1)
            await db.jarvis_approvals.update_one(
                {"_id": ObjectId(approval_id)},
                {"$set": {"expires_at": past}},
            )
        _run(_expire_approval())

        # Attempting to resolve expired token should 400
        fail_res = client.post(
            "/jarvis/approvals/resolve",
            json={"token": raw_token, "decision": "approved"},
        )
        assert fail_res.status_code == 400, fail_res.text
    finally:
        _cleanup_approval(approval_id)


def test_internal_approval_resolution(client):
    payload = {
        "action_type": "refund",
        "title": "Refund user $50",
        "description": "Customer requested booking refund",
    }
    r = client.post("/jarvis/approvals", json=payload, headers=AUTH_HEADERS)
    assert r.status_code == 200, r.text
    approval_id = r.json()["approval"]["id"]

    try:
        # Internal API resolution
        res = client.post(
            f"/jarvis/approvals/{approval_id}/resolve",
            json={"decision": "rejected", "note": "Outside refund policy"},
            headers=AUTH_HEADERS,
        )
        assert res.status_code == 200, res.text
        assert res.json()["approval"]["status"] == "rejected"
    finally:
        _cleanup_approval(approval_id)


# ═══════════════ End-to-End Loop Simulation (A.1.6) ═══════════════

def test_full_agent_to_jarvis_loop_end_to_end(client):
    """
    Simulates complete cycle:
    1. Sub-agent (Denver) enqueues a work item.
    2. JARVIS polls /jarvis/queue, sees the item.
    3. JARVIS posts a decision, marking the queue item resolved.
    4. JARVIS posts an approval request for a high-risk action.
    5. JARVIS polls /jarvis/approvals/{id} (pending).
    6. Admin reviews GET page (safe, no mutation) and confirms via POST.
    7. JARVIS polls /jarvis/approvals/{id} (approved).
    """
    # 1. Enqueue item
    item_id = _seed_queue_item(
        source_agent="denver",
        item_type="bug_triage",
        payload={"ticket_id": "ticket_999", "error": "500 on checkout"},
        priority=1,
    )
    approval_id = None
    try:
        # 2. JARVIS polls queue
        queue_res = client.get("/jarvis/queue", headers=AUTH_HEADERS)
        assert queue_res.status_code == 200
        items = queue_res.json()["items"]
        matching = [i for i in items if i["id"] == item_id]
        assert len(matching) == 1, "JARVIS should receive the enqueued item"
        item = matching[0]
        assert item["priority"] == 1
        assert item["status"] == "pending"

        # 3. JARVIS posts decision
        decision_res = client.post(
            "/jarvis/decisions",
            json={
                "queue_item_id": item_id,
                "source_agent": "jarvis",
                "decision_type": "code_fix",
                "action": "Generated fix branch fix/checkout-500",
                "details": {"branch": "fix/checkout-500"},
            },
            headers=AUTH_HEADERS,
        )
        assert decision_res.status_code == 200
        assert decision_res.json()["queue_item_updated"] is True

        # Verify item no longer appears in pending queue
        queue_after = client.get("/jarvis/queue", headers=AUTH_HEADERS)
        assert item_id not in [i["id"] for i in queue_after.json()["items"]]

        # 4. JARVIS creates approval for deploy
        approval_res = client.post(
            "/jarvis/approvals",
            json={
                "queue_item_id": item_id,
                "action_type": "deploy_prod",
                "title": "Deploy fix/checkout-500 to Production",
                "description": "Automated patch ready for merge and deploy",
                "requester_agent": "jarvis",
            },
            headers=AUTH_HEADERS,
        )
        assert approval_res.status_code == 200
        res_data = approval_res.json()
        appr = res_data["approval"]
        approval_id = appr["id"]
        token = res_data["approval_token"]

        # 5. JARVIS polls approval status -> pending
        p1 = client.get(f"/jarvis/approvals/{approval_id}", headers=AUTH_HEADERS)
        assert p1.json()["approval"]["status"] == "pending"

        # 6. Admin prefetch/review GET page (no mutation)
        r_get = client.get(f"/jarvis/approvals/resolve?token={token}&decision=approved")
        assert r_get.status_code == 200
        # Check still pending
        p_mid = client.get(f"/jarvis/approvals/{approval_id}", headers=AUTH_HEADERS)
        assert p_mid.json()["approval"]["status"] == "pending"

        # Admin POST confirmation
        r_post = client.post(
            "/jarvis/approvals/resolve",
            json={"token": token, "decision": "approved"},
        )
        assert r_post.status_code == 200

        # 7. JARVIS polls approval status -> approved
        p2 = client.get(f"/jarvis/approvals/{approval_id}", headers=AUTH_HEADERS)
        assert p2.json()["approval"]["status"] == "approved"
        assert p2.json()["approval"]["resolved_at"] is not None

    finally:
        _cleanup_queue_item(item_id)
        if approval_id:
            _cleanup_approval(approval_id)


# ═══════════════ Rate limiting - LAST in the file ═══════════════

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
    statuses = []
    for _ in range(150):
        r = client.get(
            "/jarvis/queue",
            headers={"Authorization": f"Bearer still-the-wrong-token-{uuid.uuid4().hex}"},
        )
        statuses.append(r.status_code)
        if r.status_code == 429:
            break
    try:
        assert 429 in statuses, (
            f"expected a 429 within 150 wrong-token requests once "
            f"AUTH_GATE_RATE_LIMIT was exhausted, got status codes: {sorted(set(statuses))}"
        )
        assert all(s in (401, 429) for s in statuses), (
            f"expected only 401 or 429 responses, got: {sorted(set(statuses))}"
        )
    finally:
        try:
            from internal_jarvis_api import _limiter
            _limiter._storage.reset()
        except Exception:
            pass

