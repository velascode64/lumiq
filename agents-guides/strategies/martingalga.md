Strategy: Equity Averaging Down (Martingale Mean Reversion)

⸻

1. Strategy Type

Mean Reversion – Capital Scaling Strategy
Progressive Position Averaging
Instrument: Equities (no options)

⸻

2. Core Concept

If price drops after entry, increase position size to reduce average cost.

Exit when price reverts above new average cost.

⸻

3. Instrument Selection

Eligible Assets:
	•	Large-cap or strong companies
	•	High liquidity
	•	Historical tendency to mean revert
	•	Avoid penny stocks

Examples:
	•	TSLA
	•	META
	•	AMZN
	•	AAPL
	•	DIS
	•	INTC
	•	QQQ components

⸻

4. Initial Entry

Condition

Manual / discretionary entry near:
	•	Moving Average 200
	•	Support level
	•	Pullback in uptrend

For automation, define:

Entry Trigger:
Price touches 200 EMA
OR
Price drops ≥ X% from recent high (e.g., 5%)


⸻

5. Averaging Down Logic

Base Position

Initial Position Size = P0
Entry Price = E0
Average Cost = E0


⸻

Add Level 1

If price drops:

Drop Level 1 = -X% from E0

Then:

Buy Additional Position = P1
New Average Cost = (E0*P0 + E1*P1) / (P0 + P1)


⸻

Add Level 2

If price drops further:

Drop Level 2 = -Y% from previous entry

Buy additional shares.

Repeat process until:
	•	Max capital reached
	•	Max number of adds reached

⸻

6. Position Scaling Model

Christian version (implicit Martingale style):

Each new add >= previous size

Example:
	•	P0 = $1,000
	•	P1 = $2,000
	•	P2 = $4,000

OR equal adds (safer version):

P0 = P1 = P2


⸻

7. Exit Condition

Exit when:

Current Price ≥ Average Cost + Target %

Target examples:
	•	+2%
	•	+3%
	•	+5%
OR
Breakout above local resistance

⸻

8. Risk Limits (Critical)

Maximum Adds

Max Adds = N (e.g., 3 or 4 levels)

Maximum Capital Allocation

Max Capital per asset = X% of portfolio

If reached:
	•	No further averaging
	•	Accept drawdown

⸻

9. Stop Condition (Original Strategy)

Original version:
	•	No hard stop
	•	Hold until rebound

Automatable safer version:

Hard Stop:
If total drawdown ≥ -Z% of total allocated capital
→ Liquidate full position


⸻

10. Example Execution Flow

Select Stock
Enter Initial Position

While position open:

    If price drops to next threshold:
        Add shares
        Recalculate average cost

    If price >= average cost + target:
        Sell full position
        Close trade


⸻

11. Strategy Characteristics

Works Best In:
	•	Bull markets
	•	Strong companies
	•	Mean-reverting assets
	•	Index-heavy names

Fails In:
	•	Structural downtrends
	•	Earnings collapse
	•	Bankruptcy risk
	•	Long bear markets

⸻

12. Mathematical Nature

This is a capital-weighted mean reversion system.

It increases exposure as price moves against position.

Risk Profile:
	•	Convex loss
	•	Non-linear capital expansion
	•	High drawdown potential

⸻

13. Hidden Risk

If price continues trending down:

Capital usage increases exponentially
Liquidity decreases
Recovery required becomes larger

Example:
	•	-10% requires +11% recovery
	•	-20% requires +25%
	•	-50% requires +100%

⸻

14. Version Classification

This is NOT:
	•	Momentum trading
	•	Trend following
	•	Risk-controlled systematic trading

This IS:
	•	Averaging down capital scaling
	•	Passive mean reversion capture
	•	Capital pressure strategy

⸻

⚠️ Critical Warning

Pure Martingale without max capital cap = eventual blow-up risk.

Must define:
	•	Max number of adds
	•	Max % of portfolio per asset
	•	Market regime filter