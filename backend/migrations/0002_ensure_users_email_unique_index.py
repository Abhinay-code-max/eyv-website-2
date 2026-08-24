"""
Migration 0002: Ensure db.users has a unique index on email.

Deduplicates any pre-existing legacy duplicate user documents (if any exist)
by retaining the earliest-created user_id record per email and removing later
duplicates, then creates a unique index on db.users.email.

Idempotent and safe to run multiple times.
"""
import asyncio
import logging
import os
import sys
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import DuplicateKeyError

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


async def run_migration(db=None):
    if db is None:
        client = AsyncIOMotorClient(MONGO_URL)
        db = client[DB_NAME]

    logger.info(f"Running migration 0002 on database: {db.name}")

    # 1. Find all emails with multiple user records
    pipeline = [
        {"$match": {"email": {"$exists": True, "$ne": None}}},
        {"$group": {"_id": "$email", "count": {"$sum": 1}, "docs": {"$push": {"_id": "$_id", "user_id": "$user_id", "created_at": "$created_at"}}}},
        {"$match": {"count": {"$gt": 1}}}
    ]

    duplicates = await db.users.aggregate(pipeline).to_list(1000)
    if duplicates:
        logger.warning(f"Found {len(duplicates)} emails with duplicate user documents. Deduplicating...")
        for entry in duplicates:
            email = entry["_id"]
            docs = entry["docs"]
            # Sort by created_at ascending (fallback to _id) so the earliest user record is kept
            docs.sort(key=lambda d: str(d.get("created_at") or d.get("_id")))
            primary = docs[0]
            redundant_ids = [d["_id"] for d in docs[1:]]
            logger.info(f"Keeping primary user_id {primary.get('user_id')} for {email}, deleting {len(redundant_ids)} duplicate docs")
            await db.users.delete_many({"_id": {"$in": redundant_ids}})
    else:
        logger.info("No duplicate user emails found in db.users.")

    # 2. Ensure unique index on email
    logger.info("Creating unique index on db.users.email...")
    await db.users.create_index("email", unique=True)
    logger.info("Unique index on db.users.email successfully ensured.")


if __name__ == "__main__":
    asyncio.run(run_migration())
