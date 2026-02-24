from lumibot.strategies import Strategy
from lumibot.entities import Asset
from datetime import datetime, timedelta
from collections import deque
import numpy as np
try:
    import pandas as pd  # not used now, but keep for future extensions
except ImportError:
    pd = None


class ETH10MinHighLowMidStrategy(Strategy):
    """
    Estrategia basada en máximos y mínimos en una ventana de 10 minutos.

    Regla simple (modo 1M):
    - Construye una ventana deslizante de los últimos 10 minutos de precios (1 dato por iteración).
    - Calcula Máximo (H), Mínimo (L) y el punto medio M = (H + L)/2.
    - Si NO hay posición y el precio actual cae hasta el punto medio (precio <= M) → COMPRAR.
    - Si HAY posición, vender "solo si" hay una ganancia considerable dentro de los siguientes 10 minutos
      desde la entrada. "Ganancia considerable" se parametriza como `profit_target_pct` (por defecto 1%).
    - Si pasan 10 minutos desde la entrada y no se alcanzó el objetivo → CERRAR la posición (time‑exit)
      y volver a esperar.

    Notas:
    - Itera cada 1 minuto (`sleeptime = "1M"`).
    - Opera 24/7 (Crypto en Alpaca).
    - Mantiene gestión de riesgo mínima con `stop_loss_pct` opcional.
    """

    def initialize(self):
        # Forzar trading 24/7 (Crypto)
        self.market_hours = None
        if hasattr(self, 'broker') and self.broker:
            self.broker.market = "24/7"
            self.log_message("🌍 Broker market set to '24/7' - ENABLING 24/7 crypto trading!")

        # Configuración de timeframe
        self.sleeptime = "1M"  # 1 minuto por iteración

        # Activo
        self.eth_symbol = "ETH"
        self.display_symbol = "ETH/USD"

        # Parámetros principales
        self.window_minutes = int(self.parameters.get('window_minutes', 3))  # Ventana H/L
        self.profit_target_pct = float(self.parameters.get('profit_target_pct', 0.01))  # 1%
        self.stop_loss_pct = float(self.parameters.get('stop_loss_pct', 0.005))  # 0.5% opcional
        self.position_size = float(self.parameters.get('position_size', 0.05))  # 5% del portafolio

        # Control de trades
        self.max_trades_per_day = int(self.parameters.get('max_trades_per_day', 50))
        self.trades_today = 0
        self.last_check_date = datetime.now().date()

        # Estado
        self.price_window = deque(maxlen=self.window_minutes)  # 10 valores (1 por minuto)
        self.entry_time = None
        self.entry_price = None

        self.trades_executed = 0

        self.log_message("=" * 60)
        self.log_message("ETH 10MIN HIGH/LOW MIDPOINT STRATEGY - 24/7")
        self.log_message("=" * 60)
        self.log_message(f"Symbol: {self.display_symbol} (Asset: {self.eth_symbol})")
        self.log_message(
            f"Window: {self.window_minutes} min | Target: {self.profit_target_pct*100:.2f}% | SL: {self.stop_loss_pct*100:.2f}%")
        self.log_message(f"Position size: {self.position_size*100:.1f}% of portfolio")
        self.log_message(f"Max trades/day: {self.max_trades_per_day}")
        self.log_message("=" * 60)

    def is_market_open(self):
        return True

    def should_continue_trading(self):
        return True

    def _get_current_price(self):
        """Obtiene precio actual de ETH/USD, con fallback simulado en caso de fallo."""
        eth_asset = Asset(symbol="ETH", asset_type="crypto")
        usd_quote = Asset(symbol="USD", asset_type="forex")
        quote = None
        try:
            quote = self.get_quote(eth_asset, quote=usd_quote)
            current_price = None
            if quote and hasattr(quote, 'last') and quote.last:
                current_price = float(quote.last)
            elif quote and hasattr(quote, 'price') and quote.price:
                current_price = float(quote.price)
            elif quote and hasattr(quote, 'close') and quote.close:
                current_price = float(quote.close)
            if current_price:
                self.log_message(f"📊 Real ETH price obtained: ${current_price:.2f}")
                return current_price
        except Exception as e:
            self.log_message(f"⚠️ Error getting ETH price: {str(e)}")

        # Fallback simulado
        import random
        base_price = 2600
        price_variation = random.uniform(-0.02, 0.02)
        simulated = base_price * (1 + price_variation)
        self.log_message(f"📊 Using simulated ETH price: ${simulated:.2f} (real quote unavailable)")
        return simulated

    def _calc_window_stats(self):
        """Devuelve (high, low, mid, mean) de la ventana actual si hay suficientes datos."""
        if len(self.price_window) < max(2, self.window_minutes):
            return None
        window = list(self.price_window)
        high = max(window)
        low = min(window)
        mid = (high + low) / 2.0  # punto medio H/L
        mean = float(np.mean(window))
        return high, low, mid, mean

    def _has_position(self):
        eth_asset = Asset(symbol=self.eth_symbol, asset_type="crypto")
        position = self.get_position(eth_asset)
        return position if (position and position.quantity > 0) else None

    def _execute_buy(self, price):
        eth_asset = Asset(symbol=self.eth_symbol, asset_type="crypto")
        position_value = self.portfolio_value * self.position_size
        quantity = position_value / price

        self.log_message("=" * 40)
        self.log_message("🟢 BUY SIGNAL")
        self.log_message(f"   Price: ${price:.2f}")
        self.log_message(f"   Quantity: {quantity:.6f} ETH | Value: ${position_value:.2f}")
        self.log_message(
            f"   Profit Target: {self.profit_target_pct*100:.2f}% | Stop Loss: {self.stop_loss_pct*100:.2f}%")
        self.log_message("=" * 40)

        order = self.create_order(asset=eth_asset, quantity=quantity, side="buy")
        self.submit_order(order)
        self.trades_today += 1
        self.trades_executed += 1
        self.entry_time = datetime.now()
        self.entry_price = price

    def _execute_sell(self, position, price, reason):
        self.log_message("=" * 40)
        self.log_message("🔴 SELL SIGNAL")
        self.log_message(f"   Reason: {reason}")
        self.log_message(f"   Quantity: {position.quantity:.6f} ETH | Price: ${price:.2f}")
        self.log_message("=" * 40)

        order = self.create_order(asset=position.asset, quantity=position.quantity, side="sell")
        self.submit_order(order)
        self.trades_today += 1
        self.trades_executed += 1
        # Resetear estado de entrada
        self.entry_time = None
        self.entry_price = None

    def on_trading_iteration(self):
        try:
            now = datetime.now()
            # reset diario
            if now.date() != self.last_check_date:
                self.trades_today = 0
                self.last_check_date = now.date()
                self.log_message("🔄 New day - reset trades counter")

            price = self._get_current_price()
            self.price_window.append(price)
            self.log_message(f"💰 ETH Price: ${price:.2f}")

            stats = self._calc_window_stats()
            if not stats:
                needed = self.window_minutes - len(self.price_window)
                self.log_message(f"📊 Building 10m window... need {max(0, needed)} more samples")
                
                # Log structured HOLD signal during window construction
                reason = f"Construyendo ventana de datos ({len(self.price_window)}/{self.window_minutes} muestras)"
                indicators_dict = {
                    'symbol': self.display_symbol,
                    'samples_collected': len(self.price_window),
                    'samples_needed': self.window_minutes,
                    'progress': float(len(self.price_window) / self.window_minutes),
                    'signal_strength': 0.0
                }
                
                self.log_message(
                    f"[SIGNAL] action=HOLD reason='{reason}' price={price:.2f} "
                    f"indicators={indicators_dict}"
                )
                return

            high, low, mid, mean = stats
            self.log_message(f"📈 Window H/L/Mid/Mean: {high:.2f} / {low:.2f} / {mid:.2f} / {mean:.2f}")

            position = self._has_position()

            # --- Lógica de ENTRADA ---
            if not position:
                # Compra cuando el precio cae al punto medio de la ventana de 10 min
                if price <= mid:
                    # Log structured signal for UI
                    reason = f"Precio alcanzó punto medio H/L ({mid:.2f})"
                    indicators_dict = {
                        'symbol': self.display_symbol,
                        'high': float(high),
                        'low': float(low),
                        'mid': float(mid),
                        'mean': float(mean),
                        'signal_strength': float(abs(price - mid))
                    }
                    
                    self.log_message(
                        f"[SIGNAL] action=BUY reason='{reason}' price={price:.2f} "
                        f"indicators={indicators_dict}"
                    )
                    
                    self._execute_buy(price)
                else:
                    # Log HOLD signal
                    reason = f"Esperando precio <= punto medio ({mid:.2f})"
                    indicators_dict = {
                        'symbol': self.display_symbol,
                        'high': float(high),
                        'low': float(low),
                        'mid': float(mid),
                        'mean': float(mean),
                        'signal_strength': float(abs(price - mid))
                    }
                    
                    self.log_message(
                        f"[SIGNAL] action=HOLD reason='{reason}' price={price:.2f} "
                        f"indicators={indicators_dict}"
                    )
                return

            # --- Gestión de la posición (SALIDA) ---
            # Solo vender si hay una ganancia considerable dentro de los siguientes 10 minutos
            assert self.entry_time is not None and self.entry_price is not None
            elapsed = now - self.entry_time
            pnl_pct = (price - self.entry_price) / self.entry_price
            target_hit = pnl_pct >= self.profit_target_pct
            stop_hit = (-pnl_pct) >= self.stop_loss_pct if self.stop_loss_pct > 0 else False

            self.log_message(f"📊 Position status: P&L {pnl_pct*100:.2f}% | Elapsed {elapsed}")

            # Preparar indicadores para señales
            indicators_dict = {
                'symbol': self.display_symbol,
                'high': float(high),
                'low': float(low),
                'mid': float(mid),
                'mean': float(mean),
                'pnl_pct': float(pnl_pct),
                'elapsed_minutes': float(elapsed.total_seconds() / 60),
                'signal_strength': float(abs(pnl_pct))
            }

            if target_hit and elapsed <= timedelta(minutes=self.window_minutes):
                reason = f"Take profit {pnl_pct*100:.2f}% en {elapsed.total_seconds()/60:.1f}min"
                self.log_message(
                    f"[SIGNAL] action=SELL reason='{reason}' price={price:.2f} "
                    f"indicators={indicators_dict}"
                )
                self._execute_sell(position, price, reason=f"Target hit {pnl_pct*100:.2f}% within {self.window_minutes}m")
                return

            if stop_hit:
                reason = f"Stop loss {pnl_pct*100:.2f}%"
                self.log_message(
                    f"[SIGNAL] action=SELL reason='{reason}' price={price:.2f} "
                    f"indicators={indicators_dict}"
                )
                self._execute_sell(position, price, reason=f"Stop loss hit {pnl_pct*100:.2f}%")
                return

            # Si pasan 10 minutos y NO se alcanzó el objetivo, cerrar y esperar
            if elapsed >= timedelta(minutes=self.window_minutes):
                reason = f"Time exit {elapsed.total_seconds()/60:.1f}min (target no alcanzado)"
                self.log_message(
                    f"[SIGNAL] action=SELL reason='{reason}' price={price:.2f} "
                    f"indicators={indicators_dict}"
                )
                self._execute_sell(position, price, reason=f"Time exit after {self.window_minutes}m (target not reached)")
                return

            # Si no hay condiciones de salida, mantener
            reason = f"En posición P&L: {pnl_pct*100:.2f}% ({elapsed.total_seconds()/60:.1f}min)"
            self.log_message(
                f"[SIGNAL] action=HOLD reason='{reason}' price={price:.2f} "
                f"indicators={indicators_dict}"
            )

        except Exception as e:
            self.log_message(f"❌ Error in trading iteration: {str(e)}", color="red")

    def on_filled_order(self, position, order, price, quantity, multiplier=None):
        side = order.side.upper()
        symbol = order.asset.symbol
        value = float(quantity) * float(price)
        self.log_message("\n" + "🎉" * 30)
        self.log_message("ORDER FILLED!")
        self.log_message(f"  {side}: {quantity:.6f} {symbol}")
        self.log_message(f"  Price: ${price:.2f}")
        self.log_message(f"  Value: ${value:,.2f}")
        self.log_message("🎉" * 30 + "\n")

    def on_strategy_end(self):
        self.log_message("🏁 Strategy ending - closing all positions")
        eth_asset = Asset(symbol=self.eth_symbol, asset_type="crypto")
        position = self.get_position(eth_asset)
        if position and position.quantity > 0:
            try:
                order = self.create_order(asset=position.asset, quantity=position.quantity, side="sell")
                self.submit_order(order)
                self.log_message(f"📤 Closing position: {position.quantity:.6f} ETH")
            except Exception as e:
                self.log_message(f"❌ Error closing position: {str(e)}", color="red")
