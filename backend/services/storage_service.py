"""
GridFS Object Storage Service for Travel Wallet
"""
import os
import uuid
import logging
from typing import Tuple, Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket

logger = logging.getLogger(__name__)

APP_NAME = "eyv-travel"

_bucket: Optional[AsyncIOMotorGridFSBucket] = None


def _get_bucket() -> AsyncIOMotorGridFSBucket:
    global _bucket
    if _bucket is None:
        mongo_url = os.environ['MONGO_URL']
        db_name = os.environ['DB_NAME']
        client = AsyncIOMotorClient(mongo_url)
        _bucket = AsyncIOMotorGridFSBucket(client[db_name], bucket_name="wallet_files")
    return _bucket


def init_storage() -> None:
    """Initialize the storage backend. Kept for interface compatibility."""
    _get_bucket()


async def put_object(path: str, data: bytes, content_type: str) -> dict:
    """Upload file. Returns {"path": "...", "size": 123}"""
    bucket = _get_bucket()
    await bucket.upload_from_stream(path, data, metadata={"content_type": content_type})
    return {"path": path, "size": len(data)}


async def get_object(path: str) -> Tuple[bytes, str]:
    """Download file. Returns (content_bytes, content_type)."""
    bucket = _get_bucket()
    grid_out = await bucket.open_download_stream_by_name(path)
    data = await grid_out.read()
    content_type = (grid_out.metadata or {}).get("content_type", "application/octet-stream")
    return data, content_type


def build_path(user_id: str, file_ext: str) -> str:
    """Build storage path with proper convention."""
    return f"{APP_NAME}/uploads/{user_id}/{uuid.uuid4().hex}.{file_ext}"


MIME_TYPES = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "gif": "image/gif", "webp": "image/webp", "pdf": "application/pdf",
    "json": "application/json", "csv": "text/csv", "txt": "text/plain"
}
