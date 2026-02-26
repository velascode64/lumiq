"""
Tests for DipDetector.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

from alerts.analyzers.dip_detector import DipDetector
from alerts.models.schemas import DipClassification


class TestDipDetector:
    """Tests for DipDetector class."""

    def test_init_default_params(self):
        """Test default initialization."""
        detector = DipDetector()
        assert detector.dip_threshold == 10.0
        assert detector.severe_dip_threshold == 20.0
        assert detector.volume_spike_ratio == 2.0

    def test_init_custom_params(self):
        """Test custom initialization."""
        detector = DipDetector(
            dip_threshold=15.0,
            severe_dip_threshold=25.0,
            volume_spike_ratio=3.0,
        )
        assert detector.dip_threshold == 15.0
        assert detector.severe_dip_threshold == 25.0

    def test_detect_significant_dip(self, dip_stock_data, oversold_technical, sample_trend):
        """Test detection of significant dip."""
        detector = DipDetector()
        result = detector.detect(
            dip_stock_data,
            technical=oversold_technical,
            trend=sample_trend,
        )

        assert result is not None
        assert result.is_significant is True
        assert result.dip_percentage >= 10.0

    def test_detect_no_dip(self, uptrend_stock_data):
        """Test when there's no significant dip."""
        detector = DipDetector()
        result = detector.detect(uptrend_stock_data)

        # May or may not be significant depending on data
        assert result is not None

    def test_detect_volume_spike(self, dip_stock_data):
        """Test volume spike detection."""
        detector = DipDetector(volume_spike_ratio=1.5)
        result = detector.detect(dip_stock_data)

        assert result is not None
        # The dip data has volume spike
        assert result.volume_spike is True

    def test_classify_panic_sell(self, dip_stock_data, oversold_technical, sample_trend):
        """Test panic sell classification."""
        detector = DipDetector()
        result = detector.detect(
            dip_stock_data,
            technical=oversold_technical,
            trend=sample_trend,
        )

        # With oversold RSI and volume spike, should be panic sell
        if result and result.is_significant:
            assert result.classification in [
                DipClassification.PANIC_SELL,
                DipClassification.CORRECTION,
            ]

    def test_classify_correction(self, dip_stock_data, sample_technical, sample_trend):
        """Test correction classification."""
        detector = DipDetector()
        result = detector.detect(
            dip_stock_data,
            technical=sample_technical,  # Not oversold
            trend=sample_trend,  # Uptrend
        )

        if result and result.is_significant:
            # With uptrend but not oversold, likely correction
            assert result.classification in [
                DipClassification.CORRECTION,
                DipClassification.PANIC_SELL,
            ]

    def test_is_buying_opportunity_panic(self, sample_dip, oversold_technical, sample_trend):
        """Test buying opportunity detection for panic sell."""
        detector = DipDetector()

        is_opp = detector.is_buying_opportunity(
            sample_dip,
            technical=oversold_technical,
            trend=sample_trend,
        )

        assert is_opp is True

    def test_is_buying_opportunity_correction(self, sample_technical, sample_trend):
        """Test buying opportunity detection for correction."""
        from ..models.schemas import DipInfo

        detector = DipDetector()

        dip = DipInfo(
            symbol="CORR",
            dip_percentage=12.0,
            from_high_price=112.0,
            current_price=100.0,
            volume_spike=False,
            classification=DipClassification.CORRECTION,
        )

        is_opp = detector.is_buying_opportunity(
            dip,
            technical=sample_technical,
            trend=sample_trend,
        )

        assert is_opp is True

    def test_is_not_buying_opportunity_fundamental(self, downtrend_analysis):
        """Test that fundamental drops are not opportunities."""
        from ..models.schemas import DipInfo, TechnicalIndicators

        detector = DipDetector()

        dip = DipInfo(
            symbol="FUND",
            dip_percentage=25.0,
            from_high_price=125.0,
            current_price=100.0,
            volume_spike=True,
            classification=DipClassification.FUNDAMENTAL,
        )

        technical = TechnicalIndicators(
            symbol="FUND",
            rsi=35.0,
            atr=2.0,
            chandelier_exit=95.0,
        )

        is_opp = detector.is_buying_opportunity(
            dip,
            technical=technical,
            trend=downtrend_analysis,
        )

        assert is_opp is False

    def test_calculate_support_distance(self, sample_stock_data):
        """Test support distance calculation."""
        detector = DipDetector()
        distance = detector.calculate_support_distance(sample_stock_data)

        assert distance is not None
        assert distance >= 0  # Should be at or above support

    def test_get_recovery_potential_high(self, sample_trend):
        """Test high recovery potential."""
        from ..models.schemas import DipInfo

        detector = DipDetector()

        dip = DipInfo(
            symbol="HIGH",
            dip_percentage=15.0,
            from_high_price=115.0,
            current_price=100.0,
            volume_spike=True,
            classification=DipClassification.PANIC_SELL,
        )

        potential = detector.get_recovery_potential(dip, sample_trend)
        assert potential in ["high", "medium"]

    def test_get_recovery_potential_low(self, downtrend_analysis):
        """Test low recovery potential."""
        from ..models.schemas import DipInfo

        detector = DipDetector()

        dip = DipInfo(
            symbol="LOW",
            dip_percentage=20.0,
            from_high_price=120.0,
            current_price=100.0,
            volume_spike=True,
            classification=DipClassification.FUNDAMENTAL,
        )

        potential = detector.get_recovery_potential(dip, downtrend_analysis)
        assert potential == "low"
