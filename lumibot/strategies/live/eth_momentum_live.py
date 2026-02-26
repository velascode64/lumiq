"""
Estrategia ETH Momentum para Trading en Vivo
Basada en la correlación ETH/BTC pero enfocada solo en ETH con señales más frecuentes
"""

from datetime import datetime, timedelta
from typing import Optional
import pandas as pd

from lumibot.strategies.strategy import Strategy
from lumibot.entities import Asset


class ETHMomentumLive(Strategy):
    """
    Estrategia de momentum para ETH basada en:
    1. Momentum de ETH vs BTC
    2. Señales técnicas (RSI, EMA)
    3. Gestión de riesgo con stop-loss y take-profit
    """
    
    def initialize(self):
        # Configuración de timing
        self.sleeptime = "5M"  # Ejecutar cada 5 minutos
        self.set_market("24/7")  # Crypto opera 24/7
        
        # Assets
        self.eth_asset = Asset(symbol='ETH', asset_type='crypto')
        self.btc_asset = Asset(symbol='BTC', asset_type='crypto')
        
        # Configuración de la estrategia
        self.position_size_pct = 0.20  # 20% del portfolio por trade
        self.stop_loss_pct = 0.05      # Stop-loss 5%
        self.take_profit_pct = 0.10    # Take-profit 10%
        self.max_hold_hours = 24       # Máximo 24 horas en posición
        
        # Parámetros técnicos
        self.rsi_oversold = 30
        self.rsi_overbought = 70
        self.ema_short_period = 20
        self.ema_long_period = 50
        
        # Estado de la estrategia
        self.entry_price = None
        self.entry_time = None
        self.current_position = 0
        self.last_signal_time = None
        
        # Estadísticas
        self.total_trades = 0
        self.winning_trades = 0
        self.start_time = datetime.now()
        
        # Log inicial
        self.log_message("=" * 60)
        self.log_message("ETH MOMENTUM STRATEGY - LIVE TRADING")
        self.log_message("=" * 60)
        self.log_message(f"Position size: {self.position_size_pct*100}%")
        self.log_message(f"Stop loss: {self.stop_loss_pct*100}%")
        self.log_message(f"Take profit: {self.take_profit_pct*100}%")
        self.log_message(f"Check frequency: {self.sleeptime}")
        self.log_message("=" * 60)
    
    def on_trading_iteration(self):
        """Lógica principal ejecutada cada 5 minutos"""
        try:
            current_time = self.get_datetime()
            
            # Log de iteración
            self.log_message(f"\n{'─'*50}")
            self.log_message(f"ITERATION - {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
            self.log_message(f"{'─'*50}")
            
            # Obtener precios actuales
            eth_price = self.get_last_price(self.eth_asset)
            btc_price = self.get_last_price(self.btc_asset)
            
            if not eth_price or not btc_price:
                self.log_message("❌ No se pudieron obtener precios")
                return
            
            # Log estado del portfolio
            self._log_portfolio_status(eth_price)
            
            # Obtener datos históricos
            eth_data = self.get_historical_prices(self.eth_asset, 100, "minute")
            btc_data = self.get_historical_prices(self.btc_asset, 100, "minute")
            
            if not eth_data or not btc_data:
                self.log_message("❌ No se pudieron obtener datos históricos")
                return
            
            # Calcular indicadores técnicos
            signals = self._calculate_signals(eth_data, btc_data, eth_price, btc_price)
            
            # Gestionar posición existente
            if self.current_position != 0:
                self._manage_existing_position(eth_price, current_time)
            
            # Buscar nuevas entradas si no hay posición
            elif self.current_position == 0:
                self._check_entry_signals(signals, eth_price, current_time)
            
        except Exception as e:
            self.log_message(f"❌ Error en iteración: {str(e)}")
    
    def _log_portfolio_status(self, eth_price: float):
        """Log del estado actual del portfolio"""
        portfolio_value = self.portfolio_value
        cash = self.cash
        
        # Obtener posición actual de ETH
        eth_position = self.get_position(self.eth_asset)
        eth_quantity = eth_position.quantity if eth_position else 0
        eth_value = float(eth_quantity) * eth_price if eth_quantity > 0 else 0
        
        self.log_message(f"💰 Portfolio: ${portfolio_value:,.2f} | Cash: ${cash:,.2f}")
        
        if eth_quantity > 0:
            if self.entry_price:
                pnl_pct = (eth_price - self.entry_price) / self.entry_price * 100
                pnl_color = "green" if pnl_pct >= 0 else "red"
                self.log_message(f"📈 ETH Position: {eth_quantity:.6f} @ ${eth_price:.2f} = ${eth_value:,.2f}")
                self.log_message(f"📊 P&L: {pnl_pct:+.2f}%", color=pnl_color)
            else:
                self.log_message(f"📈 ETH Position: {eth_quantity:.6f} @ ${eth_price:.2f} = ${eth_value:,.2f}")
        else:
            self.log_message("📈 No ETH position")
    
    def _calculate_signals(self, eth_data, btc_data, eth_price: float, btc_price: float) -> dict:
        """Calcula señales técnicas para ETH"""
        eth_df = eth_data.df
        btc_df = btc_data.df
        
        signals = {}
        
        # 1. Momentum ETH vs BTC (últimos 60 minutos)
        if len(eth_df) >= 60 and len(btc_df) >= 60:
            eth_return_1h = (eth_df['close'].iloc[-1] - eth_df['close'].iloc[-60]) / eth_df['close'].iloc[-60]
            btc_return_1h = (btc_df['close'].iloc[-1] - btc_df['close'].iloc[-60]) / btc_df['close'].iloc[-60]
            
            # ETH outperforming BTC es señal alcista
            relative_performance = eth_return_1h - btc_return_1h
            signals['relative_performance'] = relative_performance
            
            self.log_message(f"📊 ETH 1h: {eth_return_1h*100:+.2f}% | BTC 1h: {btc_return_1h*100:+.2f}%")
            self.log_message(f"📊 Relative Performance: {relative_performance*100:+.2f}%")
        
        # 2. RSI para ETH
        if len(eth_df) >= 14:
            rsi = self._calculate_rsi(eth_df['close'], 14)
            signals['rsi'] = rsi
            self.log_message(f"📊 ETH RSI: {rsi:.1f}")
        
        # 3. EMA Crossover
        if len(eth_df) >= self.ema_long_period:
            ema_short = eth_df['close'].ewm(span=self.ema_short_period).mean().iloc[-1]
            ema_long = eth_df['close'].ewm(span=self.ema_long_period).mean().iloc[-1]
            
            signals['ema_short'] = ema_short
            signals['ema_long'] = ema_long
            signals['ema_bullish'] = ema_short > ema_long
            
            self.log_message(f"📊 EMA{self.ema_short_period}: ${ema_short:.2f} | EMA{self.ema_long_period}: ${ema_long:.2f}")
        
        # 4. Volatilidad (precio vs EMA de 20 períodos)
        if len(eth_df) >= 20:
            price_vs_ema = (eth_price - signals.get('ema_short', eth_price)) / signals.get('ema_short', eth_price)
            signals['price_vs_ema'] = price_vs_ema
        
        return signals
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> float:
        """Calcula RSI"""
        try:
            delta = prices.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            return rsi.iloc[-1]
        except:
            return 50  # Valor neutro si hay error
    
    def _check_entry_signals(self, signals: dict, eth_price: float, current_time: datetime):
        """Verifica señales de entrada"""
        
        # Evitar señales demasiado frecuentes (mínimo 15 minutos entre señales)
        if (self.last_signal_time and 
            (current_time - self.last_signal_time).total_seconds() < 900):  # 15 min
            return
        
        # Señales alcistas
        bullish_signals = []
        
        # 1. ETH outperforming BTC significativamente
        relative_perf = signals.get('relative_performance', 0)
        if relative_perf > 0.02:  # ETH 2% mejor que BTC en 1h
            bullish_signals.append(f"ETH outperforming BTC by {relative_perf*100:.2f}%")
        
        # 2. RSI oversold (oportunidad de compra)
        rsi = signals.get('rsi', 50)
        if rsi < self.rsi_oversold:
            bullish_signals.append(f"RSI oversold ({rsi:.1f})")
        
        # 3. Precio por encima de EMA corta y EMAs en tendencia alcista
        ema_bullish = signals.get('ema_bullish', False)
        price_vs_ema = signals.get('price_vs_ema', 0)
        if ema_bullish and price_vs_ema > 0.01:  # 1% por encima de EMA
            bullish_signals.append("EMA bullish crossover")
        
        # 4. Momentum fuerte en ETH
        if relative_perf > 0.01 and rsi > 45:  # Momentum positivo sin sobrecompra
            bullish_signals.append("Strong ETH momentum")
        
        # Ejecutar compra si hay al menos 2 señales alcistas
        if len(bullish_signals) >= 2:
            self._execute_buy_order(eth_price, current_time, bullish_signals)
        
        # Señales bajistas para posibles ventas
        bearish_signals = []
        
        if relative_perf < -0.02:  # ETH underperforming BTC
            bearish_signals.append(f"ETH underperforming BTC by {abs(relative_perf)*100:.2f}%")
        
        if rsi > self.rsi_overbought:
            bearish_signals.append(f"RSI overbought ({rsi:.1f})")
        
        if bearish_signals:
            self.log_message(f"⚠️ Bearish signals: {', '.join(bearish_signals)}")
    
    def _execute_buy_order(self, eth_price: float, current_time: datetime, signals: list):
        """Ejecuta orden de compra"""
        
        # Calcular cantidad basada en % del portfolio
        cash_available = self.cash
        position_value = cash_available * self.position_size_pct
        quantity = position_value / eth_price
        
        if cash_available >= position_value:
            # Crear y enviar orden
            order = self.create_order(
                self.eth_asset,
                quantity=quantity,
                side="buy"
            )
            self.submit_order(order)
            
            # Actualizar estado
            self.entry_price = eth_price
            self.entry_time = current_time
            self.current_position = quantity
            self.last_signal_time = current_time
            
            self.log_message(f"\n🟢 BUY ORDER EXECUTED!")
            self.log_message(f"   Quantity: {quantity:.6f} ETH")
            self.log_message(f"   Price: ${eth_price:.2f}")
            self.log_message(f"   Value: ${position_value:.2f}")
            self.log_message(f"   Signals: {', '.join(signals)}")
            self.log_message(f"🟢" * 30)
            
        else:
            self.log_message(f"❌ Insufficient cash for buy order: ${cash_available:.2f} < ${position_value:.2f}")
    
    def _manage_existing_position(self, eth_price: float, current_time: datetime):
        """Gestiona posición existente con stop-loss y take-profit"""
        
        if not self.entry_price or not self.entry_time:
            self.log_message("⚠️ Missing entry data for position management")
            return
        
        # Calcular P&L
        pnl_pct = (eth_price - self.entry_price) / self.entry_price
        hold_duration = current_time - self.entry_time
        hold_hours = hold_duration.total_seconds() / 3600
        
        self.log_message(f"📊 Position P&L: {pnl_pct*100:+.2f}% | Hold time: {hold_hours:.1f}h")
        
        # Condiciones de salida
        exit_reason = None
        
        # Take profit
        if pnl_pct >= self.take_profit_pct:
            exit_reason = f"TAKE PROFIT: {pnl_pct*100:.1f}%"
        
        # Stop loss
        elif pnl_pct <= -self.stop_loss_pct:
            exit_reason = f"STOP LOSS: {pnl_pct*100:.1f}%"
        
        # Max hold time
        elif hold_hours >= self.max_hold_hours:
            exit_reason = f"MAX HOLD TIME: {hold_hours:.1f}h"
        
        # Ejecutar salida si hay condición
        if exit_reason:
            self._execute_sell_order(eth_price, current_time, exit_reason, pnl_pct)
    
    def _execute_sell_order(self, eth_price: float, current_time: datetime, reason: str, pnl_pct: float):
        """Ejecuta orden de venta"""
        
        # Obtener cantidad actual
        eth_position = self.get_position(self.eth_asset)
        if not eth_position or eth_position.quantity <= 0:
            self.log_message("❌ No ETH position to sell")
            return
        
        quantity = eth_position.quantity
        
        # Crear y enviar orden
        order = self.create_order(
            self.eth_asset,
            quantity=quantity,
            side="sell"
        )
        self.submit_order(order)
        
        # Calcular P&L en dólares
        pnl_dollars = pnl_pct * self.entry_price * float(quantity)
        
        # Actualizar estadísticas
        self.total_trades += 1
        if pnl_pct > 0:
            self.winning_trades += 1
        
        # Log de la venta
        color = "green" if pnl_pct >= 0 else "red"
        self.log_message(f"\n🔴 SELL ORDER EXECUTED!", color=color)
        self.log_message(f"   Reason: {reason}", color=color)
        self.log_message(f"   Quantity: {quantity:.6f} ETH", color=color)
        self.log_message(f"   Price: ${eth_price:.2f}", color=color)
        self.log_message(f"   P&L: ${pnl_dollars:+.2f} ({pnl_pct*100:+.2f}%)", color=color)
        
        # Estadísticas
        win_rate = (self.winning_trades / self.total_trades) * 100 if self.total_trades > 0 else 0
        self.log_message(f"   Stats: {self.total_trades} trades, {win_rate:.1f}% win rate", color=color)
        self.log_message(f"🔴" * 30, color=color)
        
        # Reset estado
        self._reset_position_state()
    
    def _reset_position_state(self):
        """Resetea el estado de la posición"""
        self.entry_price = None
        self.entry_time = None
        self.current_position = 0
    
    def on_filled_order(self, position, order, price, quantity, multiplier):
        """Se ejecuta cuando una orden se completa"""
        super().on_filled_order(position, order, price, quantity, multiplier)
        
        side = order.side.upper()
        symbol = order.asset.symbol
        total_value = float(quantity) * float(price)
        
        self.log_message(f"\n✅ ORDER FILLED - {side} {quantity:.6f} {symbol} @ ${price:.2f}")
        self.log_message(f"   Total value: ${total_value:,.2f}")
    
    def on_aborted_order(self, order):
        """Se ejecuta cuando una orden es abortada"""
        super().on_aborted_order(order)
        self.log_message(f"❌ ORDER ABORTED: {order.side} {order.quantity} {order.asset.symbol}")
        
        # Reset si era una orden de compra
        if order.side == "buy":
            self._reset_position_state()