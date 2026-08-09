"""
EYV ticket dedup service - Phase 4, Step 4.2 of the EYV Agent System roadmap.

Sits directly in front of ticket creation: when support_agent_service.py
classifies a message as bug|feature, it now calls check_and_resolve_ticket
(below) instead of calling create_or_append_ticket directly. This module is
what decides create-vs-append:

  1. Pulls up to CANDIDATE_LIMIT of the most-recently-active OPEN tickets
     (every TicketDoc status except "closed"/"rejected" - see
     OPEN_TICKET_STATUSES) of the same kind, via ONE call to
     GET /api/internal/tickets/queue?status=...&kind=... - never db.tickets
     directly. That route's own `status` param didn't used to accept more
     than one value; it was extended (see internal_tickets_api.py's own
     get_ticket_queue docstring) specifically for this module, because
     looping it once per open status would be both wasteful (up to 6x the
     requests for what's conceptually one query) and non-atomic (each call
     could see a different snapshot of the queue as writes land between
     them).
  2. If there are candidates, asks Gemini whether the new report is the
     same underlying issue as any of them - structured JSON output,
     Pydantic-validated, retried on malformed/self-contradictory output,
     same "never silently coerce" discipline support_agent_service.py's
     classify_message uses for message classification (this module
     deliberately reuses that same gemini_client - see
     check_and_resolve_ticket's signature - rather than standing up a
     second client/config).
  3. On a match: appends the new reporter to the existing ticket's
     reporter_user_ids via PATCH /{id} (internal_tickets_api.py - never
     db.tickets directly) rather than creating a duplicate. Idempotent: if
     that reporter is already on the ticket, this is a no-op and no PATCH
     request is even sent (see _append_reporter).
  4. On no match (or no candidates, or the dedup check itself couldn't be
     resolved after retries): creates a new ticket via
     support_agent_service.create_or_append_ticket, same as before this
     step existed. A dedup check that can't be resolved fails toward
     "create a new ticket," never toward "silently merge under
     uncertainty" - see _find_duplicate's docstring for why that's the
     safer default in both directions (an LLM hiccup here should degrade to
     a slightly redundant ticket, not either block reporting entirely or
     risk conflating two different issues).

Imports support_agent_service.create_or_append_ticket lazily, inside
check_and_resolve_ticket, not at module level - support_agent_service.py
imports THIS module at its own top level (to call check_and_resolve_ticket),
so a top-level import in the other direction would be circular. Deferring
it to call time is safe because by the time check_and_resolve_ticket is
actually invoked, both modules have already finished loading.
"""
import json
import logging
from typing import Any, Dict, List, Literal, Optional

import httpx
from google.genai import types as genai_types
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

logger = logging.getLogger(__name__)

# Same model choice as support_agent_service.py's GEMINI_MODEL - duplicated
# rather than imported for the same reason that module's own
# _get_gemini_client is duplicated from server.py's: avoiding a circular
# top-level import (see module docstring) without standing up a second,
# divergent client/model config - it's the same string, just two
# independent constants naming it.
GEMINI_MODEL = "gemini-2.5-flash"

# Every TicketDoc status except the two terminal-and-done ones. Kept as its
# own tuple (not derived from TICKET_STATUSES by subtracting a set) so the
# "which statuses count as open" decision is explicit and grep-able here,
# not implicit in an exclusion list someone has to reverse-engineer.
OPEN_TICKET_STATUSES = ("reported", "triaged", "awaiting_approval", "approved", "implemented", "backlog")

# Explicit cap so the dedup prompt below never grows unbounded as the
# ticket backlog grows, regardless of how many open tickets of a given kind
# actually exist. GET /queue already sorts by updated_at descending, so
# this keeps the most-recently-active (most likely to still be relevant)
# candidates.
CANDIDATE_LIMIT = 30


async def _fetch_open_candidates(
    http_client: httpx.AsyncClient, *, internal_ticket_api_token: str, kind: Literal["bug", "feature"],
) -> List[Dict[str, Any]]:
    """One GET /api/internal/tickets/queue call, status=<every open status>
    kind=<kind>, both filtered server-side. Slices to CANDIDATE_LIMIT
    client-side - the route itself only caps at its own, much larger
    QUEUE_MAX_RESULTS (200), which bounds a single query's cost but isn't
    the "no more than ~30 in a dedup prompt" cap this module needs."""
    response = await http_client.get(
        "/api/internal/tickets/queue",
        params=[("status", s) for s in OPEN_TICKET_STATUSES] + [("kind", kind)],
        headers={"Authorization": f"Bearer {internal_ticket_api_token}"},
    )
    response.raise_for_status()
    tickets = response.json()["tickets"]
    return tickets[:CANDIDATE_LIMIT]


# ── dedup check: structured, Pydantic-validated, no silent coercion ────────

DEDUP_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_match": {"type": "boolean"},
        "matched_ticket_id": {"type": "string"},
    },
    "required": ["is_match", "matched_ticket_id"],
}

_DEDUP_SYSTEM_MESSAGE = """You are triaging incoming {kind} reports for EYV, a travel-booking app. You will be shown a NEW report and a list of EXISTING open tickets of the same kind, each with an "id". Decide whether the NEW report describes the SAME underlying issue as exactly one of the EXISTING tickets.

Two reports are the same issue only if they share the same underlying root cause - different wording, different reproduction steps, or a different specific symptom of the exact same defect all count as the SAME issue. A different bug in the same feature/screen, or a different feature request in the same general area, is NOT the same issue, even if it sounds related.

If you are not confident it's the same issue, answer that there is no match - do not guess. A missed match just means a second, slightly redundant ticket gets filed; a wrong match would silently merge two different problems into one ticket, which is worse.

Return ONLY the JSON object described by the response schema:
- is_match: true only if the new report is the same issue as exactly one existing ticket.
- matched_ticket_id: that ticket's "id" if is_match is true, otherwise an empty string.
No markdown, no explanation, no extra fields."""


class DedupResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    is_match: bool
    matched_ticket_id: str = ""

    @model_validator(mode="after")
    def _match_and_id_agree(self):
        if self.is_match and not self.matched_ticket_id.strip():
            raise ValueError("is_match=true requires a non-empty matched_ticket_id")
        if not self.is_match and self.matched_ticket_id.strip():
            raise ValueError("is_match=false must not include a matched_ticket_id")
        return self


async def _find_duplicate(
    gemini_client, *, title: str, description: str, kind: Literal["bug", "feature"],
    candidates: List[Dict[str, Any]], max_attempts: int = 3,
) -> Optional[Dict[str, Any]]:
    """Returns the matched candidate dict, or None if there's no match -
    including when the check itself can't be resolved after max_attempts
    (malformed JSON, a response that fails DedupResult's own
    is_match/matched_ticket_id consistency check, or a matched_ticket_id
    that doesn't actually correspond to any candidate we sent - a
    hallucinated id is treated exactly like any other invalid response, not
    trusted). This never raises: unlike support_agent_service.classify_message
    (where there's no safe fallback category to guess), a dedup check that
    can't be resolved has an obviously safe fallback - "no match", which
    just results in a new ticket being filed, same as if dedup didn't run
    at all. Logs a warning on each failed attempt and gives up quietly
    after the last one, rather than raising and blocking ticket creation
    over what is, worst case, a slightly redundant ticket."""
    candidates_by_id = {c["id"]: c for c in candidates}
    prompt = (
        f"NEW report:\n{json.dumps({'title': title, 'description': description})}\n\n"
        f"EXISTING open {kind} tickets:\n"
        + json.dumps([{"id": c["id"], "title": c["title"], "description": c["description"]} for c in candidates])
    )
    system_message = _DEDUP_SYSTEM_MESSAGE.format(kind=kind)

    for attempt in range(max_attempts):
        try:
            stream = await gemini_client.aio.models.generate_content_stream(
                model=GEMINI_MODEL,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    system_instruction=system_message,
                    response_mime_type="application/json",
                    response_json_schema=DEDUP_RESPONSE_SCHEMA,
                ),
            )
            full_response = ""
            async for chunk in stream:
                if chunk.text:
                    full_response += chunk.text
            raw = json.loads(full_response)
            result = DedupResult.model_validate(raw)
            if not result.is_match:
                return None
            match = candidates_by_id.get(result.matched_ticket_id)
            if match is None:
                raise ValueError(
                    f"matched_ticket_id {result.matched_ticket_id!r} is not one of the "
                    f"{len(candidates)} candidate ticket id(s) sent"
                )
            return match
        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            logger.warning(
                f"_find_duplicate: attempt {attempt + 1}/{max_attempts} produced "
                f"unusable dedup output: {e}"
            )
    logger.warning(
        f"_find_duplicate: giving up after {max_attempts} attempts - treating as no match"
    )
    return None


async def _append_reporter(
    http_client: httpx.AsyncClient, *, internal_ticket_api_token: str,
    ticket: Dict[str, Any], reporter_user_id: Optional[str],
) -> Dict[str, Any]:
    """Idempotent: if reporter_user_id is None, or already present in
    ticket['reporter_user_ids'], this is a pure no-op and no PATCH request
    is sent at all - the same user reporting the same issue twice must
    result in that user appearing exactly once, and skipping the write
    entirely (rather than PATCHing an unchanged list) also avoids a
    no-change entry in the ticket's audit trail every time a duplicate
    report comes in."""
    existing_reporters = ticket.get("reporter_user_ids") or []
    if reporter_user_id is None or reporter_user_id in existing_reporters:
        return ticket

    response = await http_client.patch(
        f"/api/internal/tickets/{ticket['id']}",
        json={"reporter_user_ids": existing_reporters + [reporter_user_id]},
        headers={"Authorization": f"Bearer {internal_ticket_api_token}"},
    )
    response.raise_for_status()
    return response.json()


# ── entry point ──────────────────────────────────────────────────────────

async def check_and_resolve_ticket(
    gemini_client,
    http_client: httpx.AsyncClient,
    *,
    internal_ticket_api_token: str,
    title: str,
    description: str,
    kind: Literal["bug", "feature"],
    reporter_user_id: Optional[str] = None,
    chat_session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """The single entry point support_agent_service.py now calls for every
    bug/feature report, instead of calling create_or_append_ticket
    directly - this module is what decides create-vs-append (see module
    docstring). Same return shape as create_or_append_ticket (a
    TicketDoc-validated dict) either way, so the caller doesn't need to
    know which branch ran."""
    candidates = await _fetch_open_candidates(
        http_client, internal_ticket_api_token=internal_ticket_api_token, kind=kind,
    )
    if candidates:
        match = await _find_duplicate(
            gemini_client, title=title, description=description, kind=kind, candidates=candidates,
        )
        if match is not None:
            return await _append_reporter(
                http_client, internal_ticket_api_token=internal_ticket_api_token,
                ticket=match, reporter_user_id=reporter_user_id,
            )

    from .support_agent_service import create_or_append_ticket
    return await create_or_append_ticket(
        http_client,
        internal_ticket_api_token=internal_ticket_api_token,
        title=title,
        description=description,
        kind=kind,
        reporter_user_id=reporter_user_id,
        chat_session_id=chat_session_id,
    )
