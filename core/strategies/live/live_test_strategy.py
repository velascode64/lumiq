"""
Estrategia de Test para Pruebas Live del Core
Genera órdenes de compra y venta periódicas para probar el comportamiento del core en tiempo real
"""

from datetime import datetime, timedelta

from lumibot.strategies import Strategy
from lumibot.entities import Asset


class LiveTestStrategy(Strategy):
    """
    Estrategia de prueba para testing live del core.
    
    Genera órdenes de compra y venta automáticas a intervalos regulares
    para probar el flujo completo del sistema en tiempo real.
    """
    
    def initialize(self):
        """Inicializa la estrategia de prueba"""
        # FORZAR trading continuo para crypto (24/7)
        self.market_hours = None  # Disable market hours checking
        
        # Parámetros configurables
        # Usar formato correcto para crypto: BASE/QUOTE
        self.test_symbols = self.parameters.get('test_symbols', ['BTC/USD', 'ETH/USD', 'SOL/USD'])
        self.order_interval_minutes = self.parameters.get('order_interval_minutes', 5)
        self.order_size_usd = self.parameters.get('order_size_usd', 100)
        self.max_position_per_symbol = self.parameters.get('max_position_per_symbol', 1000)
        self.test_duration_hours = self.parameters.get('test_duration_hours', 1)
        self.enable_stop_loss = self.parameters.get('enable_stop_loss', True)
        self.enable_take_profit = self.parameters.get('enable_take_profit', True)
        self.stop_loss_pct = self.parameters.get('stop_loss_pct', 0.02)  # 2%
        self.take_profit_pct = self.parameters.get('take_profit_pct', 0.03)  # 3%
        
        # Estado interno
        self.start_time = datetime.now()
        self.last_order_time = {}
        self.order_count = 0
        self.successful_orders = 0
        self.failed_orders = 0
        self.total_value_traded = 0
        self.test_phase = 'BUY'  # Alterna entre BUY y SELL
        
        # Inicializar últimas órdenes para cada símbolo
        for symbol in self.test_symbols:
            self.last_order_time[symbol] = datetime.now() - timedelta(minutes=self.order_interval_minutes)
        
        # Log inicial
        self._log_initialization()
    
    def is_market_open(self):
        """Override para forzar que siempre consideremos el mercado abierto (crypto 24/7)"""
        return True
    
    def should_continue_trading(self):
        """Override para forzar trading continuo"""
        return True
        
    def _log_initialization(self):
        """Log de configuración inicial"""
        self.log_message("=" * 70)
        self.log_message("LIVE TEST STRATEGY - INICIANDO PRUEBAS")
        self.log_message("=" * 70)
        self.log_message(f"Hora de inicio: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        self.log_message(f"Duración de prueba: {self.test_duration_hours} horas")
        self.log_message(f"Símbolos de prueba: {', '.join(self.test_symbols)}")
        self.log_message(f"Intervalo entre órdenes: {self.order_interval_minutes} minutos")
        self.log_message(f"Tamaño de orden: ${self.order_size_usd}")
        self.log_message(f"Posición máxima por símbolo: ${self.max_position_per_symbol}")
        self.log_message(f"Stop Loss: {'Sí' if self.enable_stop_loss else 'No'} ({self.stop_loss_pct*100:.1f}%)")
        self.log_message(f"Take Profit: {'Sí' if self.enable_take_profit else 'No'} ({self.take_profit_pct*100:.1f}%)")
        self.log_message("=" * 70)
        
    def on_trading_iteration(self):
        """Iteración principal de trading"""
        try:
            current_time = datetime.now()
            
            # Verificar si ha pasado el tiempo de prueba
            if self._check_test_duration():
                self._finalize_test()
                self.stop()
                return
            
            # Log de estado cada iteración
            self._log_iteration_status()
            
            # Procesar cada símbolo
            for symbol in self.test_symbols:
                self._process_symbol(symbol, current_time)
                
            # Gestionar órdenes existentes
            self._manage_existing_orders()
            
        except Exception as e:
            self.log_message(f"ERROR en iteración: {str(e)}", color="red")
            self.failed_orders += 1
            
    def _process_symbol(self, symbol: str, current_time: datetime):
        """Procesa órdenes para un símbolo específico"""
        # Verificar si es tiempo de crear una nueva orden
        time_since_last_order = current_time - self.last_order_time[symbol]
        
        if time_since_last_order.total_seconds() >= (self.order_interval_minutes * 60):
            # Crear asset de crypto con el formato correcto BASE/QUOTE
            if '/' in symbol:
                # Para crypto: BTC/USD -> asset_type="crypto"
                asset = Asset(symbol=symbol, asset_type="crypto")
            else:
                # Para stocks tradicionales
                asset = Asset(symbol=symbol, asset_type="stock")
            
            # Obtener precio actual
            current_price = self.get_last_price(asset)
            if not current_price:
                self.log_message(f"No se pudo obtener precio para {symbol}", color="yellow")
                return
                
            # Obtener posición actual
            position = self.get_position(asset)
            current_value = 0
            
            if position:
                current_value = float(position.quantity) * float(current_price)
                
            # Decidir tipo de orden basado en la fase de prueba y posición actual
            if self.test_phase == 'BUY' and current_value < self.max_position_per_symbol:
                self._create_buy_order(asset, current_price)
                self.test_phase = 'SELL'  # Alternar para la próxima vez
            elif self.test_phase == 'SELL' and position and position.quantity > 0:
                self._create_sell_order(asset, position, current_price)
                self.test_phase = 'BUY'  # Alternar para la próxima vez
            else:
                # Si no podemos ejecutar la orden planeada, intentar la opuesta
                if current_value < self.max_position_per_symbol:
                    self._create_buy_order(asset, current_price)
                elif position and position.quantity > 0:
                    self._create_sell_order(asset, position, current_price)
                    
            self.last_order_time[symbol] = current_time
            
    def _create_buy_order(self, asset: Asset, current_price: float):
        """Crea una orden de compra de prueba"""
        try:
            # Calcular cantidad
            quantity = self.order_size_usd / float(current_price)
            
            self.log_message("\n" + "📈" * 20)
            self.log_message(f"CREANDO ORDEN DE COMPRA - {asset.symbol}")
            self.log_message(f"Precio actual: ${current_price:.2f}")
            self.log_message(f"Cantidad: {quantity:.4f}")
            self.log_message(f"Valor: ${self.order_size_usd:.2f}")
            
            # Crear orden de mercado
            order = self.create_order(
                asset,
                quantity,
                "buy",
                type="market"
            )
            
            self.order_count += 1
            self.total_value_traded += self.order_size_usd
            
            # Si está habilitado, crear órdenes de stop loss y take profit
            if self.enable_stop_loss or self.enable_take_profit:
                self._create_bracket_orders(asset, quantity, current_price)
                
            self.log_message(f"Orden creada exitosamente - ID: {order.id if order else 'N/A'}")
            self.log_message("📈" * 20 + "\n")
            
            self.successful_orders += 1
            
        except Exception as e:
            self.log_message(f"Error creando orden de compra: {str(e)}", color="red")
            self.failed_orders += 1
            
    def _create_sell_order(self, asset: Asset, position, current_price: float):
        """Crea una orden de venta de prueba"""
        try:
            # Vender una porción de la posición
            quantity_to_sell = min(
                position.quantity * 0.5,  # Vender 50% de la posición
                self.order_size_usd / float(current_price)
            )
            
            self.log_message("\n" + "📉" * 20)
            self.log_message(f"CREANDO ORDEN DE VENTA - {asset.symbol}")
            self.log_message(f"Precio actual: ${current_price:.2f}")
            self.log_message(f"Cantidad: {quantity_to_sell:.4f}")
            self.log_message(f"Valor aproximado: ${quantity_to_sell * current_price:.2f}")
            
            # Crear orden de mercado
            order = self.create_order(
                asset,
                quantity_to_sell,
                "sell",
                type="market"
            )
            
            self.order_count += 1
            self.total_value_traded += quantity_to_sell * current_price
            
            self.log_message(f"Orden creada exitosamente - ID: {order.id if order else 'N/A'}")
            self.log_message("📉" * 20 + "\n")
            
            self.successful_orders += 1
            
        except Exception as e:
            self.log_message(f"Error creando orden de venta: {str(e)}", color="red")
            self.failed_orders += 1
            
    def _create_bracket_orders(self, _asset: Asset, _quantity: float, entry_price: float):
        """Crea órdenes bracket (stop loss y take profit)"""
        try:
            if self.enable_stop_loss:
                stop_price = entry_price * (1 - self.stop_loss_pct)
                self.log_message(f"Creando Stop Loss a ${stop_price:.2f}")
                # Nota: La implementación real depende del broker
                # self.create_order(asset, quantity, "sell", type="stop", stop_price=stop_price)
                
            if self.enable_take_profit:
                limit_price = entry_price * (1 + self.take_profit_pct)
                self.log_message(f"Creando Take Profit a ${limit_price:.2f}")
                # self.create_order(asset, quantity, "sell", type="limit", limit_price=limit_price)
                
        except Exception as e:
            self.log_message(f"Error creando órdenes bracket: {str(e)}", color="yellow")
            
    def _manage_existing_orders(self):
        """Gestiona y monitorea órdenes existentes"""
        orders = self.get_orders()
        
        if orders:
            self.log_message(f"\n🔄 Órdenes activas: {len(orders)}")
            for order in orders[:5]:  # Mostrar máximo 5 órdenes
                status_emoji = "⏳" if order.status == "pending" else "✅"
                self.log_message(
                    f"  {status_emoji} {order.side.upper()} {order.quantity:.4f} "
                    f"{order.asset.symbol} - Status: {order.status}"
                )
                
    def _log_iteration_status(self):
        """Log del estado actual de la estrategia"""
        current_time = datetime.now()
        elapsed = current_time - self.start_time
        
        # Calcular métricas
        portfolio_value = self.portfolio_value
        cash = self.cash
        positions = self.get_positions()
        
        self.log_message("\n" + "─" * 60)
        self.log_message(f"ESTADO DE PRUEBA - {current_time.strftime('%H:%M:%S')}")
        self.log_message("─" * 60)
        self.log_message(f"Tiempo transcurrido: {self._format_timedelta(elapsed)}")
        self.log_message(f"Valor del portfolio: ${portfolio_value:,.2f}")
        self.log_message(f"Efectivo disponible: ${cash:,.2f}")
        self.log_message(f"Posiciones activas: {len(positions)}")
        self.log_message(f"Órdenes totales: {self.order_count}")
        self.log_message(f"Exitosas: {self.successful_orders} | Fallidas: {self.failed_orders}")
        self.log_message(f"Valor total operado: ${self.total_value_traded:,.2f}")
        
        # Mostrar posiciones actuales
        if positions:
            self.log_message("\nPosiciones:")
            for pos in positions:
                if pos.quantity > 0:
                    try:
                        current_price = self.get_last_price(pos.asset)
                        if current_price:
                            value = float(pos.quantity) * float(current_price)
                            self.log_message(
                                f"  {pos.asset.symbol}: {pos.quantity:.4f} @ "
                                f"${current_price:.2f} = ${value:,.2f}"
                            )
                    except:
                        self.log_message(f"  {pos.asset.symbol}: {pos.quantity:.4f} unidades")
                        
    def _check_test_duration(self) -> bool:
        """Verifica si se ha alcanzado la duración máxima de prueba"""
        elapsed = datetime.now() - self.start_time
        return elapsed.total_seconds() >= (self.test_duration_hours * 3600)
        
    def _finalize_test(self):
        """Finaliza la prueba y muestra estadísticas finales"""
        self.log_message("\n" + "=" * 70)
        self.log_message("PRUEBA FINALIZADA - RESUMEN")
        self.log_message("=" * 70)
        
        elapsed = datetime.now() - self.start_time
        success_rate = (self.successful_orders / self.order_count * 100) if self.order_count > 0 else 0
        
        self.log_message(f"Duración total: {self._format_timedelta(elapsed)}")
        self.log_message(f"Órdenes ejecutadas: {self.order_count}")
        self.log_message(f"Tasa de éxito: {success_rate:.1f}%")
        self.log_message(f"Valor total operado: ${self.total_value_traded:,.2f}")
        self.log_message(f"Valor final del portfolio: ${self.portfolio_value:,.2f}")
        
        # Cerrar todas las posiciones pendientes
        self._close_all_positions()
        
        self.log_message("=" * 70)
        self.log_message("Prueba completada exitosamente")
        
    def _close_all_positions(self):
        """Cierra todas las posiciones abiertas al finalizar la prueba"""
        positions = self.get_positions()
        
        if positions:
            self.log_message("\n🔒 Cerrando todas las posiciones...")
            for position in positions:
                if position.quantity > 0:
                    try:
                        self.create_order(
                            position.asset,
                            position.quantity,
                            "sell",
                            type="market"
                        )
                        self.log_message(f"  Cerrando {position.asset.symbol}: {position.quantity:.4f}")
                    except Exception as e:
                        self.log_message(f"  Error cerrando {position.asset.symbol}: {str(e)}", color="red")
                        
    def _format_timedelta(self, td: timedelta) -> str:
        """Formatea un timedelta en formato legible"""
        total_seconds = int(td.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        
    def on_filled_order(self, position, order, price, quantity, multiplier):
        """Callback cuando una orden se completa"""
        super().on_filled_order(position, order, price, quantity, multiplier)
        
        value = float(quantity) * float(price)
        
        self.log_message("\n" + "✅" * 25)
        self.log_message("ORDEN COMPLETADA")
        self.log_message(f"  Tipo: {order.side.upper()}")
        self.log_message(f"  Símbolo: {order.asset.symbol}")
        self.log_message(f"  Cantidad: {quantity:.4f}")
        self.log_message(f"  Precio: ${price:.2f}")
        self.log_message(f"  Valor: ${value:,.2f}")
        self.log_message("✅" * 25 + "\n")
        
    def on_aborted_order(self, order):
        """Callback cuando una orden es abortada"""
        super().on_aborted_order(order)
        
        self.log_message("\n" + "❌" * 25)
        self.log_message("ORDEN ABORTADA")
        self.log_message(f"  Símbolo: {order.asset.symbol}")
        self.log_message(f"  Tipo: {order.side}")
        self.log_message(f"  Cantidad: {order.quantity}")
        self.log_message("❌" * 25 + "\n")
        
    def on_canceled_order(self, order):
        """Callback cuando una orden es cancelada"""
        super().on_canceled_order(order)
        
        self.log_message("\n" + "⚠️" * 25)
        self.log_message("ORDEN CANCELADA")
        self.log_message(f"  Símbolo: {order.asset.symbol}")
        self.log_message(f"  Tipo: {order.side}")
        self.log_message(f"  Cantidad: {order.quantity}")
        self.log_message("⚠️" * 25 + "\n")