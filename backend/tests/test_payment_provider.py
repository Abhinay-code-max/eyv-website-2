"""Unit tests for PaymentProvider interface and StripePaymentProvider implementation."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.payment_provider import (
    PaymentProvider,
    get_payment_provider,
    set_payment_provider,
)
from services.stripe_provider import (
    StripePaymentProvider,
    stripe_payment_provider,
)


def _run(coro):
    return asyncio.run(coro)


def test_payment_provider_is_abstract():
    """PaymentProvider ABC cannot be directly instantiated."""
    with pytest.raises(TypeError):
        PaymentProvider()  # type: ignore[abstract]


def test_get_and_set_payment_provider():
    """get_payment_provider returns default StripePaymentProvider and supports set_payment_provider."""
    default_provider = get_payment_provider()
    assert isinstance(default_provider, StripePaymentProvider)

    class DummyProvider(PaymentProvider):
        def is_configured(self) -> bool:
            return True

        async def create_checkout_session(self, **kwargs):
            return {"id": "dummy_sess_1", "url": "https://dummy.checkout/1"}

        async def retrieve_checkout_session(self, session_id: str):
            return {"id": session_id, "payment_status": "paid"}

        def verify_webhook_signature(self, payload, signature, secret=None) -> bool:
            return True

        def parse_webhook_event(self, payload, signature=None, secret=None):
            return {"type": "dummy.event", "data": {}}

        def construct_event(self, payload, signature, secret=None):
            return self.parse_webhook_event(payload, signature, secret)

        async def modify_subscription(self, subscription_id: str, **kwargs):
            return {"id": subscription_id, "status": "active"}

        async def create_billing_portal_session(self, customer_id: str, return_url: str, **kwargs):
            return {"url": "https://dummy.portal/session"}

    dummy = DummyProvider()
    set_payment_provider(dummy)
    assert get_payment_provider() is dummy

    # Restore default provider
    set_payment_provider(default_provider)
    assert get_payment_provider() is default_provider


def test_stripe_provider_is_configured(monkeypatch):
    """is_configured checks both stripe.api_key and STRIPE_API_KEY environment variable."""
    import stripe
    provider = StripePaymentProvider()

    monkeypatch.setattr(stripe, "api_key", "sk_test_123")
    assert provider.is_configured() is True

    monkeypatch.setattr(stripe, "api_key", None)
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_env_123")
    assert provider.is_configured() is True

    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    assert provider.is_configured() is False


def test_stripe_provider_create_checkout_session(monkeypatch):
    """create_checkout_session delegates to stripe.checkout.Session.create."""
    import stripe
    provider = StripePaymentProvider()

    mock_create = MagicMock(return_value=MagicMock(id="cs_123", url="https://stripe.com/pay"))
    monkeypatch.setattr(stripe.checkout.Session, "create", mock_create)

    session = _run(provider.create_checkout_session(mode="payment", line_items=[]))
    assert session.id == "cs_123"
    assert session.url == "https://stripe.com/pay"
    mock_create.assert_called_once_with(mode="payment", line_items=[])


def test_stripe_provider_create_subscription_checkout_session_with_price_id(monkeypatch):
    """create_checkout_session supports pre-created Stripe Price IDs for subscriptions."""
    import stripe
    provider = StripePaymentProvider()

    mock_create = MagicMock(return_value=MagicMock(id="cs_sub_123", url="https://checkout.stripe.com/pay/sub123"))
    monkeypatch.setattr(stripe.checkout.Session, "create", mock_create)

    session_kwargs = {
        "line_items": [{"price": "price_test_monthly_123", "quantity": 1}],
        "mode": "subscription",
        "success_url": "https://example.com/payment-success?session_id={CHECKOUT_SESSION_ID}",
        "cancel_url": "https://example.com/payment-cancel",
        "metadata": {"user_id": "usr_1", "package_id": "monthly", "payment_type": "subscription"},
        "subscription_data": {"metadata": {"user_id": "usr_1", "package_id": "monthly", "payment_type": "subscription"}},
    }

    session = _run(provider.create_checkout_session(**session_kwargs))
    assert session.id == "cs_sub_123"
    assert session.url == "https://checkout.stripe.com/pay/sub123"
    mock_create.assert_called_once_with(**session_kwargs)


def test_stripe_provider_create_booking_checkout_session_with_price_data(monkeypatch):
    """create_checkout_session supports dynamic inline price_data for one-time bookings."""
    import stripe
    provider = StripePaymentProvider()

    mock_create = MagicMock(return_value=MagicMock(id="cs_bk_123", url="https://checkout.stripe.com/pay/bk123"))
    monkeypatch.setattr(stripe.checkout.Session, "create", mock_create)

    session_kwargs = {
        "line_items": [{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": "Booking BK_12345"},
                "unit_amount": 45000,
            },
            "quantity": 1,
        }],
        "mode": "payment",
        "payment_method_types": ["card"],
        "success_url": "https://example.com/payment-success?session_id={CHECKOUT_SESSION_ID}",
        "cancel_url": "https://example.com/payment-cancel",
        "metadata": {"user_id": "usr_1", "booking_id": "BK_12345", "payment_type": "booking", "points_used": "0"},
    }

    session = _run(provider.create_checkout_session(**session_kwargs))
    assert session.id == "cs_bk_123"
    assert session.url == "https://checkout.stripe.com/pay/bk123"
    mock_create.assert_called_once_with(**session_kwargs)


def test_stripe_provider_retrieve_checkout_session(monkeypatch):
    """retrieve_checkout_session delegates to stripe.checkout.Session.retrieve."""
    import stripe
    provider = StripePaymentProvider()

    mock_retrieve = MagicMock(return_value=MagicMock(id="cs_123", payment_status="paid"))
    monkeypatch.setattr(stripe.checkout.Session, "retrieve", mock_retrieve)

    session = _run(provider.retrieve_checkout_session("cs_123"))
    assert session.id == "cs_123"
    assert session.payment_status == "paid"
    mock_retrieve.assert_called_once_with("cs_123")


def test_stripe_provider_webhook_handling(monkeypatch):
    """construct_event, parse_webhook_event and verify_webhook_signature wrap stripe.Webhook."""
    import stripe
    provider = StripePaymentProvider()

    fake_event = {"type": "checkout.session.completed", "data": {"object": {"id": "cs_123"}}}
    mock_construct = MagicMock(return_value=fake_event)
    monkeypatch.setattr(stripe.Webhook, "construct_event", mock_construct)

    event = provider.construct_event(b"payload", "sig_123", "whsec_123")
    assert event == fake_event
    mock_construct.assert_called_with(b"payload", "sig_123", "whsec_123")

    parsed = provider.parse_webhook_event(b"payload", "sig_123", "whsec_123")
    assert parsed == fake_event

    assert provider.verify_webhook_signature(b"payload", "sig_123", "whsec_123") is True

    # Error handling
    mock_construct.side_effect = Exception("Invalid signature")
    assert provider.verify_webhook_signature(b"payload", "bad_sig", "whsec_123") is False


def test_stripe_provider_modify_subscription(monkeypatch):
    """modify_subscription delegates to stripe.Subscription.modify."""
    import stripe
    provider = StripePaymentProvider()

    mock_modify = MagicMock(return_value={"id": "sub_123", "cancel_at_period_end": True})
    monkeypatch.setattr(stripe.Subscription, "modify", mock_modify)

    sub = _run(provider.modify_subscription("sub_123", cancel_at_period_end=True))
    assert sub["id"] == "sub_123"
    mock_modify.assert_called_once_with("sub_123", cancel_at_period_end=True)


def test_stripe_provider_create_billing_portal_session(monkeypatch):
    """create_billing_portal_session delegates to stripe.billing_portal.Session.create."""
    import stripe
    provider = StripePaymentProvider()

    mock_portal = MagicMock(return_value=MagicMock(url="https://billing.stripe.com/session/123"))
    monkeypatch.setattr(stripe.billing_portal.Session, "create", mock_portal)

    portal = _run(provider.create_billing_portal_session("cus_123", "https://app.eyv.com/settings"))
    assert portal.url == "https://billing.stripe.com/session/123"
    mock_portal.assert_called_once_with(customer="cus_123", return_url="https://app.eyv.com/settings")
