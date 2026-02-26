"""
Agno Technical Analysis Agent.

Provides reliable technical/contextual analysis tools using real OHLCV data from
Alpaca and indicator calculations from the existing TechnicalAnalyzer.
"""

from __future__ import annotations

import inspect
import json
import logging
import os
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd
from agno.agent import Agent
from agno.tools import tool
from alpaca.data.timeframe import TimeFrame

logger = logging.getLogger(__name__)


def _json_dump(data: Any) -> str:
    try:
        return json.dumps(data, ensure_ascii=True, default=str, indent=2)
    except Exception:
        return str(data)


def _resolve_model():
    provider = os.getenv("AGNO_PROVIDER", "").strip().lower()
    model_id = os.getenv("AGNO_MODEL", "").strip()

    if provider == "anthropic":
        from agno.models.anthropic import Claude

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("AGNO_PROVIDER=anthropic set but ANTHROPIC_API_KEY is missing")
        return Claude(id=model_id or "claude-3-5-sonnet-20241022", api_key=api_key)

    if provider == "openai":
        from agno.models.openai import OpenAIChat

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("AGNO_PROVIDER=openai set but OPENAI_API_KEY is missing")
        return OpenAIChat(id=model_id or "gpt-4o-mini", api_key=api_key)

    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if anthropic_key:
        from agno.models.anthropic import Claude

        return Claude(id=model_id or "claude-3-5-sonnet-20241022", api_key=anthropic_key)

    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        from agno.models.openai import OpenAIChat

        return OpenAIChat(id=model_id or "gpt-4o-mini", api_key=openai_key)

    return None


def _normalize_symbol(symbol: str) -> str:
    return (symbol or "").strip().upper().replace("-", "/")


def _timeframe_from_text(text: str) -> TimeFrame:
    normalized = (text or "1D").strip().upper()
    mapping = {
        "D": TimeFrame.Day,
        "1D": TimeFrame.Day,
        "DAY": TimeFrame.Day,
        "DAILY": TimeFrame.Day,
        "H": TimeFrame.Hour,
        "1H": TimeFrame.Hour,
        "HOUR": TimeFrame.Hour,
        "HOURLY": TimeFrame.Hour,
    }
    return mapping.get(normalized, TimeFrame.Day)


def _prepare_bars(alert_system, symbol: str, days: int, timeframe: str) -> tuple[str, Optional[pd.DataFrame], Optional[str]]:
    sym = _normalize_symbol(symbol)
    tf = _timeframe_from_text(timeframe)
    bars = alert_system.data_service.get_stock_bars(sym, days=max(5, int(days)), timeframe=tf)
    if bars is None or bars.empty:
        return sym, None, "no_bars"
    df = bars.copy().sort_index()
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=[c for c in ("open", "high", "low", "close") if c in df.columns])
    if df.empty:
        return sym, None, "invalid_bars"
    return sym, df, None


def _timestamp_at(df: pd.DataFrame, idx: int) -> str:
    ts = df.index[idx]
    try:
        return ts.isoformat()
    except Exception:
        return str(ts)


def _episode_starts(mask: pd.Series) -> List[int]:
    indices: List[int] = []
    prev = False
    for i, value in enumerate(mask.fillna(False).astype(bool).tolist()):
        if value and not prev:
            indices.append(i)
        prev = value
    return indices


def _rsi_series(prices: pd.Series, period: int = 14) -> pd.Series:
    delta = prices.diff()
    gains = delta.where(delta > 0, 0.0)
    losses = (-delta).where(delta < 0, 0.0)
    avg_gain = gains.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    both_zero = avg_loss.eq(0) & avg_gain.eq(0)
    only_loss_zero = avg_loss.eq(0) & ~both_zero
    only_gain_zero = avg_gain.eq(0) & ~both_zero
    rsi = rsi.mask(only_loss_zero, 100.0)
    rsi = rsi.mask(only_gain_zero, 0.0)
    rsi = rsi.mask(both_zero, 50.0)
    return rsi.clip(lower=0, upper=100)


def _event_return_summary(values: List[float]) -> Dict[str, Any]:
    if not values:
        return {"count": 0}
    arr = np.array(values, dtype=float)
    return {
        "count": int(arr.size),
        "avg_return_pct": float(arr.mean()),
        "median_return_pct": float(np.median(arr)),
        "positive_rate": float((arr > 0).mean()),
        "min_return_pct": float(arr.min()),
        "max_return_pct": float(arr.max()),
    }


