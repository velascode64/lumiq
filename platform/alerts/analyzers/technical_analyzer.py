"""
Technical Analysis Calculator.

Calculates technical indicators using the `ta` library.
"""

import logging
from typing import Any, Dict, Optional

import pandas as pd

from ..models.schemas import TechnicalIndicators, StockData

logger = logging.getLogger(__name__)


def _ta_modules() -> Dict[str, Any]:
    try:
        from ta.momentum import (
            RSIIndicator,
            StochasticOscillator,
            WilliamsRIndicator,
            ROCIndicator,
            TSIIndicator,
            UltimateOscillator,
        )
        from ta.trend import (
            MACD,
            SMAIndicator,
            EMAIndicator,
            ADXIndicator,
            CCIIndicator,
            AroonIndicator,
        )
        from ta.volatility import (
            AverageTrueRange,
            BollingerBands,
            DonchianChannel,
            KeltnerChannel,
        )
        from ta.volume import (
            OnBalanceVolumeIndicator,
            ChaikinMoneyFlowIndicator,
            MFIIndicator,
        )
    except Exception as exc:  # pragma: no cover - dependency installed at runtime
        raise RuntimeError(
            "The `ta` library is required for technical analysis. "
            "Install project dependencies from `lumiq/requirements.txt`."
        ) from exc

    return {
        "RSIIndicator": RSIIndicator,
        "StochasticOscillator": StochasticOscillator,
        "WilliamsRIndicator": WilliamsRIndicator,
        "ROCIndicator": ROCIndicator,
        "TSIIndicator": TSIIndicator,
        "UltimateOscillator": UltimateOscillator,
        "MACD": MACD,
        "SMAIndicator": SMAIndicator,
        "EMAIndicator": EMAIndicator,
        "ADXIndicator": ADXIndicator,
        "CCIIndicator": CCIIndicator,
        "AroonIndicator": AroonIndicator,
        "AverageTrueRange": AverageTrueRange,
        "BollingerBands": BollingerBands,
        "DonchianChannel": DonchianChannel,
        "KeltnerChannel": KeltnerChannel,
        "OnBalanceVolumeIndicator": OnBalanceVolumeIndicator,
        "ChaikinMoneyFlowIndicator": ChaikinMoneyFlowIndicator,
        "MFIIndicator": MFIIndicator,
    }


def _last_valid(series: pd.Series) -> Optional[float]:
    if series is None:
        return None
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return None
    return float(clean.iloc[-1])


