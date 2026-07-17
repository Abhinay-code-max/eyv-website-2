from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, UploadFile, File, Header, Query
from fastapi.responses import StreamingResponse, RedirectResponse, JSONResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import math
from pathlib import Path

# Must run before importing any service module below - several of them read
# their API keys from os.environ at import time, so .env has to be loaded first.
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from typing import List, Optional, Dict, Any
import uuid
import secrets
from urllib.parse import urlencode
from datetime import datetime, timezone, timedelta
import httpx
import asyncio
from openai import AsyncOpenAI
from google import genai
from google.genai import types as genai_types
import stripe
from services import amadeus_service, storage_service, rewards_service, locations_service
from services import ignav_service as duffel_service  # Ignav replaces Sky Scrapper
from services import serpapi_hotels_service
from services import price_cache_service
from services import log_redaction
from services import quota_service, usage_service
from services import chat_service
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)  # kept for potential future switch-back, currently unused
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
gemini_client = genai.Client(api_key=GEMINI_API_KEY)
GEMINI_MODEL = "gemini-2.5-flash"  # gemini-2.0-flash/-lite return 429 (zero free-tier quota) and gemini-1.5-flash is 404 on this API key/version
stripe.api_key = os.environ.get('STRIPE_API_KEY')

GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')
GOOGLE_REDIRECT_URI = os.environ.get('GOOGLE_REDIRECT_URI')
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:3000')
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
OAUTH_TICKET_TTL_SECONDS = 300
ADMIN_API_KEY = os.environ.get('ADMIN_API_KEY')

app = FastAPI()
api_router = APIRouter(prefix="/api")

# ── Rate limiting ────────────────────────────────────────────────────────
# In-memory storage: no Redis in this deployment (single process, no
# multi-worker/multi-instance setup) - if that changes, point these at
# Redis instead so limits are shared across processes.
#
# One Limiter instance, stacked twice on /trips/generate with different
# key_funcs (IP and session token) - both accumulate onto the SAME route's
# limit list and are evaluated together per request. Two *separate* Limiter
# instances would NOT both fire: slowapi's per-route wrapper sets
# request.state._rate_limiting_complete after the first one runs, and every
# later decorator on the same route (even from a different Limiter) skips
# its own check because of that flag. Keying by session token/bearer value
# (not a resolved user_id) avoids an async DB lookup inside a sync key_func;
# falls back to IP for unauthenticated requests (get_current_user rejects
# those with 401 inside the handler anyway).
#
# These are a coarse "stop scripted loops" backstop, not the main control -
# the real per-user control is the daily quota further down (quota_service),
# which Premium accounts are exempt from.
def _session_token_key(request: Request) -> str:
    token = request.cookies.get("session_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[len("Bearer "):]
    return token or get_remote_address(request)


limiter = Limiter(key_func=get_remote_address)


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    response = JSONResponse(
        status_code=429,
        content={
            "detail": "Too many requests - please slow down and try again shortly.",
            "reason": "rate_limited",
        },
    )
    # exc.limit.limit is the underlying limits.RateLimitItem (e.g. "5 per
    # minute") - GRANULARITY[0] * multiples gives the window length in
    # seconds. An approximation (window length, not exact time left in the
    # current window), but simple and always correct.
    try:
        item = exc.limit.limit
        response.headers["Retry-After"] = str(item.GRANULARITY[0] * item.multiples)
    except Exception:
        pass
    return response


app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)


# ── Daily free-tier generation quota ─────────────────────────────────────
# The durable per-user control (unlike the rate limits above, which only
# guard against short bursts). See services/quota_service.py.
class QuotaExceededError(Exception):
    def __init__(self, used: int, limit: int):
        self.used = used
        self.limit = limit


async def quota_exceeded_handler(request: Request, exc: QuotaExceededError):
    return JSONResponse(
        status_code=429,
        content={
            "detail": (
                f"You've used your {exc.limit} free trip generations today - "
                "upgrade to Premium for unlimited planning."
            ),
            "reason": "quota_exceeded",
            "used": exc.used,
            "limit": exc.limit,
        },
    )


app.add_exception_handler(QuotaExceededError, quota_exceeded_handler)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
# SerpApi's api_key travels as a URL query param (no header alternative -
# confirmed against their docs/client source) and httpx logs full request
# URLs at INFO - scrub it before it reaches any handler, at any log level.
log_redaction.install_secret_redaction()

# Models
class User(BaseModel):
    model_config = ConfigDict(extra="ignore")
    user_id: str
    email: str
    name: str
    picture: Optional[str] = None
    created_at: datetime

class UserSession(BaseModel):
    model_config = ConfigDict(extra="ignore")
    session_token: str
    user_id: str
    expires_at: datetime
    created_at: datetime

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
    budget_level: str
    accommodation: List[str]
    interests: List[str]
    dietary_preferences: Optional[str] = None
    accessibility_requirements: Optional[str] = None
    travel_pace: Optional[str] = None
    trip_type: str
    currency: str = "INR"
    budget_mode: bool = True

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

# Auth Helper
async def get_current_user(request: Request) -> User:
    session_token = request.cookies.get("session_token")
    if not session_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            session_token = auth_header.replace("Bearer ", "")
    
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    session_doc = await db.user_sessions.find_one(
        {"session_token": session_token},
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
        await db.user_sessions.delete_one({"session_token": session_token})
        raise HTTPException(status_code=401, detail="Session expired")
    
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
    """Mirrors the active-and-not-expired check in GET /subscription/status,
    minus that endpoint's side-effecting write-back of expired status (not
    worth an extra write on every quota check - that endpoint already keeps
    the stored status current whenever the user views it)."""
    user_doc = await db.users.find_one(
        {'user_id': user_id},
        {'_id': 0, 'premium_status': 1, 'premium_expires_at': 1}
    )
    if not user_doc or user_doc.get('premium_status') != 'active':
        return False
    expires_at = user_doc.get('premium_expires_at')
    if not expires_at:
        return True
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at >= datetime.now(timezone.utc)

# Auth Routes
@api_router.get("/auth/google/login")
async def google_login():
    if not GOOGLE_CLIENT_ID or not GOOGLE_REDIRECT_URI:
        raise HTTPException(status_code=500, detail="Google OAuth not configured")

    state = secrets.token_urlsafe(24)
    await db.oauth_states.insert_one({
        "state": state,
        "created_at": datetime.now(timezone.utc).isoformat()
    })

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "prompt": "select_account",
        "state": state,
    }
    return RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")


@api_router.get("/auth/google/callback")
async def google_callback(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    if error or not code or not state:
        return RedirectResponse(f"{FRONTEND_URL}/login")

    state_doc = await db.oauth_states.find_one({"state": state})
    if not state_doc:
        return RedirectResponse(f"{FRONTEND_URL}/login")
    await db.oauth_states.delete_one({"state": state})

    try:
        async with httpx.AsyncClient() as client:
            token_resp = await client.post(GOOGLE_TOKEN_URL, data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            })
            token_resp.raise_for_status()
            tokens = token_resp.json()

            userinfo_resp = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {tokens['access_token']}"}
            )
            userinfo_resp.raise_for_status()
            profile = userinfo_resp.json()
    except Exception as e:
        logger.error(f"Google OAuth callback error: {e}")
        return RedirectResponse(f"{FRONTEND_URL}/login")

    ticket = uuid.uuid4().hex
    await db.oauth_tickets.insert_one({
        "ticket": ticket,
        "email": profile["email"],
        "name": profile.get("name", profile["email"]),
        "picture": profile.get("picture"),
        "created_at": datetime.now(timezone.utc).isoformat()
    })

    return RedirectResponse(f"{FRONTEND_URL}/dashboard#session_id={ticket}")


