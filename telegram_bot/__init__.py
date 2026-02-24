"""
Telegram Bot Module for Lumibot Trading

This module provides a Telegram interface for managing paper trading strategies
through the Core trading module.

Features:
- Interactive strategy selection
- Parameter configuration
- Real-time monitoring
- Trading session management
"""

from .telegram_bot import TradingBot

__version__ = "1.0.0"
__all__ = ["TradingBot"]