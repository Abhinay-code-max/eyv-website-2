"""Base HTTP Client for EYV Internal APIs.
Provides authenticated, fault-isolated async HTTP communication with internal endpoints.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional
import httpx


def get_backend_base_url() -> str:
    """Resolves base URL for internal API calls."""
    return os.environ.get("INTERNAL_API_BASE_URL") or os.environ.get("REACT_APP_BACKEND_URL", "http://127.0.0.1:8001").rstrip("/")


class BaseInternalClient:
    def __init__(
        self,
        token_env_var: str,
        token: Optional[str] = None,
        base_url: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
        timeout: float = 10.0,
    ):
        self.token_env_var = token_env_var
        self._token = token
        self.base_url = (base_url or get_backend_base_url()).rstrip("/")
        self._custom_client = http_client
        self.timeout = timeout

    def _get_token(self) -> str:
        token = self._token or os.environ.get(self.token_env_var, "")
        if not token:
            raise RuntimeError(f"{self.token_env_var} must be set for internal API client calls.")
        return token

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Optional[Any] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}" if not path.startswith("http") else path
        headers = self._get_headers()

        if self._custom_client is not None:
            res = await self._custom_client.request(
                method,
                url,
                json=json,
                params=params,
                headers=headers,
                timeout=self.timeout,
            )
            if res.status_code >= 400:
                raise httpx.HTTPStatusError(
                    f"Internal API error {res.status_code}: {res.text}",
                    request=res.request,
                    response=res,
                )
            return res.json() if res.content else {}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            res = await client.request(
                method,
                url,
                json=json,
                params=params,
                headers=headers,
            )
            if res.status_code >= 400:
                raise httpx.HTTPStatusError(
                    f"Internal API error {res.status_code}: {res.text}",
                    request=res.request,
                    response=res,
                )
            return res.json() if res.content else {}
