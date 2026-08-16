"""
Unit tests for Marketing Channel Integrations (Task A.4 - Bob).
Tests BufferClient, InstagramClient, and WhatsAppClient.
"""
import asyncio
import pytest
from services.marketing_channels.buffer_client import BufferClient, BufferClientError
from services.marketing_channels.instagram_client import InstagramClient, InstagramClientError
from services.marketing_channels.whatsapp_client import WhatsAppClient, WhatsAppClientError


def test_buffer_client_dry_run_create_update():
    client = BufferClient(dry_run=True, default_profile_ids=["test_prof_1"])
    res = asyncio.run(client.create_update(text="Special summer holiday offer!", draft=True))
    assert res["success"] is True
    assert res["dry_run"] is True
    assert res["draft"] is True
    assert res["text"] == "Special summer holiday offer!"


def test_buffer_client_blank_text_raises():
    client = BufferClient(dry_run=True)
    with pytest.raises(ValueError, match="must not be blank"):
        asyncio.run(client.create_update(text=""))


def test_buffer_client_non_dry_run_without_credentials_raises_error():
    """BufferClient must hard fail in production if credentials are missing and dry_run=False."""
    client = BufferClient(dry_run=False, access_token=None)
    with pytest.raises(BufferClientError, match="BUFFER_ACCESS_TOKEN is not configured"):
        asyncio.run(client.create_update(text="Live post without token"))


def test_instagram_client_validation_and_sandbox_publish():
    client = InstagramClient(sandbox_mode=True, account_id="test_ig_account")
    
    # Valid post
    res = asyncio.run(client.publish_photo(
        image_url="https://enjoyyourvacation.in/images/og-hero.jpg",
        caption="Explore Goa with EYV! #Goa #Travel #Vacation",
    ))
    assert res["success"] is True
    assert res["sandbox_mode"] is True
    assert "media_id" in res


def test_instagram_client_missing_image_raises():
    client = InstagramClient(sandbox_mode=True)
    with pytest.raises(ValueError, match="requires a valid media/image URL"):
        client.validate_post_content("Valid caption", media_url="")


def test_instagram_client_non_sandbox_without_credentials_raises_error():
    """InstagramClient must hard fail if credentials are missing and sandbox_mode=False."""
    client = InstagramClient(sandbox_mode=False, access_token=None, account_id=None)
    with pytest.raises(InstagramClientError, match="INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_ACCOUNT_ID must be configured"):
        asyncio.run(client.publish_photo(
            image_url="https://enjoyyourvacation.in/images/og-hero.jpg",
            caption="Live post without token",
        ))


def test_instagram_client_caption_validation_limits():
    client = InstagramClient(sandbox_mode=True)

    # Empty caption
    with pytest.raises(ValueError, match="must not be blank"):
        client.validate_post_content("", media_url="https://example.com/img.jpg")

    # Caption too long (>2200 chars)
    with pytest.raises(ValueError, match="exceeds 2200 chars"):
        client.validate_post_content("A" * 2201, media_url="https://example.com/img.jpg")

    # Too many hashtags (>30)
    too_many_tags = " ".join([f"#tag{i}" for i in range(32)])
    with pytest.raises(ValueError, match="exceeds 30 hashtags"):
        client.validate_post_content(too_many_tags, media_url="https://example.com/img.jpg")


def test_whatsapp_client_dry_run_dispatch():
    client = WhatsAppClient(dry_run=True, phone_number_id="test_phone_id")
    
    # Text message
    res = asyncio.run(client.send_text_message(to_phone="+919876543210", body="Your booking is confirmed!"))
    assert res["success"] is True
    assert res["dry_run"] is True
    assert res["to"] == "919876543210"

    # Template message
    tpl_res = asyncio.run(client.send_template_message(to_phone="+919876543210", template_name="trip_itinerary_ready"))
    assert tpl_res["success"] is True
    assert tpl_res["dry_run"] is True


def test_whatsapp_client_non_dry_run_without_credentials_raises_error():
    """WhatsAppClient must hard fail if credentials are missing and dry_run=False."""
    client = WhatsAppClient(dry_run=False, access_token=None, phone_number_id=None)
    with pytest.raises(WhatsAppClientError, match="WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID must be configured"):
        asyncio.run(client.send_text_message(to_phone="+919876543210", body="Live whatsapp without token"))


def test_whatsapp_webhook_parser():
    webhook_payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "id": "wamid.HBgL...",
                        "from": "919876543210",
                        "timestamp": "1723789200",
                        "text": {"body": "Interested in Goa package"},
                    }],
                    "statuses": [{
                        "id": "wamid.HBgL...",
                        "status": "delivered",
                        "recipient_id": "919876543210",
                    }]
                }
            }]
        }]
    }

    events = WhatsAppClient.parse_webhook_event(webhook_payload)
    assert len(events) == 2
    assert events[0]["type"] == "incoming_message"
    assert events[0]["text"] == "Interested in Goa package"
    assert events[1]["type"] == "status_update"
    assert events[1]["status"] == "delivered"
