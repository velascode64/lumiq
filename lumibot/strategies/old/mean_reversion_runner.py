#!/usr/bin/env python3
"""
Mean Reversion Momentum Strategy Runner
Ejecuta backtesting con datos de 5 años o paper trading en vivo con Alpaca API
"""

import backtrader as bt
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import sys
import os
import argparse
from loguru import logger

# Agregar el directorio padre al path para imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.mean_reversion_momentum_strategy import MeanReversionMomentumStrategy
from config.config import Config
import alpaca_trade_api as tradeapi

class MeanReversionRunner:
    """Ejecutor principal para la estrategia de Mean Reversion"""
    
    def __init__(self):
        self.cerebro = None
        self.strategy_params = {}
        
    def setup_cerebro(self, 
                     initial_cash=100000,
                     commission=0.001,
                     **strategy_params):
        """Configura el motor de Backtrader"""
        
        self.cerebro = bt.Cerebro()
        
        # Configurar estrategia con parámetros personalizables
        self.strategy_params = {
            'daily_gain_threshold': strategy_params.get('daily_gain_threshold', 0.05),
            'pullback_pct': strategy_params.get('pullback_pct', 0.02),
            'static_days': strategy_params.get('static_days', 3),
            'static_sd': strategy_params.get('static_sd', 0.01),
            'trailing_stop_pct': strategy_params.get('trailing_stop_pct', 0.02),
            'paper_trade_qty': strategy_params.get('paper_trade_qty', 10),
        }
        
        # Agregar estrategia
        self.cerebro.addstrategy(
            MeanReversionMomentumStrategy,
            **self.strategy_params
        )
        
        # Configurar broker
        self.cerebro.broker.setcash(initial_cash)
        self.cerebro.broker.setcommission(commission=commission)
        
        # Agregar analizadores
        self.cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
        self.cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        self.cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
        self.cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
        
        logger.info("Cerebro configurado exitosamente")
        logger.info(f"Parámetros de estrategia: {self.strategy_params}")
        
    def add_data_feeds(self, tickers=['TSLA', 'GOOGL', 'QQQ'], period='5y'):
        """Agrega feeds de datos usando yfinance"""
        
        if not self.cerebro:
            raise ValueError("Debe configurar cerebro primero con setup_cerebro()")
        
        logger.info(f"Descargando datos para {len(tickers)} tickers: {tickers}")
        logger.info(f"Período: {period}")
        
        for ticker in tickers:
            try:
                # Descargar datos históricos
                logger.info(f"Descargando datos para {ticker}...")
                stock = yf.Ticker(ticker)
                data = stock.history(period=period)
                
                if data.empty:
                    logger.warning(f"No se encontraron datos para {ticker}")
                    continue
                
                # Convertir a formato Backtrader
                data.index = pd.to_datetime(data.index)
                data_bt = bt.feeds.PandasData(
                    dataname=data,
                    name=ticker,
                    plot=False
                )
                
                self.cerebro.adddata(data_bt)
                logger.info(f"✅ {ticker}: {len(data)} barras, "
                           f"desde {data.index[0].strftime('%Y-%m-%d')} "
                           f"hasta {data.index[-1].strftime('%Y-%m-%d')}")
                
            except Exception as e:
                logger.error(f"Error descargando datos para {ticker}: {e}")
                
    def run_backtest(self):
        """Ejecuta el backtest"""
        
        if not self.cerebro:
            raise ValueError("Debe configurar cerebro y datos primero")
            
        logger.info("🚀 Iniciando backtest...")
        logger.info("=" * 60)
        
        # Guardar valor inicial
        initial_value = self.cerebro.broker.getvalue()
        logger.info(f"💰 Capital inicial: ${initial_value:,.2f}")
        
        # Ejecutar backtest
        strategies = self.cerebro.run()
        strategy = strategies[0]
        
        # Valor final
        final_value = self.cerebro.broker.getvalue()
        total_return = ((final_value - initial_value) / initial_value) * 100
        
        logger.info("=" * 60)
        logger.info("📊 RESULTADOS DEL BACKTEST")
        logger.info("=" * 60)
        logger.info(f"💰 Capital inicial: ${initial_value:,.2f}")
        logger.info(f"💰 Capital final: ${final_value:,.2f}")
        logger.info(f"📈 Retorno total: {total_return:.2f}%")
        
        # Analizar resultados
        self._print_analysis_results(strategy)
        
        return strategy
        
    def _print_analysis_results(self, strategy):
        """Imprime resultados detallados del análisis"""
        
        # Sharpe Ratio
        sharpe = strategy.analyzers.sharpe.get_analysis()
        if 'sharperatio' in sharpe and sharpe['sharperatio'] is not None:
            logger.info(f"📊 Sharpe Ratio: {sharpe['sharperatio']:.3f}")
        
        # Drawdown
        drawdown = strategy.analyzers.drawdown.get_analysis()
        if 'max' in drawdown:
            logger.info(f"📉 Max Drawdown: {drawdown['max']['drawdown']:.2f}%")
            logger.info(f"📅 Drawdown Duration: {drawdown['max']['len']} días")
        
        # Returns
        returns = strategy.analyzers.returns.get_analysis()
        if 'rnorm' in returns:
            logger.info(f"📈 Retorno anualizado: {returns['rnorm']:.2f}%")
        
        # Trade Analysis
        trades = strategy.analyzers.trades.get_analysis()
        if 'total' in trades and 'total' in trades['total']:
            total_trades = trades['total']['total']
            won_trades = trades['won']['total'] if 'won' in trades else 0
            
            logger.info(f"🔢 Total trades: {total_trades}")
            if total_trades > 0:
                win_rate = (won_trades / total_trades) * 100
                logger.info(f"🎯 Win Rate: {win_rate:.1f}%")
                
                if 'won' in trades and 'pnl' in trades['won']:
                    avg_win = trades['won']['pnl']['average']
                    logger.info(f"💚 Ganancia promedio: ${avg_win:.2f}")
                    
                if 'lost' in trades and 'pnl' in trades['lost']:
                    avg_loss = abs(trades['lost']['pnl']['average'])
                    logger.info(f"💔 Pérdida promedio: ${avg_loss:.2f}")
                    
                    if avg_loss > 0:
                        profit_factor = avg_win / avg_loss
                        logger.info(f"⚖️  Profit Factor: {profit_factor:.2f}")

