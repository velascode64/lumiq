import datetime as dt
import pytz
from lumibot.credentials import ALPACA_TEST_CONFIG
from lumibot.strategies.strategy import Strategy

"""
Strategy Description: Martin Gala Strategy

Estrategia de promediado a la baja (Dollar Cost Averaging) con gestión de riesgo.
Compra cuando detecta caídas y promedia la posición si continúa bajando.
Incluye stop-loss y take-profit para gestión de riesgo.
"""


class MartinGalaStrategy(Strategy):
    parameters = {
        "symbol": "TSLA",  # Acción (e.g., TSLA, SOFI, AMZN, META)
        "drop_threshold": 0.02,  # Caída mínima para comprar (2%)
        "max_trades": 3,  # Máximo de compras para promediar
        "stop_loss_pct": 0.05,  # Stop-loss (5% por debajo del precio promedio)
        "take_profit_pct": 0.03,  # Take-profit (3% por encima del precio promedio)
        "position_size": 100,  # Tamaño inicial (acciones por compra)
    }

    def initialize(self):
        self.sleeptime = "1D"  # Chequea cada día para backtesting
        self.average_price = 0  # Precio promedio ponderado
        self.total_shares = 0  # Total de acciones compradas
        self.trade_count = 0  # Contador de compras
        self.has_position = False  # Flag para tracking de posición

    def on_trading_iteration(self):
        # Obtener fecha/hora actual para logging
        dt = self.get_datetime()
        
        # Obtener símbolo de los parámetros
        symbol = self.parameters["symbol"]
        
        # Obtener precio actual
        price = self.get_last_price(symbol)
        if price is None:
            self.log_message(f"{dt}: No se pudo obtener precio para {symbol}")
            return

        # Obtener posiciones actuales
        positions = self.get_positions()
        
        # Verificar si tenemos posición en el símbolo
        current_position = None
        for pos in positions:
            if pos.symbol == symbol:
                current_position = pos
                self.has_position = True
                break
        
        # Si no hay posición, buscar oportunidad de compra
        if not current_position:
            bars = self.get_historical_prices(symbol, 2, "day")
            if bars is None or len(bars.df) < 2:
                return
            
            prev_close = bars.df['close'].iloc[-2]
            current_close = bars.df['close'].iloc[-1]
            drop = (prev_close - current_close) / prev_close
            
            # Si hay caída suficiente, comprar
            if drop >= self.parameters["drop_threshold"]:
                # Verificar que tenemos capital suficiente
                cash = self.get_cash()
                shares_to_buy = self.parameters["position_size"]
                cost = shares_to_buy * price
                
                if cash >= cost:
                    self.log_message(f"{dt}: Caída detectada: {drop*100:.2f}%. Comprando {shares_to_buy} acciones de {symbol} a ${price:.2f}")
                    
                    order = self.create_order(
                        symbol,
                        quantity=shares_to_buy,
                        side="buy"
                    )
                    self.submit_order(order)
                    
                    # Actualizar tracking
                    self.average_price = price
                    self.total_shares = shares_to_buy
                    self.trade_count = 1
                    self.has_position = True
                    
                    # Agregar línea al gráfico
                    self.add_line(f"{symbol} Price", price)
                    self.add_line("Average Price", self.average_price)

        # Si hay posición, gestionar promediado o salida
        else:
            quantity = current_position.quantity
            
            # Actualizar tracking si es necesario
            if self.total_shares == 0:
                self.total_shares = quantity
                self.average_price = current_position.avg_fill_price
                self.trade_count = 1
            
            # Logging del estado actual
            unrealized_pl = (price - self.average_price) * self.total_shares
            unrealized_pl_pct = ((price - self.average_price) / self.average_price) * 100
            
            self.log_message(f"{dt}: Posición actual: {self.total_shares} acciones, Precio promedio: ${self.average_price:.2f}, P&L: ${unrealized_pl:.2f} ({unrealized_pl_pct:.2f}%)")
            
            # Agregar líneas al gráfico
            self.add_line(f"{symbol} Price", price)
            self.add_line("Average Price", self.average_price)
            self.add_line("Unrealized P&L %", unrealized_pl_pct)
            
            # Chequear stop-loss
            if price <= self.average_price * (1 - self.parameters["stop_loss_pct"]):
                self.log_message(f"{dt}: Stop-loss alcanzado a ${price:.2f}. Vendiendo {self.total_shares} acciones.")
                
                order = self.create_order(
                    symbol,
                    quantity=self.total_shares,
                    side="sell"
                )
                self.submit_order(order)
                
                # Reset tracking
                self.average_price = 0
                self.total_shares = 0
                self.trade_count = 0
                self.has_position = False
                
            # Chequear take-profit
            elif price >= self.average_price * (1 + self.parameters["take_profit_pct"]):
                self.log_message(f"{dt}: Take-profit alcanzado a ${price:.2f}. Vendiendo {self.total_shares} acciones.")
                
                order = self.create_order(
                    symbol,
                    quantity=self.total_shares,
                    side="sell"
                )
                self.submit_order(order)
                
                # Reset tracking
                self.average_price = 0
                self.total_shares = 0
                self.trade_count = 0
                self.has_position = False
                
            # Chequear si promediar (caída adicional)
            elif self.trade_count < self.parameters["max_trades"]:
                drop_from_avg = (self.average_price - price) / self.average_price
                
                if drop_from_avg >= self.parameters["drop_threshold"]:
                    # Verificar que tenemos capital suficiente
                    cash = self.get_cash()
                    shares_to_buy = self.parameters["position_size"]
                    cost = shares_to_buy * price
                    
                    if cash >= cost:
                        self.log_message(f"{dt}: Caída adicional: {drop_from_avg*100:.2f}%. Promediando con {shares_to_buy} acciones más a ${price:.2f}")
                        
                        order = self.create_order(
                            symbol,
                            quantity=shares_to_buy,
                            side="buy"
                        )
                        self.submit_order(order)
                        
                        # Actualizar precio promedio
                        total_cost = (self.average_price * self.total_shares) + (price * shares_to_buy)
                        self.total_shares += shares_to_buy
                        self.average_price = total_cost / self.total_shares
                        self.trade_count += 1
                        
                        self.log_message(f"{dt}: Nuevo precio promedio: ${self.average_price:.2f}, Total acciones: {self.total_shares}")