@api_router.post("/auth/session")
async def exchange_session(request: SessionExchangeRequest, response: Response):
    try:
        ticket_doc = await db.oauth_tickets.find_one(
            {"ticket": request.session_id}, {"_id": 0}
        )
        if not ticket_doc:
            raise HTTPException(status_code=401, detail="Invalid session ID")
        await db.oauth_tickets.delete_one({"ticket": request.session_id})

        ticket_created_at = datetime.fromisoformat(ticket_doc["created_at"])
        if (datetime.now(timezone.utc) - ticket_created_at).total_seconds() > OAUTH_TICKET_TTL_SECONDS:
            raise HTTPException(status_code=401, detail="Session ID expired")

        session_data = ticket_doc

        existing_user = await db.users.find_one(
            {"email": session_data["email"]},
            {"_id": 0}
        )

        if existing_user:
            user_id = existing_user["user_id"]
            await db.users.update_one(
                {"user_id": user_id},
                {"$set": {
                    "name": session_data["name"],
                    "picture": session_data.get("picture")
                }}
            )
        else:
            user_id = f"user_{uuid.uuid4().hex[:12]}"
            user_doc = {
                "user_id": user_id,
                "email": session_data["email"],
                "name": session_data["name"],
                "picture": session_data.get("picture"),
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            await db.users.insert_one(user_doc)

        session_token = uuid.uuid4().hex
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)

        await db.user_sessions.delete_many({"user_id": user_id})

        session_doc = {
            "session_token": session_token,
            "user_id": user_id,
            "expires_at": expires_at.isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.user_sessions.insert_one(session_doc)

        response.set_cookie(
            key="session_token",
            value=session_token,
            httponly=True,
            secure=True,
            samesite="none",
            path="/",
            max_age=7*24*60*60
        )


        user_doc = await db.users.find_one({"user_id": user_id}, {"_id": 0})
        if isinstance(user_doc['created_at'], str):
            user_doc['created_at'] = datetime.fromisoformat(user_doc['created_at'])

        return {"user": User(**user_doc).model_dump(mode='json'), "message": "Authentication successful"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Session exchange error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/auth/me")
async def get_me(request: Request):
    user = await get_current_user(request)
    return user.model_dump(mode='json')

@api_router.post("/auth/logout")
async def logout(request: Request, response: Response):
    session_token = request.cookies.get("session_token")
    if session_token:
        await db.user_sessions.delete_one({"session_token": session_token})
    
    response.delete_cookie(key="session_token", path="/")
    return {"message": "Logged out successfully"}

TRIP_PLAN_TYPES = ("Budget", "Premium", "Luxury")


def _placeholder_plan(plan_type: str, currency: str, currency_symbol: str) -> Dict[str, Any]:
    """Shape a tier's entry takes in the trips.plans array from the moment
    the trip is created until that tier's own generation finishes - lets the
    frontend render each tier's card independently (status: "generating" ->
    "ready"/"failed") instead of blocking on the slowest of the three."""
    return {
        "plan_type": plan_type,
        "status": "generating",
        "currency": currency,
        "currency_symbol": currency_symbol,
        "itinerary": {},
        "cost_breakdown": {"transportation": 0, "accommodation": 0, "food": 0, "activities": 0, "miscellaneous": 0},
        "total_cost": 0,
        "highlights": [],
        "budget_tips": [],
    }


# Strong references to in-flight background generation tasks - asyncio only
# holds a *weak* reference to a task once nothing else does, so a bare
# `asyncio.create_task(...)` with the result discarded risks the task being
# garbage-collected mid-generation. Each task removes itself on completion.
_background_generation_tasks: set = set()


def _spawn_background_task(coro) -> None:
    task = asyncio.create_task(coro)
    _background_generation_tasks.add(task)

    def _on_done(t: asyncio.Task) -> None:
        _background_generation_tasks.discard(t)
        if not t.cancelled() and t.exception() is not None:
            # generate_single_plan already catches and reports its own
            # failures via the "failed" plan status - this is a backstop
            # for anything unexpected escaping the update itself (e.g. a
            # DB write error), so it isn't silently dropped.
            logger.error(f"Background trip-generation task failed unexpectedly: {t.exception()}")

    task.add_done_callback(_on_done)


async def _generate_and_save_tier(trip_id: str, user_id: str, plan_type: str, preferences_dict: Dict, plan_index: int) -> None:
    """Generate one tier and write only its slot in the trip's plans array -
    the same single-index update the regenerate endpoint uses, so a tier
    finishing here is indistinguishable from one finishing via regenerate."""
    plan = await generate_single_plan(preferences_dict, plan_type, trip_id, user_id)
    await db.trips.update_one(
        {"trip_id": trip_id, "user_id": user_id},
        {"$set": {f"plans.{plan_index}": plan, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )


# Trip Planning Routes
@api_router.post("/trips/generate")
@limiter.limit("5/minute")  # per-IP - stops a scripted loop from one source
@limiter.limit("5/minute", key_func=_session_token_key)  # per-authenticated-user
async def generate_trip_plans(preferences: TripPreferences, request: Request):
    user = await get_current_user(request)

    # Daily free-tier quota - the durable control, not just a burst guard.
    # Premium accounts are exempt entirely.
    if not await is_user_premium(user.user_id):
        quota = await quota_service.try_consume_trip_generation(db, user.user_id)
        if not quota["allowed"]:
            raise QuotaExceededError(used=quota["used"], limit=quota["limit"])

    trip_id = f"trip_{uuid.uuid4().hex[:12]}"

    # Store preferences
    preferences_dict = preferences.model_dump()
    currency = preferences_dict.get('currency', 'INR')
    currency_symbol = '₹' if currency == 'INR' else '$'

    # Save the trip immediately with all three tiers in "generating" status,
    # then kick off each tier's generation as an independent background task
    # instead of blocking this request on asyncio.gather for all three.
    # Budget/Premium typically finish well before Luxury (larger, denser
    # itinerary -> more prone to needing a retry) - this lets the frontend
    # show each tier the moment *it* is done rather than gating all three on
    # the slowest, and lets the client navigate to the results page and
    # start rendering almost immediately instead of waiting minutes.
    placeholder_plans = [_placeholder_plan(plan_type, currency, currency_symbol) for plan_type in TRIP_PLAN_TYPES]
    saved_trip = {
        "trip_id": trip_id,
        "user_id": user.user_id,
        "trip_name": f"{preferences.destination} Trip",
        "preferences": preferences_dict,
        "plans": placeholder_plans,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    await db.trips.insert_one(saved_trip)

    for plan_index, plan_type in enumerate(TRIP_PLAN_TYPES):
        _spawn_background_task(_generate_and_save_tier(trip_id, user.user_id, plan_type, preferences_dict, plan_index))

    return {"trip_id": trip_id, "plans": placeholder_plans}


@api_router.post("/trips/{trip_id}/regenerate/{plan_type}")
@limiter.limit("5/minute")  # per-IP - same guard as /trips/generate, still a real Gemini call
@limiter.limit("5/minute", key_func=_session_token_key)  # per-authenticated-user
async def regenerate_trip_plan(trip_id: str, plan_type: str, request: Request):
    """Re-run generation for a single tier of an existing trip (e.g. after
    that tier's original generation failed) without touching the other two
    tiers or re-fetching flight/hotel anchor data that already succeeded."""
    user = await get_current_user(request)

    if plan_type not in TRIP_PLAN_TYPES:
        raise HTTPException(status_code=400, detail=f"plan_type must be one of {list(TRIP_PLAN_TYPES)}")

    # Scoping the lookup to user_id doubles as the ownership check - a
    # trip_id that doesn't exist and one that belongs to someone else both
    # come back as the same 404, so this never leaks whether a given
    # trip_id exists for another account.
    trip = await db.trips.find_one(
        {"trip_id": trip_id, "user_id": user.user_id},
        {"_id": 0}
    )
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    plans = trip.get("plans", [])
    plan_index = next((i for i, p in enumerate(plans) if p.get("plan_type") == plan_type), None)
    if plan_index is None:
        raise HTTPException(status_code=404, detail=f"No {plan_type} plan found on this trip")

    # Daily free-tier quota - regenerating one tier is still a real Gemini
    # call, gated the same way as the original /trips/generate. Premium
    # accounts are exempt entirely, same as generate_trip_plans above.
    if not await is_user_premium(user.user_id):
        quota = await quota_service.try_consume_trip_generation(db, user.user_id)
        if not quota["allowed"]:
            raise QuotaExceededError(used=quota["used"], limit=quota["limit"])

    # Reuse the previously-fetched flight/train + hotel anchor for this tier
    # if we have one - avoids an unnecessary Duffel/SerpApi call for pricing
    # that hasn't changed. Older trips saved before anchor_pricing existed
    # fall back to a fresh fetch inside generate_single_plan.
    cached_anchor = plans[plan_index].get("anchor_pricing")

    regenerated = await generate_single_plan(
        trip["preferences"], plan_type, trip_id, user.user_id, anchor=cached_anchor
    )

    await db.trips.update_one(
        {"trip_id": trip_id, "user_id": user.user_id},
        {"$set": {f"plans.{plan_index}": regenerated, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )

    return {"trip_id": trip_id, "plan_type": plan_type, "plan": regenerated}


ROOM_OCCUPANCY = 2  # standard double-occupancy hotel room


def _room_count(num_travelers: int, occupancy: int = ROOM_OCCUPANCY) -> int:
    """Rooms a group needs at standard double occupancy. This is deliberately
    NOT the same as traveler count - 4 travelers need 2 rooms, not 4x the
    price of a single room."""
    return max(1, math.ceil(num_travelers / occupancy))


# Neither Ignav (flights) nor SerpApi (hotels) exposes separate child/senior
# fares - both only accept a flat adults/travelers count. These are
# project-defined fallback discounts, not provider-verified rates.
CHILD_FARE_DISCOUNT = 0.25   # children pay 75% of the adult fare
SENIOR_FARE_DISCOUNT = 0.10  # seniors pay 90% of the adult fare


def _fare_units(adults: int, children: int, seniors: int) -> float:
    """Age-weighted traveler count used to scale flight/train/meal prices.
    Deliberately NOT used for hotel room count - rooms are priced per-room,
    not per-person, so age has no bearing on how many rooms are needed."""
    return adults * 1.0 + children * (1 - CHILD_FARE_DISCOUNT) + seniors * (1 - SENIOR_FARE_DISCOUNT)


def _select_tier_hotel(hotels_sorted: List[Dict], plan_type: str) -> tuple:
    """Pick the anchor hotel for a Budget/Premium/Luxury plan by SELECTING a
    real hotel from the provider's own price-sorted results - Budget gets the
    cheapest, Premium the median, Luxury the most expensive. Every field on
    the returned hotel (name, price, stars, ...) is untouched provider data.

    Returns (hotel, limited_inventory) where limited_inventory is True when
    the destination doesn't have enough genuinely distinct prices to make
    Budget/Premium/Luxury meaningfully different - callers should say so
    rather than pretend the tiers are more separated than they really are.
    """
    if not hotels_sorted:
        return None, True

    if plan_type == "Budget":
        hotel = hotels_sorted[0]
    elif plan_type == "Premium":
        hotel = hotels_sorted[len(hotels_sorted) // 2]
    else:
        hotel = hotels_sorted[-1]

    # "Limited inventory" means the destination doesn't have enough genuine
    # price spread to make three tiers meaningfully different - either there
    # aren't 3 distinct prices at all, or the cheapest and priciest real
    # hotels are within 15% of each other.
    distinct_prices = {h["price"]["per_night"] for h in hotels_sorted}
    cheapest = hotels_sorted[0]["price"]["per_night"]
    priciest = hotels_sorted[-1]["price"]["per_night"]
    price_spread = (priciest / cheapest - 1) if cheapest else 0
    limited_inventory = len(distinct_prices) < 3 or price_spread < 0.15

    return hotel, limited_inventory


def _scale_per_person_costs(itinerary: Dict[str, Any], num_travelers: int) -> None:
    """Meals and per-person activities are generated by the AI as a single
    person's cost - scale them up to the full traveler count. Activities the
    AI tags pricing_type="flat_group" (a hired guide, a private car, a
    chartered boat) are one fixed cost regardless of group size and are left
    untouched."""
    for day_data in itinerary.values():
        if not isinstance(day_data, dict):
            continue
        for meal in day_data.get('meals', []):
            if isinstance(meal, dict) and isinstance(meal.get('cost'), (int, float)):
                meal['cost'] = meal['cost'] * num_travelers
        for activity in day_data.get('activities', []):
            if not isinstance(activity, dict):
                continue
            cost = activity.get('cost')
            if not isinstance(cost, (int, float)) or cost <= 0:
                continue
            if activity.get('pricing_type') == 'flat_group':
                continue
            activity['cost'] = cost * num_travelers


# Enforces the plan JSON's shape at generation time (Gemini structured
# output - response_mime_type="application/json" + response_json_schema)
# instead of only validating/fixing it after the fact. This is a reduction
# in how often the post-generation shape-hardening below has to kick in,
# not a replacement for it - structured output has occasionally been
# observed to still deviate (e.g. under retries/edge-case prompts), so the
# defensive isinstance checks in generate_single_plan stay as the backstop.
#
# "itinerary" keeps its existing day_1/day_2/... dict shape (verified live
# against the Gemini API that additionalProperties correctly constrains
# each day's value rather than the model falling back to an array) so no
# downstream code, prompt example, or stored-data shape has to change.
_DAY_SCHEMA = {
    "type": "object",
    "properties": {
        "date": {"type": "string"},
        "transportation": {
            "type": "object",
            "properties": {
                "mode": {"type": "string"},
                "details": {"type": "string"},
                "cost": {"type": "number"},
            },
            "required": ["mode", "cost"],
        },
        "activities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "time": {"type": "string"},
                    "activity": {"type": "string"},
                    "location": {"type": "string"},
                    "cost": {"type": "number"},
                    "category": {"type": "string"},
                    "pricing_type": {"type": "string", "enum": ["per_person", "flat_group"]},
                },
                "required": ["activity", "cost"],
            },
        },
        "accommodation": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "type": {"type": "string"},
                "cost": {"type": "number"},
                "location": {"type": "string"},
            },
            "required": ["name", "cost"],
        },
        "meals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "time": {"type": "string"},
                    "restaurant": {"type": "string"},
                    "cuisine": {"type": "string"},
                    "cost": {"type": "number"},
                },
                "required": ["cost"],
            },
        },
        "daily_total": {"type": "number"},
        "cumulative_total": {"type": "number"},
        "fixed_costs": {"type": "number"},
        "variable_costs": {"type": "number"},
    },
    "required": ["date", "transportation", "accommodation", "meals", "activities"],
}

