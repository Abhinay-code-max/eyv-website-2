"""
EYV support agent - Phase 4, Step 4.1 of the EYV Agent System roadmap.

Handles one turn of a user <-> support-agent conversation:

  1. Classify the incoming message as question | bug | feature | other,
     using Gemini structured JSON output validated against
     SupportClassification (a Pydantic model) - same "never silently
     coerce, raise and retry on a malformed/unparseable response" discipline
     server.py's GeneratedPlanResponse enforces for trip generation.
  2. question   -> answered directly via the read-only tools below, no
                   ticket ever created.
     bug/feature -> create_or_append_ticket is called directly. Dedup ("if
                   an open ticket for this already exists, append to it
                   instead of filing a new one") is Step 4.2, a separate,
                   later piece of work that will slot in as a pre-check
                   ahead of this call without changing this module's
                   interface - for now every bug/feature report files a new
                   ticket.
     other       -> stays conversational: no tool calls, no ticket.
  3. Every turn is logged to db.generation_logs - the exact same
     collection/field-shape 3.7's generation_log_service.py already writes
     (trip_id/plan_type/attempt/model/status/prompt/response/error/
     created_at - see log_support_turn's docstring for how this module's
     fields map onto that shape) so downstream tooling that queries that
     collection never has to special-case a support-agent entry versus a
     trip-generation one. Redaction discipline matches 3.7's: raw free-text
     is never stored as-is. The mechanism differs by necessity - 3.7 knows
     exactly which fields (dietary_preferences, accessibility_requirements)
     to strip because the caller passes those values in explicitly; a
     support message is arbitrary user-typed text with no such known
     fields, so this redacts by PII *pattern* (email addresses,
     phone-number-shaped digit runs) instead of by known value.

HARD CONSTRAINT: this module must never be able to write to db.bookings,
db.payment_transactions, or db.wallet_items - not "shouldn't", structurally
CAN'T. TOOL_REGISTRY below is the complete, explicit allowlist of every
capability this service has:
  - lookup_user_trips / lookup_booking: read-only queries.
  - get_refund_policy: static content, no DB call at all.
  - escalate_to_human: pure - returns a signal, never touches the DB. No
    further tool call is issued for a turn once this fires.
  - create_or_append_ticket: the only write tool, and it does not write
    db.tickets directly - it calls POST /api/internal/tickets
    (internal_tickets_api.py) over HTTP, hmac-token-authenticated exactly
    like any external ticket-agent caller. That module is a deliberately
    narrow, audited, rate-limited boundary (see its own docstring) that
    never touches db.users/db.bookings/db.payment_transactions either;
    routing every ticket write through it - rather than importing its
    ticket-writing logic in-process - means this service's writes still get
    that module's audit logging, scope narrowing, and request validation,
    not a shortcut around them.
See tests/test_support_agent_service.py's AST-based scope test and
TOOL_REGISTRY-based scope test for the enforcement, not just this docstring.

Tool selection for the question-answering flow is deterministic Python, not
LLM-driven free tool choice (see _answer_question) - the read-only tool
surface is small (3 tools) and always relevant to a support question in the
same way, so which tools run for a given question is fully transparent and
testable rather than an opaque model decision.
"""
import functools
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

import httpx
from google import genai
from google.genai import types as genai_types
from pydantic import BaseModel, ConfigDict, ValidationError

from db_models import GenerationLogDoc, TicketDoc

logger = logging.getLogger(__name__)

# Same model choice as server.py's trip generation (GEMINI_MODEL there) -
# gemini-2.0-flash/-lite return 429 (zero free-tier quota) and
# gemini-1.5-flash is 404 on this API key/version.
GEMINI_MODEL = "gemini-2.5-flash"


