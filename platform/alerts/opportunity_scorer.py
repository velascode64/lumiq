"""
Opportunity Scorer for ranking trading opportunities.

Combines technical, trend, and dip analysis into a single score.
"""

import logging
from typing import List, Optional

from .models.schemas import (
    Opportunity,
    Priority,
    StockData,
    TechnicalIndicators,
    TrendAnalysis,
    DipInfo,
    DipClassification,
)

logger = logging.getLogger(__name__)


class OpportunityScorer:
    """Scores and ranks trading opportunities."""

    # Default scoring weights
    DEFAULT_WEIGHTS = {
        "rsi_oversold": 20,
        "rsi_neutral_low": 10,
        "dip_severe": 25,
        "dip_moderate": 15,
        "uptrend_consistent": 15,
        "uptrend_simple": 10,
        "volume_spike": 10,
        "near_support": 15,
        "pullback_in_uptrend": 20,
        "panic_sell": 15,
        "momentum_positive": 10,
        "above_sma200": 5,
    }

    def __init__(
        self,
        hot_threshold: float = 70.0,
        watch_threshold: float = 40.0,
        weights: dict = None,
    ):
        """
        Initialize the opportunity scorer.

        Args:
            hot_threshold: Minimum score for HOT priority
            watch_threshold: Minimum score for WATCH priority
            weights: Custom scoring weights
        """
        self.hot_threshold = hot_threshold
        self.watch_threshold = watch_threshold
        self.weights = weights or self.DEFAULT_WEIGHTS

    def score(
        self,
        stock_data: StockData,
        technical: TechnicalIndicators,
        trend: TrendAnalysis,
        dip: Optional[DipInfo] = None,
    ) -> Opportunity:
        """
        Calculate opportunity score and create Opportunity object.

        Args:
            stock_data: Stock market data
            technical: Technical indicators
            trend: Trend analysis
            dip: Dip information (optional)

        Returns:
            Opportunity object with score and priority
        """
        score = 0.0
        reasons = []

        # === RSI Scoring ===
        if technical.is_oversold:
            score += self.weights["rsi_oversold"]
            reasons.append(f"Oversold (RSI: {technical.rsi:.1f})")
        elif 30 <= technical.rsi < 40:
            score += self.weights["rsi_neutral_low"]
            reasons.append(f"Low RSI ({technical.rsi:.1f})")

        # === Dip Scoring ===
        if dip:
            if dip.dip_percentage >= 20:
                score += self.weights["dip_severe"]
                reasons.append(f"Severe dip ({dip.dip_percentage:.1f}% from high)")
            elif dip.dip_percentage >= 10:
                score += self.weights["dip_moderate"]
                reasons.append(f"Moderate dip ({dip.dip_percentage:.1f}% from high)")

            if dip.classification == DipClassification.PANIC_SELL:
                score += self.weights["panic_sell"]
                reasons.append("Panic selling detected")

            if dip.volume_spike:
                score += self.weights["volume_spike"]
                reasons.append("High volume")

        # === Trend Scoring ===
        if trend.is_consistent and trend.is_uptrend:
            score += self.weights["uptrend_consistent"]
            reasons.append("Consistent uptrend (30/60/90d)")
        elif trend.is_uptrend:
            score += self.weights["uptrend_simple"]
            reasons.append("Uptrend")

        # Pullback in uptrend is a strong signal
        if trend.change_30d < 0 and trend.change_60d > 0 and trend.change_90d > 0:
            score += self.weights["pullback_in_uptrend"]
            reasons.append("Pullback in uptrend")

        # Positive momentum
        if trend.momentum_score > 25:
            score += self.weights["momentum_positive"]
            reasons.append(f"Strong momentum ({trend.momentum_score:.0f})")

        # === Support Scoring ===
        from_52w_low = ((stock_data.current_price - stock_data.low_52w) / stock_data.low_52w * 100) if stock_data.low_52w > 0 else 100
        if from_52w_low < 20:  # Within 20% of 52-week low
            score += self.weights["near_support"]
            reasons.append(f"Near 52w low ({from_52w_low:.1f}% above)")

        # === SMA Scoring ===
        if technical.sma_200 and stock_data.current_price > technical.sma_200:
            score += self.weights["above_sma200"]
            reasons.append("Above 200 SMA")

        # Clamp score to 0-100
        score = max(0.0, min(100.0, score))

        # Determine priority
        priority = self.classify_priority(score)

        return Opportunity(
            symbol=stock_data.symbol,
            score=score,
            priority=priority,
            reasons=reasons,
            stock_data=stock_data,
            technical=technical,
            trend=trend,
            dip=dip,
        )

    def classify_priority(self, score: float) -> Priority:
        """
        Classify priority based on score.

        Args:
            score: Opportunity score (0-100)

        Returns:
            Priority enum
        """
        if score >= self.hot_threshold:
            return Priority.HOT
        elif score >= self.watch_threshold:
            return Priority.WATCH
        else:
            return Priority.IGNORE

    def rank_opportunities(
        self,
        opportunities: List[Opportunity],
        top_n: Optional[int] = None,
    ) -> List[Opportunity]:
        """
        Rank opportunities by score.

        Args:
            opportunities: List of opportunities
            top_n: Return only top N (optional)

        Returns:
            Sorted list of opportunities
        """
        # Sort by score descending
        sorted_opps = sorted(opportunities, key=lambda x: x.score, reverse=True)

        if top_n:
            return sorted_opps[:top_n]

        return sorted_opps

    def filter_by_priority(
        self,
        opportunities: List[Opportunity],
        priority: Priority,
    ) -> List[Opportunity]:
        """
        Filter opportunities by priority.

        Args:
            opportunities: List of opportunities
            priority: Priority to filter by

        Returns:
            Filtered list
        """
        return [opp for opp in opportunities if opp.priority == priority]

    def get_hot_opportunities(
        self,
        opportunities: List[Opportunity],
    ) -> List[Opportunity]:
        """Get only HOT opportunities, sorted by score."""
        hot = self.filter_by_priority(opportunities, Priority.HOT)
        return self.rank_opportunities(hot)

    def get_watch_opportunities(
        self,
        opportunities: List[Opportunity],
    ) -> List[Opportunity]:
        """Get only WATCH opportunities, sorted by score."""
        watch = self.filter_by_priority(opportunities, Priority.WATCH)
        return self.rank_opportunities(watch)

    def get_summary_stats(
        self,
        opportunities: List[Opportunity],
    ) -> dict:
        """
        Get summary statistics for opportunities.

        Returns:
            Dict with counts and averages
        """
        hot = self.filter_by_priority(opportunities, Priority.HOT)
        watch = self.filter_by_priority(opportunities, Priority.WATCH)
        ignore = self.filter_by_priority(opportunities, Priority.IGNORE)

        all_scores = [opp.score for opp in opportunities]
        avg_score = sum(all_scores) / len(all_scores) if all_scores else 0

        return {
            "total": len(opportunities),
            "hot_count": len(hot),
            "watch_count": len(watch),
            "ignore_count": len(ignore),
            "average_score": avg_score,
            "max_score": max(all_scores) if all_scores else 0,
            "min_score": min(all_scores) if all_scores else 0,
        }
