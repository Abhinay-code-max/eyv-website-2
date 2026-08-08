"""
Travel Rewards Points System
Earn points for bookings, trips, referrals.
Redeem points for discounts.
"""
import logging
from typing import Optional
from datetime import datetime, timezone

from . import ignav_service
from . import booking_expiry_service

logger = logging.getLogger(__name__)

# Earning rules
EARN_RULES = {
    'booking_flight': 100,
    'booking_hotel': 150,
    'trip_completed': 200,
    'first_booking_bonus': 500,
    'premium_subscription': 1000,
    'referral': 250,
}

# Redemption: 100 points = $1 discount
POINTS_TO_USD = 0.01

# Tiers based on lifetime points
TIERS = [
    {'name': 'Explorer', 'min_points': 0, 'multiplier': 1.0, 'color': '#86A8B3'},
    {'name': 'Wanderer', 'min_points': 1000, 'multiplier': 1.25, 'color': '#C47245'},
    {'name': 'Voyager', 'min_points': 5000, 'multiplier': 1.5, 'color': '#E8B273'},
    {'name': 'Globetrotter', 'min_points': 15000, 'multiplier': 2.0, 'color': '#2A4B5C'},
]


def get_user_tier(lifetime_points: int) -> dict:
    """Determine user tier based on lifetime points."""
    current_tier = TIERS[0]
    for tier in TIERS:
        if lifetime_points >= tier['min_points']:
            current_tier = tier
    return current_tier


def get_next_tier(lifetime_points: int) -> Optional[dict]:
    """Get the next tier user can reach."""
    for tier in TIERS:
        if lifetime_points < tier['min_points']:
            return tier
    return None


async def award_points(db, user_id: str, action: str, amount: Optional[int] = None, reference_id: Optional[str] = None, description: str = "") -> dict:
    """Award points to a user for an action."""
    points = amount if amount is not None else EARN_RULES.get(action, 0)
    if points <= 0:
        return {'points_awarded': 0}
    
    # Apply tier multiplier
    user_rewards = await get_or_create_rewards(db, user_id)
    tier = get_user_tier(user_rewards['lifetime_points'])
    final_points = int(points * tier['multiplier'])
    
    transaction = {
        'transaction_id': f"tx_{action}_{datetime.now(timezone.utc).timestamp()}",
        'user_id': user_id,
        'action': action,
        'points': final_points,
        'base_points': points,
        'multiplier': tier['multiplier'],
        'reference_id': reference_id,
        'description': description or f"Earned {final_points} points for {action.replace('_', ' ')}",
        'type': 'earn',
        'created_at': datetime.now(timezone.utc),
    }

    await db.rewards_transactions.insert_one(transaction)

    # Update user rewards
    await db.user_rewards.update_one(
        {'user_id': user_id},
        {
            '$inc': {
                'available_points': final_points,
                'lifetime_points': final_points
            },
            '$set': {'updated_at': datetime.now(timezone.utc)}
        },
        upsert=True
    )
    
    return {'points_awarded': final_points, 'tier': tier['name']}


async def redeem_points(db, user_id: str, points: int, reference_id: Optional[str] = None, description: str = "") -> dict:
    """Redeem points for a discount. Atomic filtered $inc, not a read-check-
    write - the old version read `available_points`, checked it in Python,
    then wrote the decrement as a separate step, which is a classic TOCTOU:
    two concurrent redeem calls against the same balance could both read a
    "sufficient" balance before either write landed, jointly overdrawing the
    user below zero. The filter (`available_points >= points`) and the
    decrement now happen in the same Mongo operation - only whichever
    request's update Mongo actually applies gets to proceed to recording the
    transaction, the other cleanly sees matched_count == 0 and raises. Same
    pattern as reserve_points below and the payment-status race fix in
    server.py's stripe_webhook/get_payment_status (find_one_and_update
    filtered on current state instead of read-then-write)."""
    await get_or_create_rewards(db, user_id)

    result = await db.user_rewards.update_one(
        {'user_id': user_id, 'available_points': {'$gte': points}},
        {
            '$inc': {'available_points': -points},
            '$set': {'updated_at': datetime.now(timezone.utc)}
        }
    )
    if result.matched_count == 0:
        raise ValueError("Insufficient points")

    discount_usd = points * POINTS_TO_USD

    transaction = {
        'transaction_id': f"tx_redeem_{datetime.now(timezone.utc).timestamp()}",
        'user_id': user_id,
        'action': 'redeem',
        'points': -points,
        'discount_usd': discount_usd,
        'reference_id': reference_id,
        'description': description or f"Redeemed {points} points for ${discount_usd:.2f} discount",
        'type': 'redeem',
        'created_at': datetime.now(timezone.utc),
    }

    await db.rewards_transactions.insert_one(transaction)

    return {'points_redeemed': points, 'discount_usd': discount_usd}


