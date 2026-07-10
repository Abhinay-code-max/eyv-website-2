"""
Server-authoritative price cache.

Search results returned to the browser carry a display price *and* a
freshly minted item_id. The item_id is the only thing a client may send
back when creating a booking - the price itself is always looked up here
server-side, never trusted from the request body.

Flow:
  1. search endpoint calls cache_search_results() -> stamps each result
     with item_id and stores {price, currency, provider_ref} keyed by it.
  2. booking creation calls resolve_price(item_id) -> authoritative price,
     re-quoting from the live provider if the cache entry has expired.
"""
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from . import ignav_service, serpapi_hotels_service

logger = logging.getLogger(__name__)

FLIGHT_TTL_SECONDS = 15 * 60        # offers move fast - keep this short
HOTEL_TTL_SECONDS = 4 * 60 * 60     # hotel rates are stable for longer


async def ensure_indexes(db):
    await db.price_cache.create_index("item_id", unique=True)
    await db.price_cache.create_index("expires_at", expireAfterSeconds=0)


def _ttl_seconds(item_type: str) -> int:
    return FLIGHT_TTL_SECONDS if item_type == "flight" else HOTEL_TTL_SECONDS


async def cache_price(
    db,
    item_type: str,
    provider: str,
    provider_ref: Dict[str, Any],
    price: float,
    currency: str,
    item_id: Optional[str] = None,
) -> str:
    """Store an authoritative price under a (new or existing) item_id."""
    item_id = item_id or str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    doc = {
        "item_id": item_id,
        "item_type": item_type,
        "provider": provider,
        "provider_ref": provider_ref,
        "price": price,
        "currency": currency,
        "created_at": now,
        "expires_at": now + timedelta(seconds=_ttl_seconds(item_type)),
    }
    await db.price_cache.replace_one({"item_id": item_id}, doc, upsert=True)
    return item_id


async def cache_search_results(
    db,
    items: List[Dict],
    item_type: str,
    provider: str,
    search_params: Dict[str, Any],
) -> None:
    """Mutate each search result in place: attach item_id, cache its price."""
    for item in items:
        price_obj = item.get("price") or {}
        provider_ref = {**search_params, "provider_item_id": item.get("id")}
        item_id = await cache_price(
            db, item_type, provider, provider_ref,
            price=price_obj.get("total", 0),
            currency=price_obj.get("currency", "USD"),
        )
        item["item_id"] = item_id


def _is_expired(doc: Dict) -> bool:
    expires_at = doc["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= datetime.now(timezone.utc)


async def resolve_price(db, item_id: str) -> Optional[Dict[str, Any]]:
    """
    The sole source of truth for what a booking may be charged.

    - Cache hit, not expired -> return the cached price.
    - Cache hit, expired -> re-quote live from the provider using
      provider_ref, refresh the cache under the same item_id.
    - No cache entry (forged/unknown item_id, or already purged by Mongo's
      TTL monitor) -> None. Caller must treat this as "offer expired,
      please search again" - there's nothing left to re-verify against.
    """
    doc = await db.price_cache.find_one({"item_id": item_id}, {"_id": 0})
    if not doc:
        return None

    if not _is_expired(doc):
        return {"price": doc["price"], "currency": doc["currency"]}

    fresh = await _requote(doc["item_type"], doc["provider"], doc["provider_ref"])
    if not fresh:
        return None

    await cache_price(
        db, doc["item_type"], doc["provider"], doc["provider_ref"],
        price=fresh["price"], currency=fresh["currency"], item_id=item_id,
    )
    return fresh


async def _requote(item_type: str, provider: str, provider_ref: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Re-fetch a fresh price directly from the provider. Mock-sourced items
    have no real backing offer to re-verify against, so they are never
    re-quoted - they simply expire, which is the safe default.
    """
    try:
        if provider == "ignav" and item_type == "flight":
            flights = await ignav_service.search_flights(
                provider_ref["origin"], provider_ref["destination"],
                provider_ref["departure_date"], provider_ref.get("return_date"),
                provider_ref.get("travelers", 1),
            )
            for f in flights:
                if f.get("id") == provider_ref.get("provider_item_id"):
                    return {"price": f["price"]["total"], "currency": f["price"]["currency"]}
            return None

        if provider == "serpapi" and item_type == "hotel":
            hotels = await serpapi_hotels_service.search_hotels(
                provider_ref["destination"], provider_ref["check_in"], provider_ref["check_out"],
                provider_ref.get("travelers", 1),
            )
            for h in hotels:
                if h.get("id") == provider_ref.get("provider_item_id"):
                    return {"price": h["price"]["total"], "currency": h["price"]["currency"]}
            return None
    except Exception as e:
        logger.error(f"Re-quote failed for {item_type}/{provider}: {e}")
        return None

    return None
