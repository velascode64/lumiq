"""
Tests for TechnicalAnalyzer.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from alerts.analyzers.technical_analyzer import TechnicalAnalyzer
from alerts.models.schemas import StockData


class TestTechnicalAnalyzer:
    """Tests for TechnicalAnalyzer class."""

    def test_init_default_params(self):
        """Test default initialization."""
        analyzer = TechnicalAnalyzer()
        assert analyzer.rsi_period == 14
        assert analyzer.atr_period == 14
        assert analyzer.chandelier_multiplier == 2.5

    def test_init_custom_params(self):
        """Test custom initialization."""
        analyzer = TechnicalAnalyzer(
            rsi_period=10,
            atr_period=20,
            chandelier_multiplier=3.0,
        )
        assert analyzer.rsi_period == 10
        assert analyzer.atr_period == 20
        assert analyzer.chandelier_multiplier == 3.0

    def test_calculate_rsi_uptrend(self):
        """Test RSI calculation in uptrend."""
        analyzer = TechnicalAnalyzer()

        # Create uptrending prices
        prices = pd.Series(np.linspace(100, 120, 30))
        rsi = analyzer.calculate_rsi(prices)

        # In uptrend, RSI should be above 50
        assert rsi > 50
        assert rsi <= 100

    def test_calculate_rsi_downtrend(self):
        """Test RSI calculation in downtrend."""
        analyzer = TechnicalAnalyzer()

        # Create downtrending prices
        prices = pd.Series(np.linspace(120, 100, 30))
        rsi = analyzer.calculate_rsi(prices)

        # In downtrend, RSI should be below 50
        assert rsi < 50
        assert rsi >= 0

    def test_calculate_rsi_sideways(self):
        """Test RSI calculation in sideways market."""
        analyzer = TechnicalAnalyzer()

        # Create sideways prices with small oscillations
        np.random.seed(42)
        prices = pd.Series(100 + np.random.normal(0, 1, 30))
        rsi = analyzer.calculate_rsi(prices)

        # In sideways, RSI should be around 50
        assert 30 <= rsi <= 70

    def test_calculate_rsi_insufficient_data(self):
        """Test RSI with insufficient data."""
        analyzer = TechnicalAnalyzer(rsi_period=14)

        # Only 10 data points
        prices = pd.Series(np.linspace(100, 110, 10))
        rsi = analyzer.calculate_rsi(prices)

        # Should return neutral
        assert rsi == 50.0

    def test_calculate_atr(self, sample_bars):
        """Test ATR calculation."""
        analyzer = TechnicalAnalyzer()
        atr = analyzer.calculate_atr(sample_bars)

        # ATR should be positive
        assert atr > 0
        # ATR should be reasonable (not huge relative to price)
        assert atr < sample_bars["close"].mean() * 0.1

    def test_calculate_atr_insufficient_data(self):
        """Test ATR with insufficient data."""
        analyzer = TechnicalAnalyzer()

        df = pd.DataFrame({
            "high": [100, 101, 102],
            "low": [99, 100, 101],
            "close": [100, 101, 101.5],
        })
        atr = analyzer.calculate_atr(df)

        # Should handle gracefully
        assert atr >= 0

    def test_calculate_chandelier_exit(self, sample_bars):
        """Test Chandelier Exit calculation."""
        analyzer = TechnicalAnalyzer()
        atr = analyzer.calculate_atr(sample_bars)
        chandelier = analyzer.calculate_chandelier_exit(sample_bars, atr)

        # Chandelier should be below highest high
        highest = sample_bars["high"].max()
        assert chandelier < highest

    def test_calculate_sma(self):
        """Test SMA calculation."""
        analyzer = TechnicalAnalyzer()

        prices = pd.Series([10, 20, 30, 40, 50])
        sma_5 = analyzer.calculate_sma(prices, 5)

        assert sma_5 == 30.0  # Average of all 5

    def test_calculate_sma_insufficient_data(self):
        """Test SMA with insufficient data."""
        analyzer = TechnicalAnalyzer()

        prices = pd.Series([10, 20, 30])
        sma_10 = analyzer.calculate_sma(prices, 10)

        assert sma_10 is None

    def test_analyze_complete(self, sample_stock_data):
        """Test complete analysis."""
        analyzer = TechnicalAnalyzer()
        result = analyzer.analyze(sample_stock_data)

        assert result is not None
        assert result.symbol == sample_stock_data.symbol
        assert 0 <= result.rsi <= 100
        assert result.atr > 0
        assert result.chandelier_exit > 0

    def test_analyze_insufficient_data(self):
        """Test analysis with insufficient data."""
        analyzer = TechnicalAnalyzer()

        stock_data = StockData(
            symbol="TEST",
            current_price=100.0,
            previous_close=99.0,
            high_52w=110.0,
            low_52w=90.0,
            volume=1000000,
            avg_volume=1000000,
            bars=pd.DataFrame({
                "close": [100, 101],
                "high": [101, 102],
                "low": [99, 100],
            }),
        )

        result = analyzer.analyze(stock_data)
        assert result is None

    def test_is_oversold(self):
        """Test oversold detection."""
        analyzer = TechnicalAnalyzer()

        assert analyzer.is_oversold(25) is True
        assert analyzer.is_oversold(30) is False
        assert analyzer.is_oversold(50) is False

    def test_is_overbought(self):
        """Test overbought detection."""
        analyzer = TechnicalAnalyzer()

        assert analyzer.is_overbought(75) is True
        assert analyzer.is_overbought(70) is False
        assert analyzer.is_overbought(50) is False

    def test_is_below_chandelier(self):
        """Test Chandelier Exit comparison."""
        analyzer = TechnicalAnalyzer()

        assert analyzer.is_below_chandelier(95, 100) is True
        assert analyzer.is_below_chandelier(105, 100) is False
        assert analyzer.is_below_chandelier(100, 100) is False

    def test_get_price_vs_sma(self):
        """Test price vs SMA calculation."""
        analyzer = TechnicalAnalyzer()

        # 10% above SMA
        pct = analyzer.get_price_vs_sma(110, 100)
        assert pct == 10.0

        # 10% below SMA
        pct = analyzer.get_price_vs_sma(90, 100)
        assert pct == -10.0

        # No SMA
        pct = analyzer.get_price_vs_sma(100, None)
        assert pct is None
