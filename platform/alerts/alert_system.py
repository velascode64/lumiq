"""
Alert System Orchestrator.

Main entry point for the intelligent alert system.
Coordinates data fetching, analysis, and notifications.
"""

import logging
import time
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
try:
    import schedule
except ModuleNotFoundError:  # pragma: no cover - optional dependency for scheduler
    schedule = None

from .storage import alert_rules_store, portfolio_store

from .models.schemas import (
    AlertSummary,
    Opportunity,
    Priority,
    StockData,
)
from .services.alpaca_data_service import AlpacaDataService
from .services.telegram_service import TelegramService
from .analyzers.technical_analyzer import TechnicalAnalyzer
from .analyzers.trend_analyzer import TrendAnalyzer
from .analyzers.dip_detector import DipDetector
from .opportunity_scorer import OpportunityScorer


def create_alert_agent(alert_system):
    """
    Lazily import and create the Agno alert agent.

    Kept at module level for patching in tests without importing agno.
    """
    from ...agents.agno.members.alert_agent import create_alert_agent as _create_alert_agent
    return _create_alert_agent(alert_system)

logger = logging.getLogger(__name__)


@dataclass
class AlertRule:
    """User-defined alert rule."""
    id: str
    symbol: str
    rule_type: str  # percent_drop | percent_rise | target_price
    threshold: Optional[float] = None
    target: Optional[float] = None
    active: bool = True
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


