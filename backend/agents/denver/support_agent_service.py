"""EYV support-agent service - Denver Agent.
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
from . import ticket_dedup_service

logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-2.5-flash"


@functools.lru_cache(maxsize=1)
def _get_gemini_client() -> "genai.Client":
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


# ── Step 2: tools ────────────────────────────────────────────────────────

async def lookup_user_trips(db, user_id: str) -> List[Dict[str, Any]]:
    if db is None:
        return []
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
    if db is None:
        return None
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
    return _REFUND_POLICY


def escalate_to_human(reason: str) -> Dict[str, Any]:
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
    return TicketDoc(**response.json()).model_dump(mode="json")


TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {
    "lookup_user_trips": {"fn": lookup_user_trips, "read_only": True},
    "lookup_booking": {"fn": lookup_booking, "read_only": True},
    "get_refund_policy": {"fn": get_refund_policy, "read_only": True},
    "escalate_to_human": {"fn": escalate_to_human, "read_only": True},
    "create_or_append_ticket": {"fn": create_or_append_ticket, "read_only": False},
}

_BOOKING_ID_RE = re.compile(r'\bBK[0-9A-Fa-f]{10}\b')
_NOT_FOUND_REPLY = "I couldn't find a booking matching that reference, so I've flagged this for a human teammate to follow up with you directly."
_FALLBACK_REPLY = "I wasn't able to put together an answer - a human teammate will follow up."


async def _answer_question(db, gemini_client, *, user_id: str, message: str) -> str:
    booking_ids = _BOOKING_ID_RE.findall(message)
    bookings_found = []
    if booking_ids and db is not None:
        for bid in booking_ids:
            found = await lookup_booking(db, bid)
            if found:
                bookings_found.append(found)
        if not bookings_found:
            escalate_to_human(reason=f"booking_id {booking_ids} not found")
            return _NOT_FOUND_REPLY

    trips = await lookup_user_trips(db, user_id) if db is not None else []
    policy = get_refund_policy()

    context_bundle = {
        "user_trips": trips,
        "referenced_bookings": bookings_found,
        "refund_policy": policy,
    }

    system_instruction = (
        "You are an assistant answering a customer support question for EYV, "
        "a travel-booking app. Use ONLY the provided context to answer. If the context "
        "does not contain enough information to answer accurately, say so clearly and "
        "advise the user to contact human support. Never invent booking details or policies."
    )
    prompt = f"Context:\n{json.dumps(context_bundle, default=str)}\n\nUser Question:\n{message}"

    try:
        stream = await gemini_client.aio.models.generate_content_stream(
            model=GEMINI_MODEL,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                system_instruction=system_instruction,
            ),
        )
        full_response = ""
        async for chunk in stream:
            if chunk.text:
                full_response += chunk.text
        return full_response.strip() or _FALLBACK_REPLY
    except Exception as e:
        logger.warning(f"_answer_question generation failed: {e}")
        return _FALLBACK_REPLY


async def _reply_to_other(gemini_client, message: str) -> str:
    system_instruction = (
        "You are EYV's friendly support assistant. The user sent a conversational or off-topic "
        "message. Reply politely and briefly, and offer to help with trip planning, existing bookings, "
        "or bug reports."
    )
    try:
        stream = await gemini_client.aio.models.generate_content_stream(
            model=GEMINI_MODEL,
            contents=message,
            config=genai_types.GenerateContentConfig(
                system_instruction=system_instruction,
            ),
        )
        full_response = ""
        async for chunk in stream:
            if chunk.text:
                full_response += chunk.text
        return full_response.strip() or "Hello! How can I help you with your travel plans today?"
    except Exception as e:
        logger.warning(f"_reply_to_other generation failed: {e}")
        return "Hello! How can I help you with your travel plans today?"


_PII_EMAIL_RE = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
_PII_PHONE_RE = re.compile(r'(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b')
_PII_CARD_RE = re.compile(r'\b(?:\d{4}[-\s]?){3}\d{4}\b')


def _redact_pii(text: Optional[str]) -> Optional[str]:
    if not text:
        return text
    text = _PII_CARD_RE.sub("[REDACTED]", text)
    text = _PII_EMAIL_RE.sub("[REDACTED]", text)
    text = _PII_PHONE_RE.sub("[REDACTED]", text)
    return text


async def log_support_turn(
    db,
    *,
    conversation_id: str,
    status: str,
    message: str,
    response_text: str,
    error: Optional[str] = None,
) -> None:
    if db is None:
        return
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
_CRITICAL_KEYWORDS_RE = re.compile(
    r'\b(payment|checkout|stripe|booking|charge|auth|authentication|unauthorized|refund|crash|crashed|crashing)\b',
    re.IGNORECASE,
)


def _determine_ticket_priority(kind: str, message: str) -> int:
    if _CRITICAL_KEYWORDS_RE.search(message):
        return 1
    return 5


def _is_transient_quota_error(exc: Exception) -> bool:
    exc_str = str(exc).lower()
    return "429" in exc_str or "quota" in exc_str or "resourceexhausted" in exc_str or "resource_exhausted" in exc_str


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
    try:
        classification = await classify_message(gemini_client, message)
    except Exception as exc:
        if _is_transient_quota_error(exc):
            logger.warning(f"Transient quota error during classification for conversation {conversation_id}: {exc}")
            retry_reply = "Our support assistant is currently experiencing high load. Please try again in a moment."
            await log_support_turn(
                db, conversation_id=conversation_id, status="other:rate_limited",
                message=message, response_text=retry_reply, error=str(exc),
            )
            return SupportAgentTurnResult(category="other", reply=retry_reply)
        raise

    category = classification.category

    if category in ("bug", "feature"):
        try:
            ticket = await ticket_dedup_service.check_and_resolve_ticket(
                gemini_client,
                http_client,
                internal_ticket_api_token=internal_ticket_api_token,
                title=message[:120],
                description=message,
                kind=category,
                reporter_user_id=user_id,
                chat_session_id=conversation_id,
            )
        except Exception as e:
            logger.warning(f"check_and_resolve_ticket failed for conversation {conversation_id}: {e}")
            escalate_to_human(reason=f"ticket creation failed: {e}")
            await log_support_turn(
                db, conversation_id=conversation_id, status=f"{category}:escalated",
                message=message, response_text=_ESCALATED_REPLY, error=str(e),
            )
            # Enqueue high-priority escalation for JARVIS with flood-guard
            try:
                from agents.clients import JarvisInternalClient
                jarvis_client = JarvisInternalClient(http_client=http_client)
                await jarvis_client.enqueue_item(
                    source_agent="denver",
                    item_type="support_escalation",
                    priority=1,
                    payload={
                        "user_id": user_id,
                        "conversation_id": conversation_id,
                        "message": message,
                        "reason": f"ticket creation failed: {e}",
                    },
                )
            except Exception as q_exc:
                logger.warning(f"Failed to enqueue escalation item for conversation {conversation_id}: {q_exc}")

            return SupportAgentTurnResult(category=category, reply=_ESCALATED_REPLY, escalated=True)

        # Enqueue ticket review for JARVIS with dedup protection & priority boost
        try:
            ticket_id_str = str(ticket.get("id") or ticket.get("ticket_id"))
            reporters = ticket.get("reporter_user_ids") or []
            num_reporters = len(reporters)

            from agents.clients import JarvisInternalClient
            jarvis_client = JarvisInternalClient(http_client=http_client)
            await jarvis_client.enqueue_item(
                source_agent="denver",
                item_type="ticket_review",
                priority=1 if num_reporters >= 3 else _determine_ticket_priority(category, message),
                payload={
                    "ticket_id": ticket_id_str,
                    "title": ticket.get("title", message[:120]),
                    "kind": category,
                    "reporter_user_ids": reporters,
                    "conversation_id": conversation_id,
                },
            )
        except Exception as q_exc:
            logger.warning(f"Failed to enqueue JARVIS ticket review item for {conversation_id}: {q_exc}")

        await log_support_turn(
            db, conversation_id=conversation_id, status=f"{category}:ticket_created",
            message=message, response_text=_TICKET_FILED_REPLY,
        )
        return SupportAgentTurnResult(category=category, reply=_TICKET_FILED_REPLY, ticket=ticket)

    elif category == "question":
        reply = await _answer_question(db, gemini_client, user_id=user_id, message=message)
        await log_support_turn(
            db, conversation_id=conversation_id, status="question:answered",
            message=message, response_text=reply,
        )
        return SupportAgentTurnResult(category="question", reply=reply)

    else:
        reply = await _reply_to_other(gemini_client, message)
        await log_support_turn(
            db, conversation_id=conversation_id, status="other:reply",
            message=message, response_text=reply,
        )
        return SupportAgentTurnResult(category="other", reply=reply)
