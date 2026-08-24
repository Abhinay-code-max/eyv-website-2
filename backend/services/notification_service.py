"""
EYV notification service - Phase 4, Step 4.3 of the EYV Agent System roadmap.

Fans out a ticket status transition (implemented|rejected|backlog) to every
reporter on that ticket, on two channels: email (durable, off-platform) and
an in-app `notifications` document (best-effort, for the product's eventual
bell/list UI - Step 4.4, not built here).

WHEN THIS RUNS: notify_ticket_status_change is a function you CALL with
(ticket_id, new_status) - not a poller. Nothing in Phase 4 actually drives a
ticket to implemented/rejected/backlog yet (that's Phase 5's bug-fix-agent
automation); whatever eventually makes that PATCH call through
internal_tickets_api.py is expected to call this function right after that
PATCH succeeds. Building a poller for a trigger that doesn't exist yet would
be speculative infrastructure with nothing to test it against - see the
module's own git history for a codebase-wide preference against exactly that
(booking_expiry_service.py / generation_expiry_service.py exist BECAUSE they
guard against a real failure mode - a background task crashing mid-flight -
not as poller-by-default plumbing).

EMAIL PROVIDER: Resend, not Postmark. For a solo-dev, low-volume,
transactional-only send pattern, the deciding factors were:
  - Free tier that actually covers this: 3,000 emails/month / 100/day with
    no credit card, comfortably above what a ticket-notification volume
    will ever hit. Postmark's free allowance is far smaller and account
    approval can gate sending until it's manually reviewed - friction with
    no payoff at this volume.
  - API simplicity: one POST to /emails with a flat JSON body
    (from/to/subject/text/html) and a bearer token - no "message streams"
    or server/account hierarchy to configure first, matching how small
    every other outbound integration in this app is (see EmailClient
    below).
  - Deliverability reputation is good on both at this volume - not the
    deciding factor here, since a low-volume transactional sender doesn't
    stress either provider's infrastructure enough for their reputation
    differences to matter.
EmailClient (below) is deliberately generic - to/subject/text/html only,
nothing ticket-shaped on the class itself - so it's the same client this
app's eventual booking/plan-confirmation emails can reuse; only the
_render_status_email templates below are ticket-specific.

HTTP-ONLY, SAME AS 4.1/4.2: this module never touches db.tickets - every
ticket read/write goes through internal_tickets_api.py (GET /{id} to read
the ticket's current reporter_user_ids/notified_user_ids/title - added in
this step for exactly this need - and POST /{id}/notify to record who got
notified, both Bearer-token authenticated, both already-existing/extended
infra rather than a bypass). This module DOES read db.users directly
(_lookup_user_email) - unlike internal_tickets_api.py, which is deliberately
scoped away from db.users, this service's whole job requires knowing where
to send an email, so that's not a boundary it makes sense to route through
the ticket API instead.

IDEMPOTENCY: TicketDoc.notified_user_ids (Step 1.1) is the single source of
truth. A reporter already in that list is skipped entirely - no email sent,
no in-app row created, no HTTP calls made for them at all. A reporter is
only added to notified_user_ids if their EMAIL send succeeds; the in-app
notification is created alongside it but is best-effort (logged if it
fails, doesn't block marking them notified, and doesn't get retried) -
email is the channel a reporter will actually see even if they never
revisit the product again, so "notified" is gated on that, not on the
in-app copy. If email fails, the reporter is NOT marked notified, so a
later re-run of this same function retries them - and per-reporter
failures don't stop the other reporters on the same ticket, since each
reporter's send/mark-notified is independent.

KNOWN LIMITATION: notified_user_ids is one flat list per ticket (Step 1.1's
existing shape, not something this step remodels), so it doesn't distinguish
WHICH status transition a reporter was already notified about. A ticket
that transitioned to one notifiable status and later to a DIFFERENT
notifiable status would skip a reporter already in that list from the
first transition. Nothing in this app currently produces that path (these
three statuses are meant to be terminal-ish outcomes of the triage
workflow), so this is a documented edge case, not a fixed one.

FAILURE LOGGING: via the standard app logger (logger.error), not
generation_logs (that collection is specifically redacted Gemini
prompt/response pairs - see its own docstring in db_models.py, a bad fit
for an email-send failure) and not a new dedicated Mongo collection (a log
line is sufficient for a failure this low-volume and non-critical-path,
the same choice _AuditedTicketRoute makes for its own audit-write
failures)."""
import functools
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

import httpx

from db_models import NOTIFIABLE_TICKET_STATUSES, NotificationDoc, TicketDoc

logger = logging.getLogger(__name__)


