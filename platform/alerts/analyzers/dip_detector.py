"""
Dip Detector for identifying buying opportunities.

Detects significant price drops and classifies them as potential buying opportunities.
"""

import logging
from typing import Optional

import pandas as pd

from ..models.schemas import (
    DipInfo,
    DipClassification,
    StockData,
    TechnicalIndicators,
    TrendAnalysis,
)

logger = logging.getLogger(__name__)


class DipDetector:
    """Detects and classifies price dips."""

    def __init__(
        self,
        dip_threshold: float = 10.0,
        severe_dip_threshold: float = 20.0,
        volume_spike_ratio: float = 2.0,
        lookback_days: int = 60,
    ):
        """
        Initialize the dip detector.

        Args:
            dip_threshold: Minimum % drop to consider a dip
            severe_dip_threshold: % drop considered severe
            volume_spike_ratio: Volume ratio to consider a spike
            lookback_days: Days to look back for high
        """
        self.dip_threshold = dip_threshold
        self.severe_dip_threshold = severe_dip_threshold
        self.volume_spike_ratio = volume_spike_ratio
        self.lookback_days = lookback_days

    def detect(
        self,
        stock_data: StockData,
        technical: Optional[TechnicalIndicators] = None,
        trend: Optional[TrendAnalysis] = None,
    ) -> Optional[DipInfo]:
        """
        Detect and classify a dip.

        Args:
            stock_data: Stock data with historical prices
            technical: Technical indicators (for RSI context)
            trend: Trend analysis (for context)

        Returns:
            DipInfo or None if no significant dip
        """
        if stock_data.bars is None or len(stock_data.bars) < 5:
            return None

        try:
            # Calculate dip metrics
            dip_pct, high_price, days_since = self._calculate_dip(stock_data)

            if dip_pct < self.dip_threshold:
                # Not a significant dip
                return DipInfo(
                    symbol=stock_data.symbol,
                    dip_percentage=dip_pct,
                    from_high_price=high_price,
                    current_price=stock_data.current_price,
                    volume_spike=False,
                    classification=DipClassification.NOISE,
                    days_since_high=days_since,
                )

            # Check for volume spike
            volume_spike = self._detect_volume_spike(stock_data)

            # Classify the dip
            classification = self._classify_dip(
                dip_pct=dip_pct,
                volume_spike=volume_spike,
                technical=technical,
                trend=trend,
            )

            return DipInfo(
                symbol=stock_data.symbol,
                dip_percentage=dip_pct,
                from_high_price=high_price,
                current_price=stock_data.current_price,
                volume_spike=volume_spike,
                classification=classification,
                days_since_high=days_since,
            )

        except Exception as e:
            logger.error(f"Dip detection failed for {stock_data.symbol}: {e}")
            return None

    def _calculate_dip(self, stock_data: StockData) -> tuple:
        """
        Calculate dip percentage from recent high.

        Returns:
            (dip_percentage, high_price, days_since_high)
        """
        bars = stock_data.bars
        lookback = min(self.lookback_days, len(bars))

        recent_bars = bars.iloc[-lookback:]
        high_price = float(recent_bars["high"].max())
        current_price = stock_data.current_price

        if high_price == 0:
            return 0.0, 0.0, 0

        dip_pct = ((high_price - current_price) / high_price) * 100

        # Find days since high
        high_idx = recent_bars["high"].idxmax()
        days_since = (bars.index[-1] - high_idx).days if hasattr(high_idx, "days") else 0

        return dip_pct, high_price, abs(days_since)

    def _detect_volume_spike(self, stock_data: StockData) -> bool:
        """
        Check if there's a volume spike.

        A volume spike indicates unusual selling pressure.
        """
        return stock_data.volume_ratio >= self.volume_spike_ratio

    def _classify_dip(
        self,
        dip_pct: float,
        volume_spike: bool,
        technical: Optional[TechnicalIndicators],
        trend: Optional[TrendAnalysis],
    ) -> DipClassification:
        """
        Classify the type of dip.

        Args:
            dip_pct: Dip percentage
            volume_spike: Whether there's a volume spike
            technical: Technical indicators
            trend: Trend analysis

        Returns:
            DipClassification
        """
        is_oversold = technical and technical.is_oversold
        was_uptrend = trend and trend.change_90d > 0

        # Panic sell: severe drop + volume spike + oversold
        if dip_pct >= self.severe_dip_threshold and volume_spike and is_oversold:
            return DipClassification.PANIC_SELL

        # Panic sell: moderate drop + very high volume + oversold
        if dip_pct >= self.dip_threshold and volume_spike and is_oversold:
            return DipClassification.PANIC_SELL

        # Correction: dip in an uptrend, no extreme volume
        if was_uptrend and dip_pct >= self.dip_threshold:
            return DipClassification.CORRECTION

        # Fundamental: sustained downtrend with dip
        if trend and trend.change_90d < -20:
            return DipClassification.FUNDAMENTAL

        # Default to correction if significant dip
        if dip_pct >= self.dip_threshold:
            return DipClassification.CORRECTION

        return DipClassification.NOISE

    def is_buying_opportunity(
        self,
        dip: DipInfo,
        technical: Optional[TechnicalIndicators] = None,
        trend: Optional[TrendAnalysis] = None,
    ) -> bool:
        """
        Determine if a dip represents a buying opportunity.

        Best opportunities:
        - Panic sell with oversold RSI
        - Correction in a consistent uptrend

        Args:
            dip: DipInfo object
            technical: Technical indicators
            trend: Trend analysis

        Returns:
            True if this is a potential buying opportunity
        """
        # Not significant
        if not dip.is_significant:
            return False

        # Fundamental issues - avoid
        if dip.classification == DipClassification.FUNDAMENTAL:
            return False

        # Panic sell with oversold = strong opportunity
        if dip.classification == DipClassification.PANIC_SELL:
            if technical and technical.is_oversold:
                return True

        # Correction in uptrend = moderate opportunity
        if dip.classification == DipClassification.CORRECTION:
            if trend and trend.change_90d > 0:
                return True

        # Correction with oversold
        if dip.classification == DipClassification.CORRECTION:
            if technical and technical.rsi < 40:
                return True

        return False

    def calculate_support_distance(
        self,
        stock_data: StockData,
        lookback: int = 60,
    ) -> Optional[float]:
        """
        Calculate distance to support level.

        Support is approximated as the lowest low in lookback period.

        Args:
            stock_data: Stock data
            lookback: Days to look back

        Returns:
            Percentage above support, or None
        """
        if stock_data.bars is None or len(stock_data.bars) < lookback:
            return None

        recent_bars = stock_data.bars.iloc[-lookback:]
        support = float(recent_bars["low"].min())

        if support == 0:
            return None

        return ((stock_data.current_price - support) / support) * 100

    def get_recovery_potential(
        self,
        dip: DipInfo,
        trend: Optional[TrendAnalysis],
    ) -> str:
        """
        Estimate recovery potential.

        Returns:
            "high", "medium", "low"
        """
        if dip.classification == DipClassification.FUNDAMENTAL:
            return "low"

        if dip.classification == DipClassification.PANIC_SELL:
            if trend and trend.change_90d > 10:
                return "high"
            return "medium"

        if dip.classification == DipClassification.CORRECTION:
            if trend and trend.is_consistent and trend.is_uptrend:
                return "high"
            return "medium"

        return "low"
