"""Abstract payment provider interface.

Defines the contract for payment processors (e.g. Stripe, Razorpay) supported
by the application. Covers checkout sessions, status polling, webhook verification
and parsing, subscription management, and billing portal sessions.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Union


class PaymentProvider(ABC):
    """Abstract interface for payment gateway operations."""

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if the provider credentials/keys are properly configured."""
        pass

    @abstractmethod
    async def create_checkout_session(self, **kwargs: Any) -> Any:
        """Create a checkout session with the given parameters.

        Supports both:
        1. Fixed Price ID line items for recurring subscriptions:
           `line_items=[{'price': price_id, 'quantity': 1}]`, `mode='subscription'`, `subscription_data={'metadata': ...}`
        2. Dynamic inline price_data for one-time bookings:
           `line_items=[{'price_data': price_data, 'quantity': 1}]`, `mode='payment'`, `payment_method_types=['card']`

        Returns an object or dict with at least `id` and `url` attributes/keys.
        """
        pass

    @abstractmethod
    async def retrieve_checkout_session(self, session_id: str) -> Any:
        """Retrieve a checkout session by its ID to check payment status.

        Returns an object or dict with at least `payment_status` and `status`.
        """
        pass

    @abstractmethod
    def verify_webhook_signature(
        self,
        payload: Union[bytes, str],
        signature: str,
        secret: Optional[str] = None,
    ) -> bool:
        """Verify the cryptographic signature of an incoming webhook payload."""
        pass

    @abstractmethod
    def parse_webhook_event(
        self,
        payload: Union[bytes, str],
        signature: Optional[str] = None,
        secret: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Verify signature and parse raw webhook body into a normalized event dict.

        Returns a dict-like event structure containing at least 'type' and 'data'.
        """
        pass

    @abstractmethod
    def construct_event(
        self,
        payload: Union[bytes, str],
        signature: str,
        secret: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Construct and verify an event from raw webhook body and signature header."""
        pass

    @abstractmethod
    async def modify_subscription(
        self,
        subscription_id: str,
        **kwargs: Any,
    ) -> Any:
        """Modify an existing subscription (e.g. cancel_at_period_end=True/False)."""
        pass

    @abstractmethod
    async def create_billing_portal_session(
        self,
        customer_id: str,
        return_url: str,
        **kwargs: Any,
    ) -> Any:
        """Create a customer billing portal session for self-service subscription management."""
        pass


_DEFAULT_PROVIDER: Optional[PaymentProvider] = None


def get_payment_provider() -> PaymentProvider:
    """Return the active payment provider instance (defaulting to Stripe)."""
    global _DEFAULT_PROVIDER
    if _DEFAULT_PROVIDER is None:
        from services.stripe_provider import StripePaymentProvider
        _DEFAULT_PROVIDER = StripePaymentProvider()
    return _DEFAULT_PROVIDER


def set_payment_provider(provider: PaymentProvider) -> None:
    """Set the active payment provider instance (useful for testing or switching)."""
    global _DEFAULT_PROVIDER
    _DEFAULT_PROVIDER = provider
