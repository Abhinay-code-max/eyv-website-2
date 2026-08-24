"""Chat & Support AI API router (/api/chat/*, /api/support/*).
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from google.genai import types as genai_types
from pydantic import BaseModel, field_validator

from routes.shared import (
    db,
    limiter,
    _session_token_key,
    get_current_user,
    ChatMessage,
    _get_gemini_client,
    GEMINI_MODEL,
    _get_internal_ticket_http_client,
    _internal_ticket_api_token,
)
from services import chat_service, usage_service
from agents.denver import support_agent_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat", "support"])


def _day_sort_key(day_key: str):
    # "day_2" before "day_10" - a plain string sort would put day_10 first.
    try:
        return (0, int(day_key.rsplit("_", 1)[-1]))
    except (ValueError, IndexError):
        return (1, day_key)


def build_trip_context(trip: dict, tier: Optional[str] = None) -> str:
    """Compact plain-text summary of a trip doc for the chat system prompt.

    trip.plans holds three parallel tiers (Budget/Premium/Luxury). `tier`
    identifies which one is currently on screen (e.g. the tab selected on
    TripResultsPage) and drives both the itinerary summarized here and the
    "Budget: X" label, so the two never contradict each other. If `tier`
    is omitted or doesn't match any generated plan, falls back to the
    trip's originally-requested preferences.budget_level, then to any tier
    that has one generated. destination/dates/travelers are trip-level
    (from preferences) and don't vary by tier. Each day's transportation
    line (flights, transfers) is included alongside its activities, so
    logistics questions ("how do I get from the airport to the hotel")
    can be answered from what's already booked instead of the model
    reaching for general knowledge. Only populated fields are included -
    nothing prints as "None" - and the itinerary digest is capped at a
    handful of days so a long trip can't balloon the prompt.

    Example: build_trip_context({"preferences": {"destination": "Goa",
    "departure_date": "2026-08-10", "return_date": "2026-08-14",
    "adults": 2, "budget_level": "Budget"}, "plans": [{"plan_type": "Budget",
    "itinerary": {"day_1": {"transportation": {"details": "Flight to Goa"},
    "activities": [{"activity": "Arrival"}]}}}]}, tier="Budget")
    -> "Trip: Goa | Dates: 2026-08-10 to 2026-08-14 | Travelers: 2 adults |
    Budget: Budget | Itinerary so far (Budget, 1 day(s)): Day 1 - Transport:
    Flight to Goa; Arrival"
    """
    prefs = trip.get("preferences") or {}
    parts = []

    destination = prefs.get("destination")
    if destination:
        parts.append(f"Trip: {destination}")

    departure_date = prefs.get("departure_date")
    return_date = prefs.get("return_date")
    if departure_date and return_date:
        parts.append(f"Dates: {departure_date} to {return_date}")
    elif departure_date:
        parts.append(f"Dates: from {departure_date}")

    traveler_bits = [
        f"{prefs[key]} {label}"
        for key, label in (("adults", "adults"), ("children", "children"), ("seniors", "seniors"))
        if prefs.get(key)
    ]
    if traveler_bits:
        parts.append(f"Travelers: {', '.join(traveler_bits)}")

    plans = trip.get("plans") or []
    target_tier = tier or prefs.get("budget_level")
    chosen = next((p for p in plans if p.get("plan_type") == target_tier and p.get("itinerary")), None)
    if not chosen:
        chosen = next((p for p in plans if p.get("itinerary")), None)

    budget_level = chosen.get("plan_type") if chosen else prefs.get("budget_level")
    if budget_level:
        parts.append(f"Budget: {budget_level}")

    if chosen:
        itinerary = chosen.get("itinerary") or {}
        day_keys = sorted(itinerary.keys(), key=_day_sort_key)
        MAX_DAYS_SHOWN = 6
        day_summaries = []
        for day_key in day_keys[:MAX_DAYS_SHOWN]:
            day = itinerary.get(day_key) or {}
            bits = []
            # Transport (flights/transfers already booked as part of this
            # day) goes first so the model sees it before activities - it's
            # the detail logistics questions ("how do I get from the
            # airport to the hotel") actually need, and it was previously
            # dropped from this summary entirely.
            transport_details = (day.get("transportation") or {}).get("details")
            if transport_details:
                bits.append(f"Transport: {transport_details}")
            activities = day.get("activities") or []
            themes = [a["activity"] for a in activities[:2] if a.get("activity")]
            if themes:
                bits.append(" + ".join(themes))
            label = day_key.replace("_", " ").capitalize()
            day_summaries.append(f"{label} - {'; '.join(bits)}" if bits else label)
        itinerary_line = "; ".join(day_summaries)
        if len(day_keys) > MAX_DAYS_SHOWN:
            itinerary_line += f"; plus {len(day_keys) - MAX_DAYS_SHOWN} more day(s)"
        parts.append(f"Itinerary so far ({chosen.get('plan_type')}, {len(day_keys)} day(s)): {itinerary_line}")
    else:
        parts.append("No itinerary planned yet")

    return " | ".join(parts)


def _sse_data(text: str) -> str:
    """Encode `text` as a spec-compliant SSE data event.

    A naive f"data: {text}\n\n" breaks the moment `text` contains an
    embedded newline (e.g. a paragraph break within a single Gemini
    stream chunk): per the SSE spec, every line of a multi-line data
    payload needs its own "data:" prefix, or a line-by-line client
    parser (like the one in TripResultsPage.jsx) silently drops any
    continuation line that lacks the prefix - the response looks
    truncated in the UI even though the full text was sent and saved.
    """
    return "".join(f"data: {line}\n" for line in text.split("\n")) + "\n"




# AI Assistant Chat
@router.post("/chat/stream")
@limiter.limit("15/minute")  # per-IP - a live back-and-forth chat is bursty by nature
@limiter.limit("15/minute", key_func=_session_token_key)  # per-authenticated-user
async def chat_stream(chat_msg: ChatMessage, request: Request):
    user = await get_current_user(request)

    # Chat-history trip-ownership guard: prevents one user from reading or
    # polluting another user's chat_sessions by passing an arbitrary trip_id.
    # Fetches the full doc (not just _id) so it can be reused below for trip
    # context - avoids a second identical query.
    trip = None
    if chat_msg.trip_id:
        trip = await db.trips.find_one(
            {"trip_id": chat_msg.trip_id, "user_id": user.user_id},
            {"_id": 0}
        )
        if not trip:
            raise HTTPException(status_code=403, detail="Forbidden")

    system_message = "You are a helpful AI travel assistant for EYV (Enjoy Your Vacation). Help users with travel planning, recommendations, itinerary changes, and travel-related questions. Be friendly, knowledgeable, and concise."

    if trip:
        trip_context = build_trip_context(trip, chat_msg.selected_tier)
        system_message += (
            f"\n\nYou are a travel assistant helping with the following trip:\n{trip_context}"
            f"\n\nUse this context to answer questions about the trip. If the user asks something "
            f"unrelated to this trip, answer normally. For logistics questions (airport transfers, "
            f"travel times, getting between locations), check this trip's own transportation and "
            f"itinerary data first - the user may already have a flight or transfer booked that "
            f"answers the question - and only fall back to general travel knowledge if the trip "
            f"data doesn't cover it."
        )

    history = await chat_service.get_recent_messages(db, user.user_id, chat_msg.trip_id, limit=20)
    gemini_contents = [
        {"role": msg["role"], "parts": [{"text": msg["content"]}]} for msg in history
    ]
    gemini_contents.append({"role": "user", "parts": [{"text": chat_msg.message}]})

    async def event_generator():
        full_response = ""
        try:
            stream = await _get_gemini_client().aio.models.generate_content_stream(
                model=GEMINI_MODEL,
                contents=gemini_contents,
                config=genai_types.GenerateContentConfig(
                    system_instruction=system_message,
                ),
            )
            await usage_service.log_usage(db, "gemini", user_id=user.user_id, meta={"context": "chat_stream"})

            async for chunk in stream:
                if chunk.text:
                    full_response += chunk.text
                    yield _sse_data(chunk.text)
            await chat_service.append_exchange(db, user.user_id, chat_msg.trip_id, chat_msg.message, full_response)
            yield _sse_data("[DONE]")
        except Exception as e:
            logger.error(f"Chat stream error: {e}")
            yield _sse_data(f"Error: {str(e)}")
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive"
        }
    )


@router.get("/chat/{trip_id}")
async def get_chat_history(trip_id: str, request: Request):
    """Chat history for a (user, trip) pair. trip_id == "none" means general
    chat with no trip attached (stored as trip_id = null)."""
    user = await get_current_user(request)
    resolved_trip_id = None if trip_id == "none" else trip_id

    if resolved_trip_id:
        owned_trip = await db.trips.find_one(
            {"trip_id": resolved_trip_id, "user_id": user.user_id},
            {"_id": 1}
        )
        if not owned_trip:
            raise HTTPException(status_code=403, detail="Forbidden")

    messages = await chat_service.get_all_messages(db, user.user_id, resolved_trip_id)
    return {
        "messages": [
            {"role": m["role"], "content": m["content"], "timestamp": m["timestamp"].isoformat()}
            for m in messages
        ]
    }


# ── Support agent (EYV Agent System Phase 4, Step 4.4) ──────────────────
class SupportMessageRequest(BaseModel):
    message: str

    @field_validator("message")
    @classmethod
    def _non_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message must not be blank")
        return v


@router.post("/support/message")
@limiter.limit("15/minute")  # per-IP, same shape as /chat/stream above
@limiter.limit("15/minute", key_func=_session_token_key)  # per-authenticated-user
async def support_message(body: SupportMessageRequest, request: Request):
    user = await get_current_user(request)
    result = await support_agent_service.handle_support_message(
        db, _get_gemini_client(), _get_internal_ticket_http_client(),
        internal_ticket_api_token=_internal_ticket_api_token(),
        user_id=user.user_id,
        # One stable conversation id per user rather than one per browser
        # tab/session - this widget is a single ongoing support thread per
        # user (see log_support_turn's own trip_id-repurposing docstring in
        # support_agent_service.py), not a per-visit chat log.
        conversation_id=f"support_{user.user_id}",
        message=body.message,
    )
    return {
        "category": result.category,
        "reply": result.reply,
        "ticket": result.ticket,
        "escalated": result.escalated,
    }
