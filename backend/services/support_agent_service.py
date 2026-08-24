"""Shim redirecting services.support_agent_service to agents.denver.support_agent_service.
"""
import sys
from agents.denver import support_agent_service

sys.modules[__name__] = support_agent_service
