# Iteration Playbook (Lumibot, ETH/Crypto)

## Purpose

Use this when iterating a strategy after a backtest run. It keeps the review focused on evidence instead of only optimizing a single metric.

## Review order

1. **Confirm instrument and quote**
   - Verify the strategy actually traded the intended asset (e.g., `ETH/USD` crypto, not stock ticker `ETH`).
   - Check `*_trades.csv` for asset type and price scale.

2. **Check sample size**
   - Number of round trips
   - Time in market
   - If trades are too few, do not trust headline CAGR.

3. **Check risk first**
   - Max drawdown
   - Longest drawdown duration
   - Loss clustering (consecutive losses)

4. **Check trade quality**
   - Win rate
   - Average win / average loss
   - Expectancy
   - Do losers come from same pattern (e.g., false breakout, early rebound entry)?

5. **Check regime dependence**
   - Run at least two other periods.
   - If strong in bull and weak in non-bull, label it explicitly as regime-dependent and add a regime gate.

## Common failure patterns (seen in this repo)

### 1. Catching knives
Symptoms:
- low win rate
- repeated buys near “support”
- losses continue after entry

Action:
- stop buying first oversold condition
- require rebound confirmation and/or trend filter

### 2. Too strict to evaluate
Symptoms:
- 1-2 trades in a year
- tiny drawdown and tiny return (or one stop-loss dominates)

Action:
- relax filters to produce enough samples before optimizing

### 3. Backtest infra mismatch
Symptoms:
- invalid timestep errors (`hour` unsupported)
- wrong quote valuation (`USDC` issues)

Action:
- use `minute` + local aggregation
- proxy quote asset in backtest (`USD`) and document it

## Change policy (important)

When iterating:
- Change **one category** at a time:
  - entries
  - exits
  - sizing
  - regime filter
- Record why the change was made.
- Re-run same period first, then out-of-sample period.

## Live-readiness checklist

Do not move to live just because backtest CAGR is high.

Minimum checklist:
- Paper trading run completed
- Slippage/fees considered
- Drawdown acceptable for actual capital
- Kill switch / stop controls available
- Regime assumptions documented
- Monitoring and alerting enabled

## Example reporting format

- **Period:** `2025-02-01 -> 2026-02-01`
- **What changed:** `Raised breakout momentum threshold; reduced trailing stop to 1.8%`
- **Why:** `Too many weak breakouts; wanted faster profit protection`
- **Result:** `CAGR 54.7%, Sharpe 1.99, Max DD 11.4%`
- **Diagnosis:** `Works in bullish momentum periods; likely degrades in sideways/bearish conditions`
- **Next step:** `Add regime gate and retest 2023/2024/2025`
