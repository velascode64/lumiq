from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from .agents import ResearchAgents
from .dataflows import configure_tradingagents_dataflows
from .memory import FinancialSituationMemory

logger = logging.getLogger(__name__)

ResearchEventCallback = Callable[[str, str, str], None]


@dataclass
class InvestDebateState:
    bull_history: str = ""
    bear_history: str = ""
    history: str = ""
    current_response: str = ""
    judge_decision: str = ""
    count: int = 0


@dataclass
class RiskDebateState:
    aggressive_history: str = ""
    conservative_history: str = ""
    neutral_history: str = ""
    history: str = ""
    latest_speaker: str = ""
    current_aggressive_response: str = ""
    current_conservative_response: str = ""
    current_neutral_response: str = ""
    judge_decision: str = ""
    count: int = 0


@dataclass
class ResearchState:
    company_of_interest: str
    trade_date: str
    start_date: str
    end_date: str
    look_back_days: int
    market_report: str = ""
    sentiment_report: str = ""
    news_report: str = ""
    fundamentals_report: str = ""
    investment_debate_state: InvestDebateState = field(default_factory=InvestDebateState)
    investment_plan: str = ""
    trader_investment_plan: str = ""
    risk_debate_state: RiskDebateState = field(default_factory=RiskDebateState)
    final_trade_decision: str = ""


