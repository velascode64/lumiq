"""
Alert factory for predefined technical alerts.
"""

from __future__ import annotations

from typing import Dict


def _base_rule(symbol: str, rule_type: str) -> Dict:
    return {
        "symbol": symbol.upper(),
        "type": rule_type,
        "active": True,
    }


def create_rsi_oversold(symbol: str, period: int = 14, threshold: float = 30.0) -> Dict:
    rule = _base_rule(symbol, "rsi_oversold")
    rule["period"] = int(period)
    rule["threshold"] = float(threshold)
    return rule


def create_rsi_overbought(symbol: str, period: int = 14, threshold: float = 70.0) -> Dict:
    rule = _base_rule(symbol, "rsi_overbought")
    rule["period"] = int(period)
    rule["threshold"] = float(threshold)
    return rule


def create_macd_bullish_cross(
    symbol: str,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Dict:
    rule = _base_rule(symbol, "macd_bullish_cross")
    rule["fast"] = int(fast)
    rule["slow"] = int(slow)
    rule["signal"] = int(signal)
    return rule


def create_bollinger_middle_cross(
    symbol: str,
    period: int = 20,
    stddev: float = 2.0,
    direction: str = "above",
) -> Dict:
    rule = _base_rule(symbol, "bollinger_middle_cross")
    rule["period"] = int(period)
    rule["stddev"] = float(stddev)
    rule["direction"] = direction
    return rule


PRESETS = {
    "rsi_oversold": create_rsi_oversold,
    "rsi_overbought": create_rsi_overbought,
    "macd_bullish_cross": create_macd_bullish_cross,
    "bollinger_middle_cross": create_bollinger_middle_cross,
}


def create_preset(name: str, symbol: str, **kwargs) -> Dict:
    preset = PRESETS.get(name)
    if preset is None:
        raise ValueError(f"Unknown preset: {name}")
    return preset(symbol, **kwargs)
