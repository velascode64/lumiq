"""
Pytest configuration and fixtures for alert system tests.

Provides mocks for Alpaca API and sample data for testing.
"""

import sys
import os
from pathlib import Path

# Add packages/core to path so `alerts` is importable without loading parent package __init__
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Load .env from core directory for integration tests (if present)
try:
    from dotenv import load_dotenv
    core_env = Path(__file__).resolve().parents[2] / ".env"
    if core_env.exists():
        load_dotenv(core_env)
except Exception:
    pass

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch

from alerts.models.schemas import (
    StockData,
    TechnicalIndicators,
    TrendAnalysis,
    TrendDirection,
    DipInfo,
    DipClassification,
    Opportunity,
    Priority,
)


@pytest.fixture
def sample_dates():
    """Generate sample date range."""
    end = datetime.now()
    start = end - timedelta(days=100)
    return pd.date_range(start=start, end=end, freq="D")


@pytest.fixture
def sample_bars(sample_dates):
    """
    Generate sample OHLCV data for testing.

    Creates realistic price data with some volatility.
    """
    np.random.seed(42)
    n = len(sample_dates)

    # Generate random walk prices
    returns = np.random.normal(0.001, 0.02, n)
    prices = 100 * np.exp(np.cumsum(returns))

    # Add some volatility for high/low
    high = prices * (1 + np.abs(np.random.normal(0, 0.01, n)))
    low = prices * (1 - np.abs(np.random.normal(0, 0.01, n)))

    df = pd.DataFrame({
        "open": prices * (1 + np.random.normal(0, 0.005, n)),
        "high": high,
        "low": low,
        "close": prices,
        "volume": np.random.randint(1000000, 10000000, n),
    }, index=sample_dates)

    return df


@pytest.fixture
def uptrend_bars(sample_dates):
    """Generate bars for an uptrend scenario."""
    np.random.seed(42)
    n = len(sample_dates)

    # Strong uptrend
    trend = np.linspace(100, 150, n)
    noise = np.random.normal(0, 2, n)
    prices = trend + noise

    high = prices * 1.01
    low = prices * 0.99

    df = pd.DataFrame({
        "open": prices * 0.998,
        "high": high,
        "low": low,
        "close": prices,
        "volume": np.random.randint(1000000, 10000000, n),
    }, index=sample_dates)

    return df


@pytest.fixture
def downtrend_bars(sample_dates):
    """Generate bars for a downtrend scenario."""
    np.random.seed(42)
    n = len(sample_dates)

    # Strong downtrend
    trend = np.linspace(150, 100, n)
    noise = np.random.normal(0, 2, n)
    prices = trend + noise

    high = prices * 1.01
    low = prices * 0.99

    df = pd.DataFrame({
        "open": prices * 1.002,
        "high": high,
        "low": low,
        "close": prices,
        "volume": np.random.randint(1000000, 10000000, n),
    }, index=sample_dates)

    return df


@pytest.fixture
def dip_bars(sample_dates):
    """Generate bars with a recent dip."""
    np.random.seed(42)
    n = len(sample_dates)

    # Uptrend followed by sharp dip
    prices = np.concatenate([
        np.linspace(100, 130, n - 10),  # Uptrend
        np.linspace(130, 105, 10),       # Sharp dip
    ])

    high = prices * 1.01
    low = prices * 0.99

    # High volume on dip days
    volume = np.concatenate([
        np.random.randint(1000000, 3000000, n - 10),
        np.random.randint(5000000, 10000000, 10),  # Volume spike
    ])

    df = pd.DataFrame({
        "open": prices * 0.998,
        "high": high,
        "low": low,
        "close": prices,
        "volume": volume,
    }, index=sample_dates)

    return df


@pytest.fixture
def sample_stock_data(sample_bars):
    """Create sample StockData object."""
    return StockData(
        symbol="TEST",
        current_price=float(sample_bars["close"].iloc[-1]),
        previous_close=float(sample_bars["close"].iloc[-2]),
        high_52w=float(sample_bars["high"].max()),
        low_52w=float(sample_bars["low"].min()),
        volume=float(sample_bars["volume"].iloc[-1]),
        avg_volume=float(sample_bars["volume"].mean()),
        bars=sample_bars,
    )


@pytest.fixture
def uptrend_stock_data(uptrend_bars):
    """Create StockData for uptrend scenario."""
    return StockData(
        symbol="UPTREND",
        current_price=float(uptrend_bars["close"].iloc[-1]),
        previous_close=float(uptrend_bars["close"].iloc[-2]),
        high_52w=float(uptrend_bars["high"].max()),
        low_52w=float(uptrend_bars["low"].min()),
        volume=float(uptrend_bars["volume"].iloc[-1]),
        avg_volume=float(uptrend_bars["volume"].mean()),
        bars=uptrend_bars,
    )


@pytest.fixture
def dip_stock_data(dip_bars):
    """Create StockData for dip scenario."""
    return StockData(
        symbol="DIP",
        current_price=float(dip_bars["close"].iloc[-1]),
        previous_close=float(dip_bars["close"].iloc[-2]),
        high_52w=float(dip_bars["high"].max()),
        low_52w=float(dip_bars["low"].min()),
        volume=float(dip_bars["volume"].iloc[-1]),
        avg_volume=float(dip_bars["volume"].mean()),
        bars=dip_bars,
    )