@functools.lru_cache(maxsize=1)
def _get_gemini_client() -> "genai.Client":
    """Duplicated from server.py's own `_get_gemini_client` rather than
    imported from it - server.py imports every services/*.py module at
    startup (see its own import block), so the reverse import would be
    circular. Same lazy-singleton reasoning as the original: constructing
    genai.Client(api_key=...) eagerly at import time means a missing
    GEMINI_API_KEY crashes the whole process at boot; deferring it to first
    real use scopes that failure to just the request that needed it. Same
    env var (GEMINI_API_KEY), same model - not a second, divergent client
    config, just a second call site for the same one."""
    import os
    return genai.Client(api_key=os.environ.get('GEMINI_API_KEY'))


# ── Step 1: classification ──────────────────────────────────────────────

SUPPORT_CATEGORIES = ("question", "bug", "feature", "other")

CLASSIFICATION_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": list(SUPPORT_CATEGORIES)},
    },
    "required": ["category"],
}

_CLASSIFICATION_SYSTEM_MESSAGE = """You are a classifier for EYV's travel-booking support inbox. Classify the user's message into exactly ONE category:
- "question": asking about an existing trip/booking, refunds, or how something works - answerable from data or policy, no code change implied.
- "bug": reporting something in the app that is broken or behaving incorrectly.
- "feature": requesting new functionality that does not exist today.
- "other": anything conversational that isn't a question, bug report, or feature request (greetings, small talk, off-topic messages).
Return ONLY the JSON object described by the response schema - no markdown, no explanation, no extra fields."""


class SupportClassification(BaseModel):
    model_config = ConfigDict(extra="ignore")
    category: Literal[SUPPORT_CATEGORIES]


async def classify_message(gemini_client, message: str, max_attempts: int = 3) -> SupportClassification:
    """Structured-output classification, Pydantic-validated - a response
    that isn't valid JSON, or is JSON but doesn't match SupportClassification
    (wrong/missing category), is never silently repaired into a guessed
    category. It's retried (same bounded-retry shape as server.py's
    generate_single_plan) and, if every attempt fails, this raises rather
    than returning a fabricated classification - the caller must decide how
    to handle a support turn that genuinely could not be classified."""
    last_error: Optional[Exception] = None
    for attempt in range(max_attempts):
        try:
            stream = await gemini_client.aio.models.generate_content_stream(
                model=GEMINI_MODEL,
                contents=message,
                config=genai_types.GenerateContentConfig(
                    system_instruction=_CLASSIFICATION_SYSTEM_MESSAGE,
                    response_mime_type="application/json",
                    response_json_schema=CLASSIFICATION_RESPONSE_SCHEMA,
                ),
            )
            full_response = ""
            async for chunk in stream:
                if chunk.text:
                    full_response += chunk.text
            raw = json.loads(full_response)
            return SupportClassification.model_validate(raw)
        except (json.JSONDecodeError, ValidationError) as e:
            last_error = e
            logger.warning(
                f"classify_message: attempt {attempt + 1}/{max_attempts} produced "
                f"unparseable/invalid classification output: {e}"
            )
    raise ValueError(
        f"classify_message: failed to obtain a valid classification after {max_attempts} attempts"
    ) from last_error


# ── Step 2: tools (small, read-mostly, explicit allowlist) ─────────────────

async def lookup_user_trips(db, user_id: str) -> List[Dict[str, Any]]:
    """Read-only. Projects trip_id/trip_name/dates only - never plans[]
    (which holds full itinerary + cost_breakdown pricing detail this
    service has no business surfacing to a support conversation)."""
    cursor = db.trips.find(
        {"user_id": user_id},
        {
            "_id": 0, "trip_id": 1, "trip_name": 1, "created_at": 1,
            "preferences.destination": 1, "preferences.departure_date": 1,
            "preferences.return_date": 1,
        },
    ).sort("created_at", -1).limit(20)
    docs = await cursor.to_list(20)
    trips = []
    for doc in docs:
        prefs = doc.get("preferences") or {}
        trips.append({
            "trip_id": doc.get("trip_id"),
            "trip_name": doc.get("trip_name"),
            "destination": prefs.get("destination"),
            "departure_date": prefs.get("departure_date"),
            "return_date": prefs.get("return_date"),
        })
    return trips


