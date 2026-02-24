import backtrader as bt
import numpy as np
from loguru import logger
from config.config import Config
from datetime import datetime, timedelta

class MeanReversionMomentumStrategy(bt.Strategy):
    """
    Estrategia Optimizada de Mean Reversion con Momentum Trading
    
    Características Mejoradas:
    - Parámetros específicos por símbolo basados en performance histórica
    - Enhanced entry signals con MACD y confirmación de volumen
    - Take profit escalonado para maximizar ganancias
    - Portfolio allocation inteligente
    - Filtros: RSI, MACD, volumen relativo, tendencia SMA20/50
    
    Performance Histórica Optimizada:
    - QQQ: +90.9%, GOOGL: +87.5%, COIN: +59.6%
    - Risk management mejorado para DJT, BABA
    """
    
    params = (
        # Parámetros de configuración principal
        ('daily_gain_threshold', 0.05),      # 5% daily gain para activar lógica de salida
        ('pullback_pct', 0.02),              # 2% pullback desde high para vender
        ('trailing_stop_pct', 0.02),         # 2% trailing stop
        ('lookback_52w', 252),               # 252 días = ~52 semanas
        
        # Parámetros de filtrado técnico
        ('rsi_oversold', 35),                # RSI oversold para filtrar entradas
        ('rsi_overbought', 70),              # RSI overbought para filtrar entradas
        ('cooldown_days', 2),                # Días de espera después de venta
        
        # Parámetros generales
        ('min_volume', getattr(Config, 'MIN_VOLUME', 1000000)),
        ('max_position_size', getattr(Config, 'MAX_POSITION_SIZE', 0.1)),
        ('paper_trade_qty', 10),             # Cantidad fija para paper trading
        
        # Parámetros de indicadores
        ('lookback_period', 20),             # Período para indicadores técnicos
        
        # Nuevos parámetros para take profit escalonado
        ('take_profit_1', 0.15),             # 15% para primer take profit
        ('take_profit_2', 0.30),             # 30% para segundo take profit  
        ('take_profit_3', 0.50),             # 50% para tercer take profit
        ('partial_exit_pct', 0.33),          # Vender 33% en cada take profit
    )
    
    # Parámetros específicos por símbolo basados en performance histórica
    SYMBOL_PARAMS = {
        'QQQ': {
            'daily_gain_threshold': 0.03,    # Más agresivo para mejor performer
            'trailing_stop_pct': 0.015,      # Stop más tight
            'max_position_size': 0.25,       # Mayor allocation
            'rsi_oversold': 30,              # Más agresivo en oversold
        },
        'GOOGL': {
            'daily_gain_threshold': 0.04,    # Consistente performer
            'trailing_stop_pct': 0.018,
            'max_position_size': 0.20,
            'rsi_oversold': 32,
        },
        'COIN': {
            'daily_gain_threshold': 0.08,    # Más volátil, mayor target
            'trailing_stop_pct': 0.03,       # Stop más amplio
            'max_position_size': 0.15,
            'rsi_oversold': 25,              # Muy oversold para crypto
        },
        'AAPL': {
            'daily_gain_threshold': 0.04,
            'trailing_stop_pct': 0.02,
            'max_position_size': 0.15,
            'rsi_oversold': 33,
        },
        'MSFT': {
            'daily_gain_threshold': 0.04,
            'trailing_stop_pct': 0.02,
            'max_position_size': 0.15,
            'rsi_oversold': 33,
        },
        'BABA': {
            'daily_gain_threshold': 0.06,    # Underperformer, más conservador
            'trailing_stop_pct': 0.025,
            'max_position_size': 0.05,       # Menor allocation
            'rsi_oversold': 25,              # Muy oversold
        },
        'DJT': {
            'daily_gain_threshold': 0.10,    # Muy volátil
            'trailing_stop_pct': 0.05,       # Stop muy amplio
            'max_position_size': 0.03,       # Minimal allocation
            'rsi_oversold': 20,              # Extremo oversold
        },
        'TSLA': {
            'daily_gain_threshold': 0.06,
            'trailing_stop_pct': 0.03,
            'max_position_size': 0.10,
            'rsi_oversold': 30,
        },
    }
    
    def __init__(self):
        """Inicialización de la estrategia"""
        self.order = None
        self.trades_count = 0
        self.winning_trades = 0
        self.partial_exits = 0
        
        # Tracking simplificado por símbolo
        self.positions_data = {}
        
        # Indicadores técnicos para cada símbolo
        self.indicators = {}
        
        # Inicializar para cada símbolo
        for data in self.datas:
            symbol = data._name
            
            # Indicadores técnicos mejorados
            self.indicators[symbol] = {
                'volume_ma': bt.indicators.SimpleMovingAverage(data.volume, period=20),
                'sma_20': bt.indicators.SimpleMovingAverage(data.close, period=20),
                'sma_50': bt.indicators.SimpleMovingAverage(data.close, period=50),
                'highest_52w': bt.indicators.Highest(data.high, period=self.params.lookback_52w),
                'lowest_52w': bt.indicators.Lowest(data.low, period=self.params.lookback_52w),
                'atr': bt.indicators.ATR(data, period=14),
                'rsi': bt.indicators.RSI(data.close, period=14),
                # Nuevos indicadores para enhanced signals
                'macd': bt.indicators.MACD(data.close, period_me1=12, period_me2=26, period_signal=9),
                'macd_signal': bt.indicators.MACDHisto(data.close, period_me1=12, period_me2=26, period_signal=9),
                'bb': bt.indicators.BollingerBands(data.close, period=20, devfactor=2),
                'volume_sma': bt.indicators.SimpleMovingAverage(data.volume, period=10),  # Short volume MA
            }
            
            # Tracking mejorado de posiciones
            self.positions_data[symbol] = {
                # Estado simplificado
                'position_status': 'READY_TO_BUY',  # READY_TO_BUY, HOLDING, PARTIAL_SOLD
                
                # Precios de referencia
                'buy_price': None,
                'recent_high': None,
                'trailing_stop': None,
                
                # Para daily gain calculation
                'prev_close': None,
                
                # Cooldown después de venta
                'sell_date': None,
                
                # Nuevos campos para take profit escalonado
                'original_size': None,
                'remaining_size': None,
                'take_profit_1_hit': False,
                'take_profit_2_hit': False,
                'take_profit_3_hit': False,
                
                # Parámetros específicos del símbolo
                'symbol_params': self._get_symbol_params(symbol),
            }
            
        logger.info(f"MeanReversionMomentum Strategy OPTIMIZADA inicializada para {len(self.datas)} símbolos")
        logger.info(f"Parámetros base: daily_gain={self.params.daily_gain_threshold*100}%, "
                   f"pullback={self.params.pullback_pct*100}%, "
                   f"rsi_range={self.params.rsi_oversold}-{self.params.rsi_overbought}, "
                   f"cooldown={self.params.cooldown_days}d, "
                   f"trailing_stop={self.params.trailing_stop_pct*100}%")
        logger.info(f"Mejoras: MACD signals, Take profit escalonado, Parámetros por símbolo")
        
        # Log symbol-specific parameters
        for symbol in [data._name for data in self.datas]:
            if symbol in self.SYMBOL_PARAMS:
                params = self.SYMBOL_PARAMS[symbol]
                logger.info(f"{symbol} params: gain={params.get('daily_gain_threshold', self.params.daily_gain_threshold)*100:.1f}%, "
                           f"stop={params.get('trailing_stop_pct', self.params.trailing_stop_pct)*100:.1f}%, "
                           f"size={params.get('max_position_size', self.params.max_position_size)*100:.0f}%")
    
    def _get_symbol_params(self, symbol):
        """Obtiene parámetros específicos del símbolo o defaults"""
        return self.SYMBOL_PARAMS.get(symbol, {})
    
    def log(self, txt, dt=None):
        """Función de logging mejorada"""
        dt = dt or self.datas[0].datetime.date(0)
        logger.info(f'{dt.isoformat()}: {txt}')
        # También imprimir para alerts en vivo
        print(f"[ALERT] {dt.isoformat()}: {txt}")
    
    def notify_order(self, order):
        """Notificación de órdenes con alerts"""
        if order.status in [order.Submitted, order.Accepted]:
            return
        
        symbol = order.data._name
        
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f'🟢 {symbol} - COMPRA EJECUTADA - Precio: {order.executed.price:.2f}, '
                        f'Cantidad: {order.executed.size}, Comisión: {order.executed.comm:.2f}')
                
                # Actualizar tracking
                pos_data = self.positions_data[symbol]
                pos_data['buy_price'] = order.executed.price
                pos_data['recent_high'] = order.executed.price
                pos_data['trailing_stop'] = order.executed.price * (1 - self.params.trailing_stop_pct)
                pos_data['position_status'] = 'HOLDING'
                
            else:
                self.log(f'🔴 {symbol} - VENTA EJECUTADA - Precio: {order.executed.price:.2f}, '
                        f'Cantidad: {order.executed.size}, Comisión: {order.executed.comm:.2f}')
                
                # Reset tracking para cooldown
                pos_data = self.positions_data[symbol]
                pos_data['position_status'] = 'READY_TO_BUY'
                pos_data['sell_date'] = self.datas[0].datetime.date(0)
                pos_data['buy_price'] = None
                pos_data['recent_high'] = None
                pos_data['trailing_stop'] = None
                # Reset take profit flags
                pos_data['take_profit_1_hit'] = False
                pos_data['take_profit_2_hit'] = False
                pos_data['take_profit_3_hit'] = False
                pos_data['original_size'] = None
                pos_data['remaining_size'] = None
        
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'❌ {symbol} - Orden {order.status}')
        
        self.order = None
    
    def notify_trade(self, trade):
        """Notificación de trades cerrados con estadísticas"""
        if not trade.isclosed:
            return
        
        self.trades_count += 1
        if trade.pnl > 0:
            self.winning_trades += 1
        
        symbol = trade.data._name
        pnl_pct = (trade.pnl / trade.value) * 100 if trade.value != 0 else 0
        
        status_emoji = "💚" if trade.pnl > 0 else "💔"
        self.log(f'{status_emoji} {symbol} - TRADE CERRADO - P&L: ${trade.pnl:.2f} ({pnl_pct:.1f}%), '
                f'P&L Neto: ${trade.pnlcomm:.2f}')
        
        # Estadísticas
        if self.trades_count > 0:
            win_rate = (self.winning_trades / self.trades_count) * 100
            self.log(f'📊 Estadísticas - Trades: {self.trades_count}, Win Rate: {win_rate:.1f}%, Partial Exits: {self.partial_exits}')
    
    def next(self):
        """Lógica principal de la estrategia ejecutada en cada barra"""
        
        for i, data in enumerate(self.datas):
            symbol = data._name
            
            # Verificar datos suficientes
            if len(data) < max(self.params.lookback_period, self.params.lookback_52w, 50, 20, 14):
                continue
            
            # Obtener datos actuales
            current_price = data.close[0]
            current_volume = data.volume[0]
            current_date = data.datetime.date(0)
            
            # Obtener indicadores
            indicators = self.indicators[symbol]
            position_data = self.positions_data[symbol]
            
            volume_ma = indicators['volume_ma'][0]
            sma_20 = indicators['sma_20'][0]
            sma_50 = indicators['sma_50'][0]
            highest_52w = indicators['highest_52w'][0]
            lowest_52w = indicators['lowest_52w'][0]
            atr = indicators['atr'][0]
            rsi = indicators['rsi'][0]
            
            # Verificar volumen mínimo
            if current_volume < self.params.min_volume or current_volume < volume_ma * 0.5:
                continue
            
            # Actualizar precio previo para daily gain
            if position_data['prev_close'] is None:
                position_data['prev_close'] = current_price
                continue
            
            # Calcular daily gain
            daily_gain = (current_price - position_data['prev_close']) / position_data['prev_close']
            
            # Obtener posición actual
            position = self.getposition(data)
            
            # === LÓGICA SEGÚN ESTADO ===
            status = position_data['position_status']
            
            if status == 'READY_TO_BUY' and not position:
                # Verificar cooldown después de venta
                if self._is_in_cooldown(position_data, current_date):
                    continue
                    
                # Lógica de entrada mejorada
                if self._should_enter(symbol, current_price, indicators, current_volume, volume_ma):
                    size = self._calculate_position_size(data, current_price, symbol)
                    if size > 0:
                        self.order = self.buy(data=data, size=size)
                        # Guardar tamaño original para take profits
                        position_data['original_size'] = size
                        position_data['remaining_size'] = size
                        
                        macd_histo = indicators['macd_signal'][0]
                        self.log(f'📈 {symbol} - SEÑAL COMPRA MEJORADA - Precio: {current_price:.2f}, '
                               f'RSI: {rsi:.1f}, MACD: {macd_histo:.3f}, Vol: {current_volume/volume_ma:.1f}x, '
                               f'SMA20: {current_price/sma_20:.3f}, Cantidad: {size}')
            
            elif status == 'HOLDING' and position:
                # Actualizar recent high y trailing stop con parámetros específicos
                if current_price > position_data['recent_high']:
                    position_data['recent_high'] = current_price
                    # Usar trailing stop específico del símbolo
                    symbol_params = position_data['symbol_params']
                    trailing_stop_pct = symbol_params.get('trailing_stop_pct', self.params.trailing_stop_pct)
                    new_trailing = current_price * (1 - trailing_stop_pct)
                    if new_trailing > position_data['trailing_stop']:
                        position_data['trailing_stop'] = new_trailing
                        self.log(f'📊 {symbol} - Trailing Stop actualizado: {new_trailing:.2f} ({trailing_stop_pct*100:.1f}%)')
                
                # Verificar condiciones de salida (incluye take profits escalonados)
                should_sell, sell_size, reason = self._should_exit(symbol, current_price, daily_gain, highest_52w, position_data, position)
                
                if should_sell:
                    if sell_size == 'ALL':
                        self.order = self.close(data=data)
                        self.log(f'📉 {symbol} - VENTA COMPLETA - Precio: {current_price:.2f} ({reason})')
                    else:
                        self.order = self.close(data=data, size=sell_size)
                        self.partial_exits += 1
                        self.log(f'📊 {symbol} - VENTA PARCIAL - Precio: {current_price:.2f}, Cantidad: {sell_size} ({reason})')
                        # Actualizar remaining size
                        position_data['remaining_size'] = max(0, position_data['remaining_size'] - sell_size)
            
            # Actualizar precio previo
            position_data['prev_close'] = current_price
    
    def _is_in_cooldown(self, position_data, current_date):
        """Verifica si estamos en período de cooldown después de venta"""
        if position_data['sell_date'] is None:
            return False
        
        days_since_sell = (current_date - position_data['sell_date']).days
        return days_since_sell < self.params.cooldown_days
    
    def _should_enter(self, symbol, current_price, indicators, current_volume, volume_ma):
        """Determina si debe entrar en posición con filtros mejorados y MACD"""
        sma_20 = indicators['sma_20'][0]
        sma_50 = indicators['sma_50'][0]
        highest_52w = indicators['highest_52w'][0]
        lowest_52w = indicators['lowest_52w'][0]
        rsi = indicators['rsi'][0]
        atr = indicators['atr'][0]
        
        # Nuevos indicadores mejorados
        macd_line = indicators['macd'].macd[0]
        macd_signal = indicators['macd'].signal[0]
        macd_histo = indicators['macd_signal'][0]
        bb_upper = indicators['bb'].top[0]
        bb_lower = indicators['bb'].bot[0]
        volume_sma = indicators['volume_sma'][0]
        
        # Obtener parámetros específicos del símbolo
        position_data = self.positions_data[symbol]
        symbol_params = position_data['symbol_params']
        
        # Parámetros ajustados por símbolo
        rsi_oversold = symbol_params.get('rsi_oversold', self.params.rsi_oversold)
        rsi_overbought = symbol_params.get('rsi_overbought', self.params.rsi_overbought)
        
        # Filtros de entrada mejorados
        volatility_ok = atr > 0
        not_near_52w_high = current_price < highest_52w * 0.90  # No cerca del máximo 52w
        not_near_52w_low = current_price > lowest_52w * 1.10   # No cerca del mínimo 52w
        rsi_favorable = rsi_oversold < rsi < rsi_overbought
        above_sma20 = current_price > sma_20 * 1.01  # Con buffer del 1%
        above_sma50 = current_price > sma_50  # Tendencia alcista a largo plazo
        
        # NUEVOS FILTROS MEJORADOS
        macd_bullish = macd_line > macd_signal and macd_histo > 0  # MACD positivo y creciente
        volume_spike = current_volume > volume_ma * 1.2  # Volumen 20% por encima del promedio
        volume_confirmed = current_volume > volume_sma * 0.8  # Confirmación con SMA corto
        not_overbought_bb = current_price < bb_upper * 0.98  # No en banda superior
        momentum_ok = current_price > sma_20 * 1.005  # Momentum positivo
        
        entry_conditions = [
            ('volatility', volatility_ok),
            ('not_near_52w_high', not_near_52w_high),
            ('not_near_52w_low', not_near_52w_low),
            ('rsi_favorable', rsi_favorable),
            ('above_sma20', above_sma20),
            ('above_sma50', above_sma50),
            ('macd_bullish', macd_bullish),  # NUEVO
            ('volume_spike', volume_spike),   # NUEVO
            ('volume_confirmed', volume_confirmed),  # NUEVO
            ('not_overbought_bb', not_overbought_bb),  # NUEVO
            ('momentum_ok', momentum_ok),     # NUEVO
        ]
        
        # Log filtros fallidos para debugging
        failed_filters = [name for name, condition in entry_conditions if not condition]
        if failed_filters and len(failed_filters) < 6:  # Solo log si fallan pocos filtros
            self.log(f'🔍 {symbol} - Filtros fallidos: {", ".join(failed_filters)} '
                   f'(RSI: {rsi:.1f}, MACD: {macd_histo:.3f}, '
                   f'Vol: {current_volume/volume_ma:.1f}x, P/SMA20: {current_price/sma_20:.3f})')
        
        # Requerir al menos 8 de 11 filtros para entrada más selectiva
        passed_filters = sum(1 for _, condition in entry_conditions if condition)
        return passed_filters >= 8
    
    def _should_exit(self, symbol, current_price, daily_gain, highest_52w, position_data, position):
        """Determina si debe salir de la posición con take profits escalonados"""
        recent_high = position_data['recent_high']
        trailing_stop = position_data['trailing_stop']
        buy_price = position_data['buy_price']
        original_size = position_data['original_size']
        remaining_size = position_data['remaining_size']
        
        # Obtener parámetros específicos del símbolo
        symbol_params = position_data['symbol_params']
        daily_gain_threshold = symbol_params.get('daily_gain_threshold', self.params.daily_gain_threshold)
        trailing_stop_pct = symbol_params.get('trailing_stop_pct', self.params.trailing_stop_pct)
        
        if not buy_price or not original_size:
            return False, 0, ""
        
        # Calcular ganancia desde compra
        total_gain = (current_price - buy_price) / buy_price
        
        # TAKE PROFITS ESCALONADOS (basados en tu performance histórica)
        partial_size = int(original_size * self.params.partial_exit_pct)
        
        # Take Profit 1: 15% (QQQ style)
        if (not position_data['take_profit_1_hit'] and 
            total_gain >= self.params.take_profit_1 and 
            remaining_size > partial_size):
            position_data['take_profit_1_hit'] = True
            return True, partial_size, f"Take Profit 1: {total_gain*100:.1f}% (target: {self.params.take_profit_1*100}%)"
        
        # Take Profit 2: 30% (GOOGL style)
        if (not position_data['take_profit_2_hit'] and 
            total_gain >= self.params.take_profit_2 and 
            remaining_size > partial_size):
            position_data['take_profit_2_hit'] = True
            return True, partial_size, f"Take Profit 2: {total_gain*100:.1f}% (target: {self.params.take_profit_2*100}%)"
        
        # Take Profit 3: 50% (COIN style)
        if (not position_data['take_profit_3_hit'] and 
            total_gain >= self.params.take_profit_3):
            position_data['take_profit_3_hit'] = True
            return True, partial_size, f"Take Profit 3: {total_gain*100:.1f}% (target: {self.params.take_profit_3*100}%)"
        
        # CONDICIONES DE SALIDA COMPLETA
        
        # 1. Daily gain > threshold específico del símbolo
        if daily_gain >= daily_gain_threshold:
            return True, 'ALL', f"Daily gain {daily_gain*100:.1f}% >= {daily_gain_threshold*100}%"
        
        # 2. Close >= high 52-semanas
        if current_price >= highest_52w * 0.99:  # 1% tolerancia
            return True, 'ALL', f"Cerca máximo 52w: {highest_52w:.2f}"
        
        # 3. Pullback desde recent high
        if (recent_high and 
            current_price <= recent_high * (1 - self.params.pullback_pct)):
            return True, 'ALL', f"Pullback {self.params.pullback_pct*100}% desde high: {recent_high:.2f}"
        
        # 4. Trailing stop ajustado por símbolo
        if trailing_stop and current_price <= trailing_stop:
            return True, 'ALL', f"Trailing stop: {trailing_stop:.2f}"
        
        # 5. Ganancia total muy alta (proteger ganancias)
        if total_gain >= 0.80:  # 80% gain -> exit completo
            return True, 'ALL', f"Ganancia excepcional: {total_gain*100:.1f}%"
        
        return False, 0, ""
    
    def _calculate_position_size(self, data, price, symbol):
        """Calcula el tamaño de la posición con parámetros específicos por símbolo"""
        # Para paper trading, usar cantidad fija
        paper_trade_mode = getattr(self, 'paper_trade_mode', False)
        if paper_trade_mode:
            return self.params.paper_trade_qty
        
        # Obtener parámetros específicos del símbolo
        symbol_params = self.positions_data[symbol]['symbol_params']
        max_position_size = symbol_params.get('max_position_size', self.params.max_position_size)
        
        # Para backtesting, usar % del portafolio ajustado por símbolo
        portfolio_value = self.broker.getvalue()
        if portfolio_value <= 0 or price <= 0:
            return 0
        
        max_investment = portfolio_value * max_position_size
        if max_investment < price:
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
        initial_value = getattr(self, 'initial_value', Config.INITIAL_CASH)
        total_return = ((portfolio_value - initial_value) / initial_value) * 100
        
        self.log(f'🏁 BACKTEST FINALIZADO')
        self.log(f'💰 Valor inicial: ${initial_value:,.2f}')
        self.log(f'💰 Valor final: ${portfolio_value:,.2f}')
        self.log(f'📈 Retorno total: {total_return:.2f}%')
        
        if self.trades_count > 0:
            win_rate = (self.winning_trades / self.trades_count) * 100
            self.log(f'📊 Estadísticas finales - Trades: {self.trades_count}, '
                    f'Win Rate: {win_rate:.1f}%, Partial Exits: {self.partial_exits}')
        else:
            self.log('⚠️  No se ejecutaron trades durante el período')
            
        # Resumen por símbolo
        self.log(f'📋 Estados finales por símbolo:')
        for symbol, data in self.positions_data.items():
            status = data['position_status']
            self.log(f'   {symbol}: {status}')