if __name__ == "__main__":
    IS_BACKTESTING = True
    
    if IS_BACKTESTING:
        from lumibot.backtesting import AlpacaBacktesting
        
        # Verificar configuración
        if not ALPACA_TEST_CONFIG:
            print("Error: Se requiere configuración ALPACA_TEST_CONFIG en el archivo .env")
            print("Asegúrate de tener ALPACA_TEST_API_KEY y ALPACA_TEST_API_SECRET configurados.")
            exit()
        
        if not ALPACA_TEST_CONFIG['PAPER']:
            print("Advertencia: Usando credenciales de paper trading para backtesting")
        
        # Configurar fechas para el backtest
        tzinfo = pytz.timezone('America/New_York')
        backtesting_start = tzinfo.localize(dt.datetime(2023, 6, 1))  # 6 meses de datos
        backtesting_end = tzinfo.localize(dt.datetime(2024, 1, 1))
        
        print("=" * 60)
        print("Martin Gala Strategy - Backtesting")
        print("=" * 60)
        print(f"Símbolo: TSLA")
        print(f"Período: {backtesting_start.date()} a {backtesting_end.date()}")
        print(f"Capital inicial: $100,000")
        print(f"Parámetros:")
        print(f"  - Umbral de caída: 2%")
        print(f"  - Máximo trades: 3")
        print(f"  - Stop Loss: 5%")
        print(f"  - Take Profit: 3%")
        print("=" * 60)
        
        # Ejecutar backtest
        results, strategy = MartinGalaStrategy.run_backtest(
            datasource_class=AlpacaBacktesting,
            backtesting_start=backtesting_start,
            backtesting_end=backtesting_end,
            minutes_before_closing=0,
            benchmark_asset='SPY',
            analyze_backtest=True,
            parameters={
                "symbol": "TSLA",
                "drop_threshold": 0.02,
                "max_trades": 3,
                "stop_loss_pct": 0.05,
                "take_profit_pct": 0.03,
                "position_size": 10,  # Reducido para backtesting
            },
            show_progress_bar=True,
            # Configuración específica de AlpacaBacktesting
            timestep='day',
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
        # PAPER TRADING / LIVE TRADING
        from lumibot.brokers import Alpaca
        
        # Usar credenciales del .env
        ALPACA_CONFIG = ALPACA_TEST_CONFIG  # Usa las mismas credenciales
        
        if not ALPACA_CONFIG["API_KEY"] or not ALPACA_CONFIG["API_SECRET"]:
            print("Error: Credenciales de Alpaca no encontradas.")
            print("Configura ALPACA_TEST_API_KEY y ALPACA_TEST_API_SECRET en tu archivo .env")
            exit()
        
        print("=" * 60)
        print("Martin Gala Strategy - Paper Trading")
        print("=" * 60)
        print("Iniciando conexión con Alpaca...")
        
        # Inicializar broker
        broker = Alpaca(ALPACA_CONFIG)
        
        # Crear estrategia
        strategy = MartinGalaStrategy(
            broker=broker,
            parameters={
                "symbol": "TSLA",
                "drop_threshold": 0.02,
                "max_trades": 3,
                "stop_loss_pct": 0.05,
                "take_profit_pct": 0.03,
                "position_size": 10,
            }
        )
        
        # Ejecutar estrategia en vivo
        print("Ejecutando estrategia en modo paper trading...")
        strategy.run_live()