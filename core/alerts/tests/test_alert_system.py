"""
Tests for AlertSystem.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from alerts.models.schemas import Priority


class TestAlertSystem:
    """Tests for AlertSystem class."""

    @pytest.fixture
    def mock_system(self, sample_stock_data, sample_technical, sample_trend):
        """Create AlertSystem with mocked dependencies."""
        with patch("alerts.alert_system.AlpacaDataService") as mock_data:
            with patch("alerts.alert_system.TelegramService") as mock_telegram:
                mock_data_instance = Mock()
                mock_data_instance.get_stock_data = Mock(return_value=sample_stock_data)
                mock_data_instance.load_watchlist = Mock(return_value=["AAPL", "GOOGL"])
                mock_data.return_value = mock_data_instance

                mock_telegram_instance = Mock()
                mock_telegram_instance.is_configured = True
                mock_telegram_instance.send_alert_summary = Mock(return_value=True)
                mock_telegram.return_value = mock_telegram_instance

                from alerts.alert_system import AlertSystem

                system = AlertSystem(
                    api_key="test_key",
                    secret_key="test_secret",
                )

                # Mock analyzers to return test data
                system.technical_analyzer.analyze = Mock(return_value=sample_technical)
                system.trend_analyzer.analyze = Mock(return_value=sample_trend)
                system.dip_detector.detect = Mock(return_value=None)

                yield system

    def test_init(self):
        """Test initialization."""
        with patch("alerts.alert_system.AlpacaDataService"):
            with patch("alerts.alert_system.TelegramService"):
                from alerts.alert_system import AlertSystem

                system = AlertSystem(
                    api_key="test_key",
                    secret_key="test_secret",
                )

                assert system.data_service is not None
                assert system.telegram is not None
                assert system.technical_analyzer is not None
                assert system.trend_analyzer is not None
                assert system.dip_detector is not None
                assert system.scorer is not None

    def test_set_watchlist(self, mock_system):
        """Test setting watchlist directly."""
        mock_system.set_watchlist(["AAPL", "googl", " MSFT "])

        assert len(mock_system.watchlist) == 3
        assert "AAPL" in mock_system.watchlist
        assert "GOOGL" in mock_system.watchlist
        assert "MSFT" in mock_system.watchlist

    def test_load_watchlist(self, mock_system):
        """Test loading watchlist from file."""
        count = mock_system.load_watchlist("test.csv")

        assert count == 2
        assert len(mock_system.watchlist) == 2

    def test_analyze_single_success(self, mock_system, sample_stock_data):
        """Test single symbol analysis."""
        opportunity = mock_system.analyze_single("AAPL")

        assert opportunity is not None
        assert opportunity.symbol == sample_stock_data.symbol
        assert 0 <= opportunity.score <= 100

    def test_analyze_single_no_data(self, mock_system):
        """Test analysis when no data available."""
        mock_system.data_service.get_stock_data = Mock(return_value=None)

        opportunity = mock_system.analyze_single("INVALID")

        assert opportunity is None

    def test_run_analysis(self, mock_system):
        """Test full analysis run."""
        mock_system.set_watchlist(["AAPL", "GOOGL", "MSFT"])

        summary = mock_system.run_analysis("test")

        assert summary is not None
        assert summary.session == "test"
        assert summary.total_analyzed == 3

    def test_create_summary(self, mock_system):
        """Test summary creation."""
        mock_system.set_watchlist(["AAPL", "GOOGL"])
        mock_system.run_analysis("test")

        summary = mock_system.create_summary("apertura")

        assert summary is not None
        assert summary.session == "apertura"
        assert summary.market_sentiment in ["bullish", "bearish", "neutral"]

    def test_get_top_opportunities(self, mock_system):
        """Test getting top opportunities."""
        mock_system.set_watchlist(["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA"])
        mock_system.run_analysis("test")

        top_3 = mock_system.get_top_opportunities(3)

        assert len(top_3) <= 3
        # Should be sorted by score
        for i in range(len(top_3) - 1):
            assert top_3[i].score >= top_3[i + 1].score

    def test_get_hot_opportunities(self, mock_system):
        """Test getting HOT opportunities."""
        mock_system.set_watchlist(["AAPL", "GOOGL"])
        mock_system.run_analysis("test")

        hot = mock_system.get_hot_opportunities()

        for opp in hot:
            assert opp.priority == Priority.HOT

    def test_get_watch_opportunities(self, mock_system):
        """Test getting WATCH opportunities."""
        mock_system.set_watchlist(["AAPL", "GOOGL"])
        mock_system.run_analysis("test")

        watch = mock_system.get_watch_opportunities()

        for opp in watch:
            assert opp.priority == Priority.WATCH

    def test_get_dip_opportunities(self, mock_system, sample_dip):
        """Test getting dip opportunities."""
        mock_system.dip_detector.detect = Mock(return_value=sample_dip)
        mock_system.set_watchlist(["DIP1", "DIP2"])
        mock_system.run_analysis("test")

        dips = mock_system.get_dip_opportunities()

        for opp in dips:
            assert opp.dip is not None
            assert opp.dip.is_significant

    def test_get_market_summary(self, mock_system):
        """Test market summary."""
        mock_system.set_watchlist(["AAPL", "GOOGL", "MSFT"])
        mock_system.run_analysis("test")

        summary = mock_system.get_market_summary()

        assert "total" in summary
        assert "hot_count" in summary
        assert "watch_count" in summary
        assert "dip_count" in summary
        assert "oversold_count" in summary

    def test_send_summary(self, mock_system):
        """Test sending summary to Telegram."""
        mock_system.set_watchlist(["AAPL"])
        mock_system.run_analysis("test")

        result = mock_system.send_summary("test")

        assert result is True
        mock_system.telegram.send_alert_summary.assert_called_once()

    def test_run_and_notify_with_opportunities(self, mock_system):
        """Test run and notify when opportunities exist."""
        mock_system.set_watchlist(["AAPL", "GOOGL"])

        summary = mock_system.run_and_notify("apertura")

        assert summary is not None
        # Should have called telegram if there are opportunities
        if summary.has_opportunities:
            mock_system.telegram.send_alert_summary.assert_called()

    def test_run_and_notify_no_opportunities(self, mock_system):
        """Test run and notify with no opportunities."""
        # Create system that returns no significant opportunities
        mock_system.set_watchlist([])

        summary = mock_system.run_and_notify("test")

        assert summary.total_analyzed == 0

    def test_summary_to_telegram_message(self, mock_system):
        """Test Telegram message formatting."""
        mock_system.set_watchlist(["AAPL", "GOOGL"])
        mock_system.run_analysis("test")

        summary = mock_system.create_summary("apertura")
        message = summary.to_telegram_message()

        assert "APERTURA" in message
        assert "Market:" in message
        assert "Analyzed:" in message

    def test_get_agent(self, mock_system):
        """Test agent creation."""
        with patch("alerts.alert_system.create_alert_agent") as mock_create:
            mock_create.return_value = Mock()

            agent = mock_system.get_agent()

            # Should cache agent
            agent2 = mock_system.get_agent()
            assert agent is agent2
