"""General / root status API router.
"""
import logging

from fastapi import APIRouter

from routes.shared import (
    _SERVER_STARTED_AT,
    _SERVER_PID,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["general"])


@router.get("/")
async def root():
    return {
        "message": "EYV API - Enjoy Your Vacation",
        "server_started_at": _SERVER_STARTED_AT.isoformat(),
        "server_pid": _SERVER_PID,
    }

