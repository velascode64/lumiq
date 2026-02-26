---
name: lumibot-strategy-iteration
description: Use when creating or iterating Lumibot strategies in this repo, especially ETH/crypto backtests. Guides hypothesis-to-backtest workflow, log review, parameter tuning, regime validation, and live-risk assessment using files under core/strategies/backtesting and lumiq/logs.
---

# Lumibot Strategy Iteration (Lumiq)

Use this skill when the user wants to:
- turn a trading idea into a Lumibot backtest strategy,
- iterate parameters from backtest results,
- compare periods/regimes,
- or decide whether a strategy is safe enough for paper/live.

This skill is project-specific for `lumiq/core`.

## Scope

Primary paths:
- `lumiq/core/strategies/backtesting`
- `lumiq/logs`
- `lumiq/core/.env`

Recent examples in this repo:
- `lumiq/core/strategies/backtesting/eth_volatility_regime_backtest.py`
- `lumiq/core/strategies/backtesting/eth_aggressive_momentum_ytd_backtest.py`

## Workflow (the process we used)

1. **Extract the hypothesis as measurable rules**
   - Convert narrative into entries/exits/risk.
   - Example: “ETH oscillates 2%-5% before moves” became regime filters + pullback/breakout rules.

2. **Choose the first test shape**
   - `signal/backtest study` if hypothesis is unclear.
   - `tradable strategy` if entry/exit/risk are already concrete.
   - For aggressive ETH target return work, we moved to a tradable momentum strategy.

3. **Create a backtest strategy file in**
   - `lumiq/core/strategies/backtesting/`
   - Prefer copying structure from an existing strategy in this repo for logging/style.

4. **Handle Lumibot/Alpaca backtesting constraints**
   - In this environment, `AlpacaBacktesting` only accepts `timestep="day"` or `timestep="minute"`.
   - If hypothesis is hourly, fetch `minute` and aggregate locally to synthetic hourly bars.
   - For crypto quote issues (e.g., `USDC` valuation problems), use `ETH/USD` proxy in backtest and document it.

5. **Run a target-period backtest**
   - Usually YTD or user-specified period first.
   - Save the run and inspect generated files in `lumiq/logs`.

6. **Review logs, not just the headline return**
   - Check:
     - `*_tearsheet.csv`
     - `*_trades.csv`
     - `*_trade_events.csv`
     - `*_settings.json`
   - Evaluate win rate, avg win/loss, drawdown, time in market, trade count, and whether the strategy is behaving as intended.

7. **Iterate one axis at a time**
   - Examples:
     - entry strictness (signals too few / too many)
     - stop/trailing behavior
     - position sizing (risk amplification)
     - trend/regime filters
   - Avoid changing everything at once unless doing a deliberate reframe (e.g., “drop mean reversion, use momentum”).

8. **Validate across regimes (required before live)**
   - Run multiple periods (e.g., 2023, 2024, 2025 YTD).
   - If performance is regime-dependent, add a regime gate instead of forcing one strategy to work everywhere.

9. **Assess live risk separately from backtest metrics**
   - Slippage, fees, data quality, infra reliability, leverage/margin behavior, and stop behavior in crypto volatility.

## Strategy iteration rules

- Do not optimize only for `CAGR`.
- Require minimum evidence:
  - enough trades (avoid 1-trade “successes”),
  - acceptable drawdown,
  - decent Sharpe/Sortino,
  - consistency across at least 2 different periods.
- If user wants a high target (e.g., 50%+ or 90%), explicitly call out overfitting risk and validate out-of-sample.

## Commands (project-specific)

Run a backtest (example):

```bash
cd /Users/gdesign/developer-projects/algorithmic-trading/traders/lumiq
conda run --no-capture-output -n lumiq python core/strategies/backtesting/eth_aggressive_momentum_ytd_backtest.py --source alpaca --start 2025-02-01 --end 2026-02-01
```

List recent logs:

```bash
ls -lt /Users/gdesign/developer-projects/algorithmic-trading/traders/lumiq/logs | head -40
```

## Output expectations when using this skill

When iterating a strategy, return:
- what changed (logic + parameters),
- why it changed,
- what period was tested,
- key metrics,
- trade behavior diagnosis,
- live risks and next iteration recommendation.

## References

- For a repeatable iteration checklist and review template, read:
  - `references/iteration-playbook.md`
