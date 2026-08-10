"""
db_models.py's PromotionDoc validation tests (Step A7) - data-model level,
plus a direct-Mongo round trip confirming native datetimes land as real
BSON Dates, not ISO strings (same convention as every other collection in
db_models.py - see that module's own docstring), and that the unique index
on `code` (services/analytics_service.py's ensure_indexes) is actually
enforced.

Usage-cap enforcement is checked ONLY at this data-model level (a
PromotionDoc can never be constructed already over its own cap) - the
atomic, concurrency-safe "increment redemption_count under a cap filter"
flow that would enforce this against real concurrent redemptions is
explicitly out of scope for this step (no promo-application/checkout logic
exists yet to redeem against - see PromotionDoc's own docstring in
db_models.py).

Pure Pydantic-level tests never touch any Motor client at all, so they
carry none of the cross-loop concerns test_analytics_events.py's own module
docstring documents - only the Mongo round-trip tests at the bottom use a
freshly-constructed AsyncIOMotorClient per call, same pattern as every
other test file's helpers.
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import ValidationError
from pymongo.errors import DuplicateKeyError

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from db_models import PromotionDoc  # noqa: E402
from services import analytics_service  # noqa: E402

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')


def _db():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _run(coro):
    return asyncio.run(coro)


def _delete_many(collection_name, query):
    # Deliberately wrapped in a local async def, not
    # `_run(_db().<collection>.delete_many(query))` inline - the latter
    # constructs the AsyncIOMotorClient AND resolves its io_loop before
    # asyncio.run() has started a loop at all, raising "There is no current
    # event loop in thread 'MainThread'" on this stack (Python 3.14 +
    # Windows + motor) - see test_internal_tickets_api.py's own comment on
    # this exact trap.
    async def _do():
        db = _db()
        await db[collection_name].delete_many(query)
    _run(_do())


def _valid_kwargs(**overrides):
    now = datetime.now(timezone.utc)
    kwargs = {
        "code": "summer25",
        "discount_type": "percent",
        "discount_value": 25,
        "valid_from": now,
        "valid_until": now + timedelta(days=30),
        "usage_cap": 100,
        "redemption_count": 0,
        "created_at": now,
    }
    kwargs.update(overrides)
    return kwargs


# ═══════════════ Pydantic-level validation ═══════════════

def test_valid_promotion_constructs_and_normalizes_code():
    promo = PromotionDoc(**_valid_kwargs())
    assert promo.code == "SUMMER25"  # normalized to uppercase, whitespace-trimmed


def test_rejects_blank_code():
    with pytest.raises(ValidationError):
        PromotionDoc(**_valid_kwargs(code="   "))


def test_rejects_inverted_validity_window():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        PromotionDoc(**_valid_kwargs(valid_from=now, valid_until=now - timedelta(days=1)))


def test_rejects_equal_validity_window_bounds():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        PromotionDoc(**_valid_kwargs(valid_from=now, valid_until=now))


def test_rejects_percent_discount_over_100():
    with pytest.raises(ValidationError):
        PromotionDoc(**_valid_kwargs(discount_type="percent", discount_value=150))


def test_rejects_non_positive_discount_value():
    with pytest.raises(ValidationError):
        PromotionDoc(**_valid_kwargs(discount_value=0))


def test_fixed_discount_over_100_is_allowed():
    """Only "percent" is capped at 100 - a fixed-amount discount (e.g. $150
    off a large booking) has no such ceiling."""
    promo = PromotionDoc(**_valid_kwargs(discount_type="fixed", discount_value=150))
    assert promo.discount_value == 150


def test_rejects_non_positive_usage_cap():
    with pytest.raises(ValidationError):
        PromotionDoc(**_valid_kwargs(usage_cap=0))


def test_usage_cap_enforced_at_the_data_model_level():
    """redemption_count may never exceed usage_cap - enforced here since no
    real redemption path exists yet to enforce it at write time (see this
    file's own module docstring)."""
    with pytest.raises(ValidationError):
        PromotionDoc(**_valid_kwargs(usage_cap=10, redemption_count=11))


def test_redemption_count_equal_to_cap_is_allowed():
    promo = PromotionDoc(**_valid_kwargs(usage_cap=10, redemption_count=10))
    assert promo.redemption_count == 10


def test_usage_cap_none_places_no_ceiling_on_redemption_count():
    promo = PromotionDoc(**_valid_kwargs(usage_cap=None, redemption_count=10_000))
    assert promo.redemption_count == 10_000


# ═══════════════ Mongo round trip ═══════════════

def test_promotion_round_trips_through_mongo_with_native_datetimes():
    code = f"TESTPROMO{uuid.uuid4().hex[:6].upper()}"
    promo = PromotionDoc(**_valid_kwargs(code=code))
    doc = promo.model_dump(mode="python", exclude={"id"})

    async def _do():
        db = _db()
        await db.promotions.insert_one(doc)
        return await db.promotions.find_one({"code": code})

    try:
        raw = _run(_do())
        assert raw is not None
        assert isinstance(raw["valid_from"], datetime)
        assert isinstance(raw["valid_until"], datetime)
        assert isinstance(raw["created_at"], datetime)
        # Re-validate the round-tripped raw doc against the model itself -
        # confirms nothing about the stored shape drifted from what
        # PromotionDoc expects to read back.
        reparsed = PromotionDoc(**raw)
        assert reparsed.code == code
    finally:
        _delete_many("promotions", {"code": code})


def test_promotion_code_unique_index_rejects_duplicate():
    code = f"DUPTEST{uuid.uuid4().hex[:6].upper()}"
    now = datetime.now(timezone.utc)
    doc = {
        "code": code, "discount_type": "percent", "discount_value": 10,
        "valid_from": now, "valid_until": now + timedelta(days=10),
        "usage_cap": None, "redemption_count": 0, "created_at": now,
    }

    async def _do():
        db = _db()
        await analytics_service.ensure_indexes(db)
        await db.promotions.insert_one(dict(doc))
        with pytest.raises(DuplicateKeyError):
            await db.promotions.insert_one(dict(doc))

    try:
        _run(_do())
    finally:
        _delete_many("promotions", {"code": code})