async def lookup_booking(db, booking_id: str) -> Optional[Dict[str, Any]]:
    """Read-only - status only. The Mongo projection itself excludes
    total_amount/currency/payment_status/item_data/line_items/
    traveler_details, not just the return value - a field never fetched
    from the DB can't leak through this tool even by an easy future
    mistake."""
    return await db.bookings.find_one(
        {"booking_id": booking_id},
        {"_id": 0, "booking_id": 1, "confirmation_code": 1, "booking_type": 1, "status": 1},
    )


_REFUND_POLICY = (
    "Refunds follow the cancellation terms shown at booking time for each "
    "item (flight/hotel/bundle). Cancellations made before the provider's "
    "own cancellation cutoff are refunded to the original payment method; "
    "EYV does not charge an additional cancellation fee on top of the "
    "provider's terms. Refunds are typically reflected within 5-10 business "
    "days, depending on the card issuer. To request a refund, use the "
    "Cancel Booking action on the booking's details page - support cannot "
    "issue refunds outside that flow."
)


def get_refund_policy() -> str:
    """Static content, no DB call."""
    return _REFUND_POLICY


def escalate_to_human(reason: str) -> Dict[str, Any]:
    """Pure - flags this turn for manual follow-up. Never touches the DB
    (this module's only write path is create_or_append_ticket - see the
    HARD CONSTRAINT in the module docstring). Terminal: once this returns,
    no further tool call is issued for the current turn; the caller
    surfaces escalated=True to whatever handles manual follow-up."""
    return {"escalated": True, "reason": reason}