PLAN_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "plan_type": {"type": "string"},
        "currency": {"type": "string"},
        "currency_symbol": {"type": "string"},
        "itinerary": {
            "type": "object",
            "additionalProperties": _DAY_SCHEMA,
            "minProperties": 1,
        },
        "cost_breakdown": {
            "type": "object",
            "properties": {
                "transportation": {"type": "number"},
                "accommodation": {"type": "number"},
                "food": {"type": "number"},
                "activities": {"type": "number"},
                "miscellaneous": {"type": "number"},
            },
            "required": ["transportation", "accommodation", "food", "activities", "miscellaneous"],
        },
        "total_cost": {"type": "number"},
        "highlights": {"type": "array", "items": {"type": "string"}},
        "budget_tips": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["plan_type", "currency", "currency_symbol", "itinerary", "cost_breakdown", "total_cost", "highlights", "budget_tips"],
}


async def _fetch_anchor_pricing(preferences: Dict, plan_type: str, user_id: str, fare_units: float, room_count: int) -> Dict[str, Any]:
    """Fetch real flight/train + hotel anchor prices for one tier. Split out
    of generate_single_plan so a single-tier regenerate can reuse a
    previously-fetched anchor (see the "anchor" param there) instead of
    hitting Duffel/SerpApi again for tiers that already anchored fine."""
    transport_mode = preferences.get("transportation", "flight").lower()
    is_train = "train" in transport_mode

    flight_price = 0
    flight_airline = ""
    flight_number = ""
    flight_dep_time = ""
    flight_arr_time = ""
    flight_duration = ""
    flight_stops = 0

    train_price = 0
    train_name = ""
    train_number = ""
    train_class = ""
    train_duration = ""

    hotel_name = ""
    hotel_price_per_night = 0
    hotel_stars = 0
    hotel_limited_inventory = False

    if is_train:
        train_tier_prices = {
            "Budget":  {"price": 450,  "class": "Sleeper (SL)",      "name": "Express Train"},
            "Premium": {"price": 1200, "class": "AC 3-Tier (3A)",    "name": "Superfast Express"},
            "Luxury":  {"price": 2800, "class": "AC 1st Class (1A)", "name": "Rajdhani / Shatabdi"},
        }
        t = train_tier_prices.get(plan_type, train_tier_prices["Budget"])
        train_price    = t["price"] * fare_units
        train_class    = t["class"]
        train_name     = t["name"]
        train_number   = "Train"
        train_duration = "Varies by route"
        logger.info(f"{plan_type}: estimated train = {train_name} {train_class} ₹{train_price:,.0f}")
    else:
        try:
            flight_pref = {"Budget": "cheapest", "Premium": "direct", "Luxury": "fastest"}.get(plan_type, "cheapest")
            # Always query for a single traveler - Ignav's own price.total already scales
            # with the "travelers" we pass it (confirmed: requesting travelers=4 returns
            # ~4x the travelers=1 fare), so if we passed num_travelers here we'd double it
            # by multiplying again below. Querying at 1 gives us a clean per-seat fare that
            # WE scale, the same way train_price already does with its fixed base rate.
            af = await duffel_service.get_anchor_flight(
                preferences.get("starting_location", ""),
                preferences.get("destination", ""),
                preferences.get("departure_date", ""),
                travelers=1,
                preference=flight_pref,
            )
            await usage_service.log_usage(db, "duffel", user_id=user_id, meta={"context": "generate_single_plan"})
            if af:
                # Each traveler needs their own seat/fare, discounted by age
                # (Ignav has no separate child/senior fare - see _fare_units).
                flight_price    = af['price']['total'] * fare_units
                flight_airline  = af['airline']
                flight_number   = af['flight_number']
                flight_dep_time = af['departure']['time']
                flight_arr_time = af['arrival']['time']
                flight_duration = af['duration']
                flight_stops    = af['stops']
            logger.info(f"{plan_type}: anchor flight = {flight_airline} {flight_number} ₹{flight_price:,.0f}")
        except Exception as e:
            logger.warning(f"Anchor flight fetch failed for {plan_type}: {e}")

    try:
        # Always query at standard double occupancy - SerpApi/Google Hotels already
        # adjusts rate_per_night based on the "adults" we pass it (confirmed: the same
        # property's rate for 4 adults came back 1.5x-7x its 1-adult rate, inconsistently
        # depending on room type), so passing the true num_travelers here and then
        # multiplying by room_count below would double-count on top of whatever the
        # provider already adjusted. Querying at ROOM_OCCUPANCY gives a stable per-room
        # rate that WE scale by room count, which we fully control.
        hotel_results = await serpapi_hotels_service.search_hotels(
            preferences.get("destination", ""),
            preferences.get("departure_date", ""),
            preferences.get("return_date", ""),
            travelers=ROOM_OCCUPANCY,
            currency="INR",
        )
        await usage_service.log_usage(db, "serpapi", user_id=user_id, meta={"context": "generate_single_plan"})
        if hotel_results:
            # hotel_results is already price-sorted ascending by the service -
            # SELECT the tier's hotel from real data, never edit its fields.
            ah, hotel_limited_inventory = _select_tier_hotel(hotel_results, plan_type)
            # Group accommodation cost is by room count, not traveler count - 4 people
            # share 2 double-occupancy rooms, not 4x the price of a single room.
            hotel_name           = ah['name']
            hotel_price_per_night = ah['price']['per_night'] * room_count
            hotel_stars          = ah['stars']
            logger.info(
                f"{plan_type}: anchor hotel = {hotel_name} ₹{ah['price']['per_night']:,.0f}/night "
                f"x {room_count} room(s) = ₹{hotel_price_per_night:,.0f}/night"
                f"{' [limited hotel inventory for this destination]' if hotel_limited_inventory else ''}"
            )
    except Exception as e:
        logger.warning(f"Anchor hotel fetch failed for {plan_type}: {e}")

    return {
        "is_train": is_train,
        "flight_price": flight_price,
        "flight_airline": flight_airline,
        "flight_number": flight_number,
        "flight_dep_time": flight_dep_time,
        "flight_arr_time": flight_arr_time,
        "flight_duration": flight_duration,
        "flight_stops": flight_stops,
        "train_price": train_price,
        "train_name": train_name,
        "train_number": train_number,
        "train_class": train_class,
        "train_duration": train_duration,
        "hotel_name": hotel_name,
        "hotel_price_per_night": hotel_price_per_night,
        "hotel_stars": hotel_stars,
        "hotel_limited_inventory": hotel_limited_inventory,
    }


