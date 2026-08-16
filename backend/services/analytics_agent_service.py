"""
Analytics & Business Intelligence Agent (Sara) - Task A.3 of EYV Agent System.

Sara is EYV's sub-agent for:
1. Ingesting RevenueCat subscription lifecycle webhooks (idempotent, signed).
2. Deterministic anomaly & trend detection (billing failure spikes, cancellation surges,
   high-value subscriber churn, promotion over-redemption).
3. Selective JARVIS queue production: Only pushing work items to db.jarvis_queue_items
   when meaningful anomaly thresholds are crossed (avoids queue spam).
4. Anomaly Flood Deduplication: Never enqueues duplicate pending/in-progress anomalies.
5. Sandbox & Test Event Filtering: Rejects false alarms on environment: SANDBOX.
6. FX Currency Normalization: Normalizes international currencies to USD equivalent.
7. Strict scope isolation: Never modifies users, bookings, or payments collections.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from pydantic import BaseModel, Field

from db_models import RevenueCatEventDoc
from services.jarvis_queue_service import enqueue_jarvis_item

logger = logging.getLogger(__name__)

# Deterministic threshold constants (A.3.2)
BILLING_ISSUE_1H_THRESHOLD = 3
CANCELLATION_SURGE_24H_THRESHOLD = 5
CANCELLATION_RATIO_THRESHOLD = 0.40
HIGH_VALUE_CHURN_USD_THRESHOLD = 50.0
PROMO_CAP_WARNING_RATIO = 0.85

# FX rates for normalizing RevenueCat international currencies to USD equivalent
FX_RATES_TO_USD = {
    "USD": 1.0,
    "INR": 0.012,
    "EUR": 1.08,
    "GBP": 1.28,
    "AED": 0.27,
    "AUD": 0.65,
    "CAD": 0.73,
    "SGD": 0.75,
}


def convert_to_usd(price: Optional[float], currency: Optional[str]) -> float:
    """Normalizes a transaction amount to USD equivalent. Safely guards against nulls."""
    if price is None:
        return 0.0
    try:
        val = float(price)
        if val <= 0:
            return 0.0
        curr = str(currency or "USD").upper().strip()
        rate = FX_RATES_TO_USD.get(curr, 1.0)
        return round(val * rate, 2)
    except (ValueError, TypeError):
        return 0.0


class AnomalyEvaluationResult(BaseModel):
    anomaly_detected: bool
    anomaly_type: Optional[str] = None
    priority: Optional[int] = None
    queue_item_id: Optional[str] = None
    summary: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


async def _enqueue_anomaly_dedup(
    db,
    *,
    item_type: str,
    priority: int,
    payload: Dict[str, Any],
    summary: str,
    details: Dict[str, Any],
) -> AnomalyEvaluationResult:
    """Helper ensuring we never flood JARVIS with duplicate pending/in-progress anomaly items."""
    existing = await db.jarvis_queue_items.find_one({
        "source_agent": "sara",
        "item_type": item_type,
        "status": {"$in": ["pending", "in_progress"]},
    })
    if existing:
        logger.info(
            f"Existing pending queue item for {item_type} (id={existing['_id']}) already open. "
            "Skipping duplicate queue enqueue."
        )
        return AnomalyEvaluationResult(
            anomaly_detected=True,
            anomaly_type=item_type,
            priority=priority,
            queue_item_id=str(existing["_id"]),
            summary=summary,
            details=details,
        )

    q_item = await enqueue_jarvis_item(
        db,
        source_agent="sara",
        item_type=item_type,
        priority=priority,
        payload=payload,
    )
    return AnomalyEvaluationResult(
        anomaly_detected=True,
        anomaly_type=item_type,
        priority=priority,
        queue_item_id=q_item.id if q_item else None,
        summary=summary,
        details=details,
    )


async def record_revenuecat_event(db, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Ingests a RevenueCat webhook event idempotently and evaluates for anomalies."""
    now = datetime.now(timezone.utc)
    raw_event = payload.get("event") or payload

    event_id = str(raw_event.get("id") or raw_event.get("event_id") or "")
    if not event_id:
        raise ValueError("Missing RevenueCat event ID in payload")

    # Idempotency check: Ignore duplicate deliveries
    existing = await db.revenuecat_events.find_one({"event_id": event_id})
    if existing:
        logger.info(f"RevenueCat event {event_id} already processed. Ignoring duplicate.")
        return {
            "status": "duplicate_ignored",
            "event_id": event_id,
            "anomaly_detected": False,
        }

    event_type = str(raw_event.get("type", "UNKNOWN")).upper()
    environment = str(raw_event.get("environment", "PRODUCTION")).upper()
    app_user_id = str(raw_event.get("app_user_id") or "unknown_user")
    
    # Null and type guard on price
    price = raw_event.get("price_in_purchased_currency")
    if price is not None:
        try:
            price = float(price)
        except (ValueError, TypeError):
            price = None

    doc_data = {
        "event_id": event_id,
        "event_type": event_type,
        "app_user_id": app_user_id,
        "original_app_user_id": raw_event.get("original_app_user_id"),
        "product_id": raw_event.get("product_id"),
        "entitlement_id": raw_event.get("entitlement_id") or (
            raw_event.get("entitlement_ids", [None])[0] if raw_event.get("entitlement_ids") else None
        ),
        "price_in_purchased_currency": price,
        "currency": raw_event.get("currency"),
        "environment": environment,
        "cancel_reason": raw_event.get("cancel_reason"),
        "raw_payload": raw_event,
        "created_at": now,
    }

    # Validate against RevenueCatEventDoc
    validated_doc = RevenueCatEventDoc(**doc_data)
    await db.revenuecat_events.insert_one(doc_data)

    # Sandbox / test events: Do not trigger alarms or enqueue to JARVIS
    if event_type == "TEST" or environment == "SANDBOX":
        logger.info(f"Received RevenueCat TEST/SANDBOX webhook event {event_id} (env={environment})")
        return {
            "status": "test_event_recorded",
            "event_id": event_id,
            "anomaly_detected": False,
        }

    # Evaluate event against deterministic anomaly rules
    try:
        eval_result = await evaluate_revenuecat_event(db, doc_data)
    except Exception as exc:
        logger.error(f"Error evaluating RevenueCat event {event_id}: {exc}", exc_info=True)
        return {
            "status": "recorded",
            "event_id": event_id,
            "anomaly_detected": False,
            "error": str(exc),
        }

    return {
        "status": "recorded",
        "event_id": event_id,
        "anomaly_detected": eval_result.anomaly_detected,
        "anomaly_type": eval_result.anomaly_type,
        "queue_item_id": eval_result.queue_item_id,
    }


