"""EYV ticket dedup service - Denver Agent.
Triages incoming bug/feature reports to append to existing tickets or create new ones via internal APIs.
"""
import json
import logging
from typing import Any, Dict, List, Literal, Optional

import httpx
from google.genai import types as genai_types
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-2.5-flash"
OPEN_TICKET_STATUSES = ("reported", "triaged", "awaiting_approval", "approved", "implemented", "backlog")
CANDIDATE_LIMIT = 30


async def _fetch_open_candidates(
    http_client: httpx.AsyncClient, *, internal_ticket_api_token: str, kind: Literal["bug", "feature"],
) -> List[Dict[str, Any]]:
    """One GET /api/internal/tickets/queue call, status=<every open status> kind=<kind>."""
    response = await http_client.get(
        "/api/internal/tickets/queue",
        params=[("status", s) for s in OPEN_TICKET_STATUSES] + [("kind", kind)],
        headers={"Authorization": f"Bearer {internal_ticket_api_token}"},
    )
    response.raise_for_status()
    tickets = response.json()["tickets"]
    return tickets[:CANDIDATE_LIMIT]


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