# ── Generic email client (not ticket-specific - see module docstring) ──────

RESEND_API_BASE_URL = "https://api.resend.com"


class EmailClient:
    """Thin wrapper around Resend's HTTP API (POST /emails) - to/subject/
    text/html only, no ticket-shaped fields anywhere on this class, so this
    is the same client this app's eventual booking/plan-confirmation emails
    can reuse rather than something built narrowly for ticket
    notifications. `http_client` is injected (an httpx.AsyncClient whose
    base_url already points at RESEND_API_BASE_URL for real use, or a fake
    in tests) rather than constructed internally, matching the same
    dependency-injection style create_or_append_ticket
    (support_agent_service.py) already uses for its own HTTP calls."""
    def __init__(self, http_client: httpx.AsyncClient, *, api_key: str, from_address: str):
        self._http_client = http_client
        self._api_key = api_key
        self._from_address = from_address

    async def send(self, *, to: str, subject: str, text: str, html: Optional[str] = None) -> None:
        payload: Dict[str, Any] = {
            "from": self._from_address, "to": [to], "subject": subject, "text": text,
        }
        if html:
            payload["html"] = html
        response = await self._http_client.post(
            "/emails", json=payload, headers={"Authorization": f"Bearer {self._api_key}"},
        )
        response.raise_for_status()


@functools.lru_cache(maxsize=1)
def _get_resend_http_client() -> httpx.AsyncClient:
    """Lazy singleton, same reasoning as support_agent_service.py's own
    _get_gemini_client - deferred to first real use rather than constructed
    at import time."""
    return httpx.AsyncClient(base_url=RESEND_API_BASE_URL, timeout=10.0)


def get_email_client() -> EmailClient:
    """Production wiring: reads RESEND_API_KEY/RESEND_FROM_ADDRESS from the
    environment lazily (not hard-fail at import, unlike
    INTERNAL_TICKET_API_TOKEN - nothing calls this in production yet, since
    nothing in Phase 4 drives a ticket to a notifiable status; Phase 5's
    automation is expected to call this, not import EmailClient directly,
    when it needs to actually send). Tests construct EmailClient directly
    against a fake http_client instead of going through this."""
    api_key = os.environ.get("RESEND_API_KEY", "")
    from_address = os.environ.get("RESEND_FROM_ADDRESS", "EYV Support <support@updates.eyv.app>")
    return EmailClient(_get_resend_http_client(), api_key=api_key, from_address=from_address)


# ── Email templates (short, factual status updates - not marketing copy) ───

def _render_status_email(
    *, status: Literal[NOTIFIABLE_TICKET_STATUSES], ticket_title: str, ticket_id: str,
    ticket_url: Optional[str] = None,
) -> Tuple[str, str]:
    """Returns (subject, body_text). `ticket_url` is optional and omitted
    from the body when absent - there's no real ticket-detail page to link
    to until Step 4.4 ships one; wire a real URL through once it exists."""
    link_line = f"\n\nView it here: {ticket_url}" if ticket_url else ""
    if status == "implemented":
        subject = f'Fixed: "{ticket_title}"'
        body = (
            f'The issue you reported - "{ticket_title}" - has been implemented '
            f'and is live.{link_line}\n\nTicket reference: {ticket_id}'
        )
    elif status == "rejected":
        subject = f'Update on your report: "{ticket_title}"'
        body = (
            f'We reviewed the issue you reported - "{ticket_title}" - and '
            f'decided not to move forward with it.{link_line}\n\nTicket reference: {ticket_id}'
        )
    elif status == "backlog":
        subject = f'Update on your report: "{ticket_title}"'
        body = (
            f'The issue you reported - "{ticket_title}" - has been moved to our '
            f'backlog: a known issue we may address later, not currently '
            f'scheduled.{link_line}\n\nTicket reference: {ticket_id}'
        )
    else:
        raise ValueError(f"no email template for status {status!r}")
    return subject, body


# ── In-app notifications ────────────────────────────────────────────────

def _serialize_notification(raw_doc: Dict[str, Any]) -> Dict[str, Any]:
    return NotificationDoc(**raw_doc).model_dump(mode="json")


async def _create_in_app_notification(
    db, *, user_id: str, ticket_id: str, status: Literal[NOTIFIABLE_TICKET_STATUSES], title: str, body: str,
) -> None:
    record = NotificationDoc(
        user_id=user_id, ticket_id=ticket_id, status=status,
        title=title, body=body, read=False, created_at=datetime.now(timezone.utc),
    )
    await db.notifications.insert_one(record.model_dump())


