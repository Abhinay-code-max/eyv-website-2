from .support_agent_service import (
    handle_support_message,
    classify_message,
    create_or_append_ticket,
    lookup_user_trips,
    lookup_booking,
    get_refund_policy,
    escalate_to_human,
    log_support_turn,
    SupportAgentTurnResult,
    SupportClassification,
    SUPPORT_CATEGORIES,
    TOOL_REGISTRY,
    GEMINI_MODEL,
)
from .ticket_dedup_service import (
    check_and_resolve_ticket,
    DedupResult,
    OPEN_TICKET_STATUSES,
)

__all__ = [
    "handle_support_message",
    "classify_message",
    "create_or_append_ticket",
    "lookup_user_trips",
    "lookup_booking",
    "get_refund_policy",
    "escalate_to_human",
    "log_support_turn",
    "SupportAgentTurnResult",
    "SupportClassification",
    "SUPPORT_CATEGORIES",
    "TOOL_REGISTRY",
    "GEMINI_MODEL",
    "check_and_resolve_ticket",
    "DedupResult",
    "OPEN_TICKET_STATUSES",
]
