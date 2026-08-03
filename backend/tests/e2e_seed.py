"""
CLI helper the Playwright smoke suite (frontend/e2e/) shells out to before
tests run. Playwright is Node/JS and has no direct Mongo access of its own
in this repo (no mongodb npm dependency, and adding one just for this would
be new surface for one script) - this reuses the exact same seed_session/
delete_session helpers conftest.py's Python test suite already relies on,
via a subprocess, rather than teaching the frontend a second way to write
auth state into Mongo. No new backend HTTP endpoint is added for this - a
"seed a session" route would be a real backdoor if it ever shipped by
accident; a local/CI-only script that talks to Mongo directly never ships
at all.

Usage:
  python e2e_seed.py seed-session --user-id U --token T
  python e2e_seed.py seed-trip --trip-id ID --user-id U --json '<trip json>'
  python e2e_seed.py cleanup --user-id U --token T [--trip-id ID]

Each subcommand prints "OK" on success (exit 0) or a traceback (exit 1) -
Playwright's global setup treats any non-zero exit as a hard failure of the
whole run, same as any other CI precondition.
"""
import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from conftest import seed_session, delete_session  # noqa: E402

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')


def _db():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _run(coro):
    return asyncio.run(coro)


def cmd_seed_session(args):
    seed_session(args.user_id, args.token, premium=args.premium)


def cmd_seed_trip(args):
    trip = json.loads(args.json)

    async def _do():
        db = _db()
        now = datetime.now(timezone.utc).isoformat()
        await db.trips.update_one(
            {"trip_id": args.trip_id},
            {"$set": {**trip, "trip_id": args.trip_id, "user_id": args.user_id,
                       "created_at": now, "updated_at": now}},
            upsert=True,
        )
    _run(_do())


def cmd_cleanup(args):
    delete_session(args.user_id, args.token)

    async def _do():
        db = _db()
        await db.users.delete_many({"user_id": args.user_id})
        if args.trip_id:
            await db.trips.delete_many({"trip_id": args.trip_id})
            await db.bookings.delete_many({"trip_id": args.trip_id})
    _run(_do())


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    p_session = sub.add_parser("seed-session")
    p_session.add_argument("--user-id", required=True)
    p_session.add_argument("--token", required=True)
    p_session.add_argument("--premium", action="store_true")
    p_session.set_defaults(func=cmd_seed_session)

    p_trip = sub.add_parser("seed-trip")
    p_trip.add_argument("--trip-id", required=True)
    p_trip.add_argument("--user-id", required=True)
    p_trip.add_argument("--json", required=True, help="JSON object merged into the trip document")
    p_trip.set_defaults(func=cmd_seed_trip)

    p_cleanup = sub.add_parser("cleanup")
    p_cleanup.add_argument("--user-id", required=True)
    p_cleanup.add_argument("--token", required=True)
    p_cleanup.add_argument("--trip-id", default=None)
    p_cleanup.set_defaults(func=cmd_cleanup)

    args = parser.parse_args()
    args.func(args)
    print("OK")


if __name__ == "__main__":
    main()