async def list_notifications(db, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Newest first, for the frontend's eventual bell/list UI (Step 4.4) -
    this module only provides the query, not the route that exposes it."""
    cursor = db.notifications.find({"user_id": user_id}).sort("created_at", -1).limit(limit)
    docs = await cursor.to_list(limit)
    return [_serialize_notification(d) for d in docs]


async def count_unread_notifications(db, user_id: str) -> int:
    return await db.notifications.count_documents({"user_id": user_id, "read": False})


async def mark_notifications_read(db, user_id: str) -> int:
    """Marks every currently-unread notification belonging to `user_id` as
    read in one call - added in Step 4.4 for "opening/viewing the list
    marks them read," not a per-notification click-to-dismiss interaction.
    Scoped to `user_id` in the query itself (not just filtered after the
    fact), so this can never touch another user's notifications regardless
    of what the caller passes.

    NotificationDoc.read is a plain bool with no read_at timestamp (see
    that model in db_models.py) - confirmed against the existing Step 4.3
    shape before writing this, since a timestamp would need adding here if
    it didn't already cover what's needed; a bool is sufficient for the
    unread-count/mark-read mechanics this exposes, so none was added.
    Returns the number of notifications actually flipped from unread to
    read (0 if the user had none pending - safe/idempotent to call on an
    already-all-read state)."""
    result = await db.notifications.update_many(
        {"user_id": user_id, "read": False},
        {"$set": {"read": True}},
    )
    return result.modified_count


# ── Fan-out ──────────────────────────────────────────────────────────────

async def _lookup_user_email(db, user_id: str) -> Optional[str]:
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0, "email": 1})
    return user["email"] if user else None


async def notify_ticket_status_change(
    db,
    http_client: httpx.AsyncClient,
    email_client: EmailClient,
    *,
    internal_ticket_api_token: str,
    ticket_id: str,
    status: Literal[NOTIFIABLE_TICKET_STATUSES],
    ticket_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Call this right after a PATCH /api/internal/tickets/{id} that moved
    `status` to implemented/rejected/backlog has succeeded - see module
    docstring for the full idempotency/failure-handling contract. Returns
    the ticket dict (TicketDoc-validated) as it stands after this call -
    unchanged if there was nothing left to notify.

    Safe to call twice (or more) for the same ticket+status: the second
    call sees every previously-successful reporter already in
    notified_user_ids (fetched fresh via GET /{id} at the top of this
    function, not cached) and skips them - one email per reporter, not
    two, regardless of how many times this runs."""
    response = await http_client.get(
        f"/api/internal/tickets/{ticket_id}",
        headers={"Authorization": f"Bearer {internal_ticket_api_token}"},
    )
    response.raise_for_status()
    ticket = response.json()

    already_notified = set(ticket.get("notified_user_ids") or [])
    pending = [uid for uid in (ticket.get("reporter_user_ids") or []) if uid not in already_notified]

    if not pending:
        return TicketDoc(**ticket).model_dump(mode="json")

    subject, body = _render_status_email(
        status=status, ticket_title=ticket["title"], ticket_id=ticket_id, ticket_url=ticket_url,
    )

    newly_notified: List[str] = []
    for user_id in pending:
        recipient_email = await _lookup_user_email(db, user_id)
        if recipient_email is None:
            logger.warning(
                f"notify_ticket_status_change: no email on file for user {user_id}, "
                f"skipping notification for ticket {ticket_id}"
            )
            continue

        try:
            await email_client.send(to=recipient_email, subject=subject, text=body)
        except Exception as e:
            # Not marked notified - a later run will retry this reporter.
            # Doesn't stop the loop - other reporters on this same ticket
            # are independent.
            logger.error(
                f"notify_ticket_status_change: email send failed for user {user_id} "
                f"on ticket {ticket_id} (status={status}): {e}"
            )
            continue

        try:
            await _create_in_app_notification(
                db, user_id=user_id, ticket_id=ticket_id, status=status, title=subject, body=body,
            )
        except Exception as e:
            # Best-effort - email already sent, so this reporter is still
            # marked notified below despite the in-app copy failing.
            logger.error(
                f"notify_ticket_status_change: in-app notification failed for user {user_id} "
                f"on ticket {ticket_id} (status={status}): {e}"
            )

        newly_notified.append(user_id)

    if not newly_notified:
        return TicketDoc(**ticket).model_dump(mode="json")

    notify_response = await http_client.post(
        f"/api/internal/tickets/{ticket_id}/notify",
        json={"user_ids": newly_notified},
        headers={"Authorization": f"Bearer {internal_ticket_api_token}"},
    )
    notify_response.raise_for_status()
    return TicketDoc(**notify_response.json()).model_dump(mode="json")
