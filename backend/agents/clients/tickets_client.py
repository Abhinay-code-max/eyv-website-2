"""Client for internal_tickets_api.py (/api/internal/tickets/*).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
import httpx

from .base import BaseInternalClient


class TicketsInternalClient(BaseInternalClient):
    def __init__(
        self,
        token: Optional[str] = None,
        base_url: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
        timeout: float = 10.0,
    ):
        super().__init__(
            token_env_var="INTERNAL_TICKET_API_TOKEN",
            token=token,
            base_url=base_url,
            http_client=http_client,
            timeout=timeout,
        )

    async def create_or_append_ticket(
        self,
        *,
        kind: str,
        title: str,
        description: str,
        reporter_user_ids: Optional[List[str]] = None,
        linked_chat_sessions: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """POST /api/internal/tickets - Create new ticket or append reporter."""
        payload: Dict[str, Any] = {
            "kind": kind,
            "title": title,
            "description": description,
            "reporter_user_ids": reporter_user_ids or [],
            "linked_chat_sessions": linked_chat_sessions or [],
        }
        return await self._request(
            "POST",
            "/api/internal/tickets",
            json=payload,
        )

    async def get_queue(
        self,
        status: Optional[List[str]] = None,
        kind: Optional[str] = None,
    ) -> Dict[str, Any]:
        """GET /api/internal/tickets/queue - Query open tickets."""
        params: Dict[str, Any] = {}
        if status:
            params["status"] = status
        if kind:
            params["kind"] = kind
        return await self._request("GET", "/api/internal/tickets/queue", params=params)

    async def get_ticket(self, ticket_id: str) -> Dict[str, Any]:
        """GET /api/internal/tickets/{id} - Get ticket details."""
        return await self._request("GET", f"/api/internal/tickets/{ticket_id}")

    async def patch_ticket(
        self,
        ticket_id: str,
        *,
        status: Optional[str] = None,
        agent_plan: Optional[str] = None,
        agent_diff_summary: Optional[str] = None,
        approval: Optional[str] = None,
        approval_note: Optional[str] = None,
        implementation_commit: Optional[str] = None,
        reporter_user_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """PATCH /api/internal/tickets/{id} - Update ticket status / fields."""
        payload: Dict[str, Any] = {}
        if status is not None:
            payload["status"] = status
        if agent_plan is not None:
            payload["agent_plan"] = agent_plan
        if agent_diff_summary is not None:
            payload["agent_diff_summary"] = agent_diff_summary
        if approval is not None:
            payload["approval"] = approval
        if approval_note is not None:
            payload["approval_note"] = approval_note
        if implementation_commit is not None:
            payload["implementation_commit"] = implementation_commit
        if reporter_user_ids is not None:
            payload["reporter_user_ids"] = reporter_user_ids
        return await self._request("PATCH", f"/api/internal/tickets/{ticket_id}", json=payload)

    async def get_ticket_stats(self) -> Dict[str, Any]:
        """GET /api/internal/tickets/stats - Get ticket stats counts."""
        return await self._request("GET", "/api/internal/tickets/stats")

    async def notify_ticket(
        self,
        ticket_id: str,
        *,
        status: str,
        message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """POST /api/internal/tickets/{id}/notify - Dispatch user notification."""
        payload: Dict[str, Any] = {"status": status}
        if message:
            payload["message"] = message
        return await self._request("POST", f"/api/internal/tickets/{ticket_id}/notify", json=payload)
