"""
Trading Core - Main orchestrator for strategy execution

This module provides the core orchestrator that manages strategy execution
across different modes: backtesting, paper trading, and live trading.
"""

import datetime as dt
from typing import Dict, Any, Optional, Union, Literal, Callable
from enum import Enum
from pathlib import Path
import pytz
import logging
import re
import json
import os

# Prevent lumibot.credentials from auto-spawning a hidden broker/stream on import.
os.environ.setdefault("TRADING_BROKER", "none")

from lumibot.brokers import Alpaca
from lumibot.backtesting import AlpacaBacktesting
from lumibot.strategies import Strategy

try:
    from .strategy_factory import StrategyFactory
except ImportError:
    from strategy_factory import StrategyFactory


class TradingMode(Enum):
    """Trading execution modes"""
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


class StrategyLogHandler(logging.Handler):
    """
    Custom log handler that intercepts strategy log messages
    and extracts structured trading signals for UI callbacks.
    """
    
    def __init__(self, ui_callback: Optional[Callable] = None):
        super().__init__()
        self.ui_callback = ui_callback
        self.tick_counter = 0
        
        # Pattern to match structured log messages  
        # More flexible pattern to catch [SIGNAL] messages
        self.signal_pattern = re.compile(
            r'\[SIGNAL\]\s+action=(\w+)\s+reason=[\'"]([^\'\"]+)[\'"]\s+price=([\d.]+)\s+indicators=(.+)'
        )
    
    def emit(self, record):
        """Process log messages and extract trading signals."""
        try:
            message = self.format(record)
            
            # Debug: Print all messages to see what's coming through
            if '[SIGNAL]' in message:
                print(f"🔍 DEBUG: Found SIGNAL message: {message}")
            
            # Check if this is a trading signal message
            if '[SIGNAL]' in message:
                match = self.signal_pattern.search(message)
                if match and self.ui_callback:
                    self.tick_counter += 1
                    
                    # Extract signal data
                    action = match.group(1)
                    reason = match.group(2)
                    price = float(match.group(3))
                    indicators_str = match.group(4)
                    
                    # Parse indicators JSON
                    try:
                        indicators = json.loads(indicators_str.replace("'", '"'))
                    except:
                        indicators = {}
                    
                    # Prepare tick data for UI
                    tick_data = {
                        'tick_number': self.tick_counter,
                        'timestamp': dt.datetime.now().strftime("%H:%M:%S"),
                        'strategy': record.name if hasattr(record, 'name') else 'Strategy',
                        'symbol': indicators.get('symbol', 'ETH/USD'),
                        'action': action,
                        'price': price,
                        'signal': f"{indicators.get('signal_strength', 0):.2f}",
                        'reason': reason,
                        'indicators': {
                            'RSI': indicators.get('rsi', 0),
                            'MACD': indicators.get('macd', 0),
                            'MA20': indicators.get('ma20', 0),
                            'Volume': indicators.get('volume', 0)
                        }
                    }
                    
                    # Call the UI callback
                    self.ui_callback(tick_data)
                    
        except Exception as e:
            # Don't break on logging errors
            pass


