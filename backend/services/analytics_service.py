"""
Generic event tracking for db.analytics_events (Step A7) - standalone, no
dependency on the ticket/support-agent system (services/support_agent_service.py,
ticket_dedup_service.py, notification_service.py) built in Phase 4.

See db_models.py's AnalyticsEventDoc/ANALYTICS_EVENT_TYPES for the schema
and the reasoning behind each tracked event_type, and server.py's own
comments at each record_event(...) call site for exactly where/why each one
fires. internal_analytics_api.py is the read-only aggregation surface built
on top of this collection.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


async def ensure_indexes(db) -> None:
    # Funnel/aggregation queries (internal_analytics_api.py) filter by
    # event_type first, then read timestamp - matches that access pattern.
    await db.analytics_events.create_index([("event_type", 1), ("timestamp", -1)])
    # "this user's events" - not on any hot path yet, but cheap insurance
    # against an unindexed scan once one exists.
    await db.analytics_events.create_index("user_id")

    # One promotions doc per code - codes are looked up/created by their
    # code string, never by Mongo's own _id.
    await db.promotions.create_index("code", unique=True)


async def record_event(
    db, event_type: str, user_id: Optional[str], metadata: Optional[Dict[str, Any]] = None
) -> None:
    """Fire-and-forget event write - swallows and logs any failure rather
    than propagating, so instrumenting a real user action (plan generation,
    booking creation, payment success/expiry) can never turn a write hiccup
    on this side-channel collection into a 500 for that action. Same
    never-break-the-real-request principle as _AuditedTicketRoute's audit
    log write in internal_tickets_api.py."""
    try:
        await db.analytics_events.insert_one({
            "event_type": event_type,
            "user_id": user_id,
            "timestamp": datetime.now(timezone.utc),
            "metadata": metadata or {},
        })
    except Exception as e:
        logger.error(f"Failed to write analytics event {event_type!r}: {e}")
