"""Shim redirecting services.marketing_agent_service to agents.bob.marketing_agent_service.
"""
import sys
from agents.bob import marketing_agent_service

sys.modules[__name__] = marketing_agent_service
