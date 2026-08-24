"""Notifications API router (/api/notifications/*).
"""
import logging
from fastapi import APIRouter, Request

from routes.shared import db, get_current_user
from services import notification_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
async def get_notifications(request: Request):
    user = await get_current_user(request)
    notifications = await notification_service.list_notifications(db, user.user_id)
    unread_count = await notification_service.count_unread_notifications(db, user.user_id)
    return {"notifications": notifications, "unread_count": unread_count}


@router.patch("/read")
async def mark_notifications_read_route(request: Request):
    """Bulk mark-all-as-read for the current user, not a per-id route -
    matches the UI behavior this exposes ("opening/viewing the list marks
    them read"), not a per-notification click-to-dismiss interaction."""
    user = await get_current_user(request)
    count = await notification_service.mark_notifications_read(db, user.user_id)
    return {"marked_read": count}
