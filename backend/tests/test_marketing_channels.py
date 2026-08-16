"""
Unit tests for Marketing Channel Integrations (Task A.4 - Bob).
Tests BufferClient, InstagramClient, and WhatsAppClient.
"""
import asyncio
import pytest
from services.marketing_channels.buffer_client import BufferClient
from services.marketing_channels.instagram_client import InstagramClient
from services.marketing_channels.whatsapp_client import WhatsAppClient


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


def test_instagram_client_caption_validation_limits():
    client = InstagramClient(sandbox_mode=True)

    # Empty caption
    with pytest.raises(ValueError, match="must not be blank"):
        client.validate_post_content("")

    # Caption too long (>2200 chars)
    with pytest.raises(ValueError, match="exceeds 2200 chars"):
        client.validate_post_content("A" * 2201)

    # Too many hashtags (>30)
    too_many_tags = " ".join([f"#tag{i}" for i in range(32)])
    with pytest.raises(ValueError, match="exceeds 30 hashtags"):
        client.validate_post_content(too_many_tags)


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
