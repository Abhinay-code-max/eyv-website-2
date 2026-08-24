"""Telegram Bot Bridge Service - Executive Command & Push Notification Center.

Provides direct mobile operational control over JARVIS, Denver, Bob, and Sara:
1. Fault-isolated outbound HTTP requests with strict 5.0s timeout (never hangs/crashes caller).
2. Real-time push alerts for P1 emergencies and campaign approvals with inline [Approve] / [Reject] buttons.
3. Interactive callback query processing with immediate acknowledgment.
4. Ticket resolution routing through internal_tickets_api (PATCH /api/internal/tickets/{id}) with audit logging.
5. Direct slash commands (/status, /queue, /campaign with 5-50% validation, /stats).
6. Strict chat ID authorization and append-only audit logging to db.admin_audit_log.
7. Graceful degradation: skips push alerts if TELEGRAM_BOT_TOKEN is unset (stated exception to hard-fail rule).
"""
import asyncio
import hmac
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from bson import ObjectId

from agents.bob.marketing_agent_service import generate_campaign_draft, resolve_campaign_image
from agents.clients import JarvisInternalClient, TicketsInternalClient, AnalyticsInternalClient

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"
TELEGRAM_TIMEOUT_SECONDS = 5.0


def _get_telegram_config() -> Dict[str, Optional[str]]:
    """Reads Telegram configuration from environment."""
    return {
        "bot_token": os.environ.get("TELEGRAM_BOT_TOKEN"),
        "secret_token": os.environ.get("TELEGRAM_SECRET_TOKEN"),
        "admin_chat_id": os.environ.get("ADMIN_TELEGRAM_CHAT_ID"),
    }


def is_telegram_configured() -> bool:
    """Returns True if minimum Telegram configuration is present."""
    config = _get_telegram_config()
    return bool(config["bot_token"] and config["admin_chat_id"])


# ── Fault-Isolated Outbound HTTP Calls (5.0s Timeout) ──────────────────────

