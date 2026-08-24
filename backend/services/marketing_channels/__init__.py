"""Shim redirecting services.marketing_channels to agents.bob.marketing_channels.
"""
import sys
from agents.bob import marketing_channels

sys.modules[__name__] = marketing_channels
