"""Shim redirecting services.analytics_agent_service to agents.sara.analytics_agent_service.
"""
import sys
from agents.sara import analytics_agent_service

sys.modules[__name__] = analytics_agent_service
