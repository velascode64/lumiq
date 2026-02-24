"""
Trading Bot Core Module

This module provides the core infrastructure for managing trading strategies
with Lumibot integration. It includes strategy factory, execution orchestrator,
and extensible registration system.

Main Components:
- StrategyFactory: Dynamic strategy instantiation and management
- TradingCore: Main orchestrator for multi-mode execution
- Strategy registration and discovery system

Usage:
    from core import TradingCore
    
    # Initialize core with broker config
    core = TradingCore(broker_config=ALPACA_CONFIG)
    
    # Execute strategies
    results = core.run(strategy="MeanReversion", mode="backtest", params={...})
    core.run(strategy="Momentum", mode="paper", params={...})
"""

from .strategy_factory import StrategyFactory
from .trading_core import TradingCore, TradingMode
from .strategy_orchestrator import StrategyOrchestrator

__version__ = "1.0.0"
__all__ = ["StrategyFactory", "TradingCore", "TradingMode", "StrategyOrchestrator"]
