"""
Daily free-tier trip-generation quota.

Free accounts get FREE_DAILY_TRIP_LIMIT generations per calendar day (UTC),
resetting at midnight rather than a rolling window - simplest to reason
about and to surface to the user ("resets at midnight UTC"). Premium
accounts are never subject to this - callers must check premium status
themselves before calling try_consume_trip_generation.

One doc per (user_id, date) in db.generation_quota, atomically incremented
via find_one_and_update so concurrent requests can't both slip through
under the limit.
"""
import logging
from datetime import datetime, timezone
from typing import Optional
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)

FREE_DAILY_TRIP_LIMIT = 5


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def ensure_indexes(db) -> None:
    await db.generation_quota.create_index([("user_id", 1), ("date", 1)], unique=True)


async def try_consume_trip_generation(db, user_id: str, limit: int = FREE_DAILY_TRIP_LIMIT) -> dict:
    """Atomically consume one generation from today's quota if under limit.

    Returns {"allowed": bool, "used": int, "limit": int}. `used` reflects
    the count AFTER this call when allowed, or the current (unchanged)
    count when not allowed.
    """
    today = _today()

    result = await db.generation_quota.find_one_and_update(
        {"user_id": user_id, "date": today, "count": {"$lt": limit}},
        {"$inc": {"count": 1}},
        return_document=ReturnDocument.AFTER,
    )
    if result:
        return {"allowed": True, "used": result["count"], "limit": limit}

    existing = await db.generation_quota.find_one({"user_id": user_id, "date": today})
    if existing:
        # Doc exists and is already at/over the limit.
        return {"allowed": False, "used": existing.get("count", limit), "limit": limit}

    # First request of the day for this user - create the counter.
    try:
        await db.generation_quota.insert_one({"user_id": user_id, "date": today, "count": 1})
        return {"allowed": True, "used": 1, "limit": limit}
    except DuplicateKeyError:
        # Lost a race with another concurrent first-request-of-the-day insert.
        # Try the atomic increment once more against the doc that just landed.
        result = await db.generation_quota.find_one_and_update(
            {"user_id": user_id, "date": today, "count": {"$lt": limit}},
            {"$inc": {"count": 1}},
            return_document=ReturnDocument.AFTER,
        )
        if result:
            return {"allowed": True, "used": result["count"], "limit": limit}
        return {"allowed": False, "used": limit, "limit": limit}


async def get_quota_status(db, user_id: str, limit: int = FREE_DAILY_TRIP_LIMIT) -> dict:
    """Read-only peek at today's usage, for display - never increments."""
    existing = await db.generation_quota.find_one({"user_id": user_id, "date": _today()})
    used = existing.get("count", 0) if existing else 0
    return {"used": used, "limit": limit, "remaining": max(0, limit - used)}