@pytest.fixture
def sample_technical():
    """Create sample TechnicalIndicators."""
    return TechnicalIndicators(
        symbol="TEST",
        rsi=45.0,
        atr=2.5,
        chandelier_exit=95.0,
        sma_20=98.0,
        sma_50=95.0,
        sma_200=90.0,
    )


@pytest.fixture
def oversold_technical():
    """Create oversold TechnicalIndicators."""
    return TechnicalIndicators(
        symbol="OVERSOLD",
        rsi=25.0,
        atr=3.5,
        chandelier_exit=90.0,
        sma_20=100.0,
        sma_50=105.0,
        sma_200=110.0,
    )


@pytest.fixture
def sample_trend():
    """Create sample TrendAnalysis."""
    return TrendAnalysis(
        symbol="TEST",
        change_30d=5.0,
        change_60d=10.0,
        change_90d=15.0,
        direction=TrendDirection.UP,
        momentum_score=40.0,
        is_consistent=True,
    )


@pytest.fixture
def downtrend_analysis():
    """Create downtrend TrendAnalysis."""
    return TrendAnalysis(
        symbol="DOWN",
        change_30d=-10.0,
        change_60d=-15.0,
        change_90d=-25.0,
        direction=TrendDirection.DOWN,
        momentum_score=-50.0,
        is_consistent=True,
    )


@pytest.fixture
def sample_dip():
    """Create sample DipInfo."""
    return DipInfo(
        symbol="DIP",
        dip_percentage=15.0,
        from_high_price=120.0,
        current_price=102.0,
        volume_spike=True,
        classification=DipClassification.PANIC_SELL,
        days_since_high=5,
    )


@pytest.fixture
def mock_alpaca_client():
    """
    Mock of Alpaca StockHistoricalDataClient.

    Returns realistic mock responses for testing.
    """
    client = Mock()

    # Mock get_stock_bars
    def mock_get_bars(request):
        result = Mock()
        result.df = pd.DataFrame({
            "open": [100.0, 101.0, 102.0],
            "high": [102.0, 103.0, 104.0],
            "low": [99.0, 100.0, 101.0],
            "close": [101.0, 102.0, 103.0],
            "volume": [1000000, 1100000, 1200000],
        }, index=pd.date_range(end=datetime.now(), periods=3, freq="D"))
        return result

    client.get_stock_bars = Mock(side_effect=mock_get_bars)

    # Mock get_stock_latest_trade
    def mock_get_latest_trade(request):
        symbol = request.symbol_or_symbols
        if isinstance(symbol, list):
            symbol = symbol[0]
        trade = Mock()
        trade.price = 103.50
        return {symbol: trade}

    client.get_stock_latest_trade = Mock(side_effect=mock_get_latest_trade)

    return client


@pytest.fixture
def mock_crypto_client():
    """Mock of Alpaca CryptoHistoricalDataClient."""
    client = Mock()

    def mock_get_bars(request):
        result = Mock()
        result.df = pd.DataFrame({
            "open": [2000.0, 2010.0, 2020.0],
            "high": [2020.0, 2030.0, 2040.0],
            "low": [1990.0, 2000.0, 2010.0],
            "close": [2010.0, 2020.0, 2030.0],
            "volume": [10.0, 12.0, 11.0],
            "symbol": ["ETH/USD", "ETH/USD", "ETH/USD"],
            "timestamp": pd.date_range(end=datetime.now(), periods=3, freq="D"),
        }).set_index("timestamp")
        return result

    client.get_crypto_bars = Mock(side_effect=mock_get_bars)

    def mock_get_latest_trade(request):
        symbol = request.symbol_or_symbols
        if isinstance(symbol, list):
            symbol = symbol[0]
        trade = Mock()
        trade.price = 2030.0
        return {symbol: trade}

    client.get_crypto_latest_trade = Mock(side_effect=mock_get_latest_trade)
    return client

@pytest.fixture
def mock_telegram():
    """Mock TelegramService."""
    telegram = Mock()
    telegram.is_configured = True
    telegram.send_message = Mock(return_value=True)
    telegram.send_alert_summary = Mock(return_value=True)
    telegram.send_startup = Mock(return_value=True)
    return telegram


@pytest.fixture
def mock_data_service(mock_alpaca_client, mock_crypto_client, sample_stock_data):
    """Mock AlpacaDataService."""
    with patch("alerts.services.alpaca_data_service.StockHistoricalDataClient") as mock_client:
        mock_client.return_value = mock_alpaca_client
        with patch("alerts.services.alpaca_data_service.CryptoHistoricalDataClient") as mock_crypto:
            mock_crypto.return_value = mock_crypto_client

            from alerts.services.alpaca_data_service import AlpacaDataService

            service = AlpacaDataService(
                api_key="test_key",
                secret_key="test_secret",
            )

            # Override get_stock_data to return sample data
            service.get_stock_data = Mock(return_value=sample_stock_data)

            return service
