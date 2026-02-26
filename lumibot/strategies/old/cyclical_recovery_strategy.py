import backtrader as bt
import numpy as np
from loguru import logger
from config.config import Config

class CyclicalRecoveryStrategy(bt.Strategy):
    """
    Estrategia de trading basada en ciclos de recuperación
    - Compra cuando las acciones caen más de 5% (busca el mínimo)
    - Usa trailing stop loss una vez hay recuperación
    - Vende en máximos históricos o por stop loss
    """
    
    params = (
        ('drop_threshold', 0.05),                     # Caída del 5% para activar compra
        ('lookback_period', getattr(Config, 'LOOKBACK_PERIOD', 50)),  # Período para calcular mínimos/máximos
        ('min_volume', getattr(Config, 'MIN_VOLUME', 100000)),        # Volumen mínimo
        ('max_position_size', getattr(Config, 'MAX_POSITION_SIZE', 0.3)), # Tamaño máximo de posición
        ('initial_stop_loss', 0.02),                  # Stop loss inicial del 2%
        ('trailing_stop_step', 0.01),                 # Paso del trailing stop (1%)
        ('recovery_threshold', 0.02),                 # Umbral de recuperación para activar trailing (2%)
    )
    
    def __init__(self):
        """Inicialización de la estrategia"""
        self.order = None
        self.trades_count = 0
        self.winning_trades = 0
        
        # Tracking por símbolo
        self.positions_data = {}
        
        # Indicadores para cada símbolo
        self.indicators = {}
        
        for data in self.datas:
            symbol = data._name
            self.indicators[symbol] = {
                'highest': bt.indicators.Highest(data.high, period=self.params.lookback_period),
                'lowest': bt.indicators.Lowest(data.low, period=self.params.lookback_period),
                'volume_ma': bt.indicators.SimpleMovingAverage(data.volume, period=20),
                'sma_20': bt.indicators.SimpleMovingAverage(data.close, period=20),  # Para detectar caídas
            }
            
            # Inicializar tracking de posiciones
            self.positions_data[symbol] = {
                'buy_price': None,
                'highest_price_since_buy': None,
                'trailing_stop': None,
                'in_recovery': False,
                'reference_high': None,  # Para detectar caídas del 5%
            }
            
        logger.info(f"Estrategia Cíclica inicializada para {len(self.datas)} símbolos")
    
    def log(self, txt, dt=None):
        """Función de logging"""
        dt = dt or self.datas[0].datetime.date(0)
        logger.info(f'{dt.isoformat()}: {txt}')
    
    def notify_order(self, order):
        """Notificación de órdenes"""
        if order.status in [order.Submitted, order.Accepted]:
            return
        
        if order.status in [order.Completed]:
            symbol = order.data._name
            if order.isbuy():
                self.log(f'{symbol} - COMPRA EJECUTADA - Precio: {order.executed.price:.2f}, '
                        f'Tamaño: {order.executed.size}, Comisión: {order.executed.comm:.2f}')
                
                # Actualizar tracking de la posición
                self.positions_data[symbol]['buy_price'] = order.executed.price
                self.positions_data[symbol]['highest_price_since_buy'] = order.executed.price
                self.positions_data[symbol]['trailing_stop'] = order.executed.price * (1 - self.params.initial_stop_loss)
                self.positions_data[symbol]['in_recovery'] = False
                
            else:
                self.log(f'{symbol} - VENTA EJECUTADA - Precio: {order.executed.price:.2f}, '
                        f'Tamaño: {order.executed.size}, Comisión: {order.executed.comm:.2f}')
                
                # Reset tracking
                self.positions_data[symbol] = {
                    'buy_price': None,
                    'highest_price_since_buy': None,
                    'trailing_stop': None,
                    'in_recovery': False,
                    'reference_high': None,
                }
        
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
            if len(data) < max(self.params.lookback_period, 20):  # 20 para volume_ma y sma_20
                continue
            
            # Obtener indicadores y datos actuales
            indicators = self.indicators[symbol]
            position_data = self.positions_data[symbol]
            
            current_price = data.close[0]
            current_volume = data.volume[0]
            highest_lookback = indicators['highest'][0]
            lowest_lookback = indicators['lowest'][0]
            volume_ma = indicators['volume_ma'][0]
            sma_20 = indicators['sma_20'][0]
            
            # Verificar volumen mínimo
            if current_volume < self.params.min_volume:
                continue
            
            # Obtener posición actual
            position = self.getposition(data)
            
            # === LÓGICA DE COMPRA ===
            if not position:
                # Actualizar referencia de máximo para detectar caídas
                if position_data['reference_high'] is None or current_price > position_data['reference_high']:
                    position_data['reference_high'] = current_price
                
                # Detectar caída del 5% desde el máximo de referencia
                if (position_data['reference_high'] and 
                    current_price <= position_data['reference_high'] * (1 - self.params.drop_threshold)):
                    
                    # Verificar que estamos cerca del mínimo del período
                    if self._is_near_minimum(current_price, lowest_lookback):
                        size = self._calculate_position_size(data, current_price)
                        if size > 0:
                            self.order = self.buy(data=data, size=size)
                            self.log(f'{symbol} - SEÑAL COMPRA - Precio: {current_price:.2f} '
                                   f'(Caída desde: {position_data["reference_high"]:.2f}, '
                                   f'Mínimo período: {lowest_lookback:.2f})')
            
            # === LÓGICA DE VENTA ===
            elif position:
                buy_price = position_data['buy_price']
                trailing_stop = position_data['trailing_stop']
                
                # Actualizar el precio más alto desde la compra
                if (position_data['highest_price_since_buy'] is not None and 
                    current_price > position_data['highest_price_since_buy']):
                    position_data['highest_price_since_buy'] = current_price
                
                # Verificar si estamos en recuperación (precio subió 2% desde compra)
                if (not position_data['in_recovery'] and 
                    buy_price is not None and
                    current_price >= buy_price * (1 + self.params.recovery_threshold)):
                    position_data['in_recovery'] = True
                    self.log(f'{symbol} - RECUPERACIÓN DETECTADA - Activando trailing stop')
                
                # Actualizar trailing stop si estamos en recuperación
                if (position_data['in_recovery'] and 
                    position_data['highest_price_since_buy'] is not None):
                    new_trailing_stop = position_data['highest_price_since_buy'] * (1 - self.params.initial_stop_loss)
                    if trailing_stop is None or new_trailing_stop > trailing_stop:
                        position_data['trailing_stop'] = new_trailing_stop
                        self.log(f'{symbol} - TRAILING STOP actualizado a: {new_trailing_stop:.2f}')
                
                should_sell = False
                reason = ""
                
                # 1. Stop Loss (trailing o inicial)
                if (position_data['trailing_stop'] is not None and 
                    current_price <= position_data['trailing_stop']):
                    should_sell = True
                    profit_pct = ((current_price - buy_price) / buy_price) * 100 if buy_price else 0
                    reason = f"Trailing Stop: {position_data['trailing_stop']:.2f} (P&L: {profit_pct:.1f}%)"
                
                # 2. Máximo histórico detectado
                elif self._is_near_historical_high(current_price, highest_lookback):
                    should_sell = True
                    reason = f"Máximo histórico: {highest_lookback:.2f}"
                    # Opcional: poner stop loss más agresivo en lugar de vender inmediatamente
                    # position_data['trailing_stop'] = current_price * 0.98  # Stop loss del 2%
                
                if should_sell:
                    self.order = self.close(data=data)
                    self.log(f'{symbol} - SEÑAL VENTA - Precio: {current_price:.2f} ({reason})')
    
    def _is_near_minimum(self, current_price, lowest_period):
        """Verifica si estamos cerca del mínimo del período"""
        tolerance = 0.02  # 2% de tolerancia
        return current_price <= lowest_period * (1 + tolerance)
    
    def _is_near_historical_high(self, current_price, highest_period):
        """Verifica si estamos cerca del máximo histórico"""
        tolerance = 0.02  # 2% de tolerancia
        return current_price >= highest_period * (1 - tolerance)
    
    def _calculate_position_size(self, data, price):
        """Calcula el tamaño de la posición basado en el risk management"""
        portfolio_value = self.broker.getvalue()
        
        # Validaciones básicas
        if portfolio_value <= 0 or price <= 0:
            return 0
        
        max_investment = portfolio_value * self.params.max_position_size
        
        # Verificar que la inversión mínima sea viable
        if max_investment < price:  # No podemos comprar ni 1 acción
            return 0
        
        shares = int(max_investment / price)
        
        # Verificar cash disponible
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