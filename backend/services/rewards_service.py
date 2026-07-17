"""
Travel Rewards Points System
Earn points for bookings, trips, referrals.
Redeem points for discounts.
"""
import logging
from typing import Optional
from datetime import datetime, timezone

from . import ignav_service

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
        'created_at': datetime.now(timezone.utc).isoformat()
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
            '$set': {'updated_at': datetime.now(timezone.utc).isoformat()}
        },
        upsert=True
    )
    
    return {'points_awarded': final_points, 'tier': tier['name']}


async def redeem_points(db, user_id: str, points: int, reference_id: Optional[str] = None, description: str = "") -> dict:
    """Redeem points for a discount."""
    rewards = await get_or_create_rewards(db, user_id)
    
    if rewards['available_points'] < points:
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
        'created_at': datetime.now(timezone.utc).isoformat()
    }
    
    await db.rewards_transactions.insert_one(transaction)
    
    await db.user_rewards.update_one(
        {'user_id': user_id},
        {
            '$inc': {'available_points': -points},
            '$set': {'updated_at': datetime.now(timezone.utc).isoformat()}
        }
    )
    
    return {'points_redeemed': points, 'discount_usd': discount_usd}


async def get_or_create_rewards(db, user_id: str) -> dict:
    """Get or create user rewards record."""
    rewards = await db.user_rewards.find_one({'user_id': user_id}, {'_id': 0})
    if not rewards:
        rewards = {
            'user_id': user_id,
            'available_points': 0,
            'lifetime_points': 0,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat()
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
