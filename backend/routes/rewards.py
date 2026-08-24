"""Travel Rewards System API router (/api/rewards/*).
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from routes.shared import db, get_current_user
from services import rewards_service

router = APIRouter(prefix="/api/rewards", tags=["rewards"])


@router.get("")
async def get_rewards(request: Request):
    user = await get_current_user(request)
    return await rewards_service.get_user_rewards_summary(db, user.user_id)


class RedeemPointsRequest(BaseModel):
    points: int
    reference_id: Optional[str] = None


@router.post("/redeem")
async def redeem_rewards(req: RedeemPointsRequest, request: Request):
    user = await get_current_user(request)
    try:
        result = await rewards_service.redeem_points(
            db, user.user_id, req.points, req.reference_id, "Discount applied to booking"
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