def build_technical_tools(alert_system) -> List[Any]:
    tech = alert_system.technical_analyzer

    @tool
    def get_technical_snapshot(
        symbol: str,
        timeframe: str = "1D",
        lookback_days: int = 365,
        rsi_period: int = 14,
    ) -> str:
        """
        Get a deterministic technical snapshot (RSI, MACD, Bollinger, SMAs, volume ratio).

        Use this for questions like "esta sobrecomprado?", "como va el momentum?",
        or "que dice el tecnico ahora?".
        """
        try:
            sym, df, error = _prepare_bars(alert_system, symbol, lookback_days, timeframe)
            if error or df is None:
                return _json_dump({"symbol": sym, "error": error or "no_data"})

            closes = df["close"]
            latest_close = float(closes.iloc[-1])
            latest_high = float(df["high"].iloc[-1])
            latest_low = float(df["low"].iloc[-1])
            latest_volume = float(df["volume"].iloc[-1]) if "volume" in df.columns else None

            rsi = float(tech.calculate_rsi(closes, period=int(rsi_period)))
            macd_series, signal_series = tech.calculate_macd(closes)
            macd_value = float(macd_series.iloc[-1]) if macd_series is not None else None
            macd_signal = float(signal_series.iloc[-1]) if signal_series is not None else None
            macd_hist = (macd_value - macd_signal) if (macd_value is not None and macd_signal is not None) else None
            bb_lower, bb_mid, bb_upper = tech.calculate_bollinger_bands(closes)

            sma20 = tech.calculate_sma(closes, 20)
            sma50 = tech.calculate_sma(closes, 50)
            sma200 = tech.calculate_sma(closes, 200)
            volume_ratio = None
            if "volume" in df.columns and len(df) >= 20:
                vol_ma20 = float(df["volume"].iloc[-20:].mean())
                if vol_ma20 > 0:
                    volume_ratio = float(df["volume"].iloc[-1] / vol_ma20)

            def _dist_pct(level: Optional[float]) -> Optional[float]:
                if level in (None, 0):
                    return None
                return float(((latest_close - float(level)) / float(level)) * 100.0)

            trend_bias = "lateral"
            if sma20 and sma50 and latest_close > sma20 > sma50:
                trend_bias = "alcista"
            elif sma20 and sma50 and latest_close < sma20 < sma50:
                trend_bias = "bajista"

            rsi_state = "neutral"
            if rsi >= 70:
                rsi_state = "sobrecomprado"
            elif rsi <= 30:
                rsi_state = "sobrevendido"

            payload = {
                "symbol": sym,
                "timeframe": timeframe,
                "bars_analyzed": int(len(df)),
                "as_of": _timestamp_at(df, len(df) - 1),
                "price": {
                    "close": latest_close,
                    "high": latest_high,
                    "low": latest_low,
                },
                "rsi": {"value": rsi, "period": int(rsi_period), "state": rsi_state},
                "macd": {
                    "macd": macd_value,
                    "signal": macd_signal,
                    "histogram": macd_hist,
                    "bias": "alcista" if (macd_hist is not None and macd_hist > 0) else "bajista" if (macd_hist is not None and macd_hist < 0) else "neutral",
                },
                "bollinger": {
                    "lower": bb_lower,
                    "middle": bb_mid,
                    "upper": bb_upper,
                    "position": (
                        "above_upper" if bb_upper is not None and latest_close > bb_upper else
                        "below_lower" if bb_lower is not None and latest_close < bb_lower else
                        "upper_half" if bb_mid is not None and latest_close > bb_mid else
                        "lower_half" if bb_mid is not None and latest_close < bb_mid else
                        "middle"
                    ),
                },
                "moving_averages": {
                    "sma20": sma20,
                    "sma50": sma50,
                    "sma200": sma200,
                    "dist_vs_sma20_pct": _dist_pct(sma20),
                    "dist_vs_sma50_pct": _dist_pct(sma50),
                    "dist_vs_sma200_pct": _dist_pct(sma200),
                },
                "volume": {
                    "latest": latest_volume,
                    "relative_to_ma20": volume_ratio,
                },
                "trend_bias": trend_bias,
                "range": {
                    "lookback_high": float(df["high"].max()),
                    "lookback_low": float(df["low"].min()),
                },
            }
            return _json_dump(payload)
        except Exception as exc:
            logger.exception("get_technical_snapshot failed")
            return f"Error getting technical snapshot: {exc}"

    @tool
    def count_price_touches(
        symbol: str,
        target_price: float,
        timeframe: str = "1D",
        lookback_days: int = 365,
        tolerance_pct: float = 0.5,
        price_field: str = "close",
    ) -> str:
        """
        Count how many times price touched a level in a period.

        `touch_episodes` collapses consecutive bars into one touch event.
        """
        try:
            sym, df, error = _prepare_bars(alert_system, symbol, lookback_days, timeframe)
            if error or df is None:
                return _json_dump({"symbol": sym, "error": error or "no_data"})
            field = (price_field or "close").lower()
            if field not in {"open", "high", "low", "close"}:
                field = "close"
            series = df[field].astype(float)
            target = float(target_price)
            tol_pct = abs(float(tolerance_pct))
            if target == 0:
                return _json_dump({"symbol": sym, "error": "target_price_cannot_be_zero"})

            distance_pct = ((series - target).abs() / abs(target)) * 100.0
            touches = distance_pct <= tol_pct
            starts = _episode_starts(touches)
            touch_bars = int(touches.sum())

            episode_payload = []
            for idx in starts[:20]:
                episode_payload.append(
                    {
                        "timestamp": _timestamp_at(df, idx),
                        "price": float(series.iloc[idx]),
                        "distance_pct": float(distance_pct.iloc[idx]),
                    }
                )

            result = {
                "symbol": sym,
                "timeframe": timeframe,
                "target_price": target,
                "price_field": field,
                "lookback_days": int(lookback_days),
                "tolerance_pct": tol_pct,
                "bars_analyzed": int(len(df)),
                "touch_bars": touch_bars,
                "touch_episodes": int(len(starts)),
                "first_touch": _timestamp_at(df, starts[0]) if starts else None,
                "last_touch": _timestamp_at(df, starts[-1]) if starts else None,
                "sample_touch_events": episode_payload,
            }
            return _json_dump(result)
        except Exception as exc:
            logger.exception("count_price_touches failed")
            return f"Error counting touches: {exc}"

    @tool
    def analyze_price_level_reactions(
        symbol: str,
        target_price: float,
        timeframe: str = "1D",
        lookback_days: int = 365,
        tolerance_pct: float = 0.5,
        forward_bars: int = 5,
        move_threshold_pct: float = 2.0,
    ) -> str:
        """
        Analyze what happened after price touched a level (bounce vs breakdown).

        This is useful for "soporte/resistencia" style questions with historical evidence.
        """
        try:
            sym, df, error = _prepare_bars(alert_system, symbol, lookback_days, timeframe)
            if error or df is None:
                return _json_dump({"symbol": sym, "error": error or "no_data"})

            target = float(target_price)
            tol_pct = abs(float(tolerance_pct))
            fwd = max(1, int(forward_bars))
            move_thr = abs(float(move_threshold_pct))

            low_bound = target * (1 - tol_pct / 100.0)
            high_bound = target * (1 + tol_pct / 100.0)
            touch_mask = (df["low"] <= high_bound) & (df["high"] >= low_bound)
            starts = _episode_starts(touch_mask)

            bounce_hits = 0
            breakdown_hits = 0
            both_hits = 0
            neither_hits = 0
            samples: List[Dict[str, Any]] = []

            up_level = target * (1 + move_thr / 100.0)
            down_level = target * (1 - move_thr / 100.0)

            for idx in starts:
                end = min(len(df), idx + fwd + 1)
                window = df.iloc[idx + 1 : end]
                if window.empty:
                    continue
                max_high = float(window["high"].max())
                min_low = float(window["low"].min())
                final_close = float(window["close"].iloc[-1])
                bounced = max_high >= up_level
                broke_down = min_low <= down_level

                if bounced and broke_down:
                    both_hits += 1
                    label = "both"
                elif bounced:
                    bounce_hits += 1
                    label = "bounce"
                elif broke_down:
                    breakdown_hits += 1
                    label = "breakdown"
                else:
                    neither_hits += 1
                    label = "neutral"

                if len(samples) < 15:
                    samples.append(
                        {
                            "touch_at": _timestamp_at(df, idx),
                            "outcome": label,
                            "max_high_forward": max_high,
                            "min_low_forward": min_low,
                            "close_after_forward_bars": final_close,
                            "forward_return_pct": float(((final_close - target) / target) * 100.0) if target else None,
                        }
                    )

            total_eval = bounce_hits + breakdown_hits + both_hits + neither_hits
            payload = {
                "symbol": sym,
                "timeframe": timeframe,
                "target_price": target,
                "lookback_days": int(lookback_days),
                "tolerance_pct": tol_pct,
                "forward_bars": fwd,
                "move_threshold_pct": move_thr,
                "touch_episodes_detected": int(len(starts)),
                "touch_events_evaluated": int(total_eval),
                "outcomes": {
                    "bounce": bounce_hits,
                    "breakdown": breakdown_hits,
                    "both": both_hits,
                    "neutral": neither_hits,
                },
                "sample_events": samples,
                "note": "Con OHLC no se puede inferir el orden intrabar exacto; 'both' significa que ambas condiciones ocurrieron dentro de la ventana.",
            }
            return _json_dump(payload)
        except Exception as exc:
            logger.exception("analyze_price_level_reactions failed")
            return f"Error analyzing level reactions: {exc}"

    @tool
    def count_large_moves(
        symbol: str,
        direction: str = "down",
        move_percent: float = 3.0,
        timeframe: str = "1D",
        lookback_days: int = 365,
    ) -> str:
        """
        Count large bar-to-bar moves (e.g., daily drops > 3%).
        """
        try:
            sym, df, error = _prepare_bars(alert_system, symbol, lookback_days, timeframe)
            if error or df is None:
                return _json_dump({"symbol": sym, "error": error or "no_data"})

            returns = df["close"].pct_change() * 100.0
            threshold = abs(float(move_percent))
            direction_norm = (direction or "down").strip().lower()
            if direction_norm in {"up", "rise", "rally", "subida"}:
                mask = returns >= threshold
                direction_norm = "up"
            else:
                mask = returns <= -threshold
                direction_norm = "down"

            idxs = [i for i, v in enumerate(mask.fillna(False).tolist()) if v]
            events = []
            for i in idxs[:25]:
                events.append(
                    {
                        "timestamp": _timestamp_at(df, i),
                        "close": float(df["close"].iloc[i]),
                        "return_pct": float(returns.iloc[i]),
                    }
                )

            payload = {
                "symbol": sym,
                "timeframe": timeframe,
                "lookback_days": int(lookback_days),
                "direction": direction_norm,
                "move_percent_threshold": threshold,
                "bars_analyzed": int(len(df)),
                "events_count": int(mask.sum()),
                "largest_up_pct": float(returns.max()) if len(returns.dropna()) else None,
                "largest_down_pct": float(returns.min()) if len(returns.dropna()) else None,
                "sample_events": events,
            }
            return _json_dump(payload)
        except Exception as exc:
            logger.exception("count_large_moves failed")
            return f"Error counting large moves: {exc}"

    @tool
    def analyze_rsi_threshold_events(
        symbol: str,
        threshold: float = 70.0,
        direction: str = "above",
        timeframe: str = "1D",
        lookback_days: int = 365,
        rsi_period: int = 14,
        cross_only: bool = True,
        forward_bars_list: Optional[Sequence[int]] = None,
    ) -> str:
        """
        Analyze historical RSI threshold events and what happened after.

        Examples:
        - RSI > 70 (overbought)
        - RSI < 30 (oversold)
        """
        try:
            sym, df, error = _prepare_bars(alert_system, symbol, lookback_days, timeframe)
            if error or df is None:
                return _json_dump({"symbol": sym, "error": error or "no_data"})

            closes = df["close"].astype(float)
            rsi = _rsi_series(closes, period=max(2, int(rsi_period)))
            thr = float(threshold)
            direction_norm = (direction or "above").strip().lower()
            if direction_norm in {"below", "under", "down", "menor"}:
                raw_mask = rsi < thr
                cross_mask = (rsi < thr) & (rsi.shift(1) >= thr)
                direction_norm = "below"
            else:
                raw_mask = rsi > thr
                cross_mask = (rsi > thr) & (rsi.shift(1) <= thr)
                direction_norm = "above"

            event_mask = cross_mask if bool(cross_only) else raw_mask
            event_idxs = [i for i, v in enumerate(event_mask.fillna(False).tolist()) if v]
            horizons = [1, 3, 7]
            if forward_bars_list:
                parsed = []
                for item in forward_bars_list:
                    try:
                        parsed.append(max(1, int(item)))
                    except Exception:
                        continue
                if parsed:
                    horizons = sorted(set(parsed))

            returns_by_horizon: Dict[str, List[float]] = {str(h): [] for h in horizons}
            samples: List[Dict[str, Any]] = []
            for idx in event_idxs:
                if idx >= len(df):
                    continue
                close0 = float(closes.iloc[idx])
                if close0 == 0:
                    continue
                sample = {
                    "timestamp": _timestamp_at(df, idx),
                    "close": close0,
                    "rsi": float(rsi.iloc[idx]) if pd.notna(rsi.iloc[idx]) else None,
                    "forward_returns_pct": {},
                }
                for h in horizons:
                    if idx + h >= len(df):
                        continue
                    ret = float(((float(closes.iloc[idx + h]) - close0) / close0) * 100.0)
                    returns_by_horizon[str(h)].append(ret)
                    sample["forward_returns_pct"][str(h)] = ret
                if len(samples) < 20:
                    samples.append(sample)

            summary = {k: _event_return_summary(v) for k, v in returns_by_horizon.items()}

            payload = {
                "symbol": sym,
                "timeframe": timeframe,
                "lookback_days": int(lookback_days),
                "rsi_period": int(rsi_period),
                "threshold": thr,
                "direction": direction_norm,
                "cross_only": bool(cross_only),
                "bars_analyzed": int(len(df)),
                "events_count": int(len(event_idxs)),
                "latest_rsi": float(rsi.iloc[-1]) if len(rsi) else None,
                "forward_return_stats_pct": summary,
                "sample_events": samples,
            }
            return _json_dump(payload)
        except Exception as exc:
            logger.exception("analyze_rsi_threshold_events failed")
            return f"Error analyzing RSI threshold events: {exc}"

    return [
        get_technical_snapshot,
        count_price_touches,
        analyze_price_level_reactions,
        count_large_moves,
        analyze_rsi_threshold_events,
    ]


