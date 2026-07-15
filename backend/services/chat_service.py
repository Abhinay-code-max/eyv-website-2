"""
Persistent chat history for the AI travel assistant.

One document per (user_id, trip_id) in db.chat_sessions. General chat
(no trip context) uses trip_id = None, not "" - keeps "no trip" and
"empty string trip" unambiguous under the unique index.
"""
from datetime import datetime, timezone
from typing import Optional


async def ensure_indexes(db) -> None:
    await db.chat_sessions.create_index([("user_id", 1), ("trip_id", 1)], unique=True)


async def get_recent_messages(db, user_id: str, trip_id: Optional[str], limit: int = 20) -> list:
    """Last `limit` messages for (user_id, trip_id), oldest first. Empty list if no session yet."""
    session = await db.chat_sessions.find_one(
        {"user_id": user_id, "trip_id": trip_id},
        {"_id": 0, "messages": {"$slice": -limit}},
    )
    return session["messages"] if session else []


async def get_all_messages(db, user_id: str, trip_id: Optional[str]) -> list:
    """Full stored history (up to the 50-message cap), oldest first."""
    session = await db.chat_sessions.find_one(
        {"user_id": user_id, "trip_id": trip_id},
        {"_id": 0, "messages": 1},
    )
    return session["messages"] if session else []


async def append_exchange(
    db, user_id: str, trip_id: Optional[str], user_message: str, model_message: str, max_stored: int = 50
) -> None:
    """Append the user message and model reply, capping stored history at
    `max_stored` via $push/$each/$slice so we never load the full history
    into Python just to trim it."""
    now = datetime.now(timezone.utc)
    await db.chat_sessions.update_one(
        {"user_id": user_id, "trip_id": trip_id},
        {
            "$push": {
                "messages": {
                    "$each": [
                        {"role": "user", "content": user_message, "timestamp": now},
                        {"role": "model", "content": model_message, "timestamp": now},
                    ],
                    "$slice": -max_stored,
                }
            },
            "$set": {"updated_at": now},
        },
        upsert=True,
    )
