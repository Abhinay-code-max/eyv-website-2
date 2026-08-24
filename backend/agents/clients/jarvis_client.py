"""Client for internal_jarvis_api.py (/jarvis/*).
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
import httpx

from .base import BaseInternalClient


class JarvisInternalClient(BaseInternalClient):
    def __init__(
        self,
        token: Optional[str] = None,
        base_url: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
        timeout: float = 10.0,
    ):
        super().__init__(
            token_env_var="JARVIS_QUEUE_API_TOKEN",
            token=token,
            base_url=base_url,
            http_client=http_client,
            timeout=timeout,
        )

    async def enqueue_item(
        self,
        *,
        source_agent: str,
        item_type: str,
        payload: Optional[Dict[str, Any]] = None,
        priority: int = 5,
    ) -> Dict[str, Any]:
        """POST /jarvis/queue - Enqueue work item for JARVIS coordinator."""
        return await self._request(
            "POST",
            "/jarvis/queue",
            json={
                "source_agent": source_agent,
                "item_type": item_type,
                "payload": payload or {},
                "priority": priority,
            },
        )

    async def get_queue(
        self,
        status: Optional[List[str]] = None,
        source_agent: Optional[str] = None,
        item_type: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """GET /jarvis/queue - Poll pending work items."""
        params: Dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status
        if source_agent:
            params["source_agent"] = source_agent
        if item_type:
            params["item_type"] = item_type
        return await self._request("GET", "/jarvis/queue", params=params)

    async def get_queue_stats(self) -> Dict[str, Any]:
        """GET /jarvis/queue/stats - Get queue status counts."""
        return await self._request("GET", "/jarvis/queue/stats")

    async def submit_decision(
        self,
        *,
        decision_type: Optional[str] = None,
        action: Optional[Any] = None,
        reason: Optional[str] = None,
        queue_item_id: Optional[str] = None,
        source_agent: str = "jarvis",
        resolution_status: str = "resolved",
        context: Optional[Dict[str, Any]] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """POST /jarvis/decisions - Submit decision taken for a queue item."""
        return await self._request(
            "POST",
            "/jarvis/decisions",
            json={
                "queue_item_id": queue_item_id,
                "source_agent": source_agent,
                "decision_type": decision_type,
                "action": action,
                "reason": reason,
                "resolution_status": resolution_status,
                "context": context or {},
                "details": details or {},
            },
        )

    async def create_approval(
        self,
        *,
        action_type: str,
        title: str,
        description: str,
        payload: Optional[Dict[str, Any]] = None,
        requester_agent: str = "jarvis",
        queue_item_id: Optional[str] = None,
        decision_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """POST /jarvis/approvals - Request human approval."""
        return await self._request(
            "POST",
            "/jarvis/approvals",
            json={
                "action_type": action_type,
                "title": title,
                "description": description,
                "payload": payload or {},
                "requester_agent": requester_agent,
                "queue_item_id": queue_item_id,
                "decision_id": decision_id,
            },
        )

    async def get_approval(self, approval_id: str) -> Dict[str, Any]:
        """GET /jarvis/approvals/{id} - Fetch approval status."""
        return await self._request("GET", f"/jarvis/approvals/{approval_id}")

    async def resolve_approval(
        self,
        approval_id: str,
        decision: Literal["approved", "rejected"],
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """POST /jarvis/approvals/{id}/resolve - Resolve approval."""
        return await self._request(
            "POST",
            f"/jarvis/approvals/{approval_id}/resolve",
            json={"decision": decision, "note": note},
        )