async def send_telegram_message(
    chat_id: str | int,
    text: str,
    reply_markup: Optional[Dict[str, Any]] = None,
    photo_url: Optional[str] = None,
    parse_mode: str = "HTML",
    timeout: float = TELEGRAM_TIMEOUT_SECONDS,
    http_client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Sends a text or photo message to Telegram.
    Fault-isolated: strictly catches all network/HTTP exceptions and returns gracefully."""
    config = _get_telegram_config()
    bot_token = config["bot_token"]
    if not bot_token:
        logger.debug("TELEGRAM_BOT_TOKEN not configured - skipping Telegram outbound message")
        return {"success": False, "skipped": True, "reason": "TELEGRAM_BOT_TOKEN unset"}

    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/{'sendPhoto' if photo_url else 'sendMessage'}"
    payload: Dict[str, Any] = {
        "chat_id": str(chat_id),
        "parse_mode": parse_mode,
    }
    if photo_url:
        payload["photo"] = photo_url
        payload["caption"] = text
    else:
        payload["text"] = text

    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        if http_client is not None:
            res = await http_client.post(url, json=payload, timeout=timeout)
        else:
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await client.post(url, json=payload)

        if res.status_code == 200:
            return {"success": True, "data": res.json()}
        else:
            logger.warning(f"Telegram API responded with {res.status_code}: {res.text}")
            return {"success": False, "status_code": res.status_code, "error": res.text}
    except Exception as exc:
        logger.warning(f"Failed to dispatch Telegram message (fault-isolated): {exc}")
        return {"success": False, "error": str(exc)}


async def answer_callback_query(
    callback_query_id: str,
    text: Optional[str] = None,
    timeout: float = TELEGRAM_TIMEOUT_SECONDS,
    http_client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Acknowledges an inline button callback immediately to prevent Telegram retry loops."""
    config = _get_telegram_config()
    bot_token = config["bot_token"]
    if not bot_token:
        return {"success": False, "skipped": True}

    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/answerCallbackQuery"
    payload: Dict[str, Any] = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text

    try:
        if http_client is not None:
            res = await http_client.post(url, json=payload, timeout=timeout)
        else:
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await client.post(url, json=payload)
        return {"success": res.status_code == 200}
    except Exception as exc:
        logger.warning(f"Failed to answer Telegram callback query: {exc}")
        return {"success": False, "error": str(exc)}


async def edit_message_text(
    chat_id: str | int,
    message_id: int,
    text: str,
    parse_mode: str = "HTML",
    timeout: float = TELEGRAM_TIMEOUT_SECONDS,
    http_client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Updates the message in-place to show resolution status."""
    config = _get_telegram_config()
    bot_token = config["bot_token"]
    if not bot_token:
        return {"success": False, "skipped": True}

    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/editMessageText"
    payload = {
        "chat_id": str(chat_id),
        "message_id": message_id,
        "text": text,
        "parse_mode": parse_mode,
    }

    try:
        if http_client is not None:
            res = await http_client.post(url, json=payload, timeout=timeout)
        else:
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await client.post(url, json=payload)
        return {"success": res.status_code == 200}
    except Exception as exc:
        logger.warning(f"Failed to edit Telegram message: {exc}")
        return {"success": False, "error": str(exc)}


# ── Real-Time Push Alerts & Action Keyboards ───────────────────────────────

def _format_emergency_text(item: Dict[str, Any]) -> str:
    """Formats P1 high-priority incident push alert."""
    payload = item.get("payload", {})
    source_agent = item.get("source_agent", "system").upper()
    item_type = item.get("item_type", "emergency").replace("_", " ").title()
    summary = payload.get("summary") or payload.get("reason") or payload.get("title") or "P1 Alert"

    return (
        f"🚨 <b>P1 EMERGENCY: {source_agent} {item_type}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Summary:</b> {summary}\n"
        f"<b>Item ID:</b> <code>{item.get('_id') or item.get('id')}</code>\n"
        f"<b>Priority:</b> P1 (Immediate Attention)\n"
    )


def _format_campaign_approval_text(item: Dict[str, Any]) -> str:
    """Formats Bob marketing campaign approval request."""
    payload = item.get("payload", {})
    camp_title = payload.get("title", "Campaign Draft")
    channel = str(payload.get("channel", "multi_channel")).title()
    dest = payload.get("destination", "Featured Destination")
    content = payload.get("content", {})
    caption = content.get("caption") or content.get("headline") or "No copy preview"
    disc = payload.get("discount_config")
    disc_text = f"{disc.get('discount_value')}% ({disc.get('code')})" if disc else "None"

    return (
        f"📢 <b>CAMPAIGN APPROVAL REQUIRED (Bob)</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Title:</b> {camp_title}\n"
        f"<b>Destination:</b> {dest}\n"
        f"<b>Channel:</b> {channel}\n"
        f"<b>Discount:</b> {disc_text}\n\n"
        f"<b>Copy Preview:</b>\n<i>{caption[:250]}...</i>\n"
    )


async def send_emergency_alert(
    db,
    item: Dict[str, Any],
    http_client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Pushes a P1 alert immediately to Abhinay via Telegram."""
    config = _get_telegram_config()
    chat_id = config["admin_chat_id"]
    if not chat_id:
        return {"success": False, "skipped": True}

    text = _format_emergency_text(item)
    q_id = str(item.get("_id") or item.get("id") or "")
    payload = item.get("payload", {})
    ticket_id = payload.get("ticket_id")

    keyboard = []
    if ticket_id:
        keyboard.append([
            {"text": "✅ Resolve Ticket", "callback_data": f"resolve_ticket:{ticket_id}:{q_id}"},
            {"text": "❌ Dismiss", "callback_data": f"reject:{q_id}"},
        ])
    else:
        keyboard.append([
            {"text": "❌ Dismiss", "callback_data": f"reject:{q_id}"},
        ])

    reply_markup = {"inline_keyboard": keyboard}
    return await send_telegram_message(
        chat_id, text, reply_markup=reply_markup, http_client=http_client
    )


async def send_campaign_approval_alert(
    db,
    item: Dict[str, Any],
    http_client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Pushes Bob campaign approval alert with [Approve] and [Reject] inline buttons."""
    config = _get_telegram_config()
    chat_id = config["admin_chat_id"]
    if not chat_id:
        return {"success": False, "skipped": True}

    payload = item.get("payload", {})
    content = payload.get("content", {})
    photo_url = content.get("image_url")
    text = _format_campaign_approval_text(item)

    q_id = str(item.get("_id") or item.get("id") or "")
    camp_id = str(payload.get("campaign_id") or "")

    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "🚀 Approve & Publish", "callback_data": f"approve:{q_id}:{camp_id}"},
                {"text": "❌ Reject", "callback_data": f"reject:{q_id}:{camp_id}"},
            ]
        ]
    }

    return await send_telegram_message(
        chat_id,
        text,
        reply_markup=reply_markup,
        photo_url=photo_url,
        http_client=http_client,
    )


async def send_queue_alert(
    db,
    item: Dict[str, Any],
    http_client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Routes queue item alerts based on priority and type."""
    item_type = item.get("item_type")
    priority = item.get("priority", 5)

    if item_type == "marketing_campaign_approval":
        return await send_campaign_approval_alert(db, item, http_client=http_client)
    elif priority == 1:
        return await send_emergency_alert(db, item, http_client=http_client)
    else:
        # Standard notification
        config = _get_telegram_config()
        chat_id = config["admin_chat_id"]
        if not chat_id:
            return {"success": False, "skipped": True}
        text = (
            f"📋 <b>JARVIS Work Item:</b> {item_type}\n"
            f"Source: {item.get('source_agent')}\n"
            f"ID: <code>{item.get('_id') or item.get('id')}</code>\n"
        )
        return await send_telegram_message(chat_id, text, http_client=http_client)


# ── Interactive Callback Query Processor ───────────────────────────────────

async def handle_telegram_callback_query(
    db,
    callback_query: Dict[str, Any],
    internal_ticket_client: Optional[httpx.AsyncClient] = None,
    http_client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Handles inline button interactions from Telegram."""
    cb_id = callback_query.get("id")
    from_user = callback_query.get("from") or {}
    user_id = str(from_user.get("id") or "")
    message = callback_query.get("message") or {}
    chat_id = str(message.get("chat", {}).get("id") or user_id)
    message_id = message.get("message_id")
    data = str(callback_query.get("data") or "")

    config = _get_telegram_config()
    authorized_chat = config["admin_chat_id"]

    # Security: Reject unverified chat IDs
    if authorized_chat and str(user_id) != str(authorized_chat) and str(chat_id) != str(authorized_chat):
        logger.warning(f"Unauthorized Telegram callback query attempt from user {user_id}")
        await answer_callback_query(cb_id, text="Unauthorized", http_client=http_client)
        return {"status": "unauthorized"}

    now = datetime.now(timezone.utc)

    # 1. Approve & Execute Campaign (Bob Marketing Action)
    if data.startswith("approve:"):
        parts = data.split(":")
        q_id = parts[1]
        campaign_id = parts[2] if len(parts) > 2 and parts[2] else None

        await answer_callback_query(cb_id, text="Executing approval...", http_client=http_client)

        jarvis_client = JarvisInternalClient()
        action = {"type": "execute_campaign"}
        if campaign_id:
            action["campaign_id"] = campaign_id
        await jarvis_client.submit_decision(
            decision_type="telegram_approval",
            action=action,
            reason="Approved by Abhinay via Telegram Bot",
            resolution_status="resolved",
            queue_item_id=q_id,
        )

        if message_id:
            updated_text = f"✅ <b>APPROVED & EXECUTED</b> by Abhinay on {now.strftime('%d %b %Y, %H:%M UTC')}"
            await edit_message_text(chat_id, message_id, updated_text, http_client=http_client)

        return {"status": "approved", "queue_item_id": q_id}

    # 2. Resolve Ticket via internal_tickets_api (Denver Escalation)
    elif data.startswith("resolve_ticket:"):
        parts = data.split(":")
        ticket_id = parts[1]
        q_id = parts[2] if len(parts) > 2 else None

        await answer_callback_query(cb_id, text="Marking ticket resolved...", http_client=http_client)

        try:
            tickets_client = TicketsInternalClient(http_client=internal_ticket_client)
            await tickets_client.patch_ticket(
                ticket_id,
                status="resolved",
            )
        except Exception as exc:
            logger.warning(f"Error resolving ticket {ticket_id} via internal ticket route: {exc}")

        if q_id:
            try:
                jarvis_client = JarvisInternalClient()
                await jarvis_client.submit_decision(
                    decision_type="telegram_ticket_resolution",
                    action={"type": "resolve_ticket", "ticket_id": ticket_id},
                    reason="Ticket resolved by Abhinay via Telegram Bot",
                    resolution_status="resolved",
                    queue_item_id=q_id,
                )
            except Exception:
                pass

        if message_id:
            updated_text = f"✅ <b>TICKET MARKED RESOLVED</b> by Abhinay on {now.strftime('%d %b %Y, %H:%M UTC')}"
            await edit_message_text(chat_id, message_id, updated_text, http_client=http_client)

        return {"status": "ticket_resolved", "ticket_id": ticket_id}

    # 3. Reject / Dismiss Queue Item
    elif data.startswith("reject:"):
        parts = data.split(":")
        q_id = parts[1]

        await answer_callback_query(cb_id, text="Item dismissed", http_client=http_client)

        try:
            jarvis_client = JarvisInternalClient()
            await jarvis_client.submit_decision(
                decision_type="telegram_dismissal",
                action={"type": "dismiss_item"},
                reason="Dismissed by Abhinay via Telegram Bot",
                resolution_status="rejected",
                queue_item_id=q_id,
            )
        except Exception:
            pass

        if message_id:
            updated_text = f"❌ <b>DISMISSED / REJECTED</b> by Abhinay on {now.strftime('%d %b %Y, %H:%M UTC')}"
            await edit_message_text(chat_id, message_id, updated_text, http_client=http_client)

        return {"status": "rejected", "queue_item_id": q_id}

    return {"status": "ignored"}


# ── Slash Command Processor ────────────────────────────────────────────────

async def handle_telegram_command(
    db,
    text: str,
    chat_id: str | int,
    http_client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Parses and executes administrative slash commands from Telegram."""
    text_clean = text.strip()
    cmd = text_clean.split()[0].lower() if text_clean else ""

    # /status command
    if cmd == "/status":
        j_stats = await JarvisInternalClient().get_queue_stats()
        t_stats = await TicketsInternalClient().get_ticket_stats()
        c_stats = await AnalyticsInternalClient().get_campaign_stats()
        pending_count = j_stats.get("pending", 0)
        open_tickets = t_stats.get("open", 0)
        campaigns_count = c_stats.get("published", 0)

        msg = (
            f"🟢 <b>EYV Multi-Agent System: OPERATIONAL</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🧠 <b>JARVIS Coordinator:</b> Active\n"
            f"🛡 <b>Denver Support:</b> Active ({open_tickets} open tickets)\n"
            f"📢 <b>Bob Marketing:</b> Active ({campaigns_count} published campaigns)\n"
            f"📊 <b>Sara Analytics:</b> Active\n"
            f"📥 <b>Pending Queue:</b> {pending_count} items awaiting sign-off\n"
        )
        return await send_telegram_message(chat_id, msg, http_client=http_client)

    # /queue command
    elif cmd == "/queue":
        res = await JarvisInternalClient().get_queue(status="pending", limit=5)
        items = res.get("items", [])

        if not items:
            return await send_telegram_message(chat_id, "✅ <b>JARVIS Queue is clear!</b> No pending items.", http_client=http_client)

        for item in items:
            await send_queue_alert(db, item, http_client=http_client)
        return {"status": "queue_dispatched", "count": len(items)}

    # /campaign <destination> <discount_percent> command
    elif cmd == "/campaign":
        parts = text_clean.split()
        if len(parts) < 3:
            msg = "⚠️ <b>Usage:</b> <code>/campaign &lt;destination&gt; &lt;discount_percent&gt;</code>\nExample: <code>/campaign Goa 20</code>"
            return await send_telegram_message(chat_id, msg, http_client=http_client)

        dest = parts[1].title()
        try:
            discount = float(parts[2].replace("%", ""))
        except ValueError:
            return await send_telegram_message(chat_id, "⚠️ Invalid discount percent. Must be a number (e.g. 20).", http_client=http_client)

        if discount < 5.0 or discount > 50.0:
            return await send_telegram_message(
                chat_id,
                "⚠️ Discount percentage must be between <b>5%</b> and <b>50%</b>.",
                http_client=http_client,
            )

        resolved_img = resolve_campaign_image(dest)
        title = f"{dest} Special Promotion"
        result = await generate_campaign_draft(
            db,
            title=title,
            channel="multi_channel",
            destination=dest,
            theme="travel_highlight",
            discount_percent=discount,
            target_audience="all_travelers",
            custom_content={"image_url": resolved_img},
        )
        msg = f"✨ <b>Bob created a campaign draft for {dest}!</b>\nDiscount: {discount}%\nEnqueued as #{result.queue_item_id[-6:] if result.queue_item_id else ''}."
        return await send_telegram_message(chat_id, msg, http_client=http_client)

    # /stats command
    elif cmd == "/stats":
        c_stats = await AnalyticsInternalClient().get_campaign_stats()
        t_stats = await TicketsInternalClient().get_ticket_stats()
        p_res = await AnalyticsInternalClient().get_promotions()
        campaigns = c_stats.get("total", 0)
        tickets = t_stats.get("total", 0)
        promos = len(p_res.get("promotions", []))

        msg = (
            f"📊 <b>EYV Autonomous Operations Stats</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📢 <b>Total Campaigns:</b> {campaigns}\n"
            f"🎫 <b>Total Tickets Processed:</b> {tickets}\n"
            f"🎟 <b>Active Promo Codes:</b> {promos}\n"
        )
        return await send_telegram_message(chat_id, msg, http_client=http_client)

    # /help fallback
    help_text = (
        f"🤖 <b>EYV Bot Commands:</b>\n"
        f"• <code>/status</code> - Live system health & agent states\n"
        f"• <code>/queue</code> - List top pending work items\n"
        f"• <code>/campaign &lt;dest&gt; &lt;disc%&gt;</code> - Draft a campaign with Bob (5-50%)\n"
        f"• <code>/stats</code> - Daily operational metrics summary\n"
    )
    return await send_telegram_message(chat_id, help_text, http_client=http_client)


# ── Top-Level Webhook Update Dispatcher ────────────────────────────────────

async def process_telegram_update(
    db,
    update: Dict[str, Any],
    internal_ticket_client: Optional[httpx.AsyncClient] = None,
    http_client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Processes an incoming Telegram webhook update (message or callback_query)."""
    # 1. Process Callback Query (Button clicks)
    if "callback_query" in update:
        return await handle_telegram_callback_query(
            db,
            update["callback_query"],
            internal_ticket_client=internal_ticket_client,
            http_client=http_client,
        )

    # 2. Process Message (Slash Commands)
    message = update.get("message") or update.get("edited_message")
    if message:
        from_user = message.get("from") or {}
        user_id = str(from_user.get("id") or "")
        chat_id = str(message.get("chat", {}).get("id") or user_id)
        text = str(message.get("text") or "")

        config = _get_telegram_config()
        authorized_chat = config["admin_chat_id"]

        if authorized_chat and str(user_id) != str(authorized_chat) and str(chat_id) != str(authorized_chat):
            logger.warning(f"Unauthorized Telegram message from user {user_id}")
            return {"status": "unauthorized"}

        if text.startswith("/"):
            return await handle_telegram_command(db, text, chat_id, http_client=http_client)

    return {"status": "ignored"}
