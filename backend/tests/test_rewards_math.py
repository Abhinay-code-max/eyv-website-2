"""
Unit tests for services/rewards_service.py's pure points/tier math - a money
path (points translate directly into a real $ discount via POINTS_TO_USD)
that test_rewards_payments.py only ever exercises indirectly, through the
live HTTP /api/rewards endpoints. These call the service functions directly
against a real test Mongo (same _db()/_run() pattern as the rest of this
suite), no HTTP layer, no live server.
"""
import asyncio
import os
import sys
import uuid

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

from services import rewards_service  # noqa: E402

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')


def _db():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def user_id():
    uid = f"test_rewards_math_{uuid.uuid4().hex[:12]}"
    yield uid

    async def _cleanup():
        db = _db()
        await db.user_rewards.delete_many({'user_id': uid})
        await db.rewards_transactions.delete_many({'user_id': uid})
    _run(_cleanup())


def _set_lifetime_points(user_id, points):
    """Seed a user straight into a given tier by lifetime_points, bypassing
    award_points (which would itself apply a multiplier) - tests that need a
    specific starting tier want direct control over that number."""
    async def _do():
        db = _db()
        await db.user_rewards.update_one(
            {'user_id': user_id},
            {'$set': {'user_id': user_id, 'available_points': points, 'lifetime_points': points}},
            upsert=True,
        )
    _run(_do())


# ═══════════════════ Tier boundaries (get_user_tier / get_next_tier) ═══════════════════

@pytest.mark.parametrize("lifetime_points,expected_tier", [
    (0, 'Explorer'),
    (999, 'Explorer'),
    (1000, 'Wanderer'),
    (4999, 'Wanderer'),
    (5000, 'Voyager'),
    (14999, 'Voyager'),
    (15000, 'Globetrotter'),
    (1_000_000, 'Globetrotter'),
])
def test_tier_boundaries_are_inclusive_at_min_points(lifetime_points, expected_tier):
    assert rewards_service.get_user_tier(lifetime_points)['name'] == expected_tier


def test_next_tier_progression():
    assert rewards_service.get_next_tier(0)['name'] == 'Wanderer'
    assert rewards_service.get_next_tier(999)['name'] == 'Wanderer'
    assert rewards_service.get_next_tier(1000)['name'] == 'Voyager'
    assert rewards_service.get_next_tier(14999)['name'] == 'Globetrotter'


def test_next_tier_is_none_at_max_tier():
    assert rewards_service.get_next_tier(15000) is None
    assert rewards_service.get_next_tier(999_999) is None


# ═══════════════════ award_points ═══════════════════

def test_award_points_uses_earn_rules_table(user_id):
    result = _run(rewards_service.award_points(_db(), user_id, 'booking_flight'))
    assert result['points_awarded'] == rewards_service.EARN_RULES['booking_flight']
    assert result['tier'] == 'Explorer'


def test_award_points_applies_tier_multiplier(user_id):
    """A Wanderer-tier user (1.25x) earning the 100-point booking_flight
    action should actually get 125, not 100 - the multiplier is applied at
    award time based on lifetime_points *before* this award, not after."""
    _set_lifetime_points(user_id, 1000)  # exactly the Wanderer threshold
    result = _run(rewards_service.award_points(_db(), user_id, 'booking_flight'))
    assert result['points_awarded'] == 125
    assert result['tier'] == 'Wanderer'


def test_award_points_custom_amount_overrides_earn_rules(user_id):
    result = _run(rewards_service.award_points(_db(), user_id, 'referral', amount=999))
    assert result['points_awarded'] == 999


def test_award_points_unknown_action_with_no_amount_awards_zero_and_is_a_noop(user_id):
    """An action key not in EARN_RULES and no explicit amount must award 0
    points AND must not touch the DB at all - no rewards_transactions row,
    no user_rewards record created. Money-path correctness: a no-op award
    call should leave zero trace, not a zero-value transaction."""
    result = _run(rewards_service.award_points(_db(), user_id, 'not_a_real_action'))
    assert result == {'points_awarded': 0}

    async def _check():
        db = _db()
        txns = await db.rewards_transactions.find({'user_id': user_id}).to_list(10)
        rewards = await db.user_rewards.find_one({'user_id': user_id})
        return txns, rewards
    txns, rewards = _run(_check())
    assert txns == []
    assert rewards is None