async def reserve_points(db, user_id: str, points: int) -> bool:
    """Atomically reserve `points` from a user's available balance for a
    pending Stripe checkout (server.py's create_checkout) - filtered $inc,
    same shape as redeem_points above: the sufficiency check and the
    decrement happen in one Mongo operation, so two concurrent checkouts
    against the same balance can't both pass a check-then-later-deduct race
    and jointly overspend. Returns True if the reservation succeeded, False
    if the user doesn't have enough available_points - callers should treat
    False as "insufficient points" (e.g. HTTP 400), not raise, since this is
    the normal/expected outcome of a race loser rather than an error.

    No rewards_transactions row is written here - a reservation is
    provisional. The permanent audit-trail row is written later by
    finalize_reserved_points once the payment actually succeeds; if the
    checkout instead expires or is abandoned, refund_points (or the
    refund_stale_reserved_points sweep, for missed expiry events) gives the
    points back with no transaction row ever having existed."""
    if points <= 0:
        return True
    await get_or_create_rewards(db, user_id)
    result = await db.user_rewards.update_one(
        {'user_id': user_id, 'available_points': {'$gte': points}},
        {
            '$inc': {'available_points': -points},
            '$set': {'updated_at': datetime.now(timezone.utc)}
        }
    )
    return result.matched_count > 0


async def refund_points(db, user_id: str, points: int) -> None:
    """Inverse of reserve_points - returns previously-reserved points to a
    user's available balance because the checkout they were reserved for
    expired or failed before completing. Unconditional $inc (there's no
    "insufficient balance" failure mode for giving points back) with
    upsert=True so this is safe to call even in the unlikely case the
    user_rewards document doesn't exist (reserve_points always creates it
    first, so this should never actually need to upsert in practice)."""
    if points <= 0:
        return
    await db.user_rewards.update_one(
        {'user_id': user_id},
        {
            '$inc': {'available_points': points},
            '$set': {'updated_at': datetime.now(timezone.utc)}
        },
        upsert=True,
    )


async def finalize_reserved_points(db, user_id: str, points: int, reference_id: Optional[str] = None, description: str = "") -> None:
    """Record the permanent rewards_transactions audit row for points
    already decremented by reserve_points at checkout time. Deliberately
    does NOT touch available_points - the balance was already spent at
    reservation time, so finalizing again would double-deduct. This is only
    ever called once server.py's caller has confirmed (via an atomic
    reserved -> finalized transition on the payment_transactions document)
    that the reservation is still validly held; it does not re-check the
    balance itself."""
    if points <= 0:
        return
    discount_usd = points * POINTS_TO_USD
    transaction = {
        'transaction_id': f"tx_redeem_{datetime.now(timezone.utc).timestamp()}",
        'user_id': user_id,
        'action': 'redeem',
        'points': -points,
        'discount_usd': discount_usd,
        'reference_id': reference_id,
        'description': description or f"Redeemed {points} points for ${discount_usd:.2f} discount",
        'type': 'redeem',
        'created_at': datetime.now(timezone.utc),
    }
    await db.rewards_transactions.insert_one(transaction)


