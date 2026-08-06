"""
Sweeps stale "pending_payment" bookings - a safety net for the case where
Stripe's own checkout.session.expired webhook is missed or never fires (a
dropped webhook delivery, or the user closing the tab before Stripe
Checkout even loaded, so no session-level event happens at all). See
server.py's create_booking / _process_successful_payment /
_process_expired_payment for the rest of the booking status state machine.
"""
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# Well inside Stripe's own 24h Checkout Session expiry window - this TTL is
# a backstop for cases Stripe's own expiry event never reaches us, not a
# race against Stripe's own expiry.
STALE_PENDING_TTL = timedelta(minutes=90)


async def expire_stale_pending_bookings(db) -> int:
    """Flip bookings stuck in "pending_payment" past STALE_PENDING_TTL to
    "payment_failed". Filtered on status="pending_payment" so this can
    never clobber a booking a genuinely successful (possibly late) payment
    has already confirmed - _process_successful_payment's write is
    unconditional and always wins, regardless of whether it runs before or
    after this sweep. Safe to call repeatedly / on a timer: each run only
    matches documents still pending at the moment of the write, so a
    booking already resolved (confirmed, previously expired, or cancelled)
    by an earlier run or a webhook is simply not touched again.

    Returns the number of bookings flipped, for logging/observability.
    """
    cutoff = (datetime.now(timezone.utc) - STALE_PENDING_TTL).isoformat()
    result = await db.bookings.update_many(
        {"status": "pending_payment", "created_at": {"$lt": cutoff}},
        {"$set": {
            "status": "payment_failed",
            "payment_failed_at": datetime.now(timezone.utc).isoformat(),
        }},
    )
    if result.modified_count:
        logger.info(
            f"expire_stale_pending_bookings: flipped {result.modified_count} "
            f"booking(s) older than {STALE_PENDING_TTL} to payment_failed"
        )
    return result.modified_count
