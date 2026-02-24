import datetime as dt
import pytz
from datetime import time
from datetime import datetime
from lumibot.credentials import ALPACA_TEST_CONFIG
from lumibot.strategies.strategy import Strategy

"""
Strategy Description: Volume Multiplayer Options Strategy

Estrategia de opciones 0DTE (Zero Days to Expiry) basada en gaps alcistas con confirmación de volumen.
Inspirada en las técnicas de Christian para detectar breakouts intradía con alto volumen.

Características principales:
- Detección de gaps alcistas >2% en apertura
- Confirmación de volumen >1.5x promedio
- Monitoreo de soporte (piso) por 20 minutos
- Entrada en calls OTM en breakout del high de primera vela
- Gestión de riesgo con take profit y stop loss

NOTA: Esta estrategia requiere datos de opciones en tiempo real.
Para backtesting, usaremos simulación con acciones en lugar de opciones.
"""


class VolumeMultiplayerStrategy(Strategy):
    parameters = {
        # Símbolos a monitorear
        "symbols": ["SOFI", "TSLA", "AMZN", "META"],
        
        # Criterios de entrada
        "gap_threshold": 0.02,          # Gap alcista mínimo (2%)
        "volume_multiplier": 1.5,       # Volumen > 1.5x promedio
        "monitor_minutes": 20,          # Minutos para monitorear soporte
        
        # Gestión de riesgo
        "take_profit_pct": 0.50,        # Take-profit 50%
        "stop_loss_pct": 0.30,          # Stop-loss 30%
        "max_hold_minutes": 60,         # Máximo tiempo en posición (1 hora)
        
        # Tamaños de posición
        "position_size": 100,           # Acciones por posición (simulando opciones)
        "max_positions": 2,             # Máximo posiciones simultáneas
        # Ventana y filtros adicionales
        "entry_window_minutes": 60,      # Solo se permiten entradas en la primera hora (9:30-10:30 ET)
        "volume_lookback_days": 20,      # Días para promedio del volumen de la 1ra vela
        "opening_bar_minutes": 5,        # Tamaño de la 1ra vela (5m)
        # Placeholders para live trading con opciones (no usados en backtest con acciones)
        "min_option_delta": 0.40,
        "min_option_gamma": 0.0,
        "max_option_spread_bps": 75,     # pbs sobre el precio de la opción
        # Position sizing y TP/SL estilo opciones (proxy con acciones)
        "use_allocation": True,            # Usar % de caja para dimensionar la posición
        "allocation_pct": 0.25,            # 25% del cash disponible por trade
        "min_allocation_dollars": 1000,    # mínimo absoluto por trade (para cuentas 5k/10k)
        "pnl_target_dollars": 500,         # objetivo monetario por trade (TP $500)
        "underlying_tp_pct": 0.015,        # +1.5% en subyacente ≈ +50% en opción (aprox)
        "underlying_sl_pct": 0.010,        # -1.0% en subyacente ≈ -30% en opción (aprox)
        # Filtros de calidad y control de ejecución
        "vwap_filter": True,               # Exigir precio > VWAP en la entrada
        "one_trade_per_symbol": True,     # Una sola operación por símbolo por día
        "max_slippage_bps": 5,            # Límite de slippage al enviar orden (50 bps = 0.50%)
    }

    def initialize(self):
        self.sleeptime = "1M"  # Ejecutar cada minuto para intradía
        
        # Tracking de estado por símbolo
        self.symbol_data = {}
        for symbol in self.parameters["symbols"]:
            self.symbol_data[symbol] = {
                'gap_detected': False,
                'volume_confirmed': False,
                'first_candle_high': None,
                'first_candle_low': None,
                'first_candle_time': None,
                'opening_open_price': None,
                'monitor_start_time': None,
                'support_broken': False,
                'in_position': False,
                'entry_time': None,
                'entry_price': None,
                'breakout_confirmed': False,
                'monitor_completed': False,
                'entry_qty': None,
                'pnl_target_dollars': None,
                'traded_today': False,
                'last_vwap': None,
            }
        
        # Estadísticas
        self.total_trades = 0
        self.winning_trades = 0
        
        self.log_message("Volume Multiplayer Strategy inicializada")
        self.log_message(f"Monitoreando: {', '.join(self.parameters['symbols'])}")
        self.log_message(f"Gap threshold: {self.parameters['gap_threshold']*100}%, "
                        f"Volume multiplier: {self.parameters['volume_multiplier']}x")

    def _is_market_hours(self, dt_now):
        """Verifica si estamos en horarios de mercado (9:30-16:00 ET)"""
        et_time = dt_now.astimezone(pytz.timezone('US/Eastern')).time()
        return time(9, 30) <= et_time <= time(16, 0)

    def _is_opening_period(self, dt_now):
        """Devuelve True durante la ventana de entrada inicial (por defecto 9:30-10:30 ET)."""
        et = dt_now.astimezone(pytz.timezone('US/Eastern'))
        start = time(9, 30)
        end_minutes = 30 + (self.parameters.get("entry_window_minutes", 60) - 30)
        # por defecto 60 -> 10:30
        end_hour = 9 + end_minutes // 60
        end_min = 30 + end_minutes % 60
        end = time(end_hour, end_min)
        return start <= et.time() <= end

    def _get_previous_close(self, symbol):
        """Obtiene el precio de cierre del día anterior"""
        try:
            bars = self.get_historical_prices(symbol, 2, "day")
            if bars is None or len(bars.df) < 2:
                return None
            return bars.df['close'].iloc[-2]
        except Exception as e:
            self.log_message(f"Error obteniendo precio anterior para {symbol}: {e}")
            return None

    def _get_today_open(self, symbol):
        """Obtiene el precio de apertura de hoy (9:30 ET) si está disponible."""
        try:
            bars = self.get_historical_prices(symbol, 1, "day")
            if bars is None or len(bars.df) == 0:
                return None
            return float(bars.df['open'].iloc[-1])
        except Exception as e:
            self.log_message(f"Error obteniendo apertura para {symbol}: {e}")
            return None

    def _get_opening_bar_levels(self, symbol):
        """Devuelve (high, low, start_time) de la primera vela de 5m (9:30-9:35 ET).
        Maneja correctamente TZ/DST y aplica un fallback si la ventana exacta está vacía.
        """
        try:
            bars = self.get_historical_prices(symbol, 50, "minute")
            if bars is None or len(bars.df) == 0:
                return None, None, None

            df = bars.df.copy()
            # Asegurar zona horaria Eastern
            if df.index.tzinfo:
                df = df.tz_convert('US/Eastern')
            else:
                df = df.tz_localize('US/Eastern')

            tz = pytz.timezone('US/Eastern')
            today_et = self.get_datetime().astimezone(tz).date()
            day_df = df[df.index.date == today_et]
            if len(day_df) == 0:
                return None, None, None

            # Ventana exacta 9:30-9:35 ET
            start_dt = tz.localize(datetime.combine(today_et, time(9, 30)))
            end_dt = tz.localize(datetime.combine(today_et, time(9, 35)))
            window = day_df[(day_df.index >= start_dt) & (day_df.index < end_dt)]

            # Fallback: tomar la PRIMERA barra >= 9:30 y construir el rango con esa barra
            if len(window) == 0:
                first_after_open = day_df[day_df.index.time >= time(9, 30)]
                if len(first_after_open) == 0:
                    return None, None, None
                row = first_after_open.iloc[0]
                return float(row['high']), float(row['low']), first_after_open.index[0]

            return float(window['high'].max()), float(window['low'].min()), window.index[0]
        except Exception as e:
            self.log_message(f"Error obteniendo 1ra vela para {symbol}: {e}")
            return None, None, None

    def _opening_volume_ratio(self, symbol, lookback_days=20):
        """Compara volumen de la 1ra vela (hoy) vs promedio de la 1ra vela de los últimos N días."""
        try:
            bars = self.get_historical_prices(symbol, lookback_days * 78, "minute")
            if bars is None or len(bars.df) == 0:
                return None
            df = bars.df.copy()
            df = df.tz_convert('US/Eastern') if df.index.tzinfo else df.tz_localize('US/Eastern')
            # Agrupar por fecha y tomar 9:30-9:35 por día
            def first_bar_vol(g):
                start = time(9, 30)
                end = time(9, 35)
                g = g[(g.index.time >= start) & (g.index.time < end)]
                return g['volume'].sum()
            daily_vol = df.groupby(df.index.date).apply(first_bar_vol)
            today = self.get_datetime().astimezone(pytz.timezone('US/Eastern')).date()
            if today not in daily_vol.index:
                return None
            today_vol = float(daily_vol.loc[today])
            hist = daily_vol.drop(index=today)
            hist = hist.tail(lookback_days)
            if len(hist) == 0:
                return None
            avg = float(hist.mean())
            if avg == 0:
                return None
            return today_vol / avg
        except Exception as e:
            self.log_message(f"Error calculando opening volume ratio para {symbol}: {e}")
            return None

    def _get_average_volume(self, symbol, days=20):
        """Obtiene el volumen promedio de los últimos N días"""
        try:
            bars = self.get_historical_prices(symbol, days, "day")
            if bars is None or len(bars.df) < days:
                return None
            return bars.df['volume'].mean()
        except Exception as e:
            self.log_message(f"Error obteniendo volumen promedio para {symbol}: {e}")
            return None

    def _get_current_volume(self, symbol):
        """Obtiene el volumen actual acumulado del día"""
        try:
            # Para intradía, obtener datos de minutos desde apertura
            bars = self.get_historical_prices(symbol, 60, "minute")  # Última hora
            if bars is None or len(bars.df) == 0:
                return None
            
            # Sumar volumen desde apertura del día
            today = self.get_datetime().date()
            today_data = bars.df[bars.df.index.date == today]
            
            if len(today_data) == 0:
                return None
            
            return today_data['volume'].sum()
        except Exception:
            # Fallback: usar último volumen disponible
            bars = self.get_historical_prices(symbol, 1, "minute")
            if bars and len(bars.df) > 0:
                return bars.df['volume'].iloc[-1]
            return None

    def _analyze_gap_and_volume(self, symbol):
        """Analiza gap alcista (apertura vs cierre anterior) y volumen de la 1ra vela."""
        data = self.symbol_data[symbol]
        if data['gap_detected'] and data['volume_confirmed']:
            return True

        # Gap usando apertura de hoy
        today_open = self._get_today_open(symbol)
        prev_close = self._get_previous_close(symbol)
        if today_open is None or prev_close is None:
            return False
        gap = (today_open - prev_close) / prev_close
        if gap >= self.parameters["gap_threshold"]:
            data['gap_detected'] = True
            self.log_message(f"📈 {symbol} - Gap alcista detectado: {gap*100:.2f}% (Open vs Prev Close)")
        else:
            return False

        # Volumen de la primera vela (5m)
        vol_ratio = self._opening_volume_ratio(symbol, self.parameters.get("volume_lookback_days", 20))
        if vol_ratio is None:
            return False
        if vol_ratio >= self.parameters["volume_multiplier"]:
            data['volume_confirmed'] = True
            data['monitor_start_time'] = self.get_datetime()
            # setear niveles de primera vela desde fuente confiable
            hi, lo, start_ts = self._get_opening_bar_levels(symbol)
            data['first_candle_high'] = hi
            data['first_candle_low'] = lo
            data['first_candle_time'] = start_ts
            self.log_message(f"📊 {symbol} - Volumen 1ra vela: {vol_ratio:.2f}x del promedio | High {hi} Low {lo}")
            # Concise debug gap/vol
            try:
                if today_open is not None and prev_close is not None and vol_ratio is not None:
                    self.log_message(f"▶ {symbol} | GAP {( (today_open - prev_close) / prev_close )*100:.2f}% | VOL {vol_ratio:.2f}x")
            except Exception:
                pass
            return True
        else:
            self.log_message(f"🔍 {symbol} - Volumen 1ra vela insuficiente: {vol_ratio:.2f}x (req: {self.parameters['volume_multiplier']}x)")
            return False

    def _monitor_support_level(self, symbol):
        """Monitorea si se mantiene el nivel de soporte (low de primera vela)"""
        data = self.symbol_data[symbol]
        
        if not data['volume_confirmed'] or data['support_broken']:
            return False
        
        current_price = self.get_last_price(symbol)
        if current_price is None:
            return False
        
        # Establecer niveles de primera vela si no existen
        if data['first_candle_high'] is None:
            hi, lo, start_ts = self._get_opening_bar_levels(symbol)
            if hi is not None and lo is not None:
                data['first_candle_high'] = hi
                data['first_candle_low'] = lo
                data['first_candle_time'] = start_ts
                self.log_message(f"🎯 {symbol} - Niveles 1ra vela fijados: High {hi:.2f}, Low {lo:.2f}")
            else:
                return False
        
        # Verificar si se rompió el soporte
        if data['first_candle_low'] and current_price < data['first_candle_low']:
            data['support_broken'] = True
            self.log_message(f"❌ {symbol} - Soporte roto: {current_price:.2f} < {data['first_candle_low']:.2f}")
            return False
        
        # Verificar tiempo de monitoreo
        if data['monitor_start_time']:
            monitor_duration = (self.get_datetime() - data['monitor_start_time']).total_seconds() / 60
            if monitor_duration >= self.parameters["monitor_minutes"]:
                data['monitor_completed'] = True
                self.log_message(f"⏰ {symbol} - Período de monitoreo COMPLETADO ({monitor_duration:.0f} min)")
                return True  # Período completado exitosamente
        
        return False  # Continuar monitoreando

    def _check_breakout_entry(self, symbol):
        """Verifica si hay breakout para entrada"""
        data = self.symbol_data[symbol]

        # Una sola operación por símbolo por día
        if self.parameters.get("one_trade_per_symbol", True) and data.get('traded_today'):
            return False

        # Requerir que se haya completado el monitoreo del piso
        if not data.get('monitor_completed', False):
            return False

        # Solo permitir entradas dentro de la ventana inicial (ej. hasta 10:30 ET)
        if not self._is_opening_period(self.get_datetime()):
            return False

        if data['in_position'] or not data['volume_confirmed'] or data['support_broken']:
            return False
        
        current_price = self.get_last_price(symbol)
        if current_price is None or data['first_candle_high'] is None:
            return False

        # VWAP filter
        vwap_ok = True
        if self.parameters.get("vwap_filter", True):
            vwap = self._get_intraday_vwap(symbol)
            if vwap is not None:
                data['last_vwap'] = vwap
                vwap_ok = current_price > vwap
            else:
                vwap_ok = False
        
        # Verificar breakout del high de primera vela + VWAP filter
        if (current_price > data['first_candle_high']) and vwap_ok and (not data['breakout_confirmed']):
            data['breakout_confirmed'] = True
            
            # Contar posiciones actuales
            current_positions = sum(1 for d in self.symbol_data.values() if d['in_position'])
            
            if current_positions >= self.parameters["max_positions"]:
                self.log_message(f"⚠️ {symbol} - Breakout detectado pero max posiciones alcanzadas")
                return False
            
            # Dimensionar posición por asignación
            qty = self.parameters.get("position_size", 1)
            if self.parameters.get("use_allocation", False):
                alloc_cash = max(self.get_cash() * float(self.parameters.get("allocation_pct", 0.25)),
                                 float(self.parameters.get("min_allocation_dollars", 0)))
                qty = max(int(alloc_cash // current_price), 1)
            cost = qty * current_price
            cash = self.get_cash()

            if cash >= cost and qty > 0:
                # Ejecutar entrada
                order = self._submit_marketable_limit(symbol, side="buy", quantity=qty, last_price=current_price)
                if order is None:
                    return False
                
                # Actualizar tracking
                data['in_position'] = True
                data['entry_time'] = self.get_datetime()
                data['entry_price'] = current_price
                data['entry_qty'] = qty
                data['pnl_target_dollars'] = float(self.parameters.get("pnl_target_dollars", 500))
                data['traded_today'] = True
                
                self.log_message(f"🚀 {symbol} - ENTRADA: Breakout a {current_price:.2f} | Qty {qty} | Cost ${cost:.2f}")
                
                # Agregar líneas al gráfico
                self.add_line(f"{symbol} Price", current_price)
                self.add_line(f"{symbol} Entry", data['entry_price'])
                self.add_line(f"{symbol} High Level", data['first_candle_high'])
                
                return True
            else:
                self.log_message(f"❌ {symbol} - Capital insuficiente para entrada (Cash ${cash:.2f} < Cost ${cost:.2f})")
        
        return False

    def _manage_position(self, symbol):
        """Gestiona posición existente con TP/SL basados en subyacente y TP monetario proxy opciones"""
        data = self.symbol_data[symbol]
        if not data['in_position']:
            return

        current_price = self.get_last_price(symbol)
        if current_price is None or data['entry_price'] is None:
            return

        qty = int(data.get('entry_qty') or self.parameters.get('position_size', 1))
        if qty <= 0:
            qty = 1

        # P&L
        pnl_pct = (current_price - data['entry_price']) / data['entry_price']
        pnl_dollar = (current_price - data['entry_price']) * qty

        # Niveles subyacente (proxy opciones)
        tp_pct = float(self.parameters.get('underlying_tp_pct', 0.015))
        sl_pct = float(self.parameters.get('underlying_sl_pct', 0.010))
        tp_price = data['entry_price'] * (1 + tp_pct)
        sl_price = data['entry_price'] * (1 - sl_pct)

        target_pnl = data.get('pnl_target_dollars')

        # Tiempo en posición
        hold_minutes = 0
        if data['entry_time']:
            hold_minutes = (self.get_datetime() - data['entry_time']).total_seconds() / 60

        # Salida por pérdida de VWAP tras entrada (opcional)
        vwap_exit = False
        if self.parameters.get("vwap_filter", True):
            vwap = self._get_intraday_vwap(symbol)
            if vwap is not None:
                data['last_vwap'] = vwap
                if current_price < vwap:
                    vwap_exit = True

        # Señales de salida
        exit_reason = None
        if target_pnl is not None and pnl_dollar >= target_pnl:
            exit_reason = f"TP monetario +${target_pnl:.0f}"
        elif current_price >= tp_price:
            exit_reason = f"TP subyacente {tp_pct*100:.2f}%"
        elif current_price <= sl_price:
            exit_reason = f"SL subyacente {sl_pct*100:.2f}%"
        elif vwap_exit:
            exit_reason = "Salida por VWAP"
        elif hold_minutes >= self.parameters.get('max_hold_minutes', 60):
            exit_reason = f"Max Hold Time: {hold_minutes:.0f}min"

        # Trazas
        self.add_line(f"{symbol} Price", current_price)
        self.add_line(f"{symbol} P&L $", pnl_dollar)
        self.add_line(f"{symbol} P&L %", pnl_pct * 100)

        if not exit_reason:
            return

        # Salida
        order = self._submit_marketable_limit(symbol, side="sell", quantity=qty, last_price=current_price)
        if order is None:
            self.log_message(f"❌ {symbol} - No se pudo enviar orden de salida")
            return

        # Stats
        self.total_trades += 1
        if pnl_dollar > 0:
            self.winning_trades += 1

        self.log_message(
            f"📤 {symbol} - SALIDA: {exit_reason} | P&L ${pnl_dollar:.2f} ({pnl_pct*100:.2f}%) | Qty {qty}"
        )

        # Reset del símbolo
        self._reset_symbol_data(symbol)
        
    def _reset_symbol_data(self, symbol):
        """Resetea el tracking de un símbolo"""
        self.symbol_data[symbol] = {
            'gap_detected': False,
            'volume_confirmed': False,
            'first_candle_high': None,
            'first_candle_low': None,
            'first_candle_time': None,
            'opening_open_price': None,
            'monitor_start_time': None,
            'support_broken': False,
            'in_position': False,
            'entry_time': None,
            'entry_price': None,
            'breakout_confirmed': False,
            'monitor_completed': False,
            'entry_qty': None,
            'pnl_target_dollars': None,
            'traded_today': False,
            'last_vwap': None,
        }

    def _get_intraday_vwap(self, symbol):
        """Calcula VWAP intradía (desde 9:30 ET hasta ahora) usando datos de 1m/5m."""
        try:
            bars = self.get_historical_prices(symbol, 90, "minute")
            if bars is None or len(bars.df) == 0:
                return None
            df = bars.df.copy()
            tz = pytz.timezone('US/Eastern')
            if df.index.tzinfo:
                df = df.tz_convert(tz)
            else:
                df = df.tz_localize(tz)
            today = self.get_datetime().astimezone(tz).date()
            day_df = df[df.index.date == today]
            if len(day_df) == 0:
                return None
            # usar typical price
            tp = (day_df['high'] + day_df['low'] + day_df['close']) / 3.0
            vol = day_df['volume']
            if vol.sum() == 0:
                return None
            vwap = float((tp * vol).sum() / vol.sum())
            return vwap
        except Exception as e:
            self.log_message(f"Error calculando VWAP para {symbol}: {e}")
            return None

    def _submit_marketable_limit(self, symbol, side, quantity, last_price):
        """Envía una orden limit marketable con tope de slippage en bps."""
        try:
            bps = float(self.parameters.get("max_slippage_bps", 5))
            if bps < 0:
                bps = 0
            if side == "buy":
                limit_price = last_price * (1 + bps / 10000.0)
            else:
                limit_price = last_price * (1 - bps / 10000.0)
            order = self.create_order(
                symbol,
                quantity=quantity,
                side=side,
                type="limit",
                limit_price=limit_price
            )
            self.submit_order(order)
            return order
        except Exception as e:
            self.log_message(f"Error enviando orden limit para {symbol}: {e}")
            return None

    def on_trading_iteration(self):
        dt_now = self.get_datetime()
        
        # Verificar horarios de mercado
        if not self._is_market_hours(dt_now):
            return
        
        # Reset diario (al final del día)
        et_time = dt_now.astimezone(pytz.timezone('US/Eastern')).time()
        if et_time >= time(15, 50):  # 10 min antes del cierre
            self._daily_reset()
            return
        
        # Procesar cada símbolo
        for symbol in self.parameters["symbols"]:
            try:
                data = self.symbol_data[symbol]
                
                # Estado 1: Buscar gap y volumen durante la ventana inicial
                if self._is_opening_period(dt_now) and not data['volume_confirmed']:
                    self._analyze_gap_and_volume(symbol)
                
                # Estado 2: Monitorear soporte
                elif data['volume_confirmed'] and not data['support_broken']:
                    self._monitor_support_level(symbol)
                
                # Estado 3: Buscar breakout para entrada (solo si terminó el monitoreo)
                if (data['volume_confirmed'] and 
                    data.get('monitor_completed', False) and 
                    not data['support_broken'] and 
                    not data['in_position']):
                    self._check_breakout_entry(symbol)
                
                # Estado 4: Gestionar posición existente
                if data['in_position']:
                    self._manage_position(symbol)
                    
            except Exception as e:
                self.log_message(f"Error procesando {symbol}: {e}")
                continue

    def _daily_reset(self):
        """Reset diario al final del trading"""
        # Cerrar todas las posiciones abiertas
        for symbol in self.parameters["symbols"]:
            data = self.symbol_data[symbol]
            if data['in_position']:
                order = self.create_order(
                    symbol,
                    quantity=self.parameters["position_size"],
                    side="sell"
                )
                self.submit_order(order)
                
                self.log_message(f"🔔 {symbol} - Posición cerrada por fin de día")
        
        # Reset todos los símbolos
        for symbol in self.parameters["symbols"]:
            self._reset_symbol_data(symbol)
        
        # Log estadísticas del día
        if self.total_trades > 0:
            win_rate = (self.winning_trades / self.total_trades) * 100
            self.log_message(f"📊 Estadísticas del día: {self.total_trades} trades, "
                           f"Win Rate: {win_rate:.1f}%")


if __name__ == "__main__":
    IS_BACKTESTING = True
    
    if IS_BACKTESTING:
        from lumibot.backtesting import AlpacaBacktesting
        
        # Verificar configuración
        if not ALPACA_TEST_CONFIG:
            print("Error: Se requiere configuración ALPACA_TEST_CONFIG")
            exit()
        
        # Configurar fechas (período corto para estrategia intradía)
        tzinfo = pytz.timezone('America/New_York')
        backtesting_start = tzinfo.localize(dt.datetime(2023, 11, 1))
        backtesting_end = tzinfo.localize(dt.datetime(2023, 12, 1))
        
        print("=" * 60)
        print("Volume Multiplayer Strategy - Backtesting")
        print("=" * 60)
        print(f"Símbolos: {', '.join(['SOFI', 'TSLA', 'AMZN', 'META'])}")
        print(f"Período: {backtesting_start.date()} a {backtesting_end.date()}")
        print(f"Estrategia: Gap + Volume + Breakout Intradía")
        print("=" * 60)
        
        # Ejecutar backtest
        results, strategy = VolumeMultiplayerStrategy.run_backtest(
            datasource_class=AlpacaBacktesting,
            backtesting_start=backtesting_start,
            backtesting_end=backtesting_end,
            minutes_before_closing=0,
            benchmark_asset='QQQ',
            analyze_backtest=True,
            parameters={
                "symbols": ["NVDA", "AMD", "META", "SOFI"],
                "gap_threshold": 0.02,
                "volume_multiplier": 1.5,
                "monitor_minutes": 20,
                "take_profit_pct": 0.30,  # Más conservador para backtest
                "stop_loss_pct": 0.20,
                "position_size": 10,
                "entry_window_minutes": 60,
                "volume_lookback_days": 20,
                "opening_bar_minutes": 5,
                "use_allocation": True,
                "allocation_pct": 0.25,
                "min_allocation_dollars": 1000,
                "pnl_target_dollars": 500,
                "underlying_tp_pct": 0.015,
                "underlying_sl_pct": 0.010,
                "vwap_filter": True,
                "one_trade_per_symbol": True,
                "max_slippage_bps": 5,
            },
            show_progress_bar=True,
            timestep='minute',  # Datos por minuto para intradía
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
        print("Volume Multiplayer Strategy - Paper Trading")
        print("=" * 60)
        
        broker = Alpaca(ALPACA_CONFIG)
        strategy = VolumeMultiplayerStrategy(
            broker=broker,
            parameters={
                "symbols": ["SOFI", "TSLA", "AMZN", "META"],
                "gap_threshold": 0.02,
                "volume_multiplier": 1.5,
                "take_profit_pct": 0.50,
                "stop_loss_pct": 0.30,
                "position_size": 10,
            }
        )
        
        print("Ejecutando estrategia intradía en paper trading...")
        strategy.run_live()