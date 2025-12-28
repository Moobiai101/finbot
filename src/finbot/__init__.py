"""Finbot - Production-grade algorithmic trading bot."""

__version__ = "0.1.0"

from finbot.config import get_settings, Settings, TradingMode

__all__ = [
    "get_settings",
    "Settings",
    "TradingMode",
]
