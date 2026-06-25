"""
Emergent Object Storage Service for Travel Wallet
"""
import os
import uuid
import logging
import requests
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

STORAGE_URL = "https://integrations.emergentagent.com/objstore/api/v1/storage"
APP_NAME = "eyv-travel"

_storage_key = None


def _get_emergent_key():
    return os.environ.get("EMERGENT_LLM_KEY")


def init_storage() -> Optional[str]:
    """Initialize storage. Returns storage_key."""
    global _storage_key
    if _storage_key:
        return _storage_key
    
    emergent_key = _get_emergent_key()
    if not emergent_key:
        logger.error("EMERGENT_LLM_KEY not set")
        return None
    
    try:
        resp = requests.post(
            f"{STORAGE_URL}/init",
            json={"emergent_key": emergent_key},
            timeout=30
        )
        resp.raise_for_status()
        _storage_key = resp.json()["storage_key"]
        logger.info("Storage initialized successfully")
        return _storage_key
    except Exception as e:
        logger.error(f"Storage init failed: {e}")
        return None


def put_object(path: str, data: bytes, content_type: str) -> dict:
    """Upload file. Returns {"path": "...", "size": 123, "etag": "..."}"""
    key = init_storage()
    if not key:
        raise Exception("Storage not initialized")
    
    resp = requests.put(
        f"{STORAGE_URL}/objects/{path}",
        headers={"X-Storage-Key": key, "Content-Type": content_type},
        data=data,
        timeout=120
    )
    resp.raise_for_status()
    return resp.json()


def get_object(path: str) -> Tuple[bytes, str]:
    """Download file. Returns (content_bytes, content_type)."""
    key = init_storage()
    if not key:
        raise Exception("Storage not initialized")
    
    resp = requests.get(
        f"{STORAGE_URL}/objects/{path}",
        headers={"X-Storage-Key": key},
        timeout=60
    )
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "application/octet-stream")


def build_path(user_id: str, file_ext: str) -> str:
    """Build storage path with proper convention."""
    return f"{APP_NAME}/uploads/{user_id}/{uuid.uuid4().hex}.{file_ext}"


MIME_TYPES = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "gif": "image/gif", "webp": "image/webp", "pdf": "application/pdf",
    "json": "application/json", "csv": "text/csv", "txt": "text/plain"
}
