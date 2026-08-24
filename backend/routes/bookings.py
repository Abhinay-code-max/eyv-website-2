"""Booking Management API router (/api/bookings/*, /api/trips/{trip_id}/book/*).

NOTE: /api/trips/* routes are split across routes/trips.py and routes/bookings.py.
Standalone bookings (/api/bookings) and the "Book this Plan" bundled trip booking route
(/api/trips/{trip_id}/book/{plan_type}) live here in routes/bookings.py.
Trip generation, regeneration, quota, get, road-route, and deletion routes live in routes/trips.py.
"""
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from routes.shared import db, get_current_user, TRIP_PLAN_TYPES
from services import price_cache_service, analytics_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["bookings"])

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


def _bookable_line_items(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Identify the real, reservable items in a generated plan tier - flights
    and hotels only, for a "Book this Plan" bundle. Activities/meals/
    shopping are never included: nothing in the AI-authored itinerary
    carries a provider/booking reference, so there's no reliable "bookable"
    signal for them at all (this isn't a heuristic that might miss some -
    none of them are ever bookable, by construction).

    Bookability is judged from anchor_pricing (the real Duffel/Ignav +
    SerpApi fetch done at generation time - see _fetch_anchor_pricing):
      - flight: anchor_pricing.flight_price > 0 AND not is_train AND not
        is_cruise AND not is_road. None of trains, cruises, or road trips
        have any real inventory anywhere in this app (POST /search/trains
        always returns empty; there is no cruise search at all; road trips
        are a geocoded-distance fuel/toll estimate, not a provider quote) -
        all three are computed/hardcoded estimates, not provider quotes -
        see train_placeholder_pricing / cruise_placeholder_pricing /
        road_placeholder_pricing. "type": "train"/"cruise"/"road" are
        deliberately never produced here, though the field is a free
        string so any could be added later without a schema change if
        that ever becomes real.
      - hotel: anchor_pricing.hotel_price_per_night > 0. In both cases, 0
        means the real fetch failed and the AI was told to invent a
        placeholder number instead - not tied to any real fare/rate, so
        not bookable.

    The charged PRICE per item comes from cost_breakdown, not from
    anchor_pricing's raw fields - cost_breakdown.transportation/
    accommodation are the plan's own already-computed, already-displayed
    per-category totals (summed across every day's forced-to-anchor
    transportation/accommodation cost), so this always matches exactly
    what the user already saw on screen rather than re-deriving the same
    per-leg/per-night scaling independently and risking drift.
    """
    anchor = plan.get('anchor_pricing') or {}
    cost_breakdown = plan.get('cost_breakdown') or {}
    line_items = []

    if (
        not anchor.get('is_train') and not anchor.get('is_cruise') and not anchor.get('is_road')
        and anchor.get('flight_price', 0) > 0
    ):
        transport_price = cost_breakdown.get('transportation', 0)
        if transport_price > 0:
            line_items.append({
                'type': 'flight',
                'price': transport_price,
                'details': {
                    'airline': anchor.get('flight_airline', ''),
                    'flight_number': anchor.get('flight_number', ''),
                    'departure_time': anchor.get('flight_dep_time', ''),
                    'arrival_time': anchor.get('flight_arr_time', ''),
                    'duration': anchor.get('flight_duration', ''),
                    'stops': anchor.get('flight_stops', 0),
                },
            })

    if anchor.get('hotel_price_per_night', 0) > 0:
        hotel_price = cost_breakdown.get('accommodation', 0)
        if hotel_price > 0:
            line_items.append({
                'type': 'hotel',
                'price': hotel_price,
                'details': {
                    'name': anchor.get('hotel_name', ''),
                    'stars': anchor.get('hotel_stars', 0),
                },
            })

    return line_items


@router.post("/bookings")
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
        # Not "confirmed" - no Stripe checkout has even started yet at this
        # point. Only _process_successful_payment (on a real
        # checkout.session.completed / polling-confirmed payment) ever
        # promotes this to "confirmed" - see that function and
        # _process_expired_payment for the rest of the state machine.
        # payment_status mirrors payment_transactions' own convention
        # ("pending" until a real payment lands, then "paid") - it used to
        # be hardcoded "mock_paid" here regardless of whether any payment
        # had happened, which read as an already-paid booking to anything
        # that inspected the field directly.
        "status": "pending_payment",
        "payment_status": "pending",
        "total_amount": resolved["price"],
        "currency": resolved["currency"],
        "created_at": datetime.now(timezone.utc),
    }

    await db.bookings.insert_one(booking_doc)
    booking_doc.pop("_id", None)
    # A plan -> booking conversion only when this booking actually
    # references a generated trip (req.trip_id set) - a standalone
    # flight/hotel booked with no trip_id never went through a generated
    # plan at all, so it isn't a conversion of one.
    if req.trip_id:
        await analytics_service.record_event(
            db, "plan_to_booking", user.user_id,
            {"trip_id": req.trip_id, "booking_id": booking_id, "booking_type": req.booking_type},
        )
    return booking_doc


@router.post("/trips/{trip_id}/book/{plan_type}")
async def book_trip_plan(trip_id: str, plan_type: str, request: Request):
    """Create ONE bundled booking covering every real bookable item (flight +
    hotel) in a generated plan tier, for a single combined Stripe charge -
    "Book this Plan". Mirrors create_booking's state machine exactly:
    status="pending_payment" at creation (never "confirmed" - the same bug
    class Problem 1 fixed for single-item bookings), promoted only by a
    real payment via the existing, unmodified webhook/polling/scheduler
    machinery below, which operates generically on booking_id/status and
    doesn't care whether a booking has one item_data object or a
    line_items array.
    """
    user = await get_current_user(request)

    if plan_type not in TRIP_PLAN_TYPES:
        raise HTTPException(status_code=400, detail=f"plan_type must be one of {list(TRIP_PLAN_TYPES)}")

    # Scoping to user_id doubles as the ownership check, same pattern as
    # regenerate_trip_plan - a trip_id that doesn't exist and one owned by
    # someone else both 404 identically.
    trip = await db.trips.find_one(
        {"trip_id": trip_id, "user_id": user.user_id},
        {"_id": 0}
    )
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    plans = trip.get("plans", [])
    plan = next((p for p in plans if p.get("plan_type") == plan_type), None)
    if not plan:
        raise HTTPException(status_code=404, detail=f"No {plan_type} plan found on this trip")
    if plan.get("status") != "ready":
        raise HTTPException(status_code=400, detail=f"{plan_type} plan is not ready to book")

    line_items = _bookable_line_items(plan)
    if not line_items:
        raise HTTPException(status_code=400, detail="Nothing in this plan is currently bookable")

    total_amount = sum(item['price'] for item in line_items)
    preferences = trip.get('preferences', {})

    booking_id = f"BK{uuid.uuid4().hex[:10].upper()}"
    confirmation_code = f"EYV-{uuid.uuid4().hex[:8].upper()}"

    booking_doc = {
        "booking_id": booking_id,
        "confirmation_code": confirmation_code,
        "user_id": user.user_id,
        "trip_id": trip_id,
        "booking_type": "bundle",
        "plan_type": plan_type,
        "trip_summary": {
            "destination": preferences.get("destination"),
            "departure_date": preferences.get("departure_date"),
            "return_date": preferences.get("return_date"),
        },
        "line_items": line_items,
        "traveler_details": {},
        # Same not-yet-paid convention as create_booking above - "pending"
        # until a real payment lands, never a value that reads as "paid"
        # before any payment has happened.
        "status": "pending_payment",
        "payment_status": "pending",
        "total_amount": total_amount,
        "currency": plan.get('currency', 'INR'),
        "created_at": datetime.now(timezone.utc),
    }

    await db.bookings.insert_one(booking_doc)
    booking_doc.pop("_id", None)
    # "Book this Plan" always has a trip_id - this IS the plan -> booking
    # conversion path.
    await analytics_service.record_event(
        db, "plan_to_booking", user.user_id,
        {"trip_id": trip_id, "booking_id": booking_id, "booking_type": "bundle", "plan_type": plan_type},
    )
    return booking_doc


@router.get("/bookings")
async def list_bookings(request: Request):
    user = await get_current_user(request)
    bookings = await db.bookings.find(
        {"user_id": user.user_id},
        {"_id": 0}
    ).sort("created_at", -1).to_list(100)
    return {"bookings": bookings}


@router.get("/bookings/{booking_id}")
async def get_booking(booking_id: str, request: Request):
    user = await get_current_user(request)
    booking = await db.bookings.find_one(
        {"booking_id": booking_id, "user_id": user.user_id},
        {"_id": 0}
    )
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    return booking


@router.delete("/bookings/{booking_id}")
async def cancel_booking(booking_id: str, request: Request):
    """Cancel a booking via a simple status flip - only valid for a booking
    that was never actually charged (status "pending_payment" or
    "payment_failed"). A "confirmed" booking has already been paid via a
    real Stripe checkout (_process_successful_payment) and there is no
    Stripe refund call anywhere in this codebase (checked: no
    stripe.Refund/create_refund usage anywhere) - flipping status to
    "cancelled" here would silently leave the customer's money gone while
    the record claims a clean cancellation, so that path is blocked with a
    clear error instead until a real refund flow exists.

    The status filter lives in the update itself, not a separate
    read-then-write, so a cancel racing a payment success (or two
    concurrent cancels) can't both observe "still pending_payment" and let
    one through that should have been blocked - same atomic-filtered-update
    shape as the rewards/payment race fixes elsewhere in this file. The
    follow-up find_one below only runs to build a specific error message
    for the caller; it never gates the mutation itself."""
    user = await get_current_user(request)
    result = await db.bookings.update_one(
        {
            "booking_id": booking_id,
            "user_id": user.user_id,
            "status": {"$in": ["pending_payment", "payment_failed"]},
        },
        {
            "$set": {
                "status": "cancelled",
                "cancelled_at": datetime.now(timezone.utc),
            }
        },
    )
    if result.matched_count == 0:
        booking = await db.bookings.find_one(
            {"booking_id": booking_id, "user_id": user.user_id},
            {"_id": 0, "status": 1},
        )
        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found")
        if booking.get("status") == "confirmed":
            raise HTTPException(
                status_code=400,
                detail=(
                    "This booking is already paid and confirmed. Cancelling a paid "
                    "booking isn't supported yet - contact support for a refund."
                ),
            )
        raise HTTPException(
            status_code=400,
            detail=f"Booking cannot be cancelled from its current status ('{booking['status']}').",
        )
    return {"message": "Booking cancelled successfully"}