async def create_or_append_ticket(
    http_client: httpx.AsyncClient,
    *,
    internal_ticket_api_token: str,
    title: str,
    description: str,
    kind: Literal["bug", "feature"],
    reporter_user_id: Optional[str] = None,
    chat_session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """The only write tool. Always creates a brand-new ticket for now -
    dedup ("append to an existing open ticket for the same issue instead of
    filing a new one") is Step 4.2, a pre-check that will slot in ahead of
    this call without changing this function's interface (see module
    docstring). Writes via POST /api/internal/tickets
    (internal_tickets_api.py) over HTTP, Bearer-token authenticated exactly
    like any external ticket-agent caller - never db.tickets.insert_one
    directly, so this write still goes through that module's auth, audit
    logging, scope narrowing, and request validation rather than around
    them. `http_client` is expected to be an httpx.AsyncClient whose
    base_url/transport already point at this same backend (an ASGI-transport
    client in tests/most callers, since internal_tickets_api's router is
    mounted on this same FastAPI app - see server.py's
    `app.include_router(internal_tickets_router)`)."""
    response = await http_client.post(
        "/api/internal/tickets",
        json={
            "title": title,
            "description": description,
            "kind": kind,
            "reporter_user_ids": [reporter_user_id] if reporter_user_id else [],
            "linked_chat_sessions": [chat_session_id] if chat_session_id else [],
        },
        headers={"Authorization": f"Bearer {internal_ticket_api_token}"},
    )
    response.raise_for_status()
    # Re-validated client-side, not just trusted as-is - the response
    # crossed an HTTP boundary, and this codebase's rule (see db_models.py's
    # module docstring, and GeneratedPlanResponse in server.py) is to
    # validate at every boundary, never assume a well-typed response.
    return TicketDoc(**response.json()).model_dump(mode="json")


# read_only=False marks the one and only tool this service can use to write
# anything at all - see the HARD CONSTRAINT in the module docstring and
# tests/test_support_agent_service.py's registry-based + AST-based scope
# tests, which both key off this registry/module to enforce it structurally.
TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {
    "lookup_user_trips": {"fn": lookup_user_trips, "read_only": True},
    "lookup_booking": {"fn": lookup_booking, "read_only": True},
    "get_refund_policy": {"fn": get_refund_policy, "read_only": True},
    "escalate_to_human": {"fn": escalate_to_human, "read_only": True},
    "create_or_append_ticket": {"fn": create_or_append_ticket, "read_only": False},
}


# A support question is almost always about one of this app's own bookings,
# whose ids are always "BK" + 10 uppercase hex chars (see server.py's
# booking_id = f"BK{uuid.uuid4().hex[:10].upper()}").
_BOOKING_ID_RE = re.compile(r'\bBK[0-9A-Fa-f]{10}\b')

_NOT_FOUND_REPLY = (
    "I couldn't find a booking matching that reference, so I've flagged this "
    "for a human teammate to follow up with you directly."
)
_FALLBACK_REPLY = "I wasn't able to put together an answer - a human teammate will follow up."


async def _answer_question(db, gemini_client, *, user_id: str, message: str) -> str:
    """Gathers context via the read-only tools deterministically (see
    module docstring for why this isn't LLM-driven tool selection), then
    asks Gemini for a plain-text answer grounded in only that context:
      - the user's own trips are always fetched (a support question is
        almost always in the context of "my trip(s)").
      - a booking is looked up only when the message actually contains
        something that looks like one of this app's booking ids.
      - the refund policy is always made available as context; Gemini
        decides whether it's actually relevant to the answer.
    If the message names a booking id that doesn't resolve to a real
    booking, this escalates immediately rather than letting Gemini guess -
    there's nothing real to answer with."""
    trips = await lookup_user_trips(db, user_id)

    booking = None
    booking_match = _BOOKING_ID_RE.search(message)
    if booking_match:
        booking = await lookup_booking(db, booking_match.group(0))
        if booking is None:
            escalate_to_human(reason=f"referenced booking id {booking_match.group(0)} not found")
            return _NOT_FOUND_REPLY

    refund_policy = get_refund_policy()
    context = (
        f"User's trips (JSON): {json.dumps(trips)}\n"
        f"Looked-up booking, if the user referenced one (JSON, null if none/not applicable): {json.dumps(booking)}\n"
        f"Refund policy: {refund_policy}\n"
    )
    system_message = (
        "You are EYV's support assistant, answering a travel-booking "
        "customer's question. Answer using ONLY the context below - never "
        "invent trip/booking details that aren't present in it. Be concise "
        "and direct.\n\n" + context
    )
    stream = await gemini_client.aio.models.generate_content_stream(
        model=GEMINI_MODEL,
        contents=message,
        config=genai_types.GenerateContentConfig(system_instruction=system_message),
    )
    full_response = ""
    async for chunk in stream:
        if chunk.text:
            full_response += chunk.text
    return full_response.strip() or _FALLBACK_REPLY


# ── Step 4: generation_logs redaction + logging ─────────────────────────

_REDACTED = "[REDACTED]"
_MAX_STORED_CHARS = 20000
_EMAIL_RE = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')
# A run of 8+ digits (allowing spaces/hyphens/parens/leading +) is
# phone-number-shaped in practice for this app's user base - deliberately
# permissive (would also catch some non-phone digit runs) since over-
# redacting a false positive costs nothing here, under-redacting a real
# phone number does.
_PHONE_RE = re.compile(r'(?<!\d)(\+?\(?\d[\d\-\s()]{6,}\d)(?!\d)')


def _redact_pii(text: str) -> str:
    """Redacts by PII *pattern*, not by known value - see module docstring
    for why this necessarily differs from generation_log_service.py's
    _redact (which strips known caller-supplied values like
    dietary_preferences). Safe to call on text with no PII in it - a no-op."""
    if not text:
        return text
    text = _EMAIL_RE.sub(_REDACTED, text)
    text = _PHONE_RE.sub(_REDACTED, text)
    return text[:_MAX_STORED_CHARS]


async def log_support_turn(
    db,
    *,
    conversation_id: str,
    status: str,
    message: str,
    response_text: str = "",
    error: Optional[str] = None,
) -> None:
    """Fire-and-forget (never raises - a logging failure must not break the
    real conversation turn that triggered it), writing to the SAME
    db.generation_logs collection and field shape 3.7's
    generation_log_service.log_generation_attempt already uses:
    trip_id/plan_type/attempt/model/status/prompt/response/error/created_at.
    There's no real trip involved in a support conversation, so trip_id
    holds this conversation's id and plan_type holds the constant
    "support_agent" - repurposing those two fields rather than adding new
    ones keeps every existing consumer of this collection working
    unmodified. `status` is expected to encode both the classification
    category and the outcome (e.g. "bug:ticket_created",
    "question:answered", "other:reply") - GenerationLogDoc.status is a free
    string, same as generate_single_plan's own "success"/"failed"."""
    try:
        record = GenerationLogDoc(
            trip_id=conversation_id,
            plan_type="support_agent",
            attempt=1,
            model=GEMINI_MODEL,
            status=status,
            prompt=_redact_pii(message),
            response=_redact_pii(response_text),
            error=error,
            created_at=datetime.now(timezone.utc),
        )
        await db.generation_logs.insert_one(record.model_dump())
    except Exception as e:
        logger.warning(f"Failed to log support-agent turn for conversation {conversation_id}: {e}")


# ── Orchestration ────────────────────────────────────────────────────────

_TICKET_FILED_REPLY = (
    "Thanks for the report - I've filed a ticket for our team to look into. "
    "You can follow up on it any time by referencing this conversation."
)
_ESCALATED_REPLY = "I wasn't able to file that automatically - I've flagged it for a human teammate instead."
_OTHER_REPLY = "Got it - let me know if there's anything travel- or booking-related I can help with."


class SupportAgentTurnResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    category: Literal[SUPPORT_CATEGORIES]
    reply: str
    ticket: Optional[Dict[str, Any]] = None
    escalated: bool = False


async def handle_support_message(
    db,
    gemini_client,
    http_client: httpx.AsyncClient,
    *,
    internal_ticket_api_token: str,
    user_id: str,
    conversation_id: str,
    message: str,
) -> SupportAgentTurnResult:
    """Entry point for one turn: classify, branch, log. See module
    docstring for the full behavior of each branch."""
    classification = await classify_message(gemini_client, message)
    category = classification.category

    if category in ("bug", "feature"):
        try:
            ticket = await create_or_append_ticket(
                http_client,
                internal_ticket_api_token=internal_ticket_api_token,
                title=message[:120],
                description=message,
                kind=category,
                reporter_user_id=user_id,
                chat_session_id=conversation_id,
            )
        except Exception as e:
            logger.warning(f"create_or_append_ticket failed for conversation {conversation_id}: {e}")
            escalate_to_human(reason=f"ticket creation failed: {e}")
            await log_support_turn(
                db, conversation_id=conversation_id, status=f"{category}:escalated",
                message=message, response_text=_ESCALATED_REPLY, error=str(e),
            )
            return SupportAgentTurnResult(category=category, reply=_ESCALATED_REPLY, escalated=True)

        await log_support_turn(
            db, conversation_id=conversation_id, status=f"{category}:ticket_created",
            message=message, response_text=_TICKET_FILED_REPLY,
        )
        return SupportAgentTurnResult(category=category, reply=_TICKET_FILED_REPLY, ticket=ticket)

    if category == "question":
        reply = await _answer_question(db, gemini_client, user_id=user_id, message=message)
        await log_support_turn(
            db, conversation_id=conversation_id, status="question:answered",
            message=message, response_text=reply,
        )
        return SupportAgentTurnResult(category=category, reply=reply)

    # "other"
    await log_support_turn(
        db, conversation_id=conversation_id, status="other:reply",
        message=message, response_text=_OTHER_REPLY,
    )
    return SupportAgentTurnResult(category=category, reply=_OTHER_REPLY)