class TradingAgentsAgnoWorkflow:
    def __init__(self):
        configure_tradingagents_dataflows()
        self.agents = ResearchAgents()
        self.bull_memory = FinancialSituationMemory("bull_memory")
        self.bear_memory = FinancialSituationMemory("bear_memory")
        self.trader_memory = FinancialSituationMemory("trader_memory")
        self.invest_judge_memory = FinancialSituationMemory("invest_judge_memory")
        self.risk_manager_memory = FinancialSituationMemory("risk_manager_memory")
        self.max_debate_rounds = 1
        self.max_risk_discuss_rounds = 1

    @staticmethod
    def _run(agent, message: str, session_id: str) -> str:
        response = agent.run(message, user_id="research-api", session_id=session_id)
        content = getattr(response, "content", None)
        return content if isinstance(content, str) else str(content or "")

    @staticmethod
    def _calc_lookback_days(start_date: str, end_date: str) -> int:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
        return max(1, (end_dt - start_dt).days)

    def _market_prompt(self, state: ResearchState) -> str:
        return (
            f"For your reference, the current date is {state.trade_date}. The company we want to look at is {state.company_of_interest}.\n"
            f"Use get_stock_data with start_date={state.start_date} and end_date={state.end_date}.\n"
            f"Then use get_indicators with curr_date={state.trade_date} and look_back_days={state.look_back_days}.\n"
            "Produce the market report now."
        )

    def _social_prompt(self, state: ResearchState) -> str:
        return (
            f"For your reference, the current date is {state.trade_date}. The current company we want to analyze is {state.company_of_interest}.\n"
            f"Use get_news with start_date={state.start_date} and end_date={state.end_date}.\n"
            "Produce the social media / sentiment report now."
        )

    def _news_prompt(self, state: ResearchState) -> str:
        return (
            f"For your reference, the current date is {state.trade_date}. We are looking at the company {state.company_of_interest}.\n"
            f"Use get_news with start_date={state.start_date} and end_date={state.end_date}.\n"
            f"Use get_global_news with curr_date={state.trade_date}.\n"
            "Produce the news report now."
        )

    def _fundamentals_prompt(self, state: ResearchState) -> str:
        return (
            f"For your reference, the current date is {state.trade_date}. The company we want to look at is {state.company_of_interest}.\n"
            f"Use current date {state.trade_date} for fundamentals tools.\n"
            "Produce the fundamentals report now."
        )

    def _curr_situation(self, state: ResearchState) -> str:
        return f"{state.market_report}\n\n{state.sentiment_report}\n\n{state.news_report}\n\n{state.fundamentals_report}"

    def _bull_prompt(self, state: ResearchState, memory_str: str) -> str:
        ds = state.investment_debate_state
        return f"""You are a Bull Analyst advocating for investing in the stock. Your task is to build a strong, evidence-based case emphasizing growth potential, competitive advantages, and positive market indicators. Leverage the provided research and data to address concerns and counter bearish arguments effectively.

Key points to focus on:
- Growth Potential: Highlight the company's market opportunities, revenue projections, and scalability.
- Competitive Advantages: Emphasize factors like unique products, strong branding, or dominant market positioning.
- Positive Indicators: Use financial health, industry trends, and recent positive news as evidence.
- Bear Counterpoints: Critically analyze the bear argument with specific data and sound reasoning, addressing concerns thoroughly and showing why the bull perspective holds stronger merit.
- Engagement: Present your argument in a conversational style, engaging directly with the bear analyst's points and debating effectively rather than just listing data.

Resources available:
Market research report: {state.market_report}
Social media sentiment report: {state.sentiment_report}
Latest world affairs news: {state.news_report}
Company fundamentals report: {state.fundamentals_report}
Conversation history of the debate: {ds.history}
Last bear argument: {ds.current_response}
Reflections from similar situations and lessons learned: {memory_str}
Use this information to deliver a compelling bull argument, refute the bear's concerns, and engage in a dynamic debate that demonstrates the strengths of the bull position. You must also address reflections and learn from lessons and mistakes you made in the past.
"""

    def _bear_prompt(self, state: ResearchState, memory_str: str) -> str:
        ds = state.investment_debate_state
        return f"""You are a Bear Analyst making the case against investing in the stock. Your goal is to present a well-reasoned argument emphasizing risks, challenges, and negative indicators. Leverage the provided research and data to highlight potential downsides and counter bullish arguments effectively.

Key points to focus on:
- Risks and Challenges: Highlight factors like market saturation, financial instability, or macroeconomic threats that could hinder the stock's performance.
- Competitive Weaknesses: Emphasize vulnerabilities such as weaker market positioning, declining innovation, or threats from competitors.
- Negative Indicators: Use evidence from financial data, market trends, or recent adverse news to support your position.
- Bull Counterpoints: Critically analyze the bull argument with specific data and sound reasoning, exposing weaknesses or over-optimistic assumptions.
- Engagement: Present your argument in a conversational style, directly engaging with the bull analyst's points and debating effectively rather than simply listing facts.

Resources available:
Market research report: {state.market_report}
Social media sentiment report: {state.sentiment_report}
Latest world affairs news: {state.news_report}
Company fundamentals report: {state.fundamentals_report}
Conversation history of the debate: {ds.history}
Last bull argument: {ds.current_response}
Reflections from similar situations and lessons learned: {memory_str}
Use this information to deliver a compelling bear argument, refute the bull's claims, and engage in a dynamic debate that demonstrates the risks and weaknesses of investing in the stock. You must also address reflections and learn from lessons and mistakes you made in the past.
"""

    def _research_manager_prompt(self, state: ResearchState, memory_str: str) -> str:
        ds = state.investment_debate_state
        return f"""As the portfolio manager and debate facilitator, your role is to critically evaluate this round of debate and make a definitive decision: align with the bear analyst, the bull analyst, or choose Hold only if it is strongly justified based on the arguments presented.

Summarize the key points from both sides concisely, focusing on the most compelling evidence or reasoning. Your recommendation—Buy, Sell, or Hold—must be clear and actionable. Avoid defaulting to Hold simply because both sides have valid points; commit to a stance grounded in the debate's strongest arguments.

Additionally, develop a detailed investment plan for the trader. This should include:
Your Recommendation: A decisive stance supported by the most convincing arguments.
Rationale: An explanation of why these arguments lead to your conclusion.
Strategic Actions: Concrete steps for implementing the recommendation.
Take into account your past mistakes on similar situations. Use these insights to refine your decision-making and ensure you are learning and improving. Present your analysis conversationally, as if speaking naturally, without special formatting.

Here are your past reflections on mistakes:
"{memory_str}"

Here is the debate:
Debate History:
{ds.history}"""

    def _trader_prompt(self, state: ResearchState, memory_str: str) -> str:
        return f"""Based on a comprehensive analysis by a team of analysts, here is an investment plan tailored for {state.company_of_interest}. This plan incorporates insights from current technical market trends, macroeconomic indicators, and social media sentiment. Use this plan as a foundation for evaluating your next trading decision.

Proposed Investment Plan: {state.investment_plan}

Leverage these insights to make an informed and strategic decision.

You are a trading agent analyzing market data to make investment decisions. Based on your analysis, provide a specific recommendation to buy, sell, or hold. End with a firm decision and always conclude your response with 'FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**' to confirm your recommendation. Do not forget to utilize lessons from past decisions to learn from your mistakes. Here is some reflections from similar situations you traded in and the lessons learned: {memory_str}"""

    def _aggressive_prompt(self, state: ResearchState) -> str:
        rs = state.risk_debate_state
        return f"""As the Aggressive Risk Analyst, your role is to actively champion high-reward, high-risk opportunities, emphasizing bold strategies and competitive advantages. When evaluating the trader's decision or plan, focus intently on the potential upside, growth potential, and innovative benefits—even when these come with elevated risk. Use the provided market data and sentiment analysis to strengthen your arguments and challenge the opposing views. Specifically, respond directly to each point made by the conservative and neutral analysts, countering with data-driven rebuttals and persuasive reasoning. Highlight where their caution might miss critical opportunities or where their assumptions may be overly conservative. Here is the trader's decision:

{state.trader_investment_plan}

Your task is to create a compelling case for the trader's decision by questioning and critiquing the conservative and neutral stances to demonstrate why your high-reward perspective offers the best path forward. Incorporate insights from the following sources into your arguments:

Market Research Report: {state.market_report}
Social Media Sentiment Report: {state.sentiment_report}
Latest World Affairs Report: {state.news_report}
Company Fundamentals Report: {state.fundamentals_report}
Here is the current conversation history: {rs.history} Here are the last arguments from the conservative analyst: {rs.current_conservative_response} Here are the last arguments from the neutral analyst: {rs.current_neutral_response}. If there are no responses from the other viewpoints, do not hallucinate and just present your point.

Engage actively by addressing any specific concerns raised, refuting the weaknesses in their logic, and asserting the benefits of risk-taking to outpace market norms. Maintain a focus on debating and persuading, not just presenting data. Challenge each counterpoint to underscore why a high-risk approach is optimal. Output conversationally as if you are speaking without any special formatting."""

    def _conservative_prompt(self, state: ResearchState) -> str:
        rs = state.risk_debate_state
        return f"""As the Conservative Risk Analyst, your primary objective is to protect assets, minimize volatility, and ensure steady, reliable growth. You prioritize stability, security, and risk mitigation, carefully assessing potential losses, economic downturns, and market volatility. When evaluating the trader's decision or plan, critically examine high-risk elements, pointing out where the decision may expose the firm to undue risk and where more cautious alternatives could secure long-term gains. Here is the trader's decision:

{state.trader_investment_plan}

Your task is to actively counter the arguments of the Aggressive and Neutral Analysts, highlighting where their views may overlook potential threats or fail to prioritize sustainability. Respond directly to their points, drawing from the following data sources to build a convincing case for a low-risk approach adjustment to the trader's decision:

Market Research Report: {state.market_report}
Social Media Sentiment Report: {state.sentiment_report}
Latest World Affairs Report: {state.news_report}
Company Fundamentals Report: {state.fundamentals_report}
Here is the current conversation history: {rs.history} Here is the last response from the aggressive analyst: {rs.current_aggressive_response} Here is the last response from the neutral analyst: {rs.current_neutral_response}. If there are no responses from the other viewpoints, do not hallucinate and just present your point.

Engage by questioning their optimism and emphasizing the potential downsides they may have overlooked. Address each of their counterpoints to showcase why a conservative stance is ultimately the safest path for the firm's assets. Focus on debating and critiquing their arguments to demonstrate the strength of a low-risk strategy over their approaches. Output conversationally as if you are speaking without any special formatting."""

    def _neutral_prompt(self, state: ResearchState) -> str:
        rs = state.risk_debate_state
        return f"""As the Neutral Risk Analyst, your role is to provide a balanced perspective, weighing both the potential benefits and risks of the trader's decision or plan. You prioritize a well-rounded approach, evaluating the upsides and downsides while factoring in broader market trends, potential economic shifts, and diversification strategies. Here is the trader's decision:

{state.trader_investment_plan}

Your task is to challenge both the Aggressive and Conservative Analysts, pointing out where each perspective may be overly optimistic or overly cautious. Use insights from the following data sources to support a moderate, sustainable strategy to adjust the trader's decision:

Market Research Report: {state.market_report}
Social Media Sentiment Report: {state.sentiment_report}
Latest World Affairs Report: {state.news_report}
Company Fundamentals Report: {state.fundamentals_report}
Here is the current conversation history: {rs.history} Here is the last response from the aggressive analyst: {rs.current_aggressive_response} Here is the last response from the conservative analyst: {rs.current_conservative_response}. If there are no responses from the other viewpoints, do not hallucinate and just present your point.

Engage actively by analyzing both sides critically, addressing weaknesses in the aggressive and conservative arguments to advocate for a more balanced approach. Challenge each of their points to illustrate why a moderate risk strategy might offer the best of both worlds, providing growth potential while safeguarding against extreme volatility. Focus on debating rather than simply presenting data, aiming to show that a balanced view can lead to the most reliable outcomes. Output conversationally as if you are speaking without any special formatting."""

    def _risk_judge_prompt(self, state: ResearchState, memory_str: str) -> str:
        rs = state.risk_debate_state
        return f"""As the Risk Management Judge and Debate Facilitator, your goal is to evaluate the debate between three risk analysts—Aggressive, Neutral, and Conservative—and determine the best course of action for the trader. Your decision must result in a clear recommendation: Buy, Sell, or Hold. Choose Hold only if strongly justified by specific arguments, not as a fallback when all sides seem valid. Strive for clarity and decisiveness.

Guidelines for Decision-Making:
1. Summarize Key Arguments: Extract the strongest points from each analyst, focusing on relevance to the context.
2. Provide Rationale: Support your recommendation with direct quotes and counterarguments from the debate.
3. Refine the Trader's Plan: Start with the trader's original plan, {state.investment_plan}, and adjust it based on the analysts' insights.
4. Learn from Past Mistakes: Use lessons from {memory_str} to address prior misjudgments and improve the decision.

Deliverables:
- A clear and actionable recommendation: Buy, Sell, or Hold.
- Detailed reasoning anchored in the debate and past reflections.

Analysts Debate History:
{rs.history}

Focus on actionable insights and continuous improvement. Build on past lessons, critically evaluate all perspectives, and ensure each decision advances better outcomes."""

    @staticmethod
    def _memory_str(memories: List[dict]) -> str:
        if not memories:
            return ""
        return "\n\n".join(rec["recommendation"] for rec in memories)

    @staticmethod
    def _emit(callback: Optional[ResearchEventCallback], stage: str, title: str, content: str) -> None:
        logger.info("Research workflow event | stage=%s | title=%s\n%s", stage, title, content or "(sin contenido)")
        if callback is None:
            return
        callback(stage, title, content)

    def run(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        selected_analysts: List[str] | None = None,
        on_event: Optional[ResearchEventCallback] = None,
    ) -> Dict[str, Any]:
        selected = selected_analysts or ["market", "social", "news", "fundamentals"]
        look_back_days = self._calc_lookback_days(start_date, end_date)
        state = ResearchState(
            company_of_interest=ticker,
            trade_date=end_date,
            start_date=start_date,
            end_date=end_date,
            look_back_days=look_back_days,
        )

        analyst_order = {
            "market": (self.agents.market, self._market_prompt, "market_report"),
            "social": (self.agents.social, self._social_prompt, "sentiment_report"),
            "news": (self.agents.news, self._news_prompt, "news_report"),
            "fundamentals": (self.agents.fundamentals, self._fundamentals_prompt, "fundamentals_report"),
        }
        self._emit(
            on_event,
            "start",
            f"Research started: {ticker}",
            f"Rango: {start_date} -> {end_date}\nAnalistas: {', '.join(selected)}",
        )
        for analyst_type in selected:
            agent, prompt_builder, field_name = analyst_order[analyst_type]
            value = self._run(agent, prompt_builder(state), session_id=f"research-{ticker}-{analyst_type}-{end_date}")
            setattr(state, field_name, value)
            self._emit(on_event, analyst_type, f"{analyst_type.title()} report", value)

        curr_situation = self._curr_situation(state)

        for _ in range(self.max_debate_rounds):
            bull_mem = self._memory_str(self.bull_memory.get_memories(curr_situation, n_matches=2))
            bull_resp = self._run(self.agents.bull, self._bull_prompt(state, bull_mem), session_id=f"research-{ticker}-bull-{end_date}")
            bull_arg = f"Bull Analyst: {bull_resp}"
            state.investment_debate_state.history += ("\n" if state.investment_debate_state.history else "") + bull_arg
            state.investment_debate_state.bull_history += ("\n" if state.investment_debate_state.bull_history else "") + bull_arg
            state.investment_debate_state.current_response = bull_arg
            state.investment_debate_state.count += 1
            self._emit(on_event, "bull", "Bull deliberation", bull_resp)

            bear_mem = self._memory_str(self.bear_memory.get_memories(curr_situation, n_matches=2))
            bear_resp = self._run(self.agents.bear, self._bear_prompt(state, bear_mem), session_id=f"research-{ticker}-bear-{end_date}")
            bear_arg = f"Bear Analyst: {bear_resp}"
            state.investment_debate_state.history += "\n" + bear_arg
            state.investment_debate_state.bear_history += ("\n" if state.investment_debate_state.bear_history else "") + bear_arg
            state.investment_debate_state.current_response = bear_arg
            state.investment_debate_state.count += 1
            self._emit(on_event, "bear", "Bear deliberation", bear_resp)

        judge_mem = self._memory_str(self.invest_judge_memory.get_memories(curr_situation, n_matches=2))
        judge_resp = self._run(self.agents.research_manager, self._research_manager_prompt(state, judge_mem), session_id=f"research-{ticker}-manager-{end_date}")
        state.investment_debate_state.judge_decision = judge_resp
        state.investment_plan = judge_resp
        self._emit(on_event, "research_manager", "Research manager decision", judge_resp)

        trader_mem = self._memory_str(self.trader_memory.get_memories(curr_situation, n_matches=2)) or "No past memories found."
        state.trader_investment_plan = self._run(self.agents.trader, self._trader_prompt(state, trader_mem), session_id=f"research-{ticker}-trader-{end_date}")
        self._emit(on_event, "trader", "Trader plan", state.trader_investment_plan)

        for _ in range(self.max_risk_discuss_rounds):
            agg_resp = self._run(self.agents.aggressive, self._aggressive_prompt(state), session_id=f"research-{ticker}-aggressive-{end_date}")
            agg_arg = f"Aggressive Analyst: {agg_resp}"
            rs = state.risk_debate_state
            rs.history += ("\n" if rs.history else "") + agg_arg
            rs.aggressive_history += ("\n" if rs.aggressive_history else "") + agg_arg
            rs.latest_speaker = "Aggressive"
            rs.current_aggressive_response = agg_arg
            rs.count += 1
            self._emit(on_event, "aggressive", "Aggressive risk deliberation", agg_resp)

            cons_resp = self._run(self.agents.conservative, self._conservative_prompt(state), session_id=f"research-{ticker}-conservative-{end_date}")
            cons_arg = f"Conservative Analyst: {cons_resp}"
            rs.history += "\n" + cons_arg
            rs.conservative_history += ("\n" if rs.conservative_history else "") + cons_arg
            rs.latest_speaker = "Conservative"
            rs.current_conservative_response = cons_arg
            rs.count += 1
            self._emit(on_event, "conservative", "Conservative risk deliberation", cons_resp)

            neu_resp = self._run(self.agents.neutral, self._neutral_prompt(state), session_id=f"research-{ticker}-neutral-{end_date}")
            neu_arg = f"Neutral Analyst: {neu_resp}"
            rs.history += "\n" + neu_arg
            rs.neutral_history += ("\n" if rs.neutral_history else "") + neu_arg
            rs.latest_speaker = "Neutral"
            rs.current_neutral_response = neu_arg
            rs.count += 1
            self._emit(on_event, "neutral", "Neutral risk deliberation", neu_resp)

        risk_mem = self._memory_str(self.risk_manager_memory.get_memories(curr_situation, n_matches=2))
        risk_resp = self._run(self.agents.risk_judge, self._risk_judge_prompt(state, risk_mem), session_id=f"research-{ticker}-riskjudge-{end_date}")
        state.risk_debate_state.judge_decision = risk_resp
        state.final_trade_decision = risk_resp
        self._emit(on_event, "risk_judge", "Final risk decision", risk_resp)

        return {
            "company_of_interest": state.company_of_interest,
            "trade_date": state.trade_date,
            "start_date": state.start_date,
            "end_date": state.end_date,
            "look_back_days": state.look_back_days,
            "market_report": state.market_report,
            "sentiment_report": state.sentiment_report,
            "news_report": state.news_report,
            "fundamentals_report": state.fundamentals_report,
            "investment_debate_state": {
                "bull_history": state.investment_debate_state.bull_history,
                "bear_history": state.investment_debate_state.bear_history,
                "history": state.investment_debate_state.history,
                "current_response": state.investment_debate_state.current_response,
                "judge_decision": state.investment_debate_state.judge_decision,
                "count": state.investment_debate_state.count,
            },
            "investment_plan": state.investment_plan,
            "trader_investment_plan": state.trader_investment_plan,
            "risk_debate_state": {
                "aggressive_history": state.risk_debate_state.aggressive_history,
                "conservative_history": state.risk_debate_state.conservative_history,
                "neutral_history": state.risk_debate_state.neutral_history,
                "history": state.risk_debate_state.history,
                "latest_speaker": state.risk_debate_state.latest_speaker,
                "current_aggressive_response": state.risk_debate_state.current_aggressive_response,
                "current_conservative_response": state.risk_debate_state.current_conservative_response,
                "current_neutral_response": state.risk_debate_state.current_neutral_response,
                "judge_decision": state.risk_debate_state.judge_decision,
                "count": state.risk_debate_state.count,
            },
            "final_trade_decision": state.final_trade_decision,
        }
