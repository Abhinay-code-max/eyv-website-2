"""Shim redirecting services.ticket_dedup_service to agents.denver.ticket_dedup_service.
"""
import sys
from agents.denver import ticket_dedup_service

sys.modules[__name__] = ticket_dedup_service