async def generate_single_plan(
    preferences: Dict, plan_type: str, trip_id: str, user_id: str, anchor: Optional[Dict[str, Any]] = None
) -> Dict:
    """Generate a single vacation plan using AI with real price anchoring.

    `anchor`, when provided, skips Step 1's Duffel/SerpApi calls entirely and
    reuses that already-fetched flight/train + hotel pricing - used by the
    per-tier regenerate endpoint so retrying just the AI portion for one tier
    doesn't re-hit paid providers for pricing that hasn't changed.
    """
    import json

    currency = preferences.get('currency', 'INR')
    currency_symbol = '₹' if currency == 'INR' else '$'
    num_travelers = preferences.get('num_travelers', 1)
    room_count = _room_count(num_travelers)
    # Age-weighted count for flight/train/meal pricing (room count above stays
    # on raw headcount - occupancy isn't age-discounted).
    fare_units = _fare_units(
        preferences.get('adults', num_travelers),
        preferences.get('children', 0),
        preferences.get('seniors', 0),
    )

    # ── Step 1: Fetch real anchor prices (or reuse a previously-fetched one)
    if anchor is None:
        anchor = await _fetch_anchor_pricing(preferences, plan_type, user_id, fare_units, room_count)

    is_train = anchor["is_train"]
    flight_price = anchor["flight_price"]
    flight_airline = anchor["flight_airline"]
    flight_number = anchor["flight_number"]
    flight_dep_time = anchor["flight_dep_time"]
    flight_arr_time = anchor["flight_arr_time"]
    flight_duration = anchor["flight_duration"]
    flight_stops = anchor["flight_stops"]
    train_price = anchor["train_price"]
    train_name = anchor["train_name"]
    train_number = anchor["train_number"]
    train_class = anchor["train_class"]
    train_duration = anchor["train_duration"]
    hotel_name = anchor["hotel_name"]
    hotel_price_per_night = anchor["hotel_price_per_night"]
    hotel_stars = anchor["hotel_stars"]
    hotel_limited_inventory = anchor["hotel_limited_inventory"]

    # ── Step 2: Build tier-specific instructions ─────────────────────────────
    tier_rules = {
        "Budget": f"""
- Cheapest available options throughout
- Hotel: {hotel_name or 'budget guesthouse'} at EXACTLY ₹{hotel_price_per_night:,.0f}/night (use this hotel name and price)
- Public transport (metro, bus, shared rides)
- Street food and casual dining (₹150-400/meal)
- Free or low-cost attractions
- TOTAL trip cost must be the LOWEST of the three tiers
""",
        "Premium": f"""
- Mid-range comfortable options
- Hotel: {hotel_name or '4-star hotel'} at EXACTLY ₹{hotel_price_per_night:,.0f}/night (use this hotel name and price)
- Mix of metro and private transport
- Good restaurants (₹500-1200/meal)
- Mix of free and paid attractions
- TOTAL trip cost must be BETWEEN Budget and Luxury tiers
""",
        "Luxury": f"""
- Premium luxury options only
- Hotel: {hotel_name or '5-star luxury hotel'} at EXACTLY ₹{hotel_price_per_night:,.0f}/night (use this hotel name and price)
- Private transfers and premium vehicles only
- Fine dining at signature restaurants (₹1500+/meal)
- Exclusive experiences, private tours, VIP access
- TOTAL trip cost must be the HIGHEST of the three tiers
"""
    }

    # ── Step 3: Build the prompt with constraints at the TOP ─────────────────
    if is_train:
        flight_constraint = f"""TRAIN (DO NOT CHANGE THESE VALUES):
  Train Name: {train_name}
  Class: {train_class}
  Duration: {train_duration}
  PRICE: ₹{train_price:,.0f} total for {num_travelers} traveler(s) (USE THIS EXACT NUMBER)""" if train_price > 0 else "Use realistic Indian train prices."
    else:
        flight_constraint = f"""FLIGHT (DO NOT CHANGE THESE VALUES):
  Airline: {flight_airline}
  Flight Number: {flight_number}
  Departure: {flight_dep_time}
  Arrival: {flight_arr_time}
  Duration: {flight_duration}
  Stops: {'Non-stop' if flight_stops == 0 else f'{flight_stops} stop(s)'}
  PRICE: ₹{flight_price:,.0f} (USE THIS EXACT NUMBER — do not round, inflate, or change)""" if flight_price > 0 else "Use realistic market flight prices."

    hotel_constraint = f"""HOTEL (DO NOT CHANGE THESE VALUES):
  Name: {hotel_name}
  Stars: {hotel_stars}★
  PRICE PER NIGHT: ₹{hotel_price_per_night:,.0f} total for {room_count} room(s) accommodating {num_travelers} traveler(s) (USE THIS EXACT NUMBER)""" if hotel_price_per_night > 0 else "Use realistic market hotel prices."

    prompt = f"""You are a travel pricing engine. Generate a {plan_type} trip plan as valid JSON only.

╔══════════════════════════════════════════════════════╗
║  MANDATORY CONSTRAINTS — VIOLATION = INVALID OUTPUT  ║
╠══════════════════════════════════════════════════════╣
║ {flight_constraint}
║
║ {hotel_constraint}
║
║ TIER RULE: {plan_type} plan total must be
║ {'the LOWEST cost of all three tiers' if plan_type == 'Budget' else 'BETWEEN Budget and Luxury costs' if plan_type == 'Premium' else 'the HIGHEST cost of all three tiers'}
╚══════════════════════════════════════════════════════╝

TRIP DETAILS:
- Destination: {preferences['destination']}
- From: {preferences['starting_location']}
- Dates: {preferences['departure_date']} to {preferences['return_date']}
- Travelers: {num_travelers}
- Tier: {plan_type}
- Currency: {currency}

TIER GUIDELINES:
{tier_rules[plan_type]}

OUTPUT: Return ONLY valid JSON, no markdown, no explanation:
{{
  "plan_type": "{plan_type}",
  "currency": "{currency}",
  "currency_symbol": "{currency_symbol}",
  "itinerary": {{
    "day_1": {{
      "date": "{preferences['departure_date']}",
      "transportation": {{"mode": "{'train' if is_train else 'flight'}", "details": "{train_name + ' ' + train_class + ' ' if is_train else flight_airline + ' ' + flight_number + ' '}{preferences.get('starting_location','')} to {preferences['destination']}", "cost": {train_price if is_train and train_price > 0 else (flight_price if flight_price > 0 else 15000)}}},
      "activities": [{{"time": "14:00", "activity": "Check-in and explore", "location": "Hotel", "cost": 0, "category": "free", "pricing_type": "flat_group"}}],
      "accommodation": {{"name": "{hotel_name or 'Hotel'}", "type": "hotel", "cost": {hotel_price_per_night if hotel_price_per_night > 0 else 5000}, "location": "{preferences['destination']}"}},
      "meals": [{{"time": "dinner", "restaurant": "Local restaurant", "cuisine": "Local", "cost": 500}}],
      "daily_total": {int((train_price if is_train else flight_price) + hotel_price_per_night + 500) if (train_price if is_train else flight_price) and hotel_price_per_night else 20000},
      "cumulative_total": {int((train_price if is_train else flight_price) + hotel_price_per_night + 500) if (train_price if is_train else flight_price) and hotel_price_per_night else 20000},
      "fixed_costs": {int((train_price if is_train else flight_price) + hotel_price_per_night) if (train_price if is_train else flight_price) and hotel_price_per_night else 18000},
      "variable_costs": 500
    }}
  }},
  "cost_breakdown": {{
    "transportation": {train_price if is_train and train_price > 0 else (flight_price if flight_price > 0 else 15000)},
    "accommodation": 0,
    "food": 0,
    "activities": 0,
    "miscellaneous": 0
  }},
  "total_cost": 0,
  "highlights": ["highlight 1", "highlight 2", "highlight 3"],
  "budget_tips": ["tip 1", "tip 2", "tip 3"]
}}

Fill in ALL days from {preferences['departure_date']} to {preferences['return_date']}.
Use EXACT prices from constraints above — especially ₹{train_price if is_train else flight_price:,.0f} for {'train' if is_train else 'flight'} and ₹{hotel_price_per_night:,.0f}/night for hotel.
Generate realistic activities, meals, and local transport for each day.

MEAL AND ACTIVITY PRICING (group size = {num_travelers}):
- Every meal "cost" must be the PER-PERSON price of that meal only (e.g. a ₹400 thali is "cost": 400,
  regardless of group size). Do NOT multiply meal costs by the traveler count yourself — the system
  does that automatically afterward.
- Every activity with cost > 0 must include a "pricing_type" field:
  - "per_person" for anything charged per visitor (entry tickets, adventure sports, rides, per-head
    experiences). Report the PER-PERSON price only - do not multiply by traveler count yourself.
  - "flat_group" for anything with one fixed price regardless of group size (a private car/driver,
    a hired guide, a chartered boat). Report the actual total price for the whole group.
  - If unsure whether something is per-person or a flat group rate, use "per_person" - it's the more
    common case for tickets and experiences."""

    # ── Step 4: Call LLM (retry with backoff on failure) ──────────────────────
    max_attempts = 3
    last_error = None
    for attempt in range(max_attempts):
      try:
        if attempt > 0:
            backoff_seconds = 2 ** (attempt - 1)  # 1s, 2s, ...
            logger.warning(f"Retrying {plan_type} plan generation (attempt {attempt + 1}/{max_attempts}) after {backoff_seconds}s...")
            await asyncio.sleep(backoff_seconds)
        system_message = (
            f"You are a travel cost calculator that outputs ONLY valid JSON. "
            f"You ALWAYS use the exact prices provided in the MANDATORY CONSTRAINTS section. "
            f"{'Train' if is_train else 'Flight'} transport cost MUST be ₹{(train_price if is_train else flight_price):,.0f}. "
            f"Hotel cost MUST be ₹{hotel_price_per_night:,.0f}/night. "
            f"Never invent or change these numbers."
        )

        stream = await gemini_client.aio.models.generate_content_stream(
            model=GEMINI_MODEL,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                system_instruction=system_message,
                response_mime_type="application/json",
                response_json_schema=PLAN_RESPONSE_SCHEMA,
            ),
        )
        await usage_service.log_usage(db, "gemini", user_id=user_id, meta={"context": "generate_single_plan", "plan_type": plan_type})

        full_response = ""
        async for chunk in stream:
            if chunk.text:
                full_response += chunk.text

        # Parse JSON
        start_i = full_response.find('{')
        end_i   = full_response.rfind('}') + 1
        if start_i != -1 and end_i > start_i:
            plan_data = json.loads(full_response[start_i:end_i])
        else:
            raise ValueError("No JSON found in response")

        # ── Step 5: Post-process — enforce exact prices regardless of AI output
        logger.info(f"{plan_type}: flight_price={flight_price}, hotel_price={hotel_price_per_night}")
        logger.info(f"{plan_type}: AI day_1 transport cost before fix = {plan_data.get('itinerary', {}).get('day_1', {}).get('transportation', {}).get('cost', 'N/A')}")
        anchor_transport_price = train_price if is_train else flight_price
        anchor_transport_label = "train" if is_train else "flight"

        # The AI is asked to return "itinerary" as an object keyed by day_1,
        # day_2, ... with each day and its nested transportation/accommodation
        # as objects - but it doesn't always comply (e.g. an empty list `[]`
        # instead of `{}` for a day with no separate transport). Every write
        # below assumes those shapes, so normalize them here rather than let
        # a bracket-assignment into a wrongly-typed value crash the whole
        # generation (see "list indices must be integers or slices" crash).
        if not isinstance(plan_data.get('itinerary'), dict):
            plan_data['itinerary'] = {}
        itinerary = plan_data['itinerary']
        for day_key, day_val in list(itinerary.items()):
            if not isinstance(day_val, dict):
                itinerary[day_key] = {}

        if anchor_transport_price > 0:
            if not isinstance(plan_data.get('cost_breakdown'), dict):
                plan_data['cost_breakdown'] = {}
            plan_data['cost_breakdown']['transportation'] = anchor_transport_price

            days = sorted(itinerary.keys())

            if days:
                # Day 1: outbound transport
                d1 = itinerary[days[0]]
                if 'transportation' in d1:
                    if not isinstance(d1['transportation'], dict):
                        d1['transportation'] = {}
                    d1['transportation']['cost'] = anchor_transport_price
                    d1['transportation']['mode'] = anchor_transport_label
                    if is_train:
                        d1['transportation']['details'] = f"{train_name} ({train_class}) - {preferences.get('starting_location','')} to {preferences['destination']}"
                    else:
                        d1['transportation']['details'] = f"{flight_airline} {flight_number} - {d1['transportation'].get('details', '')}"
                for act in d1.get('activities', []):
                    if not isinstance(act, dict):
                        continue
                    kw = anchor_transport_label
                    if kw in act.get('activity', '').lower() or 'depart' in act.get('activity', '').lower():
                        act['cost'] = anchor_transport_price

                # Last day: always force return transport to match outbound
                if len(days) > 1:
                    dl = itinerary[days[-1]]
                    if not isinstance(dl.get('transportation'), dict):
                        dl['transportation'] = {}
                    dl['transportation']['cost'] = anchor_transport_price
                    dl['transportation']['mode'] = anchor_transport_label
                    if is_train:
                        dl['transportation']['details'] = f"{train_name} ({train_class}) - {preferences['destination']} to {preferences.get('starting_location','')}"
                    else:
                        dl['transportation']['details'] = f"Return {flight_airline} {flight_number} - {preferences['destination']} to {preferences.get('starting_location','')}"

        if hotel_price_per_night > 0:
            for day_key, day_data in itinerary.items():
                if isinstance(day_data, dict) and 'accommodation' in day_data and isinstance(day_data['accommodation'], dict):
                    day_data['accommodation']['cost'] = hotel_price_per_night
                    day_data['accommodation']['name'] = hotel_name or day_data['accommodation'].get('name', 'Hotel')

        # Meals and per-person activities come back from the AI as a single person's
        # cost regardless of what the prompt asked - enforce the group scaling here
        # rather than trust the AI to have done the multiplication itself. Age-weighted
        # (fare_units), not raw headcount, so child/senior discounts apply here too.
        _scale_per_person_costs(itinerary, fare_units)

        # Recalculate per-day totals AND the top-level cost_breakdown/total_cost from
        # the same pass over the (now anchor-corrected) itinerary, so the two can never
        # drift apart the way AI-authored daily_total/cumulative_total can.
        itinerary = plan_data.get('itinerary', {})
        day_keys_sorted = sorted(itinerary.keys())

        real_transport = 0
        real_accommodation = 0
        real_food = 0
        real_activities = 0
        running_cumulative = 0

        for day_key in day_keys_sorted:
            day_data = itinerary[day_key]
            if not isinstance(day_data, dict):
                day_data = {}
                itinerary[day_key] = day_data

            t = day_data.get('transportation', {})
            day_transport = t.get('cost', 0) if isinstance(t, dict) else 0

            a = day_data.get('accommodation', {})
            day_accommodation = a.get('cost', 0) if isinstance(a, dict) else 0

            day_food = sum(meal.get('cost', 0) for meal in day_data.get('meals', []) if isinstance(meal, dict))
            day_activities = sum(act.get('cost', 0) for act in day_data.get('activities', []) if isinstance(act, dict))

            day_fixed = day_transport + day_accommodation
            day_variable = day_food + day_activities

            day_data['fixed_costs'] = day_fixed
            day_data['variable_costs'] = day_variable
            day_data['daily_total'] = day_fixed + day_variable

            running_cumulative += day_data['daily_total']
            day_data['cumulative_total'] = running_cumulative

            real_transport += day_transport
            real_accommodation += day_accommodation
            real_food += day_food
            real_activities += day_activities

        plan_data['cost_breakdown'] = {
            'transportation': real_transport,
            'accommodation': real_accommodation,
            'food': real_food,
            'activities': real_activities,
            'miscellaneous': 0,
        }
        plan_data['total_cost'] = running_cumulative
        logger.info(f"{plan_type}: day_1 transport cost AFTER fix = {plan_data.get('itinerary', {}).get('day_1', {}).get('transportation', {}).get('cost', 'N/A')}")
        logger.info(f"{plan_type}: recalculated total = {plan_data['total_cost']}")

        # Force plan_type rather than trust the AI echoed it correctly - the
        # regenerate-single-tier endpoint identifies/replaces a plan in the
        # saved trip by this field, so it must always match what was asked for.
        plan_data['plan_type'] = plan_type
        plan_data['status'] = 'ready'
        plan_data['anchor_pricing'] = anchor
        plan_data.setdefault('currency', currency)
        plan_data.setdefault('currency_symbol', currency_symbol)
        if hotel_limited_inventory:
            plan_data['hotel_inventory_note'] = (
                "Limited hotel options are available for this destination - "
                "Budget/Premium/Luxury tiers may share the same or similarly priced hotel."
            )
        if is_train:
            plan_data['train_placeholder_pricing'] = True
        return plan_data

      except Exception as e:
            last_error = e
            logger.warning(f"Attempt {attempt + 1}/{max_attempts} failed for {plan_type} plan: {e}")

    # All attempts genuinely failed - surface this as a distinct failure state
    # rather than a "successful" zero-cost plan. The zero-cost shape used to be
    # indistinguishable from a real (if oddly priced) plan, so it got persisted
    # and shown to the user as if generation had succeeded.
    logger.error(f"All {max_attempts} attempts failed for {plan_type} plan: {last_error}")
    return {
        "plan_type": plan_type,
        "status": "failed",
        "currency": currency,
        "currency_symbol": currency_symbol,
        "itinerary": {},
        "cost_breakdown": {"transportation": 0, "accommodation": 0, "food": 0, "activities": 0, "miscellaneous": 0},
        "total_cost": 0,
        "highlights": [],
        "budget_tips": [],
        "generation_failed": True,
        "error": f"{plan_type} plan generation failed, please try again.",
        # The anchor fetch (Step 1) runs before the retry loop and never
        # raises out of this function, so it's always available here too -
        # a later regenerate call can reuse it even after a failed attempt.
        "anchor_pricing": anchor,
    }


