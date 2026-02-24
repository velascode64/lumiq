"""
Strategy Factory - Core module for strategy instantiation and management

This module provides a factory pattern for creating and managing trading strategies
based on Lumibot framework integration.
"""

import importlib
import importlib.util
import inspect
from typing import Dict, Any, Type, Optional
from pathlib import Path

from lumibot.strategies import Strategy


class StrategyFactory:
    """
    Factory class for creating strategy instances dynamically.
    
    Manages strategy registration, configuration, and instantiation.
    """
    
    def __init__(self):
        self._strategies_registry: Dict[str, Type[Strategy]] = {}
        self._strategy_configs: Dict[str, Dict[str, Any]] = {}
        
    def register_strategy(self, name: str, strategy_class: Type[Strategy], 
                         default_config: Optional[Dict[str, Any]] = None) -> None:
        """
        Register a strategy class with the factory.
        
        Args:
            name: Strategy identifier name
            strategy_class: Strategy class inheriting from lumibot.Strategy
            default_config: Default configuration parameters for the strategy
        """
        if not issubclass(strategy_class, Strategy):
            raise ValueError(f"Strategy class {strategy_class.__name__} must inherit from lumibot.Strategy")
        
        self._strategies_registry[name] = strategy_class
        self._strategy_configs[name] = default_config or {}
        
    def get_available_strategies(self) -> Dict[str, Type[Strategy]]:
        """
        Returns dictionary of all registered strategies.
        
        Returns:
            Dict mapping strategy names to strategy classes
        """
        return self._strategies_registry.copy()
    
    def get_strategy_config(self, name: str) -> Dict[str, Any]:
        """
        Get default configuration for a strategy.
        
        Args:
            name: Strategy name
            
        Returns:
            Default configuration dictionary
        """
        if name not in self._strategy_configs:
            raise ValueError(f"Strategy '{name}' not found in registry")
        
        return self._strategy_configs[name].copy()
    
    def create_strategy(self, name: str, broker, 
                       parameters: Optional[Dict[str, Any]] = None,
                       **kwargs) -> Strategy:
        """
        Create an instance of the specified strategy.
        
        Args:
            name: Strategy name from registry
            broker: Broker instance (Alpaca, InteractiveBrokers, etc.)
            parameters: Strategy-specific configuration parameters
            **kwargs: Additional arguments passed to strategy constructor
            
        Returns:
            Configured strategy instance ready for execution
        """
        if name not in self._strategies_registry:
            raise ValueError(f"Strategy '{name}' not found. Available: {list(self._strategies_registry.keys())}")
        
        strategy_class = self._strategies_registry[name]
        
        # Merge default config with provided parameters
        config = self._strategy_configs[name].copy()
        if parameters:
            config.update(parameters)
        
        # Create strategy instance
        strategy_instance = strategy_class(
            broker=broker,
            parameters=config,
            **kwargs
        )
        
        return strategy_instance
    
    def auto_discover_strategies(self, strategies_path: str = "strategies") -> int:
        """
        Automatically discover and register strategies from a directory.
        
        Args:
            strategies_path: Path to directory containing strategy files
            
        Returns:
            Number of strategies discovered and registered
        """
        strategies_dir = Path(strategies_path)
        if not strategies_dir.exists():
            raise FileNotFoundError(f"Strategies directory '{strategies_path}' not found")
        
        discovered = 0
        
        for py_file in strategies_dir.glob("*.py"):
            if py_file.name.startswith("__"):
                continue
            if py_file.name.endswith("_ui.py"):
                continue
                
            try:
                # Import module dynamically
                module_name = py_file.stem
                spec = importlib.util.spec_from_file_location(module_name, py_file)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                # Find Strategy classes in the module
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if (obj != Strategy and 
                        issubclass(obj, Strategy) and 
                        obj.__module__ == module_name):
                        
                        # Register strategy with class name as identifier
                        strategy_name = name
                        default_params = getattr(obj, 'parameters', {})
                        
                        self.register_strategy(
                            name=strategy_name,
                            strategy_class=obj,
                            default_config=default_params
                        )
                        
                        discovered += 1
                        print(f"✓ Discovered strategy: {strategy_name}")
                        
            except Exception as e:
                print(f"⚠ Failed to load strategy from {py_file}: {e}")
                continue
        
        return discovered
    
    def validate_strategy_config(self, name: str, parameters: Dict[str, Any]) -> bool:
        """
        Validate strategy parameters against strategy requirements.
        
        Args:
            name: Strategy name
            parameters: Parameters to validate
            
        Returns:
            True if parameters are valid
        """
        if name not in self._strategies_registry:
            raise ValueError(f"Strategy '{name}' not found")
        
        strategy_class = self._strategies_registry[name]
        default_params = getattr(strategy_class, 'parameters', {})
        
        # Basic validation - check if all required parameters are present
        missing_params = []
        for param_name, default_value in default_params.items():
            if param_name not in parameters and default_value is None:
                missing_params.append(param_name)
        
        if missing_params:
            raise ValueError(f"Missing required parameters for {name}: {missing_params}")
        
        return True
