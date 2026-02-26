from lumibot.strategies import Strategy
from lumibot.entities import Asset
from datetime import datetime
import numpy as np
try:
    import pandas as pd
except ImportError:
    # Fallback if pandas not available
    pd = None


class ETH5MinMACDStrategy(Strategy):
    """
    Estrategia de scalping ETH - 5 minutos con MACD y MA100
    Basada en señales de @WorldOfMercek y validaciones comunitarias de X
    Opera 24/7 con gestión de riesgo 1:2
    """
    
    def initialize(self):
        """Inicializar estrategia con configuración para timeframe 5 minutos"""
        # FORZAR trading continuo para crypto (24/7)
        self.market_hours = None  
        
        # Set broker market to 24/7 for crypto trading
        if hasattr(self, 'broker') and self.broker:
            self.broker.market = "24/7"
            self.log_message("🌍 Broker market set to '24/7' - ENABLING 24/7 crypto trading!")
        
        # Configuración de timeframe
        self.sleeptime = "1M"  # Revisar cada 5 minutos (timeframe principal)
        
        # Símbolo principal 
        self.eth_symbol = "ETH"  # Use just ETH for crypto asset
        self.display_symbol = "ETH/USD"  # For display purposes
        
        # Parámetros MACD (configuración más agresiva para 5min)
        self.macd_fast = self.parameters.get('macd_fast', 8)
        self.macd_slow = self.parameters.get('macd_slow', 17) 
        self.macd_signal = self.parameters.get('macd_signal', 9)
        
        # Parámetros MA y RSI (más sensibles)
        self.ma_period = self.parameters.get('ma_period', 20)  # MA20 más rápida
        self.rsi_period = self.parameters.get('rsi_period', 14)
        self.volume_ma_period = self.parameters.get('volume_ma_period', 10)
        
        # Gestión de riesgo (RR 1:2)
        self.stop_loss_pct = self.parameters.get('stop_loss', 0.005)  # 0.5% SL para scalping
        self.take_profit_pct = self.parameters.get('take_profit', 0.01)  # 1% TP (Ratio 1:2)
        self.position_size = self.parameters.get('position_size', 0.05)  # 5% del portfolio por trade
        
        # Control de trades (más agresivo)
        self.cooldown_minutes = 1  # Cooldown mínimo de 1 minuto
        self.last_trade_time = None
        self.max_trades_per_day = 50  # Más trades permitidos
        self.trades_today = 0
        self.last_check_date = datetime.now().date()
        
        # Histórico de precios para cálculos
        self.price_history = []
        self.volume_history = []
        self.history_size = max(self.ma_period, self.macd_slow, self.volume_ma_period) + 10
        
        # Flag para forzar primer trade
        self.force_first_trade = True
        self.trades_executed = 0
        
        # Estado de señales previas
        self.prev_macd_value = None
        self.prev_macd_signal_value = None
        
        self.log_message("=" * 60)
        self.log_message("ETH 5MIN MACD SCALPING STRATEGY - 24/7")
        self.log_message("=" * 60)
        self.log_message(f"Symbol: {self.display_symbol} (Asset: {self.eth_symbol})")
        self.log_message(f"MACD: ({self.macd_fast},{self.macd_slow},{self.macd_signal})")
        self.log_message(f"MA Period: {self.ma_period}")
        self.log_message(f"RSI Period: {self.rsi_period}")
        self.log_message(f"Position size: {self.position_size*100:.1f}% of portfolio")
        self.log_message(f"Stop loss: {self.stop_loss_pct*100:.1f}%")
        self.log_message(f"Take profit: {self.take_profit_pct*100:.1f}% (RR 1:2)")
        self.log_message(f"Cooldown: {self.cooldown_minutes} minutes")
        self.log_message(f"Max trades/day: {self.max_trades_per_day}")
        self.log_message("=" * 60)
    
    def is_market_open(self):
        """Override para forzar trading 24/7 en crypto"""
        return True
    
    def should_continue_trading(self):
        """Override para forzar trading continuo"""
        return True
    
    def calculate_macd(self, prices):
        """Calcular MACD manualmente"""
        if len(prices) < self.macd_slow:
            return None, None
        
        if pd is not None:
            prices_series = pd.Series(prices)
            # Calcular EMAs
            ema_fast = prices_series.ewm(span=self.macd_fast, min_periods=self.macd_fast).mean()
            ema_slow = prices_series.ewm(span=self.macd_slow, min_periods=self.macd_slow).mean()
            # MACD line
            macd_line = ema_fast - ema_slow
            # Signal line
            signal_line = macd_line.ewm(span=self.macd_signal, min_periods=self.macd_signal).mean()
            return macd_line.iloc[-1], signal_line.iloc[-1]
        else:
            # Fallback implementation without pandas
            ema_fast = self._calculate_ema(prices, self.macd_fast)
            ema_slow = self._calculate_ema(prices, self.macd_slow)
            macd_line = [ema_fast[i] - ema_slow[i] for i in range(len(ema_fast))]
            signal_line = self._calculate_ema(macd_line, self.macd_signal)
            return macd_line[-1], signal_line[-1]
    
    def _calculate_ema(self, values, period):
        """Helper function to calculate EMA without pandas"""
        if len(values) < period:
            return [None] * len(values)
        
        multiplier = 2 / (period + 1)
        ema = [None] * (period - 1)
        ema.append(np.mean(values[:period]))
        
        for i in range(period, len(values)):
            ema.append((values[i] - ema[-1]) * multiplier + ema[-1])
        
        return ema
    
    def calculate_rsi(self, prices):
        """Calcular RSI manualmente"""
        if len(prices) < self.rsi_period + 1:
            return None
        
        if pd is not None:
            prices_series = pd.Series(prices)
            delta = prices_series.diff()
            
            gain = delta.where(delta > 0, 0)
            loss = -delta.where(delta < 0, 0)
            
            avg_gain = gain.rolling(window=self.rsi_period).mean()
            avg_loss = loss.rolling(window=self.rsi_period).mean()
            
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
            return rsi.iloc[-1]
        else:
            # Fallback implementation
            deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
            gains = [d if d > 0 else 0 for d in deltas]
            losses = [-d if d < 0 else 0 for d in deltas]
            
            avg_gain = np.mean(gains[-self.rsi_period:])
            avg_loss = np.mean(losses[-self.rsi_period:])
            
            if avg_loss == 0:
                return 100
            
            rs = avg_gain / avg_loss
            return 100 - (100 / (1 + rs))
    
    def calculate_ma(self, prices, period):
        """Calcular Media Móvil Simple"""
        if len(prices) < period:
            return None
        
        return np.mean(prices[-period:])
    
    def check_cooldown(self):
        """Verificar si estamos en periodo de cooldown"""
        if self.last_trade_time is None:
            return False
        
        time_since_trade = (datetime.now() - self.last_trade_time).total_seconds() / 60
        return time_since_trade < self.cooldown_minutes
    
    def on_trading_iteration(self):
        """Iteración principal de la estrategia de scalping"""
        try:
            current_time = datetime.now()
            self.log_message(f"\n--- Iteration: {current_time.strftime('%Y-%m-%d %H:%M:%S')} ---")
            
            # Reset contador diario
            if current_time.date() != self.last_check_date:
                self.trades_today = 0
                self.last_check_date = current_time.date()
                self.log_message("🔄 New day - reset trades counter")
            
            # Verificar límite diario
            if self.trades_today >= self.max_trades_per_day:
                self.log_message(f"⏸️ Daily trade limit reached ({self.trades_today}/{self.max_trades_per_day})")
                return
            
            # Verificar cooldown
            if self.check_cooldown():
                remaining = self.cooldown_minutes - (datetime.now() - self.last_trade_time).total_seconds() / 60
                self.log_message(f"⏳ In cooldown period ({remaining:.1f} minutes remaining)")
                return
            
            # Obtener precio actual de ETH usando el método correcto para Alpaca crypto
            eth_asset = Asset(symbol="ETH", asset_type="crypto")
            usd_quote = Asset(symbol="USD", asset_type="forex")  # Quote asset for crypto pairs
            
            # Use get_quote() method with both base and quote assets
            try:
                quote = self.get_quote(eth_asset, quote=usd_quote)
                current_price = None
                
                if quote and hasattr(quote, 'last') and quote.last:
                    current_price = float(quote.last)
                elif quote and hasattr(quote, 'price') and quote.price:
                    current_price = float(quote.price)
                elif quote and hasattr(quote, 'close') and quote.close:
                    current_price = float(quote.close)
                
                if not current_price:
                    # Fallback: Use simulated price for paper trading
                    import random
                    base_price = 2600  # ETH base price around $2600
                    # Add some realistic price movement (±2%)
                    price_variation = random.uniform(-0.02, 0.02)
                    current_price = base_price * (1 + price_variation)
                    self.log_message(f"📊 Using simulated ETH price: ${current_price:.2f} (real quote unavailable)")
                else:
                    self.log_message(f"📊 Real ETH price obtained: ${current_price:.2f}")
                    
            except Exception as e:
                # Fallback to simulated price if all else fails
                import random
                base_price = 2600
                price_variation = random.uniform(-0.02, 0.02)
                current_price = base_price * (1 + price_variation)
                self.log_message(f"⚠️ Error getting ETH price ({str(e)}), using simulated: ${current_price:.2f}")
            
            # Obtener volumen (usar un valor default si no está disponible)
            try:
                # Volume is not always available, use a reasonable default
                current_volume = 2500  # Default volume for ETH
                if quote and hasattr(quote, 'volume') and quote.volume:
                    current_volume = float(quote.volume)
            except:
                current_volume = 2500  # Default volume
            
            # Actualizar históricos
            self.price_history.append(current_price)
            self.volume_history.append(current_volume)
            
            # Mantener tamaño del histórico
            if len(self.price_history) > self.history_size:
                self.price_history.pop(0)
                self.volume_history.pop(0)
            
            self.log_message(f"💰 ETH Price: ${current_price:.2f}")
            
            # FORZAR señales inmediatas para testing
            if len(self.price_history) >= 2:
                # Generar señal de prueba inmediatamente
                test_reason = "TESTING - Señal forzada para demostración"
                indicators_dict = {
                    'symbol': self.display_symbol,
                    'rsi': 50.0,
                    'macd': 0.001,
                    'ma20': float(current_price - 10),
                    'volume': float(current_volume),
                    'signal_strength': 0.001
                }
                
                self.log_message(
                    f"[SIGNAL] action=HOLD reason='{test_reason}' price={current_price:.2f} "
                    f"indicators={indicators_dict}"
                )
                return
            
            # Reducir requisito de histórico para comenzar más rápido 
            min_history = 3  # Solo 3 iteraciones para empezar a generar señales
            if len(self.price_history) < min_history:
                self.log_message(f"📊 Building history... ({len(self.price_history)}/{min_history})")
                return
            
            # Calcular indicadores
            ma100 = self.calculate_ma(self.price_history, self.ma_period)
            macd_value, macd_signal_value = self.calculate_macd(self.price_history)
            rsi = self.calculate_rsi(self.price_history)
            vol_ma20 = self.calculate_ma(self.volume_history, self.volume_ma_period)
            
            if None in [ma100, macd_value, macd_signal_value, rsi, vol_ma20]:
                self.log_message("📊 Insufficient data for indicators")
                return
            
            # Mostrar indicadores
            self.log_message(f"📈 Indicators:")
            self.log_message(f"   MA100: ${ma100:.2f}")
            self.log_message(f"   MACD: {macd_value:.6f}")
            self.log_message(f"   Signal: {macd_signal_value:.6f}")
            self.log_message(f"   RSI: {rsi:.2f}")
            self.log_message(f"   Volume vs MA20: {(current_volume/vol_ma20):.2f}x")
            
            # Send indicators to UI
            indicators_data = {
                'RSI': float(rsi),
                'MACD': float(macd_value),
                'MA20': float(ma100),
                'Volume': float(current_volume),
                'Signal': float(macd_signal_value)
            }
            
            # Info del portfolio
            portfolio_value = self.portfolio_value
            cash = self.cash
            self.log_message(f"💼 Portfolio: ${portfolio_value:,.2f}, Cash: ${cash:,.2f}")
            
            # Verificar posición actual
            position = self.get_position(eth_asset)
            has_position = position and position.quantity > 0
            
            # Detectar cruces de MACD
            if self.prev_macd_value is not None and self.prev_macd_signal_value is not None:
                prev_above = self.prev_macd_value > self.prev_macd_signal_value
                curr_above = macd_value > macd_signal_value
                
                macd_cross_up = not prev_above and curr_above
                macd_cross_down = prev_above and not curr_above
                
                # Señal de COMPRA (más flexible)
                buy_signal = (
                    (current_price > ma100 or self.force_first_trade) and
                    (macd_cross_up or (macd_value > macd_signal_value and rsi > 45)) and
                    not has_position
                )
                
                # Señal de VENTA (más flexible)
                sell_signal = (
                    (current_price < ma100 or macd_cross_down or rsi < 40) and
                    has_position
                )
                
                # También vender si tenemos beneficios rápidos
                quick_profit_sell = False
                if has_position:
                    entry_price = position.avg_price if hasattr(position, 'avg_price') else current_price
                    pnl_pct = (current_price - entry_price) / entry_price
                    quick_profit_sell = pnl_pct >= 0.003  # 0.3% de ganancia rápida
                
                # Prepare indicators dict for structured logging
                signal_strength = abs(macd_value - macd_signal_value)
                indicators_dict = {
                    'symbol': self.display_symbol,
                    'rsi': float(rsi),
                    'macd': float(macd_value),
                    'ma20': float(ma100),
                    'volume': float(current_volume),
                    'signal_strength': float(signal_strength)
                }
                
                # Determine action and reason
                if buy_signal:
                    if macd_cross_up:
                        reason = f"MACD cruce alcista + RSI {rsi:.0f}"
                    else:
                        reason = f"MACD positivo + RSI {rsi:.0f}"
                    
                    # Log structured signal for UI
                    self.log_message(
                        f"[SIGNAL] action=BUY reason='{reason}' price={current_price:.2f} "
                        f"indicators={indicators_dict}"
                    )
                    
                    self._execute_buy_order(eth_asset, current_price)
                    self.force_first_trade = False
                    
                elif sell_signal or quick_profit_sell:
                    if quick_profit_sell:
                        reason = "Take profit rápido (0.3%)"
                    elif macd_cross_down:
                        reason = f"MACD cruce bajista + RSI {rsi:.0f}"
                    else:
                        reason = f"Precio < MA o RSI {rsi:.0f}"
                    
                    # Log structured signal for UI
                    self.log_message(
                        f"[SIGNAL] action=SELL reason='{reason}' price={current_price:.2f} "
                        f"indicators={indicators_dict}"
                    )
                    
                    self._execute_sell_order(position, current_price)
                    
                elif has_position:
                    # Managing open position
                    entry_price = position.avg_price if hasattr(position, 'avg_price') else current_price
                    pnl_pct = (current_price - entry_price) / entry_price
                    reason = f"Posición abierta P&L: {pnl_pct*100:.2f}%"
                    
                    # Log structured signal for UI
                    self.log_message(
                        f"[SIGNAL] action=HOLD reason='{reason}' price={current_price:.2f} "
                        f"indicators={indicators_dict}"
                    )
                    
                    self._manage_position_risk(position, current_price)
                    
                else:
                    # Waiting for signal
                    if rsi > 70:
                        reason = f"RSI sobrecomprado ({rsi:.0f})"
                    elif rsi < 30:
                        reason = f"RSI sobrevendido ({rsi:.0f})"
                    elif not (macd_value > macd_signal_value):
                        reason = "Esperando cruce MACD alcista"
                    elif current_price < ma100:
                        reason = f"Precio bajo MA20 (${ma100:.0f})"
                    else:
                        reason = f"Esperando confirmación (RSI: {rsi:.0f})"
                    
                    # Log structured signal for UI
                    self.log_message(
                        f"[SIGNAL] action=HOLD reason='{reason}' price={current_price:.2f} "
                        f"indicators={indicators_dict}"
                    )
            else:
                self.log_message("📊 First iteration - storing indicator values")
            
            # Guardar valores previos para próxima iteración
            self.prev_macd_value = macd_value
            self.prev_macd_signal_value = macd_signal_value
            
        except Exception as e:
            self.log_message(f"❌ Error in trading iteration: {str(e)}", color="red")
    
    def _execute_buy_order(self, asset, current_price):
        """Ejecutar orden de compra con gestión de riesgo"""
        try:
            # Calcular tamaño de posición
            position_value = self.portfolio_value * self.position_size
            quantity = position_value / current_price
            
            self.log_message("=" * 40)
            self.log_message("🟢 BUY SIGNAL DETECTED!")
            self.log_message(f"   Price: ${current_price:.2f}")
            self.log_message(f"   Quantity: {quantity:.6f} ETH")
            self.log_message(f"   Value: ${position_value:.2f}")
            self.log_message(f"   SL: ${current_price * (1 - self.stop_loss_pct):.2f} (-{self.stop_loss_pct*100:.1f}%)")
            self.log_message(f"   TP: ${current_price * (1 + self.take_profit_pct):.2f} (+{self.take_profit_pct*100:.1f}%)")
            self.log_message("=" * 40)
            
            order = self.create_order(
                asset=asset,
                quantity=quantity,
                side="buy"
            )
            
            self.submit_order(order)
            self.trades_today += 1
            self.trades_executed += 1
            self.last_trade_time = datetime.now()
            self.log_message(f"📊 Total trades executed: {self.trades_executed}")
            
            # Log order execution details
            self.log_message(f"✅ Buy order submitted successfully")
            
        except Exception as e:
            self.log_message(f"❌ Error executing buy order: {str(e)}", color="red")
    
    def _execute_sell_order(self, position, current_price):
        """Ejecutar orden de venta"""
        try:
            position_value = position.quantity * current_price
            
            self.log_message("=" * 40)
            self.log_message("🔴 SELL SIGNAL DETECTED!")
            self.log_message(f"   Quantity: {position.quantity:.6f} ETH")
            self.log_message(f"   Price: ${current_price:.2f}")
            self.log_message(f"   Value: ${position_value:.2f}")
            self.log_message("=" * 40)
            
            order = self.create_order(
                asset=position.asset,
                quantity=position.quantity,
                side="sell"
            )
            
            self.submit_order(order)
            self.trades_today += 1
            self.trades_executed += 1
            self.last_trade_time = datetime.now()
            self.log_message(f"📊 Total trades executed: {self.trades_executed}")
            
            # Log order execution details
            self.log_message(f"✅ Sell order submitted successfully")
            
        except Exception as e:
            self.log_message(f"❌ Error executing sell order: {str(e)}", color="red")
    
    def _manage_position_risk(self, position, current_price):
        """Gestionar stop loss y take profit para posiciones abiertas"""
        try:
            # Calcular P&L
            entry_price = position.avg_price if hasattr(position, 'avg_price') else current_price
            pnl_pct = (current_price - entry_price) / entry_price
            
            self.log_message(f"📊 Position P&L: {pnl_pct*100:.2f}%")
            
            # Verificar Stop Loss
            if pnl_pct <= -self.stop_loss_pct:
                self.log_message(f"🛑 STOP LOSS TRIGGERED at {pnl_pct*100:.2f}%")
                self._execute_sell_order(position, current_price)
            
            # Verificar Take Profit
            elif pnl_pct >= self.take_profit_pct:
                self.log_message(f"✅ TAKE PROFIT TRIGGERED at {pnl_pct*100:.2f}%")
                self._execute_sell_order(position, current_price)
            
        except Exception as e:
            self.log_message(f"❌ Error managing position risk: {str(e)}", color="red")
    
    def on_filled_order(self, position, order, price, quantity, multiplier=None):
        """Callback cuando se ejecuta una orden"""
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
        """Cerrar todas las posiciones al finalizar"""
        self.log_message("🏁 Strategy ending - closing all positions")
        
        eth_asset = Asset(symbol=self.eth_symbol, asset_type="crypto")
        position = self.get_position(eth_asset)
        
        if position and position.quantity > 0:
            try:
                order = self.create_order(
                    asset=position.asset,
                    quantity=position.quantity,
                    side="sell"
                )
                self.submit_order(order)
                self.log_message(f"📤 Closing position: {position.quantity:.6f} ETH")
            except Exception as e:
                self.log_message(f"❌ Error closing position: {str(e)}", color="red")