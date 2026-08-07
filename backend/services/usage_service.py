"""
Lightweight in-app usage tracking for the paid providers (Gemini, Duffel,
SerpApi) - a backup signal for eyeballing spikes, NOT a replacement for
each provider's own dashboard billing alarms (those still need to be
configured manually in each provider's console).

Every call is one doc in db.provider_usage: {provider, user_id, created_at,
meta}. get_usage_summary() aggregates counts per provider for today and
the trailing 7 days for the admin usage-summary endpoint.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

PROVIDERS = ("gemini", "duffel", "serpapi")


async def log_usage(db, provider: str, user_id: Optional[str] = None, meta: Optional[dict] = None) -> None:
    """Fire-and-forget usage log. Never raises - a logging failure must not
    break the real request that triggered the provider call."""
    try:
        await db.provider_usage.insert_one({
            "provider": provider,
            "user_id": user_id,
            "created_at": datetime.now(timezone.utc),
            "meta": meta or {},
        })
    except Exception as e:
        logger.warning(f"Failed to log provider usage ({provider}): {e}")


async def _counts_since(db, since: datetime) -> dict:
    # `since` must be a native datetime, matching how created_at is now
    # written above - see migrations/0001_normalize_timestamps_to_datetime.py
    # for why this matters: a Date $gte query against a still-string
    # created_at (pre-migration data) does not compare chronologically at
    # all (MongoDB compares by BSON type when types differ), so this would
    # silently undercount until the database is migrated.
    pipeline = [
        {"$match": {"created_at": {"$gte": since}}},
        {"$group": {"_id": "$provider", "count": {"$sum": 1}}},
    ]
    rows = await db.provider_usage.aggregate(pipeline).to_list(None)
    counts = {row["_id"]: row["count"] for row in rows}
    return {provider: counts.get(provider, 0) for provider in PROVIDERS}


async def get_usage_summary(db) -> dict:
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=7)
    return {
        "today": await _counts_since(db, today_start),
        "last_7_days": await _counts_since(db, week_start),
        "generated_at": now.isoformat(),
    }