class TradingCore:
    """
    Core orchestrator for trading strategy execution.
    
    Manages strategy lifecycle across different execution modes with
    unified configuration and extensible architecture.
    """
    
    def __init__(self, broker_config: Optional[Dict[str, Any]] = None):
        """
        Initialize the trading core.
        
        Args:
            broker_config: Broker configuration (Alpaca credentials, etc.)
        """
        self.factory = StrategyFactory()
        self.broker_config = broker_config or {}
        self._current_strategy: Optional[Strategy] = None
        self._current_mode: Optional[TradingMode] = None
        self._log_handler: Optional[StrategyLogHandler] = None
        
        # Auto-discover strategies from strategies directory
        try:
            discovered = self.factory.auto_discover_strategies("strategies")
            print(f"🚀 Core initialized with {discovered} strategies")
        except FileNotFoundError:
            # Fallback to module-local strategies path when cwd is outside packages/core.
            try:
                local_strategies = Path(__file__).resolve().parent / "strategies" / "live"
                discovered = self.factory.auto_discover_strategies(str(local_strategies))
                print(f"🚀 Core initialized with {discovered} local strategies")
            except FileNotFoundError:
                print("📁 No strategies directory found, using manual registration")
        
    def register_strategy(self, name: str, strategy_class, default_config: Optional[Dict] = None):
        """
        Register a strategy with the core.
        
        Args:
            name: Strategy identifier
            strategy_class: Strategy class
            default_config: Default parameters
        """
        self.factory.register_strategy(name, strategy_class, default_config)
        print(f"✅ Strategy '{name}' registered")
    
    def list_strategies(self) -> Dict[str, Any]:
        """
        List all available strategies with their configurations.
        
        Returns:
            Dictionary of strategy information
        """
        strategies = self.factory.get_available_strategies()
        result = {}
        
        for name, strategy_class in strategies.items():
            config = self.factory.get_strategy_config(name)
            result[name] = {
                'class': strategy_class.__name__,
                'module': strategy_class.__module__,
                'parameters': config,
                'description': strategy_class.__doc__ or "No description available"
            }
        
        return result
    
    def run(self, 
            strategy: str,
            mode: Literal["backtest", "paper", "live"] = "paper",
            params: Optional[Dict[str, Any]] = None,
            **execution_kwargs) -> Union[Dict, Strategy]:
        """
        Execute a strategy in the specified mode.
        
        Args:
            strategy: Strategy name from registry
            mode: Execution mode (backtest, paper, live)  
            params: Strategy-specific parameters
            **execution_kwargs: Mode-specific execution parameters
            
        Returns:
            Backtest results dictionary or Strategy instance for live/paper
        """
        trading_mode = TradingMode(mode)
        self._current_mode = trading_mode
        
        print(f"🎯 Executing strategy '{strategy}' in {mode} mode")
        
        # Validate strategy and parameters
        if params:
            self.factory.validate_strategy_config(strategy, params)
        
        if trading_mode == TradingMode.BACKTEST:
            return self._run_backtest(strategy, params, **execution_kwargs)
        elif trading_mode == TradingMode.PAPER:
            return self._run_paper_trading(strategy, params, **execution_kwargs)
        elif trading_mode == TradingMode.LIVE:
            return self._run_live_trading(strategy, params, **execution_kwargs)
        else:
            raise ValueError(f"Unsupported trading mode: {mode}")
    
    def _run_backtest(self, strategy_name: str, params: Optional[Dict], **kwargs) -> Dict:
        """
        Execute strategy in backtesting mode.
        
        Args:
            strategy_name: Name of strategy to backtest
            params: Strategy parameters
            **kwargs: Backtesting configuration
            
        Returns:
            Backtest results dictionary
        """
        # Default backtest configuration
        default_config = {
            'datasource_class': AlpacaBacktesting,
            'backtesting_start': self._get_default_start_date(),
            'backtesting_end': self._get_default_end_date(),
            'benchmark_asset': 'SPY',
            'analyze_backtest': True,
            'show_progress_bar': True,
            'timestep': 'day',
            'market': 'NASDAQ',
            'config': self.broker_config,
            'refresh_cache': False,
            'warm_up_trading_days': 0,
            'auto_adjust': True,
        }
        
        # Merge with provided kwargs
        backtest_config = {**default_config, **kwargs}
        
        # Get strategy class and create instance for backtesting
        strategy_class = self.factory.get_available_strategies()[strategy_name]
        
        print(f"📈 Starting backtest for {strategy_name}")
        print(f"📅 Period: {backtest_config['backtesting_start'].date()} to {backtest_config['backtesting_end'].date()}")
        
        # Run backtest using class method
        results, strategy_instance = strategy_class.run_backtest(
            parameters=params or {},
            **backtest_config
        )
        
        self._current_strategy = strategy_instance
        
        print("✅ Backtest completed")
        return results
    
    def _run_paper_trading(self, strategy_name: str, params: Optional[Dict], **kwargs) -> Strategy:
        """
        Execute strategy in paper trading mode.
        
        Args:
            strategy_name: Name of strategy to run
            params: Strategy parameters
            **kwargs: Paper trading configuration (including event_queue, ui_callback)
            
        Returns:
            Strategy instance running in paper mode
        """
        if not self.broker_config:
            raise ValueError("Broker configuration required for paper trading")
        
        # Extract special parameters
        event_queue = kwargs.pop('event_queue', None)
        ui_callback = kwargs.pop('ui_callback', None)
        
        # Setup UI callback if provided
        if ui_callback:
            self._setup_ui_logging(ui_callback)
        
        # Create paper trading broker
        broker_config = {**self.broker_config, 'IS_PAPER': True}
        broker = Alpaca(broker_config)
        
        # Create strategy instance
        strategy_instance = self.factory.create_strategy(
            strategy_name, 
            broker, 
            params,
            **kwargs
        )
        
        # Pass event queue to strategy if provided
        if event_queue and hasattr(strategy_instance, 'set_event_queue'):
            strategy_instance.set_event_queue(event_queue)
        
        # Attach log handler to strategy logger if UI callback provided
        if ui_callback and self._log_handler:
            # Access the real logger from StrategyLoggerAdapter
            strategy_instance.logger.logger.addHandler(self._log_handler)
            strategy_instance.logger.logger.setLevel(logging.INFO)
        
        self._current_strategy = strategy_instance
        
        print(f"📝 Starting paper trading for {strategy_name}")
        
        # Run in paper mode
        strategy_instance.run_live()
        
        return strategy_instance
    
    def _run_live_trading(self, strategy_name: str, params: Optional[Dict], **kwargs) -> Strategy:
        """
        Execute strategy in live trading mode.
        
        Args:
            strategy_name: Name of strategy to run  
            params: Strategy parameters
            **kwargs: Live trading configuration (including event_queue)
            
        Returns:
            Strategy instance running live
        """
        if not self.broker_config:
            raise ValueError("Broker configuration required for live trading")
        
        # Extract event queue if provided
        event_queue = kwargs.pop('event_queue', None)
        
        # Create live trading broker
        broker_config = {**self.broker_config, 'IS_PAPER': False}
        broker = Alpaca(broker_config)
        
        # Create strategy instance
        strategy_instance = self.factory.create_strategy(
            strategy_name,
            broker, 
            params,
            **kwargs
        )
        
        # Pass event queue to strategy if provided
        if event_queue and hasattr(strategy_instance, 'set_event_queue'):
            strategy_instance.set_event_queue(event_queue)
        
        self._current_strategy = strategy_instance
        
        print(f"🚨 Starting LIVE trading for {strategy_name}")
        print("⚠️  WARNING: This is live trading with real money!")
        
        # Run in live mode
        strategy_instance.run_live()
        
        return strategy_instance
    
    def _setup_ui_logging(self, ui_callback: Callable):
        """
        Setup custom log handler for UI callbacks.
        
        Args:
            ui_callback: Callback function to receive trading signals
        """
        # Create and configure the log handler
        self._log_handler = StrategyLogHandler(ui_callback)
        self._log_handler.setLevel(logging.INFO)
        self._log_handler.setFormatter(logging.Formatter('%(message)s'))
        print("📡 UI callback handler configured")
    
    def stop(self):
        """Stop current running strategy."""
        if self._current_strategy:
            # Implementation depends on Lumibot's stopping mechanism
            print("🛑 Stopping current strategy...")
            # self._current_strategy.stop()  # If such method exists
        
        # Clean up log handler
        if self._log_handler and self._current_strategy:
            try:
                self._current_strategy.logger.logger.removeHandler(self._log_handler)
            except:
                pass  # Handler might not be attached
            self._log_handler = None
        
    def get_current_strategy(self) -> Optional[Strategy]:
        """Get currently running strategy instance."""
        return self._current_strategy
    
    def get_current_mode(self) -> Optional[TradingMode]:
        """Get current trading mode.""" 
        return self._current_mode
    
    def _get_default_start_date(self) -> dt.datetime:
        """Get default backtest start date (6 months ago)."""
        tzinfo = pytz.timezone('America/New_York')
        start = dt.datetime.now() - dt.timedelta(days=180)
        return tzinfo.localize(start)
    
    def _get_default_end_date(self) -> dt.datetime:
        """Get default backtest end date (today)."""
        tzinfo = pytz.timezone('America/New_York') 
        end = dt.datetime.now()
        return tzinfo.localize(end)
    
    # Convenience methods matching the specification
    def backtest(self, strategy: str, params: Optional[Dict] = None, **kwargs) -> Dict:
        """Convenience method for backtesting."""
        return self.run(strategy, "backtest", params, **kwargs)
    
    def paper_trade(
        self,
        strategy: str,
        params: Optional[Dict] = None,
        ui_callback: Optional[Callable] = None,
        **kwargs,
    ) -> Strategy:
        """Convenience method for paper trading with optional UI callback."""
        if ui_callback:
            kwargs["ui_callback"] = ui_callback
        return self.run(strategy, "paper", params, **kwargs)
    
    def live_trade(self, strategy: str, params: Optional[Dict] = None, **kwargs) -> Strategy:
        """Convenience method for live trading.""" 
        return self.run(strategy, "live", params, **kwargs)
    
    def initialize_strategy(self, strategy: str, mode: Literal["paper", "live"], params: Optional[Dict] = None, **kwargs) -> Strategy:
        """Initialize strategy without running it (to avoid signal issues)."""
        trading_mode = TradingMode(mode)
        self._current_mode = trading_mode
        
        print(f"🎯 Initializing strategy '{strategy}' in {mode} mode")
        
        # Validate strategy and parameters
        if params:
            self.factory.validate_strategy_config(strategy, params)
        
        if not self.broker_config:
            raise ValueError("Broker configuration required for trading")
        
        # Extract event queue if provided
        event_queue = kwargs.pop('event_queue', None)
        
        # Create broker
        is_paper = (trading_mode == TradingMode.PAPER)
        broker_config = {**self.broker_config, 'IS_PAPER': is_paper}
        broker = Alpaca(broker_config)
        
        # Create strategy instance - pass event_queue as kwarg
        strategy_kwargs = kwargs.copy()
        if event_queue:
            strategy_kwargs['event_queue'] = event_queue
            
        strategy_instance = self.factory.create_strategy(
            strategy,
            broker, 
            params,
            **strategy_kwargs
        )
        
        # Also try the set_event_queue method as backup
        if event_queue and hasattr(strategy_instance, 'set_event_queue'):
            strategy_instance.set_event_queue(event_queue)
        
        # Initialize the strategy (call initialize method)
        if hasattr(strategy_instance, 'initialize'):
            strategy_instance.initialize()
        
        self._current_strategy = strategy_instance
        
        print(f"✅ Strategy '{strategy}' initialized successfully")
        return strategy_instance