class AlpacaPaperTrader:
    """Trader en vivo usando Alpaca Paper Trading API"""
    
    def __init__(self):
        self.api = None
        self.strategy_params = {}
        
    def setup_alpaca_connection(self):
        """Configura conexión con Alpaca"""
        try:
            Config.validate()
            
            self.api = tradeapi.REST(
                Config.ALPACA_API_KEY,
                Config.ALPACA_SECRET_KEY,
                Config.ALPACA_BASE_URL
            )
            
            # Verificar conexión
            account = self.api.get_account()
            logger.info(f"✅ Conectado a Alpaca Paper Trading")
            logger.info(f"💰 Cash disponible: ${float(account.cash):,.2f}")
            logger.info(f"📊 Equity total: ${float(account.equity):,.2f}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error conectando con Alpaca: {e}")
            return False
    
    def run_live_strategy(self, tickers=['TSLA', 'GOOGL', 'QQQ'], **strategy_params):
        """Ejecuta estrategia en modo paper trading"""
        
        if not self.api:
            if not self.setup_alpaca_connection():
                return False
        
        self.strategy_params = strategy_params
        
        logger.info("🔴 MODO PAPER TRADING ACTIVADO")
        logger.info(f"🎯 Monitoreando: {tickers}")
        logger.info(f"⚙️  Parámetros: {strategy_params}")
        
        # Aquí implementarías la lógica de trading en vivo
        # Por ahora, mostrar un ejemplo de cómo sería
        
        try:
            while True:
                for ticker in tickers:
                    # Obtener datos actuales
                    latest_quote = self.api.get_latest_quote(ticker)
                    logger.info(f"{ticker}: ${latest_quote.bid_price:.2f}")
                    
                    # Aquí aplicarías la lógica de la estrategia
                    # y ejecutarías órdenes según las condiciones
                    
                import time
                time.sleep(60)  # Esperar 1 minuto entre checks
                
        except KeyboardInterrupt:
            logger.info("🛑 Trading detenido por usuario")
            
        return True

def main():
    """Función principal para ejecutar la estrategia"""
    
    parser = argparse.ArgumentParser(description='Mean Reversion Momentum Strategy Runner')
    parser.add_argument('--mode', choices=['backtest', 'live'], default='backtest',
                       help='Modo de ejecución: backtest o live')
    parser.add_argument('--tickers', nargs='+', default=['TSLA', 'GOOGL', 'QQQ'],
                       help='Tickers a operar')
    parser.add_argument('--period', default='5y',
                       help='Período para backtest (formato yfinance)')
    parser.add_argument('--cash', type=float, default=100000,
                       help='Capital inicial')
    
    # Parámetros de estrategia
    parser.add_argument('--daily_gain_threshold', type=float, default=0.05,
                       help='Umbral de ganancia diaria (0.05 = 5%)')
    parser.add_argument('--pullback_pct', type=float, default=0.02,
                       help='Porcentaje de pullback (0.02 = 2%)')
    parser.add_argument('--static_days', type=int, default=3,
                       help='Días para considerar precio estático')
    parser.add_argument('--static_sd', type=float, default=0.01,
                       help='Desviación estándar para precio estático')
    parser.add_argument('--trailing_stop_pct', type=float, default=0.02,
                       help='Porcentaje de trailing stop')
    
    args = parser.parse_args()
    
    # Configurar logging
    logger.remove()
    logger.add(sys.stdout, 
               format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
               level="INFO")
    
    logger.info("🎯 Mean Reversion Momentum Strategy Runner")
    logger.info("=" * 60)
    
    if args.mode == 'backtest':
        # Modo Backtest
        runner = MeanReversionRunner()
        
        # Configurar parámetros
        strategy_params = {
            'daily_gain_threshold': args.daily_gain_threshold,
            'pullback_pct': args.pullback_pct,
            'static_days': args.static_days,
            'static_sd': args.static_sd,
            'trailing_stop_pct': args.trailing_stop_pct,
        }
        
        # Setup y ejecución
        runner.setup_cerebro(initial_cash=args.cash, **strategy_params)
        runner.add_data_feeds(tickers=args.tickers, period=args.period)
        runner.run_backtest()
        
    elif args.mode == 'live':
        # Modo Live Paper Trading
        trader = AlpacaPaperTrader()
        
        strategy_params = {
            'daily_gain_threshold': args.daily_gain_threshold,
            'pullback_pct': args.pullback_pct,
            'static_days': args.static_days,
            'static_sd': args.static_sd,
            'trailing_stop_pct': args.trailing_stop_pct,
        }
        
        trader.run_live_strategy(tickers=args.tickers, **strategy_params)

if __name__ == "__main__":
    main() 