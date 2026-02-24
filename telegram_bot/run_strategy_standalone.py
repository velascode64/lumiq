"""
Standalone strategy runner that bypasses signal handler issues
Run strategies directly without threading complications
"""

import sys
import os
import time
import signal
from pathlib import Path
from datetime import datetime

# Add paths for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "packages"))

# Ignore signals completely
signal.signal(signal.SIGINT, signal.SIG_IGN)
signal.signal(signal.SIGTERM, signal.SIG_IGN)

def run_strategy(strategy_name, user_id, config):
    """Run a strategy standalone without signal issues"""
    
    print(f"🚀 Starting {strategy_name} for user {user_id}")
    
    try:
        from lumibot.brokers import Alpaca
        from lumibot.credentials import ALPACA_TEST_CONFIG
        
        # Import the specific strategy
        strategy_map = {
            "ETH 5 Min MACD": ("packages.core.strategies.live.eth_5min_macd_strategy", "ETH5MinMACDStrategy"),
            "ETH-BTC Correlation Live": ("packages.core.strategies.live.eth_btc_correlation", "CryptoLeadLagStrategy"),
            "Live Test Strategy": ("packages.core.strategies.live.live_test_strategy", "LiveTestStrategy"),
            "Mean Reversion Live": ("packages.core.strategies.live.carlos_mean_reversion_live", "CarlosMeanReversionLiveStrategy"),
        }
        
        if strategy_name not in strategy_map:
            print(f"❌ Unknown strategy: {strategy_name}")
            return
            
        module_path, class_name = strategy_map[strategy_name]
        module = __import__(module_path, fromlist=[class_name])
        strategy_class = getattr(module, class_name)
        
        # Create broker
        broker = Alpaca(ALPACA_TEST_CONFIG)
        
        # Prepare parameters
        params = {
            'initial_budget': config.get('budget', 10000),
            **config.get('parameters', {})
        }
        
        # Create strategy instance
        strategy = strategy_class(broker=broker, parameters=params)
        strategy.sleeptime = '10S'  # Check every 10 seconds
        
        print(f"✅ Strategy initialized: {strategy_name}")
        print(f"💰 Budget: ${params['initial_budget']:,}")
        print(f"⏰ Starting main loop...")
        
        # Initialize strategy
        strategy.initialize()
        
        # Main loop - run iterations manually
        iteration_count = 0
        while True:
            try:
                iteration_count += 1
                print(f"\n--- Iteration {iteration_count} at {datetime.now().strftime('%H:%M:%S')} ---")
                
                # Run one trading iteration
                strategy.on_trading_iteration()
                
                # Sleep between iterations
                time.sleep(10)
                
            except KeyboardInterrupt:
                print("\n⏹️ Strategy stopped by user")
                break
            except Exception as e:
                print(f"❌ Error in iteration {iteration_count}: {e}")
                time.sleep(10)
                
        # Clean up
        try:
            strategy.on_strategy_end()
        except:
            pass
            
        print(f"🏁 Strategy {strategy_name} ended")
        
    except Exception as e:
        print(f"❌ Critical error running strategy: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # Test run
    if len(sys.argv) > 1:
        strategy_name = sys.argv[1]
        user_id = int(sys.argv[2]) if len(sys.argv) > 2 else 12345
        config = {'budget': 10000}
        
        run_strategy(strategy_name, user_id, config)
    else:
        print("Usage: python run_strategy_standalone.py 'Strategy Name' [user_id]")
        print("\nAvailable strategies:")
        print("  - ETH 5 Min MACD")
        print("  - ETH-BTC Correlation Live")
        print("  - Live Test Strategy")
        print("  - Mean Reversion Live")