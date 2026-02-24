"""
Tests for AlpacaDataService.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
import pandas as pd
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime


class TestAlpacaDataService:
    """Tests for AlpacaDataService class."""

    def test_init_with_credentials(self):
        """Test initialization with credentials."""
        with patch("alerts.services.alpaca_data_service.StockHistoricalDataClient") as mock_client, \
             patch("alerts.services.alpaca_data_service.CryptoHistoricalDataClient"):
            from alerts.services.alpaca_data_service import AlpacaDataService

            service = AlpacaDataService(
                api_key="test_key",
                secret_key="test_secret",
            )

            assert service.api_key == "test_key"
            assert service.secret_key == "test_secret"
            mock_client.assert_called_once()

    def test_init_missing_credentials(self):
        """Test initialization fails without credentials."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="credentials required"):
                from alerts.services.alpaca_data_service import AlpacaDataService
                AlpacaDataService()

    def test_get_stock_bars_success(self, mock_alpaca_client):
        """Test successful bars retrieval."""
        with patch("alerts.services.alpaca_data_service.StockHistoricalDataClient") as mock_cls, \
             patch("alerts.services.alpaca_data_service.CryptoHistoricalDataClient"):
            mock_cls.return_value = mock_alpaca_client
            from alerts.services.alpaca_data_service import AlpacaDataService

            service = AlpacaDataService(
                api_key="test_key",
                secret_key="test_secret",
            )

            bars = service.get_stock_bars("AAPL", days=30)

            assert bars is not None
            assert isinstance(bars, pd.DataFrame)
            mock_alpaca_client.get_stock_bars.assert_called_once()

    def test_get_stock_bars_error(self):
        """Test bars retrieval with API error."""
        with patch("alerts.services.alpaca_data_service.StockHistoricalDataClient") as mock_cls, \
             patch("alerts.services.alpaca_data_service.CryptoHistoricalDataClient"):
            mock_client = Mock()
            mock_client.get_stock_bars.side_effect = Exception("API Error")
            mock_cls.return_value = mock_client
            from alerts.services.alpaca_data_service import AlpacaDataService

            service = AlpacaDataService(
                api_key="test_key",
                secret_key="test_secret",
            )

            bars = service.get_stock_bars("INVALID")

            assert bars is None

    def test_get_latest_price_success(self, mock_alpaca_client):
        """Test successful latest price retrieval."""
        with patch("alerts.services.alpaca_data_service.StockHistoricalDataClient") as mock_cls, \
             patch("alerts.services.alpaca_data_service.CryptoHistoricalDataClient"):
            mock_cls.return_value = mock_alpaca_client
            from alerts.services.alpaca_data_service import AlpacaDataService

            service = AlpacaDataService(
                api_key="test_key",
                secret_key="test_secret",
            )

            price = service.get_latest_price("AAPL")

            assert price is not None
            assert isinstance(price, float)
            assert price > 0

    def test_get_latest_price_error(self):
        """Test latest price retrieval with API error."""
        with patch("alerts.services.alpaca_data_service.StockHistoricalDataClient") as mock_cls, \
             patch("alerts.services.alpaca_data_service.CryptoHistoricalDataClient"):
            mock_client = Mock()
            mock_client.get_stock_latest_trade.side_effect = Exception("API Error")
            mock_cls.return_value = mock_client
            from alerts.services.alpaca_data_service import AlpacaDataService

            service = AlpacaDataService(
                api_key="test_key",
                secret_key="test_secret",
            )

            price = service.get_latest_price("INVALID")

            assert price is None

    def test_get_multiple_stocks(self, mock_alpaca_client):
        """Test multiple stocks retrieval."""
        # Setup mock to return multi-symbol data
        mock_df = pd.DataFrame({
            "symbol": ["AAPL", "AAPL", "GOOGL", "GOOGL"],
            "open": [150, 151, 2800, 2810],
            "high": [152, 153, 2820, 2830],
            "low": [149, 150, 2790, 2800],
            "close": [151, 152, 2810, 2820],
            "volume": [1000000, 1100000, 500000, 550000],
            "timestamp": pd.date_range(end=datetime.now(), periods=4, freq="12H"),
        })
        mock_df = mock_df.set_index(["symbol", "timestamp"])

        mock_result = Mock()
        mock_result.df = mock_df
        mock_alpaca_client.get_stock_bars = Mock(return_value=mock_result)

        with patch("alerts.services.alpaca_data_service.StockHistoricalDataClient") as mock_cls, \
             patch("alerts.services.alpaca_data_service.CryptoHistoricalDataClient"):
            mock_cls.return_value = mock_alpaca_client
            from alerts.services.alpaca_data_service import AlpacaDataService

            service = AlpacaDataService(
                api_key="test_key",
                secret_key="test_secret",
            )

            result = service.get_multiple_stocks(["AAPL", "GOOGL"], days=30)

            assert isinstance(result, dict)

    def test_get_stock_data_complete(self, mock_alpaca_client, sample_bars):
        """Test complete stock data retrieval."""
        mock_result = Mock()
        mock_result.df = sample_bars
        mock_alpaca_client.get_stock_bars = Mock(return_value=mock_result)

        trade_mock = Mock()
        trade_mock.price = 105.0
        mock_alpaca_client.get_stock_latest_trade = Mock(return_value={"AAPL": trade_mock})

        with patch("alerts.services.alpaca_data_service.StockHistoricalDataClient") as mock_cls, \
             patch("alerts.services.alpaca_data_service.CryptoHistoricalDataClient"):
            mock_cls.return_value = mock_alpaca_client
            from alerts.services.alpaca_data_service import AlpacaDataService

            service = AlpacaDataService(
                api_key="test_key",
                secret_key="test_secret",
            )

            stock_data = service.get_stock_data("AAPL")

            assert stock_data is not None
            assert stock_data.symbol == "AAPL"
            assert stock_data.current_price > 0
            assert stock_data.bars is not None

    def test_load_watchlist_with_symbol_column(self, tmp_path):
        """Test loading watchlist with 'symbol' column."""
        csv_file = tmp_path / "watchlist.csv"
        csv_file.write_text("symbol\nAAPL\nGOOGL\nMSFT\n")

        with patch("alerts.services.alpaca_data_service.StockHistoricalDataClient"), \
             patch("alerts.services.alpaca_data_service.CryptoHistoricalDataClient"):
            from alerts.services.alpaca_data_service import AlpacaDataService

            service = AlpacaDataService(
                api_key="test_key",
                secret_key="test_secret",
            )

            symbols = service.load_watchlist(str(csv_file))

            assert len(symbols) == 3
            assert "AAPL" in symbols
            assert "GOOGL" in symbols

    def test_load_watchlist_with_ticker_column(self, tmp_path):
        """Test loading watchlist with 'ticker' column."""
        csv_file = tmp_path / "watchlist.csv"
        csv_file.write_text("ticker,quantity\naapl,100\ngoogl,50\n")

        with patch("alerts.services.alpaca_data_service.StockHistoricalDataClient"), \
             patch("alerts.services.alpaca_data_service.CryptoHistoricalDataClient"):
            from alerts.services.alpaca_data_service import AlpacaDataService

            service = AlpacaDataService(
                api_key="test_key",
                secret_key="test_secret",
            )

            symbols = service.load_watchlist(str(csv_file))

            assert len(symbols) == 2
            assert "AAPL" in symbols  # Should be uppercased

    def test_load_watchlist_file_not_found(self):
        """Test loading non-existent watchlist."""
        with patch("alerts.services.alpaca_data_service.StockHistoricalDataClient"), \
             patch("alerts.services.alpaca_data_service.CryptoHistoricalDataClient"):
            from alerts.services.alpaca_data_service import AlpacaDataService

            service = AlpacaDataService(
                api_key="test_key",
                secret_key="test_secret",
            )

            symbols = service.load_watchlist("/nonexistent/path.csv")

            assert symbols == []

    def test_get_crypto_latest_price(self, mock_crypto_client):
        """Test latest price retrieval for crypto symbol."""
        with patch("alerts.services.alpaca_data_service.StockHistoricalDataClient") as mock_stock:
            mock_stock.return_value = Mock()
            with patch("alerts.services.alpaca_data_service.CryptoHistoricalDataClient") as mock_crypto:
                mock_crypto.return_value = mock_crypto_client
                from alerts.services.alpaca_data_service import AlpacaDataService

                service = AlpacaDataService(api_key="test_key", secret_key="test_secret")
                price = service.get_latest_price("ETH/USD")

                assert price == 2030.0
                mock_crypto_client.get_crypto_latest_trade.assert_called_once()

    def test_get_crypto_bars(self, mock_crypto_client):
        """Test historical bars retrieval for crypto symbol."""
        with patch("alerts.services.alpaca_data_service.StockHistoricalDataClient") as mock_stock:
            mock_stock.return_value = Mock()
            with patch("alerts.services.alpaca_data_service.CryptoHistoricalDataClient") as mock_crypto:
                mock_crypto.return_value = mock_crypto_client
                from alerts.services.alpaca_data_service import AlpacaDataService

                service = AlpacaDataService(api_key="test_key", secret_key="test_secret")
                bars = service.get_stock_bars("ETHUSD", days=3)

                assert bars is not None
                assert not bars.empty
                mock_crypto_client.get_crypto_bars.assert_called_once()
