"""
Technical Analysis Calculator.

Calculates RSI, ATR, Chandelier Exit, and other technical indicators.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

from ..models.schemas import TechnicalIndicators, StockData

logger = logging.getLogger(__name__)


class TechnicalAnalyzer:
    """Calculates technical indicators for stocks."""

    def __init__(
        self,
        rsi_period: int = 14,
        atr_period: int = 14,
        chandelier_multiplier: float = 2.5,
    ):
        """
        Initialize the technical analyzer.

        Args:
            rsi_period: Period for RSI calculation
            atr_period: Period for ATR calculation
            chandelier_multiplier: Multiplier for Chandelier Exit
        """
        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self.chandelier_multiplier = chandelier_multiplier

    def analyze(self, stock_data: StockData) -> Optional[TechnicalIndicators]:
        """
        Calculate all technical indicators for a stock.

        Args:
            stock_data: StockData object with historical bars

        Returns:
            TechnicalIndicators or None if insufficient data
        """
        if stock_data.bars is None or len(stock_data.bars) < self.rsi_period + 1:
            logger.warning(f"Insufficient data for {stock_data.symbol}")
            return None

        df = stock_data.bars.copy()

        try:
            rsi = self.calculate_rsi(df["close"])
            atr = self.calculate_atr(df)
            chandelier = self.calculate_chandelier_exit(df, atr)
            sma_20 = self.calculate_sma(df["close"], 20)
            sma_50 = self.calculate_sma(df["close"], 50)
            sma_200 = self.calculate_sma(df["close"], 200)

            return TechnicalIndicators(
                symbol=stock_data.symbol,
                rsi=rsi,
                atr=atr,
                chandelier_exit=chandelier,
                sma_20=sma_20,
                sma_50=sma_50,
                sma_200=sma_200,
            )

        except Exception as e:
            logger.error(f"Technical analysis failed for {stock_data.symbol}: {e}")
            return None

    def calculate_rsi(
        self,
        prices: pd.Series,
        period: Optional[int] = None,
    ) -> float:
        """
        Calculate the Relative Strength Index.

        RSI = 100 - (100 / (1 + RS))
        RS = Average Gain / Average Loss

        Args:
            prices: Series of closing prices
            period: RSI period (default: self.rsi_period)

        Returns:
            Current RSI value (0-100)
        """
        period = period or self.rsi_period

        if len(prices) < period + 1:
            return 50.0  # Neutral if insufficient data

        # Calculate price changes
        delta = prices.diff()

        # Separate gains and losses
        gains = delta.where(delta > 0, 0.0)
        losses = (-delta).where(delta < 0, 0.0)

        # Calculate exponential moving averages
        avg_gain = gains.ewm(alpha=1/period, adjust=False).mean()
        avg_loss = losses.ewm(alpha=1/period, adjust=False).mean()

        last_gain = float(avg_gain.iloc[-1])
        last_loss = float(avg_loss.iloc[-1])

        # Avoid division by zero and handle flat series
        if last_loss == 0:
            return 50.0 if last_gain == 0 else 100.0
        if last_gain == 0:
            return 0.0

        rs = last_gain / last_loss
        rsi = 100 - (100 / (1 + rs))

        return float(rsi)

    def calculate_atr(
        self,
        df: pd.DataFrame,
        period: Optional[int] = None,
    ) -> float:
        """
        Calculate the Average True Range.

        True Range = max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close)
        )

        Args:
            df: DataFrame with 'high', 'low', 'close' columns
            period: ATR period (default: self.atr_period)

        Returns:
            Current ATR value
        """
        period = period or self.atr_period

        if len(df) < period + 1:
            return 0.0

        high = df["high"]
        low = df["low"]
        close = df["close"]

        # Calculate True Range components
        high_low = high - low
        high_close = (high - close.shift()).abs()
        low_close = (low - close.shift()).abs()

        # True Range is the max of the three
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)

        # ATR is the exponential moving average of True Range
        atr = true_range.ewm(alpha=1/period, adjust=False).mean()

        return float(atr.iloc[-1])

    def calculate_chandelier_exit(
        self,
        df: pd.DataFrame,
        atr: Optional[float] = None,
        lookback: int = 22,
        multiplier: Optional[float] = None,
    ) -> float:
        """
        Calculate the Chandelier Exit (long).

        Chandelier Exit = Highest High - (ATR * Multiplier)

        Args:
            df: DataFrame with OHLC data
            atr: Pre-calculated ATR (will calculate if None)
            lookback: Period for highest high
            multiplier: ATR multiplier (default: self.chandelier_multiplier)

        Returns:
            Chandelier Exit price
        """
        if atr is None:
            atr = self.calculate_atr(df)

        multiplier = multiplier or self.chandelier_multiplier

        # Get highest high in lookback period
        if len(df) >= lookback:
            highest_high = float(df["high"].iloc[-lookback:].max())
        else:
            highest_high = float(df["high"].max())

        return highest_high - (atr * multiplier)

    def calculate_sma(
        self,
        prices: pd.Series,
        period: int,
    ) -> Optional[float]:
        """
        Calculate Simple Moving Average.

        Args:
            prices: Series of prices
            period: SMA period

        Returns:
            Current SMA value or None if insufficient data
        """
        if len(prices) < period:
            return None

        return float(prices.iloc[-period:].mean())

    def calculate_bollinger_bands(
        self,
        prices: pd.Series,
        period: int = 20,
        stddev: float = 2.0,
    ) -> tuple[Optional[float], Optional[float], Optional[float]]:
        """
        Calculate Bollinger Bands.

        Args:
            prices: Series of prices
            period: Rolling window
            stddev: Standard deviation multiplier

        Returns:
            (lower, middle, upper) tuple or (None, None, None) if insufficient data.
        """
        if len(prices) < period:
            return None, None, None

        window = prices.iloc[-period:]
        middle = float(window.mean())
        std = float(window.std(ddof=0))
        upper = middle + (stddev * std)
        lower = middle - (stddev * std)
        return lower, middle, upper

    def calculate_macd(
        self,
        prices: pd.Series,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> tuple[Optional[pd.Series], Optional[pd.Series]]:
        """
        Calculate MACD and signal line series.

        Args:
            prices: Series of prices
            fast: Fast EMA period
            slow: Slow EMA period
            signal: Signal EMA period

        Returns:
            (macd_series, signal_series) or (None, None) if insufficient data.
        """
        if len(prices) < slow + signal:
            return None, None

        ema_fast = prices.ewm(span=fast, adjust=False).mean()
        ema_slow = prices.ewm(span=slow, adjust=False).mean()
        macd = ema_fast - ema_slow
        signal_line = macd.ewm(span=signal, adjust=False).mean()
        return macd, signal_line

    def is_oversold(self, rsi: float) -> bool:
        """Check if RSI indicates oversold condition."""
        return rsi < 30

    def is_overbought(self, rsi: float) -> bool:
        """Check if RSI indicates overbought condition."""
        return rsi > 70

    def is_below_chandelier(
        self,
        current_price: float,
        chandelier_exit: float,
    ) -> bool:
        """Check if price is below Chandelier Exit (sell signal)."""
        return current_price < chandelier_exit

    def get_price_vs_sma(
        self,
        current_price: float,
        sma: Optional[float],
    ) -> Optional[float]:
        """
        Calculate percentage of price relative to SMA.

        Args:
            current_price: Current stock price
            sma: SMA value

        Returns:
            Percentage above/below SMA, or None if SMA unavailable
        """
        if sma is None or sma == 0:
            return None

        return ((current_price - sma) / sma) * 100
