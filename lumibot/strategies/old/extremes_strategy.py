import backtrader as bt
import numpy as np
from loguru import logger
from config.config import Config

class HistoricalExtremesStrategy(bt.Strategy):
    """
    Estrategia de trading basada en extremos históricos
    - Compra cuando el precio alcanza mínimos históricos
    - Vende cuando el precio alcanza máximos históricos
    """
    
    params = (
        ('lookback_period', Config.LOOKBACK_PERIOD),  # Período para calcular extremos
        ('min_volume', Config.MIN_VOLUME),            # Volumen mínimo
        ('max_position_size', Config.MAX_POSITION_SIZE), # Tamaño máximo de posición
        ('stop_loss_pct', 0.05),                      # Stop loss del 5%
        ('take_profit_pct', 0.15),                    # Take profit del 15%
    )
    
    def __init__(self):
        """Inicialización de la estrategia"""
        self.order = None
        self.buy_price = None
        self.buy_comm = None
        self.trades_count = 0
        self.winning_trades = 0
        
        # Indicadores para cada símbolo
        self.indicators = {}
        
        for data in self.datas:
            symbol = data._name
            self.indicators[symbol] = {
                'highest': bt.indicators.Highest(data.high, period=self.params.lookback_period),
                'lowest': bt.indicators.Lowest(data.low, period=self.params.lookback_period),
                'volume_ma': bt.indicators.SimpleMovingAverage(data.volume, period=20),
                'atr': bt.indicators.ATR(data, period=14),  # Average True Range para volatilidad
                'rsi': bt.indicators.RSI(data.close, period=14),  # RSI para momentum
            }
            
        logger.info(f"Estrategia inicializada para {len(self.datas)} símbolos")
    
    def log(self, txt, dt=None):
        """Función de logging"""
        dt = dt or self.datas[0].datetime.date(0)
        logger.info(f'{dt.isoformat()}: {txt}')
    
    def notify_order(self, order):
        """Notificación de órdenes"""
        if order.status in [order.Submitted, order.Accepted]:
            return
        
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f'COMPRA EJECUTADA - Precio: {order.executed.price:.2f}, '
                        f'Costo: {order.executed.value:.2f}, Comisión: {order.executed.comm:.2f}')
                self.buy_price = order.executed.price
                self.buy_comm = order.executed.comm
            else:
                self.log(f'VENTA EJECUTADA - Precio: {order.executed.price:.2f}, '
                        f'Costo: {order.executed.value:.2f}, Comisión: {order.executed.comm:.2f}')
        
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'Orden {order.status}')
        
        self.order = None
    
    def notify_trade(self, trade):
        """Notificación de trades cerrados"""
        if not trade.isclosed:
            return
        
        self.trades_count += 1
        if trade.pnl > 0:
            self.winning_trades += 1
        
        self.log(f'TRADE CERRADO - P&L Bruto: {trade.pnl:.2f}, P&L Neto: {trade.pnlcomm:.2f}')
        
        # Estadísticas
        win_rate = (self.winning_trades / self.trades_count) * 100 if self.trades_count > 0 else 0
        self.log(f'Trades totales: {self.trades_count}, Win Rate: {win_rate:.1f}%')
    
    def next(self):
        """Lógica principal de la estrategia ejecutada en cada barra"""
        
        for i, data in enumerate(self.datas):
            symbol = data._name
            
            # Verificar que tenemos suficientes datos para todos los indicadores
            if len(data) < max(self.params.lookback_period, 20, 14):  # 20 para volume_ma, 14 para ATR y RSI
                continue
            
            # Obtener indicadores para este símbolo
            indicators = self.indicators[symbol]
            
            current_price = data.close[0]
            current_volume = data.volume[0]
            highest = indicators['highest'][0]
            lowest = indicators['lowest'][0]
            volume_ma = indicators['volume_ma'][0]
            atr = indicators['atr'][0]
            rsi = indicators['rsi'][0]
            
            # Verificar volumen mínimo
            if current_volume < self.params.min_volume or current_volume < volume_ma * 0.5:
                continue
            
            # Obtener posición actual para este símbolo
            position = self.getposition(data)
            
            # Lógica de compra - Mínimo histórico
            if not position and self._is_historical_low(current_price, lowest, atr, rsi):
                size = self._calculate_position_size(data, current_price)
                if size > 0:
                    self.order = self.buy(data=data, size=size)
                    self.log(f'{symbol} - SEÑAL COMPRA - Precio: {current_price:.2f} '
                            f'(Mínimo histórico: {lowest:.2f}), Tamaño: {size}')
            
            # Lógica de venta - Máximo histórico o stop loss/take profit
            elif position:
                should_sell = False
                reason = ""
                
                # Máximo histórico
                if self._is_historical_high(current_price, highest, atr, rsi):
                    should_sell = True
                    reason = f"Máximo histórico: {highest:.2f}"
                
                # Stop loss
                elif self.buy_price and current_price <= self.buy_price * (1 - self.params.stop_loss_pct):
                    should_sell = True
                    reason = f"Stop Loss: {self.buy_price * (1 - self.params.stop_loss_pct):.2f}"
                
                # Take profit
                elif self.buy_price and current_price >= self.buy_price * (1 + self.params.take_profit_pct):
                    should_sell = True
                    reason = f"Take Profit: {self.buy_price * (1 + self.params.take_profit_pct):.2f}"
                
                if should_sell:
                    self.order = self.close(data=data)
                    self.log(f'{symbol} - SEÑAL VENTA - Precio: {current_price:.2f} ({reason})')
    
    def _is_historical_low(self, current_price, lowest, atr, rsi):
        """Determina si el precio actual está en un mínimo histórico"""
        # Precio debe estar muy cerca del mínimo histórico
        price_threshold = lowest * 1.02  # 2% de tolerancia
        
        # Condiciones adicionales para filtrar señales
        volatility_ok = atr > 0  # Debe haber volatilidad
        oversold = rsi < 30      # RSI indica sobreventa
        
        return (current_price <= price_threshold and 
                volatility_ok and 
                oversold)
    
    def _is_historical_high(self, current_price, highest, atr, rsi):
        """Determina si el precio actual está en un máximo histórico"""
        # Precio debe estar muy cerca del máximo histórico
        price_threshold = highest * 0.98  # 2% de tolerancia
        
        # Condiciones adicionales
        volatility_ok = atr > 0  # Debe haber volatilidad
        overbought = rsi > 70    # RSI indica sobrecompra
        
        return (current_price >= price_threshold and 
                volatility_ok and 
                overbought)
    
    def _calculate_position_size(self, data, price):
        """Calcula el tamaño de la posición basado en el risk management"""
        # Valor total del portafolio
        portfolio_value = self.broker.getvalue()
        
        # Validaciones básicas
        if portfolio_value <= 0 or price <= 0:
            return 0
        
        # Máximo valor a invertir en esta posición
        max_investment = portfolio_value * self.params.max_position_size
        
        # Verificar que la inversión mínima sea viable
        if max_investment < price:  # No podemos comprar ni 1 acción
            return 0
        
        # Número de acciones que podemos comprar
        shares = int(max_investment / price)
        
        # Verificar que tenemos suficiente cash
        available_cash = self.broker.getcash()
        required_cash = shares * price
        
        if required_cash > available_cash:
            shares = int(available_cash / price)
        
        return max(0, shares)
    
    def stop(self):
        """Función ejecutada al final del backtest"""
        portfolio_value = self.broker.getvalue()
        self.log(f'Valor final del portafolio: ${portfolio_value:,.2f}')
        
        if self.trades_count > 0:
            win_rate = (self.winning_trades / self.trades_count) * 100
            self.log(f'Estadísticas finales - Trades: {self.trades_count}, '
                    f'Win Rate: {win_rate:.1f}%')
        else:
            self.log('No se ejecutaron trades durante el período') 