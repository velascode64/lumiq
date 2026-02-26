"""
Trend Analysis for detecting multi-period trends.

Analyzes 30, 60, and 90 day periods to detect consistent growth patterns.
"""

import logging
from typing import List, Optional

import pandas as pd

from ..models.schemas import TrendAnalysis, TrendDirection, StockData

logger = logging.getLogger(__name__)


class TrendAnalyzer:
    """Analyzes price trends over multiple periods."""

    def __init__(
        self,
        periods: List[int] = None,
        uptrend_threshold: float = 5.0,
        downtrend_threshold: float = -5.0,
    ):
        """
        Initialize the trend analyzer.

        Args:
            periods: List of periods to analyze (default: [30, 60, 90])
            uptrend_threshold: Minimum % change to consider uptrend
            downtrend_threshold: Maximum % change to consider downtrend
        """
        self.periods = periods or [30, 60, 90]
        self.uptrend_threshold = uptrend_threshold
        self.downtrend_threshold = downtrend_threshold

    def analyze(self, stock_data: StockData) -> Optional[TrendAnalysis]:
        """
        Analyze trend over multiple periods.

        Args:
            stock_data: StockData object with historical bars

        Returns:
            TrendAnalysis or None if insufficient data
        """
        if stock_data.bars is None or len(stock_data.bars) < max(self.periods):
            logger.warning(f"Insufficient data for trend analysis: {stock_data.symbol}")
            return None

        try:
            prices = stock_data.bars["close"]
            current_price = stock_data.current_price

            # Calculate changes for each period
            change_30d = self._calculate_period_change(prices, current_price, 30)
            change_60d = self._calculate_period_change(prices, current_price, 60)
            change_90d = self._calculate_period_change(prices, current_price, 90)

            # Determine overall direction
            direction = self._determine_direction(change_30d, change_60d, change_90d)

            # Calculate momentum score
            momentum_score = self._calculate_momentum_score(
                change_30d, change_60d, change_90d
            )

            # Check if trend is consistent
            is_consistent = self._is_consistent_trend(change_30d, change_60d, change_90d)

            return TrendAnalysis(
                symbol=stock_data.symbol,
                change_30d=change_30d,
                change_60d=change_60d,
                change_90d=change_90d,
                direction=direction,
                momentum_score=momentum_score,
                is_consistent=is_consistent,
            )

        except Exception as e:
            logger.error(f"Trend analysis failed for {stock_data.symbol}: {e}")
            return None

    def _calculate_period_change(
        self,
        prices: pd.Series,
        current_price: float,
        days: int,
    ) -> float:
        """
        Calculate percentage change over a period.

        Args:
            prices: Historical close prices
            current_price: Current price
            days: Number of days to look back

        Returns:
            Percentage change
        """
        if len(prices) < days:
            return 0.0

        past_price = float(prices.iloc[-days])
        if past_price == 0:
            return 0.0

        return ((current_price - past_price) / past_price) * 100

    def _determine_direction(
        self,
        change_30d: float,
        change_60d: float,
        change_90d: float,
    ) -> TrendDirection:
        """
        Determine overall trend direction.

        Uses weighted average with more weight on recent periods.

        Args:
            change_30d: 30-day change
            change_60d: 60-day change
            change_90d: 90-day change

        Returns:
            TrendDirection
        """
        # Weighted average (recent periods have more weight)
        weighted_change = (change_30d * 0.5) + (change_60d * 0.3) + (change_90d * 0.2)

        if weighted_change >= self.uptrend_threshold:
            return TrendDirection.UP
        elif weighted_change <= self.downtrend_threshold:
            return TrendDirection.DOWN
        else:
            return TrendDirection.SIDEWAYS

    def _calculate_momentum_score(
        self,
        change_30d: float,
        change_60d: float,
        change_90d: float,
    ) -> float:
        """
        Calculate momentum score from -100 to +100.

        Considers both magnitude and acceleration of trend.

        Args:
            change_30d: 30-day change
            change_60d: 60-day change
            change_90d: 90-day change

        Returns:
            Momentum score
        """
        # Weighted magnitude
        weighted_change = (change_30d * 0.5) + (change_60d * 0.3) + (change_90d * 0.2)

        # Acceleration (is trend speeding up or slowing down?)
        monthly_30 = change_30d
        monthly_60 = change_60d / 2 if change_60d else 0
        monthly_90 = change_90d / 3 if change_90d else 0

        acceleration = monthly_30 - monthly_60

        # Combine magnitude and acceleration (keep magnitude dominant)
        score = (weighted_change * 0.7) + (acceleration * 0.3)

        # Clamp to -100 to +100
        return max(-100.0, min(100.0, score))

    def _is_consistent_trend(
        self,
        change_30d: float,
        change_60d: float,
        change_90d: float,
    ) -> bool:
        """
        Check if trend is consistent across all periods.

        A consistent uptrend means all periods are positive.
        A consistent downtrend means all periods are negative.

        Args:
            change_30d: 30-day change
            change_60d: 60-day change
            change_90d: 90-day change

        Returns:
            True if trend is consistent
        """
        all_positive = change_30d > 0 and change_60d > 0 and change_90d > 0
        all_negative = change_30d < 0 and change_60d < 0 and change_90d < 0

        return all_positive or all_negative

    def is_consistent_uptrend(self, trend: TrendAnalysis) -> bool:
        """Check if in consistent uptrend (growth month over month)."""
        return (
            getattr(trend.direction, "value", trend.direction) == TrendDirection.UP.value
            and trend.is_consistent
            and trend.change_30d > 0
            and trend.change_60d > 0
            and trend.change_90d > 0
        )

    def is_accelerating_uptrend(self, trend: TrendAnalysis) -> bool:
        """
        Check if uptrend is accelerating.

        Acceleration means recent periods have stronger growth.
        """
        if getattr(trend.direction, "value", trend.direction) != TrendDirection.UP.value:
            return False

        monthly_30 = trend.change_30d
        monthly_60 = trend.change_60d / 2

        return monthly_30 > monthly_60

    def is_pullback_in_uptrend(self, trend: TrendAnalysis) -> bool:
        """
        Detect a pullback within a longer-term uptrend.

        This is often a buying opportunity.
        """
        # Short-term negative, but longer-term positive
        return (
            trend.change_30d < 0
            and trend.change_60d > 0
            and trend.change_90d > 0
        )

    def get_trend_strength(self, trend: TrendAnalysis) -> str:
        """
        Classify trend strength.

        Returns:
            "strong", "moderate", or "weak"
        """
        momentum = abs(trend.momentum_score)

        if momentum >= 50:
            return "strong"
        elif momentum >= 25:
            return "moderate"
        else:
            return "weak"
