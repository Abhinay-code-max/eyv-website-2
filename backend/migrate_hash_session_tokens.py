"""
One-off migration: hash plaintext session tokens in place.

Background: user_sessions.session_token used to store the raw session token
(a uuid4().hex value handed to the browser as the session_token cookie).
Anyone with read access to the sessions collection could copy that value and
impersonate the session directly. server.py now stores/looks up
sha256(token) instead (see _hash_session_token in server.py) - this script
converts any documents still holding the old plaintext value, so a deploy of
that change doesn't invalidate every currently logged-in user.

Idempotent and safe to re-run: a token is only rewritten if it still looks
like a raw uuid4().hex value (32 hex chars) rather than a sha256 hex digest
(64 hex chars), so running this twice - or against a DB that's a mix of pre-
and post-migration sessions - is a no-op the second time. Existing sessions
also predate the per-session session_id field added alongside this change
(used by the new GET/DELETE /api/auth/sessions endpoints); any document
missing one gets a fresh uuid4().hex backfilled here as well.

Usage:
    cd backend
    python migrate_hash_session_tokens.py [--dry-run]

Reads MONGO_URL / DB_NAME from the environment the same way server.py does
(falls back to backend/.env via python-dotenv if present).
"""
import argparse
import hashlib
import os
import uuid

from dotenv import load_dotenv
from pymongo import MongoClient, UpdateOne

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

RAW_TOKEN_LENGTH = 32  # uuid4().hex
HASHED_TOKEN_LENGTH = 64  # sha256(...).hexdigest()


def _looks_already_hashed(token: str) -> bool:
    return len(token) == HASHED_TOKEN_LENGTH


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what would change without writing anything.",
    )
    args = parser.parse_args()

    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    db = MongoClient(mongo_url)[db_name]

    to_hash = 0
    already_hashed = 0
    backfilled_session_id = 0
    ops = []

    for doc in db.user_sessions.find({}):
        token = doc.get("session_token", "")
        update = {}

        if token and not _looks_already_hashed(token):
            update["session_token"] = hashlib.sha256(token.encode("utf-8")).hexdigest()
            to_hash += 1
        else:
            already_hashed += 1

        if not doc.get("session_id"):
            update["session_id"] = uuid.uuid4().hex
            backfilled_session_id += 1

        if update:
            ops.append(UpdateOne({"_id": doc["_id"]}, {"$set": update}))

    print(f"Sessions needing token hash: {to_hash}")
    print(f"Sessions already hashed:     {already_hashed}")
    print(f"Sessions needing session_id backfill: {backfilled_session_id}")

    if args.dry_run:
        print("--dry-run set: no changes written.")
        return

    if ops:
        result = db.user_sessions.bulk_write(ops)
        print(f"Updated {result.modified_count} document(s).")
    else:
        print("Nothing to update.")


if __name__ == "__main__":
    main()