@api_router.get("/trips")
async def get_user_trips(request: Request):
    user = await get_current_user(request)
    
    trips = await db.trips.find(
        {"user_id": user.user_id},
        {"_id": 0}
    ).sort("created_at", -1).to_list(100)
    
    return {"trips": trips}


@api_router.get("/trips/quota-status")
async def get_trip_quota_status(request: Request):
    """Lets the trip planner show remaining free generations before the
    user hits the wall, rather than only surfacing it as an error."""
    user = await get_current_user(request)
    is_premium = await is_user_premium(user.user_id)
    if is_premium:
        return {"is_premium": True, "used": 0, "limit": None, "remaining": None}
    status = await quota_service.get_quota_status(db, user.user_id)
    return {"is_premium": False, **status}


@api_router.get("/trips/{trip_id}")
async def get_trip(trip_id: str, request: Request):
    user = await get_current_user(request)
    
    trip = await db.trips.find_one(
        {"trip_id": trip_id, "user_id": user.user_id},
        {"_id": 0}
    )
    
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    
    return trip

@api_router.delete("/trips/{trip_id}")
async def delete_trip(trip_id: str, request: Request):
    user = await get_current_user(request)
    
    result = await db.trips.delete_one(
        {"trip_id": trip_id, "user_id": user.user_id}
    )
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Trip not found")
    
    return {"message": "Trip deleted successfully"}


def _day_sort_key(day_key: str):
    # "day_2" before "day_10" - a plain string sort would put day_10 first.
    try:
        return (0, int(day_key.rsplit("_", 1)[-1]))
    except (ValueError, IndexError):
        return (1, day_key)


