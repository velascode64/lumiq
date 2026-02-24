import datetime as dt
import pytz
import numpy as np
import yfinance as yf
from lumibot.credentials import ALPACA_TEST_CONFIG
from lumibot.strategies.strategy import Strategy

"""
Strategy Description: Carlos Mean Reversion Strategy

Estrategia optimizada de Mean Reversion con Momentum Trading adaptada de Backtrader a Lumibot.
Combina análisis técnico avanzado con gestión de riesgo inteligente y take profits escalonados.

Características principales:
- Salidas inteligentes: Vende en ganancia diaria >5% o máximos 52 semanas
- Take profits escalonados: 15%, 30%, 50%
- Trailing stop dinámico
- Filtros técnicos: RSI, MACD, volumen, Bollinger Bands
- Parámetros específicos por símbolo
- Integración con yfinance para datos 52 semanas
"""


class CarlosMeanReversionStrategy(Strategy):
    parameters = {
        # Universe
        "symbols": ["QQQ", "NVDA", "MSFT", "META", "NFLX", "TSLA"],
        "symbol": "QQQ",

        # === Trend filter (only long in uptrends) ===
        "trade_only_above_ma": True,
        "trend_ma_period": 200,

        # === Breakout logic (52w high confirmation) ===
        "use_breakout_confirmation": True,
        "breakout_confirm_days": 3,          # number of closes above prior 52w high
        "breakout_buffer_pct": 0.005,        # +0.5% above 52w high to avoid whipsaw

        # === Buy-the-dip (less aggressive) ===
        "buy_on_dip_enabled": True,
        "dip_min_pct": 0.02,                  # 2% from 20d high
        "dip_max_pct": 0.08,                  # up to 8% from 20d high
        "rsi_buy_threshold": 50,              # require RSI < 50 on dips
        "volume_spike_on_dip": 1.10,          # 10% above 20d avg volume

        # === Position sizing by volatility (risk budgeting) ===
        "position_sizing": "volatility",     # options: fixed | dynamic | volatility
        "risk_per_trade_pct": 0.0075,         # risk 0.75% of equity per entry
        "max_position_pct": 0.95,
        "max_positions": 1,
        "pyramid_on_dip": True,               # add only if move in favor
        "pyramid_add_atr_steps": 1.0,         # add every +1 ATR from avg price
        "pyramid_max_adds": 2,

        # === Profit taking & trailing ===
        "dynamic_tp_enabled": True,
        "min_profit_target": 0.12,            # start scaling from +12%
        "scale_out_levels": [0.25, 0.40],     # take ~33% at 25% and 40%
        "atr_trailing_stop": True,
        "atr_multiplier": 3.0,                # chandelier: HH - 3*ATR
        "min_trailing_stop": 0.05,            # 5% floor (avoid 2% whipsaws)

        # === Initial stop (failure protection) ===
        "use_atr_initial_stop": True,
        "initial_atr_mult": 2.5,              # initial stop = entry - 2.5*ATR
        "min_stop_pct": 0.03,                 # but never tighter than 3%

        # === Cooldowns ===
        "cooldown_days": 0,                    # between winners
        "cooldown_days_after_stop": 3,         # after a stop-out to avoid churn

        # === Misc ===
        "rsi_oversold": 40,                   # oversold threshold for non-dip entries
        "rsi_overbought": 85,
        "paper_trade_qty": 100,
    }

    # Parámetros específicos por símbolo optimizados
    SYMBOL_PARAMS = {
        'QQQ': {
            'rsi_oversold': 30,
            'min_trailing_stop': 0.015,
        },
        'TSLA': {
            'rsi_oversold': 30,
            'min_trailing_stop': 0.03,
        },
        'COIN': {
            'rsi_oversold': 25,
            'min_trailing_stop': 0.03,
        }, 
        'GLD': {
            'rsi_oversold': 30,
            'min_trailing_stop': 0.015,
        },
        'SPY': {
            'rsi_oversold': 30,
            'min_trailing_stop': 0.015,
        },
    }

    def initialize(self):
        self.sleeptime = "15m"
        # Estado de la estrategia
        self.position_status = 'READY_TO_BUY'  # READY_TO_BUY, HOLDING, WATCHING_FOR_DIP

        # Precios de referencia
        self.buy_price = None
        self.avg_price = None  # Precio promedio si hay pyramiding
        self.recent_high = None
        self.trailing_stop = None
        self.prev_close = None

        # Control de cooldown y take profits
        self.sell_date = None
        self.original_size = None
        self.remaining_size = None
        self.take_profit_levels_hit = []  # Track de niveles alcanzados

        # Datos históricos para 52 semanas
        self.high_52w = None
        self.last_52w_update = None
        self.market_high_20d = None  # Máximo de 20 días

        # Tracking de pyramiding
        self.pyramid_entries = []  # Lista de (precio, cantidad)
        self.last_pyramid_price = None

        # Parámetros específicos del símbolo
        symbol = self.parameters["symbol"]
        self.symbol_params = self.SYMBOL_PARAMS.get(symbol, {})

        # Estadísticas
        self.trades_count = 0
        self.winning_trades = 0
        self.partial_exits = 0

        # Buffer para análisis de precio estático
        self.price_buffer = []

        self.last_stop_date = None
        self.cooldown_after_stop = self.parameters.get("cooldown_days_after_stop", 3)
        self.last_entry_reason = None          # 'breakout' | 'dip' | 'oversold'

        self.log_message(f"Carlos Mean Reversion Strategy inicializada para {symbol}")
        self.log_message(f"Parámetros: RSI oversold={self._get_param('rsi_oversold')}, "
                        f"Min trailing stop={self._get_param('min_trailing_stop')*100:.1f}%, "
                        f"Dip buying={self.parameters['buy_on_dip_enabled']}")

    def _get_param(self, param_name):
        """Obtiene parámetro específico del símbolo o default"""
        return self.symbol_params.get(param_name, self.parameters[param_name])

    def _get_52w_high(self, symbol):
        """Obtiene el máximo de 52 semanas usando yfinance"""
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="1y")
            if not hist.empty:
                return hist['High'].max()
        except Exception as e:
            self.log_message(f"Error obteniendo datos 52w para {symbol}: {e}")
        return None

    def _calculate_rsi(self, symbol, period=14):
        """Calcula RSI usando datos históricos de Lumibot"""
        try:
            bars = self.get_historical_prices(symbol, period + 1, "day")
            if bars is None or len(bars.df) < period + 1:
                return None
            
            prices = bars.df['close'].values
            deltas = np.diff(prices)
            gains = np.where(deltas > 0, deltas, 0)
            losses = np.where(deltas < 0, -deltas, 0)
            
            avg_gain = np.mean(gains[:period])
            avg_loss = np.mean(losses[:period])
            
            if avg_loss == 0:
                return 100
            
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            return rsi
        except Exception as e:
            self.log_message(f"Error calculando RSI: {e}")
            return None

    def _calculate_bollinger_bands(self, symbol, period=20, std=2):
        """Calcula Bollinger Bands"""
        try:
            bars = self.get_historical_prices(symbol, period, "day")
            if bars is None or len(bars.df) < period:
                return None, None, None
            
            prices = bars.df['close'].values
            sma = np.mean(prices)
            std_dev = np.std(prices)
            
            upper = sma + (std * std_dev)
            lower = sma - (std * std_dev)
            
            return upper, sma, lower
        except Exception:
            return None, None, None
    
    def _calculate_atr(self, symbol, period=14):
        """Calcula Average True Range para trailing stop dinámico"""
        try:
            bars = self.get_historical_prices(symbol, period + 1, "day")
            if bars is None or len(bars.df) < period:
                return None

            df = bars.df
            high = df['high'].values
            low = df['low'].values
            close = df['close'].values

            tr = np.maximum(high[1:] - low[1:],
                           np.abs(high[1:] - close[:-1]),
                           np.abs(low[1:] - close[:-1]))

            atr = np.mean(tr[-period:])
            return atr
        except Exception:
            return None

    def _get_sma(self, symbol, period=200):
        """Simple moving average of closes using Lumibot data."""
        try:
            bars = self.get_historical_prices(symbol, period, "day")
            if bars is None or len(bars.df) < period:
                return None
            return bars.df['close'].tail(period).mean()
        except Exception:
            return None

    def _recent_breakout_confirmed(self, symbol, buffer_pct, confirm_days):
        """Return (is_breakout, prior_52w_high) using yfinance 1y data and Lumibot closes."""
        high_52w = self._get_52w_high(symbol)
        if not high_52w:
            return False, None
        try:
            bars = self.get_historical_prices(symbol, confirm_days + 1, "day")
            if bars is None or len(bars.df) < confirm_days:
                return False, high_52w
            closes = bars.df['close'].values[-confirm_days:]
            thresh = high_52w * (1 + buffer_pct)
            return bool(np.all(closes > thresh)), high_52w
        except Exception:
            return False, high_52w

    def _calculate_chandelier_stop(self, current_price, atr, atr_mult, recent_high, min_stop_pct):
        """Chandelier exit: highest high minus ATR multiple, floored by a % from recent high."""
        if recent_high is None or atr is None:
            return None
        ce = recent_high - (atr * atr_mult)
        floor = recent_high * (1 - min_stop_pct)
        return max(ce, floor)

    def _position_size_by_volatility(self, current_price, atr):
        """Shares sized so that stop distance risks ~risk_per_trade_pct of equity."""
        equity = self.get_portfolio_value()
        risk_budget = equity * self.parameters["risk_per_trade_pct"]
        stop_dist = max(current_price * self.parameters["min_stop_pct"], atr * self.parameters["initial_atr_mult"] if atr else current_price * self.parameters["min_stop_pct"])
        if stop_dist <= 0:
            return 0
        shares = int(risk_budget / stop_dist)
        return max(shares, 0)

    def _is_price_static(self, symbol):
        """Determina si el precio ha estado estático por varios días"""
        try:
            static_days = self.parameters["static_days"]
            static_sd = self.parameters["static_sd"]
            
            bars = self.get_historical_prices(symbol, static_days, "day")
            if bars is None or len(bars.df) < static_days:
                return False
            
            prices = bars.df['close'].values
            std_dev = np.std(prices) / np.mean(prices)  # Coefficient of variation
            
            return std_dev < static_sd
        except Exception:
            return False

    def _should_enter(self, symbol, current_price):
        """Entry logic with trend filter, breakout confirmation, and moderated dip buys."""
        # Cooldown after last sell/stop
        if self.sell_date:
            dt_now = self.get_datetime()
            days_since_sell = (dt_now.date() - self.sell_date).days
            if days_since_sell < max(self.parameters["cooldown_days"], self.parameters["cooldown_days_after_stop"] if self.last_stop_date == self.sell_date else 0):
                return False, "standard"

        # Trend filter
        if self.parameters.get("trade_only_above_ma", True):
            sma = self._get_sma(symbol, self.parameters.get("trend_ma_period", 200))
            if sma and current_price < sma:
                return False, "standard"

        # Indicators
        rsi = self._calculate_rsi(symbol)
        if rsi is None:
            return False, "standard"

        # Recent 20d high for dip computation
        try:
            bars_20 = self.get_historical_prices(symbol, 20, "day")
            if bars_20 is None or len(bars_20.df) < 5:
                return False, "standard"
            self.market_high_20d = bars_20.df['high'].max()
        except Exception:
            return False, "standard"

        # 1) Breakout confirmation over 52w high
        if self.parameters.get("use_breakout_confirmation", True):
            ok, h52 = self._recent_breakout_confirmed(symbol, self.parameters["breakout_buffer_pct"], self.parameters["breakout_confirm_days"])
            if ok and current_price > h52 * (1 + self.parameters["breakout_buffer_pct"]):
                self.last_entry_reason = 'breakout'
                return True, "breakout"

        # 2) Buy-the-dip within band and with RSI confirmation
        if self.parameters["buy_on_dip_enabled"] and self.market_high_20d:
            dip_pct = (self.market_high_20d - current_price) / self.market_high_20d
            if self.parameters["dip_min_pct"] <= dip_pct <= self.parameters["dip_max_pct"] and rsi < self.parameters["rsi_buy_threshold"]:
                # volume filter
                try:
                    recent_vol = self.get_historical_prices(symbol, 5, "day")
                    avg_vol = self.get_historical_prices(symbol, 20, "day")
                    if recent_vol and avg_vol:
                        recent_avg = recent_vol.df['volume'].mean()
                        historical_avg = avg_vol.df['volume'].mean()
                        if historical_avg and recent_avg / historical_avg >= self.parameters["volume_spike_on_dip"]:
                            self.last_entry_reason = 'dip'
                            return True, "dip_buy"
                except Exception:
                    pass

        # 3) Classic mean-reversion to lower Bollinger and RSI oversold
        upper, sma20, bb_lower = self._calculate_bollinger_bands(symbol)
        if bb_lower is not None and (current_price <= bb_lower or rsi < self.parameters["rsi_oversold"]):
            self.last_entry_reason = 'oversold'
            return True, "oversold"

        return False, "standard"

    def _should_exit(self, symbol, current_price, _):
        """Exit logic: chandelier trailing, partials on strength, and breakout failure."""
        if not self.avg_price or not self.original_size:
            return False, 0, ""

        # P&L
        total_gain = (current_price - self.avg_price) / self.avg_price

        # ATR and chandelier stop
        atr = self._calculate_atr(symbol)
        chand = self._calculate_chandelier_stop(
            current_price=current_price,
            atr=atr,
            atr_mult=self.parameters["atr_multiplier"],
            recent_high=self.recent_high if self.recent_high else current_price,
            min_stop_pct=self.parameters["min_trailing_stop"],
        )
        if chand:
            self.trailing_stop = chand

        # Breakout failure: if entry was breakout and price loses 52w high by buffer for 2 consecutive closes
        if self.last_entry_reason == 'breakout' and self.high_52w:
            try:
                bars = self.get_historical_prices(symbol, 3, "day")
                if bars is not None and len(bars.df) >= 2:
                    closes = bars.df['close'].values[-2:]
                    if np.all(closes < self.high_52w * (1 - self.parameters["breakout_buffer_pct"])):
                        return True, 'ALL', "Breakout failure"
            except Exception:
                pass

        # Dynamic TPs
        if self.parameters["dynamic_tp_enabled"] and total_gain >= self.parameters["min_profit_target"]:
            for i, level in enumerate(self.parameters["scale_out_levels"]):
                if i not in self.take_profit_levels_hit and total_gain >= level:
                    self.take_profit_levels_hit.append(i)
                    partial_size = int(self.remaining_size * 0.33)
                    if partial_size > 0:
                        return True, partial_size, f"TP Nivel {i+1}: +{total_gain*100:.1f}%"

        # Trailing stop
        if self.trailing_stop and current_price <= self.trailing_stop:
            return True, 'ALL', f"Chandelier stop: {self.trailing_stop:.2f}"

        # Exceptional gain: secure the win
        if total_gain >= 0.50:
            return True, 'ALL', f"Ganancia excepcional: {total_gain*100:.1f}%"

        return False, 0, ""

    def on_trading_iteration(self):
        symbol = self.parameters["symbol"]
        
        # Obtener precio actual
        current_price = self.get_last_price(symbol)
        if current_price is None:
            self.log_message(f"No se pudo obtener precio para {symbol}")
            return
        
        # Inicializar precio previo
        if not hasattr(self, 'prev_close') or self.prev_close is None:
            self.prev_close = current_price
            return
        
        # Calcular ganancia diaria
        daily_gain = (current_price - self.prev_close) / self.prev_close
        
        # Obtener posición actual
        positions = self.get_positions()
        current_position = None
        for pos in positions:
            if pos.symbol == symbol:
                current_position = pos
                break
        
        # Lógica según estado
        if self.position_status in ['READY_TO_BUY', 'WATCHING_FOR_DIP']:
            # Lógica de entrada mejorada
            should_buy, buy_type = self._should_enter(symbol, current_price)

            if should_buy:
                # Volatility-based position sizing
                atr = self._calculate_atr(symbol)
                if self.parameters["position_sizing"] == "volatility":
                    shares = self._position_size_by_volatility(current_price, atr)
                elif self.parameters["position_sizing"] == "dynamic":
                    cash = self.get_cash()
                    portfolio_value = self.get_portfolio_value()
                    position_pct = self.parameters.get("base_position_pct", 0.60)
                    position_value = portfolio_value * position_pct
                    shares = int(position_value / current_price)
                else:
                    shares = self.parameters["paper_trade_qty"]

                cost = shares * current_price

                if self.get_cash() >= cost and shares > 0:
                    order = self.create_order(symbol, shares, "buy")
                    self.submit_order(order)

                    # Actualizar tracking con pyramiding
                    if not self.buy_price:
                        self.buy_price = current_price
                        self.avg_price = current_price
                        self.original_size = shares
                    else:
                        # Actualizar precio promedio
                        total_cost = (self.avg_price * self.original_size) + (current_price * shares)
                        self.original_size += shares
                        self.avg_price = total_cost / self.original_size

                    self.pyramid_entries.append((current_price, shares))
                    self.recent_high = max(self.recent_high or 0, current_price)
                    self.trailing_stop = current_price * (1 - self.parameters["min_trailing_stop"])
                    # Initialize ATR-based initial stop
                    atr = self._calculate_atr(symbol)
                    if atr and self.parameters.get("use_atr_initial_stop", True):
                        init_stop = self.avg_price - max(atr * self.parameters["initial_atr_mult"], self.avg_price * self.parameters["min_stop_pct"])
                        self.trailing_stop = max(self.trailing_stop or 0, init_stop)
                    self.position_status = 'HOLDING'
                    self.remaining_size = self.original_size

                    emoji = "🎯" if buy_type == "dip_buy" else "📈"
                    self.log_message(f'{emoji} {symbol} - COMPRA ({buy_type}): {shares} acciones a ${current_price:.2f} '
                                   f'(Avg: ${self.avg_price:.2f})')

                    # Agregar líneas al gráfico
                    self.add_line(f"{symbol} Price", current_price)
                    self.add_line("Avg Price", self.avg_price)
        
        elif self.position_status == 'HOLDING' and current_position:
            # NUEVO: Considerar pyramiding en caídas
            if self.parameters["pyramid_on_dip"] and self.recent_high:
                dip_from_high = (self.recent_high - current_price) / self.recent_high
                
                # Si hay una caída del 1% y no hemos hecho pyramid recientemente
                if (dip_from_high >= 0.01 and 
                    (not self.last_pyramid_price or 
                     current_price <= self.last_pyramid_price * 0.95)):
                    
                    # Calcular tamaño adicional
                    portfolio_value = self.get_portfolio_value()
                    current_position_value = self.remaining_size * current_price
                    max_position_value = portfolio_value * self.parameters["max_position_pct"]
                    
                    if current_position_value < max_position_value:
                        additional_value = min(max_position_value - current_position_value,
                                              portfolio_value * self.parameters["base_position_pct"] * 0.5)
                        additional_shares = int(additional_value / current_price)
                        
                        if additional_shares > 0 and self.get_cash() >= additional_shares * current_price:
                            order = self.create_order(symbol, additional_shares, "buy")
                            self.submit_order(order)
                            
                            # Actualizar tracking
                            total_cost = (self.avg_price * self.remaining_size) + (current_price * additional_shares)
                            self.remaining_size += additional_shares
                            self.original_size = self.remaining_size
                            self.avg_price = total_cost / self.remaining_size
                            self.last_pyramid_price = current_price
                            self.pyramid_entries.append((current_price, additional_shares))
                            
                            self.log_message(f'🔄 {symbol} - PYRAMID: {additional_shares} acciones más a ${current_price:.2f} '
                                           f'(Nuevo Avg: ${self.avg_price:.2f})')
            
            # Actualizar recent high y trailing stop
            if current_price > self.recent_high:
                self.recent_high = current_price
                
                # Ajustar trailing stop
                if self.parameters["atr_trailing_stop"]:
                    atr = self._calculate_atr(symbol)
                    if atr:
                        new_trailing = current_price - (atr * self.parameters["atr_multiplier"])
                    else:
                        new_trailing = current_price * (1 - self.parameters["min_trailing_stop"])
                else:
                    new_trailing = current_price * (1 - self.parameters["min_trailing_stop"])
                
                if new_trailing > self.trailing_stop:
                    self.trailing_stop = new_trailing
                    self.log_message(f'📊 {symbol} - Trailing Stop actualizado: ${new_trailing:.2f}')
            
            # Calcular P&L actual usando precio promedio
            if self.avg_price:
                unrealized_pl = (current_price - self.avg_price) * self.remaining_size
                unrealized_pl_pct = ((current_price - self.avg_price) / self.avg_price) * 100
                
                # Agregar líneas al gráfico
                self.add_line(f"{symbol} Price", current_price)
                self.add_line("Recent High", self.recent_high)
                self.add_line("Trailing Stop", self.trailing_stop)
                self.add_line("Unrealized P&L %", unrealized_pl_pct)
                
                self.log_message(f'📊 {symbol} - Posición: {self.remaining_size} acciones, '
                               f'P&L: ${unrealized_pl:.2f} ({unrealized_pl_pct:.1f}%)')
            
            # Verificar condiciones de salida
            should_sell, sell_size, reason = self._should_exit(symbol, current_price, daily_gain)
            
            if should_sell:
                if sell_size == 'ALL':
                    # Venta completa
                    order = self.create_order(symbol, self.remaining_size, "sell")
                    self.submit_order(order)

                    # Calcular P&L final usando precio promedio
                    final_pl = (current_price - self.avg_price) * self.remaining_size
                    final_pl_pct = ((current_price - self.avg_price) / self.avg_price) * 100

                    self.log_message(f'📉 {symbol} - VENTA COMPLETA: {self.remaining_size} acciones '
                                   f'a ${current_price:.2f} - P&L: ${final_pl:.2f} ({final_pl_pct:.1f}%) - {reason}')
                    self.last_stop_date = self.get_datetime().date()
                    # Reset tracking
                    self._reset_position()
                    self.trades_count += 1
                    if final_pl > 0:
                        self.winning_trades += 1
                else:
                    # Venta parcial
                    order = self.create_order(symbol, sell_size, "sell")
                    self.submit_order(order)

                    self.remaining_size -= sell_size
                    self.partial_exits += 1

                    partial_pl = (current_price - self.avg_price) * sell_size
                    self.log_message(f'📊 {symbol} - VENTA PARCIAL: {sell_size} acciones '
                                   f'a ${current_price:.2f} - P&L: ${partial_pl:.2f} - {reason}')
        
        # Actualizar precio previo
        self.prev_close = current_price

    def _reset_position(self):
        """Reset del estado de la posición"""
        self.position_status = 'WATCHING_FOR_DIP'  # Cambio: buscar siguiente caída
        self.sell_date = self.get_datetime().date()
        self.buy_price = None
        self.avg_price = None
        self.recent_high = None
        self.trailing_stop = None
        self.take_profit_levels_hit = []
        self.original_size = None
        self.remaining_size = None
        self.pyramid_entries = []
        self.last_pyramid_price = None
        self.last_entry_reason = None
        self.high_52w = None


