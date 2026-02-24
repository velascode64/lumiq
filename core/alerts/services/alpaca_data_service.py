"""
Alpaca Data Service for fetching stock data.

Uses alpaca-py StockHistoricalDataClient for market data.
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
from alpaca.data.requests import (
    StockBarsRequest,
    StockLatestTradeRequest,
    CryptoBarsRequest,
    CryptoLatestTradeRequest,
)
from alpaca.data.timeframe import TimeFrame

from ..models.schemas import StockData

logger = logging.getLogger(__name__)


class AlpacaDataService:
    """Service for fetching stock data from Alpaca."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
    ):
        """
        Initialize the Alpaca data service.

        Args:
            api_key: Alpaca API key (defaults to ALPACA_API_KEY env var)
            secret_key: Alpaca secret key (defaults to ALPACA_SECRET_KEY env var)
        """
        self.api_key = api_key or os.getenv("ALPACA_API_KEY", "")
        self.secret_key = secret_key or os.getenv("ALPACA_SECRET_KEY", "") or os.getenv("ALPACA_API_SECRET", "")

        if not self.api_key or not self.secret_key:
            raise ValueError("Alpaca API credentials required. Set ALPACA_API_KEY and ALPACA_SECRET_KEY.")

        self.client = StockHistoricalDataClient(
            api_key=self.api_key,
            secret_key=self.secret_key,
        )
        self.crypto_client = CryptoHistoricalDataClient(
            api_key=self.api_key,
            secret_key=self.secret_key,
        )

    def _is_crypto_symbol(self, symbol: str) -> bool:
        return "/" in symbol or "-" in symbol or symbol.upper().endswith("USD")

    def _normalize_crypto_symbol(self, symbol: str) -> str:
        sym = symbol.upper().replace("-", "/")
        if "/" in sym:
            return sym
        # Convert ETHUSD -> ETH/USD (default USD quote)
        if sym.endswith("USD") and len(sym) > 3:
            return f"{sym[:-3]}/USD"
        return sym

    def get_stock_bars(
        self,
        symbol: str,
        days: int = 90,
        timeframe: TimeFrame = TimeFrame.Day,
    ) -> Optional[pd.DataFrame]:
        """
        Get historical bars for a symbol.

        Args:
            symbol: Stock symbol (e.g., "AAPL")
            days: Number of days of history
            timeframe: Bar timeframe (default: Day)

        Returns:
            DataFrame with OHLCV data, or None on error
        """
        try:
            start_date = datetime.now() - timedelta(days=days)

            symbol_key = symbol
            if self._is_crypto_symbol(symbol):
                crypto_symbol = self._normalize_crypto_symbol(symbol)
                symbol_key = crypto_symbol
                request = CryptoBarsRequest(
                    symbol_or_symbols=crypto_symbol,
                    timeframe=timeframe,
                    start=start_date,
                )
                bars = self.crypto_client.get_crypto_bars(request)
            else:
                request = StockBarsRequest(
                    symbol_or_symbols=symbol,
                    timeframe=timeframe,
                    start=start_date,
                )
                bars = self.client.get_stock_bars(request)
            df = bars.df

            if df.empty:
                logger.warning(f"No bars returned for {symbol}")
                return None

            # Reset index to make symbol a column if multi-index
            if isinstance(df.index, pd.MultiIndex):
                df = df.reset_index()
                df = df[df["symbol"] == symbol_key].copy()
                df = df.set_index("timestamp")

            return df

        except Exception as e:
            logger.error(f"Failed to get bars for {symbol}: {e}")
            return None

    def get_latest_price(self, symbol: str) -> Optional[float]:
        """
        Get the latest trade price for a symbol.

        Args:
            symbol: Stock symbol

        Returns:
            Latest price or None on error
        """
        try:
            if self._is_crypto_symbol(symbol):
                crypto_symbol = self._normalize_crypto_symbol(symbol)
                request = CryptoLatestTradeRequest(symbol_or_symbols=crypto_symbol)
                trades = self.crypto_client.get_crypto_latest_trade(request)
                if crypto_symbol in trades:
                    return float(trades[crypto_symbol].price)
            else:
                request = StockLatestTradeRequest(symbol_or_symbols=symbol)
                trades = self.client.get_stock_latest_trade(request)
                if symbol in trades:
                    return float(trades[symbol].price)
            return None

        except Exception as e:
            logger.error(f"Failed to get latest price for {symbol}: {e}")
            return None

    def get_multiple_stocks(
        self,
        symbols: List[str],
        days: int = 90,
    ) -> Dict[str, pd.DataFrame]:
        """
        Get historical data for multiple symbols.

        Args:
            symbols: List of stock symbols
            days: Number of days of history

        Returns:
            Dict mapping symbol to DataFrame
        """
        result = {}

        try:
            start_date = datetime.now() - timedelta(days=days)

            request = StockBarsRequest(
                symbol_or_symbols=symbols,
                timeframe=TimeFrame.Day,
                start=start_date,
            )

            bars = self.client.get_stock_bars(request)
            df = bars.df

            if df.empty:
                logger.warning("No bars returned for any symbols")
                return result

            # Split by symbol
            if isinstance(df.index, pd.MultiIndex):
                df = df.reset_index()
                for symbol in symbols:
                    symbol_df = df[df["symbol"] == symbol].copy()
                    if not symbol_df.empty:
                        symbol_df = symbol_df.set_index("timestamp")
                        result[symbol] = symbol_df

        except Exception as e:
            logger.error(f"Failed to get multiple stocks: {e}")

        return result

    def get_stock_data(self, symbol: str, days: int = 252) -> Optional[StockData]:
        """
        Get comprehensive stock data for analysis.

        Args:
            symbol: Stock symbol
            days: Days of history (default 252 = ~1 year)

        Returns:
            StockData object or None on error
        """
        try:
            # Get historical bars
            bars = self.get_stock_bars(symbol, days=days)
            if bars is None or bars.empty:
                return None

            # Get latest price
            current_price = self.get_latest_price(symbol)
            if current_price is None:
                current_price = float(bars["close"].iloc[-1])

            # Calculate metrics
            previous_close = float(bars["close"].iloc[-2]) if len(bars) > 1 else current_price
            high_52w = float(bars["high"].max())
            low_52w = float(bars["low"].min())
            volume = float(bars["volume"].iloc[-1])
            avg_volume = float(bars["volume"].mean())

            return StockData(
                symbol=symbol,
                current_price=current_price,
                previous_close=previous_close,
                high_52w=high_52w,
                low_52w=low_52w,
                volume=volume,
                avg_volume=avg_volume,
                bars=bars,
            )

        except Exception as e:
            logger.error(f"Failed to get stock data for {symbol}: {e}")
            return None

    def load_watchlist(self, filepath: str) -> List[str]:
        """
        Load symbols from a CSV watchlist file.

        Args:
            filepath: Path to CSV file with 'symbol' or 'ticker' column

        Returns:
            List of symbols
        """
        try:
            df = pd.read_csv(filepath)

            # Try different column names
            for col in ["symbol", "ticker", "Symbol", "Ticker"]:
                if col in df.columns:
                    return df[col].dropna().str.strip().str.upper().tolist()

            # If no named column, use first column
            return df.iloc[:, 0].dropna().str.strip().str.upper().tolist()

        except Exception as e:
            logger.error(f"Failed to load watchlist from {filepath}: {e}")
            return []
