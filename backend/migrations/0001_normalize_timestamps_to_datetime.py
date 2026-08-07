"""
Migration 0001: normalize ISO-string timestamps to native datetime (BSON Date).

Background: most of this app's own timestamp writes used
`datetime.now(timezone.utc).isoformat()` (a string) instead of a native
datetime. server.py and services/*.py have been changed to write native
datetimes for every field below going forward (see backend/db_models.py for
the documented target shape of each collection) - this migration backfills
existing documents to match. This is not just a style cleanup - two real
bugs motivated it:

  1. index_service.py compound-indexes (user_id, created_at) on trips/
     bookings/wallet_items/payment_transactions/rewards_transactions, and
     every list endpoint sorts on it. String sort only happens to match
     chronological order today because Python's isoformat() output is
     lexicographically sortable in the exact format this app always wrote
     it in - one document in a different format (a hand-inserted row, a
     future code path, old "Emergent platform" leftover data) would
     silently produce wrong sort order with no error.
  2. services/booking_expiry_service.py runs a live `$lt` range query
     against booking.created_at to auto-expire stale pending bookings -
     same fragility, but with a real state-mutation side effect instead of
     just wrong display order.

Fields migrated, by collection:
  users:                 created_at, premium_started_at, current_period_end
  user_sessions:          created_at  (NOT expires_at - already native;
                           the TTL index in index_service.py required it)
  trips:                  created_at, updated_at
  bookings:                created_at, cancelled_at, paid_at, payment_failed_at
  wallet_items:            created_at, deleted_at
  payment_transactions:    created_at, completed_at
  user_rewards:            created_at, updated_at
  rewards_transactions:    created_at
  generation_logs:         created_at
  provider_usage:          created_at

NOT touched (already a native datetime before this task, or not a
timestamp at all):
  user_sessions.expires_at, oauth_states.created_at, oauth_tickets.created_at,
  chat_sessions.* (updated_at, messages[].timestamp), price_cache.*,
  search_cache.*, generation_quota.date (a "YYYY-MM-DD" string key by
  design, not a timestamp - out of scope).

Idempotent and safe to re-run: a field is only rewritten if it's currently
a str - a document whose field is already a native datetime (including one
this script already converted on an earlier run) is left untouched, so
re-running this against a database that's a mix of pre- and post-migration
documents (e.g. new writes landing after the code deploys but before this
script runs) is a no-op for anything already correct.

A field that exists but isn't a str, datetime, or None (a value this
migration's authors never observed in practice) is reported as a parse
failure and left untouched rather than guessed at, and the run exits
non-zero so it can't be mistaken for a clean pass.

DEPLOY ORDER: run this BEFORE deploying the server.py/services code that
writes native datetimes going forward, not after - see
services/booking_expiry_service.py's expire_stale_pending_bookings
docstring for exactly what breaks (bookings incorrectly auto-expired) if
the code ships to a still-unmigrated database.

Usage:
    cd backend
    python migrations/0001_normalize_timestamps_to_datetime.py --dry-run
    python migrations/0001_normalize_timestamps_to_datetime.py

Reads MONGO_URL / DB_NAME from the environment the same way server.py does
(falls back to backend/.env via python-dotenv if present).
"""
import argparse
import os
import sys
from datetime import datetime
from urllib.parse import urlparse

from dotenv import load_dotenv
from pymongo import MongoClient, UpdateOne


def _redact_target(mongo_url: str, db_name: str) -> str:
    """Format a connection target for logging without ever including credentials."""
    parsed = urlparse(mongo_url)
    return f"Target: {parsed.scheme}://{parsed.hostname} / db={db_name}"

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

# collection -> [timestamp field names to normalize]
FIELDS_BY_COLLECTION = {
    "users": ["created_at", "premium_started_at", "current_period_end"],
    "user_sessions": ["created_at"],
    "trips": ["created_at", "updated_at"],
    "bookings": ["created_at", "cancelled_at", "paid_at", "payment_failed_at"],
    "wallet_items": ["created_at", "deleted_at"],
    "payment_transactions": ["created_at", "completed_at"],
    "user_rewards": ["created_at", "updated_at"],
    "rewards_transactions": ["created_at"],
    "generation_logs": ["created_at"],
    "provider_usage": ["created_at"],
}


def _migrate_collection(db, collection_name: str, fields: list, dry_run: bool) -> dict:
    docs_needing_conversion = 0
    docs_with_nothing_to_convert = 0
    parse_failures = []
    ops = []

    for doc in db[collection_name].find({}):
        update = {}
        for field in fields:
            if field not in doc:
                continue  # genuinely absent on this doc (e.g. premium_started_at pre-checkout) - nothing to convert
            value = doc[field]
            if value is None or isinstance(value, datetime):
                continue  # already correct (or explicitly null), nothing to do
            if isinstance(value, str):
                try:
                    update[field] = datetime.fromisoformat(value)
                except ValueError as e:
                    parse_failures.append((doc.get("_id"), field, repr(value), f"ValueError: {e}"))
                continue
            parse_failures.append((doc.get("_id"), field, repr(value), f"unexpected type: {type(value).__name__}"))

        if update:
            docs_needing_conversion += 1
            ops.append(UpdateOne({"_id": doc["_id"]}, {"$set": update}))
        else:
            docs_with_nothing_to_convert += 1

    result = {
        "collection": collection_name,
        "docs_needing_conversion": docs_needing_conversion,
        "docs_with_nothing_to_convert": docs_with_nothing_to_convert,
        "parse_failures": parse_failures,
        "modified_count": 0,
    }

    if dry_run or not ops:
        return result

    write_result = db[collection_name].bulk_write(ops)
    result["modified_count"] = write_result.modified_count
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Report what would change without writing anything.")
    args = parser.parse_args()

    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    db = MongoClient(mongo_url)[db_name]

    print(_redact_target(mongo_url, db_name))
    print(f"Mode: {'DRY RUN (no writes)' if args.dry_run else 'LIVE (will write)'}\n")

    total_needing_conversion = 0
    total_modified = 0
    any_failures = False

    for collection_name, fields in FIELDS_BY_COLLECTION.items():
        result = _migrate_collection(db, collection_name, fields, args.dry_run)
        total_needing_conversion += result["docs_needing_conversion"]
        total_modified += result["modified_count"]

        print(f"{collection_name} (fields: {', '.join(fields)}):")
        print(f"  documents needing conversion: {result['docs_needing_conversion']}")
        print(f"  documents with nothing to convert: {result['docs_with_nothing_to_convert']}")
        if not args.dry_run:
            print(f"  documents modified: {result['modified_count']}")
        if result["parse_failures"]:
            any_failures = True
            print(f"  PARSE FAILURES ({len(result['parse_failures'])}) - left untouched, needs manual review:")
            for doc_id, field, value, error in result["parse_failures"][:10]:
                print(f"    _id={doc_id} field={field} value={value}: {error}")
            if len(result["parse_failures"]) > 10:
                print(f"    ... and {len(result['parse_failures']) - 10} more")
        print()

    print("=" * 60)
    print(f"Total documents needing conversion: {total_needing_conversion}")
    if args.dry_run:
        print("--dry-run set: no changes written.")
    else:
        print(f"Total documents modified: {total_modified}")
    if any_failures:
        print("Some fields failed to parse and were left as-is - review before re-running.")
        sys.exit(1)


if __name__ == "__main__":
    main()