async def evaluate_revenuecat_event(db, event_doc: Dict[str, Any]) -> AnomalyEvaluationResult:
    """Evaluates a single RevenueCat event for deterministic threshold crossings."""
    now = datetime.now(timezone.utc)
    event_type = event_doc.get("event_type")
    price = event_doc.get("price_in_purchased_currency")
    currency = event_doc.get("currency")
    price_usd = convert_to_usd(price, currency)

    # 1. Billing Issue Spike Check (>= 3 billing issues in last 1 hour)
    if event_type == "BILLING_ISSUE":
        one_hour_ago = now - timedelta(hours=1)
        recent_billing_issues = await db.revenuecat_events.count_documents({
            "event_type": "BILLING_ISSUE",
            "environment": {"$ne": "SANDBOX"},
            "created_at": {"$gte": one_hour_ago},
        })

        if recent_billing_issues >= BILLING_ISSUE_1H_THRESHOLD:
            summary = (
                f"RevenueCat billing failure spike: {recent_billing_issues} failures in the past hour "
                f"(threshold={BILLING_ISSUE_1H_THRESHOLD})"
            )
            logger.warning(summary)
            return await _enqueue_anomaly_dedup(
                db,
                item_type="billing_issue_spike",
                priority=1,  # Critical emergency
                payload={
                    "metric": "billing_issues_1h",
                    "count": recent_billing_issues,
                    "threshold": BILLING_ISSUE_1H_THRESHOLD,
                    "summary": summary,
                    "latest_user_id": event_doc.get("app_user_id"),
                    "timestamp": now.isoformat(),
                },
                summary=summary,
                details={"count": recent_billing_issues},
            )

    # 2. High-Value Subscriber Churn Check ($50+ USD equivalent cancellation)
    if event_type == "CANCELLATION" and price_usd >= HIGH_VALUE_CHURN_USD_THRESHOLD:
        summary = (
            f"High-value subscriber cancelled: {event_doc.get('app_user_id')} "
            f"(${price_usd:.2f} USD eqv, original: {price} {currency})"
        )
        logger.warning(summary)
        return await _enqueue_anomaly_dedup(
            db,
            item_type="high_value_cancellation",
            priority=1,  # Critical
            payload={
                "metric": "high_value_churn",
                "app_user_id": event_doc.get("app_user_id"),
                "price": price,
                "price_usd": price_usd,
                "currency": currency,
                "cancel_reason": event_doc.get("cancel_reason"),
                "product_id": event_doc.get("product_id"),
                "summary": summary,
                "timestamp": now.isoformat(),
            },
            summary=summary,
            details={"price_usd": price_usd},
        )

    # 3. Cancellation Surge Check (>= 5 cancellations in 24h & cancellation ratio > 40%)
    if event_type == "CANCELLATION":
        twenty_four_hours_ago = now - timedelta(hours=24)
        cancellations_24h = await db.revenuecat_events.count_documents({
            "event_type": "CANCELLATION",
            "environment": {"$ne": "SANDBOX"},
            "created_at": {"$gte": twenty_four_hours_ago},
        })
        renewals_24h = await db.revenuecat_events.count_documents({
            "event_type": "RENEWAL",
            "environment": {"$ne": "SANDBOX"},
            "created_at": {"$gte": twenty_four_hours_ago},
        })

        total_activity = cancellations_24h + renewals_24h
        ratio = (cancellations_24h / total_activity) if total_activity > 0 else 0.0

        if cancellations_24h >= CANCELLATION_SURGE_24H_THRESHOLD and ratio > CANCELLATION_RATIO_THRESHOLD:
            summary = (
                f"RevenueCat cancellation surge: {cancellations_24h} cancellations in 24h "
                f"({ratio:.1%} churn ratio, threshold={CANCELLATION_RATIO_THRESHOLD:.0%})"
            )
            logger.warning(summary)
            return await _enqueue_anomaly_dedup(
                db,
                item_type="cancellation_surge",
                priority=1,
                payload={
                    "metric": "cancellations_24h",
                    "cancellations": cancellations_24h,
                    "renewals": renewals_24h,
                    "churn_ratio": ratio,
                    "summary": summary,
                    "timestamp": now.isoformat(),
                },
                summary=summary,
                details={"cancellations": cancellations_24h, "ratio": ratio},
            )

    # Routine events below threshold -> 0 queue items
    return AnomalyEvaluationResult(anomaly_detected=False)


async def evaluate_system_anomalies(db) -> List[AnomalyEvaluationResult]:
    """Periodic evaluation of broader system metrics (promotion capacity exhaustion)."""
    now = datetime.now(timezone.utc)
    results = []

    # 1. Check promotion capacity near limit (>= 85% redeemed)
    cursor = db.promotions.find({"usage_cap": {"$ne": None}})
    async for promo in cursor:
        usage_cap = promo.get("usage_cap")
        redemptions = promo.get("redemption_count", 0)
        if usage_cap and usage_cap > 0:
            ratio = redemptions / usage_cap
            if ratio >= PROMO_CAP_WARNING_RATIO:
                code = promo.get("code")
                summary = f"Promotion code {code} is at {ratio:.1%} capacity ({redemptions}/{usage_cap} redeemed)"
                res = await _enqueue_anomaly_dedup(
                    db,
                    item_type="promo_capacity_near_limit",
                    priority=5,
                    payload={
                        "code": code,
                        "redemption_count": redemptions,
                        "usage_cap": usage_cap,
                        "usage_ratio": ratio,
                        "summary": summary,
                        "timestamp": now.isoformat(),
                    },
                    summary=summary,
                    details={"code": code, "ratio": ratio},
                )
                results.append(res)

    return results
