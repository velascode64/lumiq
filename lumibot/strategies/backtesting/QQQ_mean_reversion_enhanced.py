from datetime import datetime, timedelta
import numpy as np
import pandas as pd
from lumibot.strategies.strategy import Strategy

"""
Strategy Description: QQQ Mean Reversion Enhanced v3.0 - TARGET 60%+

Estrategia optimizada para QQQ con objetivo de 60%+ anual.
Nuevas características implementadas:
- Trailing Stop Dinámico: -2% después de cada +5% de ganancia
- Recompra Inteligente: Tras caídas >5% y 2+ días de estabilización
- Gestión agresiva de ganancias para maximizar retorno
"""


class QQQMeanReversionEnhanced(Strategy):
    parameters = {
        "symbol": "QQQ",
        # Parámetros de entrada optimizados
        "dip_threshold_bull": -0.015,  # Caída del 1.5% en bull market
        "dip_threshold_bear": -0.05,   # Caída del 5% en bear market
        "dip_threshold_normal": -0.025, # Caída del 2.5% en mercado normal

        # RSI parameters
        "rsi_oversold": 35,
        "rsi_overbought": 70,
        "rsi_period": 14,

        # TRAILING STOP DINÁMICO - Nueva funcionalidad
        "dynamic_trailing_trigger": 0.05,  # Activar trailing stop tras +5%
        "dynamic_trailing_stop": -0.02,    # Stop loss del -2% desde peak
        "recompra_threshold": -0.05,       # Recomprar tras caída del -5%
        "stability_days": 2,               # Días de estabilización para recompra

        # Salidas optimizadas
        "take_profit_1": 0.08,  # Primera toma de ganancias al 8%
        "take_profit_2": 0.15,  # Segunda toma de ganancias al 15%
        "aggressive_tp": 0.25,  # Take profit agresivo al 25%
        "stop_loss": -0.12,     # Stop loss inicial más amplio
        "trailing_stop_pct": 0.04,  # Trailing stop tradicional

        # Gestión de posiciones agresiva
        "position_size_1": 0.40,  # Primera entrada 40% (más agresivo)
        "position_size_2": 0.35,  # Segunda entrada 35%
        "position_size_3": 0.25,  # Tercera entrada 25%
        "max_positions": 3,

        # Parámetros de mercado
        "sma_short": 20,
        "sma_medium": 50,
        "sma_long": 200,
        "bb_period": 20,
        "bb_std": 2,

        # Control de volatilidad
        "high_volatility_threshold": 0.30,
        "low_volatility_threshold": 0.15,
        "volatility_lookback": 20,

        # Control de tiempo optimizado
        "max_holding_days": 45,  # Más tiempo para desarrollar ganancias
        "min_time_between_trades": 12,  # Reducido para más oportunidades
    }

    def initialize(self):
        self.sleeptime = "1D"

        # Tracking de posiciones y performance
        self.positions_data = {}
        self.last_peak = 0
        self.peak_date = None
        self.last_trade_time = None
        self.current_regime = "normal"
        self.entry_prices = []
        self.entry_dates = []

        # NUEVA: Tracking para trailing stop dinámico
        self.dynamic_trailing_active = False
        self.dynamic_peak = 0
        self.entry_peak_price = 0
        self.gains_realized = 0

        # NUEVA: Tracking para recompra
        self.last_big_drop_date = None
        self.last_big_drop_price = 0
        self.stability_counter = 0
        self.awaiting_recompra = False

        # Performance tracking
        self.consecutive_wins = 0
        self.consecutive_losses = 0
        self.total_trades = 0
        self.winning_trades = 0

    def calculate_rsi(self, prices, period=14):
        """Calcula el RSI mejorado"""
        if len(prices) < period + 1:
            return 50

        deltas = np.diff(prices)
        seed = deltas[:period]
        up = seed[seed >= 0].sum() / period
        down = -seed[seed < 0].sum() / period

        if down == 0:
            return 100

        rs = up / down
        rsi = 100 - (100 / (1 + rs))

        # Smooth RSI para evitar señales falsas
        for i in range(period, len(deltas)):
            delta = deltas[i]
            if delta > 0:
                upval = delta
                downval = 0
            else:
                upval = 0
                downval = -delta

            up = (up * (period - 1) + upval) / period
            down = (down * (period - 1) + downval) / period

            if down != 0:
                rs = up / down
                rsi = 100 - (100 / (1 + rs))

        return rsi

    def calculate_macd(self, prices):
        """Calcula MACD con señales"""
        if len(prices) < 26:
            return 0, 0, 0

        exp1 = pd.Series(prices).ewm(span=12, adjust=False).mean()
        exp2 = pd.Series(prices).ewm(span=26, adjust=False).mean()
        macd_line = exp1 - exp2
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        histogram = macd_line - signal_line

        return macd_line.iloc[-1], signal_line.iloc[-1], histogram.iloc[-1]

    def calculate_bollinger_bands(self, prices, period=20, std_dev=2):
        """Calcula Bandas de Bollinger"""
        if len(prices) < period:
            return 0, 0, 0

        sma = np.mean(prices[-period:])
        std = np.std(prices[-period:])

        upper_band = sma + (std * std_dev)
        lower_band = sma - (std * std_dev)

        return upper_band, sma, lower_band

    def calculate_volatility(self, symbol, days=20):
        """Calcula volatilidad anualizada"""
        try:
            bars = self.get_historical_prices(symbol, days + 1, "day")
            if bars and hasattr(bars, 'df') and not bars.df.empty:
                returns = bars.df['close'].pct_change().dropna()
                volatility = returns.std() * np.sqrt(252)
                return volatility
        except:
            pass
        return 0.20

    def determine_market_regime(self, current_price, sma_50, sma_200, volatility):
        """Determina el régimen de mercado actual"""
        if current_price > sma_50 > sma_200:
            return "bull"
        elif current_price < sma_50 < sma_200:
            return "bear"
        elif volatility > self.parameters["high_volatility_threshold"]:
            return "high_vol"
        else:
            return "normal"

    def check_price_stability(self, prices, days=2):
        """Verifica si el precio se ha estabilizado (no cae >2% por X días)"""
        if len(prices) < days + 1:
            return False

        recent_changes = []
        for i in range(days):
            if len(prices) > i + 1:
                change = (prices[-(i+1)] - prices[-(i+2)]) / prices[-(i+2)]
                recent_changes.append(change)

        # Estable si no hay caídas >2% en los últimos días
        return all(change > -0.02 for change in recent_changes)

    def get_dynamic_position_size(self, regime, volatility, consecutive_losses, is_recompra=False):
        """Calcula tamaño de posición dinámico"""
        if is_recompra:
            # Más agresivo en recompras tras estabilización
            base_size = 0.50
        else:
            base_size = self.parameters["position_size_1"]

        # Ajustar por régimen de mercado
        regime_multipliers = {
            "bull": 1.3,      # Más agresivo en bull market
            "normal": 1.0,
            "bear": 0.6,
            "high_vol": 0.4
        }
        size = base_size * regime_multipliers.get(regime, 1.0)

        # Ajustar por volatilidad
        if volatility > self.parameters["high_volatility_threshold"]:
            size *= 0.8
        elif volatility < self.parameters["low_volatility_threshold"]:
            size *= 1.2

        # Reducir tamaño después de pérdidas consecutivas
        if consecutive_losses > 2:
            size *= 0.9
        elif consecutive_losses > 4:
            size *= 0.7

        # Aumentar en rachas ganadoras
        if self.consecutive_wins > 3:
            size *= 1.1

        return max(0.15, min(0.60, size))

    def check_entry_conditions(self, current_price, indicators, regime, prices_history):
        """Evalúa condiciones de entrada mejoradas"""
        rsi = indicators['rsi']
        macd_hist = indicators['macd_hist']
        bb_lower = indicators['bb_lower']
        daily_change = indicators['daily_change']
        volume_ratio = indicators.get('volume_ratio', 1.0)

        # NUEVA: Verificar si es momento de recompra tras estabilización
        if self.awaiting_recompra:
            if self.check_price_stability(prices_history, self.parameters["stability_days"]):
                return True, "Recompra tras estabilización"
            else:
                return False, ""

        # Seleccionar threshold según régimen
        if regime == "bull":
            dip_threshold = self.parameters["dip_threshold_bull"]
        elif regime == "bear":
            dip_threshold = self.parameters["dip_threshold_bear"]
        else:
            dip_threshold = self.parameters["dip_threshold_normal"]

        # Condiciones de entrada por prioridad
        entry_score = 0
        entry_reasons = []

        # 1. Caída fuerte con RSI oversold (máxima prioridad)
        if daily_change <= dip_threshold and rsi < self.parameters["rsi_oversold"]:
            entry_score += 4  # Aumentado para más agresividad
            entry_reasons.append(f"Caída {daily_change:.2%} + RSI {rsi:.1f}")

        # 2. Toque de banda inferior de Bollinger
        if current_price <= bb_lower * 1.01:
            entry_score += 3  # Aumentado
            entry_reasons.append("Banda Bollinger inferior")

        # 3. MACD positivo (momentum girando)
        if macd_hist > 0 and rsi < 45:  # Más permisivo
            entry_score += 2  # Aumentado
            entry_reasons.append("MACD positivo")

        # 4. Alto volumen (capitulación)
        if volume_ratio > 1.3 and daily_change < 0:  # Más sensible
            entry_score += 2
            entry_reasons.append(f"Alto volumen {volume_ratio:.1f}x")

        # 5. NUEVA: Oportunidad tras caída significativa
        if daily_change <= -0.03 and regime != "bear":
            entry_score += 2
            entry_reasons.append("Caída significativa >3%")

        # Requiere score mínimo según régimen (reducido para más agresividad)
        min_scores = {
            "bull": 2,      # Más agresivo
            "normal": 3,
            "bear": 5,      # Más conservador en bear
            "high_vol": 4
        }

        min_score = min_scores.get(regime, 3)
        should_buy = entry_score >= min_score

        return should_buy, " + ".join(entry_reasons) if entry_reasons else ""

    def check_exit_conditions(self, position, current_price, indicators, regime):
        """Evalúa condiciones de salida mejoradas con trailing stop dinámico"""
        if not position:
            return False, "", 0

        avg_price = position.avg_fill_price
        pnl_pct = (current_price - avg_price) / avg_price
        rsi = indicators['rsi']
        macd_hist = indicators['macd_hist']
        bb_upper = indicators['bb_upper']

        # NUEVA: Activar trailing stop dinámico
        if not self.dynamic_trailing_active and pnl_pct >= self.parameters["dynamic_trailing_trigger"]:
            self.dynamic_trailing_active = True
            self.dynamic_peak = current_price
            self.entry_peak_price = avg_price
            self.log_message(f"🔥 TRAILING STOP DINÁMICO ACTIVADO tras {pnl_pct:.2%} ganancia")

        # Actualizar peak dinámico
        if self.dynamic_trailing_active and current_price > self.dynamic_peak:
            self.dynamic_peak = current_price

        # Calcular días de holding
        holding_days = 0
        if self.entry_dates:
            holding_days = (self.get_datetime() - self.entry_dates[0]).days

        should_sell = False
        sell_quantity = 0
        sell_reason = ""

        # 1. NUEVA: Trailing Stop Dinámico (-2% desde peak tras +5%)
        if self.dynamic_trailing_active and self.dynamic_peak > 0:
            drawdown_from_dynamic_peak = (current_price - self.dynamic_peak) / self.dynamic_peak
            if drawdown_from_dynamic_peak <= self.parameters["dynamic_trailing_stop"]:
                should_sell = True
                sell_quantity = position.quantity
                sell_reason = f"Trailing Stop Dinámico {drawdown_from_dynamic_peak:.2%} (Peak: ${self.dynamic_peak:.2f})"

        # 2. Take Profit Agresivo Escalonado
        elif pnl_pct >= self.parameters["aggressive_tp"]:
            should_sell = True
            sell_quantity = position.quantity
            sell_reason = f"Take profit agresivo {pnl_pct:.2%}"
        elif pnl_pct >= self.parameters["take_profit_2"]:
            should_sell = True
            sell_quantity = position.quantity * 3 // 4  # Vender 75%
            sell_reason = f"Take profit 2 alcanzado {pnl_pct:.2%}"
        elif pnl_pct >= self.parameters["take_profit_1"]:
            should_sell = True
            sell_quantity = position.quantity // 2  # Vender 50%
            sell_reason = f"Take profit 1 alcanzado {pnl_pct:.2%}"

        # 3. Stop Loss Inicial
        elif pnl_pct <= self.parameters["stop_loss"]:
            should_sell = True
            sell_quantity = position.quantity
            sell_reason = f"Stop loss {pnl_pct:.2%}"

        # 4. Señales técnicas agresivas de salida
        elif rsi > 75 and current_price > bb_upper * 1.02:  # Más agresivo
            should_sell = True
            sell_quantity = position.quantity // 2
            sell_reason = f"Sobrecompra extrema RSI {rsi:.1f}"

        # 5. Momentum negativo con ganancias
        elif macd_hist < -0.5 and pnl_pct > 0.03:
            should_sell = True
            sell_quantity = position.quantity // 3
            sell_reason = "MACD negativo fuerte"

        # 6. Tiempo máximo con pérdidas
        elif holding_days > self.parameters["max_holding_days"] and pnl_pct < -0.05:
            should_sell = True
            sell_quantity = position.quantity
            sell_reason = f"Tiempo máximo {holding_days} días"

        # 7. Cambio de régimen crítico
        elif regime == "bear" and pnl_pct > 0.02:
            should_sell = True
            sell_quantity = position.quantity
            sell_reason = "Bear market detectado"

        return should_sell, sell_reason, sell_quantity

    def on_trading_iteration(self):
        symbol = self.parameters["symbol"]

        # Verificar tiempo mínimo entre trades
        if self.last_trade_time:
            hours_since_last = (self.get_datetime() - self.last_trade_time).total_seconds() / 3600
            if hours_since_last < self.parameters["min_time_between_trades"]:
                return

        # Obtener precio actual
        current_price = self.get_last_price(symbol)
        if not current_price:
            return

        try:
            # Obtener datos históricos extendidos
            bars = self.get_historical_prices(symbol, 250, "day")
            if not bars or not hasattr(bars, 'df') or bars.df.empty or len(bars.df) < 200:
                self.log_message("Datos insuficientes para análisis")
                return

            df = bars.df
            prices = df['close'].values
            volumes = df['volume'].values if 'volume' in df.columns else None

            # NUEVA: Detectar caídas grandes para activar recompra
            if len(prices) > 1:
                recent_change = (current_price - prices[-2]) / prices[-2]
                if recent_change <= self.parameters["recompra_threshold"]:
                    self.last_big_drop_date = self.get_datetime()
                    self.last_big_drop_price = current_price
                    self.awaiting_recompra = True
                    self.stability_counter = 0
                    self.log_message(f"🔻 CAÍDA GRANDE DETECTADA: {recent_change:.2%} - Esperando estabilización")

            # Calcular todos los indicadores técnicos
            sma_20 = df['close'].rolling(window=self.parameters["sma_short"]).mean().iloc[-1]
            sma_50 = df['close'].rolling(window=self.parameters["sma_medium"]).mean().iloc[-1]
            sma_200 = df['close'].rolling(window=self.parameters["sma_long"]).mean().iloc[-1]

            rsi = self.calculate_rsi(prices, self.parameters["rsi_period"])
            macd_line, signal_line, macd_hist = self.calculate_macd(prices)
            bb_upper, bb_middle, bb_lower = self.calculate_bollinger_bands(
                prices, self.parameters["bb_period"], self.parameters["bb_std"]
            )

            # Calcular volatilidad y régimen de mercado
            volatility = self.calculate_volatility(symbol, self.parameters["volatility_lookback"])
            self.current_regime = self.determine_market_regime(current_price, sma_50, sma_200, volatility)

            # Calcular métricas adicionales
            daily_change = (current_price - df['close'].iloc[-2]) / df['close'].iloc[-2]
            volume_ratio = 1.0
            if volumes is not None and len(volumes) > 20:
                current_volume = volumes[-1]
                avg_volume = np.mean(volumes[-20:])
                if avg_volume > 0:
                    volume_ratio = current_volume / avg_volume

            # Preparar diccionario de indicadores
            indicators = {
                'rsi': rsi,
                'macd_line': macd_line,
                'macd_signal': signal_line,
                'macd_hist': macd_hist,
                'bb_upper': bb_upper,
                'bb_middle': bb_middle,
                'bb_lower': bb_lower,
                'sma_20': sma_20,
                'sma_50': sma_50,
                'sma_200': sma_200,
                'daily_change': daily_change,
                'volume_ratio': volume_ratio,
                'volatility': volatility
            }

        except Exception as e:
            self.log_message(f"Error calculando indicadores: {e}")
            return

        # Obtener posiciones actuales
        positions = self.get_positions()
        qqq_position = None
        for position in positions:
            if position.symbol == symbol:
                qqq_position = position
                break

        current_value = self.get_portfolio_value()
        cash_available = self.get_cash()

        # ============ LÓGICA DE COMPRA ============
        if not qqq_position or len(self.entry_prices) < self.parameters["max_positions"]:
            should_buy, buy_reason = self.check_entry_conditions(
                current_price, indicators, self.current_regime, prices
            )

            if should_buy:
                # Determinar si es recompra
                is_recompra = self.awaiting_recompra and "estabilización" in buy_reason

                # Calcular tamaño de posición dinámico
                position_size = self.get_dynamic_position_size(
                    self.current_regime, volatility, self.consecutive_losses, is_recompra
                )

                # Si ya tenemos posiciones, ajustar tamaño para escalar
                if len(self.entry_prices) == 1:
                    position_size = self.parameters["position_size_2"]
                elif len(self.entry_prices) == 2:
                    position_size = self.parameters["position_size_3"]

                order_value = current_value * position_size

                if cash_available > order_value:
                    quantity = int(order_value / current_price)
                    if quantity > 0:
                        order = self.create_order(symbol, quantity, "buy")
                        self.submit_order(order)

                        # Registrar entrada
                        self.entry_prices.append(current_price)
                        self.entry_dates.append(self.get_datetime())
                        self.last_trade_time = self.get_datetime()
                        self.total_trades += 1

                        # Reset recompra si es aplicable
                        if is_recompra:
                            self.awaiting_recompra = False
                            self.stability_counter = 0

                        self.log_message(f"""
                        🔵 COMPRA EJECUTADA
                        Cantidad: {quantity} {symbol} @ ${current_price:.2f}
                        Razón: {buy_reason}
                        Régimen: {self.current_regime}
                        RSI: {rsi:.1f} | Volatilidad: {volatility:.2%}
                        Tamaño: {position_size:.1%} | Recompra: {is_recompra}
                        """)

        # ============ LÓGICA DE VENTA ============
        if qqq_position and qqq_position.quantity > 0:
            should_sell, sell_reason, sell_quantity = self.check_exit_conditions(
                qqq_position, current_price, indicators, self.current_regime
            )

            if should_sell and sell_quantity > 0:
                sell_quantity = min(sell_quantity, qqq_position.quantity)

                order = self.create_order(symbol, sell_quantity, "sell")
                self.submit_order(order)

                # Calcular PnL
                avg_price = qqq_position.avg_fill_price
                pnl_pct = (current_price - avg_price) / avg_price

                # Actualizar estadísticas
                if pnl_pct > 0:
                    self.consecutive_wins += 1
                    self.consecutive_losses = 0
                    self.winning_trades += 1
                    self.gains_realized += pnl_pct
                else:
                    self.consecutive_losses += 1
                    self.consecutive_wins = 0

                self.last_trade_time = self.get_datetime()

                # Si vendemos toda la posición, resetear
                if sell_quantity == qqq_position.quantity:
                    self.entry_prices = []
                    self.entry_dates = []
                    self.last_peak = 0
                    # Reset trailing stop dinámico
                    self.dynamic_trailing_active = False
                    self.dynamic_peak = 0

                self.log_message(f"""
                🔴 VENTA EJECUTADA
                Cantidad: {sell_quantity} {symbol} @ ${current_price:.2f}
                Razón: {sell_reason}
                PnL: {pnl_pct:.2%}
                Ganancias acumuladas: {self.gains_realized:.2%}
                Win Rate: {(self.winning_trades/max(1,self.total_trades))*100:.1f}%
                """)

        # ============ LOGGING MEJORADO ============
        if self.get_datetime().hour == 10 and self.get_datetime().minute == 0:
            portfolio_value = self.get_portfolio_value()
            positions_value = portfolio_value - cash_available
            win_rate = (self.winning_trades / max(1, self.total_trades)) * 100 if self.total_trades > 0 else 0

            self.log_message(f"""
            📊 ESTADO DEL PORTFOLIO v3.0
            ════════════════════════════════════════
            Valor Total: ${portfolio_value:,.2f}
            Efectivo: ${cash_available:,.2f}
            Posiciones: ${positions_value:,.2f}
            Ganancia YTD: {((portfolio_value/100000)-1)*100:.2f}%

            MERCADO & SEÑALES
            ────────────────────────────────────────
            Precio {symbol}: ${current_price:.2f}
            Régimen: {self.current_regime.upper()}
            Volatilidad: {volatility:.1%} anual
            RSI: {rsi:.1f} | MACD: {macd_hist:.3f}

            TRAILING STOP DINÁMICO
            ────────────────────────────────────────
            Activo: {self.dynamic_trailing_active}
            Peak Dinámico: ${self.dynamic_peak:.2f}
            Esperando Recompra: {self.awaiting_recompra}

            PERFORMANCE AGRESIVA
            ────────────────────────────────────────
            Total Trades: {self.total_trades}
            Win Rate: {win_rate:.1f}%
            Ganancias Realizadas: {self.gains_realized:.2%}
            Racha: {self.consecutive_wins}W/{self.consecutive_losses}L
            ════════════════════════════════════════
            """)


