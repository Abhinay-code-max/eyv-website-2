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

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


# ── notifications ────────────────────────────────────────────────────────

# The only three TicketDoc.status values a ticket transition notifies
# reporters about (services/notification_service.py, Step 4.3) - a subset
# of TICKET_STATUSES, exposed the same way (module constant, not inlined)
# so NotificationDoc.status and that service's own signature share one
# source of truth for "which transitions are notifiable."
NOTIFIABLE_TICKET_STATUSES = ("implemented", "rejected", "backlog")


class NotificationDoc(BaseModel):
    """db.notifications - one in-app notification per (ticket, reporter)
    actually delivered by notification_service.notify_ticket_status_change.
    Brand-new collection as of this model - every *_at field is a native
    datetime from its first write, no migration needed (same situation as
    TicketDoc)."""
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    id: Optional[str] = Field(default=None, alias="_id")
    user_id: str
    ticket_id: str
    status: Literal[NOTIFIABLE_TICKET_STATUSES]
    title: str
    body: str
    read: bool = False
    created_at: datetime

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


# ── analytics_events (Step A7 - standalone, no dependency on the ticket/
# support-agent system above) ───────────────────────────────────────────

# Deliberately generic and open-ended - a new event_type is just a new
# string written into this same (event_type, user_id, timestamp, metadata)
# shape, never a new collection/model, so instrumenting a new funnel step
# later needs no schema migration. Four tracked as of Step A7, each tied to
# a specific server.py call site (see that file's own comments at each):
#   - plan_generated: one tier of a trip finished generating with
#     status "ready" (_generate_and_save_tier / regenerate_trip_plan).
#   - plan_to_booking: a booking was created referencing a trip_id - a
#     generated plan converting into a booking (create_booking when
#     req.trip_id is set, and book_trip_plan, which always has one).
#   - booking_completed: a booking's payment actually succeeded
#     (_process_successful_payment, payment_type == "booking").
#   - booking_abandoned: the one explicit abandonment signal this app
#     already has - a pending booking's Stripe Checkout session expired
#     unpaid (_process_expired_payment, payment_type == "booking"), rather
#     than a user ever clicking anything like "abandon". Used as the
#     drop-off signal for the plan_to_booking -> booking_completed leg of
#     the funnel in internal_analytics_api.py; the plan_generated ->
#     plan_to_booking leg has no equivalent explicit signal, so that leg's
#     drop-off is instead a time-window definition (see that module).
ANALYTICS_EVENT_TYPES = (
    "plan_generated", "plan_to_booking", "booking_completed", "booking_abandoned",
)


class AnalyticsEventDoc(BaseModel):
    """db.analytics_events - generic append-only event log, deliberately
    NOT a bespoke collection/model per event type (contrast db.bookings'
    real discriminated union above, which models two GENUINELY different
    storage shapes - these events all share one shape; only `metadata`'s
    contents vary by event_type). Brand-new collection, so every field is a
    native datetime from its first write - no migration needed, same
    situation as TicketDoc.

    Like TicketDoc/NotificationDoc, Mongo's own `_id` is this document's
    real identity (no app-generated event_id) - same id/_id alias +
    stringify-ObjectId pattern.

    user_id is Optional, unlike almost every other *_user_id field in this
    file - every event_type tracked as of Step A7 always has one (every
    call site requires an authenticated user), but the schema stays generic
    enough for a future event_type that legitimately has none (e.g. an
    anonymous landing-page view) without another migration.

    metadata is intentionally Dict[str, Any] rather than a typed field set
    per event_type - e.g. plan_generated carries trip_id/plan_type/
    plan_index; booking_completed carries booking_id/trip_id/amount/
    currency - the same kind of deliberately-untyped, varies-by-variant
    field as TripDoc.preferences/plans (see this module's own docstring)."""
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    id: Optional[str] = Field(default=None, alias="_id")
    event_type: Literal[ANALYTICS_EVENT_TYPES]
    user_id: Optional[str] = None
    timestamp: datetime
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", mode="before")
    @classmethod
    def _stringify_object_id(cls, v: Any) -> Optional[str]:
        return str(v) if v is not None else v


# ── promotions (Step A7 - data-model only, see module docstring) ───────────

