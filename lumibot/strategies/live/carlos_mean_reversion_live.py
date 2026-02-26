"""
Carlos Mean Reversion Live Strategy
Versión live optimizada de la estrategia de Carlos para trading en tiempo real

Características adaptadas para live trading:
- Trading continuo durante horarios de mercado
- Monitoreo cada 5 minutos en lugar de diario
- Gestión de riesgo mejorada con stops dinámicos
- Take profits escalonados más frecuentes
- Filtros técnicos adaptados para alta frecuencia
- Logging detallado para Telegram notifications
- Parámetros optimizados para diferentes símbolos
"""

import datetime as dt
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from lumibot.strategies import Strategy
from lumibot.entities import Asset


class CarlosMeanReversionLiveStrategy(Strategy):
    """
    Estrategia live de Mean Reversion con momentum trading.
    Optimizada para ejecución en tiempo real con notificaciones.
    """
    
    def initialize(self):
        """Inicializar estrategia live"""
        # Trading continuo cada 5 minutos
        self.sleeptime = "5M"
        
        # Parámetros configurables desde Telegram bot
        self.symbol = self.parameters.get('symbol', 'QQQ')
        self.position_size_usd = self.parameters.get('position_size_usd', 1000)
        self.daily_gain_threshold = self.parameters.get('daily_gain_threshold', 0.04)  # 4%
        self.trailing_stop_pct = self.parameters.get('trailing_stop_pct', 0.02)  # 2%
        self.rsi_oversold = self.parameters.get('rsi_oversold', 30)
        self.rsi_overbought = self.parameters.get('rsi_overbought', 75)
        
        # Take profits escalonados más agresivos para live
        self.take_profit_1 = self.parameters.get('take_profit_1', 0.08)  # 8%
        self.take_profit_2 = self.parameters.get('take_profit_2', 0.15)  # 15% 
        self.take_profit_3 = self.parameters.get('take_profit_3', 0.25)  # 25%
        self.partial_exit_pct = self.parameters.get('partial_exit_pct', 0.33)  # 33%
        
        # Parámetros específicos por símbolo (optimizados para live)
        self.symbol_configs = {
            'QQQ': {'daily_gain_threshold': 0.03, 'trailing_stop_pct': 0.015, 'rsi_oversold': 32},
            'SPY': {'daily_gain_threshold': 0.025, 'trailing_stop_pct': 0.015, 'rsi_oversold': 30},
            'AAPL': {'daily_gain_threshold': 0.035, 'trailing_stop_pct': 0.02, 'rsi_oversold': 33},
            'GOOGL': {'daily_gain_threshold': 0.04, 'trailing_stop_pct': 0.018, 'rsi_oversold': 32},
            'TSLA': {'daily_gain_threshold': 0.05, 'trailing_stop_pct': 0.025, 'rsi_oversold': 28},
            'MSFT': {'daily_gain_threshold': 0.03, 'trailing_stop_pct': 0.018, 'rsi_oversold': 35},
            'AMZN': {'daily_gain_threshold': 0.04, 'trailing_stop_pct': 0.02, 'rsi_oversold': 30},
            'NVDA': {'daily_gain_threshold': 0.06, 'trailing_stop_pct': 0.03, 'rsi_oversold': 25},
        }
        
        # Aplicar configuración específica del símbolo
        if self.symbol in self.symbol_configs:
            config = self.symbol_configs[self.symbol]
            self.daily_gain_threshold = config.get('daily_gain_threshold', self.daily_gain_threshold)
            self.trailing_stop_pct = config.get('trailing_stop_pct', self.trailing_stop_pct)
            self.rsi_oversold = config.get('rsi_oversold', self.rsi_oversold)
        
        # Estado de la estrategia
        self.position_status = 'READY_TO_BUY'  # READY_TO_BUY, HOLDING, COOLDOWN
        self.cooldown_until = None
        self.cooldown_hours = 2  # 2 horas de cooldown después de venta
        
        # Tracking de posición
        self.entry_price = None
        self.entry_time = None
        self.recent_high = None
        self.trailing_stop = None
        self.original_quantity = None
        self.remaining_quantity = None
        
        # Take profits tracking
        self.take_profit_1_hit = False
        self.take_profit_2_hit = False
        self.take_profit_3_hit = False
        
        # Datos para análisis
        self.price_buffer = []
        self.high_52w = None
        self.last_rsi = None
        self.last_price_check = None
        
        # Estadísticas
        self.trades_completed = 0
        self.winning_trades = 0
        self.total_pnl = 0
        self.partial_exits = 0
        
        # Logging inicial
        self.log_message("=" * 70)
        self.log_message("CARLOS MEAN REVERSION LIVE STRATEGY")
        self.log_message("=" * 70)
        self.log_message(f"📈 Symbol: {self.symbol}")
        self.log_message(f"💰 Position Size: ${self.position_size_usd:,}")
        self.log_message(f"🎯 Daily Gain Threshold: {self.daily_gain_threshold*100:.1f}%")
        self.log_message(f"🛑 Trailing Stop: {self.trailing_stop_pct*100:.1f}%")
        self.log_message(f"📊 RSI Range: {self.rsi_oversold}-{self.rsi_overbought}")
        self.log_message(f"⏰ Check Interval: {self.sleeptime}")
        self.log_message("=" * 70)
        
        # Obtener datos iniciales
        self._update_52w_high()
    
    def _update_52w_high(self):
        """Actualizar máximo de 52 semanas"""
        try:
            ticker = yf.Ticker(self.symbol)
            hist = ticker.history(period="1y")
            if not hist.empty:
                self.high_52w = hist['High'].max()
                self.log_message(f"📊 52W High for {self.symbol}: ${self.high_52w:.2f}")
        except Exception as e:
            self.log_message(f"⚠️ Error getting 52W high: {e}")
    
    def _calculate_rsi(self, period=14):
        """Calcular RSI usando datos de Lumibot"""
        try:
            asset = Asset(symbol=self.symbol, asset_type="stock")
            bars = self.get_historical_prices(asset, period + 5, "day")
            
            if bars is None or len(bars.df) < period + 1:
                return self.last_rsi  # Usar último RSI conocido
            
            prices = bars.df['close'].values
            deltas = np.diff(prices)
            gains = np.where(deltas > 0, deltas, 0)
            losses = np.where(deltas < 0, -deltas, 0)
            
            avg_gain = np.mean(gains[-period:])
            avg_loss = np.mean(losses[-period:])
            
            if avg_loss == 0:
                rsi = 100
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
                
            self.last_rsi = rsi
            return rsi
            
        except Exception as e:
            self.log_message(f"⚠️ Error calculating RSI: {e}")
            return self.last_rsi or 50  # Default neutral RSI
    
    def _calculate_sma(self, period):
        """Calcular SMA"""
        try:
            asset = Asset(symbol=self.symbol, asset_type="stock")
            bars = self.get_historical_prices(asset, period + 2, "day")
            
            if bars is None or len(bars.df) < period:
                return None
                
            return bars.df['close'].tail(period).mean()
            
        except Exception as e:
            self.log_message(f"⚠️ Error calculating SMA{period}: {e}")
            return None
    
    def _is_price_consolidating(self):
        """Detectar consolidación de precio (condición clave de Carlos)"""
        try:
            asset = Asset(symbol=self.symbol, asset_type="stock")
            bars = self.get_historical_prices(asset, 10, "day")
            
            if bars is None or len(bars.df) < 5:
                return False
            
            prices = bars.df['close'].values
            high_prices = bars.df['high'].values
            low_prices = bars.df['low'].values
            
            # Calcular rango de consolidación
            recent_high = np.max(high_prices[-5:])
            recent_low = np.min(low_prices[-5:])
            
            # Consolidación si el rango es pequeño
            consolidation_range = (recent_high - recent_low) / recent_low
            is_consolidating = consolidation_range < 0.03  # 3% range
            
            if is_consolidating:
                self.log_message(f"📊 Price consolidating: {consolidation_range*100:.1f}% range")
                
            return is_consolidating
            
        except Exception as e:
            self.log_message(f"⚠️ Error checking consolidation: {e}")
            return False
    
    def _should_enter_position(self, current_price):
        """Determinar si debe entrar en posición"""
        
        # Verificar cooldown
        if self.cooldown_until:
            current_time = datetime.now()
            if current_time < self.cooldown_until:
                remaining = (self.cooldown_until - current_time).total_seconds() / 60
                if remaining > 5:  # Solo log si quedan más de 5 minutos
                    self.log_message(f"⏸️ Cooldown active: {remaining:.0f} minutes remaining")
                return False
            else:
                self.cooldown_until = None
                self.position_status = 'READY_TO_BUY'
                self.log_message("✅ Cooldown period ended - ready to trade")
        
        # Calcular indicadores
        rsi = self._calculate_rsi()
        sma_20 = self._calculate_sma(20)
        sma_50 = self._calculate_sma(50)
        
        if not rsi or not sma_20 or not sma_50:
            self.log_message("⚠️ Missing technical indicators")
            return False
        
        # Actualizar 52W high cada hora
        current_time = datetime.now()
        if (not self.last_price_check or 
            (current_time - self.last_price_check).total_seconds() > 3600):
            self._update_52w_high()
            self.last_price_check = current_time
        
        # Condiciones de entrada
        conditions = {
            'rsi_favorable': self.rsi_oversold <= rsi <= self.rsi_overbought,
            'above_sma_20': current_price > sma_20 * 1.005,  # 0.5% buffer
            'above_sma_50': current_price > sma_50,
            'sma_trend': sma_20 > sma_50 * 0.998,  # Trend alcista
            'not_near_52w_high': not self.high_52w or current_price < self.high_52w * 0.92,
            'price_consolidating': self._is_price_consolidating(),
        }
        
        # Log de análisis técnico
        self.log_message(f"\\n🔍 TECHNICAL ANALYSIS - {self.symbol}")
        self.log_message(f"   💰 Current Price: ${current_price:.2f}")
        self.log_message(f"   📊 RSI: {rsi:.1f} (target: {self.rsi_oversold}-{self.rsi_overbought})")
        self.log_message(f"   📈 SMA20: ${sma_20:.2f} | SMA50: ${sma_50:.2f}")
        if self.high_52w:
            self.log_message(f"   🏔️ 52W High: ${self.high_52w:.2f} ({current_price/self.high_52w*100:.1f}%)")
        
        # Verificar condiciones
        passed_conditions = [k for k, v in conditions.items() if v]
        failed_conditions = [k for k, v in conditions.items() if not v]
        
        self.log_message(f"   ✅ Passed: {', '.join(passed_conditions)}")
        if failed_conditions:
            self.log_message(f"   ❌ Failed: {', '.join(failed_conditions)}")
        
        # Requerir al menos 4 de 6 condiciones para entrada
        entry_signal = len(passed_conditions) >= 4
        
        if entry_signal:
            self.log_message(f"🟢 ENTRY SIGNAL CONFIRMED ({len(passed_conditions)}/6 conditions)")
        
        return entry_signal
    
    def _should_exit_position(self, current_price):
        """Determinar si debe salir de posición"""
        
        if not self.entry_price or not self.original_quantity:
            return False, 0, ""
        
        # Calcular ganancias
        total_gain_pct = (current_price - self.entry_price) / self.entry_price
        unrealized_pnl = (current_price - self.entry_price) * self.remaining_quantity
        
        # Calcular ganancia diaria
        if self.entry_time:
            time_held = datetime.now() - self.entry_time
            daily_gain_pct = total_gain_pct * (86400 / max(time_held.total_seconds(), 3600))  # Anualizar
        else:
            daily_gain_pct = 0
        
        # Tamaño de venta parcial
        partial_size = max(1, int(self.original_quantity * self.partial_exit_pct))
        
        # Take Profit 1: 8%
        if (not self.take_profit_1_hit and 
            total_gain_pct >= self.take_profit_1 and 
            self.remaining_quantity > partial_size):
            self.take_profit_1_hit = True
            return True, partial_size, f"Take Profit 1: {total_gain_pct*100:.1f}% (+${unrealized_pnl:.2f})"
        
        # Take Profit 2: 15%
        if (not self.take_profit_2_hit and 
            total_gain_pct >= self.take_profit_2 and 
            self.remaining_quantity > partial_size):
            self.take_profit_2_hit = True
            return True, partial_size, f"Take Profit 2: {total_gain_pct*100:.1f}% (+${unrealized_pnl:.2f})"
        
        # Take Profit 3: 25%
        if (not self.take_profit_3_hit and 
            total_gain_pct >= self.take_profit_3):
            self.take_profit_3_hit = True
            return True, partial_size, f"Take Profit 3: {total_gain_pct*100:.1f}% (+${unrealized_pnl:.2f})"
        
        # Condiciones de salida completa
        
        # 1. Ganancia diaria objetivo alcanzada
        if daily_gain_pct >= self.daily_gain_threshold:
            return True, 'ALL', f"Daily gain target: {daily_gain_pct*100:.1f}% (+${unrealized_pnl:.2f})"
        
        # 2. Cerca del máximo 52 semanas
        if (self.high_52w and current_price >= self.high_52w * 0.98):
            return True, 'ALL', f"Near 52W high: ${self.high_52w:.2f} (+${unrealized_pnl:.2f})"
        
        # 3. Trailing stop
        if self.trailing_stop and current_price <= self.trailing_stop:
            loss_pct = (current_price - self.entry_price) / self.entry_price * 100
            return True, 'ALL', f"Trailing stop hit: ${self.trailing_stop:.2f} ({loss_pct:+.1f}%)"
        
        # 4. Ganancia excepcional (50% para live trading)
        if total_gain_pct >= 0.50:
            return True, 'ALL', f"Exceptional gain: {total_gain_pct*100:.1f}% (+${unrealized_pnl:.2f})"
        
        # 5. Stop loss severo (protección)
        if total_gain_pct <= -0.08:  # -8% stop loss
            return True, 'ALL', f"Stop loss protection: {total_gain_pct*100:.1f}% (${unrealized_pnl:.2f})"
        
        return False, 0, ""
    
    def on_trading_iteration(self):
        """Iteración principal de trading"""
        try:
            current_time = datetime.now()
            self.log_message(f"\\n📊 === Trading Check: {current_time.strftime('%H:%M:%S')} ===")
            
            # Obtener precio actual
            asset = Asset(symbol=self.symbol, asset_type="stock")
            current_price = self.get_last_price(asset)
            
            if not current_price:
                self.log_message("⚠️ Could not get current price")
                return
            
            self.log_message(f"💰 {self.symbol}: ${current_price:.2f}")
            
            # Obtener posición actual
            position = self.get_position(asset)
            current_qty = position.quantity if position else 0
            
            # Log de estado actual
            portfolio_value = self.portfolio_value
            cash_available = self.cash
            
            self.log_message(f"💼 Portfolio: ${portfolio_value:,.2f} | Cash: ${cash_available:,.2f}")
            if current_qty > 0:
                position_value = current_qty * current_price
                if self.entry_price:
                    pnl = (current_price - self.entry_price) * current_qty
                    pnl_pct = (current_price - self.entry_price) / self.entry_price * 100
                    self.log_message(f"📈 Position: {current_qty} shares = ${position_value:,.2f} | P&L: ${pnl:+,.2f} ({pnl_pct:+.1f}%)")
            
            # Lógica principal según estado
            if self.position_status == 'READY_TO_BUY' and current_qty == 0:
                # Buscar oportunidad de entrada
                if self._should_enter_position(current_price):
                    self._execute_buy_order(current_price, cash_available)
                
            elif self.position_status == 'HOLDING' and current_qty > 0:
                # Gestionar posición existente
                self._manage_existing_position(current_price, current_qty)
            
            elif current_qty == 0 and self.position_status == 'HOLDING':
                # Posición cerrada externamente
                self.log_message("⚠️ Position was closed externally - resetting strategy state")
                self._reset_position_state()
                
        except Exception as e:
            self.log_message(f"❌ Error in trading iteration: {str(e)}", color="red")
    
    def _execute_buy_order(self, current_price, cash_available):
        """Ejecutar orden de compra"""
        try:
            # Calcular cantidad de acciones
            max_shares = int(self.position_size_usd / current_price)
            cash_needed = max_shares * current_price
            
            if cash_available < cash_needed:
                max_shares = int(cash_available * 0.95 / current_price)  # 95% del cash disponible
                cash_needed = max_shares * current_price
            
            if max_shares < 1:
                self.log_message(f"⚠️ Insufficient cash for purchase. Need ${cash_needed:.2f}, have ${cash_available:.2f}")
                return
            
            # Crear y enviar orden
            asset = Asset(symbol=self.symbol, asset_type="stock")
            order = self.create_order(
                asset=asset,
                quantity=max_shares,
                side="buy"
            )
            
            self.submit_order(order)
            
            # Actualizar estado
            self.entry_price = current_price
            self.entry_time = datetime.now()
            self.recent_high = current_price
            self.trailing_stop = current_price * (1 - self.trailing_stop_pct)
            self.original_quantity = max_shares
            self.remaining_quantity = max_shares
            self.position_status = 'HOLDING'
            
            # Reset take profit flags
            self.take_profit_1_hit = False
            self.take_profit_2_hit = False
            self.take_profit_3_hit = False
            
            self.log_message("\\n🟢 BUY ORDER EXECUTED")
            self.log_message(f"   📈 Symbol: {self.symbol}")
            self.log_message(f"   💰 Quantity: {max_shares} shares")
            self.log_message(f"   💵 Price: ${current_price:.2f}")
            self.log_message(f"   💸 Total: ${cash_needed:.2f}")
            self.log_message(f"   🛑 Trailing Stop: ${self.trailing_stop:.2f}")
            
        except Exception as e:
            self.log_message(f"❌ Error executing buy order: {str(e)}", color="red")
    
    def _manage_existing_position(self, current_price, current_qty):
        """Gestionar posición existente"""
        
        # Actualizar trailing stop si precio sube
        if current_price > self.recent_high:
            self.recent_high = current_price
            new_trailing_stop = current_price * (1 - self.trailing_stop_pct)
            
            if new_trailing_stop > self.trailing_stop:
                old_stop = self.trailing_stop
                self.trailing_stop = new_trailing_stop
                self.log_message(f"📈 New High: ${current_price:.2f} | Trailing Stop: ${old_stop:.2f} → ${self.trailing_stop:.2f}")
        
        # Verificar condiciones de salida
        should_sell, sell_quantity, reason = self._should_exit_position(current_price)
        
        if should_sell:
            self._execute_sell_order(current_price, sell_quantity, reason)
    
    def _execute_sell_order(self, current_price, sell_quantity, reason):
        """Ejecutar orden de venta"""
        try:
            # Determinar cantidad a vender
            if sell_quantity == 'ALL':
                sell_qty = self.remaining_quantity
            else:
                sell_qty = min(sell_quantity, self.remaining_quantity)
            
            if sell_qty < 1:
                return
            
            # Crear y enviar orden
            asset = Asset(symbol=self.symbol, asset_type="stock")
            order = self.create_order(
                asset=asset,
                quantity=sell_qty,
                side="sell"
            )
            
            self.submit_order(order)
            
            # Calcular P&L
            pnl = (current_price - self.entry_price) * sell_qty
            pnl_pct = (current_price - self.entry_price) / self.entry_price * 100
            
            if sell_quantity == 'ALL':
                # Venta completa
                self.log_message("\\n🔴 SELL ORDER EXECUTED - COMPLETE EXIT")
                self.log_message(f"   📉 Symbol: {self.symbol}")
                self.log_message(f"   💰 Quantity: {sell_qty} shares")
                self.log_message(f"   💵 Price: ${current_price:.2f}")
                self.log_message(f"   💸 Total: ${sell_qty * current_price:.2f}")
                self.log_message(f"   📊 P&L: ${pnl:+.2f} ({pnl_pct:+.1f}%)")
                self.log_message(f"   📝 Reason: {reason}")
                
                # Actualizar estadísticas
                self.trades_completed += 1
                self.total_pnl += pnl
                if pnl > 0:
                    self.winning_trades += 1
                
                # Reset y activar cooldown
                self._reset_position_state()
                
            else:
                # Venta parcial
                self.remaining_quantity -= sell_qty
                self.partial_exits += 1
                
                self.log_message("\\n🟡 SELL ORDER EXECUTED - PARTIAL EXIT")
                self.log_message(f"   📉 Symbol: {self.symbol}")
                self.log_message(f"   💰 Quantity: {sell_qty} shares (keeping {self.remaining_quantity})")
                self.log_message(f"   💵 Price: ${current_price:.2f}")
                self.log_message(f"   💸 Total: ${sell_qty * current_price:.2f}")
                self.log_message(f"   📊 P&L: ${pnl:+.2f} ({pnl_pct:+.1f}%)")
                self.log_message(f"   📝 Reason: {reason}")
                
        except Exception as e:
            self.log_message(f"❌ Error executing sell order: {str(e)}", color="red")
    
    def _reset_position_state(self):
        """Reset del estado después de cerrar posición"""
        self.position_status = 'COOLDOWN'
        self.cooldown_until = datetime.now() + timedelta(hours=self.cooldown_hours)
        
        # Reset tracking variables
        self.entry_price = None
        self.entry_time = None
        self.recent_high = None
        self.trailing_stop = None
        self.original_quantity = None
        self.remaining_quantity = None
        
        # Reset take profit flags
        self.take_profit_1_hit = False
        self.take_profit_2_hit = False
        self.take_profit_3_hit = False
        
        self.log_message(f"⏸️ Entering {self.cooldown_hours}h cooldown until {self.cooldown_until.strftime('%H:%M')}")
    
    def on_filled_order(self, position, order, price, quantity, multiplier):
        """Callback cuando una orden se completa"""
        side = order.side.upper()
        symbol = order.asset.symbol
        total_value = float(quantity) * float(price)
        
        self.log_message("\\n" + "🎉" * 30)
        self.log_message("ORDER FILLED CONFIRMATION")
        self.log_message(f"  {side}: {quantity} shares of {symbol}")
        self.log_message(f"  Fill Price: ${price:.2f}")
        self.log_message(f"  Fill Value: ${total_value:,.2f}")
        self.log_message(f"  Time: {datetime.now().strftime('%H:%M:%S')}")
        self.log_message("🎉" * 30 + "\\n")
    
    def on_strategy_end(self):
        """Estadísticas finales al terminar estrategia"""
        self.log_message("\\n" + "=" * 70)
        self.log_message("CARLOS MEAN REVERSION STRATEGY - FINAL STATS")
        self.log_message("=" * 70)
        self.log_message(f"📊 Symbol Traded: {self.symbol}")
        self.log_message(f"🔢 Total Trades: {self.trades_completed}")
        self.log_message(f"✅ Winning Trades: {self.winning_trades}")
        self.log_message(f"📈 Win Rate: {(self.winning_trades/max(self.trades_completed,1)*100):.1f}%")
        self.log_message(f"💰 Total P&L: ${self.total_pnl:+,.2f}")
        self.log_message(f"📊 Partial Exits: {self.partial_exits}")
        self.log_message(f"💼 Final Portfolio: ${self.portfolio_value:,.2f}")
        self.log_message("=" * 70)
        
        # Cerrar cualquier posición restante
        try:
            asset = Asset(symbol=self.symbol, asset_type="stock")
            position = self.get_position(asset)
            if position and position.quantity > 0:
                self.log_message(f"🔒 Closing remaining position: {position.quantity} shares")
                order = self.create_order(asset=asset, quantity=position.quantity, side="sell")
                self.submit_order(order)
        except Exception as e:
            self.log_message(f"⚠️ Error closing final position: {e}")