"""Travel Wallet (File Storage) API router (/api/wallet/*).
"""
import io
import os
import time
import uuid
import hmac
import logging
from datetime import datetime, timezone
from typing import Optional, Dict

from PIL import Image
from fastapi import APIRouter, File, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel

from routes.shared import (
    db,
    get_current_user,
    _sign_wallet_download,
    WALLET_DOWNLOAD_URL_TTL_SECONDS,
)
from services import storage_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/wallet", tags=["wallet"])


class WalletItem(BaseModel):
    item_id: str
    user_id: str
    file_path: str
    original_filename: str
    content_type: str
    size: int
    category: str  # 'boarding_pass', 'ticket', 'voucher', 'document'
    title: str
    description: Optional[str] = None
    trip_id: Optional[str] = None
    created_at: str


# Only what the frontend upload widget actually offers (accept=".pdf,.jpg,
# .jpeg,.png,.gif,.webp" in WalletPage.jsx) - never trust the client's
# Content-Type header for this: an HTML file uploaded with a spoofed
# "image/jpeg" header would otherwise get served back with that same
# spoofed type later, a stored-XSS foothold if anything ever renders it
# inline. The extension used for GridFS's storage path is derived from the
# sniffed type below too, not the client-supplied filename.
_WALLET_MIME_TO_EXT = {
    "image/jpeg": "jpg", "image/png": "png", "image/gif": "gif",
    "image/webp": "webp", "application/pdf": "pdf",
}
_WALLET_PDF_MAGIC = b"%PDF-"
_PILLOW_FORMAT_TO_MIME = {"JPEG": "image/jpeg", "PNG": "image/png", "GIF": "image/gif", "WEBP": "image/webp"}


def _sniff_wallet_content_type(data: bytes) -> Optional[str]:
    """Identify the real file type from its bytes, never the client-supplied
    Content-Type. PDFs are checked by header magic bytes (the same signature
    every PDF reader relies on); images are opened with Pillow, which parses
    real header structure rather than trusting an extension - Image.open()
    already raises for anything that isn't a genuine image of a format it
    knows, and .verify() additionally checks the file isn't truncated/
    corrupt. Returns None (rejected) for anything else, including a
    same-named-but-wrong-content file like an HTML page saved as "x.jpg"."""
    if data.startswith(_WALLET_PDF_MAGIC):
        return "application/pdf"
    try:
        img = Image.open(io.BytesIO(data))
        fmt = img.format
        img.verify()
    except Exception:
        return None
    return _PILLOW_FORMAT_TO_MIME.get(fmt)


@router.post("/upload")
async def upload_wallet_item(
    request: Request,
    file: UploadFile = File(...),
    category: str = "document",
    title: str = "",
    description: str = "",
    trip_id: Optional[str] = None
):
    user = await get_current_user(request)

    data = await file.read()

    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 10MB)")

    content_type = _sniff_wallet_content_type(data)
    if content_type not in _WALLET_MIME_TO_EXT:
        raise HTTPException(
            status_code=415,
            detail="Unsupported file type - only JPEG, PNG, GIF, WEBP images and PDF are accepted",
        )

    storage_path = storage_service.build_path(user.user_id, _WALLET_MIME_TO_EXT[content_type])

    try:
        result = await storage_service.put_object(storage_path, data, content_type)
    except Exception as e:
        logger.error(f"Storage upload error: {e}")
        raise HTTPException(status_code=500, detail="File upload failed")

    item_id = f"wallet_{uuid.uuid4().hex[:12]}"
    item_doc = {
        "item_id": item_id,
        "user_id": user.user_id,
        "file_path": result["path"],
        "original_filename": file.filename,
        "content_type": content_type,
        "size": result.get("size", len(data)),
        "category": category,
        "title": title or file.filename,
        "description": description,
        "trip_id": trip_id,
        "is_deleted": False,
        "created_at": datetime.now(timezone.utc),
    }
    await db.wallet_items.insert_one(item_doc)
    item_doc.pop("_id", None)
    return item_doc


@router.get("")
async def list_wallet_items(request: Request, category: Optional[str] = None, trip_id: Optional[str] = None):
    user = await get_current_user(request)
    
    query = {"user_id": user.user_id, "is_deleted": False}
    if category:
        query["category"] = category
    if trip_id:
        query["trip_id"] = trip_id
    
    items = await db.wallet_items.find(query, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"items": items}


@router.get("/{item_id}/download-url")
async def get_wallet_download_url(item_id: str, request: Request):
    """Mints a short-lived signed download link for this item. Session-
    authenticated (ownership is checked here, once) so the actual download
    route below never needs the session cookie/token at all - it previously
    accepted the raw session_token as a URL query param, which leaks into
    server logs, browser history, and any proxy in the path. The signature
    is scoped to this specific item_id + expiry, so it can't be replayed for
    a different item or after it expires."""
    user = await get_current_user(request)
    item = await db.wallet_items.find_one(
        {"item_id": item_id, "user_id": user.user_id, "is_deleted": False},
        {"_id": 0}
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    expires = int(time.time()) + WALLET_DOWNLOAD_URL_TTL_SECONDS
    signature = _sign_wallet_download(item_id, expires)
    return {"item_id": item_id, "expires": expires, "signature": signature}


@router.get("/{item_id}/download")
async def download_wallet_item(
    item_id: str,
    expires: int = Query(...),
    signature: str = Query(...),
):
    if int(time.time()) > expires:
        raise HTTPException(status_code=401, detail="Download link expired")
    if not hmac.compare_digest(_sign_wallet_download(item_id, expires), signature):
        raise HTTPException(status_code=401, detail="Invalid download link")

    item = await db.wallet_items.find_one(
        {"item_id": item_id, "is_deleted": False},
        {"_id": 0}
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    try:
        data, content_type = await storage_service.get_object(item["file_path"])
    except Exception as e:
        logger.error(f"Storage download error: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve file")

    # attachment (not inline) + nosniff so a mis-classified or since-changed
    # file can never be rendered inline by the browser, even as a
    # defense-in-depth backstop to the upload-time content sniffing above.
    safe_filename = os.path.basename(item["original_filename"]).replace('"', "'").replace("\r", "").replace("\n", "")
    return Response(
        content=data,
        media_type=item.get("content_type", content_type),
        headers={
            "Content-Disposition": f'attachment; filename="{safe_filename}"',
            "X-Content-Type-Options": "nosniff",
        }
    )


@router.delete("/{item_id}")
async def delete_wallet_item(item_id: str, request: Request):
    user = await get_current_user(request)
    result = await db.wallet_items.update_one(
        {"item_id": item_id, "user_id": user.user_id},
        {"$set": {"is_deleted": True, "deleted_at": datetime.now(timezone.utc)}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"message": "Item deleted successfully"}