class AlertSystem:
    """
    Main orchestrator for the intelligent alert system.

    Coordinates:
    - Data fetching from Alpaca
    - Technical, trend, and dip analysis
    - Opportunity scoring
    - Telegram notifications
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        telegram_token: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
        alerts_store_override=None,
        portfolio_store_override=None,
    ):
        """
        Initialize the alert system.

        Args:
            api_key: Alpaca API key
            secret_key: Alpaca secret key
            telegram_token: Telegram bot token
            telegram_chat_id: Telegram chat ID
        """
        # Initialize services
        self.data_service = AlpacaDataService(
            api_key=api_key,
            secret_key=secret_key,
        )
        self.telegram = TelegramService(
            bot_token=telegram_token,
            chat_id=telegram_chat_id,
        )

        # Initialize analyzers
        self.technical_analyzer = TechnicalAnalyzer()
        self.trend_analyzer = TrendAnalyzer()
        self.dip_detector = DipDetector()
        self.scorer = OpportunityScorer()

        # State
        self.watchlist: List[str] = []
        self.opportunities: List[Opportunity] = []
        self._agent = None
        self._active_chat_id: Optional[int] = None
        self._stream_manager = None

        # Persistence
        core_dir = Path(__file__).resolve().parents[1]
        self._alerts_store = alerts_store_override or alert_rules_store(core_dir / "alerts" / "data" / "alert_rules.json")
        self._portfolio_store = portfolio_store_override or portfolio_store(core_dir / "alerts" / "data" / "portfolio.json")

        # Ensure files exist
        self._alerts_store.read()
        self._portfolio_store.read()

    def set_active_chat_id(self, chat_id: Optional[int]) -> None:
        """Set the active chat id for creating rules from chat context."""
        self._active_chat_id = chat_id

    def get_active_chat_id(self) -> Optional[int]:
        """Get the active chat id for rule creation."""
        return self._active_chat_id

    def get_default_chat_id(self) -> Optional[int]:
        """Fallback chat id from env (TELEGRAM_CHAT_ID or TELEGRAM_ALLOWED_CHAT_IDS)."""
        raw = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        if raw:
            try:
                return int(raw)
            except ValueError:
                return None
        allowed = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
        if not allowed:
            return None
        for token in allowed.replace(";", ",").split(","):
            token = token.strip()
            if not token:
                continue
            try:
                return int(token)
            except ValueError:
                continue
        return None

    def set_stream_manager(self, manager) -> None:
        """Attach a stream manager so rules can refresh subscriptions."""
        self._stream_manager = manager

    def load_watchlist(self, filepath: str) -> int:
        """
        Load symbols from watchlist file.

        Args:
            filepath: Path to CSV file

        Returns:
            Number of symbols loaded
        """
        self.watchlist = self.data_service.load_watchlist(filepath)
        logger.info(f"Loaded {len(self.watchlist)} symbols from {filepath}")
        return len(self.watchlist)

    def set_watchlist(self, symbols: List[str]) -> None:
        """
        Set watchlist directly.

        Args:
            symbols: List of stock symbols
        """
        self.watchlist = [s.upper().strip() for s in symbols]
        logger.info(f"Set watchlist with {len(self.watchlist)} symbols")

    def analyze_single(self, symbol: str) -> Optional[Opportunity]:
        """
        Analyze a single symbol.

        Args:
            symbol: Stock symbol

        Returns:
            Opportunity or None if analysis failed
        """
        try:
            # Get stock data
            stock_data = self.data_service.get_stock_data(symbol)
            if stock_data is None:
                logger.warning(f"No data for {symbol}")
                return None

            # Run analyzers
            technical = self.technical_analyzer.analyze(stock_data)
            if technical is None:
                return None

            trend = self.trend_analyzer.analyze(stock_data)
            if trend is None:
                return None

            dip = self.dip_detector.detect(stock_data, technical, trend)

            # Score the opportunity
            opportunity = self.scorer.score(
                stock_data=stock_data,
                technical=technical,
                trend=trend,
                dip=dip,
            )

            return opportunity

        except Exception as e:
            logger.error(f"Analysis failed for {symbol}: {e}")
            return None

    def run_analysis(self, session: str = "analysis") -> AlertSummary:
        """
        Run analysis on all watchlist symbols.

        Args:
            session: Session name (apertura, medio_dia, cierre)

        Returns:
            AlertSummary with results
        """
        logger.info(f"Starting {session} analysis for {len(self.watchlist)} symbols")

        self.opportunities = []

        for symbol in self.watchlist:
            opportunity = self.analyze_single(symbol)
            if opportunity:
                self.opportunities.append(opportunity)

        logger.info(f"Analyzed {len(self.opportunities)} symbols successfully")

        return self.create_summary(session)

    def create_summary(self, session: str = "analysis") -> AlertSummary:
        """
        Create an AlertSummary from current opportunities.

        Args:
            session: Session name

        Returns:
            AlertSummary object
        """
        hot = self.scorer.get_hot_opportunities(self.opportunities)
        watch = self.scorer.get_watch_opportunities(self.opportunities)

        # Determine market sentiment
        stats = self.scorer.get_summary_stats(self.opportunities)
        if stats["hot_count"] >= 5:
            sentiment = "bullish"
        elif stats["average_score"] < 30:
            sentiment = "bearish"
        else:
            sentiment = "neutral"

        return AlertSummary(
            timestamp=datetime.now(),
            session=session,
            total_analyzed=len(self.opportunities),
            hot_opportunities=hot[:10],
            watch_opportunities=watch[:10],
            market_sentiment=sentiment,
        )

    def get_top_opportunities(self, n: int = 10) -> List[Opportunity]:
        """
        Get top N opportunities.

        Args:
            n: Number of opportunities to return

        Returns:
            List of top opportunities
        """
        return self.scorer.rank_opportunities(self.opportunities, top_n=n)

    def get_hot_opportunities(self) -> List[Opportunity]:
        """Get all HOT opportunities."""
        return self.scorer.get_hot_opportunities(self.opportunities)

    def get_watch_opportunities(self) -> List[Opportunity]:
        """Get all WATCH opportunities."""
        return self.scorer.get_watch_opportunities(self.opportunities)

    def get_dip_opportunities(self) -> List[Opportunity]:
        """Get opportunities with significant dips."""
        return [
            opp for opp in self.opportunities
            if opp.dip and opp.dip.is_significant
        ]

    def get_market_summary(self) -> dict:
        """Get market summary statistics."""
        stats = self.scorer.get_summary_stats(self.opportunities)

        # Add additional context
        dip_count = len(self.get_dip_opportunities())
        oversold_count = len([
            opp for opp in self.opportunities
            if opp.technical.is_oversold
        ])

        stats["dip_count"] = dip_count
        stats["oversold_count"] = oversold_count

        return stats

    # ===== Alert Rules Persistence =====
    def list_rules(self) -> List[Dict[str, Any]]:
        data = self._alerts_store.read()
        return list(data.get("rules", []))

    def add_rule(self, rule: Dict[str, Any]) -> Dict[str, Any]:
        data = self._alerts_store.read()
        rules = data.get("rules", [])
        if not rule.get("id"):
            rule["id"] = str(uuid.uuid4())
        if rule.get("chat_id") is None and self._active_chat_id is not None:
            rule["chat_id"] = int(self._active_chat_id)
        if rule.get("chat_id") is None:
            fallback = self.get_default_chat_id()
            if fallback is not None:
                rule["chat_id"] = int(fallback)
        if rule.get("cooldown_seconds") is None:
            rule["cooldown_seconds"] = 300
        if rule.get("last_triggered_at") is None:
            rule["last_triggered_at"] = None
        rules.append(rule)
        data["rules"] = rules
        data["updated_at"] = datetime.now().isoformat()
        self._alerts_store.write(data)
        if hasattr(self._alerts_store, "log_event"):
            try:
                self._alerts_store.log_event(rule.get("id"), rule.get("symbol"), "created", payload=rule)
            except Exception:
                logger.exception("Failed to log alert created event")
        if self._stream_manager is not None:
            try:
                self._stream_manager.refresh_subscriptions()
            except Exception as e:
                logger.error("Failed to refresh stream subscriptions: %s", e)
        return rule

    def update_rule(self, rule_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        data = self._alerts_store.read()
        rules = data.get("rules", [])
        for r in rules:
            if r.get("id") == rule_id:
                r.update(updates)
                data["updated_at"] = datetime.now().isoformat()
                self._alerts_store.write(data)
                if hasattr(self._alerts_store, "log_event"):
                    try:
                        self._alerts_store.log_event(rule_id, r.get("symbol"), "updated", payload=updates)
                    except Exception:
                        logger.exception("Failed to log alert updated event")
                if self._stream_manager is not None:
                    try:
                        self._stream_manager.refresh_subscriptions()
                    except Exception as e:
                        logger.error("Failed to refresh stream subscriptions: %s", e)
                return r
        return None

    def remove_rule(self, rule_id: str) -> bool:
        data = self._alerts_store.read()
        rules = data.get("rules", [])
        new_rules = [r for r in rules if r.get("id") != rule_id]
        if len(new_rules) == len(rules):
            return False
        data["rules"] = new_rules
        data["updated_at"] = datetime.now().isoformat()
        self._alerts_store.write(data)
        if hasattr(self._alerts_store, "log_event"):
            try:
                self._alerts_store.log_event(rule_id, None if not new_rules else next((x.get("symbol") for x in rules if x.get("id")==rule_id), None), "removed", payload={"rule_id": rule_id})
            except Exception:
                logger.exception("Failed to log alert removed event")
        if self._stream_manager is not None:
            try:
                self._stream_manager.refresh_subscriptions()
            except Exception as e:
                logger.error("Failed to refresh stream subscriptions: %s", e)
        return True

    # ===== Rule Evaluation =====
    def evaluate_rules(self) -> List[str]:
        """
        Evaluate persisted rules against current prices.
        Returns list of triggered messages.
        """
        messages: List[str] = []
        for rule in self.list_rules():
            if not rule.get("active", True):
                continue
            symbol = rule.get("symbol")
            if not symbol:
                continue
            current = self.data_service.get_latest_price(symbol)
            if current is None:
                continue

            rtype = rule.get("type")
            if rtype == "target_price":
                target = rule.get("target")
                if target is not None and float(current) >= float(target):
                    messages.append(f"🎯 {symbol} reached target ${target:.2f} (now ${current:.2f})")
            elif rtype == "percent_drop":
                threshold = rule.get("threshold")
                prev = rule.get("reference_price")
                if threshold is not None and prev:
                    change = (current - prev) / prev * 100
                    if change <= -abs(float(threshold)):
                        messages.append(f"📉 {symbol} dropped {abs(change):.2f}% (threshold {threshold}%)")
            elif rtype == "percent_rise":
                threshold = rule.get("threshold")
                prev = rule.get("reference_price")
                if threshold is not None and prev:
                    change = (current - prev) / prev * 100
                    if change >= abs(float(threshold)):
                        messages.append(f"📈 {symbol} rose {abs(change):.2f}% (threshold {threshold}%)")

        return messages

    def send_summary(self, session: str = "analysis") -> bool:
        """
        Create and send summary to Telegram.

        Args:
            session: Session name

        Returns:
            True if sent successfully
        """
        summary = self.create_summary(session)
        return self.telegram.send_alert_summary(summary)

    def send_rule_alerts(self) -> int:
        """Evaluate rules and send any triggered messages to Telegram."""
        messages = self.evaluate_rules()
        sent = 0
        for msg in messages:
            if self.telegram.send_message(msg):
                sent += 1
        return sent

    def run_and_notify(self, session: str = "analysis") -> AlertSummary:
        """
        Run analysis and send notification.

        Args:
            session: Session name

        Returns:
            AlertSummary
        """
        summary = self.run_analysis(session)

        if summary.has_opportunities:
            self.send_summary(session)
        else:
            logger.info("No opportunities found, skipping notification")

        # Also evaluate user-defined alert rules
        try:
            count = self.send_rule_alerts()
            if count:
                logger.info("Sent %d rule alert(s)", count)
        except Exception as e:
            logger.error("Rule evaluation failed: %s", e)

        return summary

    def start_scheduler(self, timezone: str = "America/New_York") -> None:
        """
        Start the scheduled analysis.

        Runs 3 times daily:
        - 9:30 AM ET (apertura)
        - 12:30 PM ET (medio_dia)
        - 3:30 PM ET (cierre)

        Args:
            timezone: Timezone for scheduling
        """
        if schedule is None:
            raise RuntimeError(
                "Scheduler dependency not installed. Install with `pip install schedule` to use start_scheduler()."
            )
        logger.info("Starting alert scheduler")

        # Schedule the three daily runs
        schedule.every().day.at("09:30", timezone).do(
            self.run_and_notify, "apertura"
        )
        schedule.every().day.at("12:30", timezone).do(
            self.run_and_notify, "medio_dia"
        )
        schedule.every().day.at("15:30", timezone).do(
            self.run_and_notify, "cierre"
        )

        # Send startup notification
        self.telegram.send_startup(len(self.watchlist))

        # Run scheduler loop
        logger.info("Scheduler running. Press Ctrl+C to stop.")
        while True:
            schedule.run_pending()
            time.sleep(60)

    def get_agent(self):
        """
        Get or create the Agno agent.

        Returns:
            Agent instance or None if not configured
        """
        if self._agent is None:
            self._agent = create_alert_agent(self)

        return self._agent


def main():
    """Main entry point for running the alert system."""
    import argparse
    import os
    from pathlib import Path

    # Load .env from core directory if available
    try:
        from dotenv import load_dotenv
        core_env = Path(__file__).resolve().parents[1] / ".env"
        if core_env.exists():
            load_dotenv(core_env)
    except Exception:
        # dotenv is optional; continue without it
        pass

    parser = argparse.ArgumentParser(description="Intelligent Stock Alert System")
    parser.add_argument(
        "--watchlist",
        type=str,
        default="watchlist.csv",
        help="Path to watchlist CSV file",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run analysis once and exit",
    )
    parser.add_argument(
        "--session",
        type=str,
        default="manual",
        help="Session name for the analysis",
    )

    args = parser.parse_args()

    # Initialize system
    system = AlertSystem()

    # Load watchlist
    if os.path.exists(args.watchlist):
        system.load_watchlist(args.watchlist)
    else:
        # Default watchlist for testing
        system.set_watchlist(["SPY", "QQQ", "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA"])

    if args.once:
        # Run once and exit
        summary = system.run_and_notify(args.session)
        print(f"\nAnalyzed: {summary.total_analyzed}")
        print(f"HOT: {len(summary.hot_opportunities)}")
        print(f"WATCH: {len(summary.watch_opportunities)}")

        if summary.hot_opportunities:
            print("\nTop HOT opportunities:")
            for opp in summary.hot_opportunities[:5]:
                print(f"  {opp.summary}")
    else:
        # Run scheduler
        system.start_scheduler()


if __name__ == "__main__":
    main()
