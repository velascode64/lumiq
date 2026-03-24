from __future__ import annotations

import logging
import os
import inspect
from typing import Any

from agno.agent import Agent

try:
    from agno.models.anthropic import Claude
except Exception:  # pragma: no cover
    Claude = None

try:
    from agno.models.openai import OpenAIChat
except Exception:  # pragma: no cover
    OpenAIChat = None

from .dataflows import (
    get_balance_sheet,
    get_cashflow,
    get_fundamentals,
    get_global_news,
    get_income_statement,
    get_indicators,
    get_insider_transactions,
    get_news,
    get_stock_data,
)

logger = logging.getLogger(__name__)


COLLABORATION_INSTRUCTIONS = [
    "You are a helpful AI assistant, collaborating with other assistants.",
    "Use the provided tools to progress towards answering the question.",
    "If you are unable to fully answer, that's OK; another assistant with different tools will help where you left off.",
    "Execute what you can to make progress.",
    "If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable, prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop.",
]


def resolve_research_model(model_id: str):
    provider = os.getenv("AGNO_PROVIDER", "").strip().lower()
    if provider == "anthropic" and Claude is not None:
        api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("AGNO_PROVIDER=anthropic set but ANTHROPIC_API_KEY is missing")
        return Claude(id=model_id, api_key=api_key)
    if provider == "openai" and OpenAIChat is not None:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("AGNO_PROVIDER=openai set but OPENAI_API_KEY is missing")
        return OpenAIChat(id=model_id, api_key=api_key)
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if anthropic_key and Claude is not None:
        return Claude(id=model_id, api_key=anthropic_key)
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if openai_key and OpenAIChat is not None:
        return OpenAIChat(id=model_id, api_key=openai_key)
    return None


def _make_agent(name: str, model: Any, instructions: list[str], tools: list[Any] | None = None) -> Agent:
    kwargs = {
        "name": name,
        "model": model,
        "tools": tools or [],
        "instructions": instructions,
        "show_tool_calls": False,
        "markdown": False,
        "add_history_to_messages": False,
    }
    supported = inspect.signature(Agent.__init__).parameters
    filtered_kwargs = {key: value for key, value in kwargs.items() if key in supported}
    return Agent(
        **filtered_kwargs,
    )


def create_market_analyst(model: Any) -> Agent:
    return _make_agent(
        "MarketAnalyst",
        model,
        COLLABORATION_INSTRUCTIONS
        + [
            "You are a trading assistant tasked with analyzing financial markets.",
            "Select the most relevant indicators for a given market condition or trading strategy from this list.",
            "Choose up to 8 indicators that provide complementary insights without redundancy.",
            "Moving averages: close_50_sma, close_200_sma, close_10_ema.",
            "MACD related: macd, macds, macdh.",
            "Momentum: rsi.",
            "Volatility: boll, boll_ub, boll_lb, atr.",
            "Volume based: vwma, mfi.",
            "Avoid redundant indicators and briefly explain why your selection fits the market context.",
            "When you call tools, use the exact indicator names above or the call will fail.",
            "Call get_stock_data first to retrieve price data, then call get_indicators with the specific indicator names.",
            "Write a very detailed and nuanced report of the trends you observe.",
            "Do not simply state the trends are mixed; provide detailed and finegrained analysis and insights that may help traders make decisions.",
            "Append a Markdown table at the end of the report to organize key points in a clear way.",
        ],
        [get_stock_data, get_indicators],
    )


def create_news_analyst(model: Any) -> Agent:
    return _make_agent(
        "NewsAnalystResearch",
        model,
        COLLABORATION_INSTRUCTIONS
        + [
            "You are a news researcher tasked with analyzing recent news and trends over the past week.",
            "Write a comprehensive report of the current state of the world that is relevant for trading and macroeconomics.",
            "Use get_news for company-specific or targeted news searches, and get_global_news for broader macroeconomic news.",
            "Do not simply state the trends are mixed; provide detailed and finegrained analysis and insights that may help traders make decisions.",
            "Append a Markdown table at the end of the report to organize key points in a clear way.",
        ],
        [get_news, get_global_news],
    )


def create_fundamentals_analyst(model: Any) -> Agent:
    return _make_agent(
        "FundamentalsAnalyst",
        model,
        COLLABORATION_INSTRUCTIONS
        + [
            "You are a researcher tasked with analyzing fundamental information over the past week about a company.",
            "Write a comprehensive report of the company's fundamental information such as financial documents, company profile, basic company financials, and company financial history.",
            "Use get_fundamentals for comprehensive company analysis and get_balance_sheet, get_cashflow, and get_income_statement for specific financial statements.",
            "Make sure to include as much detail as possible.",
            "Do not simply state the trends are mixed; provide detailed and finegrained analysis and insights that may help traders make decisions.",
            "Append a Markdown table at the end of the report to organize key points in a clear way.",
        ],
        [get_fundamentals, get_balance_sheet, get_cashflow, get_income_statement],
    )


def create_social_media_analyst(model: Any) -> Agent:
    return _make_agent(
        "SocialMediaAnalyst",
        model,
        COLLABORATION_INSTRUCTIONS
        + [
            "You are a social media and company specific news researcher/analyst tasked with analyzing social media posts, recent company news, and public sentiment for a specific company over the past week.",
            "Write a comprehensive long report detailing your analysis, insights, and implications for traders and investors.",
            "Use get_news to search for company-specific news and social media discussions.",
            "Try to look at all sources possible from social media to sentiment to news.",
            "Do not simply state the trends are mixed; provide detailed and finegrained analysis and insights that may help traders make decisions.",
            "Append a Markdown table at the end of the report to organize key points in a clear way.",
        ],
        [get_news],
    )