def create_technical_agent(alert_system) -> Optional[Agent]:
    """
    Create a technical-analysis-only agent that explains indicators with evidence.
    """
    if alert_system is None:
        return None

    model = _resolve_model()
    if model is None:
        logger.warning("No LLM API key configured - technical agent disabled")
        return None

    instructions = [
        "You are an educational and rigorous technical analyst for stocks and crypto.",
        "Your role DOES include technical recommendations, but NOT absolute financial advice.",
        "Do not simply say 'buy/sell'. Instead, provide a conditional, evidence-based technical recommendation.",
        "For RSI, MACD, Bollinger, price touches, historical drops, or bounces, ALWAYS use tools and never invent values.",
        "If the question is open-ended (e.g., 'what do you see', 'is there a bounce', 'how does it look technically'), use get_technical_snapshot first.",
        "If the user asks how many times price touched a level, use count_price_touches.",
        "If the user asks whether a level acted as support/resistance, bounce, or breakdown, use analyze_price_level_reactions.",
        "If the user asks about large drops/rallies, use count_large_moves.",
        "If the user asks about historical RSI behavior (e.g., RSI>70 and what happened next), use analyze_rsi_threshold_events.",
        "If the user does not specify a timeframe, use 1D by default and state that explicitly.",
        "If the user does not specify a period, use 365 days by default and state that explicitly.",
        "When discussing a 'price touch', explain the assumed `tolerance_pct`.",
        "When discussing support/resistance, describe historical evidence (touches, bounces, breakdowns) and limitations.",
        "If signals are mixed or evidence quality is low, recommend waiting for confirmation and say exactly what confirmation is missing.",
        "Your response must ALWAYS include these plain-text sections: Diagnosis, Technical Recommendation, Evidence For, Evidence Against, Key Levels, Confidence, Limitations.",
        "In 'Technical Recommendation', use actions such as: wait, observe, wait for confirmed breakout, wait for retest, avoid chasing price, consider an alert; avoid giving final trade orders.",
        "In 'Key Levels', include support/resistance if they can be inferred; otherwise state that explicitly.",
        "In 'Confidence', use low/medium/high and explain why in one sentence.",
        "Respond in the same language as the user's latest message (Spanish or English), with a teacher-like tone and simple, concrete language.",
        "If the user asks for a quick conclusion, still include a technical recommendation plus 2-3 key numeric facts.",
    ]

    desired_kwargs = {
        "name": "TechnicalAnalyst",
        "model": model,
        "tools": build_technical_tools(alert_system),
        "role": "Market technical analyst that explains indicators and provides conditional technical recommendations",
        "goal": "Deliver reliable, explainable, actionable technical diagnoses without inventing data or giving absolute financial advice",
        "success_criteria": "Use tools to support each technical recommendation with numerical evidence, key levels, confidence, and limitations",
        "instructions": instructions,
        "show_tool_calls": False,
        "add_history_to_messages": True,
        "num_history_runs": 6,
        "markdown": False,
    }
    accepted = set(inspect.signature(Agent.__init__).parameters.keys())
    filtered_kwargs = {key: value for key, value in desired_kwargs.items() if key in accepted}
    agent = Agent(**filtered_kwargs)
    setattr(agent, "_alert_system", alert_system)
    return agent
