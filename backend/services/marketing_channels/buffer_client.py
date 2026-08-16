"""
Buffer API Integration - Task A.4.1 of EYV Marketing Agent (Bob).

Direct HTTP client for Buffer API (https://api.bufferapp.com/1/).
Scoped to posting and scheduling social media updates only.
Defaults to draft=True and supports sandbox dry_run mode.
"""
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

BUFFER_API_BASE = "https://api.bufferapp.com/1"


class BufferClientError(Exception):
    """Raised on unrecoverable Buffer API errors."""


class BufferClient:
    def __init__(
        self,
        access_token: Optional[str] = None,
        default_profile_ids: Optional[List[str]] = None,
        dry_run: bool = False,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.access_token = access_token or os.environ.get("BUFFER_ACCESS_TOKEN")
        self.default_profile_ids = default_profile_ids or (
            [p.strip() for p in os.environ.get("BUFFER_PROFILE_IDS", "").split(",") if p.strip()]
        )
        self.dry_run = dry_run
        self._client = http_client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    async def create_update(
        self,
        text: str,
        profile_ids: Optional[List[str]] = None,
        media: Optional[Dict[str, Any]] = None,
        scheduled_at: Optional[datetime] = None,
        now: bool = False,
        top: bool = False,
        draft: bool = True,
    ) -> Dict[str, Any]:
        """Creates a post update on Buffer.
        If dry_run is True or access token is not configured, returns a simulated success response."""
        target_profiles = profile_ids or self.default_profile_ids

        if not text or not text.strip():
            raise ValueError("Buffer update text must not be blank")

        if self.dry_run:
            logger.info(f"[Buffer DRY-RUN] Creating draft update (profiles={target_profiles}, draft={draft}): {text[:60]}...")
            return {
                "success": True,
                "dry_run": True,
                "buffer_id": f"sim_buf_{int(datetime.now().timestamp())}",
                "text": text,
                "draft": draft,
                "profiles": target_profiles,
                "scheduled_at": scheduled_at.isoformat() if scheduled_at else None,
            }

        if not self.access_token:
            raise BufferClientError("BUFFER_ACCESS_TOKEN is not configured - cannot publish live without credentials")

        client = await self._get_client()
        data: Dict[str, Any] = {

            "text": text,
            "profile_ids[]": target_profiles,
            "now": "true" if now else "false",
            "top": "true" if top else "false",
            "shorten": "false",
        }

        if draft:
            data["pinned"] = "false"

        if scheduled_at:
            data["scheduled_at"] = scheduled_at.strftime("%Y-%m-%d %H:%M:%S")

        if media:
            if "photo" in media:
                data["media[photo]"] = media["photo"]
            if "thumbnail" in media:
                data["media[thumbnail]"] = media["thumbnail"]
            if "link" in media:
                data["media[link]"] = media["link"]

        response = await client.post(
            f"{BUFFER_API_BASE}/updates/create.json",
            data=data,
            headers={"Authorization": f"Bearer {self.access_token}"},
        )

        if response.status_code != 200:
            logger.error(f"Buffer API error: {response.status_code} - {response.text}")
            raise BufferClientError(f"Buffer API error HTTP {response.status_code}: {response.text[:200]}")

        resp_json = response.json()
        return {
            "success": True,
            "dry_run": False,
            "buffer_id": resp_json.get("updates", [{}])[0].get("id", "unknown"),
            "raw": resp_json,
        }


def get_buffer_client() -> BufferClient:
    return BufferClient()
