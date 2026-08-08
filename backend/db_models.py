"""
Pydantic models for documents AS THEY ARE ACTUALLY STORED in MongoDB - this
is a map of current reality (traced from every insert/update call site in
server.py and services/*.py), not an idealized target schema. Distinct from
the request/response models in server.py (TripPreferences, User, etc.),
which describe API payloads, not storage shapes.

Deliberately loose where the real data is loose:
  - Every field a document doesn't always have (e.g. a user's premium/
    subscription fields before their first checkout) is Optional, not
    given a fake default - "missing" and "present but empty" are different
    facts about real documents and this preserves that distinction.
  - `TripDoc.preferences`/`plans` stay as Dict[str, Any]/List[Dict[str, Any]]
    rather than being re-modeled here - preferences is exactly
    TripPreferences.model_dump() (server.py) stored verbatim, and each
    plans[] entry is one of three deliberately different shapes depending
    on status ("generating" has no anchor_pricing key at all; "ready" is
    GeneratedPlanResponse's shape, also server.py, plus anchor_pricing and
    optional placeholder-pricing flags; "failed" is a zeroed-out shape with
    generation_failed=True) - forcing one strict nested type over all three
    would misrepresent a real, intentional difference as a schema bug.
  - bookings is genuinely two different document shapes under one
    collection (single-item vs. bundle bookings - see BookingDoc below) -
    modeled as a real discriminated union on booking_type, not flattened.

Timestamp convention: every *_at/created_at/updated_at/expires_at field
below is a native `datetime` (BSON Date). Some collections already stored
these correctly - user_sessions.expires_at, oauth_states.created_at,
oauth_tickets.created_at, price_cache/search_cache (all TTL-indexed, so
Mongo's TTL monitor required a real BSON Date), and chat_sessions
(chat_service.py happened to get this right independently). Most of the
rest of the app stored these same kinds of fields as `.isoformat()` strings
instead - migrations/0001_normalize_timestamps_to_datetime.py backfills
existing documents to match; new code should construct the relevant model
below and call `model.model_dump()` (default mode="python", NOT
mode="json") so Motor gets a real `datetime` object to serialize as BSON,
never `.isoformat()` again.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── users ────────────────────────────────────────────────────────────────

class UserDoc(BaseModel):
    """db.users - one per person, created on first login (server.py's
    /auth/session). Premium/subscription fields are bolted on ad-hoc by the
    Stripe webhook handlers (_sync_subscription_from_stripe,
    _process_successful_payment) the first time a checkout succeeds -
    absent on every free-tier user, not just empty."""
    model_config = ConfigDict(extra="ignore")
    user_id: str
    email: str
    name: str
    picture: Optional[str] = None
    created_at: datetime
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
    stripe_subscription_status: Optional[str] = None
    premium_plan: Optional[str] = None
    current_period_end: Optional[datetime] = None
    cancel_at_period_end: Optional[bool] = None
    # Set once, the first time a subscription is ever observed active - not
    # touched again, so a later past_due/active flap doesn't reset it.
    premium_started_at: Optional[datetime] = None


# ── user_sessions / oauth_states / oauth_tickets (already correct) ────────

class UserSessionDoc(BaseModel):
    """db.user_sessions - one per login (multi-session; not wiped on a new
    login elsewhere). expires_at was already a native datetime before this
    task - index_service.py's TTL index on it requires a real BSON Date.
    created_at was NOT already correct despite living in the same document -
    it was a `.isoformat()` string, used in GET /auth/sessions'
    `.sort("created_at", -1)`, so it has the same string-sort fragility as
    the collections below and is included in migration 0001's scope."""
    model_config = ConfigDict(extra="ignore")
    session_id: str
    session_token: str  # sha256(raw token) hex digest, never the raw token
    user_id: str
    expires_at: datetime
    created_at: datetime
    user_agent: Optional[str] = None


class OAuthStateDoc(BaseModel):
    """db.oauth_states - short-lived CSRF state, TTL-expired after 10 min
    (index_service.py). created_at was already a native datetime."""
    model_config = ConfigDict(extra="ignore")
    state: str
    created_at: datetime