def build_trip_context(trip: dict, tier: Optional[str] = None) -> str:
    """Compact plain-text summary of a trip doc for the chat system prompt.

    trip.plans holds three parallel tiers (Budget/Premium/Luxury). `tier`
    identifies which one is currently on screen (e.g. the tab selected on
    TripResultsPage) and drives both the itinerary summarized here and the
    "Budget: X" label, so the two never contradict each other. If `tier`
    is omitted or doesn't match any generated plan, falls back to the
    trip's originally-requested preferences.budget_level, then to any tier
    that has one generated. destination/dates/travelers are trip-level
    (from preferences) and don't vary by tier. Each day's transportation
    line (flights, transfers) is included alongside its activities, so
    logistics questions ("how do I get from the airport to the hotel")
    can be answered from what's already booked instead of the model
    reaching for general knowledge. Only populated fields are included -
    nothing prints as "None" - and the itinerary digest is capped at a
    handful of days so a long trip can't balloon the prompt.

    Example: build_trip_context({"preferences": {"destination": "Goa",
    "departure_date": "2026-08-10", "return_date": "2026-08-14",
    "adults": 2, "budget_level": "Budget"}, "plans": [{"plan_type": "Budget",
    "itinerary": {"day_1": {"transportation": {"details": "Flight to Goa"},
    "activities": [{"activity": "Arrival"}]}}}]}, tier="Budget")
    -> "Trip: Goa | Dates: 2026-08-10 to 2026-08-14 | Travelers: 2 adults |
    Budget: Budget | Itinerary so far (Budget, 1 day(s)): Day 1 - Transport:
    Flight to Goa; Arrival"
    """
    prefs = trip.get("preferences") or {}
    parts = []

    destination = prefs.get("destination")
    if destination:
        parts.append(f"Trip: {destination}")

    departure_date = prefs.get("departure_date")
    return_date = prefs.get("return_date")
    if departure_date and return_date:
        parts.append(f"Dates: {departure_date} to {return_date}")
    elif departure_date:
        parts.append(f"Dates: from {departure_date}")

    traveler_bits = [
        f"{prefs[key]} {label}"
        for key, label in (("adults", "adults"), ("children", "children"), ("seniors", "seniors"))
        if prefs.get(key)
    ]
    if traveler_bits:
        parts.append(f"Travelers: {', '.join(traveler_bits)}")

    plans = trip.get("plans") or []
    target_tier = tier or prefs.get("budget_level")
    chosen = next((p for p in plans if p.get("plan_type") == target_tier and p.get("itinerary")), None)
    if not chosen:
        chosen = next((p for p in plans if p.get("itinerary")), None)

    budget_level = chosen.get("plan_type") if chosen else prefs.get("budget_level")
    if budget_level:
        parts.append(f"Budget: {budget_level}")

    if chosen:
        itinerary = chosen.get("itinerary") or {}
        day_keys = sorted(itinerary.keys(), key=_day_sort_key)
        MAX_DAYS_SHOWN = 6
        day_summaries = []
        for day_key in day_keys[:MAX_DAYS_SHOWN]:
            day = itinerary.get(day_key) or {}
            bits = []
            # Transport (flights/transfers already booked as part of this
            # day) goes first so the model sees it before activities - it's
            # the detail logistics questions ("how do I get from the
            # airport to the hotel") actually need, and it was previously
            # dropped from this summary entirely.
            transport_details = (day.get("transportation") or {}).get("details")
            if transport_details:
                bits.append(f"Transport: {transport_details}")
            activities = day.get("activities") or []
            themes = [a["activity"] for a in activities[:2] if a.get("activity")]
            if themes:
                bits.append(" + ".join(themes))
            label = day_key.replace("_", " ").capitalize()
            day_summaries.append(f"{label} - {'; '.join(bits)}" if bits else label)
        itinerary_line = "; ".join(day_summaries)
        if len(day_keys) > MAX_DAYS_SHOWN:
            itinerary_line += f"; plus {len(day_keys) - MAX_DAYS_SHOWN} more day(s)"
        parts.append(f"Itinerary so far ({chosen.get('plan_type')}, {len(day_keys)} day(s)): {itinerary_line}")
    else:
        parts.append("No itinerary planned yet")

    return " | ".join(parts)


def _sse_data(text: str) -> str:
    """Encode `text` as a spec-compliant SSE data event.

    A naive f"data: {text}\\n\\n" breaks the moment `text` contains an
    embedded newline (e.g. a paragraph break within a single Gemini
    stream chunk): per the SSE spec, every line of a multi-line data
    payload needs its own "data:" prefix, or a line-by-line client
    parser (like the one in TripResultsPage.jsx) silently drops any
    continuation line that lacks the prefix - the response looks
    truncated in the UI even though the full text was sent and saved.
    """
    return "".join(f"data: {line}\n" for line in text.split("\n")) + "\n"


# AI Assistant Chat
@api_router.post("/chat/stream")
@limiter.limit("15/minute")  # per-IP - a live back-and-forth chat is bursty by nature
@limiter.limit("15/minute", key_func=_session_token_key)  # per-authenticated-user
async def chat_stream(chat_msg: ChatMessage, request: Request):
    user = await get_current_user(request)

    # Chat-history trip-ownership guard: prevents one user from reading or
    # polluting another user's chat_sessions by passing an arbitrary trip_id.
    # Fetches the full doc (not just _id) so it can be reused below for trip
    # context - avoids a second identical query.
    trip = None
    if chat_msg.trip_id:
        trip = await db.trips.find_one(
            {"trip_id": chat_msg.trip_id, "user_id": user.user_id},
            {"_id": 0}
        )
        if not trip:
            raise HTTPException(status_code=403, detail="Forbidden")

    system_message = "You are a helpful AI travel assistant for EYV (Enjoy Your Vacation). Help users with travel planning, recommendations, itinerary changes, and travel-related questions. Be friendly, knowledgeable, and concise."

    if trip:
        trip_context = build_trip_context(trip, chat_msg.selected_tier)
        system_message += (
            f"\n\nYou are a travel assistant helping with the following trip:\n{trip_context}"
            f"\n\nUse this context to answer questions about the trip. If the user asks something "
            f"unrelated to this trip, answer normally. For logistics questions (airport transfers, "
            f"travel times, getting between locations), check this trip's own transportation and "
            f"itinerary data first - the user may already have a flight or transfer booked that "
            f"answers the question - and only fall back to general travel knowledge if the trip "
            f"data doesn't cover it."
        )

    history = await chat_service.get_recent_messages(db, user.user_id, chat_msg.trip_id, limit=20)
    gemini_contents = [
        {"role": msg["role"], "parts": [{"text": msg["content"]}]} for msg in history
    ]
    gemini_contents.append({"role": "user", "parts": [{"text": chat_msg.message}]})

    async def event_generator():
        full_response = ""
        try:
            stream = await gemini_client.aio.models.generate_content_stream(
                model=GEMINI_MODEL,
                contents=gemini_contents,
                config=genai_types.GenerateContentConfig(
                    system_instruction=system_message,
                ),
            )
            await usage_service.log_usage(db, "gemini", user_id=user.user_id, meta={"context": "chat_stream"})

            async for chunk in stream:
                if chunk.text:
                    full_response += chunk.text
                    yield _sse_data(chunk.text)
            await chat_service.append_exchange(db, user.user_id, chat_msg.trip_id, chat_msg.message, full_response)
            yield _sse_data("[DONE]")
        except Exception as e:
            logger.error(f"Chat stream error: {e}")
            yield _sse_data(f"Error: {str(e)}")
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive"
        }
    )

@api_router.get("/chat/{trip_id}")
async def get_chat_history(trip_id: str, request: Request):
    """Chat history for a (user, trip) pair. trip_id == "none" means general
    chat with no trip attached (stored as trip_id = null)."""
    user = await get_current_user(request)
    resolved_trip_id = None if trip_id == "none" else trip_id

    if resolved_trip_id:
        owned_trip = await db.trips.find_one(
            {"trip_id": resolved_trip_id, "user_id": user.user_id},
            {"_id": 1}
        )
        if not owned_trip:
            raise HTTPException(status_code=403, detail="Forbidden")

    messages = await chat_service.get_all_messages(db, user.user_id, resolved_trip_id)
    return {
        "messages": [
            {"role": m["role"], "content": m["content"], "timestamp": m["timestamp"].isoformat()}
            for m in messages
        ]
    }

@api_router.get("/")
async def root():
    return {"message": "EYV API - Enjoy Your Vacation"}


# ==================== Booking Search Endpoints ====================

class FlightSearchRequest(BaseModel):
    origin: str
    destination: str
    departure_date: str
    return_date: Optional[str] = None
    travelers: int = 1


class HotelSearchRequest(BaseModel):
    destination: str
    check_in: str
    check_out: str
    travelers: int = 1


# Keys that carry a price/amount. Rejected outright on BookingRequest.item_data so
# it's structurally impossible for a client to smuggle a price into a booking -
# the server always determines price by looking up item_id in price_cache.
_FORBIDDEN_ITEM_DATA_KEYS = {
    "price", "amount", "total_amount", "total_price",
    "unit_amount", "unit_price", "cost", "fare",
}


class BookingRequest(BaseModel):
    booking_type: str  # 'flight' or 'hotel'
    item_id: str  # price_cache key returned by /search/flights or /search/hotels
    item_data: Dict[str, Any] = Field(default_factory=dict)  # display-only fields, no price
    trip_id: Optional[str] = None
    traveler_details: Optional[Dict[str, Any]] = None

    @field_validator("item_data")
    @classmethod
    def _reject_price_fields(cls, v):
        found = _FORBIDDEN_ITEM_DATA_KEYS & v.keys()
        if found:
            raise ValueError(
                f"item_data must not contain price fields ({', '.join(sorted(found))}); "
                "price is always determined server-side from item_id"
            )
        return v


@api_router.post("/search/flights")
async def search_flights_endpoint(req: FlightSearchRequest, request: Request):
    user = await get_current_user(request)
    # Try Duffel (real data) first, fall back to mock
    flights = await duffel_service.search_flights(
        req.origin, req.destination, req.departure_date, req.return_date, req.travelers
    )
    await usage_service.log_usage(db, "duffel", user_id=user.user_id, meta={"context": "search_flights_endpoint"})
    provider = "ignav"
    if not flights:
        logger.warning("Duffel returned no flights, falling back to mock data")
        flights = amadeus_service._generate_mock_flights(
            req.origin, req.destination, req.departure_date,
            req.return_date or req.departure_date, req.travelers
        )
        provider = "mock"
    # Sort: cheapest first
    flights = sorted(flights, key=lambda f: f["price"]["total"])
    # Cache the authoritative price per result and stamp an item_id - the
    # client only ever gets to reference that id back, never the price itself.
    await price_cache_service.cache_search_results(
        db, flights, "flight", provider,
        {
            "origin": req.origin, "destination": req.destination,
            "departure_date": req.departure_date, "return_date": req.return_date,
            "travelers": req.travelers,
        },
    )
    return {"flights": flights, "count": len(flights)}

class TrainSearchRequest(BaseModel):
    origin: str
    destination: str
    departure_date: str
    travelers: int = 1

@api_router.post("/search/trains")
async def search_trains_endpoint(req: TrainSearchRequest, request: Request):
    await get_current_user(request)
    # Live train API not yet integrated. Return empty list with honest message.
    # Frontend should show "Train data unavailable for this route" when count == 0.
    return {
        "trains": [],
        "count": 0,
        "message": "Live train data is not available for this route. Please check IRCTC or Rome2rio for train options."
    }



