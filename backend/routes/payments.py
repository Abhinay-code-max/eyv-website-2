"""Payments and Subscription API router (/api/payments/*, /api/subscription/*).
"""
import os
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

import sentry_sdk
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from routes.shared import (
    db,
    payment_provider,
    get_current_user,
    is_user_premium,
)
from services import (
    ignav_service as duffel_service,
    rewards_service,
    notification_service,
    analytics_service,
    sentry_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["payments", "subscription"])


# ==================== Stripe Payments ====================

# Fixed packages - amounts defined on backend with pre-created Stripe Price IDs.
# USD is the canonical base price; customers are displayed prices in INR converted
# at read time via the app's live FX rate (services.ignav_service._to_inr) for display,
# while recurring subscriptions charge via pre-created Stripe Price objects configured
# in environment variables (STRIPE_PREMIUM_MONTHLY_PRICE_ID, STRIPE_PREMIUM_ANNUAL_PRICE_ID).
# See _get_premium_plans().
_PREMIUM_PLANS_USD = {
    "monthly": {"name": "EYV Premium Monthly", "amount_usd": 9.99, "interval": "month"},
    "yearly": {"name": "EYV Premium Yearly", "amount_usd": 99.00, "interval": "year"},
}


def _get_stripe_price_id(package_id: str) -> Optional[str]:
    """Resolve the configured Stripe Price ID for a given subscription package."""
    if package_id == "monthly":
        return os.environ.get("STRIPE_PREMIUM_MONTHLY_PRICE_ID")
    elif package_id in ("yearly", "annual"):
        return os.environ.get("STRIPE_PREMIUM_ANNUAL_PRICE_ID") or os.environ.get("STRIPE_PREMIUM_YEARLY_PRICE_ID")
    return None


