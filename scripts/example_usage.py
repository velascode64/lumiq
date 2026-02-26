"""
Example usage of the Trading Core module

This file demonstrates how to use the core module to execute strategies
across different modes with various configurations.
"""

import datetime as dt
import pytz
from core import TradingCore
from lumibot.credentials import ALPACA_TEST_CONFIG

def main():
    """Demonstrate core functionality with examples"""
    
    # Initialize the core with broker configuration
    print("🚀 Initializing Trading Core...")
    core = TradingCore(broker_config=ALPACA_TEST_CONFIG)
    
    # List available strategies
    print("\n📋 Available Strategies:")
    strategies = core.list_strategies()
    for name, info in strategies.items():
        print(f"  • {name}: {info['class']}")
        if info['parameters']:
            print(f"    Parameters: {list(info['parameters'].keys())}")
    
    # Example 1: Backtest a strategy
    print("\n📈 Example 1: Backtesting Carlos Mean Reversion Strategy")
    try:
        backtest_results = core.run(
            strategy="CarlosMeanReversionStrategy",
            mode="backtest",
            params={
                "symbol": "QQQ",
                "daily_gain_threshold": 0.03,
                "paper_trade_qty": 100
            },
            # Backtest-specific parameters
            backtesting_start=pytz.timezone('America/New_York').localize(dt.datetime(2023, 6, 1)),
            backtesting_end=pytz.timezone('America/New_York').localize(dt.datetime(2024, 1, 1)),
            benchmark_asset='SPY'
        )
        print("✅ Backtest completed successfully")
        print(f"Results type: {type(backtest_results)}")
        
    except Exception as e:
        print(f"❌ Backtest failed: {e}")
    
    # Example 2: Run in paper trading mode  
    print("\n📝 Example 2: Paper Trading (commented out - would run continuously)")
    print("Code example:")
    print("""
    strategy_instance = core.run(
        strategy="CarlosMeanReversionStrategy", 
        mode="paper",
        params={
            "symbol": "AAPL",
            "daily_gain_threshold": 0.04,
            "paper_trade_qty": 10
        }
    )
    """)
    
    # Example 3: Convenience methods
    print("\n🎯 Example 3: Using convenience methods")
    print("Convenience methods available:")
    print("  • core.backtest(strategy, params)")
    print("  • core.paper_trade(strategy, params)") 
    print("  • core.live_trade(strategy, params)")
    
    # Example 4: Strategy registration (if needed manually)
    print("\n🔧 Example 4: Manual strategy registration")
    from strategies.carlos_mean_reversion_strategy import CarlosMeanReversionStrategy
    
    core.register_strategy(
        name="CustomMeanReversion",
        strategy_class=CarlosMeanReversionStrategy,
        default_config={
            "symbol": "SPY",
            "daily_gain_threshold": 0.05,
            "paper_trade_qty": 50
        }
    )
    
    # Example 5: Simple usage as specified in requirements
    print("\n✨ Example 5: Simple usage as per specification")
    print('core.run(strategy="MeanReversion", params={...}, mode="paper")')
    
    print("\n🎉 Core module demonstration completed!")

if __name__ == "__main__":
    main()