@api_router.post("/search/hotels")
async def search_hotels_endpoint(req: HotelSearchRequest, request: Request):
    user = await get_current_user(request)
    # Try SerpApi (real data) first, fall back to mock
    hotels = await serpapi_hotels_service.search_hotels(
        req.destination, req.check_in, req.check_out, req.travelers, currency="INR"
    )
    await usage_service.log_usage(db, "serpapi", user_id=user.user_id, meta={"context": "search_hotels_endpoint"})
    provider = "serpapi"
    if not hotels:
        logger.warning("SerpApi returned no hotels, falling back to mock data")
        hotels = amadeus_service._generate_mock_hotels(
            req.destination, req.check_in, req.check_out, req.travelers
        )
        provider = "mock"
    # Enforce tier ordering: always sort by price ascending
    hotels = sorted(hotels, key=lambda h: h["price"]["per_night"])
    # Cache the authoritative price per result and stamp an item_id - the
    # client only ever gets to reference that id back, never the price itself.
    await price_cache_service.cache_search_results(
        db, hotels, "hotel", provider,
        {
            "destination": req.destination, "check_in": req.check_in,
            "check_out": req.check_out, "travelers": req.travelers,
        },
    )
    return {"hotels": hotels, "count": len(hotels)}


@api_router.get("/destinations/{destination}/coords")
async def get_destination_coords_endpoint(destination: str, request: Request):
    await get_current_user(request)
    coords = await locations_service.geocode_destination(destination)
    if not coords:
        # Final fallback to amadeus mock coords
        coords = amadeus_service.get_destination_coords(destination)
    return coords


@api_router.get("/locations/autocomplete")
@limiter.limit("25/minute")  # per-IP - generous enough for live typeahead, still bounded
async def locations_autocomplete(request: Request, q: str = Query("", min_length=0)):
    """Autocomplete location suggestions. Returns popular destinations matching query.
    Public endpoint - used on landing page as well."""
    suggestions = locations_service.search_locations(q, limit=8)
    return {"suggestions": suggestions}


# ==================== Booking Management ====================

