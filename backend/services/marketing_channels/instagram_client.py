"""
Instagram Graph API Integration - Task A.4.2 of EYV Marketing Agent (Bob).

Direct client for Meta Instagram Graph API (https://graph.facebook.com/v19.0).
Implements the 2-step media container creation & publishing workflow.
Includes sandbox validation (A.4.5) and dry_run mode.
"""
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v19.0"
MAX_CAPTION_LENGTH = 2200
MAX_HASHTAGS = 30


class InstagramClientError(Exception):
    """Raised on unrecoverable Instagram Graph API errors."""


class InstagramClient:
    def __init__(
        self,
        access_token: Optional[str] = None,
        account_id: Optional[str] = None,
        sandbox_mode: bool = False,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.access_token = access_token or os.environ.get("INSTAGRAM_ACCESS_TOKEN")
        self.account_id = account_id or os.environ.get("INSTAGRAM_ACCOUNT_ID")
        self.sandbox_mode = sandbox_mode or not bool(self.access_token and self.account_id)
        self._client = http_client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=20.0)
        return self._client

    def validate_post_content(self, caption: str, media_url: Optional[str] = None) -> Dict[str, Any]:
        """Performs Instagram payload validation rules."""
        if not caption or not caption.strip():
            raise ValueError("Instagram caption must not be blank")

        if len(caption) > MAX_CAPTION_LENGTH:
            raise ValueError(f"Instagram caption exceeds {MAX_CAPTION_LENGTH} chars (got {len(caption)})")

        hashtags = re.findall(r'#\w+', caption)
        if len(hashtags) > MAX_HASHTAGS:
            raise ValueError(f"Instagram caption exceeds {MAX_HASHTAGS} hashtags (got {len(hashtags)})")

        return {
            "valid": True,
            "char_count": len(caption),
            "hashtag_count": len(hashtags),
            "media_url": media_url,
        }

    async def publish_photo(
        self,
        image_url: str,
        caption: str,
        location_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Publishes a single photo post to Instagram via 2-step container flow."""
        self.validate_post_content(caption, image_url)

        if self.sandbox_mode:
            logger.info(f"[Instagram SANDBOX] Validated photo post (account={self.account_id}): {caption[:60]}...")
            return {
                "success": True,
                "sandbox_mode": True,
                "media_id": f"sim_ig_{int(datetime.now().timestamp())}",
                "creation_id": f"sim_container_{int(datetime.now().timestamp())}",
                "caption": caption,
                "image_url": image_url,
            }

        client = await self._get_client()

        # Step 1: Create media container
        container_params = {
            "image_url": image_url,
            "caption": caption,
            "access_token": self.access_token,
        }
        if location_id:
            container_params["location_id"] = location_id

        res_container = await client.post(
            f"{GRAPH_API_BASE}/{self.account_id}/media",
            params=container_params,
        )
        if res_container.status_code != 200:
            logger.error(f"Instagram container creation error: {res_container.text}")
            raise InstagramClientError(f"Container creation failed HTTP {res_container.status_code}: {res_container.text[:200]}")

        creation_id = res_container.json().get("id")
        if not creation_id:
            raise InstagramClientError("Missing container creation ID from Instagram API")

        # Step 2: Publish media container
        res_publish = await client.post(
            f"{GRAPH_API_BASE}/{self.account_id}/media_publish",
            params={
                "creation_id": creation_id,
                "access_token": self.access_token,
            },
        )
        if res_publish.status_code != 200:
            logger.error(f"Instagram media publish error: {res_publish.text}")
            raise InstagramClientError(f"Media publish failed HTTP {res_publish.status_code}: {res_publish.text[:200]}")

        media_id = res_publish.json().get("id")
        return {
            "success": True,
            "sandbox_mode": False,
            "media_id": media_id,
            "creation_id": creation_id,
        }


def get_instagram_client() -> InstagramClient:
    return InstagramClient()
