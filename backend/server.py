from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, UploadFile, File, Header, Query
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, timezone, timedelta
import httpx
import asyncio
from emergentintegrations.llm.chat import LlmChat, UserMessage, TextDelta, StreamDone
from emergentintegrations.payments.stripe.checkout import StripeCheckout, CheckoutSessionRequest
from services import amadeus_service, storage_service, rewards_service, locations_service

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]
EMERGENT_LLM_KEY = os.environ.get('EMERGENT_LLM_KEY')

app = FastAPI()
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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
    num_travelers: int
    adults: int = 1
    children: int = 0
    seniors: int = 0
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

# Auth Routes
@api_router.post("/auth/session")
async def exchange_session(request: SessionExchangeRequest, response: Response):
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
                headers={"X-Session-ID": request.session_id},
                timeout=10.0
            )
            
            if resp.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid session ID")
            
            session_data = resp.json()
        
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
        
        session_token = session_data["session_token"]
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
    
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Authentication service timeout")
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

# Trip Planning Routes
@api_router.post("/trips/generate")
async def generate_trip_plans(preferences: TripPreferences, request: Request):
    user = await get_current_user(request)
    
    trip_id = f"trip_{uuid.uuid4().hex[:12]}"
    
    # Store preferences
    preferences_dict = preferences.model_dump()
    
    # Generate 3 plans in parallel using AI
    plan_tasks = [
        generate_single_plan(preferences_dict, plan_type, trip_id, user.user_id)
        for plan_type in ["Budget", "Premium", "Luxury"]
    ]
    plans = await asyncio.gather(*plan_tasks)
    
    # Save trip
    saved_trip = {
        "trip_id": trip_id,
        "user_id": user.user_id,
        "trip_name": f"{preferences.destination} Trip",
        "preferences": preferences_dict,
        "plans": plans,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.trips.insert_one(saved_trip)
    
    return {"trip_id": trip_id, "plans": plans}

async def generate_single_plan(preferences: Dict, plan_type: str, trip_id: str, user_id: str) -> Dict:
    """Generate a single vacation plan using AI"""
    
    currency = preferences.get('currency', 'INR')
    currency_symbol = '₹' if currency == 'INR' else '$'
    budget_mode = preferences.get('budget_mode', True)
    
    budget_instructions = ""
    if budget_mode:
        budget_instructions = """
**BUDGET OPTIMIZATION RULES (CRITICAL):**
- Prioritize the MINIMUM possible cost for every recommendation
- Suggest budget hostels, dormitories, homestays, or guesthouses (₹500-₹1500/night)
- Recommend public transport: state buses, sleeper trains (3AC/SL), local metro, shared autos
- Avoid private taxis unless absolutely necessary; prefer shared rides
- Suggest free attractions (temples, beaches, parks, viewpoints) and skip expensive entry fees where possible
- Recommend local street food and dhabas for meals (₹100-₹250 per meal)
- For flights: only when train/bus would take 24+ hours, otherwise prefer rail
- Cap daily expenditure to absolute minimum - aim for ₹2000-₹3500 per person/day
- Clearly mark free activities with cost: 0
- Distinguish FIXED costs (travel, accommodation) vs VARIABLE costs (food, activities)
"""
    
    prompt = f"""You are an expert Indian travel planner specialized in BUDGET-CONSCIOUS itineraries. Create a detailed {plan_type} vacation plan based on these preferences:

Destination: {preferences['destination']}
Starting Location: {preferences['starting_location']}
Dates: {preferences['departure_date']} to {preferences['return_date']}
Travelers: {preferences['num_travelers']} ({preferences['adults']} adults, {preferences['children']} children, {preferences['seniors']} seniors)
Transportation: {preferences['transportation']}
Accommodation Preferences: {', '.join(preferences['accommodation']) if preferences['accommodation'] else 'Budget options'}
Interests: {', '.join(preferences['interests']) if preferences['interests'] else 'General sightseeing'}
Trip Type: {preferences['trip_type']}
Currency: {currency} ({currency_symbol})
{f"Dietary Preferences: {preferences['dietary_preferences']}" if preferences.get('dietary_preferences') else ""}
{f"Accessibility: {preferences['accessibility_requirements']}" if preferences.get('accessibility_requirements') else ""}

{budget_instructions}

Create a complete {plan_type} plan with:
1. Day-wise detailed itinerary (activities, timings, locations)
2. Transportation details (mention exact mode: train, bus, flight)
3. Accommodation recommendations (name + type + cost per night)
4. Restaurant suggestions for each day (local + budget-friendly)
5. Estimated costs breakdown - ALL VALUES IN {currency}
6. Cumulative trip expenditure up to each day
7. Distinguish FIXED costs (travel, stay) from VARIABLE costs (food, activities)

Return the response in this exact JSON format (NO markdown, just JSON):
{{
  "plan_type": "{plan_type}",
  "currency": "{currency}",
  "itinerary": {{
    "day_1": {{
      "date": "YYYY-MM-DD",
      "activities": [
        {{"time": "09:00", "activity": "description", "location": "place name", "cost": 0, "category": "free/sightseeing/transport"}}
      ],
      "accommodation": {{"name": "specific hotel/hostel name", "type": "hostel/guesthouse/homestay", "cost": 800, "location": "area"}},
      "meals": [
        {{"time": "breakfast", "restaurant": "name or local eatery", "cuisine": "type", "cost": 150}}
      ],
      "transportation": {{"mode": "train/bus/flight", "details": "route info", "cost": 1200}},
      "daily_total": 2500,
      "cumulative_total": 2500,
      "fixed_costs": 2000,
      "variable_costs": 500
    }}
  }},
  "cost_breakdown": {{
    "transportation": 0,
    "accommodation": 0,
    "food": 0,
    "activities": 0,
    "miscellaneous": 0
  }},
  "total_cost": 0,
  "currency_symbol": "{currency_symbol}",
  "highlights": ["highlight 1", "highlight 2", "highlight 3"],
  "budget_tips": ["tip 1", "tip 2", "tip 3"]
}}

Provide REALISTIC Indian market prices in {currency}. Be specific with restaurant/hotel names. Generate one day for each day of the trip duration."""
    
    try:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"{trip_id}_{plan_type}",
            system_message=f"You are an expert Indian travel planner. Always provide detailed, practical, and budget-conscious travel plans in valid JSON format with all costs in {currency}."
        ).with_model("openai", "gpt-4o")
        
        full_response = ""
        async for event in chat.stream_message(UserMessage(text=prompt)):
            if isinstance(event, TextDelta):
                full_response += event.content
            elif isinstance(event, StreamDone):
                break
        
        # Parse JSON from response
        import json
        # Extract JSON from response (in case there's extra text)
        start_idx = full_response.find('{')
        end_idx = full_response.rfind('}') + 1
        if start_idx != -1 and end_idx > start_idx:
            json_str = full_response[start_idx:end_idx]
            plan_data = json.loads(json_str)
        else:
            # Fallback structure if parsing fails
            plan_data = {
                "plan_type": plan_type,
                "currency": currency,
                "currency_symbol": currency_symbol,
                "itinerary": {},
                "cost_breakdown": {
                    "transportation": 0,
                    "accommodation": 0,
                    "food": 0,
                    "activities": 0,
                    "miscellaneous": 0
                },
                "total_cost": 0,
                "highlights": [],
                "budget_tips": []
            }
        
        # Ensure currency fields exist
        plan_data.setdefault('currency', currency)
        plan_data.setdefault('currency_symbol', currency_symbol)
        
        return plan_data
    
    except Exception as e:
        logger.error(f"Error generating {plan_type} plan: {e}")
        # Return fallback plan
        return {
            "plan_type": plan_type,
            "currency": currency,
            "currency_symbol": currency_symbol,
            "itinerary": {},
            "cost_breakdown": {
                "transportation": 0,
                "accommodation": 0,
                "food": 0,
                "activities": 0,
                "miscellaneous": 0
            },
            "total_cost": 0,
            "highlights": [],
            "budget_tips": [],
            "error": str(e)
        }

