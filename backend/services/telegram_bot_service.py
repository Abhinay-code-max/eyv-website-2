"""
Telegram Bot Bridge Service - Executive Command & Push Notification Center.

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

from db_models import AdminAuditLogDoc
from services.marketing_agent_service import generate_campaign_draft, resolve_campaign_image

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


# ── Rich Push Notification Card Generator ──────────────────────────────────

async def send_queue_alert(
    db,
    queue_item: Dict[str, Any],
    http_client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Formats and dispatches a rich notification card to the admin Telegram chat."""
    config = _get_telegram_config()
    admin_chat_id = config["admin_chat_id"]
    if not admin_chat_id or not config["bot_token"]:
        return {"success": False, "skipped": True}

    q_id = str(queue_item.get("id") or queue_item.get("_id") or "")
    source_agent = str(queue_item.get("source_agent", "jarvis")).upper()
    item_type = str(queue_item.get("item_type", "task"))
    priority = int(queue_item.get("priority", 5))
    payload = queue_item.get("payload") or {}

    priority_badge = "🔴 <b>PRIORITY 1 (CRITICAL)</b>" if priority == 1 else f"🟡 <b>Priority {priority} (Normal)</b>"
    
    # 1. Bob Marketing Campaign Alert
    if source_agent == "BOB" or item_type == "campaign_approval":
        destination = payload.get("destination", "Featured Destination")
        discount = payload.get("discount_percent")
        channel = payload.get("channel", "multi_channel")
        summary = payload.get("summary") or payload.get("title") or "New Campaign Proposal"
        campaign_id = payload.get("campaign_id", "")
        photo_url = payload.get("image_url") or resolve_campaign_image(destination)

        text = (
            f"🤖 <b>JARVIS Alert: Bob Campaign Proposal</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{priority_badge}\n"
            f"📍 <b>Destination:</b> {destination}\n"
            f"🎟 <b>Discount:</b> {discount}%\n"
            f"📢 <b>Channel:</b> {channel}\n"
            f"📝 <b>Summary:</b> {summary}\n"
            f"🆔 <code>#{q_id[-6:] if len(q_id) >= 6 else q_id}</code>\n"
        )
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "✅ Approve & Execute", "callback_data": f"approve:{q_id}:{campaign_id}"},
                    {"text": "❌ Reject", "callback_data": f"reject:{q_id}"},
                ]
            ]
        }
        return await send_telegram_message(
            chat_id=admin_chat_id,
            text=text,
            reply_markup=reply_markup,
            photo_url=photo_url,
            http_client=http_client,
        )

    # 2. Denver Customer Support Escalation Alert
    elif source_agent == "DENVER" or item_type in ("support_escalation", "ticket_review"):
        ticket_id = payload.get("ticket_id") or payload.get("id") or ""
        reporters = payload.get("reporters_count", 1)
        summary = payload.get("summary") or payload.get("title") or "Customer Escalation"

        text = (
            f"🆘 <b>DENVER ESCALATION: Customer Support</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{priority_badge}\n"
            f"👥 <b>Reporters Count:</b> {reporters}\n"
            f"📝 <b>Issue:</b> {summary}\n"
            f"🎫 <b>Ticket ID:</b> <code>{ticket_id}</code>\n"
            f"🆔 <code>#{q_id[-6:] if len(q_id) >= 6 else q_id}</code>\n"
        )
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "✅ Mark Resolved", "callback_data": f"resolve_ticket:{ticket_id}:{q_id}"},
                    {"text": "🔕 Dismiss", "callback_data": f"reject:{q_id}"},
                ]
            ]
        }
        return await send_telegram_message(
            chat_id=admin_chat_id,
            text=text,
            reply_markup=reply_markup,
            http_client=http_client,
        )

    # 3. Sara Analytics Anomaly Alert
    elif source_agent == "SARA" or "anomaly" in item_type or "billing" in item_type or "cancellation" in item_type:
        metric = payload.get("metric", item_type)
        summary = payload.get("summary", "Metric Anomaly Detected")

        text = (
            f"🚨 <b>SARA EMERGENCY ALERT: Metric Anomaly</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{priority_badge}\n"
            f"📊 <b>Metric:</b> {metric}\n"
            f"⚠️ <b>Details:</b> {summary}\n"
            f"🆔 <code>#{q_id[-6:] if len(q_id) >= 6 else q_id}</code>\n"
        )
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "🔕 Acknowledge / Dismiss", "callback_data": f"reject:{q_id}"},
                ]
            ]
        }
        return await send_telegram_message(
            chat_id=admin_chat_id,
            text=text,
            reply_markup=reply_markup,
            http_client=http_client,
        )

    # 4. General Queue Item Fallback
    text = (
        f"🤖 <b>JARVIS Coordination Alert</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{priority_badge}\n"
        f"🏷 <b>Agent:</b> {source_agent} | <b>Type:</b> {item_type}\n"
        f"📝 {payload.get('summary') or payload.get('title') or 'Pending Action'}\n"
        f"🆔 <code>#{q_id[-6:] if len(q_id) >= 6 else q_id}</code>\n"
    )
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "✅ Acknowledge", "callback_data": f"approve:{q_id}"},
                {"text": "❌ Dismiss", "callback_data": f"reject:{q_id}"},
            ]
        ]
    }
    return await send_telegram_message(
        chat_id=admin_chat_id,
        text=text,
        reply_markup=reply_markup,
        http_client=http_client,
    )


# ── Interactive Callback Query Handler ─────────────────────────────────────

