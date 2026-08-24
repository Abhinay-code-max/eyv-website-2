"""Shim redirecting services.telegram_bot_service to agents.telegram.telegram_bot_service.
"""
import sys
from agents.telegram import telegram_bot_service

sys.modules[__name__] = telegram_bot_service
