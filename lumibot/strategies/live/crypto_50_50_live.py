"""
Estrategia Crypto 50/50 para Trading en Vivo
Rebalancea un portfolio 50% BTC / 50% ETH cuando hay drift
"""

from datetime import datetime
from decimal import Decimal

from lumibot.example_strategies.drift_rebalancer import DriftRebalancer


class Crypto5050Live(DriftRebalancer):
    """
    Estrategia de rebalanceo 50/50 BTC/ETH para trading en vivo.
    Hereda de DriftRebalancer y añade logging mejorado para monitoreo.
    """
    
    def initialize(self):
        """Inicializa la estrategia con logging mejorado"""
        super().initialize()
        
        # Tracking adicional
        self.start_time = datetime.now()
        self.total_trades = 0
        self.last_rebalance = None
        self.initial_portfolio_value = None
        
        # Log inicial
        self.log_message("=" * 60)
        self.log_message("CRYPTO 50/50 STRATEGY - LIVE TRADING")
        self.log_message("=" * 60)
        self.log_message(f"Market: {self.market}")
        self.log_message(f"Sleep time: {self.sleeptime}")
        self.log_message(f"Drift threshold: {float(self.parameters.get('drift_threshold', 0.05))*100:.1f}%")
        self.log_message(f"Order type: {self.parameters.get('order_type', 'MARKET')}")
        self.log_message("Portfolio weights:")
        
        for weight_config in self.parameters.get('portfolio_weights', []):
            asset = weight_config['base_asset']
            weight = weight_config['weight']
            self.log_message(f"  - {asset.symbol}: {float(weight)*100:.0f}%")
        
        self.log_message("=" * 60)
        
    def on_trading_iteration(self):
        """Override para añadir logging detallado"""
        try:
            # Guardar valor inicial del portfolio
            if self.initial_portfolio_value is None:
                self.initial_portfolio_value = self.portfolio_value
            
            # Log del estado actual
            self._log_iteration_start()
            
            # Ejecutar la lógica de rebalanceo del padre
            super().on_trading_iteration()
            
            # Log post-rebalanceo
            self._log_iteration_end()
            
        except Exception as e:
            self.log_message(f"ERROR en iteración: {str(e)}", color="red")
    
    def _log_iteration_start(self):
        """Log al inicio de cada iteración"""
        self.log_message("\n" + "─" * 50)
        self.log_message(f"ITERATION START - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.log_message("─" * 50)
        
        # Portfolio status
        portfolio_value = self.portfolio_value
        cash = self.cash
        
        self.log_message(f"Portfolio Value: ${portfolio_value:,.2f}")
        self.log_message(f"Cash Available: ${cash:,.2f}")
        
        # P&L
        if self.initial_portfolio_value:
            pnl = portfolio_value - self.initial_portfolio_value
            pnl_pct = (pnl / self.initial_portfolio_value) * 100
            color = "green" if pnl >= 0 else "red"
            self.log_message(f"P&L: ${pnl:,.2f} ({pnl_pct:+.2f}%)", color=color)
        
        # Posiciones actuales
        self._log_positions()
        
    def _log_positions(self):
        """Log de posiciones actuales con pesos"""
        positions = self.get_positions()
        portfolio_value = self.portfolio_value
        
        self.log_message("\nCurrent Positions:")
        
        for position in positions:
            if position.quantity > 0:
                symbol = position.asset.symbol
                
                if symbol in ['BTC', 'ETH']:
                    try:
                        current_price = self.get_last_price(position.asset)
                        if current_price:
                            value = float(position.quantity) * float(current_price)
                            weight = (value / portfolio_value) * 100 if portfolio_value > 0 else 0
                            target_weight = self._get_target_weight(symbol)
                            drift = weight - target_weight if target_weight else 0
                            
                            self.log_message(
                                f"  {symbol}: {position.quantity:.6f} units @ ${current_price:.2f} = "
                                f"${value:,.2f} ({weight:.1f}% / Target: {target_weight:.0f}% / "
                                f"Drift: {drift:+.1f}%)"
                            )
                    except Exception as e:
                        self.log_message(f"  {symbol}: Error getting price - {e}")
    
    def _get_target_weight(self, symbol: str) -> float:
        """Obtiene el peso objetivo para un símbolo"""
        for weight_config in self.parameters.get('portfolio_weights', []):
            if weight_config['base_asset'].symbol == symbol:
                return float(weight_config['weight']) * 100
        return 0
    
    def _log_iteration_end(self):
        """Log al final de cada iteración"""
        # Verificar si hay órdenes activas
        orders = self.get_orders()
        
        if orders:
            self.log_message(f"\nActive Orders: {len(orders)}")
            for order in orders:
                side_emoji = "BUY" if order.side == "buy" else "SELL"
                self.log_message(
                    f"  [{side_emoji}] {order.quantity} {order.asset.symbol} - "
                    f"Status: {order.status}"
                )
        else:
            self.log_message("\nNo active orders")
        
        # Estadísticas
        uptime = datetime.now() - self.start_time
        hours, remainder = divmod(int(uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        
        self.log_message(f"\nStats: Uptime {hours:02d}:{minutes:02d}:{seconds:02d} | "
                        f"Rebalances: {self.total_trades}")
    
    def on_filled_order(self, position, order, price, quantity, multiplier):
        """Se ejecuta cuando una orden se completa"""
        super().on_filled_order(position, order, price, quantity, multiplier)
        
        self.total_trades += 1
        self.last_rebalance = datetime.now()
        
        # Log detallado de la orden completada
        side = order.side.upper()
        total_value = float(quantity) * float(price)
        
        self.log_message("\n" + "🟢" * 30)
        self.log_message("ORDER FILLED!")
        self.log_message(f"  Side: {side}")
        self.log_message(f"  Symbol: {order.asset.symbol}")
        self.log_message(f"  Quantity: {quantity}")
        self.log_message(f"  Price: ${price:.2f}")
        self.log_message(f"  Total Value: ${total_value:,.2f}")
        self.log_message("🟢" * 30 + "\n")
    
    def on_aborted_order(self, order):
        """Se ejecuta cuando una orden es abortada"""
        super().on_aborted_order(order)
        
        self.log_message("\n" + "🔴" * 30)
        self.log_message("ORDER ABORTED!")
        self.log_message(f"  Symbol: {order.asset.symbol}")
        self.log_message(f"  Side: {order.side}")
        self.log_message(f"  Quantity: {order.quantity}")
        self.log_message("🔴" * 30 + "\n")
    
    def on_canceled_order(self, order):
        """Se ejecuta cuando una orden es cancelada"""
        super().on_canceled_order(order)
        
        self.log_message("\n" + "🟡" * 30)
        self.log_message("ORDER CANCELED")
        self.log_message(f"  Symbol: {order.asset.symbol}")
        self.log_message(f"  Side: {order.side}")
        self.log_message(f"  Quantity: {order.quantity}")
        self.log_message("🟡" * 30 + "\n")