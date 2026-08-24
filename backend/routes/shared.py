"""Shared models, dependencies, clients, and helpers across API routes.
Preserves all existing logic, type signatures, docstrings, and contracts verbatim.
"""
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field, ConfigDict, model_validator
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from pathlib import Path
import os
import functools
import hashlib
import hmac
import httpx
import asyncio
import logging
import subprocess
import secrets
from google import genai
from motor.motor_asyncio import AsyncIOMotorClient
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from rate_limit_keys import get_trusted_client_ip
from services.payment_provider import get_payment_provider, PaymentProvider

ROOT_DIR = Path(__file__).parent.parent
from dotenv import load_dotenv
load_dotenv(ROOT_DIR / '.env')

logger = logging.getLogger(__name__)

# ── Database & Global Clients ──────────────────────────────────────────────
_loop_clients = {}


def _get_db():
    import sys
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    global _loop_clients
    if loop not in _loop_clients:
        mongo_url = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
        db_name = os.environ.get('DB_NAME', 'test_database')
        c = AsyncIOMotorClient(mongo_url)
        _loop_clients[loop] = c[db_name]
    return _loop_clients[loop]


class _DbProxy:
    def __getattr__(self, name):
        import sys
        srv = sys.modules.get("server")
        if srv is not None and hasattr(srv, "db") and not isinstance(srv.db, _DbProxy):
            return getattr(srv.db, name)
        return getattr(_get_db(), name)

    def __getitem__(self, name):
        import sys
        srv = sys.modules.get("server")
        if srv is not None and hasattr(srv, "db") and not isinstance(srv.db, _DbProxy):
            return srv.db[name]
        return _get_db()[name]


db = _DbProxy()
client = AsyncIOMotorClient(os.environ.get('MONGO_URL', 'mongodb://localhost:27017'))



GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
GEMINI_MODEL = "gemini-2.5-flash"  # gemini-2.0-flash/-lite return 429 (zero free-tier quota) and gemini-1.5-flash is 404 on this API key/version


_real_gemini_client = None


def _get_gemini_client() -> genai.Client:
    """Lazy singleton - genai.Client(api_key=...) raises ValueError
    immediately if the key is None/blank, so constructing this eagerly at
    import time meant a missing GEMINI_API_KEY crashed the entire server
    at boot (auth, bookings, every unrelated endpoint), not just trip
    generation and chat. Now that failure only happens the first time
    something that actually needs Gemini runs, scoped to just that
    request instead of the whole process.
    Also honors monkeypatching of server._get_gemini_client in test suites.
    """
    import sys
    server_mod = sys.modules.get("server")
    if server_mod is not None:
        server_client_fn = getattr(server_mod, "_get_gemini_client", None)
        if server_client_fn is not None and server_client_fn is not _get_gemini_client:
            return server_client_fn()

    global _real_gemini_client
    if _real_gemini_client is None:
        _real_gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    return _real_gemini_client



class _PaymentProviderProxy:
    def __getattr__(self, name):
        return getattr(get_payment_provider(), name)


payment_provider = _PaymentProviderProxy()

GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')
GOOGLE_REDIRECT_URI = os.environ.get('GOOGLE_REDIRECT_URI')
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:3000')
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
OAUTH_TICKET_TTL_SECONDS = 300


def _resolve_admin_api_key() -> str:
    """Authenticates the EYV Admin surface. Fails fast at startup if unset."""
    key = os.environ.get("ADMIN_API_KEY")
    if not key:
        raise RuntimeError(
            "ADMIN_API_KEY must be set - it authenticates the EYV Admin surface. "
            "Set it in backend/.env for local dev and in Railway's service variables for deploys."
        )
    return key


ADMIN_API_KEY = _resolve_admin_api_key()


