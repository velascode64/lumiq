# AI Trading Companion Monorepo

This repository has been a long time coming.

I have wanted to publish it for a while because there are already too many trading libraries, broker SDKs, technical analysis packages, and agent frameworks. The hard part is no longer finding tools. The hard part is knowing what to combine, what to trust, and how to turn all of that into something that actually helps a trader.

My current view is simple: trading software now needs an intelligence layer.

That layer should help traders monitor ideas, review positions, track portfolios, talk through possible entries, and generate or test strategies. Not as a toy chatbot, but as something that can sit on top of real broker APIs, strategy engines, and market workflows.

Even though everything right now is moving around agent platforms like OpenClaw, I do not think the end goal is to create thousands of disconnected skills. I think the stronger approach is to build focused systems and teams that can do real follow-through: monitor, report, compare, test, and improve.

Ideally, OpenClaw or any other agent runtime could use this repository as a real backend. An agent could take this library, start testing strategies, create new teams, improve portfolio monitoring, and help users discover opportunities with better context and better benchmarks. That may be the right path for agents to create strategies that are actually measurable, useful, and understandable for non-technical traders.

That is the main idea here:

**an AI companion for trading.**

## What This Repo Is

This is a monorepo focused on trading automation, portfolio monitoring, and agent-driven workflows.

It combines:

- a trading execution layer built around **Lumibot** and **Alpaca**
- a product layer for chat, reporting, and orchestration
- multi-agent experiments using **Agno**
- supporting experiments with other agent runtimes and research frameworks

The main product direction today is:

- `lumiq`: the application layer
- `lumibot-dev`: the trading engine and strategy workspace

Other folders exist as experiments, references, or parallel explorations.

## Main Components

### `lumiq`

This is the clearest application layer in the repo.

It provides:

- a **FastAPI core server**
- a **Telegram bot**
- a shared runtime that wires together strategies, agents, alerts, reports, watchlists, and persistence
- Agno-based teams for task delegation

Key responsibilities inside `lumiq`:

- talk to users through chat
- route requests to the right team or tool
- manage watchlists and groups
- generate portfolio and news reports
- expose APIs for strategy control
- keep a central runtime for long-lived services

### `lumibot-dev`

This is the trading foundation.

It includes:

- the Lumibot codebase
- strategy runners
- example live scripts
- tests and docs

This is where the actual trading and backtesting mechanics live.

### `automaton`, `eliza-trader`, `trading-agents`, `openclaw`

These folders represent different explorations:

- autonomous agent runtimes
- ElizaOS-based agents and MCP setups
- multi-agent financial research frameworks
- future OpenClaw integration direction

They are useful because the long-term goal is not just “run one bot.” The goal is to make the system easier for agent runtimes to extend and improve.

## What You Can Do Today

This repo is built around practical workflows, not just prompts.

You can:

- talk to agent teams through chat
- manage and inspect **watchlists** and grouped tickers
- generate **portfolio reviews**
- generate **news digests**
- run and monitor **trading strategies**
- switch between **paper** and **live** execution modes
- compute and display **P&L**
- extend the system with new teams, tools, and workflows

In practice, the product direction is:

- users interact through Telegram (and later other channels)
- the application runtime interprets the request
- deterministic handlers deal with clear commands
- agent teams handle more flexible, contextual tasks
- Lumibot and broker integrations handle execution

## Team-Based Design

One of the core ideas in this repo is that a trading assistant should not be one giant “super-agent.”

It should be a small system of focused teams.

That means separate responsibilities for things like:

- strategy operations
- live trading actions
- alerts
- technical analysis
- news monitoring
- portfolio review

This matters because real trading workflows need follow-through. A useful assistant should not only answer a question. It should know how to:

- look up the right data
- produce a report
- update a watchlist
- evaluate a signal
- compare outcomes over time

That is why this repo is structured around teams and runtime orchestration instead of only prompt-based skills.

## Watchlists, Reports, and Chat

The application layer supports operational features that are useful for day-to-day trading:

- **Watchlists**
  - create groups of tickers
  - maintain favorites
  - track focused sets like AI, crypto, gold, or sector-specific ideas

- **Reports**
  - portfolio review summaries
  - grouped watchlist reports
  - news digests
  - P&L views

- **Chat**
  - Telegram is the current user-facing interface
  - messages can be handled deterministically when the command is obvious
  - more flexible requests can be delegated to agent teams

This is the practical center of the repo: turning raw trading infrastructure into something a person can actually use every day.

## How To Extend It

The most important extension path is not “add more code everywhere.”

It is:

**add better teams.**

You can keep extending this repo by adding:

- new Agno team members
- new tools for existing teams
- new reporting flows
- new portfolio review logic
- new watchlist workflows
- new strategy-testing loops
- new backtesting pipelines

Good next extensions include:

- a dedicated strategy research team
- a benchmarking team that compares new strategies against SPY, QQQ, BTC, or custom references
- a portfolio risk team
- a trade journal review team
- a non-technical “idea explainer” team for traders who want plain language summaries

The real value here is that the repo can grow as a working system, not just as a collection of one-off scripts.

## Running the App Layer

The easiest current entrypoint for the application side is `lumiq`.

Typical local entrypoints include:

```bash
cd lumiq
python run_api.py
```

or:

```bash
cd lumiq
python run_telegram_bot.py
```

There are also helper scripts such as:

- `lumiq/run_local_core.sh`
- `lumiq/run_local_telegram.sh`
- `lumiq/run_local_stack.sh`

You will generally need environment variables for:

- Alpaca credentials
- Telegram bot credentials
- whichever model provider you use for the agents

## Running Backtests

The backtesting engine lives in `lumibot-dev`.

A simple Lumibot example can be run with:

```bash
cd lumibot-dev
python -m lumibot.example_strategies.stock_buy_and_hold
```

This repo also includes strategy runner scripts and custom strategy files for more realistic testing and live execution.

Common places to look:

- `lumibot-dev/strategy_runner.py`
- `lumibot-dev/run_eth_momentum.py`
- `lumibot-dev/run_crypto_live.py`
- `lumiq/scripts/`

If you want to extend strategy development, the intended direction is:

- create or iterate on a strategy
- backtest it
- compare it to a benchmark
- promote it into paper trading
- only then move it into live workflows

That path is much more useful than jumping directly from idea to live execution.

## Intended Future Direction

This repo is meant to become more useful as agents get better.

The long-term goal is not only to have a Telegram bot that can answer questions.

The long-term goal is to have a strong backend that:

- agent runtimes can plug into
- teams can extend
- strategies can be tested against benchmarks
- portfolio tracking can be improved over time
- non-technical traders can use without needing to understand every API behind it

If OpenClaw or another agent system wants to do serious trading support, the right path is probably not to create endless isolated skills.

The better path is to connect to a system like this one:

- a real trading engine
- real reporting
- real team orchestration
- and a codebase that can keep evolving

## Final Note

This repository is not trying to be “the one perfect framework.”

It is trying to be a useful layer between:

- trading infrastructure
- agent systems
- and actual traders

That is why it mixes execution, reporting, teams, watchlists, and experiments.

The objective is practical:

build an AI companion that helps people trade with better context, better monitoring, and better strategy iteration.