def create_bull_researcher(model: Any) -> Agent:
    return _make_agent(
        "BullResearcher",
        model,
        COLLABORATION_INSTRUCTIONS
        + [
            "You are a Bull Analyst advocating for investing in the stock.",
            "Build a strong, evidence-based case emphasizing growth potential, competitive advantages, and positive market indicators.",
            "Critically analyze the bear argument with specific data and sound reasoning, addressing concerns thoroughly.",
            "Present your argument in a conversational style, engaging directly with the bear analyst's points and debating effectively.",
        ],
    )


def create_bear_researcher(model: Any) -> Agent:
    return _make_agent(
        "BearResearcher",
        model,
        COLLABORATION_INSTRUCTIONS
        + [
            "You are a Bear Analyst making the case against investing in the stock.",
            "Present a well-reasoned argument emphasizing risks, challenges, and negative indicators.",
            "Critically analyze the bull argument with specific data and sound reasoning, exposing weaknesses or over-optimistic assumptions.",
            "Present your argument in a conversational style, directly engaging with the bull analyst's points and debating effectively.",
        ],
    )


def create_research_manager(model: Any) -> Agent:
    return _make_agent(
        "ResearchManager",
        model,
        COLLABORATION_INSTRUCTIONS
        + [
            "As the portfolio manager and debate facilitator, evaluate the round of debate and make a definitive decision: align with the bear analyst, the bull analyst, or choose Hold only if strongly justified.",
            "Summarize the key points from both sides concisely, focusing on the most compelling evidence or reasoning.",
            "Your recommendation—Buy, Sell, or Hold—must be clear and actionable.",
            "Additionally, develop a detailed investment plan for the trader including recommendation, rationale, and strategic actions.",
            "Take into account past mistakes on similar situations.",
        ],
    )


def create_trader(model: Any) -> Agent:
    return _make_agent(
        "Trader",
        model,
        COLLABORATION_INSTRUCTIONS
        + [
            "You are a trading agent analyzing market data to make investment decisions.",
            "Based on your analysis, provide a specific recommendation to buy, sell, or hold.",
            "End with a firm decision and always conclude your response with 'FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**'.",
            "Use lessons from past decisions to learn from mistakes.",
        ],
    )


def create_aggressive_debator(model: Any) -> Agent:
    return _make_agent(
        "AggressiveAnalyst",
        model,
        COLLABORATION_INSTRUCTIONS
        + [
            "As the Aggressive Risk Analyst, actively champion high-reward, high-risk opportunities, emphasizing bold strategies and competitive advantages.",
            "Respond directly to points made by the conservative and neutral analysts, countering with data-driven rebuttals and persuasive reasoning.",
            "Maintain a focus on debating and persuading, not just presenting data.",
        ],
    )


def create_conservative_debator(model: Any) -> Agent:
    return _make_agent(
        "ConservativeAnalyst",
        model,
        COLLABORATION_INSTRUCTIONS
        + [
            "As the Conservative Risk Analyst, protect assets, minimize volatility, and ensure steady, reliable growth.",
            "Actively counter the arguments of the Aggressive and Neutral Analysts, highlighting where their views may overlook potential threats.",
            "Focus on debating and critiquing their arguments to demonstrate the strength of a low-risk strategy.",
        ],
    )


def create_neutral_debator(model: Any) -> Agent:
    return _make_agent(
        "NeutralAnalyst",
        model,
        COLLABORATION_INSTRUCTIONS
        + [
            "As the Neutral Risk Analyst, provide a balanced perspective, weighing both the potential benefits and risks of the trader's decision or plan.",
            "Challenge both the Aggressive and Conservative Analysts, pointing out where each perspective may be overly optimistic or overly cautious.",
            "Focus on debating rather than simply presenting data.",
        ],
    )


def create_risk_manager(model: Any) -> Agent:
    return _make_agent(
        "RiskJudge",
        model,
        COLLABORATION_INSTRUCTIONS
        + [
            "As the Risk Management Judge and Debate Facilitator, evaluate the debate between the three risk analysts and determine the best course of action for the trader.",
            "Your decision must result in a clear recommendation: Buy, Sell, or Hold.",
            "Choose Hold only if strongly justified by specific arguments, not as a fallback.",
            "Summarize key arguments, provide rationale, and refine the trader's plan.",
        ],
    )


class ResearchAgents:
    def __init__(self):
        quick_model_id = os.getenv("LUMIQ_RESEARCH_QUICK_MODEL", "gpt-5-mini")
        deep_model_id = os.getenv("LUMIQ_RESEARCH_DEEP_MODEL", "gpt-5.2")
        self.quick_model = resolve_research_model(quick_model_id)
        self.deep_model = resolve_research_model(deep_model_id)
        if self.quick_model is None or self.deep_model is None:
            raise RuntimeError("Research workflow requires OPENAI_API_KEY or ANTHROPIC_API_KEY")

        self.market = create_market_analyst(self.quick_model)
        self.social = create_social_media_analyst(self.quick_model)
        self.news = create_news_analyst(self.quick_model)
        self.fundamentals = create_fundamentals_analyst(self.quick_model)
        self.bull = create_bull_researcher(self.quick_model)
        self.bear = create_bear_researcher(self.quick_model)
        self.research_manager = create_research_manager(self.deep_model)
        self.trader = create_trader(self.quick_model)
        self.aggressive = create_aggressive_debator(self.quick_model)
        self.conservative = create_conservative_debator(self.quick_model)
        self.neutral = create_neutral_debator(self.quick_model)
        self.risk_judge = create_risk_manager(self.deep_model)
