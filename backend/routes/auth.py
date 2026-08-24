"""Authentication API router (/api/auth/*).
"""
import os
import uuid
import secrets
import logging
import httpx
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pymongo.errors import DuplicateKeyError

from routes.shared import (
    db,
    _hash_session_token,
    _get_current_session,
    get_current_user,
    User,
    SessionExchangeRequest,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REDIRECT_URI,
    FRONTEND_URL,
    GOOGLE_AUTH_URL,
    GOOGLE_TOKEN_URL,
    GOOGLE_USERINFO_URL,
    OAUTH_TICKET_TTL_SECONDS,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/google/login")
async def google_login():
    if not GOOGLE_CLIENT_ID or not GOOGLE_REDIRECT_URI:
        raise HTTPException(status_code=500, detail="Google OAuth not configured")

    state = secrets.token_urlsafe(24)
    await db.oauth_states.insert_one({
        "state": state,
        # Native datetime (not .isoformat()) - the TTL index in
        # index_service.py needs a real BSON Date to expire these.
        "created_at": datetime.now(timezone.utc)
    })

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "prompt": "select_account",
        "state": state,
    }
    return RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")


@router.get("/google/callback")
async def google_callback(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    if error or not code or not state:
        return RedirectResponse(f"{FRONTEND_URL}/login")

    state_doc = await db.oauth_states.find_one({"state": state})
    if not state_doc:
        return RedirectResponse(f"{FRONTEND_URL}/login")
    await db.oauth_states.delete_one({"state": state})

    try:
        async with httpx.AsyncClient() as client:
            token_resp = await client.post(GOOGLE_TOKEN_URL, data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            })
            token_resp.raise_for_status()
            tokens = token_resp.json()

            userinfo_resp = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {tokens['access_token']}"}
            )
            userinfo_resp.raise_for_status()
            profile = userinfo_resp.json()
    except Exception as e:
        logger.error(f"Google OAuth callback error: {e}")
        return RedirectResponse(f"{FRONTEND_URL}/login")

    ticket = uuid.uuid4().hex
    await db.oauth_tickets.insert_one({
        "ticket": ticket,
        "email": profile["email"],
        "name": profile.get("name", profile["email"]),
        "picture": profile.get("picture"),
        # Native datetime (not .isoformat()) - the TTL index in
        # index_service.py needs a real BSON Date to expire these.
        "created_at": datetime.now(timezone.utc)
    })

    return RedirectResponse(f"{FRONTEND_URL}/dashboard#session_id={ticket}")


@router.post("/session")
async def exchange_session(request: SessionExchangeRequest, response: Response, http_request: Request):
    try:
        ticket_doc = await db.oauth_tickets.find_one(
            {"ticket": request.session_id}, {"_id": 0}
        )
        if not ticket_doc:
            raise HTTPException(status_code=401, detail="Invalid session ID")
        await db.oauth_tickets.delete_one({"ticket": request.session_id})

        ticket_created_at = ticket_doc["created_at"]
        if isinstance(ticket_created_at, str):
            ticket_created_at = datetime.fromisoformat(ticket_created_at)
        if ticket_created_at.tzinfo is None:
            ticket_created_at = ticket_created_at.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - ticket_created_at).total_seconds() > OAUTH_TICKET_TTL_SECONDS:
            raise HTTPException(status_code=401, detail="Session ID expired")

        session_data = ticket_doc

        existing_user = await db.users.find_one(
            {"email": session_data["email"]},
            {"_id": 0}
        )

        is_new_user = existing_user is None

        if existing_user:
            user_id = existing_user["user_id"]
            await db.users.update_one(
                {"user_id": user_id},
                {"$set": {
                    "name": session_data["name"],
                    "picture": session_data.get("picture")
                }}
            )
        else:
            user_id = f"user_{uuid.uuid4().hex[:12]}"
            user_doc = {
                "user_id": user_id,
                "email": session_data["email"],
                "name": session_data["name"],
                "picture": session_data.get("picture"),
                "created_at": datetime.now(timezone.utc),
            }
            try:
                await db.users.insert_one(user_doc)
            except DuplicateKeyError:
                # Concurrent race: another OAuth exchange for this email just inserted the user record
                is_new_user = False
                existing_user = await db.users.find_one(
                    {"email": session_data["email"]},
                    {"_id": 0}
                )
                user_id = existing_user["user_id"]
                await db.users.update_one(
                    {"user_id": user_id},
                    {"$set": {
                        "name": session_data["name"],
                        "picture": session_data.get("picture")
                    }}
                )

        session_token = uuid.uuid4().hex
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)

        # Each login inserts its own session rather than deleting the user's
        # existing ones - logging in on a phone shouldn't kill a laptop
        # session. Sessions are only ever removed individually now: by
        # /auth/logout (this token only), /auth/sessions/{id} (explicit
        # revoke), or the TTL index once expires_at passes.
        session_doc = {
            "session_id": uuid.uuid4().hex,
            # Plaintext tokens in this collection would let anyone with DB
            # read access impersonate any live session - store only a
            # SHA-256 hash and compare hashes on every lookup instead.
            "session_token": _hash_session_token(session_token),
            "user_id": user_id,
            # Native datetime (not .isoformat()) - the TTL index in
            # index_service.py needs a real BSON Date to expire these.
            "expires_at": expires_at,
            "created_at": datetime.now(timezone.utc),
            "user_agent": http_request.headers.get("user-agent"),
        }
        await db.user_sessions.insert_one(session_doc)

        response.set_cookie(
            key="session_token",
            value=session_token,
            httponly=True,
            secure=True,
            samesite="none",
            path="/",
            max_age=7*24*60*60
        )

        user_doc = await db.users.find_one({"user_id": user_id}, {"_id": 0})
        if isinstance(user_doc['created_at'], str):
            user_doc['created_at'] = datetime.fromisoformat(user_doc['created_at'])

        return {
            "user": User(**user_doc).model_dump(mode='json'),
            "is_new_user": is_new_user,
            "message": "Authentication successful",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Session exchange error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/me")
async def get_me(request: Request):
    user = await get_current_user(request)
    return user.model_dump(mode='json')


@router.post("/logout")
async def logout(request: Request, response: Response):
    session_token = request.cookies.get("session_token")
    if not session_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            session_token = auth_header.replace("Bearer ", "")
    if session_token:
        # Only this one session/device - not db.user_sessions.delete_many,
        # which would also sign the user out everywhere else.
        await db.user_sessions.delete_one({"session_token": _hash_session_token(session_token)})

    response.delete_cookie(key="session_token", path="/")
    return {"message": "Logged out successfully"}


@router.get("/sessions")
async def list_sessions(request: Request):
    """All of the current user's active sessions (e.g. phone + laptop both
    logged in at once) - never includes the token hash itself."""
    current_session = await _get_current_session(request)
    docs = await db.user_sessions.find(
        {"user_id": current_session["user_id"]},
        {"_id": 0, "session_token": 0}
    ).sort("created_at", -1).to_list(100)
    for doc in docs:
        doc["is_current"] = doc.get("session_id") == current_session.get("session_id")
    return {"sessions": docs}


@router.delete("/sessions/{session_id}")
async def revoke_session(session_id: str, request: Request):
    """Revoke one specific session (e.g. a lost/stolen device) without
    touching any of the user's other active sessions."""
    current_session = await _get_current_session(request)
    result = await db.user_sessions.delete_one(
        {"session_id": session_id, "user_id": current_session["user_id"]}
    )
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"message": "Session revoked"}
