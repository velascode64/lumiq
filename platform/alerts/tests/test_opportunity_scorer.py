"""
Tests for OpportunityScorer.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

from alerts.opportunity_scorer import OpportunityScorer
from alerts.models.schemas import Priority, DipClassification, DipInfo


class TestOpportunityScorer:
    """Tests for OpportunityScorer class."""

    def test_init_default_params(self):
        """Test default initialization."""
        scorer = OpportunityScorer()
        assert scorer.hot_threshold == 70.0
        assert scorer.watch_threshold == 40.0

    def test_init_custom_params(self):
        """Test custom initialization."""
        scorer = OpportunityScorer(
            hot_threshold=80.0,
            watch_threshold=50.0,
        )
        assert scorer.hot_threshold == 80.0
        assert scorer.watch_threshold == 50.0

    def test_classify_priority_hot(self):
        """Test HOT classification."""
        scorer = OpportunityScorer()
        assert scorer.classify_priority(75) == Priority.HOT
        assert scorer.classify_priority(100) == Priority.HOT

    def test_classify_priority_watch(self):
        """Test WATCH classification."""
        scorer = OpportunityScorer()
        assert scorer.classify_priority(50) == Priority.WATCH
        assert scorer.classify_priority(69) == Priority.WATCH

    def test_classify_priority_ignore(self):
        """Test IGNORE classification."""
        scorer = OpportunityScorer()
        assert scorer.classify_priority(30) == Priority.IGNORE
        assert scorer.classify_priority(0) == Priority.IGNORE

    def test_score_basic(self, sample_stock_data, sample_technical, sample_trend):
        """Test basic scoring."""
        scorer = OpportunityScorer()
        opportunity = scorer.score(
            stock_data=sample_stock_data,
            technical=sample_technical,
            trend=sample_trend,
        )

        assert opportunity is not None
        assert 0 <= opportunity.score <= 100
        assert opportunity.priority in [Priority.HOT, Priority.WATCH, Priority.IGNORE]
        assert len(opportunity.reasons) > 0

    def test_score_oversold(self, sample_stock_data, oversold_technical, sample_trend):
        """Test scoring with oversold RSI."""
        scorer = OpportunityScorer()
        opportunity = scorer.score(
            stock_data=sample_stock_data,
            technical=oversold_technical,
            trend=sample_trend,
        )

        # Oversold should add to score
        assert opportunity.score >= scorer.DEFAULT_WEIGHTS["rsi_oversold"]
        assert any("oversold" in r.lower() for r in opportunity.reasons)

    def test_score_with_dip(self, sample_stock_data, sample_technical, sample_trend, sample_dip):
        """Test scoring with significant dip."""
        scorer = OpportunityScorer()
        opportunity = scorer.score(
            stock_data=sample_stock_data,
            technical=sample_technical,
            trend=sample_trend,
            dip=sample_dip,
        )

        # Dip should add to score
        assert opportunity.score > 0
        assert any("dip" in r.lower() for r in opportunity.reasons)

    def test_score_panic_sell(self, sample_stock_data, oversold_technical, sample_trend):
        """Test high score for panic sell scenario."""
        scorer = OpportunityScorer()

        dip = DipInfo(
            symbol="PANIC",
            dip_percentage=20.0,
            from_high_price=120.0,
            current_price=100.0,
            volume_spike=True,
            classification=DipClassification.PANIC_SELL,
        )

        opportunity = scorer.score(
            stock_data=sample_stock_data,
            technical=oversold_technical,
            trend=sample_trend,
            dip=dip,
        )

        # Should be high score
        assert opportunity.score >= 50
        assert opportunity.priority in [Priority.HOT, Priority.WATCH]

    def test_rank_opportunities(self, sample_stock_data, sample_technical, sample_trend):
        """Test opportunity ranking."""
        scorer = OpportunityScorer()

        # Create multiple opportunities with different scores
        opps = []
        for i, rsi in enumerate([20, 40, 60]):
            tech = sample_technical
            tech = type(tech)(
                symbol=f"TEST{i}",
                rsi=rsi,
                atr=tech.atr,
                chandelier_exit=tech.chandelier_exit,
            )
            opp = scorer.score(
                stock_data=sample_stock_data,
                technical=tech,
                trend=sample_trend,
            )
            opps.append(opp)

        ranked = scorer.rank_opportunities(opps)

        # Should be sorted by score descending
        for i in range(len(ranked) - 1):
            assert ranked[i].score >= ranked[i + 1].score

    def test_rank_opportunities_top_n(self, sample_stock_data, sample_technical, sample_trend):
        """Test top N ranking."""
        scorer = OpportunityScorer()

        opps = []
        for i in range(10):
            opp = scorer.score(
                stock_data=sample_stock_data,
                technical=sample_technical,
                trend=sample_trend,
            )
            opps.append(opp)

        top_5 = scorer.rank_opportunities(opps, top_n=5)
        assert len(top_5) == 5

    def test_filter_by_priority(self, sample_stock_data, sample_technical, sample_trend):
        """Test filtering by priority."""
        scorer = OpportunityScorer()

        opps = []
        # Create opportunities with varying RSI to get different priorities
        for rsi in [15, 25, 45, 55, 75]:
            tech = type(sample_technical)(
                symbol=f"TEST_{rsi}",
                rsi=rsi,
                atr=sample_technical.atr,
                chandelier_exit=sample_technical.chandelier_exit,
            )
            opp = scorer.score(
                stock_data=sample_stock_data,
                technical=tech,
                trend=sample_trend,
            )
            opps.append(opp)

        hot = scorer.filter_by_priority(opps, Priority.HOT)
        watch = scorer.filter_by_priority(opps, Priority.WATCH)

        for opp in hot:
            assert opp.priority == Priority.HOT
        for opp in watch:
            assert opp.priority == Priority.WATCH

    def test_get_summary_stats(self, sample_stock_data, sample_technical, sample_trend):
        """Test summary statistics."""
        scorer = OpportunityScorer()

        opps = []
        for i in range(5):
            opp = scorer.score(
                stock_data=sample_stock_data,
                technical=sample_technical,
                trend=sample_trend,
            )
            opps.append(opp)

        stats = scorer.get_summary_stats(opps)

        assert "total" in stats
        assert stats["total"] == 5
        assert "hot_count" in stats
        assert "watch_count" in stats
        assert "ignore_count" in stats
        assert "average_score" in stats
        assert stats["hot_count"] + stats["watch_count"] + stats["ignore_count"] == 5

    def test_score_clamping(self, sample_stock_data, oversold_technical, sample_trend):
        """Test that scores are clamped to 0-100."""
        scorer = OpportunityScorer()

        # Create scenario with many positive factors
        dip = DipInfo(
            symbol="MAX",
            dip_percentage=25.0,
            from_high_price=130.0,
            current_price=100.0,
            volume_spike=True,
            classification=DipClassification.PANIC_SELL,
        )

        opportunity = scorer.score(
            stock_data=sample_stock_data,
            technical=oversold_technical,
            trend=sample_trend,
            dip=dip,
        )

        assert 0 <= opportunity.score <= 100