async def _get_premium_plans() -> Dict[str, Dict[str, Any]]:
    """Premium plans priced in INR, converted from the canonical USD base
    above using the app's live FX rate. Subscription checkout sessions reference
    pre-created Stripe Price objects configured via environment variables
    (STRIPE_PREMIUM_MONTHLY_PRICE_ID, STRIPE_PREMIUM_ANNUAL_PRICE_ID)."""
    await duffel_service._refresh_rates_if_stale()
    return {
        package_id: {
            "name": plan["name"],
            "amount": duffel_service._to_inr(plan["amount_usd"], "USD"),
            "currency": "inr",
            "interval": plan["interval"],
            "price_id": _get_stripe_price_id(package_id),
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
    if not payment_provider.is_configured():
        raise HTTPException(status_code=500, detail="Stripe not configured")


@router.post("/payments/checkout")
async def create_checkout(req: CreateCheckoutRequest, request: Request):
    user = await get_current_user(request)

    # Only ever set >0 in the booking branch below (points redemption isn't
    # offered on subscription checkouts) - defined here, before the
    # package_id/booking_id branch, so it's always bound regardless of
    # which branch runs; referenced later for the refund-on-Stripe-failure
    # path and for tagging the stored transaction.
    points_reserved = 0

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
        
        # Apply points discount if requested. Reserved atomically right here
        # via rewards_service.reserve_points - not just checked, with the
        # actual deduction deferred to payment success. Two concurrent
        # checkouts against the same balance could previously both pass a
        # check-then-later-deduct race and jointly overspend (both read
        # "sufficient" before either write landed); the filtered $inc inside
        # reserve_points either atomically claims the points or fails
        # cleanly, with no window where both requests observe a stale
        # balance. If this checkout never completes, the reservation is
        # given back - either by _process_expired_payment (Stripe's
        # checkout.session.expired webhook, or the /payments/status poll
        # detecting expiry) or, if neither ever fires,
        # rewards_service.refund_stale_reserved_points's periodic sweep
        # (mirrors services.booking_expiry_service.expire_stale_pending_bookings's
        # own missed-webhook backstop, same STALE_PENDING_TTL).
        if req.use_points > 0:
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
            reserved = await rewards_service.reserve_points(db, user.user_id, req.use_points)
            if not reserved:
                raise HTTPException(status_code=400, detail="Insufficient points")
            points_reserved = req.use_points
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
    
    if payment_type == 'subscription':
        # Subscription Checkout Session referencing pre-created Stripe Price ID.
        # subscription_data.metadata is required so the Subscription object Stripe creates
        # carries user_id/package_id for webhook resolution.
        price_id = _get_stripe_price_id(req.package_id)
        if price_id:
            session_kwargs = dict(
                line_items=[{'price': price_id, 'quantity': 1}],
                mode='subscription',
                success_url=success_url,
                cancel_url=cancel_url,
                metadata=metadata,
                subscription_data={'metadata': metadata},
            )
        else:
            # Fallback to inline price_data if price ID env var is unset (e.g. before Stripe Dashboard setup)
            price_data = {
                'currency': currency,
                'product_data': {'name': description},
                'unit_amount': int(round(amount * 100)),
                'recurring': {'interval': plan['interval']},
            }
            session_kwargs = dict(
                line_items=[{'price_data': price_data, 'quantity': 1}],
                mode='subscription',
                success_url=success_url,
                cancel_url=cancel_url,
                metadata=metadata,
                subscription_data={'metadata': metadata},
            )
    else:
        # Dynamic booking charge - genuinely variable per trip search (flights + hotels)
        # and points redemption. Dynamic price_data is the correct tool here.
        price_data = {
            'currency': currency,
            'product_data': {'name': description},
            'unit_amount': int(round(amount * 100)),
        }
        session_kwargs = dict(
            line_items=[{'price_data': price_data, 'quantity': 1}],
            mode='payment',
            payment_method_types=['card'],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata=metadata,
        )

    _ensure_stripe_configured()
    try:
        session = await payment_provider.create_checkout_session(**session_kwargs)
    except Exception:
        # Points were already reserved above (if any) - a failed Checkout
        # Session means there's no checkout for that reservation to ever be
        # confirmed or expired against, so it must be given back here
        # rather than held indefinitely.
        if points_reserved:
            await rewards_service.refund_points(db, user.user_id, points_reserved)
        raise

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
        'created_at': datetime.now(timezone.utc),
    }
    if points_reserved:
        transaction['points_reservation_status'] = 'reserved'
    await db.payment_transactions.insert_one(transaction)
    
    return {
        'url': session.url,
        'session_id': session.id,
        'amount': amount,
        'currency': currency,
    }


@router.get("/payments/status/{session_id}")
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
    status_response = await payment_provider.retrieve_checkout_session(session_id)

    # Update transaction (idempotent - only process once). The webhook above
    # can be racing this exact request for the same session_id (Stripe fires
    # checkout.session.completed independently of whether/when the frontend
    # happens to poll this endpoint) - a plain read-this-Python-variable-then-
    # write is NOT enough to prevent double-processing (_process_successful_payment
    # awarding points twice, etc.): both requests could read payment_status
    # as still-pending before either one's write lands. The filter on
    # payment_status in the update itself is what makes this atomic - only
    # whichever request's update Mongo actually applies first gets a non-None
    # result back, so only that one calls the (non-idempotent) side effects.
    if status_response.payment_status == 'paid':
        updated = await db.payment_transactions.find_one_and_update(
            {'session_id': session_id, 'payment_status': {'$ne': 'paid'}},
            {'$set': {
                'payment_status': 'paid',
                'status': 'completed',
                'completed_at': datetime.now(timezone.utc),
            }}
        )
        if updated is not None:
            # Trigger post-payment actions
            await _process_successful_payment(transaction)
    elif status_response.status == 'expired':
        updated = await db.payment_transactions.find_one_and_update(
            {'session_id': session_id, 'payment_status': {'$nin': ['paid', 'expired']}},
            {'$set': {'payment_status': 'expired', 'status': 'expired'}}
        )
        if updated is not None:
            await _process_expired_payment(transaction)
    
    return {
        'payment_status': status_response.payment_status,
        'status': status_response.status,
        'amount': status_response.amount_total / 100 if status_response.amount_total else transaction['amount'],
        'currency': status_response.currency or transaction['currency'],
        'metadata': status_response.metadata or transaction['metadata'],
    }


async def _finalize_or_alert_points_redemption(db, transaction: Dict, user_id: str, points_used: int, booking_id: str) -> None:
    """Finalize the points reservation made atomically at checkout
    (create_checkout -> rewards_service.reserve_points). available_points
    was already decremented there, so this must NOT call
    redeem_points/re-deduct - that would spend the balance a second time.
    This only needs to flip the reservation reserved -> finalized (a
    filtered transition, the same shape as the payment_status race fix in
    get_payment_status/stripe_webhook - only whichever caller actually
    flips it proceeds) and record the permanent rewards_transactions audit
    row.

    If the flip fails (the reservation isn't "reserved" anymore - already
    refunded by rewards_service.refund_stale_reserved_points's sweep, or by
    _process_expired_payment on a since-revived Stripe session, either
    possibly racing this very late success), the Stripe charge still
    reflects the points discount but the points are no longer held - a
    real money-losing inconsistency. This used to be a silent
    `except ValueError: pass  # Already validated at checkout` in
    _process_successful_payment, which swallowed exactly this case. Now
    it's logged and sent to Sentry for manual reconciliation instead of
    disappearing - never silently ignored.

    Takes `db` as an explicit parameter (not the module-level `db` global)
    so it can be exercised directly in tests against a freshly-constructed
    Motor client, without going through the full HTTP/Stripe-mocking path
    - see tests/test_rewards_race.py."""
    finalized_txn = await db.payment_transactions.find_one_and_update(
        {'session_id': transaction['session_id'], 'points_reservation_status': 'reserved'},
        {'$set': {'points_reservation_status': 'finalized'}},
    )
    if finalized_txn is None:
        logger.error(
            f"Points reservation for booking {booking_id} (user {user_id}, "
            f"{points_used} points) was not in 'reserved' state at payment "
            f"success - the Stripe charge already reflects the points discount "
            f"but the points are no longer held. Needs manual reconciliation."
        )
        sentry_sdk.capture_exception(
            RuntimeError(f"Points reservation lost before payment success for booking {booking_id}"),
            tags={"area": "rewards_points_finalize"},
        )
    else:
        try:
            await rewards_service.finalize_reserved_points(
                db, user_id, points_used, booking_id, f"Discount on booking {booking_id}"
            )
        except Exception as e:
            logger.error(
                f"Failed to record points-redemption audit row for booking "
                f"{booking_id} (user {user_id}, {points_used} points): {e}"
            )
            sentry_sdk.capture_exception(e, tags={"area": "rewards_points_finalize"})


async def _process_successful_payment(transaction: Dict):
    """Process successful payment - subscription or booking."""
    metadata = transaction.get('metadata', {})
    payment_type = metadata.get('payment_type')
    user_id = metadata.get('user_id') or transaction.get('user_id')
    
    if payment_type == 'subscription':
        # checkout.session.completed for a subscription-mode Checkout
        # Session only ever fires once Stripe has actually collected the
        # first payment (unlike the raw Subscription API, hosted Checkout
        # doesn't complete on an unpaid/incomplete subscription) - so it's
        # safe to award the one-time signup bonus here. Everything about
        # the subscription's *ongoing* state (status, current_period_end,
        # stripe_subscription_id/customer_id) is owned entirely by
        # customer.subscription.created/updated (_sync_subscription_from_stripe)
        # instead of being set here - this event doesn't carry the
        # subscription object at all, and per the state-tracking design,
        # local fields are only ever written from the webhook that is
        # actually authoritative for them.
        package_id = metadata.get('package_id')
        await rewards_service.award_points(
            db, user_id, 'premium_subscription',
            reference_id=transaction['session_id'],
            description=f"Premium {package_id} subscription bonus"
        )
    
    elif payment_type == 'booking':
        booking_id = metadata.get('booking_id')
        points_used = int(metadata.get('points_used', 0))
        
        # Mark booking as paid AND confirmed. Deliberately unconditional on
        # the booking's current status (filtered only by booking_id) - a
        # genuinely successful payment must always win, even if this fires
        # after _process_expired_payment already flipped the same booking to
        # "payment_failed" (e.g. the user's Stripe Checkout tab was still
        # open and they completed payment within Stripe's 24h session
        # window, well after our own much shorter stale-pending TTL gave up
        # on it - see the scheduler in services/booking_expiry_service.py).
        # Money received must never be overridden by a stale-cleanup job.
        booking = await db.bookings.find_one({'booking_id': booking_id}, {'_id': 0})
        if booking:
            await db.bookings.update_one(
                {'booking_id': booking_id},
                {'$set': {
                    'status': 'confirmed',
                    'payment_status': 'paid',
                    'paid_at': datetime.now(timezone.utc),
                }}
            )
            await analytics_service.record_event(
                db, "booking_completed", user_id,
                {
                    "booking_id": booking_id,
                    "trip_id": booking.get("trip_id"),
                    "amount": booking.get("total_amount"),
                    "currency": booking.get("currency"),
                },
            )

            # Finalize the points reservation made atomically at checkout -
            # see _finalize_or_alert_points_redemption's own docstring for
            # why this must never be a silent no-op.
            if points_used > 0:
                await _finalize_or_alert_points_redemption(db, transaction, user_id, points_used, booking_id)
            
            # Award points for the booking. A bundle earns points for each
            # bookable type it actually contains (same as booking a flight
            # and a hotel separately would have) rather than falling into
            # the single-item flight/hotel branch below, which only ever
            # awards one type.
            if booking.get('booking_type') == 'bundle':
                for line_item in booking.get('line_items', []):
                    item_type = line_item.get('type')
                    action = 'booking_flight' if item_type == 'flight' else 'booking_hotel'
                    await rewards_service.award_points(
                        db, user_id, action,
                        reference_id=f"{booking_id}:{item_type}",
                        description=f"Earned for {item_type} in bundled booking"
                    )
            else:
                action = 'booking_flight' if booking.get('booking_type') == 'flight' else 'booking_hotel'
                await rewards_service.award_points(
                    db, user_id, action,
                    reference_id=booking_id,
                    description=f"Earned for {booking.get('booking_type')} booking"
                )


async def _process_expired_payment(transaction: Dict):
    """Process an abandoned/declined checkout whose Stripe session expired
    without completing. Mirrors _process_successful_payment's dispatch
    shape, but only ever moves a booking OUT of "pending_payment" - the
    update filter includes status: "pending_payment" so it can never
    clobber a booking _process_successful_payment already confirmed (that
    write is unconditional and always wins - see the comment there). Called
    from both the checkout.session.expired webhook and the polling
    /payments/status path, same as the success side.

    No-op for premium/subscription checkouts - Problem 2 (real
    subscriptions) is a separate, later effort, and premium access is only
    ever granted on success, never provisionally, so there's no pending
    state to roll back here.

    Also refunds any points reserved at checkout (create_checkout ->
    rewards_service.reserve_points) - filtered reserved -> refunded
    transition on the transaction's own points_reservation_status, the same
    atomic-transition shape as the payment_status race fix above, so this
    can never double-refund a reservation
    rewards_service.refund_stale_reserved_points's periodic sweep already
    caught (or vice versa) - only whichever caller's update actually flips
    the status gets to call refund_points."""
    metadata = transaction.get('metadata', {})
    if metadata.get('payment_type') != 'booking':
        return

    booking_id = metadata.get('booking_id')
    points_used = int(metadata.get('points_used', 0))
    user_id = metadata.get('user_id') or transaction.get('user_id')

    if booking_id:
        result = await db.bookings.update_one(
            {'booking_id': booking_id, 'status': 'pending_payment'},
            {'$set': {
                'status': 'payment_failed',
                'payment_failed_at': datetime.now(timezone.utc),
            }}
        )
        # Only when this call actually made the pending -> payment_failed
        # transition (not a no-op racing an already-confirmed/already-failed
        # booking) - the one explicit abandonment signal this app has, used
        # as the drop-off count for the plan_to_booking -> booking_completed
        # leg of the funnel (see AnalyticsEventDoc's own docstring).
        if result.matched_count > 0:
            await analytics_service.record_event(
                db, "booking_abandoned", user_id, {"booking_id": booking_id},
            )

    if points_used > 0:
        updated = await db.payment_transactions.find_one_and_update(
            {'session_id': transaction['session_id'], 'points_reservation_status': 'reserved'},
            {'$set': {'points_reservation_status': 'refunded'}},
        )
        if updated is not None:
            await rewards_service.refund_points(db, user_id, points_used)


async def _sync_subscription_from_stripe(subscription_obj: Dict):
    """Sync local subscription-state fields from a Stripe Subscription
    object - shared by customer.subscription.created/updated/deleted, since
    a .deleted event's object is itself just a subscription with
    status="canceled" (there's nothing event-specific to branch on; this is
    the one place that ever writes these fields, matching the rest of this
    app's rule that local state is always downstream of Stripe, never
    guessed at). A bare overwrite of the current Stripe-reported values is
    inherently idempotent - unlike the checkout success/expiry paths there
    are no side effects here (no points awarded, nothing granted) that a
    duplicate delivery could double-apply, so no extra "already processed"
    guard is needed.

    current_period_end lives on the subscription's line item, not the
    subscription itself, as of recent Stripe API versions (verified against
    docs.stripe.com/api/subscriptions/object rather than assumed) - reading
    the old top-level field would have silently returned nothing.
    """
    user_id = (subscription_obj.get('metadata') or {}).get('user_id')
    if not user_id:
        logger.warning(
            f"customer.subscription event for {subscription_obj.get('id')} "
            "has no user_id in metadata - cannot sync, skipping"
        )
        return

    update = {
        'stripe_customer_id': subscription_obj.get('customer'),
        'stripe_subscription_id': subscription_obj.get('id'),
        'stripe_subscription_status': subscription_obj.get('status'),
        'cancel_at_period_end': bool(subscription_obj.get('cancel_at_period_end')),
    }
    package_id = (subscription_obj.get('metadata') or {}).get('package_id')
    if package_id:
        update['premium_plan'] = package_id

    items = (subscription_obj.get('items') or {}).get('data') or []
    if items and items[0].get('current_period_end'):
        update['current_period_end'] = datetime.fromtimestamp(
            items[0]['current_period_end'], tz=timezone.utc
        )

    # Set once, the first time this subscription is ever observed active -
    # not overwritten on every sync, so a later past_due/active flap on
    # renewal doesn't reset "member since".
    if subscription_obj.get('status') == 'active':
        existing = await db.users.find_one({'user_id': user_id}, {'_id': 0, 'premium_started_at': 1})
        if not existing or not existing.get('premium_started_at'):
            update['premium_started_at'] = datetime.now(timezone.utc)

    await db.users.update_one({'user_id': user_id}, {'$set': update})


def _resolve_invoice_subscription(invoice_obj: Dict) -> tuple:
    """Returns (user_id, subscription_id) for an invoice.paid/payment_failed
    event. parent.subscription_details is where both the subscription
    reference AND its metadata live as of recent Stripe API versions
    (verified against docs.stripe.com/api/invoices/object - the old flat
    invoice.subscription field is gone). Metadata is preferred when present
    (avoids a DB lookup race against customer.subscription.created for the
    very first invoice on a brand-new subscription); falling back to a
    stripe_subscription_id match covers subscriptions old enough to predate
    Stripe populating this metadata (documented as only present from
    2023-06-29 onward), which isn't a real concern for this app but is a
    one-line safety net.
    """
    sub_details = (invoice_obj.get('parent') or {}).get('subscription_details') or {}
    subscription_id = sub_details.get('subscription')
    user_id = (sub_details.get('metadata') or {}).get('user_id')
    return user_id, subscription_id





async def _subscription_status_payload(user_id: str) -> Dict[str, Any]:
    """Shared response shape for GET /subscription/status and the cancel/
    resume endpoints below - one definition of what "subscription status"
    means to a client, rather than three near-identical hand-rolled dicts.
    Pure read, no write-back - see the note on the GET endpoint for why."""
    user_doc = await db.users.find_one(
        {'user_id': user_id},
        {
            '_id': 0, 'stripe_subscription_status': 1, 'premium_plan': 1,
            'current_period_end': 1, 'premium_started_at': 1, 'cancel_at_period_end': 1,
        }
    )
    return {
        'is_premium': await is_user_premium(user_id),
        'subscription_status': user_doc.get('stripe_subscription_status') if user_doc else None,
        'premium_plan': user_doc.get('premium_plan') if user_doc else None,
        'current_period_end': user_doc.get('current_period_end') if user_doc else None,
        'cancel_at_period_end': bool(user_doc.get('cancel_at_period_end')) if user_doc else False,
        'available_plans': await _get_premium_plans(),
    }



@router.get("/subscription/status")

async def get_subscription_status(request: Request):
    user = await get_current_user(request)
    # Pure read - no write-back here. Under the old design this endpoint
    # self-healed a stale "active" status by computing expiry itself and
    # writing "expired" back on read; that's exactly the app-guessing-at-
    # expiry pattern this rebuild replaces. stripe_subscription_status is
    # only ever current because a webhook (_sync_subscription_from_stripe /
    # invoice.paid / invoice.payment_failed) keeps it that way.
    return await _subscription_status_payload(user.user_id)


@router.post("/subscription/cancel")
async def cancel_subscription(request: Request):
    """Cancel-at-period-end, not an immediate cancel - the user keeps
    access through the period they already paid for (product decision).
    Stripe's synchronous response from Subscription.modify is fed straight
    into _sync_subscription_from_stripe (the same function
    customer.subscription.updated uses) so the local cancel_at_period_end
    flag is correct immediately, without waiting on that webhook's round
    trip - it still arrives moments later and just re-syncs the same
    values, harmlessly, since that function is idempotent by construction.
    _sync_subscription_from_stripe stays the only place these fields are
    ever written, whether triggered by a webhook or (as here) directly by
    the user's own request."""
    user = await get_current_user(request)
    user_doc = await db.users.find_one(
        {'user_id': user.user_id},
        {'_id': 0, 'stripe_subscription_id': 1, 'stripe_subscription_status': 1}
    )
    if not user_doc or not user_doc.get('stripe_subscription_id'):
        raise HTTPException(status_code=400, detail="No subscription to cancel")
    if user_doc.get('stripe_subscription_status') not in ('active', 'past_due'):
        raise HTTPException(status_code=400, detail="No active subscription to cancel")

    _ensure_stripe_configured()
    subscription = await payment_provider.modify_subscription(
        user_doc['stripe_subscription_id'],
        cancel_at_period_end=True,
    )
    await _sync_subscription_from_stripe(subscription)
    return await _subscription_status_payload(user.user_id)


@router.post("/subscription/resume")
async def resume_subscription(request: Request):
    """Undo a pending cancel-at-period-end before the period actually ends
    - standard SaaS UX (a user who clicked cancel and changed their mind
    shouldn't have to resubscribe from scratch through checkout again).
    Only meaningful while cancel_at_period_end is still true and the
    subscription hasn't actually ended yet; once customer.subscription.deleted
    has fired there's nothing left to resume and the user needs a new
    checkout instead."""
    user = await get_current_user(request)
    user_doc = await db.users.find_one(
        {'user_id': user.user_id},
        {'_id': 0, 'stripe_subscription_id': 1, 'stripe_subscription_status': 1, 'cancel_at_period_end': 1}
    )
    if not user_doc or not user_doc.get('stripe_subscription_id'):
        raise HTTPException(status_code=400, detail="No subscription to resume")
    if user_doc.get('stripe_subscription_status') not in ('active', 'past_due'):
        raise HTTPException(status_code=400, detail="Subscription has already ended - start a new one instead")
    if not user_doc.get('cancel_at_period_end'):
        raise HTTPException(status_code=400, detail="Subscription is not scheduled to cancel")

    _ensure_stripe_configured()
    subscription = await payment_provider.modify_subscription(
        user_doc['stripe_subscription_id'],
        cancel_at_period_end=False,
    )
    await _sync_subscription_from_stripe(subscription)
    return await _subscription_status_payload(user.user_id)


class CreatePortalSessionRequest(BaseModel):
    return_url: str


@router.post("/subscription/portal")
async def create_subscription_portal_session(req: CreatePortalSessionRequest, request: Request):
    """Stripe-hosted Customer Portal session - used for the past_due
    "update payment method" action (Part 5) rather than building custom
    card-update UI. Also lets a user see invoices/payment history for
    free, without any more of our own UI. Requires a portal configuration
    to already exist for this account (Dashboard > Settings > Billing >
    Customer portal, or stripe.billingPortal.Configuration.create) -
    Stripe returns a clear error naming exactly that if none exists yet,
    which this deliberately doesn't paper over by auto-creating one."""
    user = await get_current_user(request)
    user_doc = await db.users.find_one(
        {'user_id': user.user_id}, {'_id': 0, 'stripe_customer_id': 1}
    )
    if not user_doc or not user_doc.get('stripe_customer_id'):
        raise HTTPException(status_code=400, detail="No billing account to manage")

    _ensure_stripe_configured()
    portal_session = await payment_provider.create_billing_portal_session(
        customer_id=user_doc['stripe_customer_id'],
        return_url=req.return_url,
    )
    return {'url': portal_session.url}


# Stale-pending-booking sweep - a safety net for missed/undelivered
# checkout.session.expired webhooks (e.g. the user closing the tab before
