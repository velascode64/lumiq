from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from agno.tools import tool


def _dump(data: Any) -> str:
    try:
        return json.dumps(data, ensure_ascii=True, default=str, indent=2)
    except Exception:
        return str(data)


def build_shared_memory_tools(
    *,
    memory_repo=None,
    coordination_repo=None,
    default_team_name: Optional[str] = None,
) -> List[Any]:
    """Attach shared knowledge + coordination tools to agents (Phase 1/2)."""
    tools: List[Any] = []

    if memory_repo is not None:
        @tool
        def remember_fact(
            category: str,
            key: str,
            value: str,
            team_name: Optional[str] = None,
            strategy_name: Optional[str] = None,
            symbol: Optional[str] = None,
            confidence: float = 1.0,
            source: str = "agent",
        ) -> str:
            """Store/update a reusable fact in shared semantic memory."""
            result = memory_repo.remember_fact(
                category=category,
                key=key,
                value=value,
                team_name=team_name or default_team_name,
                strategy_name=strategy_name,
                symbol=symbol,
                confidence=confidence,
                source=source,
            )
            return _dump(result)

        @tool
        def recall_facts(
            category: Optional[str] = None,
            team_name: Optional[str] = None,
            strategy_name: Optional[str] = None,
            symbol: Optional[str] = None,
            query: Optional[str] = None,
            limit: int = 10,
        ) -> str:
            """Recall shared facts for a team/strategy/ticker scope."""
            result = memory_repo.recall_facts(
                category=category,
                team_name=team_name or default_team_name,
                strategy_name=strategy_name,
                symbol=symbol,
                query=query,
                limit=limit,
            )
            return _dump(result)

        @tool
        def log_experiment(
            episode_type: str,
            title: str,
            summary: str,
            outcome: Optional[str] = None,
            team_name: Optional[str] = None,
            strategy_name: Optional[str] = None,
            symbol: Optional[str] = None,
            importance: float = 0.5,
            payload: Optional[Dict[str, Any]] = None,
        ) -> str:
            """Persist a backtest/optimization/research episode in shared episodic memory."""
            result = memory_repo.log_experiment(
                episode_type=episode_type,
                title=title,
                summary=summary,
                outcome=outcome,
                team_name=team_name or default_team_name,
                strategy_name=strategy_name,
                symbol=symbol,
                importance=importance,
                payload=payload or {},
                created_by="agent",
            )
            return _dump(result)

        @tool
        def save_procedure(
            procedure_name: str,
            description: str,
            steps: List[Dict[str, Any]],
            team_name: Optional[str] = None,
            strategy_name: Optional[str] = None,
            symbol: Optional[str] = None,
        ) -> str:
            """Store a reusable playbook/checklist in procedural memory."""
            result = memory_repo.save_procedure(
                procedure_name=procedure_name,
                description=description,
                steps=steps,
                team_name=team_name or default_team_name,
                strategy_name=strategy_name,
                symbol=symbol,
                created_by="agent",
            )
            return _dump(result)

        @tool
        def recall_procedures(
            procedure_name: Optional[str] = None,
            query: Optional[str] = None,
            team_name: Optional[str] = None,
            strategy_name: Optional[str] = None,
            symbol: Optional[str] = None,
            limit: int = 5,
        ) -> str:
            """Recall procedures/playbooks relevant to a scope."""
            result = memory_repo.recall_procedures(
                procedure_name=procedure_name,
                query=query,
                team_name=team_name or default_team_name,
                strategy_name=strategy_name,
                symbol=symbol,
                limit=limit,
            )
            return _dump(result)

        @tool
        def review_memory_scope(
            team_name: Optional[str] = None,
            strategy_name: Optional[str] = None,
            symbol: Optional[str] = None,
        ) -> str:
            """Summarize shared memory for a given team/strategy/symbol scope."""
            result = memory_repo.review_memory_scope(
                team_name=team_name or default_team_name,
                strategy_name=strategy_name,
                symbol=symbol,
            )
            return _dump(result)

        tools.extend([
            remember_fact,
            recall_facts,
            log_experiment,
            save_procedure,
            recall_procedures,
            review_memory_scope,
        ])

    if coordination_repo is not None:
        @tool
        def send_agent_message(
            thread_id: str,
            from_agent: str,
            message_type: str,
            payload: Dict[str, Any],
            to_agent: Optional[str] = None,
            to_team: Optional[str] = None,
            priority: str = "normal",
            subject: Optional[str] = None,
            related_symbol: Optional[str] = None,
        ) -> str:
            """Send a typed message to another agent/team via shared coordination store."""
            result = coordination_repo.send_agent_message(
                thread_id=thread_id,
                from_agent=from_agent,
                message_type=message_type,
                payload=payload,
                to_agent=to_agent,
                to_team=to_team,
                priority=priority,
                subject=subject,
                related_symbol=related_symbol,
            )
            return _dump(result)

        @tool
        def poll_agent_messages(
            to_agent: Optional[str] = None,
            to_team: Optional[str] = None,
            status: str = "pending",
            limit: int = 20,
        ) -> str:
            """Poll shared typed messages for this agent/team."""
            result = coordination_repo.poll_agent_messages(
                to_agent=to_agent,
                to_team=to_team,
                status=status,
                limit=limit,
            )
            return _dump(result)

        tools.extend([send_agent_message, poll_agent_messages])

    return tools

