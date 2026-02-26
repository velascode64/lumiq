"""
Data models for the intelligent alert system.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List
import pandas as pd


class TrendDirection(Enum):
    """Direction of price trend."""
    UP = "up"
    DOWN = "down"
    SIDEWAYS = "sideways"


class DipClassification(Enum):
    """Classification of price dip."""
    PANIC_SELL = "panic_sell"      # Sharp drop, high volume, often oversold
    CORRECTION = "correction"       # Normal pullback in uptrend
    FUNDAMENTAL = "fundamental"     # Drop due to company/sector issues
    NOISE = "noise"                 # Small fluctuation, ignore


class Priority(Enum):
    """Alert priority classification."""
    HOT = "hot"         # Score > 70, strong buy signal
    WATCH = "watch"     # Score 40-70, monitor closely
    IGNORE = "ignore"   # Score < 40, skip


@dataclass
class StockData:
    """Raw stock data from Alpaca."""
    symbol: str
    current_price: float
    previous_close: float
    high_52w: float
    low_52w: float
    volume: float
    avg_volume: float
    bars: Optional[pd.DataFrame] = None
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def daily_change_pct(self) -> float:
        """Calculate daily percentage change."""
        if self.previous_close == 0:
            return 0.0
        return ((self.current_price - self.previous_close) / self.previous_close) * 100

    @property
    def from_52w_high_pct(self) -> float:
        """Percentage below 52-week high."""
        if self.high_52w == 0:
            return 0.0
        return ((self.current_price - self.high_52w) / self.high_52w) * 100

    @property
    def volume_ratio(self) -> float:
        """Current volume vs average volume ratio."""
        if self.avg_volume == 0:
            return 1.0
        return self.volume / self.avg_volume


@dataclass
class TechnicalIndicators:
    """Technical analysis indicators."""
    symbol: str
    rsi: float                          # Relative Strength Index (0-100)
    atr: float                          # Average True Range
    chandelier_exit: float              # Chandelier Exit price
    sma_20: Optional[float] = None      # 20-day SMA
    sma_50: Optional[float] = None      # 50-day SMA
    sma_200: Optional[float] = None     # 200-day SMA

    @property
    def is_oversold(self) -> bool:
        """RSI below 30 indicates oversold."""
        return self.rsi < 30

    @property
    def is_overbought(self) -> bool:
        """RSI above 70 indicates overbought."""
        return self.rsi > 70

    @property
    def is_neutral(self) -> bool:
        """RSI between 30 and 70."""
        return 30 <= self.rsi <= 70


@dataclass
class TrendAnalysis:
    """Multi-period trend analysis."""
    symbol: str
    change_30d: float           # % change over 30 days
    change_60d: float           # % change over 60 days
    change_90d: float           # % change over 90 days
    direction: TrendDirection
    momentum_score: float       # -100 to +100
    is_consistent: bool         # All periods same direction?

    @property
    def is_uptrend(self) -> bool:
        """Check if in uptrend."""
        return self.direction == TrendDirection.UP

    @property
    def is_downtrend(self) -> bool:
        """Check if in downtrend."""
        return self.direction == TrendDirection.DOWN

    @property
    def avg_monthly_change(self) -> float:
        """Average monthly change percentage."""
        return (self.change_30d + (self.change_60d / 2) + (self.change_90d / 3)) / 3


@dataclass
class DipInfo:
    """Information about a price dip."""
    symbol: str
    dip_percentage: float           # % below recent high
    from_high_price: float          # The high price reference
    current_price: float
    volume_spike: bool              # Unusual volume?
    classification: DipClassification
    days_since_high: int = 0

    @property
    def is_significant(self) -> bool:
        """Dip > 10% is significant."""
        return self.dip_percentage >= 10.0

    @property
    def is_buying_opportunity(self) -> bool:
        """Check if dip represents buying opportunity."""
        return (
            self.is_significant and
            self.classification in [DipClassification.PANIC_SELL, DipClassification.CORRECTION]
        )


@dataclass
class Opportunity:
    """A scored trading opportunity."""
    symbol: str
    score: float                    # 0-100
    priority: Priority
    reasons: List[str]
    stock_data: StockData
    technical: TechnicalIndicators
    trend: TrendAnalysis
    dip: Optional[DipInfo] = None
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def is_hot(self) -> bool:
        """Check if this is a HOT opportunity."""
        return self.priority == Priority.HOT

    @property
    def summary(self) -> str:
        """Generate a brief summary."""
        emoji = {"hot": "🔥", "watch": "👀", "ignore": "⚪"}.get(self.priority.value, "")
        return f"{emoji} {self.symbol}: {self.score:.0f}/100 - {', '.join(self.reasons[:2])}"


@dataclass
class AlertSummary:
    """Summary of alerts for notification."""
    timestamp: datetime
    session: str                    # "apertura", "medio_dia", "cierre"
    total_analyzed: int
    hot_opportunities: List[Opportunity]
    watch_opportunities: List[Opportunity]
    market_sentiment: str           # "bullish", "bearish", "neutral"

    @property
    def has_opportunities(self) -> bool:
        """Check if there are any opportunities."""
        return len(self.hot_opportunities) > 0 or len(self.watch_opportunities) > 0

    def to_telegram_message(self) -> str:
        """Format as Telegram message."""
        lines = [
            f"📊 *Alert Report - {self.session.upper()}*",
            f"📅 {self.timestamp.strftime('%Y-%m-%d %H:%M')} ET",
            f"📈 Market: {self.market_sentiment}",
            f"🔍 Analyzed: {self.total_analyzed} stocks",
            "",
        ]

        if self.hot_opportunities:
            lines.append("🔥 *HOT OPPORTUNITIES:*")
            for opp in self.hot_opportunities[:5]:
                lines.append(f"  • {opp.summary}")
            lines.append("")

        if self.watch_opportunities:
            lines.append("👀 *WATCH LIST:*")
            for opp in self.watch_opportunities[:5]:
                lines.append(f"  • {opp.summary}")
            lines.append("")

        if not self.has_opportunities:
            lines.append("_No significant opportunities detected._")

        return "\n".join(lines)
