"""Client for internal_analytics_api.py (/api/internal/analytics/*).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime
import httpx

from .base import BaseInternalClient


class AnalyticsInternalClient(BaseInternalClient):
    def __init__(
        self,
        token: Optional[str] = None,
        base_url: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
        timeout: float = 10.0,
    ):
        super().__init__(
            token_env_var="INTERNAL_ANALYTICS_API_TOKEN",
            token=token,
            base_url=base_url,
            http_client=http_client,
            timeout=timeout,
        )

    async def get_promotions(self) -> Dict[str, Any]:
        """GET /api/internal/analytics/promotions - List capped promotions and usages."""
        return await self._request("GET", "/api/internal/analytics/promotions")

    async def create_promotion(
        self,
        *,
        code: str,
        discount_type: str = "percent",
        discount_value: float = 10.0,
        valid_days: int = 30,
        usage_cap: Optional[int] = 100,
    ) -> Dict[str, Any]:
        """POST /api/internal/analytics/promotions - Create a new promotion in db.promotions."""
        return await self._request(
            "POST",
            "/api/internal/analytics/promotions",
            json={
                "code": code,
                "discount_type": discount_type,
                "discount_value": discount_value,
                "valid_days": valid_days,
                "usage_cap": usage_cap,
            },
        )

    async def create_campaign(
        self,
        *,
        title: str,
        channel: str,
        status: str = "pending_approval",
        content: Optional[Dict[str, Any]] = None,
        target_audience: Optional[str] = "all_travelers",
        spend_budget: float = 0.0,
        discount_config: Optional[Dict[str, Any]] = None,
        scheduled_for: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """POST /api/internal/analytics/campaigns - Create a marketing campaign draft."""
        payload: Dict[str, Any] = {
            "title": title,
            "channel": channel,
            "status": status,
            "content": content or {},
            "target_audience": target_audience,
            "spend_budget": spend_budget,
            "discount_config": discount_config,
        }
        if scheduled_for:
            payload["scheduled_for"] = scheduled_for.isoformat()
        return await self._request("POST", "/api/internal/analytics/campaigns", json=payload)

    async def get_campaign(self, campaign_id: str) -> Dict[str, Any]:
        """GET /api/internal/analytics/campaigns/{id} - Fetch campaign by ID."""
        return await self._request("GET", f"/api/internal/analytics/campaigns/{campaign_id}")

    async def patch_campaign(
        self,
        campaign_id: str,
        *,
        status: Optional[str] = None,
        external_post_id: Optional[str] = None,
        promo_code: Optional[str] = None,
        published_at: Optional[datetime] = None,
        error_message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """PATCH /api/internal/analytics/campaigns/{id} - Update campaign status."""
        payload: Dict[str, Any] = {}
        if status is not None:
            payload["status"] = status
        if external_post_id is not None:
            payload["external_post_id"] = external_post_id
        if promo_code is not None:
            payload["promo_code"] = promo_code
        if published_at is not None:
            payload["published_at"] = published_at.isoformat()
        if error_message is not None:
            payload["error_message"] = error_message
        return await self._request("PATCH", f"/api/internal/analytics/campaigns/{campaign_id}", json=payload)

    async def get_campaign_stats(self) -> Dict[str, Any]:
        """GET /api/internal/analytics/campaigns/stats - Get campaign metrics."""
        return await self._request("GET", "/api/internal/analytics/campaigns/stats")

    async def get_funnel(self) -> Dict[str, Any]:
        """GET /api/internal/analytics/funnel - Get funnel conversion analytics."""
        return await self._request("GET", "/api/internal/analytics/funnel")
