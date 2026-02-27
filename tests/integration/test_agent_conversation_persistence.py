from __future__ import annotations

import pytest

from lumiq.platform.db.core import agent_messages, memory_episodic, memory_procedural, memory_semantic, sa
from lumiq.platform.db.repositories import DbCoordinationRepository, DbMemoryRepository


@pytest.mark.integration
def test_agents_exchange_messages_and_persist_memory(db_manager):
    coordination = DbCoordinationRepository(db_manager)
    memory = DbMemoryRepository(db_manager)

    thread_id = "research-eth-001"

    first_msg = coordination.send_agent_message(
        thread_id=thread_id,
        from_agent="TechnicalAnalyst",
        to_agent="NewsAnalyst",
        message_type="signal_review_request",
        payload={"symbol": "ETH/USD", "question": "confirm catalyst relevance"},
        priority="high",
        subject="ETH signal check",
        related_symbol="ETH/USD",
    )
    assert first_msg["status"] == "pending"

    second_msg = coordination.send_agent_message(
        thread_id=thread_id,
        from_agent="NewsAnalyst",
        to_agent="TechnicalAnalyst",
        message_type="signal_review_response",
        payload={"symbol": "ETH/USD", "impact": "medium", "catalyst": "ETF flow headline"},
        priority="normal",
        subject="ETH catalyst summary",
        related_symbol="ETH/USD",
    )
    assert second_msg["status"] == "pending"

    news_queue = coordination.poll_agent_messages(to_agent="NewsAnalyst", status="pending", limit=10)
    assert len(news_queue) == 1
    assert news_queue[0]["from_agent"] == "TechnicalAnalyst"

    technical_queue = coordination.poll_agent_messages(to_agent="TechnicalAnalyst", status="pending", limit=10)
    assert len(technical_queue) == 1
    assert technical_queue[0]["from_agent"] == "NewsAnalyst"

    coordination.mark_agent_message_processed(news_queue[0]["id"])
    recheck_news_queue = coordination.poll_agent_messages(to_agent="NewsAnalyst", status="pending", limit=10)
    assert recheck_news_queue == []

    with db_manager.connect() as conn:
        rows = conn.execute(
            sa.select(agent_messages).where(agent_messages.c.thread_id == thread_id).order_by(agent_messages.c.created_at.asc())
        ).mappings().all()
    assert len(rows) == 2

    remember = memory.remember_fact(
        category="regime",
        key="eth_bull_regime_bias",
        value="momentum setups work better when weekly trend is positive",
        source="TechnicalAnalyst",
        team_name="TradingAlertTeam",
        strategy_name="ETHAggressiveMomentumYTDStrategy",
        symbol="ETH/USD",
        confidence=0.84,
    )
    assert remember["id"]

    facts = memory.recall_facts(
        category="regime",
        team_name="TradingAlertTeam",
        strategy_name="ETHAggressiveMomentumYTDStrategy",
        symbol="ETH/USD",
        query="momentum",
        limit=10,
    )
    assert len(facts) == 1
    assert facts[0]["fact_key"] == "eth_bull_regime_bias"

    episode = memory.log_experiment(
        episode_type="backtest",
        title="ETH momentum weekly review",
        summary="2024-2026 looks strong in bullish regime and weak in 2023-style chop.",
        outcome="mixed",
        team_name="LumibotLabTeam",
        strategy_name="ETHAggressiveMomentumYTDStrategy",
        symbol="ETH/USD",
        importance=0.9,
        payload={"cagr": 54.7, "max_dd": 11.4},
        created_by="EvaluatorAgent",
    )
    assert episode["id"]

    procedure = memory.save_procedure(
        procedure_name="eth_regime_gate_check",
        description="Check trend regime before enabling aggressive momentum strategy.",
        steps=[
            {"step": 1, "action": "Read weekly trend"},
            {"step": 2, "action": "Confirm RSI and volume context"},
            {"step": 3, "action": "Enable strategy only in favorable regime"},
        ],
        team_name="LumibotLabTeam",
        strategy_name="ETHAggressiveMomentumYTDStrategy",
        symbol="ETH/USD",
        created_by="StrategyOpsAgent",
    )
    assert procedure["version"] == 1

    scope_summary = memory.review_memory_scope(
        team_name="LumibotLabTeam",
        strategy_name="ETHAggressiveMomentumYTDStrategy",
        symbol="ETH/USD",
    )
    assert len(scope_summary["episodes"]) >= 1
    assert len(scope_summary["procedures"]) >= 1

    with db_manager.connect() as conn:
        semantic_count = conn.execute(sa.select(sa.func.count()).select_from(memory_semantic)).scalar_one()
        episodic_count = conn.execute(sa.select(sa.func.count()).select_from(memory_episodic)).scalar_one()
        procedural_count = conn.execute(sa.select(sa.func.count()).select_from(memory_procedural)).scalar_one()
    assert int(semantic_count) >= 1
    assert int(episodic_count) >= 1
    assert int(procedural_count) >= 1

