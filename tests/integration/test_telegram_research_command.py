from __future__ import annotations

from contextlib import nullcontext

from lumiq.telegram_bot.http_telegram_bot import ApiTelegramBot


def test_research_command_calls_research_api(monkeypatch):
    bot = ApiTelegramBot(telegram_token="token", core_api_base_url="http://localhost:8000")
    sent_messages: list[str] = []

    monkeypatch.setattr(bot, "_typing_indicator", lambda _chat_id: nullcontext())
    monkeypatch.setattr(
        bot,
        "_stream_research",
        lambda chat_id, ticker, start_date, end_date: sent_messages.extend(
            [
                f"Market report\n\nmarket for {ticker}",
                f"Bull deliberation\n\nbull for {ticker}",
            ]
        )
        or {
            "result": {
                "company_of_interest": ticker,
                "start_date": start_date,
                "end_date": end_date,
                "final_trade_decision": "BUY",
                "investment_plan": "Plan",
                "trader_investment_plan": "Trader plan",
            }
        },
    )
    monkeypatch.setattr(bot, "_forward_to_core", lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not call core chat")))
    monkeypatch.setattr(bot, "_send_message", lambda chat_id, text, parse_mode=None: sent_messages.append(text))

    bot._handle_update(
        {
            "message": {
                "text": "/research NVDA 2026-03-01 2026-03-23",
                "chat": {"id": 1},
                "from": {"id": 2},
            }
        }
    )

    assert len(sent_messages) == 3
    assert "Market report" in sent_messages[0]
    assert "Bull deliberation" in sent_messages[1]
    assert "Research complete: NVDA" in sent_messages[2]
    assert "Decision: BUY" in sent_messages[2]


def test_research_command_returns_usage_when_arguments_are_missing(monkeypatch):
    bot = ApiTelegramBot(telegram_token="token", core_api_base_url="http://localhost:8000")
    sent_messages: list[str] = []

    monkeypatch.setattr(bot, "_send_message", lambda chat_id, text, parse_mode=None: sent_messages.append(text))
    monkeypatch.setattr(bot, "_forward_to_core", lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not call core chat")))

    bot._handle_update(
        {
            "message": {
                "text": "/research NVDA",
                "chat": {"id": 1},
                "from": {"id": 2},
            }
        }
    )

    assert sent_messages == [bot._research_usage()]