def test_award_points_persists_reference_id_and_increments_balance(user_id):
    _run(rewards_service.award_points(_db(), user_id, 'booking_hotel', reference_id='booking_abc123'))

    async def _check():
        db = _db()
        txn = await db.rewards_transactions.find_one({'user_id': user_id}, {'_id': 0})
        rewards = await db.user_rewards.find_one({'user_id': user_id}, {'_id': 0})
        return txn, rewards
    txn, rewards = _run(_check())
    assert txn['reference_id'] == 'booking_abc123'
    assert txn['points'] == 150
    assert rewards['available_points'] == 150
    assert rewards['lifetime_points'] == 150


def test_award_points_accumulates_across_multiple_calls(user_id):
    _run(rewards_service.award_points(_db(), user_id, 'booking_flight'))
    _run(rewards_service.award_points(_db(), user_id, 'booking_hotel'))

    async def _check():
        return await _db().user_rewards.find_one({'user_id': user_id}, {'_id': 0})
    rewards = _run(_check())
    assert rewards['available_points'] == 100 + 150
    assert rewards['lifetime_points'] == 100 + 150


# ═══════════════════ redeem_points ═══════════════════

def test_redeem_points_computes_correct_discount(user_id):
    _set_lifetime_points(user_id, 500)
    result = _run(rewards_service.redeem_points(_db(), user_id, 200))
    assert result['points_redeemed'] == 200
    assert result['discount_usd'] == pytest.approx(200 * rewards_service.POINTS_TO_USD)


def test_redeem_points_decrements_available_but_not_lifetime(user_id):
    """lifetime_points is a monotonic tier-progression counter - redeeming
    must never reduce it, only available_points (the spendable balance)."""
    _set_lifetime_points(user_id, 500)
    _run(rewards_service.redeem_points(_db(), user_id, 200))

    async def _check():
        return await _db().user_rewards.find_one({'user_id': user_id}, {'_id': 0})
    rewards = _run(_check())
    assert rewards['available_points'] == 300
    assert rewards['lifetime_points'] == 500


def test_redeem_points_insufficient_balance_raises_and_does_not_mutate(user_id):
    _set_lifetime_points(user_id, 50)
    with pytest.raises(ValueError):
        _run(rewards_service.redeem_points(_db(), user_id, 200))

    async def _check():
        db = _db()
        rewards = await db.user_rewards.find_one({'user_id': user_id}, {'_id': 0})
        txns = await db.rewards_transactions.find({'user_id': user_id}).to_list(10)
        return rewards, txns
    rewards, txns = _run(_check())
    # Balance must be exactly what it was before the failed redeem attempt -
    # not partially decremented, and no stray transaction row left behind.
    assert rewards['available_points'] == 50
    assert txns == []


def test_redeem_points_exact_balance_is_allowed(user_id):
    _set_lifetime_points(user_id, 100)
    result = _run(rewards_service.redeem_points(_db(), user_id, 100))
    assert result['points_redeemed'] == 100

    async def _check():
        return await _db().user_rewards.find_one({'user_id': user_id}, {'_id': 0})
    rewards = _run(_check())
    assert rewards['available_points'] == 0


# ═══════════════════ get_or_create_rewards / get_user_rewards_summary ═══════════════════

def test_get_or_create_rewards_initializes_new_user_at_zero(user_id):
    rewards = _run(rewards_service.get_or_create_rewards(_db(), user_id))
    assert rewards['available_points'] == 0
    assert rewards['lifetime_points'] == 0


def test_get_or_create_rewards_does_not_overwrite_existing_balance(user_id):
    _set_lifetime_points(user_id, 250)
    rewards = _run(rewards_service.get_or_create_rewards(_db(), user_id))
    assert rewards['available_points'] == 250
    assert rewards['lifetime_points'] == 250


def test_summary_points_to_next_tier_counts_down_correctly(user_id):
    _set_lifetime_points(user_id, 4500)  # Wanderer, 500 short of Voyager (5000)
    summary = _run(rewards_service.get_user_rewards_summary(_db(), user_id))
    assert summary['current_tier']['name'] == 'Wanderer'
    assert summary['next_tier']['name'] == 'Voyager'
    assert summary['points_to_next_tier'] == 500


def test_summary_at_max_tier_has_no_next_tier_and_zero_remaining(user_id):
    _set_lifetime_points(user_id, 20000)
    summary = _run(rewards_service.get_user_rewards_summary(_db(), user_id))
    assert summary['current_tier']['name'] == 'Globetrotter'
    assert summary['next_tier'] is None
    assert summary['points_to_next_tier'] == 0


def test_summary_available_discount_usd_matches_points_to_usd_rate(user_id):
    _set_lifetime_points(user_id, 300)
    summary = _run(rewards_service.get_user_rewards_summary(_db(), user_id))
    assert summary['available_discount_usd'] == pytest.approx(300 * rewards_service.POINTS_TO_USD)