def _resolve_cors_origins() -> List[str]:
    """Explicit allowlist only - no wildcard fallback. Combined with the
    allow_credentials=True on the CORSMiddleware below, a "*" origin makes
    Starlette reflect back whatever Origin sent the request whenever a
    cookie is present (see CORSMiddleware.send()), letting any website ride
    a logged-in user's session_token cookie into this API. Fail loudly at
    import time instead of ever silently allowing that - a crashed deploy
    is recoverable, a silently wide-open CORS policy isn't."""
    origins = [o.strip() for o in os.environ.get('CORS_ORIGINS', '').split(',') if o.strip()]
    if not origins or '*' in origins:
        raise RuntimeError(
            "CORS_ORIGINS must be a comma-separated list of explicit origins "
            "(e.g. http://localhost:3000) - it is unset or contains '*', which "
            "is incompatible with allow_credentials=True. Set it in backend/.env "
            "for local dev and in Railway's service variables for deploys."
        )
    return origins


CORS_ORIGINS = _resolve_cors_origins()


def _resolve_wallet_download_secret() -> str:
    """Signs short-lived wallet file download URLs (item id + expiry) so the
    download route can validate a request without needing the session
    cookie/token on it - deliberately a separate secret from session tokens
    (session tokens are opaque random values with no secret key at all) so a
    leaked download link can never be used to forge a session or vice versa.
    Required, not optional - unlike ADMIN_API_KEY-gated features, wallet
    downloads have no "disabled" fallback mode, and a per-process random
    fallback would make signed URLs fail validation on every other worker/
    restart. Set once in backend/.env locally and in Railway's service
    variables for deploys, and never rotate it without expecting all
    in-flight download links to invalidate."""
    secret = os.environ.get('WALLET_URL_SIGNING_SECRET')
    if not secret:
        raise RuntimeError(
            "WALLET_URL_SIGNING_SECRET must be set - it signs short-lived "
            "wallet file download URLs. Set it in backend/.env for local dev "
            "and in Railway's service variables for deploys."
        )
    return secret


WALLET_URL_SIGNING_SECRET = _resolve_wallet_download_secret()
WALLET_DOWNLOAD_URL_TTL_SECONDS = 180


def _resolve_revenuecat_webhook_key() -> str:
    """Authenticates incoming RevenueCat subscription lifecycle webhooks (Task A.3 - Sara).
    Strictly required at boot (consistent with WALLET_URL_SIGNING_SECRET and internal API tokens)
    so an unset auth key immediately fails fast rather than silently accepting or failing requests."""
    key = os.environ.get("REVENUECAT_WEBHOOK_AUTH_KEY")
    if not key:
        raise RuntimeError(
            "REVENUECAT_WEBHOOK_AUTH_KEY must be set - it authenticates incoming "
            "RevenueCat subscription lifecycle webhooks. Set it in backend/.env "
            "for local dev and in Railway's service variables for deploys."
        )
    return key


REVENUECAT_WEBHOOK_AUTH_KEY = _resolve_revenuecat_webhook_key()


