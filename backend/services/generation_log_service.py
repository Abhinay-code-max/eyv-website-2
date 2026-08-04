"""
Lightweight prompt/response logging for AI trip generation - a debugging and
prompt-regression aid appropriate for a solo-dev app, not a full
observability platform. Every Gemini call generate_single_plan makes (one
per retry attempt, success or failure) is one doc in db.generation_logs:
{trip_id, plan_type, attempt, model, status, prompt, response, error,
created_at} - queryable later via a plain Mongo query on trip_id or
created_at, no separate log-shipping/analysis tooling required.

Free-text user-supplied fields that can carry health-adjacent information
(dietary_preferences, accessibility_requirements - e.g. "wheelchair user",
"nut allergy") are redacted from both the stored prompt and response before
they're written. Callers pass the raw values in so this module can strip
them wherever they landed in the assembled text, rather than the caller
having to reconstruct redaction after the fact.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_REDACTED = "[REDACTED]"
# Generous cap - these documents are for debugging/prompt-regression
# analysis, not a verbatim audit trail, so truncating extreme outliers
# (a pathological response) is fine.
_MAX_STORED_CHARS = 20000


def _redact(text: str, *sensitive_values: str) -> str:
    for value in sensitive_values:
        if value:
            text = text.replace(value, _REDACTED)
    return text[:_MAX_STORED_CHARS]


async def log_generation_attempt(
    db,
    *,
    trip_id: str,
    plan_type: str,
    attempt: int,
    model: str,
    status: str,
    prompt: str,
    response_text: str = "",
    error: Optional[str] = None,
    dietary_preferences: str = "",
    accessibility_requirements: str = "",
) -> None:
    """Fire-and-forget - never raises, a logging failure must not break the
    real generation request that triggered it."""
    try:
        await db.generation_logs.insert_one({
            "trip_id": trip_id,
            "plan_type": plan_type,
            "attempt": attempt,
            "model": model,
            "status": status,
            "prompt": _redact(prompt, dietary_preferences, accessibility_requirements),
            "response": _redact(response_text, dietary_preferences, accessibility_requirements),
            "error": error,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        logger.warning(f"Failed to log generation attempt for trip {trip_id}: {e}")
