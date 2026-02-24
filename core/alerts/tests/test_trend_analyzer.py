"""
Tests for TrendAnalyzer.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
import pandas as pd
import numpy as np

from alerts.analyzers.trend_analyzer import TrendAnalyzer
from alerts.models.schemas import TrendDirection


class TestTrendAnalyzer:
    """Tests for TrendAnalyzer class."""

    def test_init_default_params(self):
        """Test default initialization."""
        analyzer = TrendAnalyzer()
        assert analyzer.periods == [30, 60, 90]
        assert analyzer.uptrend_threshold == 5.0
        assert analyzer.downtrend_threshold == -5.0

    def test_init_custom_params(self):
        """Test custom initialization."""
        analyzer = TrendAnalyzer(
            periods=[20, 40, 60],
            uptrend_threshold=10.0,
            downtrend_threshold=-10.0,
        )
        assert analyzer.periods == [20, 40, 60]
        assert analyzer.uptrend_threshold == 10.0

    def test_analyze_uptrend(self, uptrend_stock_data):
        """Test analysis in uptrend."""
        analyzer = TrendAnalyzer()
        result = analyzer.analyze(uptrend_stock_data)

        assert result is not None
        assert result.direction == TrendDirection.UP
        assert result.change_30d > 0
        assert result.change_60d > 0
        assert result.change_90d > 0
        assert result.is_consistent is True
        assert result.momentum_score > 0

    def test_analyze_downtrend(self, downtrend_bars):
        """Test analysis in downtrend."""
        from ..models.schemas import StockData

        stock_data = StockData(
            symbol="DOWN",
            current_price=float(downtrend_bars["close"].iloc[-1]),
            previous_close=float(downtrend_bars["close"].iloc[-2]),
            high_52w=float(downtrend_bars["high"].max()),
            low_52w=float(downtrend_bars["low"].min()),
            volume=float(downtrend_bars["volume"].iloc[-1]),
            avg_volume=float(downtrend_bars["volume"].mean()),
            bars=downtrend_bars,
        )

        analyzer = TrendAnalyzer()
        result = analyzer.analyze(stock_data)

        assert result is not None
        assert result.direction == TrendDirection.DOWN
        assert result.change_30d < 0
        assert result.change_90d < 0
        assert result.momentum_score < 0

    def test_analyze_insufficient_data(self):
        """Test analysis with insufficient data."""
        from ..models.schemas import StockData

        analyzer = TrendAnalyzer()

        stock_data = StockData(
            symbol="TEST",
            current_price=100.0,
            previous_close=99.0,
            high_52w=110.0,
            low_52w=90.0,
            volume=1000000,
            avg_volume=1000000,
            bars=pd.DataFrame({"close": [100, 101, 102]}),
        )

        result = analyzer.analyze(stock_data)
        assert result is None

    def test_is_consistent_uptrend(self, sample_trend):
        """Test consistent uptrend detection."""
        analyzer = TrendAnalyzer()
        assert analyzer.is_consistent_uptrend(sample_trend) is True

    def test_is_consistent_uptrend_false(self, downtrend_analysis):
        """Test non-uptrend detection."""
        analyzer = TrendAnalyzer()
        assert analyzer.is_consistent_uptrend(downtrend_analysis) is False

    def test_is_accelerating_uptrend(self):
        """Test accelerating uptrend detection."""
        from ..models.schemas import TrendAnalysis

        analyzer = TrendAnalyzer()

        # Monthly 30d > monthly 60d = accelerating
        trend = TrendAnalysis(
            symbol="ACC",
            change_30d=15.0,   # 15% in 30 days = 15%/month
            change_60d=20.0,   # 20% in 60 days = 10%/month
            change_90d=25.0,
            direction=TrendDirection.UP,
            momentum_score=50,
            is_consistent=True,
        )

        assert analyzer.is_accelerating_uptrend(trend) is True

    def test_is_pullback_in_uptrend(self):
        """Test pullback detection."""
        from ..models.schemas import TrendAnalysis

        analyzer = TrendAnalyzer()

        # Short-term down, long-term up
        trend = TrendAnalysis(
            symbol="PULL",
            change_30d=-5.0,
            change_60d=10.0,
            change_90d=20.0,
            direction=TrendDirection.SIDEWAYS,
            momentum_score=10,
            is_consistent=False,
        )

        assert analyzer.is_pullback_in_uptrend(trend) is True

    def test_get_trend_strength(self):
        """Test trend strength classification."""
        from ..models.schemas import TrendAnalysis

        analyzer = TrendAnalyzer()

        strong = TrendAnalysis(
            symbol="S",
            change_30d=20,
            change_60d=30,
            change_90d=40,
            direction=TrendDirection.UP,
            momentum_score=60,
            is_consistent=True,
        )
        assert analyzer.get_trend_strength(strong) == "strong"

        moderate = TrendAnalysis(
            symbol="M",
            change_30d=5,
            change_60d=10,
            change_90d=15,
            direction=TrendDirection.UP,
            momentum_score=30,
            is_consistent=True,
        )
        assert analyzer.get_trend_strength(moderate) == "moderate"

        weak = TrendAnalysis(
            symbol="W",
            change_30d=1,
            change_60d=2,
            change_90d=3,
            direction=TrendDirection.SIDEWAYS,
            momentum_score=10,
            is_consistent=False,
        )
        assert analyzer.get_trend_strength(weak) == "weak"

    def test_momentum_score_bounds(self, sample_stock_data):
        """Test that momentum score stays within bounds."""
        analyzer = TrendAnalyzer()
        result = analyzer.analyze(sample_stock_data)

        if result:
            assert -100 <= result.momentum_score <= 100