PROMOTION_DISCOUNT_TYPES = ("percent", "fixed")


class PromotionDoc(BaseModel):
    """db.promotions - a discount code and its validity/usage constraints.
    Data-model only as of Step A7: nothing in checkout/pricing reads or
    applies this collection yet, and internal_analytics_api.py's read
    surface built alongside this is read-only, deliberately - see that
    module's own docstring for why (the eventual analytics agent gets no
    promotions write access until it has a long track record of trustworthy
    output). Brand-new collection, so every field is a native datetime from
    its first write, same as TicketDoc/AnalyticsEventDoc above.

    discount_type/discount_value replace a single ambiguous "discount"
    field - a bare number can't say whether it means "20% off" or "$20
    off", and this collection existing correctly (not just existing) is the
    whole point of this step, per the roadmap's own framing.

    redemption_count is a plain counter, not computed on the fly from a
    redemptions ledger - no redemption path exists yet to write one; the
    later work that actually applies a promo at checkout is what would
    start incrementing it (atomically, under a usage_cap filter - the same
    find_one_and_update-under-a-filter shape quota_service.py already uses
    for generation_quota - so it can enforce the cap under concurrent
    redemptions). That increment path isn't built here, since there's
    nothing yet to enforce it against; what IS enforced here, at the
    data-model level, is that a document can never be constructed already
    over its own cap or with an inverted validity window - see the
    validators below."""
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    id: Optional[str] = Field(default=None, alias="_id")
    code: str
    discount_type: Literal[PROMOTION_DISCOUNT_TYPES]
    discount_value: float
    valid_from: datetime
    valid_until: datetime
    usage_cap: Optional[int] = None
    redemption_count: int = 0
    created_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def _stringify_object_id(cls, v: Any) -> Optional[str]:
        return str(v) if v is not None else v

    @field_validator("code")
    @classmethod
    def _normalize_code(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("code must not be blank")
        return v.strip().upper()

    @field_validator("discount_value")
    @classmethod
    def _positive_discount(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("discount_value must be positive")
        return v

    @field_validator("usage_cap")
    @classmethod
    def _positive_cap(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v <= 0:
            raise ValueError("usage_cap must be positive when set")
        return v

    @model_validator(mode="after")
    def _validate_window_and_cap(self) -> "PromotionDoc":
        if self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be after valid_from")
        if self.discount_type == "percent" and not (0 < self.discount_value <= 100):
            raise ValueError("percent discount_value must be between 0 and 100")
        if self.usage_cap is not None and self.redemption_count > self.usage_cap:
            raise ValueError("redemption_count must not exceed usage_cap")
        return self


# ── Marketing & Bob Agent Models (Task A.4) ─────────────────────────────────

MARKETING_CHANNELS = ("buffer", "instagram", "whatsapp", "promo_code", "multi_channel")
MARKETING_CAMPAIGN_STATUSES = ("draft", "pending_approval", "approved", "published", "failed", "cancelled")


class MarketingCampaignDoc(BaseModel):
    """db.marketing_campaigns - records of marketing campaigns generated or
    executed by Bob (marketing sub-agent)."""
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    id: Optional[str] = Field(default=None, alias="_id")
    title: str
    channel: Literal[MARKETING_CHANNELS]
    status: Literal[MARKETING_CAMPAIGN_STATUSES] = "draft"
    content: Dict[str, Any] = Field(default_factory=dict)
    target_audience: Optional[str] = None
    spend_budget: float = 0.0
    discount_config: Optional[Dict[str, Any]] = None
    external_post_id: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    scheduled_for: Optional[datetime] = None
    published_at: Optional[datetime] = None

    @field_validator("id", mode="before")
    @classmethod
    def _stringify_object_id(cls, v: Any) -> Optional[str]:
        return str(v) if v is not None else v


# ── Analytics & Sara Agent Models (Task A.3) ────────────────────────────────

REVENUECAT_EVENT_TYPES = (
    "INITIAL_PURCHASE",
    "RENEWAL",
    "CANCELLATION",
    "UNCANCELLATION",
    "NON_RENEWING_PURCHASE",
    "SUBSCRIPTION_PAUSED",
    "EXPIRATION",
    "BILLING_ISSUE",
    "PRODUCT_CHANGE",
    "TRANSFER",
    "TEST",
)


class RevenueCatEventDoc(BaseModel):
    """db.revenuecat_events - subscription lifecycle audit log from RevenueCat webhooks."""
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    id: Optional[str] = Field(default=None, alias="_id")
    event_id: str
    event_type: str
    app_user_id: str
    original_app_user_id: Optional[str] = None
    product_id: Optional[str] = None
    entitlement_id: Optional[str] = None
    price_in_purchased_currency: Optional[float] = None
    currency: Optional[str] = None
    environment: str = "PRODUCTION"
    cancel_reason: Optional[str] = None
    raw_payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def _stringify_object_id(cls, v: Any) -> Optional[str]:
        return str(v) if v is not None else v


# ── JARVIS Multi-Agent Queue & Coordination Models (Task A.1) ──────────────



JARVIS_QUEUE_STATUSES = ("pending", "in_progress", "resolved", "rejected", "failed")


class JarvisQueueItemDoc(BaseModel):
    """db.jarvis_queue_items - unified queue for all EYV sub-agents
    (Denver/Bob/Sara) feeding JARVIS (Claude coordinator brain).
    Generic payload rather than a separate table per agent.
    Priority: 1 (critical/highest) -> 5 (normal) -> 10 (low)."""
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    id: Optional[str] = Field(default=None, alias="_id")
    source_agent: str
    item_type: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    priority: int = 5
    status: Literal[JARVIS_QUEUE_STATUSES] = "pending"
    created_at: datetime
    resolved_at: Optional[datetime] = None

    @field_validator("id", mode="before")
    @classmethod
    def _stringify_object_id(cls, v: Any) -> Optional[str]:
        return str(v) if v is not None else v


class JarvisDecisionDoc(BaseModel):
    """db.jarvis_decisions - records of decisions submitted back by JARVIS
    upon reasoning about queue items or autonomous agent actions."""
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    id: Optional[str] = Field(default=None, alias="_id")
    queue_item_id: Optional[str] = None
    source_agent: str = "jarvis"
    decision_type: str = "general"
    action: Any = None
    reason: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    details: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def _stringify_object_id(cls, v: Any) -> Optional[str]:
        return str(v) if v is not None else v



JARVIS_APPROVAL_STATUSES = ("pending", "approved", "rejected")


class JarvisApprovalDoc(BaseModel):
    """db.jarvis_approvals - pending approval records created when JARVIS
    decides an action requires human sign-off (Abhinay).
    Stores approval_token_hash (sha256 digest) at rest with expires_at,
    never the raw token in plaintext."""
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    id: Optional[str] = Field(default=None, alias="_id")
    queue_item_id: Optional[str] = None
    decision_id: Optional[str] = None
    action_type: str
    title: str
    description: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    requester_agent: str = "jarvis"
    approval_token_hash: str
    status: Literal[JARVIS_APPROVAL_STATUSES] = "pending"
    resolution_note: Optional[str] = None
    created_at: datetime
    expires_at: datetime
    resolved_at: Optional[datetime] = None

    @field_validator("id", mode="before")
    @classmethod
    def _stringify_object_id(cls, v: Any) -> Optional[str]:
        return str(v) if v is not None else v


# ── Admin Dashboard & Session Models ───────────────────────────────────────

class AdminSessionDoc(BaseModel):
    """db.admin_sessions - short-lived session tokens for Admin UI control."""
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    id: Optional[str] = Field(default=None, alias="_id")
    session_token_hash: str  # SHA-256
    admin_email: Optional[str] = None
    created_at: datetime
    expires_at: datetime  # 2 hours TTL

    @field_validator("id", mode="before")
    @classmethod
    def _stringify_object_id(cls, v: Any) -> Optional[str]:
        return str(v) if v is not None else v


class AdminAuditLogDoc(BaseModel):
    """db.admin_audit_log - immutable audit trail for all admin panel operations."""
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    id: Optional[str] = Field(default=None, alias="_id")
    timestamp: datetime
    route: str
    method: str
    admin_identity: str
    client_ip: str
    status_code: int
    action: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", mode="before")
    @classmethod
    def _stringify_object_id(cls, v: Any) -> Optional[str]:
        return str(v) if v is not None else v