@api_router.get("/trips")
async def get_user_trips(request: Request):
    user = await get_current_user(request)
    
    trips = await db.trips.find(
        {"user_id": user.user_id},
        {"_id": 0}
    ).sort("created_at", -1).to_list(100)
    
    return {"trips": trips}

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

# AI Assistant Chat
@api_router.post("/chat/stream")
async def chat_stream(chat_msg: ChatMessage, request: Request):
    user = await get_current_user(request)
    
    system_message = "You are a helpful AI travel assistant for EYV (Enjoy Your Vacation). Help users with travel planning, recommendations, itinerary changes, and travel-related questions. Be friendly, knowledgeable, and concise."
    
    if chat_msg.trip_id:
        trip = await db.trips.find_one(
            {"trip_id": chat_msg.trip_id, "user_id": user.user_id},
            {"_id": 0}
        )
        if trip:
            system_message += f"\n\nContext: The user is planning a trip to {trip['preferences']['destination']}. Here are their preferences: {trip['preferences']}"
    
    async def event_generator():
        try:
            chat = LlmChat(
                api_key=EMERGENT_LLM_KEY,
                session_id=f"{user.user_id}_chat",
                system_message=system_message
            ).with_model("openai", "gpt-4o")
            
            async for event in chat.stream_message(UserMessage(text=chat_msg.message)):
                if isinstance(event, TextDelta):
                    yield f"data: {event.content}\n\n"
                elif isinstance(event, StreamDone):
                    yield "data: [DONE]\n\n"
                    break
        except Exception as e:
            logger.error(f"Chat stream error: {e}")
            yield f"data: Error: {str(e)}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive"
        }
    )

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


