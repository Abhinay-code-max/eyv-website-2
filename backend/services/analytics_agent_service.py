"""
Analytics & Business Intelligence Agent (Sara) - Task A.3 of EYV Agent System.

Sara is EYV's sub-agent for:
1. Ingesting RevenueCat subscription lifecycle webhooks (idempotent, signed).
2. Deterministic anomaly & trend detection (billing failure spikes, cancellation surges,
   high-value subscriber churn, promotion over-redemption).
3. Selective JARVIS queue production: Only pushing work items to db.jarvis_queue_items
   when meaningful anomaly thresholds are crossed (avoids queue spam).
4. Strict scope isolation: Never modifies users, bookings, or payments collections.
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
HIGH_VALUE_CHURN_AMOUNT = 50.0
PROMO_CAP_WARNING_RATIO = 0.85


class AnomalyEvaluationResult(BaseModel):
    anomaly_detected: bool
    anomaly_type: Optional[str] = None
    priority: Optional[int] = None
    queue_item_id: Optional[str] = None
    summary: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


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
    app_user_id = str(raw_event.get("app_user_id") or "unknown_user")
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
        "environment": raw_event.get("environment", "PRODUCTION"),
        "cancel_reason": raw_event.get("cancel_reason"),
        "raw_payload": raw_event,
        "created_at": now,
    }

    # Validate against RevenueCatEventDoc
    validated_doc = RevenueCatEventDoc(**doc_data)
    await db.revenuecat_events.insert_one(doc_data)

    # Sandbox / test events: Do not trigger alarms or enqueue to JARVIS
    if event_type == "TEST":
        logger.info(f"Received RevenueCat TEST webhook event {event_id}")
        return {
            "status": "test_event_recorded",
            "event_id": event_id,
            "anomaly_detected": False,
        }

    # Evaluate event against deterministic anomaly rules
    eval_result = await evaluate_revenuecat_event(db, doc_data)
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
    price = event_doc.get("price_in_purchased_currency") or 0.0

    # 1. Billing Issue Spike Check (>= 3 billing issues in last 1 hour)
    if event_type == "BILLING_ISSUE":
        one_hour_ago = now - timedelta(hours=1)
        recent_billing_issues = await db.revenuecat_events.count_documents({
            "event_type": "BILLING_ISSUE",
            "created_at": {"$gte": one_hour_ago},
        })

        if recent_billing_issues >= BILLING_ISSUE_1H_THRESHOLD:
            summary = (
                f"RevenueCat billing failure spike: {recent_billing_issues} failures in the past hour "
                f"(threshold={BILLING_ISSUE_1H_THRESHOLD})"
            )
            logger.warning(summary)
            q_item = await enqueue_jarvis_item(
                db,
                source_agent="sara",
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
            )
            return AnomalyEvaluationResult(
                anomaly_detected=True,
                anomaly_type="billing_issue_spike",
                priority=1,
                queue_item_id=q_item.id if q_item else None,
                summary=summary,
                details={"count": recent_billing_issues},
            )

    # 2. High-Value Subscriber Churn Check ($50+ cancellation)
    if event_type == "CANCELLATION" and price >= HIGH_VALUE_CHURN_AMOUNT:
        summary = (
            f"High-value subscriber cancelled: {event_doc.get('app_user_id')} "
            f"(${price:.2f} {event_doc.get('currency', 'USD')})"
        )
        logger.warning(summary)
        q_item = await enqueue_jarvis_item(
            db,
            source_agent="sara",
            item_type="high_value_cancellation",
            priority=1,  # Critical
            payload={
                "metric": "high_value_churn",
                "app_user_id": event_doc.get("app_user_id"),
                "price": price,
                "currency": event_doc.get("currency"),
                "cancel_reason": event_doc.get("cancel_reason"),
                "product_id": event_doc.get("product_id"),
                "summary": summary,
                "timestamp": now.isoformat(),
            },
        )
        return AnomalyEvaluationResult(
            anomaly_detected=True,
            anomaly_type="high_value_cancellation",
            priority=1,
            queue_item_id=q_item.id if q_item else None,
            summary=summary,
            details={"price": price},
        )

    # 3. Cancellation Surge Check (>= 5 cancellations in 24h & cancellation ratio > 40%)
    if event_type == "CANCELLATION":
        twenty_four_hours_ago = now - timedelta(hours=24)
        cancellations_24h = await db.revenuecat_events.count_documents({
            "event_type": "CANCELLATION",
            "created_at": {"$gte": twenty_four_hours_ago},
        })
        renewals_24h = await db.revenuecat_events.count_documents({
            "event_type": "RENEWAL",
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
            q_item = await enqueue_jarvis_item(
                db,
                source_agent="sara",
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
            )
            return AnomalyEvaluationResult(
                anomaly_detected=True,
                anomaly_type="cancellation_surge",
                priority=1,
                queue_item_id=q_item.id if q_item else None,
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
                q_item = await enqueue_jarvis_item(
                    db,
                    source_agent="sara",
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
                )
                results.append(AnomalyEvaluationResult(
                    anomaly_detected=True,
                    anomaly_type="promo_capacity_near_limit",
                    priority=5,
                    queue_item_id=q_item.id if q_item else None,
                    summary=summary,
                    details={"code": code, "ratio": ratio},
                ))

    return results