class OAuthTicketDoc(BaseModel):
    """db.oauth_tickets - one-time ticket exchanged for a session right
    after the Google OAuth callback, TTL-expired after 5 minutes
    (OAUTH_TICKET_TTL_SECONDS). created_at was already a native datetime."""
    model_config = ConfigDict(extra="ignore")
    ticket: str
    email: str
    name: str
    picture: Optional[str] = None
    created_at: datetime


# ── trips ────────────────────────────────────────────────────────────────

class TripDoc(BaseModel):
    """db.trips - one per generated trip, holding all 3 tiers. See the
    module docstring for why `preferences`/`plans` stay untyped here."""
    model_config = ConfigDict(extra="ignore")
    trip_id: str
    user_id: str
    trip_name: str
    preferences: Dict[str, Any]
    plans: List[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime


# ── bookings (real discriminated union) ────────────────────────────────────

class BookingLineItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: Literal["flight", "hotel"]
    price: float
    details: Dict[str, Any]


class SingleItemBookingDoc(BaseModel):
    """db.bookings variant 1 - create_booking's shape: one flight OR one
    hotel booked standalone (not via "Book this Plan")."""
    model_config = ConfigDict(extra="ignore")
    booking_id: str
    confirmation_code: str
    user_id: str
    trip_id: Optional[str] = None
    booking_type: Literal["flight", "hotel"]
    item_data: Dict[str, Any]
    traveler_details: Dict[str, Any] = Field(default_factory=dict)
    status: str
    payment_status: str
    total_amount: float
    currency: str
    created_at: datetime
    cancelled_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    payment_failed_at: Optional[datetime] = None


class BundleBookingDoc(BaseModel):
    """db.bookings variant 2 - book_trip_plan's shape: "Book this Plan",
    one Stripe charge covering every real bookable item (flight + hotel) in
    a generated tier."""
    model_config = ConfigDict(extra="ignore")
    booking_id: str
    confirmation_code: str
    user_id: str
    trip_id: str
    booking_type: Literal["bundle"]
    plan_type: str
    trip_summary: Dict[str, Any]
    line_items: List[BookingLineItem]
    traveler_details: Dict[str, Any] = Field(default_factory=dict)
    status: str
    payment_status: str
    total_amount: float
    currency: str
    created_at: datetime
    cancelled_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    payment_failed_at: Optional[datetime] = None


BookingDoc = Annotated[
    Union[SingleItemBookingDoc, BundleBookingDoc],
    Field(discriminator="booking_type"),
]


class _BookingDocAdapter(BaseModel):
    """Bare wrapper so callers can do
    `_BookingDocAdapter(booking=raw_doc).booking` to get the discriminated
    union to validate/dispatch on booking_type - Pydantic has no top-level
    `parse_obj`-for-a-bare-Union entry point, only for a field on a model."""
    model_config = ConfigDict(extra="ignore")
    booking: BookingDoc


def parse_booking(doc: Dict[str, Any]) -> Union[SingleItemBookingDoc, BundleBookingDoc]:
    """Validate a raw db.bookings document against whichever variant its
    booking_type selects."""
    return _BookingDocAdapter(booking=doc).booking


# ── payment_transactions ───────────────────────────────────────────────────

class PaymentTransactionDoc(BaseModel):
    """db.payment_transactions - one per Stripe Checkout Session created
    (POST /payments/checkout). payment_type is "subscription" | "booking"
    (a free string in the real data, not enforced as an enum anywhere)."""
    model_config = ConfigDict(extra="ignore")
    session_id: str
    user_id: str
    amount: float
    currency: str
    description: str
    payment_type: str
    metadata: Dict[str, Any]
    payment_status: str
    status: str
    points_used: int = 0
    created_at: datetime
    completed_at: Optional[datetime] = None


# ── wallet_items ────────────────────────────────────────────────────────────

class WalletItemDoc(BaseModel):
    """db.wallet_items - uploaded travel documents (boarding passes etc.),
    soft-deleted via is_deleted rather than a real delete."""
    model_config = ConfigDict(extra="ignore")
    item_id: str
    user_id: str
    file_path: str
    original_filename: str
    content_type: str
    size: int
    category: str
    title: str
    description: Optional[str] = None
    trip_id: Optional[str] = None
    is_deleted: bool = False
    created_at: datetime
    deleted_at: Optional[datetime] = None


# ── rewards ─────────────────────────────────────────────────────────────────

class UserRewardsDoc(BaseModel):
    """db.user_rewards - one per user, upserted (unique index on user_id)."""
    model_config = ConfigDict(extra="ignore")
    user_id: str
    available_points: int
    lifetime_points: int
    created_at: datetime
    updated_at: datetime


class RewardsTransactionDoc(BaseModel):
    """db.rewards_transactions - append-only ledger. base_points/multiplier
    are only present on 'earn' transactions; discount_usd only on 'redeem'."""
    model_config = ConfigDict(extra="ignore")
    transaction_id: str
    user_id: str
    action: str
    points: int
    base_points: Optional[int] = None
    multiplier: Optional[float] = None
    discount_usd: Optional[float] = None
    reference_id: Optional[str] = None
    description: str
    type: Literal["earn", "redeem"]
    created_at: datetime


# ── generation_quota (no timestamp fields - not in scope for migration 0001) ─

class GenerationQuotaDoc(BaseModel):
    """db.generation_quota - one per (user_id, date), atomically
    incremented. `date` is deliberately a "YYYY-MM-DD" string key, not a
    timestamp - out of scope for the datetime-normalization migration."""
    model_config = ConfigDict(extra="ignore")
    user_id: str
    date: str
    count: int


# ── provider_usage ──────────────────────────────────────────────────────────

class ProviderUsageDoc(BaseModel):
    """db.provider_usage - lightweight call-count log for paid providers
    (Gemini/Duffel/SerpApi)."""
    model_config = ConfigDict(extra="ignore")
    provider: str
    user_id: Optional[str] = None
    created_at: datetime
    meta: Dict[str, Any] = Field(default_factory=dict)


# ── generation_logs ──────────────────────────────────────────────────────────

class GenerationLogDoc(BaseModel):
    """db.generation_logs - redacted prompt/response pair per Gemini call
    attempt (services/generation_log_service.py)."""
    model_config = ConfigDict(extra="ignore")
    trip_id: str
    plan_type: str
    attempt: int
    model: str
    status: str
    prompt: str
    response: str
    error: Optional[str] = None
    created_at: datetime


# ── chat_sessions (already correct) ─────────────────────────────────────────

class ChatMessageDoc(BaseModel):
    model_config = ConfigDict(extra="ignore")
    role: Literal["user", "model"]
    content: str
    timestamp: datetime


class ChatSessionDoc(BaseModel):
    """db.chat_sessions - one per (user_id, trip_id); trip_id=None for
    trip-less general chat. Already used native datetimes before this task
    (chat_service.py)."""
    model_config = ConfigDict(extra="ignore")
    user_id: str
    trip_id: Optional[str] = None
    messages: List[ChatMessageDoc]
    updated_at: datetime


# ── price_cache / search_cache (already correct, TTL-indexed) ──────────────

class PriceCacheDoc(BaseModel):
    """db.price_cache - server-authoritative price per item_id, TTL-expired.
    Already used native datetimes before this task (price_cache_service.py)."""
    model_config = ConfigDict(extra="ignore")
    item_id: str
    item_type: str
    provider: str
    provider_ref: Dict[str, Any]
    price: float
    currency: str
    created_at: datetime
    expires_at: datetime


class SearchCacheDoc(BaseModel):
    """db.search_cache - raw flight/hotel search-result cache, TTL-expired.
    Already used native datetimes before this task (price_cache_service.py)."""
    model_config = ConfigDict(extra="ignore")
    cache_key: str
    item_type: str
    results: List[Dict[str, Any]]
    created_at: datetime
    expires_at: datetime


# ── tickets (new collection - nothing to migrate) ───────────────────────────

# Exposed as module-level constants (not just inlined in TicketDoc.status/
# approval below) so internal_tickets_api.py's request-validation models can
# share the exact same allowed values via Literal[TICKET_STATUSES] /
# Literal[TICKET_APPROVAL_STATES] - one source of truth for "what's a valid
# status/approval value", not two lists that have to be kept in sync by hand.
TICKET_STATUSES = (
    "reported", "triaged", "awaiting_approval", "approved",
    "implemented", "closed", "rejected", "backlog",
)
TICKET_APPROVAL_STATES = ("pending", "approved", "rejected", "deferred")


class TicketDoc(BaseModel):
    """db.tickets - a bug/feature ticket, progressed by an agent-assisted
    triage/approval workflow: reported -> triaged -> awaiting_approval ->
    approved -> implemented -> closed, rejected at any gate, or parked in
    backlog outside that main flow. Brand-new collection as of this model -
    there is no pre-existing tickets-shaped data anywhere in this app to
    backfill, so unlike migrations/0001_normalize_timestamps_to_datetime.py's
    16 collections, every *_at field here is a native datetime from its
    very first write, with no migration step needed.

    Unlike every other model in this file, tickets has no app-generated
    string ID field of its own (no "ticket_id") - Mongo's own `_id` is
    genuinely this document's real identity here, not just an implementation
    detail every other collection's queries strip via {"_id": 0}. Modeled
    below as `id` (Python attribute name, since Pydantic v2 treats a
    leading underscore as a private, non-field attribute) aliased to the
    wire name "_id", with a before-validator that stringifies a raw
    bson.ObjectId - every other *_id-shaped field in this file is already a
    plain str (user_id, trip_id, booking_id, session_id, ...), never a raw
    ObjectId, so this keeps that same str-everywhere convention for the one
    field that would otherwise be the sole exception.

    reporter_user_ids/notified_user_ids reference db.users the same way
    every other collection here does (UserDoc.user_id: str) - never
    ObjectId. linked_chat_sessions references db.chat_sessions, which (see
    ChatSessionDoc above) has no app-level ID field of its own either - it's
    identified only by the compound (user_id, trip_id) key plus its own
    implicit Mongo _id, so this stores that same stringified _id, for the
    same reason and via the same conversion as this document's own `id`
    field above."""
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    id: Optional[str] = Field(default=None, alias="_id")
    title: str
    description: str
    kind: Literal["bug", "feature"]
    status: Literal[TICKET_STATUSES]
    reporter_user_ids: List[str] = Field(default_factory=list)
    linked_chat_sessions: List[str] = Field(default_factory=list)
    first_reported_at: datetime
    updated_at: datetime
    agent_plan: Optional[str] = None
    agent_diff_summary: Optional[str] = None
    approval: Literal[TICKET_APPROVAL_STATES]
    approval_note: Optional[str] = None
    implementation_commit: Optional[str] = None
    notified_user_ids: List[str] = Field(default_factory=list)

    @field_validator("id", mode="before")
    @classmethod
    def _stringify_object_id(cls, v: Any) -> Optional[str]:
        return str(v) if v is not None else v


class TicketAgentAuditLogDoc(BaseModel):
    """db.ticket_agent_audit_log - append-only audit trail for every call to
    /api/internal/tickets/* (see internal_tickets_api.py's
    _AuditedTicketRoute) - exactly one record per HTTP request through that
    router, success or failure (auth rejection, validation error, not-found,
    unexpected exception, or a real success), written from the route-class
    wrapper rather than per-route so a new route added to that router can't
    forget to log itself. Like TicketDoc, brand new as of this model, so
    every field is a native datetime from its first write - no migration.

    No update or delete path exists anywhere in this app for this
    collection, and none should ever be added - append-only means
    append-only; a mutable audit log defeats its own purpose."""
    model_config = ConfigDict(extra="ignore")
    timestamp: datetime
    route: str
    method: str
    ticket_id: Optional[str] = None
    status_code: int
    summary: Dict[str, Any] = Field(default_factory=dict)