async def refund_stale_reserved_points(db) -> int:
    """Refund points reserved at checkout (create_checkout -> reserve_points)
    whose Stripe Checkout Session was abandoned without Stripe's own
    checkout.session.expired webhook ever firing and without the user ever
    polling /payments/status again (e.g. the tab was closed before Checkout
    even loaded) - the exact same missed-event gap
    services.booking_expiry_service.expire_stale_pending_bookings backstops
    for booking status, mirrored here for the points side of the same
    checkout. Reuses that module's STALE_PENDING_TTL rather than a second,
    separately-tuned constant, since both are bounded by the same underlying
    Stripe Checkout Session lifetime.

    Unlike expire_stale_pending_bookings's single update_many (everything it
    needs to change lives on the one document being matched), refunding
    here has to $inc a *different* collection's document (user_rewards) for
    each match, so this walks the stale transactions and, per document,
    does an atomic find_one_and_update filtered on
    points_reservation_status == 'reserved' before calling refund_points -
    the same reserved -> refunded transition server.py's
    _process_expired_payment uses. That filter is what prevents this sweep
    from double-refunding a reservation _process_expired_payment (webhook
    or poll path) already refunded moments earlier, or vice versa - only
    whichever caller's update actually flips the status gets to call
    refund_points.

    Returns the number of reservations refunded, for logging/observability."""
    cutoff = datetime.now(timezone.utc) - booking_expiry_service.STALE_PENDING_TTL
    stale = await db.payment_transactions.find(
        {
            'payment_status': 'pending',
            'points_reservation_status': 'reserved',
            'created_at': {'$lt': cutoff},
        },
        {'_id': 0, 'session_id': 1, 'user_id': 1, 'points_used': 1},
    ).to_list(None)

    refunded_count = 0
    for txn in stale:
        updated = await db.payment_transactions.find_one_and_update(
            {'session_id': txn['session_id'], 'points_reservation_status': 'reserved'},
            {'$set': {'points_reservation_status': 'refunded'}},
        )
        if updated is not None:
            await refund_points(db, txn['user_id'], txn['points_used'])
            refunded_count += 1

    if refunded_count:
        logger.info(
            f"refund_stale_reserved_points: refunded {refunded_count} stale "
            f"point reservation(s) older than {booking_expiry_service.STALE_PENDING_TTL}"
        )
    return refunded_count


async def get_or_create_rewards(db, user_id: str) -> dict:
    """Get or create user rewards record."""
    rewards = await db.user_rewards.find_one({'user_id': user_id}, {'_id': 0})
    if not rewards:
        rewards = {
            'user_id': user_id,
            'available_points': 0,
            'lifetime_points': 0,
            'created_at': datetime.now(timezone.utc),
            'updated_at': datetime.now(timezone.utc),
        }
        await db.user_rewards.insert_one(dict(rewards))
    return rewards


async def get_user_rewards_summary(db, user_id: str) -> dict:
    """Get full rewards summary for a user."""
    rewards = await get_or_create_rewards(db, user_id)
    tier = get_user_tier(rewards['lifetime_points'])
    next_tier = get_next_tier(rewards['lifetime_points'])
    
    transactions = await db.rewards_transactions.find(
        {'user_id': user_id},
        {'_id': 0}
    ).sort('created_at', -1).to_list(50)

    # available_discount_usd is the canonical value (100 points = $1); the
    # INR figure alongside it is derived from that same live FX rate
    # already used everywhere else (services.ignav_service), not a new
    # conversion - kept alongside the USD value rather than replacing it.
    available_discount_usd = rewards['available_points'] * POINTS_TO_USD
    await ignav_service._refresh_rates_if_stale()
    available_discount_inr = ignav_service._to_inr(available_discount_usd, 'USD')

    return {
        'available_points': rewards['available_points'],
        'lifetime_points': rewards['lifetime_points'],
        'available_discount_usd': available_discount_usd,
        'available_discount_inr': available_discount_inr,
        'current_tier': tier,
        'next_tier': next_tier,
        'points_to_next_tier': (next_tier['min_points'] - rewards['lifetime_points']) if next_tier else 0,
        'transactions': transactions,
        'earn_rules': EARN_RULES,
        'all_tiers': TIERS,
    }
