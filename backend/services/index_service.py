"""
Index setup for collections that see every-request or growing-without-bound
traffic: session/auth lookups (every authenticated request), oauth CSRF-state
and login-ticket docs (currently never expire on their own), and the
per-user collections (trips/bookings/wallet_items/rewards/payment history)
that get scanned by user_id constantly.

create_index() is idempotent - safe to call on every startup, no separate
migration step.
"""


async def ensure_indexes(db) -> None:
    # Auth - looked up on every authenticated request
    await db.user_sessions.create_index("session_token", unique=True)
    # expires_at is a native datetime (see server.py session creation) -
    # expireAfterSeconds=0 means "expire at the timestamp stored in the
    # field itself", i.e. Mongo's TTL monitor does the same cleanup the
    # request-time expiry check in get_current_user() already does, just
    # on its own ~60s cycle. That in-code check stays as the actual
    # enforcement; this is only garbage collection.
    await db.user_sessions.create_index("expires_at", expireAfterSeconds=0)

    await db.users.create_index("email", unique=True)

    # OAuth CSRF state / login ticket docs - single-use and short-lived by
    # design, but nothing previously deleted them if the flow was abandoned
    # mid-way (state minted but callback never hit, or ticket minted but
    # /auth/session never called). TTL on created_at closes that off.
    await db.oauth_states.create_index("created_at", expireAfterSeconds=600)  # 10 min CSRF window
    await db.oauth_tickets.create_index("created_at", expireAfterSeconds=300)  # matches OAUTH_TICKET_TTL_SECONDS in server.py

    # Per-user collections - queried by user_id (and usually sorted by
    # created_at) on essentially every page load. The compound index also
    # serves plain {user_id: ...} queries via its user_id prefix.
    for collection_name in ("trips", "bookings", "wallet_items", "payment_transactions", "rewards_transactions"):
        await db[collection_name].create_index([("user_id", 1), ("created_at", -1)])

    # One rewards doc per user, upserted by user_id (get_or_create_rewards /
    # earn_points / redeem_points in rewards_service.py) - unique index
    # matches that invariant and protects it under concurrent upserts.
    await db.user_rewards.create_index("user_id", unique=True)

    # Direct-lookup fields used outside the user_id+created_at pattern above.
    await db.trips.create_index("trip_id")
    await db.bookings.create_index("booking_id")
    await db.bookings.create_index("session_id")
    await db.payment_transactions.create_index("session_id")

    # Tickets (db_models.py's TicketDoc) - each queried independently, not as
    # a compound pattern: status/kind for dashboard filters ("what needs
    # triage", "bugs vs features"), updated_at descending for "most
    # recently active first" sorts, and reporter_user_ids (a multikey index,
    # since it's an array field) for "tickets this user reported".
    await db.tickets.create_index("status")
    await db.tickets.create_index("kind")
    await db.tickets.create_index([("updated_at", -1)])
    await db.tickets.create_index("reporter_user_ids")
