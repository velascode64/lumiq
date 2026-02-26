# Trading Bot Core Module 🚀

Core module for trading strategy execution with Lumibot integration. Provides modular architecture for strategy instantiation, multi-mode execution, and extensible interfaces.

## 🎯 Features

- **Strategy Factory**: Dynamic strategy instantiation and management
- **Multi-mode Execution**: Backtesting, paper trading, and live trading
- **Auto-discovery**: Automatic strategy registration from directories
- **Extensible Architecture**: Easy integration of new strategies
- **Unified Interface**: Simple API for strategy execution

## 📁 Structure

```
core/
├── __init__.py              # Module exports
├── strategy_factory.py     # Strategy factory and registration
├── trading_core.py          # Main orchestrator
├── example_usage.py         # Usage examples
└── README.md               # This file
```

## 🚀 Quick Start

### Basic Usage

```python
from core import TradingCore
from lumibot.credentials import ALPACA_TEST_CONFIG

# Initialize core
core = TradingCore(broker_config=ALPACA_TEST_CONFIG)

# Execute strategy (as simple as specified!)
core.run(strategy="MeanReversion", params={...}, mode="paper")
```

### Available Modes

- **`backtest`**: Historical backtesting
- **`paper`**: Paper trading with live data
- **`live`**: Live trading with real money ⚠️

## 🤖 Conversational Telegram Bot (Agno + Core)

Run from `packages/core`:

```bash
cd lumibot-dev/packages/core
python run_telegram_bot.py
```

Required env vars:

```bash
export TELEGRAM_BOT_TOKEN="..."
export ALPACA_API_KEY="..."
export ALPACA_API_SECRET="..."
```

Optional for conversational mode:

```bash
# Use one of these
export ANTHROPIC_API_KEY="..."
export OPENAI_API_KEY="..."
```

Telegram commands:
- `/strategies`
- `/run LiveTestStrategy mode=paper order_interval_minutes=2 order_size_usd=15`
- `/status LiveTestStrategy`
- `/set LiveTestStrategy test_duration_hours 0.2`
- `/stop LiveTestStrategy`

Natural language chat is enabled when Agno has a model API key configured.

## 📋 Strategy Management

### Auto-discovery

The core automatically discovers strategies from the `strategies/` directory:

```python
# Strategies are auto-registered on initialization
core = TradingCore(broker_config=config)
# ✓ Discovered strategy: CarlosMeanReversionStrategy
# ✓ Discovered strategy: MartinGalaStrategy
# ✓ Discovered strategy: VolumeMultiplayerStrategy
```

### Manual Registration

```python
core.register_strategy(
    name="CustomStrategy",
    strategy_class=MyCustomStrategy,
    default_config={"param1": "value1"}
)
```

### List Available Strategies

```python
strategies = core.list_strategies()
for name, info in strategies.items():
    print(f"{name}: {info['class']}")
    print(f"Parameters: {info['parameters']}")
```

## 🎮 Execution Examples

### Backtesting

```python
results = core.run(
    strategy="CarlosMeanReversionStrategy",
    mode="backtest",
    params={
        "symbol": "QQQ",
        "daily_gain_threshold": 0.03,
        "paper_trade_qty": 100
    },
    # Backtest-specific options
    backtesting_start=start_date,
    backtesting_end=end_date,
    benchmark_asset='SPY'
)
```

### Paper Trading

```python
strategy_instance = core.run(
    strategy="Momentum",
    mode="paper", 
    params={
        "symbol": "AAPL",
        "lookback_period": 20,
        "position_size": 0.1
    }
)
```

### Live Trading

```python
# ⚠️ WARNING: Live trading with real money!
strategy_instance = core.run(
    strategy="MeanReversion",
    mode="live",
    params={
        "symbol": "SPY",
        "risk_level": 0.02
    }
)
```

## 🛠️ Convenience Methods

```python
# Equivalent to core.run(strategy, "backtest", params)
results = core.backtest("Strategy", params)

# Equivalent to core.run(strategy, "paper", params)  
instance = core.paper_trade("Strategy", params)

# Equivalent to core.run(strategy, "live", params)
instance = core.live_trade("Strategy", params)
```

## 🏗️ Architecture

The core follows the factory pattern with clean separation of concerns:

```
┌─────────────────────┐
│   TradingCore       │ ← Main orchestrator
│   - run()           │
│   - backtest()      │
│   - paper_trade()   │
│   - live_trade()    │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  StrategyFactory    │ ← Strategy management
│  - register()       │
│  - create()         │
│  - auto_discover()  │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│   Strategy Classes  │ ← Lumibot strategies
│   (Auto-discovered) │
└─────────────────────┘
```

## 📚 Strategy Requirements

Strategies must inherit from `lumibot.strategies.Strategy`:

```python
from lumibot.strategies import Strategy

class MyStrategy(Strategy):
    parameters = {
        "symbol": "SPY",
        "lookback": 20,
        # ... other parameters
    }
    
    def initialize(self):
        # Strategy initialization
        pass
    
    def on_trading_iteration(self):
        # Trading logic
        pass
```

## 🔧 Configuration

### Broker Configuration

```python
ALPACA_CONFIG = {
    "API_KEY": "your_api_key",
    "API_SECRET": "your_secret_key", 
    "PAPER": True,  # Set to False for live trading
}

core = TradingCore(broker_config=ALPACA_CONFIG)
```

### Default Backtest Settings

The core provides sensible defaults for backtesting:

- **Period**: Last 6 months
- **Benchmark**: SPY
- **Timestep**: Daily
- **Market**: NASDAQ
- **Analysis**: Enabled with progress bar

## 🔍 Validation

The core validates strategy parameters before execution:

```python
# Automatic validation
core.run(strategy="MyStrategy", params={"required_param": "value"})

# Manual validation
is_valid = core.factory.validate_strategy_config("MyStrategy", params)
```

## ⚡ Performance

- **Auto-discovery**: Strategies loaded once on initialization
- **Lazy loading**: Strategy instances created on demand  
- **Memory efficient**: Minimal overhead for unused strategies
- **Extensible**: Easy to add new brokers and execution modes

## 🔮 Future Extensions

The architecture supports future interfaces as specified:

- **CLI Interface**: Using Typer framework
- **REST API**: FastAPI integration for web dashboards  
- **Telegram Bot**: Chat-based strategy execution
- **Configuration files**: YAML/JSON runners

## 📝 Example

See `example_usage.py` for complete usage demonstrations.

## 🏃‍♂️ Running

```bash
# Test the core functionality
python core/example_usage.py

# Import in your own scripts
from core import TradingCore
```

---

**The core abstracts Lumibot execution complexity to make strategy execution as simple as:**

```python
core.run(strategy="MeanReversion", params={...}, mode="paper")
```

Exactly as specified in the requirements! ✅