def _hash_session_token(token: str) -> str:
    """Session tokens are already high-entropy random values (uuid4().hex),
    so a plain SHA-256 hash is sufficient here - no need for slow/salted
    hashing (bcrypt etc.) meant for low-entropy human passwords."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _sign_wallet_download(item_id: str, expires: int) -> str:
    message = f"{item_id}:{expires}".encode("utf-8")
    return hmac.new(WALLET_URL_SIGNING_SECRET.encode("utf-8"), message, hashlib.sha256).hexdigest()


# Singleton HTTP client factory function placeholder - app reference passed or imported dynamically
_internal_ticket_http_client_instance = None


def get_internal_ticket_http_client(app_instance=None) -> httpx.AsyncClient:
    global _internal_ticket_http_client_instance
    if _internal_ticket_http_client_instance is None:
        if app_instance is None:
            import server
            app_instance = server.app
        _internal_ticket_http_client_instance = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app_instance),
            base_url="http://internal"
        )
    return _internal_ticket_http_client_instance


def _get_internal_ticket_http_client() -> httpx.AsyncClient:
    return get_internal_ticket_http_client()


def _internal_ticket_api_token() -> str:
    """Reads INTERNAL_TICKET_API_TOKEN the same way internal_tickets_api.py
    itself does (re-read on every call, not cached - see that module's own
    _current_internal_ticket_api_token docstring for why: instant
    revocation). Read directly from the environment here rather than
    importing that module's own private helper - this app's convention is
    every module reads its own secrets from os.environ directly."""
    return os.environ.get('INTERNAL_TICKET_API_TOKEN', '')


_SERVER_STARTED_AT = datetime.now(timezone.utc)
_SERVER_PID = os.getpid()


def _resolve_app_version() -> str:
    """Short commit hash the running process was built from, for GET /health
    and Sentry's `release`. APP_VERSION (set by the platform at build/deploy
    time - e.g. a Docker build ARG baking in `git rev-parse --short HEAD`, or
    Railway/Vercel's own git-sha env var) always wins so a deployed instance
    reports exactly what's live rather than whatever happened to be checked
    out wherever the image was built. Falls back to reading git directly,
    which only works when running from a working tree with .git present -
    i.e. local dev, not inside a built container image."""
    env_version = os.environ.get('APP_VERSION')
    if env_version:
        return env_version
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            cwd=ROOT_DIR, capture_output=True, text=True, timeout=2, check=True,
        )
        return result.stdout.strip()
    except Exception:
        return 'unknown'


APP_VERSION = _resolve_app_version()


# ── Rate Limiting ──────────────────────────────────────────────────────────
def _session_token_key(request: Request) -> str:
    token = request.cookies.get("session_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[len("Bearer "):]
    return token or get_trusted_client_ip(request)


limiter = Limiter(key_func=get_trusted_client_ip)


class QuotaExceededError(Exception):
    def __init__(self, used: int, limit: int):
        self.used = used
        self.limit = limit


# ── Shared Models ──────────────────────────────────────────────────────────
class User(BaseModel):
    model_config = ConfigDict(extra="ignore")
    user_id: str
    email: str
    name: str
    picture: Optional[str] = None
    created_at: datetime


class UserSession(BaseModel):
    model_config = ConfigDict(extra="ignore")
    session_id: str
    user_id: str
    expires_at: datetime
    created_at: datetime
    user_agent: Optional[str] = None


class SessionExchangeRequest(BaseModel):
    session_id: str


class TripPreferences(BaseModel):
    destination: str
    starting_location: str
    departure_date: str
    return_date: str
    adults: int = Field(default=1, ge=0)
    children: int = Field(default=0, ge=0)
    seniors: int = Field(default=0, ge=0)
    # Derived server-side from adults+children+seniors below - never trusted
    # from the client, the same way price_cache_service never trusts a
    # client-supplied price. Any value sent by the client is discarded.
    num_travelers: int = Field(default=0, ge=0)
    transportation: str
    # "round_trip" (default) or "one_way" - frontend TripPlannerPage's "One-way
    # trip" checkbox (Trip Basics step). Previously absent from this model, so
    # Pydantic's extra="ignore" default silently dropped it from every request -
    # same class of bug the cruise_cabin_type comment above describes.
    trip_direction: str = "round_trip"
    budget_level: str
    accommodation: List[str]
    interests: List[str]
    dietary_preferences: Optional[str] = None
    accessibility_requirements: Optional[str] = None
    travel_pace: Optional[str] = None
    trip_type: str
    currency: str = "INR"
    budget_mode: bool = True
    # Road Trip question branch (frontend TripPlannerPage "Road Trip
    # Preferences" step) - only meaningful when transportation == "Road Trip".
    # Previously absent from this model, so FastAPI/Pydantic silently dropped
    # every one of these from every request before generate_single_plan's
    # road_flavor_block (or any real day-count math) ever saw the user's
    # actual answers - road_max_driving_hours_per_day always fell back to
    # its hardcoded default of 8 regardless of what was picked in the wizard.
    road_drivers: Optional[int] = None
    road_max_hours_before_break: Optional[int] = None
    road_break_duration_minutes: Optional[int] = None
    road_max_driving_hours_per_day: Optional[int] = None
    road_route_style: Optional[str] = None
    road_route_avoidances: List[str] = Field(default_factory=list)
    road_fuel_type: Optional[str] = None
    road_vehicle_mileage_or_model: Optional[str] = None
    road_ev_battery_percent: Optional[int] = None
    road_ev_recharge_preference: Optional[str] = None
    road_overnight_accommodation: List[str] = Field(default_factory=list)
    road_food_preference: Optional[str] = None
    road_route_attractions: List[str] = Field(default_factory=list)
    road_avoid: List[str] = Field(default_factory=list)
    # Cruise question branch (frontend TripPlannerPage "Cruise Preferences"
    # step) - only meaningful when transportation == "Cruise". Previously
    # absent from this model, so FastAPI/Pydantic silently dropped them from
    # every request before generation ever saw them.
    cruise_cabin_type: Optional[str] = None
    cruise_duration_preference: Optional[str] = None
    cruise_dining_style: Optional[str] = None
    cruise_itinerary_style: Optional[str] = None

    @model_validator(mode="after")
    def _derive_and_validate_num_travelers(self):
        self.num_travelers = self.adults + self.children + self.seniors
        if self.num_travelers < 1:
            raise ValueError("At least 1 traveler (adults + children + seniors) is required")
        return self


class TripPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")
    trip_id: str
    user_id: str
    preferences: Dict[str, Any]
    plan_type: str
    itinerary: Dict[str, Any]
    total_cost: float
    cost_breakdown: Dict[str, float]
    created_at: datetime
    status: str = "draft"


class SavedTrip(BaseModel):
    model_config = ConfigDict(extra="ignore")
    trip_id: str
    user_id: str
    trip_name: str
    preferences: Dict[str, Any]
    plans: List[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime


class ChatMessage(BaseModel):
    message: str
    trip_id: Optional[str] = None
    selected_tier: Optional[str] = None


TRIP_PLAN_TYPES = ("Budget", "Premium", "Luxury")


# ── Shared Auth Helpers ────────────────────────────────────────────────────
async def _get_current_session(request: Request) -> Dict[str, Any]:
    """Resolves the raw session document for the request's session token.
    Split out from get_current_user() so session-management endpoints (list/
    revoke) can get at session_id/expires_at/etc. without a second lookup."""
    session_token = request.cookies.get("session_token")
    if not session_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            session_token = auth_header.replace("Bearer ", "")

    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    token_hash = _hash_session_token(session_token)
    session_doc = await db.user_sessions.find_one(
        {"session_token": token_hash},
        {"_id": 0}
    )

    if not session_doc:
        raise HTTPException(status_code=401, detail="Invalid session")

    expires_at = session_doc["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at < datetime.now(timezone.utc):
        await db.user_sessions.delete_one({"session_token": token_hash})
        raise HTTPException(status_code=401, detail="Session expired")

    return session_doc


async def get_current_user(request: Request) -> User:
    session_doc = await _get_current_session(request)

    user_doc = await db.users.find_one(
        {"user_id": session_doc["user_id"]},
        {"_id": 0}
    )

    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")

    if isinstance(user_doc['created_at'], str):
        user_doc['created_at'] = datetime.fromisoformat(user_doc['created_at'])

    return User(**user_doc)


async def is_user_premium(user_id: str) -> bool:
    """Stripe is the source of truth; stripe_subscription_status/
    current_period_end are a webhook-synced local cache read here so an
    access check never has to make a live Stripe API call. Never writes -
    these fields are only ever set from _sync_subscription_from_stripe
    (customer.subscription.created/updated/deleted) or the invoice webhooks,
    never guessed at from app-side date math.

    "past_due" (Stripe's own Smart Retries mid-grace-period status) counts
    as active - by the time a renewal invoice first fails, current_period_end
    has typically already lapsed (that's *why* Stripe is retrying), so this
    deliberately does NOT also require current_period_end >= now while
    past_due, or the grace period would be a no-op. Access only actually
    ends once a later customer.subscription.updated/deleted moves status to
    something else (canceled/unpaid), driven entirely by Stripe's own retry
    schedule and Dashboard-configured exhaustion action - no independent
    grace-period timer of ours."""
    user_doc = await db.users.find_one(
        {'user_id': user_id},
        {'_id': 0, 'stripe_subscription_status': 1, 'current_period_end': 1}
    )
    if not user_doc:
        return False
    status = user_doc.get('stripe_subscription_status')
    if status == 'past_due':
        return True
    if status != 'active':
        return False
    current_period_end = user_doc.get('current_period_end')
    if not current_period_end:
        return True
    if isinstance(current_period_end, str):
        current_period_end = datetime.fromisoformat(current_period_end)
    if current_period_end.tzinfo is None:
        current_period_end = current_period_end.replace(tzinfo=timezone.utc)
    return current_period_end >= datetime.now(timezone.utc)
