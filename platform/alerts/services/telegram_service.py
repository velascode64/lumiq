"""
Telegram notification service for alerts.
"""

import os
import logging
import asyncio
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class TelegramService:
    """Service for sending Telegram notifications."""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
    ):
        """
        Initialize Telegram service.

        Args:
            bot_token: Telegram bot token (defaults to TELEGRAM_TOKEN env var)
            chat_id: Target chat ID (defaults to TELEGRAM_CHAT_ID env var)
        """
        self.bot_token = (
            bot_token
            or os.getenv("TELEGRAM_TOKEN", "").strip()
            or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        )
        self.chat_id = (
            chat_id
            or os.getenv("TELEGRAM_CHAT_ID", "").strip()
            or self._first_allowed_chat_id()
        )

        if not self.bot_token:
            logger.warning("TELEGRAM token not set (expected TELEGRAM_TOKEN or TELEGRAM_BOT_TOKEN) - notifications disabled")
        if not self.chat_id:
            logger.warning("TELEGRAM chat id not set (expected TELEGRAM_CHAT_ID or TELEGRAM_ALLOWED_CHAT_IDS) - notifications disabled")

    @staticmethod
    def _first_allowed_chat_id() -> str:
        raw = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
        if not raw:
            return ""
        for token in raw.replace(";", ",").split(","):
            candidate = token.strip()
            if candidate:
                return candidate
        return ""

    @property
    def is_configured(self) -> bool:
        """Check if Telegram is properly configured."""
        return bool(self.bot_token and self.chat_id)

    def send_message(
        self,
        message: str,
        parse_mode: str = "Markdown",
        silent: bool = False,
    ) -> bool:
        """
        Send a message to Telegram.

        Args:
            message: Message text (supports Markdown)
            parse_mode: Parse mode ("Markdown" or "HTML")
            silent: Send without notification sound

        Returns:
            True if sent successfully
        """
        if not self.is_configured:
            logger.warning("Telegram not configured, skipping message")
            return False

        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": parse_mode,
                "disable_notification": silent,
            }

            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()

            result = response.json()
            if not result.get("ok"):
                logger.error(f"Telegram API error: {result}")
                return False

            logger.info("Telegram message sent successfully")
            return True

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    async def send_message_async(
        self,
        message: str,
        parse_mode: str = "Markdown",
        silent: bool = False,
    ) -> bool:
        """
        Send a message asynchronously.

        Args:
            message: Message text
            parse_mode: Parse mode
            silent: Silent notification

        Returns:
            True if sent successfully
        """
        # Run sync method in thread pool
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.send_message(message, parse_mode, silent),
        )

    def send_alert_summary(self, summary) -> bool:
        """
        Send an AlertSummary as a Telegram message.

        Args:
            summary: AlertSummary object

        Returns:
            True if sent successfully
        """
        message = summary.to_telegram_message()
        return self.send_message(message)

    def send_opportunity(self, opportunity, detailed: bool = False) -> bool:
        """
        Send a single opportunity notification.

        Args:
            opportunity: Opportunity object
            detailed: Include detailed analysis

        Returns:
            True if sent successfully
        """
        emoji = {"hot": "🔥", "watch": "👀", "ignore": "⚪"}.get(
            opportunity.priority.value, ""
        )

        lines = [
            f"{emoji} *{opportunity.symbol}* - {opportunity.priority.value.upper()}",
            f"Score: {opportunity.score:.0f}/100",
            f"Price: ${opportunity.stock_data.current_price:.2f}",
            f"Daily: {opportunity.stock_data.daily_change_pct:+.2f}%",
        ]

        if opportunity.dip and opportunity.dip.is_significant:
            lines.append(f"Dip: {opportunity.dip.dip_percentage:.1f}% from high")

        if opportunity.technical.is_oversold:
            lines.append(f"RSI: {opportunity.technical.rsi:.1f} (oversold)")

        lines.append("")
        lines.append("*Reasons:*")
        for reason in opportunity.reasons[:3]:
            lines.append(f"• {reason}")

        message = "\n".join(lines)
        return self.send_message(message)

    def send_error(self, error_message: str) -> bool:
        """
        Send an error notification.

        Args:
            error_message: Error description

        Returns:
            True if sent successfully
        """
        message = f"❌ *Alert System Error*\n\n{error_message}"
        return self.send_message(message, silent=True)

    def send_startup(self, asset_count: int) -> bool:
        """
        Send startup notification.

        Args:
            asset_count: Number of assets being monitored

        Returns:
            True if sent successfully
        """
        message = f"🔆 *Alert System Started*\nMonitoring {asset_count} assets"
        return self.send_message(message, silent=True)
