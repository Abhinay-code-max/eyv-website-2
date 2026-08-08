"""
Regression tests for services/generation_expiry_service.py -
expire_stuck_generations, the sweep that flips trip-plan tiers stuck in
status "generating" (a crash/restart mid-generation left them with no other
way to ever resolve - see that module's docstring) to "failed".

Seeds trips directly into db.trips - same direct-DB-seed idiom
test_rewards_race.py / test_booking_hygiene.py use for their own sweep/
status-transition tests - rather than driving a real Gemini generation,
since only the trip document's shape (plans[].status, created_at) matters
here, not how it got that way. Calls expire_stuck_generations(db) directly
against a freshly-constructed Motor client, the same function the
_booking_expiry_scheduler job in server.py calls on a timer.
"""
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta

import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from services import generation_expiry_service  # noqa: E402

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')


def _db():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _run(coro):
    return asyncio.run(coro)


def _placeholder_plan(plan_type):
    """Same shape server.py's _placeholder_plan writes for a tier still
    generating - itinerary/costs all zeroed, no generation_failed/error
    yet."""
    return {
        "plan_type": plan_type,
        "status": "generating",
        "currency": "INR",
        "currency_symbol": "₹",
        "itinerary": {},
        "cost_breakdown": {"transportation": 0, "accommodation": 0, "food": 0,
                           "activities": 0, "miscellaneous": 0},
        "total_cost": 0,
        "highlights": [],
        "budget_tips": [],
    }


def _ready_plan(plan_type):
    plan = _placeholder_plan(plan_type)
    plan["status"] = "ready"
    plan["total_cost"] = 8000
    return plan


def _seed_trip(trip_id, user_id, created_at, plans):
    async def _do():
        db = _db()
        await db.trips.insert_one({
            "trip_id": trip_id,
            "user_id": user_id,
            "trip_name": "Test Trip",
            "preferences": {"destination": "Goa"},
            "plans": plans,
            "created_at": created_at,
            "updated_at": created_at,
        })
    _run(_do())


def _get_trip(trip_id):
    async def _do():
        db = _db()
        return await db.trips.find_one({"trip_id": trip_id}, {"_id": 0})
    return _run(_do())


def _cleanup(trip_ids):
    async def _do():
        db = _db()
        await db.trips.delete_many({"trip_id": {"$in": list(trip_ids)}})
    _run(_do())


def _sweep():
    return _run(generation_expiry_service.expire_stuck_generations(_db()))


def test_generation_stuck_past_ttl_is_flipped_to_failed():
    """The core failure mode: a tier still "generating" well past
    STUCK_GENERATING_TTL (server crash/restart mid-generation, per the
    module docstring) must be flipped to "failed" with generation_failed
    set, so the frontend's regenerate CTA (which keys off
    plan.generation_failed, not plan.status - see TripResultsPage.jsx) can
    actually surface for it."""
    trip_id = f"test_stuck_gen_{uuid.uuid4().hex[:10]}"
    user_id = f"test_stuck_gen_user_{uuid.uuid4().hex[:10]}"
    stuck_since = datetime.now(timezone.utc) - generation_expiry_service.STUCK_GENERATING_TTL - timedelta(minutes=5)
    try:
        _seed_trip(trip_id, user_id, stuck_since, [
            _ready_plan("Budget"),
            _placeholder_plan("Premium"),
            _placeholder_plan("Luxury"),
        ])

        flipped = _sweep()
        assert flipped >= 1

        trip = _get_trip(trip_id)
        plans_by_type = {p["plan_type"]: p for p in trip["plans"]}

        assert plans_by_type["Premium"]["status"] == "failed"
        assert plans_by_type["Premium"]["generation_failed"] is True
        assert plans_by_type["Premium"]["error"]

        assert plans_by_type["Luxury"]["status"] == "failed"
        assert plans_by_type["Luxury"]["generation_failed"] is True

        # The already-"ready" Budget tier must be left completely untouched
        # by a sweep meant only for stuck "generating" tiers.
        assert plans_by_type["Budget"]["status"] == "ready"
        assert "generation_failed" not in plans_by_type["Budget"]
    finally:
        _cleanup([trip_id])


def test_recent_in_progress_generation_is_left_untouched():
    """Control case: a trip created well within STUCK_GENERATING_TTL is a
    genuinely in-progress generation, not a stuck one - the sweep must not
    touch it, or every real generation would be at risk of being flipped to
    "failed" out from under itself before it ever gets a chance to finish."""
    trip_id = f"test_recent_gen_{uuid.uuid4().hex[:10]}"
    user_id = f"test_recent_gen_user_{uuid.uuid4().hex[:10]}"
    just_started = datetime.now(timezone.utc) - timedelta(minutes=2)
    try:
        _seed_trip(trip_id, user_id, just_started, [
            _placeholder_plan("Budget"),
            _placeholder_plan("Premium"),
            _placeholder_plan("Luxury"),
        ])

        _sweep()

        trip = _get_trip(trip_id)
        for plan in trip["plans"]:
            assert plan["status"] == "generating", (
                f"{plan['plan_type']} was flipped despite being well within "
                f"the TTL - sweep must not touch a genuinely in-progress generation"
            )
            assert "generation_failed" not in plan
    finally:
        _cleanup([trip_id])


def test_sweep_is_idempotent_and_leaves_already_resolved_trips_alone():
    """Safe to call repeatedly / on a timer, same guarantee
    expire_stale_pending_bookings documents: running the sweep twice against
    a trip it already resolved must not error or re-flip anything (there's
    nothing left in "generating" to match), and a trip with no stuck tiers
    at all is never touched."""
    trip_id = f"test_idempotent_gen_{uuid.uuid4().hex[:10]}"
    user_id = f"test_idempotent_gen_user_{uuid.uuid4().hex[:10]}"
    stuck_since = datetime.now(timezone.utc) - generation_expiry_service.STUCK_GENERATING_TTL - timedelta(minutes=5)
    try:
        _seed_trip(trip_id, user_id, stuck_since, [_placeholder_plan("Budget")])

        first_pass = _sweep()
        assert first_pass >= 1
        second_pass = _sweep()
        assert second_pass == 0, "nothing left in \"generating\" - a second run must match zero trips"

        trip = _get_trip(trip_id)
        assert trip["plans"][0]["status"] == "failed"
    finally:
        _cleanup([trip_id])
