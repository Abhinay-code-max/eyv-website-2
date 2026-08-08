"""
Sweeps trip-plan tiers stuck in status: "generating" - a safety net for the
case where the background generation task (_generate_and_save_tier in
server.py) never finishes: the process crashes, times out, or a deploy
restarts the server mid-generation. asyncio tasks are not persisted or
resumed across a restart (see _spawn_background_task in server.py), so a
tier's placeholder status: "generating" written at trip-creation time
(_placeholder_plan) is otherwise the final word on that tier - nothing else
ever revisits it. Mirrors services/booking_expiry_service.py's own pattern
for the same class of problem: a status the app promises will eventually
transition, with no timeout of its own to guarantee that.
"""
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# generate_single_plan (server.py) retries up to 3 times with only 1-2s of
# backoff between attempts, so a genuinely in-progress tier resolves in well
# under a minute - 15 minutes is a generous margin above that, chosen so a
# tier that's actually still working is never mistaken for stuck, while a
# crashed/restarted deploy doesn't leave the UI showing "Generating..."
# indefinitely.
STUCK_GENERATING_TTL = timedelta(minutes=15)


async def expire_stuck_generations(db) -> int:
    """Flip trip-plan tiers stuck in status: "generating" past
    STUCK_GENERATING_TTL to "failed". Filtered on plans.status="generating"
    AND the trip's own created_at - set once at trip-creation time
    (generate_trip_plans) and never rewritten by any later per-tier write, so
    it's a reliable "generation started at" timestamp for every tier on the
    trip even after other tiers finish and bump updated_at. This can never
    clobber a tier a genuinely-finished generation already resolved -
    _generate_and_save_tier's and regenerate_trip_plan's writes replace the
    whole plan object unconditionally and always win, regardless of whether
    they land before or after this sweep. Safe to call repeatedly / on a
    timer: each run only matches plans still "generating" at the moment of
    the write, so a tier already resolved (ready or failed) by an earlier
    run, the background task itself, or a regenerate call is simply not
    touched again.

    Sets generation_failed: True and an error message on each matched tier,
    matching the shape generate_single_plan itself writes on a genuine
    failure (see server.py, and db_models.py's TripDoc docstring for the
    three plans[] shapes). The frontend's regenerate CTA
    (TripResultsPage.jsx) keys off plan.generation_failed, not plan.status -
    setting status alone would flip the tier out of "generating" but leave
    it with no visible way for the user to retry it.

    Returns the number of trips flipped (each may have had more than one
    stuck tier resolved in the same update), for logging/observability.

    DEPLOY ORDER NOTE: same as expire_stale_pending_bookings - this compares
    trips.created_at against a native datetime, which is only correct once
    migrations/0001_normalize_timestamps_to_datetime.py has actually run
    against this database. See that sweep's own docstring for what breaks
    (every legacy trip incorrectly matched) if this ships before that
    migration.
    """
    cutoff = datetime.now(timezone.utc) - STUCK_GENERATING_TTL
    result = await db.trips.update_many(
        {"plans.status": "generating", "created_at": {"$lt": cutoff}},
        {"$set": {
            "plans.$[elem].status": "failed",
            "plans.$[elem].generation_failed": True,
            "plans.$[elem].error": "Generation was interrupted, please try again.",
            "updated_at": datetime.now(timezone.utc),
        }},
        array_filters=[{"elem.status": "generating"}],
    )
    if result.modified_count:
        logger.info(
            f"expire_stuck_generations: flipped {result.modified_count} trip(s) with "
            f"tier(s) stuck in generating older than {STUCK_GENERATING_TTL} to failed"
        )
    return result.modified_count