if __name__ == "__main__":
    is_live = False

    if is_live:
        from lumibot.credentials import ALPACA_CONFIG
        from lumibot.brokers import Alpaca

        broker = Alpaca(ALPACA_CONFIG)
        strategy = QQQMeanReversionEnhanced(broker=broker)
        strategy.run_live()

    else:
        from lumibot.backtesting import YahooDataBacktesting

        # Backtest agresivo para 2020-2024
        backtesting_start = datetime(2020, 1, 1)
        backtesting_end = datetime(2024, 12, 31)

        results = QQQMeanReversionEnhanced.backtest(
            YahooDataBacktesting,
            backtesting_start,
            backtesting_end,
            benchmark_asset="QQQ",
            show_plot=True,
            show_tearsheet=True,
            save_tearsheet=True,
            parameters={
                "symbol": "QQQ",
                # Parámetros optimizados para 60%+
                "dip_threshold_bull": -0.015,
                "dip_threshold_normal": -0.025,
                "dip_threshold_bear": -0.05,
                "rsi_oversold": 35,
                "dynamic_trailing_trigger": 0.05,  # Trailing tras +5%
                "dynamic_trailing_stop": -0.02,    # Stop -2%
                "take_profit_1": 0.08,
                "take_profit_2": 0.15,
                "aggressive_tp": 0.25,
                "position_size_1": 0.40,  # Más agresivo
                "max_positions": 3,
                "recompra_threshold": -0.05,
                "stability_days": 2,
            }
        )

        print("\n" + "="*70)
        print("    RESULTADOS OPTIMIZADOS PARA 60%+ ANUAL - v3.0")
        print("="*70)

        if hasattr(results, 'stats'):
            stats = results.stats

            # Calcular métricas clave
            total_return = stats.get('total_return', 0)
            years = (backtesting_end - backtesting_start).days / 365.25
            annualized_return = ((1 + total_return) ** (1/years) - 1) * 100
            sharpe = stats.get('sharpe', 0)
            max_dd = stats.get('max_drawdown', 0) * 100
            win_rate = stats.get('win_rate', 0) * 100

            print(f"\n🚀 RENDIMIENTO AGRESIVO")
            print(f"  • Retorno Total: {total_return * 100:.2f}%")
            print(f"  • Retorno Anualizado: {annualized_return:.2f}%")
            print(f"  • Sharpe Ratio: {sharpe:.2f}")

            print(f"\n⚡ GESTIÓN DE RIESGO")
            print(f"  • Max Drawdown: {max_dd:.2f}%")
            print(f"  • Volatilidad: {stats.get('volatility', 0) * 100:.2f}%")

            print(f"\n🎯 EFICIENCIA OPTIMIZADA")
            print(f"  • Win Rate: {win_rate:.2f}%")
            print(f"  • Número de Trades: {stats.get('total_trades', 0)}")

            print(f"\n🏆 NUEVAS CARACTERÍSTICAS")
            print(f"  • Trailing Stop Dinámico: +5% → -2%")
            print(f"  • Recompra Inteligente: Tras caídas >5%")
            print(f"  • Gestión Agresiva: TP hasta 25%")

            # Verificar objetivo 60%+
            print("\n" + "="*70)
            if annualized_return >= 60:
                print(f"🎉 OBJETIVO 60%+ ALCANZADO: {annualized_return:.2f}% anual")
                print("💰 Estrategia lista para trading agresivo")
            elif annualized_return >= 50:
                print(f"🔥 EXCELENTE RESULTADO: {annualized_return:.2f}% anual")
                print("💡 Muy cerca del objetivo 60%")
            elif annualized_return >= 40:
                print(f"⭐ BUEN RESULTADO: {annualized_return:.2f}% anual")
                print("💡 Considerar más agresividad en bull markets")
            else:
                print(f"⚠️  Objetivo no alcanzado: {annualized_return:.2f}%")
                print("💡 Revisar parámetros o período de backtest")

            # Análisis de mejoras
            if max_dd > 25:
                print("\n🔧 OPTIMIZACIÓN: Drawdown alto, considerar más trailing stops")
            if win_rate < 55:
                print("🔧 OPTIMIZACIÓN: Win rate bajo, mejorar timing entrada")
            if sharpe < 1.2:
                print("🔧 OPTIMIZACIÓN: Sharpe ratio bajo, balancear riesgo/retorno")

        print("\n" + "="*70)