class BookingRequest(BaseModel):
    booking_type: str  # 'flight' or 'hotel'
    item_id: str
    item_data: Dict[str, Any]
    trip_id: Optional[str] = None
    traveler_details: Optional[Dict[str, Any]] = None


@api_router.post("/search/flights")
async def search_flights_endpoint(req: FlightSearchRequest, request: Request):
    await get_current_user(request)
    flights = await amadeus_service.search_flights(
        req.origin, req.destination, req.departure_date, req.return_date, req.travelers
    )
    return {"flights": flights, "count": len(flights)}


@api_router.post("/search/hotels")
async def search_hotels_endpoint(req: HotelSearchRequest, request: Request):
    await get_current_user(request)
    hotels = await amadeus_service.search_hotels(
        req.destination, req.check_in, req.check_out, req.travelers
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
async def locations_autocomplete(q: str = Query("", min_length=0)):
    """Autocomplete location suggestions. Returns popular destinations matching query.
    Public endpoint - used on landing page as well."""
    suggestions = locations_service.search_locations(q, limit=8)
    return {"suggestions": suggestions}


# ==================== Booking Management ====================

@api_router.post("/bookings")
async def create_booking(req: BookingRequest, request: Request):
    """Create a mock booking. In production, this would call real booking APIs."""
    user = await get_current_user(request)
    
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
        "total_amount": req.item_data.get("price", {}).get("total", 0),
        "currency": req.item_data.get("price", {}).get("currency", "USD"),
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
        result = storage_service.put_object(storage_path, data, content_type)
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
        data, content_type = storage_service.get_object(item["file_path"])
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

# Fixed packages - amounts defined ONLY on backend
PREMIUM_PLANS = {
    "monthly": {"name": "EYV Premium Monthly", "amount": 9.99, "currency": "usd", "duration_days": 30},
    "yearly": {"name": "EYV Premium Yearly", "amount": 99.00, "currency": "usd", "duration_days": 365},
}


class CreateCheckoutRequest(BaseModel):
    package_id: Optional[str] = None  # For premium subscriptions
    booking_id: Optional[str] = None  # For booking payments
    origin_url: str
    use_points: int = 0


class CheckoutStatusRequest(BaseModel):
    session_id: str


def _get_stripe_client(request: Request) -> StripeCheckout:
    api_key = os.environ.get('STRIPE_API_KEY')
    if not api_key:
        raise HTTPException(status_code=500, detail="Stripe not configured")
    host_url = str(request.base_url).rstrip('/')
    webhook_url = f"{host_url}/api/webhook/stripe"
    return StripeCheckout(api_key=api_key, webhook_url=webhook_url)


@api_router.post("/payments/checkout")
async def create_checkout(req: CreateCheckoutRequest, request: Request):
    user = await get_current_user(request)
    
    # Determine amount based on backend logic
    if req.package_id:
        # Premium subscription
        if req.package_id not in PREMIUM_PLANS:
            raise HTTPException(status_code=400, detail="Invalid package")
        plan = PREMIUM_PLANS[req.package_id]
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
            discount = req.use_points * rewards_service.POINTS_TO_USD
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
    
    stripe_client = _get_stripe_client(request)
    checkout_request = CheckoutSessionRequest(
        amount=amount,
        currency=currency,
        success_url=success_url,
        cancel_url=cancel_url,
        metadata=metadata,
    )
    session = await stripe_client.create_checkout_session(checkout_request)
    
    # Store transaction
    transaction = {
        'session_id': session.session_id,
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
        'session_id': session.session_id,
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
    stripe_client = _get_stripe_client(request)
    status_response = await stripe_client.get_checkout_status(session_id)
    
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
        plan = PREMIUM_PLANS.get(package_id)
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
    
    try:
        stripe_client = _get_stripe_client(request)
        webhook_response = await stripe_client.handle_webhook(body, signature)
        
        if webhook_response.event_type == 'checkout.session.completed':
            transaction = await db.payment_transactions.find_one(
                {'session_id': webhook_response.session_id},
                {'_id': 0}
            )
            if transaction and transaction['payment_status'] != 'paid':
                await db.payment_transactions.update_one(
                    {'session_id': webhook_response.session_id},
                    {'$set': {
                        'payment_status': 'paid',
                        'status': 'completed',
                        'completed_at': datetime.now(timezone.utc).isoformat(),
                    }}
                )
                await _process_successful_payment(transaction)
        
        return {"received": True}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        # Return non-2xx so Stripe retries the webhook
        raise HTTPException(status_code=400, detail=f"Webhook processing failed: {str(e)}")


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
        'available_plans': PREMIUM_PLANS,
    }


@app.on_event("startup")
async def startup_event():
    try:
        storage_service.init_storage()
    except Exception as e:
        logger.warning(f"Storage init failed at startup: {e}")


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
