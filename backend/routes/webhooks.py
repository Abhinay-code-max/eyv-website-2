"""Webhooks API router (/api/webhook/*, /api/webhooks/*).
"""
import os
import hmac
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import sentry_sdk
from fastapi import APIRouter, HTTPException, Request

from routes.shared import (
    db,
    limiter,
    payment_provider,
    _get_internal_ticket_http_client,
)
from routes.payments import (
    _ensure_stripe_configured,
    _process_successful_payment,
    _process_expired_payment,
    _sync_subscription_from_stripe,
    _resolve_invoice_subscription,
)
from agents.sara.analytics_agent_service import record_revenuecat_event
from agents.telegram.telegram_bot_service import process_telegram_update

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["webhooks"])


@router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events."""
    body = await request.body()
    signature = request.headers.get('Stripe-Signature', '')
    webhook_secret = os.environ.get('STRIPE_WEBHOOK_SECRET')

    try:
        _ensure_stripe_configured()
        if not webhook_secret:
            raise HTTPException(status_code=500, detail="Stripe webhook secret not configured")
        event = payment_provider.construct_event(body, signature, webhook_secret)

        if event['type'] == 'checkout.session.completed':
            session_obj = event['data']['object']
            transaction = await db.payment_transactions.find_one(
                {'session_id': session_obj['id']},
                {'_id': 0}
            )
            # Atomic find_one_and_update, not a read-then-write - this can
            # race the /payments/status poll endpoint for the same
            # session_id (Stripe's webhook delivery and the frontend's own
            # poll are entirely independent of each other), and
            # _process_successful_payment's side effects (awarding points,
            # confirming bookings) are not themselves idempotent. Filtering
            # payment_status into the update means only whichever request
            # Mongo actually applies first gets a non-None result and
            # proceeds to the side effects - see the matching comment on
            # get_payment_status.
            if transaction:
                updated = await db.payment_transactions.find_one_and_update(
                    {'session_id': session_obj['id'], 'payment_status': {'$ne': 'paid'}},
                    {'$set': {
                        'payment_status': 'paid',
                        'status': 'completed',
                        'completed_at': datetime.now(timezone.utc),
                    }}
                )
                if updated is not None:
                    await _process_successful_payment(transaction)

        elif event['type'] == 'checkout.session.expired':
            session_obj = event['data']['object']
            transaction = await db.payment_transactions.find_one(
                {'session_id': session_obj['id']},
                {'_id': 0}
            )
            # Same atomic-update reasoning as checkout.session.completed above.
            # Guards against reprocessing on Stripe's at-least-once webhook
            # redelivery, against racing the /payments/status poll endpoint,
            # and against a stray/duplicate expired event ever touching a
            # transaction a (possibly since-arrived) success event already
            # marked paid.
            if transaction:
                updated = await db.payment_transactions.find_one_and_update(
                    {'session_id': session_obj['id'], 'payment_status': {'$nin': ['paid', 'expired']}},
                    {'$set': {'payment_status': 'expired', 'status': 'expired'}}
                )
                if updated is not None:
                    await _process_expired_payment(transaction)

        elif event['type'] in (
            'customer.subscription.created',
            'customer.subscription.updated',
            'customer.subscription.deleted',
        ):
            await _sync_subscription_from_stripe(event['data']['object'])

        elif event['type'] == 'invoice.paid':
            invoice_obj = event['data']['object']
            user_id, subscription_id = _resolve_invoice_subscription(invoice_obj)
            filter_query = {'user_id': user_id} if user_id else (
                {'stripe_subscription_id': subscription_id} if subscription_id else None
            )
            if filter_query:
                # Confirms a successful (renewal or initial) charge - status
                # reflects active/current again even if a previous cycle's
                # invoice.payment_failed had marked this past_due.
                await db.users.update_one(filter_query, {'$set': {'stripe_subscription_status': 'active'}})

        elif event['type'] == 'invoice.payment_failed':
            invoice_obj = event['data']['object']
            user_id, subscription_id = _resolve_invoice_subscription(invoice_obj)
            filter_query = {'user_id': user_id} if user_id else (
                {'stripe_subscription_id': subscription_id} if subscription_id else None
            )
            if filter_query:
                # Grace period starts here - access stays on (is_user_premium
                # treats past_due as active) for as long as Stripe's own
                # Smart Retries keep retrying (~2 weeks by default). No
                # custom timer: whatever Stripe/the Dashboard's configured
                # exhaustion action eventually does (cancel / mark unpaid /
                # leave past_due) arrives as its own
                # customer.subscription.updated/deleted event and is synced
                # by _sync_subscription_from_stripe like any other change.
                await db.users.update_one(filter_query, {'$set': {'stripe_subscription_status': 'past_due'}})

        return {"received": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        sentry_sdk.capture_exception(e, tags={"provider": "stripe"})
        # Return non-2xx so Stripe retries the webhook
        raise HTTPException(status_code=400, detail=f"Webhook processing failed: {str(e)}")




@router.post("/webhooks/revenuecat")
@router.post("/webhook/revenuecat")
async def revenuecat_webhook(request: Request):
    """Handle RevenueCat subscription lifecycle webhook events (Task A.3 - Sara).
    Authenticated via REVENUECAT_WEBHOOK_AUTH_KEY using constant-time hmac.compare_digest."""
    auth_header = request.headers.get("Authorization", "").strip()
    if not auth_header:
        raise HTTPException(status_code=401, detail="Missing RevenueCat webhook authorization header")

    provided_key = auth_header[len("Bearer "):].strip() if auth_header.startswith("Bearer ") else auth_header
    expected_key = os.environ.get("REVENUECAT_WEBHOOK_AUTH_KEY", "").strip()

    if not expected_key:
        logger.error("REVENUECAT_WEBHOOK_AUTH_KEY is not configured")
        raise HTTPException(status_code=500, detail="RevenueCat webhook auth key not configured")

    if not hmac.compare_digest(provided_key, expected_key):
        raise HTTPException(status_code=401, detail="Invalid RevenueCat webhook authorization")


    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    from agents.sara.analytics_agent_service import record_revenuecat_event
    res = await record_revenuecat_event(db, payload)
    return res


@limiter.limit("120/minute")
async def _telegram_preauth_marker(request: Request) -> None:
    """Marker function for SlowAPI bookkeeping of Telegram pre-auth flood gate."""
    pass


@router.post("/webhooks/telegram")
@router.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    """Handle incoming Telegram Bot webhook updates (slash commands and callback queries).
    Includes a pre-auth flood gate before secret header validation to prevent slowapi flag collisions."""
    # 1. Pre-auth rate-limit flood gate (120/min per IP)
    limiter._check_request_limit(request, _telegram_preauth_marker, False)


    # 2. Secret header validation
    expected_secret = os.environ.get("TELEGRAM_SECRET_TOKEN", "").strip()
    if expected_secret:
        secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "").strip()
        if not secret_header or not hmac.compare_digest(secret_header, expected_secret):
            raise HTTPException(status_code=401, detail="Invalid Telegram webhook secret token")

    # 3. JSON payload parsing
    try:
        update_payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    from agents.telegram.telegram_bot_service import process_telegram_update
    internal_client = _get_internal_ticket_http_client()
    return await process_telegram_update(db, update_payload, internal_ticket_client=internal_client)


