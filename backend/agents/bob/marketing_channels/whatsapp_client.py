"""WhatsApp Business Cloud API Integration - Bob Marketing Channel.
Direct client for Meta WhatsApp Cloud API (https://graph.facebook.com/v19.0).
"""
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v19.0"


class WhatsAppClientError(Exception):
    """Raised on unrecoverable WhatsApp Cloud API errors."""


class WhatsAppClient:
    def __init__(
        self,
        access_token: Optional[str] = None,
        phone_number_id: Optional[str] = None,
        verify_token: Optional[str] = None,
        dry_run: bool = False,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.access_token = access_token or os.environ.get("WHATSAPP_ACCESS_TOKEN")
        self.phone_number_id = phone_number_id or os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
        self.verify_token = verify_token or os.environ.get("WHATSAPP_VERIFY_TOKEN")
        self.dry_run = dry_run
        self._client = http_client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    async def send_text_message(
        self,
        to_phone: str,
        body: str,
        preview_url: bool = False,
    ) -> Dict[str, Any]:
        if not to_phone or not body.strip():
            raise ValueError("to_phone and body must not be empty")

        clean_phone = to_phone.replace("+", "").replace("-", "").replace(" ", "").strip()

        if self.dry_run:
            logger.info(f"[WhatsApp DRY-RUN] Sending text to {clean_phone}: {body[:60]}...")
            return {
                "success": True,
                "dry_run": True,
                "message_id": f"sim_wa_{int(datetime.now().timestamp())}",
                "to": clean_phone,
                "body": body,
            }

        if not self.access_token or not self.phone_number_id:
            raise WhatsAppClientError(
                "WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID must be configured for live WhatsApp dispatch"
            )

        client = await self._get_client()
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone,
            "type": "text",
            "text": {"preview_url": preview_url, "body": body},
        }

        response = await client.post(
            f"{GRAPH_API_BASE}/{self.phone_number_id}/messages",
            json=payload,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
            },
        )

        if response.status_code != 200:
            logger.error(f"WhatsApp API error: {response.status_code} - {response.text}")
            raise WhatsAppClientError(f"WhatsApp API error HTTP {response.status_code}: {response.text[:200]}")

        res_json = response.json()
        message_id = res_json.get("messages", [{}])[0].get("id", "unknown")
        return {
            "success": True,
            "dry_run": False,
            "message_id": message_id,
            "raw": res_json,
        }

    async def send_template_message(
        self,
        to_phone: str,
        template_name: str,
        language_code: str = "en",
        components: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        clean_phone = to_phone.replace("+", "").replace("-", "").replace(" ", "").strip()

        if self.dry_run:
            logger.info(f"[WhatsApp DRY-RUN] Sending template {template_name} to {clean_phone}")
            return {
                "success": True,
                "dry_run": True,
                "message_id": f"sim_wa_tpl_{int(datetime.now().timestamp())}",
                "to": clean_phone,
                "template": template_name,
            }

        if not self.access_token or not self.phone_number_id:
            raise WhatsAppClientError(
                "WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID must be configured for live WhatsApp dispatch"
            )

        client = await self._get_client()

        payload: Dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": clean_phone,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
            },
        }
        if components:
            payload["template"]["components"] = components

        response = await client.post(
            f"{GRAPH_API_BASE}/{self.phone_number_id}/messages",
            json=payload,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
            },
        )

        if response.status_code != 200:
            logger.error(f"WhatsApp template API error: {response.status_code} - {response.text}")
            raise WhatsAppClientError(f"WhatsApp template API error HTTP {response.status_code}: {response.text[:200]}")

        res_json = response.json()
        message_id = res_json.get("messages", [{}])[0].get("id", "unknown")
        return {
            "success": True,
            "dry_run": False,
            "message_id": message_id,
            "raw": res_json,
        }

    @staticmethod
    def parse_webhook_event(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parses incoming WhatsApp webhook payload into normalized event items."""
        events = []
        try:
            for entry in payload.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    for msg in value.get("messages", []):
                        events.append({
                            "type": "incoming_message",
                            "message_id": msg.get("id"),
                            "from": msg.get("from"),
                            "timestamp": msg.get("timestamp"),
                            "text": msg.get("text", {}).get("body", ""),
                            "context": msg.get("context", {}),
                        })
                    for status in value.get("statuses", []):
                        events.append({
                            "type": "status_update",
                            "message_id": status.get("id"),
                            "status": status.get("status"),
                            "recipient_id": status.get("recipient_id"),
                            "timestamp": status.get("timestamp"),
                        })
        except Exception as e:
            logger.warning(f"Error parsing WhatsApp webhook payload: {e}")
        return events


def get_whatsapp_client() -> WhatsAppClient:
    return WhatsAppClient()
