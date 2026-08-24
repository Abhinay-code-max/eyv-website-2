"""Stripe implementation of PaymentProvider.

Wraps existing Stripe SDK calls verbatim to provide a clean abstraction
boundary while maintaining 100% behavioral compatibility.
"""
import asyncio
import os
from typing import Any, Dict, Optional, Union
import stripe

from services.payment_provider import PaymentProvider


class StripePaymentProvider(PaymentProvider):
    """Stripe payment provider wrapping the official stripe Python SDK."""

    def __init__(self, api_key: Optional[str] = None):
        if api_key:
            stripe.api_key = api_key
        elif not stripe.api_key:
            stripe.api_key = os.environ.get("STRIPE_API_KEY")

    def is_configured(self) -> bool:
        """Return True if stripe.api_key or STRIPE_API_KEY is configured."""
        return bool(stripe.api_key or os.environ.get("STRIPE_API_KEY"))

    async def create_checkout_session(self, **kwargs: Any) -> Any:
        """Create a Stripe Checkout Session via stripe.checkout.Session.create."""
        return await asyncio.to_thread(stripe.checkout.Session.create, **kwargs)

    async def retrieve_checkout_session(self, session_id: str) -> Any:
        """Retrieve a Stripe Checkout Session via stripe.checkout.Session.retrieve."""
        return await asyncio.to_thread(stripe.checkout.Session.retrieve, session_id)

    def verify_webhook_signature(
        self,
        payload: Union[bytes, str],
        signature: str,
        secret: Optional[str] = None,
    ) -> bool:
        """Verify webhook signature using stripe.Webhook.construct_event."""
        webhook_secret = secret or os.environ.get("STRIPE_WEBHOOK_SECRET")
        if not webhook_secret:
            return False
        try:
            stripe.Webhook.construct_event(payload, signature, webhook_secret)
            return True
        except Exception:
            return False

    def parse_webhook_event(
        self,
        payload: Union[bytes, str],
        signature: Optional[str] = None,
        secret: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Verify signature and parse raw webhook body via stripe.Webhook.construct_event."""
        webhook_secret = secret or os.environ.get("STRIPE_WEBHOOK_SECRET")
        if not webhook_secret:
            raise ValueError("Stripe webhook secret not configured")
        return stripe.Webhook.construct_event(payload, signature or "", webhook_secret)

    def construct_event(
        self,
        payload: Union[bytes, str],
        signature: str,
        secret: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Construct and verify event via stripe.Webhook.construct_event."""
        return self.parse_webhook_event(payload, signature, secret)

    async def modify_subscription(
        self,
        subscription_id: str,
        **kwargs: Any,
    ) -> Any:
        """Modify an active Stripe subscription via stripe.Subscription.modify."""
        return await asyncio.to_thread(
            stripe.Subscription.modify,
            subscription_id,
            **kwargs,
        )

    async def create_billing_portal_session(
        self,
        customer_id: str,
        return_url: str,
        **kwargs: Any,
    ) -> Any:
        """Create a Stripe Customer Portal session via stripe.billing_portal.Session.create."""
        return await asyncio.to_thread(
            stripe.billing_portal.Session.create,
            customer=customer_id,
            return_url=return_url,
            **kwargs,
        )


# Singleton instance for standard use
stripe_payment_provider = StripePaymentProvider()