class TechnicalAnalyzer:
    """Calculates technical indicators for stocks using `ta`."""

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
            return 50.0

        mods = _ta_modules()
        indicator = mods["RSIIndicator"](close=prices.astype(float), window=int(period))
        value = _last_valid(indicator.rsi())
        return 50.0 if value is None else float(value)

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

        mods = _ta_modules()
        indicator = mods["AverageTrueRange"](
            high=df["high"].astype(float),
            low=df["low"].astype(float),
            close=df["close"].astype(float),
            window=int(period),
        )
        value = _last_valid(indicator.average_true_range())
        return 0.0 if value is None else float(value)

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
        mods = _ta_modules()
        indicator = mods["SMAIndicator"](close=prices.astype(float), window=int(period))
        return _last_valid(indicator.sma_indicator())

    def calculate_ema(
        self,
        prices: pd.Series,
        period: int,
    ) -> Optional[float]:
        if len(prices) < period:
            return None
        mods = _ta_modules()
        indicator = mods["EMAIndicator"](close=prices.astype(float), window=int(period))
        return _last_valid(indicator.ema_indicator())

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
        mods = _ta_modules()
        indicator = mods["BollingerBands"](
            close=prices.astype(float),
            window=int(period),
            window_dev=float(stddev),
        )
        return (
            _last_valid(indicator.bollinger_lband()),
            _last_valid(indicator.bollinger_mavg()),
            _last_valid(indicator.bollinger_hband()),
        )

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

        mods = _ta_modules()
        indicator = mods["MACD"](
            close=prices.astype(float),
            window_fast=int(fast),
            window_slow=int(slow),
            window_sign=int(signal),
        )
        return indicator.macd(), indicator.macd_signal()

    def calculate_indicator_series(
        self,
        df: pd.DataFrame,
        indicator: str,
        **params: Any,
    ) -> pd.Series:
        mods = _ta_modules()
        name = (indicator or "").strip().lower()
        close = df["close"].astype(float)
        high = df["high"].astype(float) if "high" in df.columns else close
        low = df["low"].astype(float) if "low" in df.columns else close
        volume = df["volume"].astype(float) if "volume" in df.columns else pd.Series([0.0] * len(df), index=df.index)

        if name == "rsi":
            return mods["RSIIndicator"](close=close, window=int(params.get("window", 14))).rsi()
        if name == "stoch_k":
            return mods["StochasticOscillator"](
                high=high,
                low=low,
                close=close,
                window=int(params.get("window", 14)),
                smooth_window=int(params.get("smooth_window", 3)),
            ).stoch()
        if name == "stoch_d":
            return mods["StochasticOscillator"](
                high=high,
                low=low,
                close=close,
                window=int(params.get("window", 14)),
                smooth_window=int(params.get("smooth_window", 3)),
            ).stoch_signal()
        if name == "williams_r":
            return mods["WilliamsRIndicator"](high=high, low=low, close=close, lbp=int(params.get("window", 14))).williams_r()
        if name == "roc":
            return mods["ROCIndicator"](close=close, window=int(params.get("window", 12))).roc()
        if name == "tsi":
            return mods["TSIIndicator"](
                close=close,
                window_slow=int(params.get("window_slow", 25)),
                window_fast=int(params.get("window_fast", 13)),
            ).tsi()
        if name == "ultimate_oscillator":
            return mods["UltimateOscillator"](
                high=high,
                low=low,
                close=close,
                window1=int(params.get("window1", 7)),
                window2=int(params.get("window2", 14)),
                window3=int(params.get("window3", 28)),
            ).ultimate_oscillator()
        if name == "macd":
            return mods["MACD"](
                close=close,
                window_fast=int(params.get("window_fast", 12)),
                window_slow=int(params.get("window_slow", 26)),
                window_sign=int(params.get("window_sign", 9)),
            ).macd()
        if name == "macd_signal":
            return mods["MACD"](
                close=close,
                window_fast=int(params.get("window_fast", 12)),
                window_slow=int(params.get("window_slow", 26)),
                window_sign=int(params.get("window_sign", 9)),
            ).macd_signal()
        if name == "macd_diff":
            return mods["MACD"](
                close=close,
                window_fast=int(params.get("window_fast", 12)),
                window_slow=int(params.get("window_slow", 26)),
                window_sign=int(params.get("window_sign", 9)),
            ).macd_diff()
        if name == "sma":
            return mods["SMAIndicator"](close=close, window=int(params.get("window", 20))).sma_indicator()
        if name == "ema":
            return mods["EMAIndicator"](close=close, window=int(params.get("window", 20))).ema_indicator()
        if name == "atr":
            return mods["AverageTrueRange"](
                high=high,
                low=low,
                close=close,
                window=int(params.get("window", 14)),
            ).average_true_range()
        if name == "adx":
            return mods["ADXIndicator"](high=high, low=low, close=close, window=int(params.get("window", 14))).adx()
        if name == "adx_pos":
            return mods["ADXIndicator"](high=high, low=low, close=close, window=int(params.get("window", 14))).adx_pos()
        if name == "adx_neg":
            return mods["ADXIndicator"](high=high, low=low, close=close, window=int(params.get("window", 14))).adx_neg()
        if name == "cci":
            return mods["CCIIndicator"](
                high=high,
                low=low,
                close=close,
                window=int(params.get("window", 20)),
                constant=float(params.get("constant", 0.015)),
            ).cci()
        if name == "aroon_up":
            return mods["AroonIndicator"](close=close, window=int(params.get("window", 25))).aroon_up()
        if name == "aroon_down":
            return mods["AroonIndicator"](close=close, window=int(params.get("window", 25))).aroon_down()
        if name == "bollinger_upper":
            return mods["BollingerBands"](
                close=close,
                window=int(params.get("window", 20)),
                window_dev=float(params.get("window_dev", 2.0)),
            ).bollinger_hband()
        if name == "bollinger_lower":
            return mods["BollingerBands"](
                close=close,
                window=int(params.get("window", 20)),
                window_dev=float(params.get("window_dev", 2.0)),
            ).bollinger_lband()
        if name == "bollinger_mid":
            return mods["BollingerBands"](
                close=close,
                window=int(params.get("window", 20)),
                window_dev=float(params.get("window_dev", 2.0)),
            ).bollinger_mavg()
        if name == "bollinger_width":
            return mods["BollingerBands"](
                close=close,
                window=int(params.get("window", 20)),
                window_dev=float(params.get("window_dev", 2.0)),
            ).bollinger_wband()
        if name == "bollinger_percent":
            return mods["BollingerBands"](
                close=close,
                window=int(params.get("window", 20)),
                window_dev=float(params.get("window_dev", 2.0)),
            ).bollinger_pband()
        if name == "donchian_upper":
            return mods["DonchianChannel"](
                high=high,
                low=low,
                close=close,
                window=int(params.get("window", 20)),
                offset=int(params.get("offset", 0)),
            ).donchian_channel_hband()
        if name == "donchian_lower":
            return mods["DonchianChannel"](
                high=high,
                low=low,
                close=close,
                window=int(params.get("window", 20)),
                offset=int(params.get("offset", 0)),
            ).donchian_channel_lband()
        if name == "donchian_mid":
            return mods["DonchianChannel"](
                high=high,
                low=low,
                close=close,
                window=int(params.get("window", 20)),
                offset=int(params.get("offset", 0)),
            ).donchian_channel_mband()
        if name == "keltner_upper":
            return mods["KeltnerChannel"](
                high=high,
                low=low,
                close=close,
                window=int(params.get("window", 20)),
                window_atr=int(params.get("window_atr", 10)),
                multiplier=float(params.get("multiplier", 2.0)),
            ).keltner_channel_hband()
        if name == "keltner_lower":
            return mods["KeltnerChannel"](
                high=high,
                low=low,
                close=close,
                window=int(params.get("window", 20)),
                window_atr=int(params.get("window_atr", 10)),
                multiplier=float(params.get("multiplier", 2.0)),
            ).keltner_channel_lband()
        if name == "keltner_mid":
            return mods["KeltnerChannel"](
                high=high,
                low=low,
                close=close,
                window=int(params.get("window", 20)),
                window_atr=int(params.get("window_atr", 10)),
                multiplier=float(params.get("multiplier", 2.0)),
            ).keltner_channel_mband()
        if name == "obv":
            return mods["OnBalanceVolumeIndicator"](close=close, volume=volume).on_balance_volume()
        if name == "cmf":
            return mods["ChaikinMoneyFlowIndicator"](
                high=high,
                low=low,
                close=close,
                volume=volume,
                window=int(params.get("window", 20)),
            ).chaikin_money_flow()
        if name == "mfi":
            return mods["MFIIndicator"](
                high=high,
                low=low,
                close=close,
                volume=volume,
                window=int(params.get("window", 14)),
            ).money_flow_index()
        raise ValueError(f"Unsupported indicator: {indicator}")

    def calculate_indicator_snapshot(
        self,
        df: pd.DataFrame,
        indicator: str,
        **params: Any,
    ) -> Dict[str, Any]:
        series = self.calculate_indicator_series(df, indicator, **params)
        clean = pd.to_numeric(series, errors="coerce").dropna()
        if clean.empty:
            return {
                "indicator": (indicator or "").strip().lower(),
                "value": None,
                "previous": None,
                "delta": None,
                "bars_with_values": 0,
            }
        current = float(clean.iloc[-1])
        previous = float(clean.iloc[-2]) if len(clean) >= 2 else None
        delta = (current - previous) if previous is not None else None
        return {
            "indicator": (indicator or "").strip().lower(),
            "value": current,
            "previous": previous,
            "delta": delta,
            "bars_with_values": int(len(clean)),
        }

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
