"""
Marketing Channel Integrations for Bob (Task A.4).
Includes Buffer, Instagram Graph API, and WhatsApp Business Cloud API.
"""
from .buffer_client import BufferClient, get_buffer_client
from .instagram_client import InstagramClient, get_instagram_client
from .whatsapp_client import WhatsAppClient, get_whatsapp_client

__all__ = [
    "BufferClient",
    "get_buffer_client",
    "InstagramClient",
    "get_instagram_client",
    "WhatsAppClient",
    "get_whatsapp_client",
]