async def handle_telegram_callback_query(
    db,
    callback_query: Dict[str, Any],
    internal_ticket_client: Optional[httpx.AsyncClient] = None,
    http_client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Handles inline button clicks in Telegram and routes decisions/resolutions."""
    now = datetime.now(timezone.utc)
    cb_id = str(callback_query.get("id"))
    from_user = callback_query.get("from") or {}
    user_id = str(from_user.get("id"))
    message = callback_query.get("message") or {}
    chat_id = str(message.get("chat", {}).get("id") or user_id)
    message_id = message.get("message_id")
    data = str(callback_query.get("data") or "")

    config = _get_telegram_config()
    admin_chat_id = str(config["admin_chat_id"] or "")

    # Security check: verify chat_id matches whitelist
    if chat_id != admin_chat_id and user_id != admin_chat_id:
        logger.warning(f"Unauthorized Telegram callback query from user {user_id}")
        await answer_callback_query(cb_id, text="Unauthorized: Admin chat only", http_client=http_client)
        return {"status": "unauthorized"}

    # 1. Approve & Execute Decision (Bob Campaign or Queue Item)
    if data.startswith("approve:"):
        parts = data.split(":")
        q_id = parts[1]
        campaign_id = parts[2] if len(parts) > 2 and parts[2] else None

        # Acknowledge callback immediately
        await answer_callback_query(cb_id, text="Executing approval...", http_client=http_client)

        # Update queue item
        try:
            await db.jarvis_queue_items.update_one(
                {"_id": ObjectId(q_id)},
                {"$set": {"status": "resolved", "resolved_at": now}},
            )
        except Exception:
            pass

        # Record decision
        action: Dict[str, Any] = {"type": "execute_campaign"}
        if campaign_id:
            action["campaign_id"] = campaign_id

        dec_doc = {
            "queue_item_id": q_id,
            "source_agent": f"telegram:{user_id}",
            "decision_type": "telegram_approval",
            "action": action,
            "reason": "Approved by Abhinay via Telegram Bot",
            "resolution_status": "resolved",
            "created_at": now,
        }
        await db.jarvis_decisions.insert_one(dec_doc)

        # Execute campaign via Bob if campaign_id present
        if campaign_id:
            from services.marketing_agent_service import handle_jarvis_marketing_decision
            await handle_jarvis_marketing_decision(db, dec_doc)

        # Record audit log
        await db.admin_audit_log.insert_one({
            "timestamp": now,
            "route": "/api/webhooks/telegram",
            "method": "POST",
            "admin_identity": f"telegram:{user_id}",
            "client_ip": "telegram_api",
            "status_code": 200,
            "action": "telegram_approve_campaign",
            "details": {"queue_item_id": q_id, "campaign_id": campaign_id},
        })

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

        # Route through internal_tickets_api (PATCH /api/internal/tickets/{ticket_id})
        try:
            token = os.environ.get("INTERNAL_TICKET_API_TOKEN", "")
            headers = {"Authorization": f"Bearer {token}"}
            patch_payload = {
                "status": "resolved",
                "resolution_note": "Resolved by Abhinay via Telegram Bot",
            }
            if internal_ticket_client is not None:
                await internal_ticket_client.patch(
                    f"/api/internal/tickets/{ticket_id}",
                    json=patch_payload,
                    headers=headers,
                )
            else:
                # Direct service fallback with audit
                await db.tickets.update_one(
                    {"$or": [{"_id": ObjectId(ticket_id) if ObjectId.is_valid(ticket_id) else None}, {"ticket_id": ticket_id}]},
                    {"$set": {"status": "resolved", "resolution_note": patch_payload["resolution_note"], "updated_at": now}},
                )
                await db.ticket_agent_audit_log.insert_one({
                    "timestamp": now,
                    "route": f"/api/internal/tickets/{ticket_id}",
                    "method": "PATCH",
                    "caller_ip": "telegram_bot",
                    "status_code": 200,
                    "action": "telegram_resolve_ticket",
                    "ticket_id": ticket_id,
                })
        except Exception as exc:
            logger.warning(f"Error resolving ticket {ticket_id} via internal ticket route: {exc}")

        # Mark linked queue item resolved
        if q_id:
            try:
                await db.jarvis_queue_items.update_one(
                    {"_id": ObjectId(q_id)},
                    {"$set": {"status": "resolved", "resolved_at": now}},
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
            await db.jarvis_queue_items.update_one(
                {"_id": ObjectId(q_id)},
                {"$set": {"status": "rejected", "resolved_at": now}},
            )
        except Exception:
            pass

        await db.admin_audit_log.insert_one({
            "timestamp": now,
            "route": "/api/webhooks/telegram",
            "method": "POST",
            "admin_identity": f"telegram:{user_id}",
            "client_ip": "telegram_api",
            "status_code": 200,
            "action": "telegram_reject_item",
            "details": {"queue_item_id": q_id},
        })

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
        pending_count = await db.jarvis_queue_items.count_documents({"status": "pending"})
        open_tickets = await db.tickets.count_documents({"status": {"$in": ["open", "in_progress"]}})
        campaigns_count = await db.marketing_campaigns.count_documents({"status": "published"})

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
        cursor = db.jarvis_queue_items.find({"status": "pending"}).sort([("priority", 1), ("created_at", 1)]).limit(5)
        items = await cursor.to_list(5)
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

        # Enforce 5% - 50% discount bound
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
        campaigns = await db.marketing_campaigns.count_documents({})
        tickets = await db.tickets.count_documents({})
        promos = await db.promotions.count_documents({})
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
        admin_chat_id = str(config["admin_chat_id"] or "")

        if chat_id != admin_chat_id and user_id != admin_chat_id:
            logger.warning(f"Unauthorized Telegram message from user {user_id}")
            return {"status": "unauthorized"}

        if text.startswith("/"):
            return await handle_telegram_command(db, text, chat_id, http_client=http_client)

    return {"status": "ignored"}