if __name__ == "__main__":
    IS_BACKTESTING = True
    
    if IS_BACKTESTING:
        from lumibot.backtesting import AlpacaBacktesting
        
        # Verificar configuración
        if not ALPACA_TEST_CONFIG:
            print("Error: Se requiere configuración ALPACA_TEST_CONFIG")
            exit()
        
        # Configurar fechas - ACTUALIZADO: Enero 2024 a Enero 2025
        tzinfo = pytz.timezone('America/New_York')
        backtesting_start = tzinfo.localize(dt.datetime(2022, 1, 1))
        backtesting_end = tzinfo.localize(dt.datetime(2025, 9, 1))
        
        print("=" * 60)
        print("Carlos Mean Reversion Strategy - Backtesting")
        print("=" * 60)
        print(f"Símbolo: QQQ")
        print(f"Período: {backtesting_start.date()} a {backtesting_end.date()}")
        print(f"Estrategia: Mean Reversion + Momentum + Take Profits Escalonados")
        print("=" * 60)
        
        # Ejecutar backtest
        results, strategy = CarlosMeanReversionStrategy.run_backtest(
            datasource_class=AlpacaBacktesting,
            backtesting_start=backtesting_start,
            backtesting_end=backtesting_end,
            minutes_before_closing=0,
            benchmark_asset='QQQ',
            analyze_backtest=True,
            parameters={
                "symbol": "QQQ",  # QQQ - tech diversificado y líquido
                # Protección en máximos
                "exit_at_52w_high": True,
                "distance_from_52w_high": 0.02,
                "stop_loss_from_52w": 0.02,
                # Compra en caídas
                "symbols": ["QQQ", "NVDA", "MSFT", "META", "NFLX"],
                "buy_on_dip_enabled": True,
                "dip_from_recent_high": 0.01,
                "rsi_buy_threshold": 55,
                "volume_spike_on_dip": 1.05,
                # Position sizing
                "position_sizing": "dynamic",
                "base_position_pct": 0.60,
                "max_position_pct": 0.98,
                "pyramid_on_dip": True,
                # Take profits
                "dynamic_tp_enabled": True,
                "min_profit_target": 0.15,
                "scale_out_levels": [0.20, 0.40, 0.80],
                # Trailing stop
                "atr_trailing_stop": True,
                "atr_multiplier": 3.0,
                "min_trailing_stop": 0.07,
                # Otros
                "rsi_oversold": 45,
                "cooldown_days": 0,
                "paper_trade_qty": 100,
            },
            show_progress_bar=True,
            timestep='day',
            market='NASDAQ',
            config=ALPACA_TEST_CONFIG,
            refresh_cache=False,
            warm_up_trading_days=0,
            auto_adjust=True,
        )
        
        # Imprimir resultados
        print("\n" + "=" * 60)
        print("RESULTADOS DEL BACKTEST")
        print("=" * 60)
        print(results)
        
    else:
        # PAPER TRADING
        from lumibot.brokers import Alpaca
        
        ALPACA_CONFIG = ALPACA_TEST_CONFIG
        
        if not ALPACA_CONFIG["API_KEY"] or not ALPACA_CONFIG["API_SECRET"]:
            print("Error: Credenciales no encontradas")
            exit()
        
        print("=" * 60)
        print("Carlos Mean Reversion Strategy - Paper Trading")
        print("=" * 60)
        
        broker = Alpaca(ALPACA_CONFIG)
        strategy = CarlosMeanReversionStrategy(
            broker=broker,
            parameters={
                "symbol": "QQQ",
                "daily_gain_threshold": 0.03,
                "pullback_pct": 0.02,
                "trailing_stop_pct": 0.015,
                "paper_trade_qty": 10,
            }
        )
        
        print("Ejecutando estrategia en paper trading...")
        strategy.run_live()