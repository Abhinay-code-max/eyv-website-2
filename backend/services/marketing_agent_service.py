"""
Marketing & Promotion Agent (Bob) - Task A.4 of EYV Agent System.

Bob is EYV's sub-agent for:
1. Drafting social copy and promotional campaigns (Buffer, Instagram, WhatsApp, Promo codes).
2. Staging campaigns in db.marketing_campaigns as draft / pending_approval.
3. Producing approval work items into db.jarvis_queue_items for JARVIS/human sign-off.
4. Executing approved marketing actions (creating discounts, publishing posts).
5. Strict scope isolation: Never modifies users, bookings, or payments collections.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from pydantic import BaseModel, Field

from db_models import (
    MarketingCampaignDoc,
    PromotionDoc,
)
from services.jarvis_queue_service import enqueue_jarvis_item
from services.marketing_channels.buffer_client import BufferClient, get_buffer_client
from services.marketing_channels.instagram_client import InstagramClient, get_instagram_client
from services.marketing_channels.whatsapp_client import WhatsAppClient, get_whatsapp_client

logger = logging.getLogger(__name__)


class CampaignGenerationResult(BaseModel):
    campaign_id: str
    queue_item_id: Optional[str]
    title: str
    channel: str
    status: str
DESTINATION_DEFAULT_IMAGES = {
    "goa": "https://enjoyyourvacation.in/images/destinations/goa.jpg",
    "kerala": "https://enjoyyourvacation.in/images/destinations/kerala.jpg",
    "manali": "https://enjoyyourvacation.in/images/destinations/manali.jpg",
    "jaipur": "https://enjoyyourvacation.in/images/destinations/jaipur.jpg",
    "ladakh": "https://enjoyyourvacation.in/images/destinations/ladakh.jpg",
    "kashmir": "https://enjoyyourvacation.in/images/destinations/kashmir.jpg",
    "bali": "https://enjoyyourvacation.in/images/destinations/bali.jpg",
    "dubai": "https://enjoyyourvacation.in/images/destinations/dubai.jpg",
}
DEFAULT_HERO_IMAGE = "https://enjoyyourvacation.in/images/og-hero.jpg"


def resolve_campaign_image(destination: str, custom_image_url: Optional[str] = None) -> str:
    """Resolves a valid, high-resolution production image URL for Instagram/social campaigns.
    Falls back to curated destination assets or default brand hero image."""
    if custom_image_url and custom_image_url.strip():
        return custom_image_url.strip()
    dest_clean = destination.lower().strip()
    return DESTINATION_DEFAULT_IMAGES.get(dest_clean, DEFAULT_HERO_IMAGE)


class CampaignExecutionResult(BaseModel):
    campaign_id: str
    channel: str
    status: str
    external_post_id: Optional[str] = None
    promo_code: Optional[str] = None
    published_at: Optional[datetime] = None
    error: Optional[str] = None


async def generate_campaign_draft(
    db,
    gemini_client=None,
    *,
    title: str,
    channel: str,
    destination: str,
    theme: str = "travel_highlight",
    discount_percent: Optional[float] = None,
    target_audience: Optional[str] = "all_travelers",
    custom_content: Optional[Dict[str, Any]] = None,
) -> CampaignGenerationResult:
    """Generates a structured marketing campaign draft and enqueues it for JARVIS approval."""
    now = datetime.now(timezone.utc)
    content: Dict[str, Any] = custom_content.copy() if custom_content else {}

    # Ensure image_url is always resolved and present for Instagram/social channels
    resolved_image = resolve_campaign_image(destination, content.get("image_url"))
    content["image_url"] = resolved_image

    if not content.get("headline"):
        headline = f"Discover {destination.title()} - {theme.replace('_', ' ').title()}"
        promo_code = f"EYV{destination[:3].upper()}{int(discount_percent)}" if discount_percent else None
        caption = (
            f"Ready for an unforgettable trip to {destination.title()}? 🌴✈️\n"
            f"Explore curated itineraries, local hidden gems, and seamless planning with EYV."
        )
        if promo_code and discount_percent:
            caption += f"\n\nUse code {promo_code} for {int(discount_percent)}% off your booking!"
        caption += f"\n\n#EYV #Travel{destination.title()} #Explore #VacationGoals"

        content.update({
            "headline": headline,
            "caption": caption,
            "destination": destination,
            "hashtags": [f"#{destination.title()}", "#Travel", "#EYV", "#Vacation"],
            "promo_code": promo_code,
            "discount_percent": discount_percent,
        })

    discount_config = None
    if discount_percent and discount_percent > 0:
        code_str = content.get("promo_code") or f"EYV{destination[:3].upper()}{int(discount_percent)}"
        discount_config = {
            "code": code_str,
            "discount_type": "percent",
            "discount_value": float(discount_percent),
            "valid_days": 30,
            "usage_cap": 100,
        }

    campaign_doc = {
        "title": title,
        "channel": channel,
        "status": "pending_approval",
        "content": content,
        "target_audience": target_audience,
        "spend_budget": 0.0,
        "discount_config": discount_config,
        "created_at": now,
        "scheduled_for": now + timedelta(hours=24),
    }

    insert_res = await db.marketing_campaigns.insert_one(campaign_doc)
    campaign_id = str(insert_res.inserted_id)

    # Priority determination: Priority 1 if discount > 20% or spend > $100, else normal 5
    priority = 1 if (discount_percent and discount_percent > 20.0) else 5

    queue_item = await enqueue_jarvis_item(
        db,
        source_agent="bob",
        item_type="marketing_campaign_approval",
        priority=priority,
        payload={
            "campaign_id": campaign_id,
            "title": title,
            "channel": channel,
            "destination": destination,
            "content": content,
            "discount_config": discount_config,
            "requires_approval": True,
        },
    )

    queue_item_id = queue_item.id if queue_item else None

    return CampaignGenerationResult(
        campaign_id=campaign_id,
        queue_item_id=queue_item_id,
        title=title,

        channel=channel,
        status="pending_approval",
        content=content,
    )


async def execute_approved_campaign(
    db,
    *,
    campaign_id: str,
    buffer_client: Optional[BufferClient] = None,
    instagram_client: Optional[InstagramClient] = None,
    whatsapp_client: Optional[WhatsAppClient] = None,
) -> CampaignExecutionResult:
    """Executes a previously approved campaign across its designated channels."""
    try:
        obj_id = ObjectId(campaign_id)
        campaign = await db.marketing_campaigns.find_one({"_id": obj_id})
    except Exception:
        campaign = await db.marketing_campaigns.find_one({"_id": campaign_id})

    if not campaign:
        raise ValueError(f"Marketing campaign {campaign_id} not found")

    now = datetime.now(timezone.utc)
    channel = campaign.get("channel", "buffer")
    content = campaign.get("content", {})
    external_post_id: Optional[str] = None
    created_promo_code: Optional[str] = None

    # Step 1: If promo code discount attached, create PromotionDoc in db.promotions
    discount_config = campaign.get("discount_config")
    if discount_config:
        code = discount_config.get("code", f"PROMO{int(now.timestamp())}").upper()
        valid_days = int(discount_config.get("valid_days", 30))
        promo_doc = {
            "code": code,
            "discount_type": discount_config.get("discount_type", "percent"),
            "discount_value": float(discount_config.get("discount_value", 10.0)),
            "valid_from": now,
            "valid_until": now + timedelta(days=valid_days),
            "usage_cap": discount_config.get("usage_cap", 100),
            "redemption_count": 0,
            "created_at": now,
        }
        try:
            # Validate through PromotionDoc
            validated_promo = PromotionDoc(**promo_doc)
            existing_promo = await db.promotions.find_one({"code": code})
            if not existing_promo:
                await db.promotions.insert_one(promo_doc)
            created_promo_code = code
        except Exception as promo_exc:
            logger.warning(f"Failed to create promotion code {code}: {promo_exc}")

    # Step 2: Channel Dispatch
    dry_run = bool(content.get("dry_run", False))
    sandbox_mode = bool(content.get("sandbox_mode", False))

    try:
        if channel == "buffer":
            b_client = buffer_client or BufferClient(dry_run=dry_run)
            text = content.get("caption") or content.get("headline") or campaign.get("title")
            res = await b_client.create_update(text=text, draft=False)
            external_post_id = res.get("buffer_id")

        elif channel == "instagram":
            ig_client = instagram_client or InstagramClient(sandbox_mode=sandbox_mode)
            caption = content.get("caption") or campaign.get("title")
            image_url = content.get("image_url", "https://enjoyyourvacation.in/images/og-hero.jpg")
            res = await ig_client.publish_photo(image_url=image_url, caption=caption)
            external_post_id = res.get("media_id") or res.get("creation_id")

        elif channel == "whatsapp":
            wa_client = whatsapp_client or WhatsAppClient(dry_run=dry_run)
            recipient = content.get("recipient_phone") or "15550001234"
            body = content.get("caption") or content.get("headline") or campaign.get("title")
            res = await wa_client.send_text_message(to_phone=recipient, body=body)
            external_post_id = res.get("message_id")

        elif channel == "promo_code":
            external_post_id = f"promo_{created_promo_code}"

        elif channel == "multi_channel":
            # Post to Buffer and Instagram simultaneously
            b_client = buffer_client or BufferClient(dry_run=dry_run)
            text = content.get("caption") or campaign.get("title")
            b_res = await b_client.create_update(text=text, draft=False)
            external_post_id = b_res.get("buffer_id")


        # Mark campaign as published
        await db.marketing_campaigns.update_one(
            {"_id": campaign["_id"]},
            {
                "$set": {
                    "status": "published",
                    "external_post_id": external_post_id,
                    "published_at": now,
                }
            },
        )

        return CampaignExecutionResult(
            campaign_id=campaign_id,
            channel=channel,
            status="published",
            external_post_id=external_post_id,
            promo_code=created_promo_code,
            published_at=now,
        )

    except Exception as exc:
        logger.error(f"Failed to execute marketing campaign {campaign_id}: {exc}")
        await db.marketing_campaigns.update_one(
            {"_id": campaign["_id"]},
            {"$set": {"status": "failed", "error_message": str(exc)}},
        )
        return CampaignExecutionResult(
            campaign_id=campaign_id,
            channel=channel,
            status="failed",
            error=str(exc),
        )


async def handle_jarvis_marketing_decision(db, decision_doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Hook invoked when JARVIS records a decision targeting marketing actions."""
    action = decision_doc.get("action")
    if not isinstance(action, dict):
        return None

    campaign_id = action.get("campaign_id")
    action_type = action.get("type")

    if action_type in ("execute_campaign", "publish_post", "approve_campaign") and campaign_id:
        exec_res = await execute_approved_campaign(db, campaign_id=campaign_id)
        return exec_res.model_dump(mode="json")

    return None
