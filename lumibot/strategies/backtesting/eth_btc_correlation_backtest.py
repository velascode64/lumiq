"""
ETH/BTC Correlation Strategy - Backtesting Version
Corregida para funcionar con Lumibot + Alpaca
"""

import os
import sys
from datetime import datetime
from dotenv import load_dotenv
import pytz

# Agregar el directorio padre al path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lumibot.strategies.strategy import Strategy
from lumibot.entities import Asset
from lumibot.backtesting import YahooDataBacktesting
from lumibot.brokers import Alpaca

# Cargar variables de entorno
load_dotenv()


class CryptoLeadLagStrategy(Strategy):
    """
    Estrategia que opera ETH basándose en movimientos fuertes de BTC
    """
    
    def initialize(self):
        # Configuración básica
        self.sleeptime = "1H"  # Revisar cada hora para backtesting
        
        # Assets
        self.btc_asset = Asset(symbol="BTC", asset_type="crypto")
        self.eth_asset = Asset(symbol="ETH", asset_type="crypto") 
        self.sol_asset = Asset(symbol="SOL", asset_type="crypto")
        
        # Configuración de la estrategia
        self.btc_threshold = 0.05  # 5% movimiento de BTC
        self.position_size_pct = 0.30  # 30% del portfolio por asset
        self.stop_loss_pct = 0.03  # Stop-loss 3%
        
        # Tracking
        self.total_trades = 0
        
        self.log_message("=" * 60)
        self.log_message("CRYPTO LEAD-LAG STRATEGY INITIALIZED")
        self.log_message("=" * 60)
        self.log_message(f"BTC threshold: {self.btc_threshold*100}%")
        self.log_message(f"Position size: {self.position_size_pct*100}% per asset")
        self.log_message(f"Stop loss: {self.stop_loss_pct*100}%")
        self.log_message("=" * 60)

    def on_trading_iteration(self):
        """Lógica principal de trading"""
        try:
            current_time = self.get_datetime()
            
            self.log_message(f"\n{'─'*50}")
            self.log_message(f"ITERATION - {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
            self.log_message(f"{'─'*50}")
            
            # Obtener datos de BTC para análisis de momentum
            btc_data = self.get_historical_prices(self.btc_asset, 24, "hour")
            
            if not btc_data or len(btc_data.df) < 2:
                self.log_message("❌ Insufficient BTC data")
                return
            
            # Calcular retorno de BTC en las últimas 24 horas
            btc_df = btc_data.df
            btc_current_price = btc_df['close'].iloc[-1]
            btc_prev_price = btc_df['close'].iloc[-24] if len(btc_df) >= 24 else btc_df['close'].iloc[0]
            btc_return = (btc_current_price - btc_prev_price) / btc_prev_price
            
            self.log_message(f"📊 BTC 24h return: {btc_return*100:+.2f}%")
            self.log_message(f"💰 Portfolio value: ${self.portfolio_value:,.2f}")
            self.log_message(f"💵 Cash: ${self.cash:,.2f}")
            
            # Obtener posiciones actuales
            eth_position = self.get_position(self.eth_asset)
            sol_position = self.get_position(self.sol_asset)
            
            eth_quantity = eth_position.quantity if eth_position else 0
            sol_quantity = sol_position.quantity if sol_position else 0
            
            self.log_message(f"📈 ETH position: {eth_quantity:.6f}")
            self.log_message(f"📈 SOL position: {sol_quantity:.6f}")
            
            # Señal alcista: BTC sube >5%
            if btc_return > self.btc_threshold:
                self.log_message(f"🚀 BULLISH SIGNAL: BTC up {btc_return*100:.1f}%")
                self._execute_buy_signals(btc_return)
            
            # Señal bajista: BTC baja >5%
            elif btc_return < -self.btc_threshold:
                self.log_message(f"📉 BEARISH SIGNAL: BTC down {btc_return*100:.1f}%")
                self._execute_sell_signals(btc_return)
            
            else:
                self.log_message(f"😴 NO SIGNAL: BTC move {btc_return*100:+.1f}% < {self.btc_threshold*100}%")
                
            # Gestionar posiciones existentes (stop-loss)
            self._manage_existing_positions()
                
        except Exception as e:
            self.log_message(f"❌ Error in trading iteration: {e}")

    def _execute_buy_signals(self, btc_return: float):
        """Ejecuta compras de ETH y SOL tras señal alcista de BTC"""
        assets_to_buy = [self.eth_asset, self.sol_asset]
        
        for asset in assets_to_buy:
            try:
                current_price = self.get_last_price(asset)
                if not current_price:
                    continue
                
                # Verificar si ya tenemos posición
                position = self.get_position(asset)
                if position and position.quantity > 0:
                    self.log_message(f"⚠️ Already have {asset.symbol} position")
                    continue
                
                # Calcular cantidad a comprar
                position_value = self.portfolio_value * self.position_size_pct
                quantity = position_value / current_price
                
                # Verificar si tenemos suficiente cash
                if self.cash >= position_value:
                    # Crear orden
                    order = self.create_order(
                        asset,
                        quantity=quantity,
                        side="buy"
                    )
                    
                    self.submit_order(order)
                    self.total_trades += 1
                    
                    self.log_message(f"🟢 BUY ORDER: {quantity:.6f} {asset.symbol} @ ${current_price:.2f}")
                    self.log_message(f"   Value: ${position_value:,.2f}")
                    self.log_message(f"   Reason: BTC up {btc_return*100:.1f}%")
                    
                else:
                    self.log_message(f"❌ Insufficient cash for {asset.symbol}: ${self.cash:.2f} < ${position_value:.2f}")
                    
            except Exception as e:
                self.log_message(f"❌ Error buying {asset.symbol}: {e}")

    def _execute_sell_signals(self, btc_return: float):
        """Ejecuta ventas tras señal bajista de BTC"""
        assets_to_sell = [self.eth_asset, self.sol_asset]
        
        for asset in assets_to_sell:
            try:
                position = self.get_position(asset)
                
                if position and position.quantity > 0:
                    current_price = self.get_last_price(asset)
                    
                    # Crear orden de venta
                    order = self.create_order(
                        asset,
                        quantity=position.quantity,
                        side="sell"
                    )
                    
                    self.submit_order(order)
                    self.total_trades += 1
                    
                    value = float(position.quantity) * current_price
                    
                    self.log_message(f"🔴 SELL ORDER: {position.quantity:.6f} {asset.symbol} @ ${current_price:.2f}")
                    self.log_message(f"   Value: ${value:,.2f}")
                    self.log_message(f"   Reason: BTC down {btc_return*100:.1f}%")
                    
                else:
                    self.log_message(f"⚠️ No {asset.symbol} position to sell")
                    
            except Exception as e:
                self.log_message(f"❌ Error selling {asset.symbol}: {e}")

    def _manage_existing_positions(self):
        """Gestiona posiciones existentes con stop-loss"""
        assets_to_check = [self.eth_asset, self.sol_asset]
        
        for asset in assets_to_check:
            try:
                position = self.get_position(asset)
                
                if not position or position.quantity <= 0:
                    continue
                
                current_price = self.get_last_price(asset)
                if not current_price:
                    continue
                
                # Para simplificar, usar precio de entrada como el precio de la última vela
                # En una implementación real, guardarías el precio de entrada
                historical_data = self.get_historical_prices(asset, 2, "hour")
                if not historical_data or len(historical_data.df) < 2:
                    continue
                
                entry_price = historical_data.df['close'].iloc[-2]  # Precio anterior como proxy
                
                # Calcular pérdida
                loss_pct = (entry_price - current_price) / entry_price
                
                # Stop-loss
                if loss_pct >= self.stop_loss_pct:
                    order = self.create_order(
                        asset,
                        quantity=position.quantity,
                        side="sell"
                    )
                    
                    self.submit_order(order)
                    self.total_trades += 1
                    
                    self.log_message(f"🛑 STOP-LOSS: {position.quantity:.6f} {asset.symbol}")
                    self.log_message(f"   Loss: {loss_pct*100:.1f}% >= {self.stop_loss_pct*100}%")
                    
            except Exception as e:
                self.log_message(f"❌ Error managing {asset.symbol} position: {e}")

    def on_strategy_end(self):
        """Cerrar todas las posiciones al final"""
        self.log_message("\n" + "=" * 60)
        self.log_message("STRATEGY ENDING - CLOSING ALL POSITIONS")
        self.log_message("=" * 60)
        
        assets = [self.eth_asset, self.sol_asset]
        
        for asset in assets:
            position = self.get_position(asset)
            if position and position.quantity > 0:
                order = self.create_order(
                    asset,
                    quantity=position.quantity,
                    side="sell"
                )
                self.submit_order(order)
                self.log_message(f"🏁 Final sell: {position.quantity:.6f} {asset.symbol}")
        
        self.log_message(f"📊 Total trades executed: {self.total_trades}")
        self.log_message("=" * 60)


def run_backtest():
    """Ejecuta el backtesting"""
    
    print("🧪 ETH/BTC Correlation Strategy - Backtesting")
    print("=" * 60)
    
    # Configuración de Alpaca para datos
    alpaca_config = {
        "API_KEY": os.getenv("ALPACA_API_KEY"),
        "API_SECRET": os.getenv("ALPACA_API_SECRET"),
        "PAPER": True,
        "BASE_URL": "https://paper-api.alpaca.markets"
    }
    
    if not alpaca_config["API_KEY"]:
        print("❌ Error: ALPACA_API_KEY not found in .env")
        return
    
    # Fechas para backtesting
    tzinfo = pytz.timezone('UTC')
    backtesting_start = tzinfo.localize(datetime(2024, 6, 1))  # 3 meses
    backtesting_end = tzinfo.localize(datetime(2024, 9, 1))
    
    print(f"📅 Period: {backtesting_start.date()} to {backtesting_end.date()}")
    print(f"🎯 Strategy: BTC momentum → ETH/SOL trades")
    print(f"📊 Threshold: ±5% BTC moves")
    print("=" * 60)
    
    try:
        # Ejecutar backtest usando YahooDataBacktesting
        results, strategy_instance = CryptoLeadLagStrategy.run_backtest(
            datasource_class=YahooDataBacktesting,
            backtesting_start=backtesting_start,
            backtesting_end=backtesting_end,
            benchmark_asset=Asset("BTC", asset_type="crypto"),
            analyze_backtest=True,
            show_progress_bar=True,
            # Configuración adicional
            budget=100000,  # $100k inicial
        )
        
        print("\n" + "=" * 60)
        print("BACKTEST RESULTS")
        print("=" * 60)
        print(results)
        
    except Exception as e:
        print(f"❌ Backtest error: {e}")
        import traceback
        traceback.print_exc()


def run_live():
    """Ejecuta la estrategia en vivo"""
    
    print("🚀 ETH/BTC Correlation Strategy - Live Trading")
    print("=" * 60)
    
    alpaca_config = {
        "API_KEY": os.getenv("ALPACA_API_KEY"),
        "API_SECRET": os.getenv("ALPACA_API_SECRET"),
        "PAPER": True,
        "BASE_URL": "https://paper-api.alpaca.markets"
    }
    
    if not alpaca_config["API_KEY"]:
        print("❌ Error: ALPACA_API_KEY not found in .env")
        return
    
    try:
        broker = Alpaca(alpaca_config)
        strategy = CryptoLeadLagStrategy(broker=broker)
        
        print("🔄 Starting live strategy...")
        print("📊 Monitoring BTC for 5%+ moves")
        print("🛑 Press Ctrl+C to stop\n")
        
        strategy.run_live()
        
    except KeyboardInterrupt:
        print("\n🛑 Strategy stopped by user")
    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    import sys
    
    mode = sys.argv[1] if len(sys.argv) > 1 else "backtest"
    
    if mode == "live":
        run_live()
    else:
        run_backtest()