@api_router.post("/bookings")
async def create_booking(req: BookingRequest, request: Request):
    """Create a booking. Price is never trusted from the client - it's resolved
    server-side from price_cache (set at search time) by req.item_id."""
    user = await get_current_user(request)

    resolved = await price_cache_service.resolve_price(db, req.item_id)
    if not resolved:
        raise HTTPException(
            status_code=410,
            detail="This offer has expired. Please search again.",
        )

    booking_id = f"BK{uuid.uuid4().hex[:10].upper()}"
    confirmation_code = f"EYV-{uuid.uuid4().hex[:8].upper()}"

    booking_doc = {
        "booking_id": booking_id,
        "confirmation_code": confirmation_code,
        "user_id": user.user_id,
        "trip_id": req.trip_id,
        "booking_type": req.booking_type,
        "item_data": req.item_data,
        "traveler_details": req.traveler_details or {},
        "status": "confirmed",
        "payment_status": "mock_paid",
        "total_amount": resolved["price"],
        "currency": resolved["currency"],
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    await db.bookings.insert_one(booking_doc)
    booking_doc.pop("_id", None)
    return booking_doc


@api_router.get("/bookings")
async def list_bookings(request: Request):
    user = await get_current_user(request)
    bookings = await db.bookings.find(
        {"user_id": user.user_id},
        {"_id": 0}
    ).sort("created_at", -1).to_list(100)
    return {"bookings": bookings}


@api_router.get("/bookings/{booking_id}")
async def get_booking(booking_id: str, request: Request):
    user = await get_current_user(request)
    booking = await db.bookings.find_one(
        {"booking_id": booking_id, "user_id": user.user_id},
        {"_id": 0}
    )
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    return booking


@api_router.delete("/bookings/{booking_id}")
async def cancel_booking(booking_id: str, request: Request):
    user = await get_current_user(request)
    result = await db.bookings.update_one(
        {"booking_id": booking_id, "user_id": user.user_id},
        {"$set": {"status": "cancelled", "cancelled_at": datetime.now(timezone.utc).isoformat()}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Booking not found")
    return {"message": "Booking cancelled successfully"}


# ==================== Travel Wallet (File Storage) ====================

class WalletItem(BaseModel):
    item_id: str
    user_id: str
    file_path: str
    original_filename: str
    content_type: str
    size: int
    category: str  # 'boarding_pass', 'ticket', 'voucher', 'document'
    title: str
    description: Optional[str] = None
    trip_id: Optional[str] = None
    created_at: str


@api_router.post("/wallet/upload")
async def upload_wallet_item(
    request: Request,
    file: UploadFile = File(...),
    category: str = "document",
    title: str = "",
    description: str = "",
    trip_id: Optional[str] = None
):
    user = await get_current_user(request)
    
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "bin"
    if ext not in storage_service.MIME_TYPES:
        ext = "bin"
    
    content_type = file.content_type or storage_service.MIME_TYPES.get(ext, "application/octet-stream")
    storage_path = storage_service.build_path(user.user_id, ext)
    data = await file.read()
    
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 10MB)")
    
    try:
        result = await storage_service.put_object(storage_path, data, content_type)
    except Exception as e:
        logger.error(f"Storage upload error: {e}")
        raise HTTPException(status_code=500, detail="File upload failed")
    
    item_id = f"wallet_{uuid.uuid4().hex[:12]}"
    item_doc = {
        "item_id": item_id,
        "user_id": user.user_id,
        "file_path": result["path"],
        "original_filename": file.filename,
        "content_type": content_type,
        "size": result.get("size", len(data)),
        "category": category,
        "title": title or file.filename,
        "description": description,
        "trip_id": trip_id,
        "is_deleted": False,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.wallet_items.insert_one(item_doc)
    item_doc.pop("_id", None)
    return item_doc


@api_router.get("/wallet")
async def list_wallet_items(request: Request, category: Optional[str] = None, trip_id: Optional[str] = None):
    user = await get_current_user(request)
    
    query = {"user_id": user.user_id, "is_deleted": False}
    if category:
        query["category"] = category
    if trip_id:
        query["trip_id"] = trip_id
    
    items = await db.wallet_items.find(query, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"items": items}


@api_router.get("/wallet/{item_id}/download")
async def download_wallet_item(item_id: str, request: Request, auth: Optional[str] = Query(None)):
    # Support both cookie auth and query param auth (for direct <img> tag access)
    user = None
    
    if auth:
        # Validate session_token from query param
        session_doc = await db.user_sessions.find_one(
            {"session_token": auth}, {"_id": 0}
        )
        if session_doc:
            user_doc = await db.users.find_one({"user_id": session_doc["user_id"]}, {"_id": 0})
            if user_doc:
                if isinstance(user_doc.get("created_at"), str):
                    user_doc["created_at"] = datetime.fromisoformat(user_doc["created_at"])
                user = User(**user_doc)
    
    if not user:
        user = await get_current_user(request)
    
    item = await db.wallet_items.find_one(
        {"item_id": item_id, "user_id": user.user_id, "is_deleted": False},
        {"_id": 0}
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    try:
        data, content_type = await storage_service.get_object(item["file_path"])
    except Exception as e:
        logger.error(f"Storage download error: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve file")
    
    return Response(
        content=data,
        media_type=item.get("content_type", content_type),
        headers={"Content-Disposition": f'inline; filename="{item["original_filename"]}"'}
    )


@api_router.delete("/wallet/{item_id}")
async def delete_wallet_item(item_id: str, request: Request):
    user = await get_current_user(request)
    result = await db.wallet_items.update_one(
        {"item_id": item_id, "user_id": user.user_id},
        {"$set": {"is_deleted": True, "deleted_at": datetime.now(timezone.utc).isoformat()}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"message": "Item deleted successfully"}


# ==================== Travel Rewards System ====================

@api_router.get("/rewards")
async def get_rewards(request: Request):
    user = await get_current_user(request)
    return await rewards_service.get_user_rewards_summary(db, user.user_id)


class RedeemPointsRequest(BaseModel):
    points: int
    reference_id: Optional[str] = None


@api_router.post("/rewards/redeem")
async def redeem_rewards(req: RedeemPointsRequest, request: Request):
    user = await get_current_user(request)
    try:
        result = await rewards_service.redeem_points(
            db, user.user_id, req.points, req.reference_id, "Discount applied to booking"
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==================== Stripe Payments ====================

# Fixed packages - amounts defined ONLY on backend. USD is the canonical
# base price; customers are charged in INR, converted at read time via the
# app's live FX rate (services.ignav_service._to_inr) rather than a second
# hardcoded INR number that would drift out of sync with the rate used
# everywhere else. See _get_premium_plans().
_PREMIUM_PLANS_USD = {
    "monthly": {"name": "EYV Premium Monthly", "amount_usd": 9.99, "duration_days": 30},
    "yearly": {"name": "EYV Premium Yearly", "amount_usd": 99.00, "duration_days": 365},
}


async def _get_premium_plans() -> Dict[str, Dict[str, Any]]:
    """Premium plans priced in INR, converted from the canonical USD base
    above using the app's live FX rate - no Stripe Price objects are
    involved anywhere in this app (premium and bookings both already use
    dynamic price_data), so there's nothing on the Stripe side to keep in
    sync; this is the sole source of truth for the charged amount."""
    await duffel_service._refresh_rates_if_stale()
    return {
        package_id: {
            "name": plan["name"],
            "amount": duffel_service._to_inr(plan["amount_usd"], "USD"),
            "currency": "inr",
            "duration_days": plan["duration_days"],
        }
        for package_id, plan in _PREMIUM_PLANS_USD.items()
    }


class CreateCheckoutRequest(BaseModel):
    package_id: Optional[str] = None  # For premium subscriptions
    booking_id: Optional[str] = None  # For booking payments
    origin_url: str
    use_points: int = 0


class CheckoutStatusRequest(BaseModel):
    session_id: str


def _ensure_stripe_configured():
    if not stripe.api_key:
        raise HTTPException(status_code=500, detail="Stripe not configured")


@api_router.post("/payments/checkout")
async def create_checkout(req: CreateCheckoutRequest, request: Request):
    user = await get_current_user(request)
    
    # Determine amount based on backend logic
    if req.package_id:
        # Premium subscription
        premium_plans = await _get_premium_plans()
        if req.package_id not in premium_plans:
            raise HTTPException(status_code=400, detail="Invalid package")
        plan = premium_plans[req.package_id]
        amount = plan['amount']
        currency = plan['currency']
        description = plan['name']
        payment_type = 'subscription'
        metadata = {
            'user_id': user.user_id,
            'package_id': req.package_id,
            'payment_type': payment_type,
        }
    elif req.booking_id:
        # Booking payment
        booking = await db.bookings.find_one(
            {'booking_id': req.booking_id, 'user_id': user.user_id},
            {'_id': 0}
        )
        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found")
        amount = float(booking['total_amount'])
        currency = booking.get('currency', 'usd').lower()
        description = f"Booking {booking['booking_id']}"
        payment_type = 'booking'
        
        # Apply points discount if requested
        if req.use_points > 0:
            rewards = await rewards_service.get_or_create_rewards(db, user.user_id)
            if rewards['available_points'] < req.use_points:
                raise HTTPException(status_code=400, detail="Insufficient points")
            # POINTS_TO_USD is a USD-denominated canonical point value ("100
            # points = $1") - it must be converted into the booking's own
            # `currency` before being subtracted from `amount`, which is in
            # that same native currency. Reuses the same FX table already
            # live for real Ignav flight-price INR conversion (duffel_service
            # is services.ignav_service under its historical alias) instead
            # of a second, separate hardcoded rate.
            await duffel_service._refresh_rates_if_stale()
            discount_usd = req.use_points * rewards_service.POINTS_TO_USD
            if currency == 'usd':
                discount = discount_usd
            elif currency == 'inr':
                discount = duffel_service._to_inr(discount_usd, 'USD')
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Points redemption is not supported for currency '{currency}'",
                )
            amount = max(0.50, amount - discount)  # Minimum charge $0.50
        
        metadata = {
            'user_id': user.user_id,
            'booking_id': req.booking_id,
            'payment_type': payment_type,
            'points_used': str(req.use_points),
        }
    else:
        raise HTTPException(status_code=400, detail="Must provide package_id or booking_id")
    
    # Build URLs
    origin = req.origin_url.rstrip('/')
    success_url = f"{origin}/payment-success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{origin}/payment-cancel"
    
    _ensure_stripe_configured()
    session = await asyncio.to_thread(
        stripe.checkout.Session.create,
        mode='payment',
        payment_method_types=['card'],
        line_items=[{
            'price_data': {
                'currency': currency,
                'product_data': {'name': description},
                'unit_amount': int(round(amount * 100)),
            },
            'quantity': 1,
        }],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata=metadata,
    )

    # Store transaction
    transaction = {
        'session_id': session.id,
        'user_id': user.user_id,
        'amount': amount,
        'currency': currency,
        'description': description,
        'payment_type': payment_type,
        'metadata': metadata,
        'payment_status': 'pending',
        'status': 'initiated',
        'points_used': req.use_points,
        'created_at': datetime.now(timezone.utc).isoformat(),
    }
    await db.payment_transactions.insert_one(transaction)
    
    return {
        'url': session.url,
        'session_id': session.id,
        'amount': amount,
        'currency': currency,
    }


@api_router.get("/payments/status/{session_id}")
async def get_payment_status(session_id: str, request: Request):
    user = await get_current_user(request)
    
    # Find the transaction
    transaction = await db.payment_transactions.find_one(
        {'session_id': session_id, 'user_id': user.user_id},
        {'_id': 0}
    )
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    # If already processed, return immediately (idempotency)
    if transaction['payment_status'] in ('paid', 'failed', 'expired'):
        return {
            'payment_status': transaction['payment_status'],
            'status': transaction['status'],
            'amount': transaction['amount'],
            'currency': transaction['currency'],
            'metadata': transaction['metadata'],
        }
    
    # Poll Stripe
    _ensure_stripe_configured()
    status_response = await asyncio.to_thread(stripe.checkout.Session.retrieve, session_id)

    # Update transaction (idempotent - only process once)
    if status_response.payment_status == 'paid' and transaction['payment_status'] != 'paid':
        await db.payment_transactions.update_one(
            {'session_id': session_id},
            {'$set': {
                'payment_status': 'paid',
                'status': 'completed',
                'completed_at': datetime.now(timezone.utc).isoformat(),
            }}
        )
        # Trigger post-payment actions
        await _process_successful_payment(transaction)
    elif status_response.status == 'expired':
        await db.payment_transactions.update_one(
            {'session_id': session_id},
            {'$set': {'payment_status': 'expired', 'status': 'expired'}}
        )
    
    return {
        'payment_status': status_response.payment_status,
        'status': status_response.status,
        'amount': status_response.amount_total / 100 if status_response.amount_total else transaction['amount'],
        'currency': status_response.currency or transaction['currency'],
        'metadata': status_response.metadata or transaction['metadata'],
    }


async def _process_successful_payment(transaction: Dict):
    """Process successful payment - subscription or booking."""
    metadata = transaction.get('metadata', {})
    payment_type = metadata.get('payment_type')
    user_id = metadata.get('user_id') or transaction.get('user_id')
    
    if payment_type == 'subscription':
        package_id = metadata.get('package_id')
        premium_plans = await _get_premium_plans()
        plan = premium_plans.get(package_id)
        if plan:
            expires_at = datetime.now(timezone.utc) + timedelta(days=plan['duration_days'])
            await db.users.update_one(
                {'user_id': user_id},
                {'$set': {
                    'premium_status': 'active',
                    'premium_plan': package_id,
                    'premium_expires_at': expires_at.isoformat(),
                    'premium_started_at': datetime.now(timezone.utc).isoformat(),
                }}
            )
            # Award premium signup bonus points
            await rewards_service.award_points(
                db, user_id, 'premium_subscription',
                reference_id=transaction['session_id'],
                description=f"Premium {package_id} subscription bonus"
            )
    
    elif payment_type == 'booking':
        booking_id = metadata.get('booking_id')
        points_used = int(metadata.get('points_used', 0))
        
        # Mark booking as paid
        booking = await db.bookings.find_one({'booking_id': booking_id}, {'_id': 0})
        if booking:
            await db.bookings.update_one(
                {'booking_id': booking_id},
                {'$set': {'payment_status': 'paid', 'paid_at': datetime.now(timezone.utc).isoformat()}}
            )
            
            # Redeem points if used
            if points_used > 0:
                try:
                    await rewards_service.redeem_points(db, user_id, points_used, booking_id, f"Discount on booking {booking_id}")
                except ValueError:
                    pass  # Already validated at checkout
            
            # Award points for the booking
            action = 'booking_flight' if booking.get('booking_type') == 'flight' else 'booking_hotel'
            await rewards_service.award_points(
                db, user_id, action,
                reference_id=booking_id,
                description=f"Earned for {booking.get('booking_type')} booking"
            )


@api_router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events."""
    body = await request.body()
    signature = request.headers.get('Stripe-Signature', '')
    webhook_secret = os.environ.get('STRIPE_WEBHOOK_SECRET')

    try:
        _ensure_stripe_configured()
        if not webhook_secret:
            raise HTTPException(status_code=500, detail="Stripe webhook secret not configured")
        event = stripe.Webhook.construct_event(body, signature, webhook_secret)

        if event['type'] == 'checkout.session.completed':
            session_obj = event['data']['object']
            transaction = await db.payment_transactions.find_one(
                {'session_id': session_obj['id']},
                {'_id': 0}
            )
            if transaction and transaction['payment_status'] != 'paid':
                await db.payment_transactions.update_one(
                    {'session_id': session_obj['id']},
                    {'$set': {
                        'payment_status': 'paid',
                        'status': 'completed',
                        'completed_at': datetime.now(timezone.utc).isoformat(),
                    }}
                )
                await _process_successful_payment(transaction)

        return {"received": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        # Return non-2xx so Stripe retries the webhook
        raise HTTPException(status_code=400, detail=f"Webhook processing failed: {str(e)}")


# ==================== Admin: Usage Summary ====================
# Backup signal for eyeballing provider call volume without waiting on a
# provider dashboard alert - NOT a replacement for actually configuring
# spend/quota alarms in the Gemini and SerpApi consoles (that's dashboard-side
# and still needs to be done manually).

@api_router.get("/admin/usage-summary")
async def get_admin_usage_summary(x_admin_key: Optional[str] = Header(default=None)):
    if not ADMIN_API_KEY or x_admin_key != ADMIN_API_KEY:
        raise HTTPException(status_code=403, detail="Not authorized")
    return await usage_service.get_usage_summary(db)


# ==================== Premium Subscription Status ====================

@api_router.get("/subscription/status")
async def get_subscription_status(request: Request):
    user = await get_current_user(request)
    user_doc = await db.users.find_one(
        {'user_id': user.user_id},
        {'_id': 0, 'premium_status': 1, 'premium_plan': 1, 'premium_expires_at': 1, 'premium_started_at': 1}
    )
    
    premium_status = user_doc.get('premium_status', 'inactive') if user_doc else 'inactive'
    
    # Check expiry
    if premium_status == 'active' and user_doc.get('premium_expires_at'):
        expires_at = user_doc['premium_expires_at']
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            premium_status = 'expired'
            await db.users.update_one(
                {'user_id': user.user_id},
                {'$set': {'premium_status': 'expired'}}
            )
    
    return {
        'is_premium': premium_status == 'active',
        'premium_status': premium_status,
        'premium_plan': user_doc.get('premium_plan') if user_doc else None,
        'premium_expires_at': user_doc.get('premium_expires_at') if user_doc else None,
        'available_plans': await _get_premium_plans(),
    }


@app.on_event("startup")
async def startup_event():
    try:
        storage_service.init_storage()
    except Exception as e:
        logger.warning(f"Storage init failed at startup: {e}")
    try:
        await price_cache_service.ensure_indexes(db)
    except Exception as e:
        logger.warning(f"price_cache index setup failed at startup: {e}")
    try:
        await quota_service.ensure_indexes(db)
    except Exception as e:
        logger.warning(f"quota index setup failed at startup: {e}")
    try:
        await chat_service.ensure_indexes(db)
    except Exception as e:
        logger.warning(f"chat index setup failed at startup: {e}")
    try:
        # Warm the FX rate cache eagerly so the first real request doesn't
        # pay the fetch latency - _refresh_rates_if_stale() also runs lazily
        # from every conversion call site, so this is a nice-to-have, not
        # load-bearing (a failure here just means the first live call does it).
        await duffel_service._refresh_rates_if_stale()
    except Exception as e:
        logger.warning(f"FX rate warm-up failed at startup: {e}")


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
