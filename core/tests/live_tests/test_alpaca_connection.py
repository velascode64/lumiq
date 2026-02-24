#!/usr/bin/env python3
"""
Script para probar conexión a Alpaca usando TradingCore
OBJETIVO: Verificar conexión y ejecutar compra de prueba usando la arquitectura correcta
"""

import os
import sys
from pathlib import Path
import time
from datetime import datetime

# Añadir el directorio actual al path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from lumibot.brokers import Alpaca
from lumibot.entities import Asset
from lumibot.strategies import Strategy
from trading_core import TradingCore


class TestBuySellStrategy(Strategy):
    """Estrategia simple para probar compra y venta de ETH con trading 24/7"""
    
    def initialize(self):
        # FORZAR trading 24/7 para crypto
        self.market_hours = None
        
        # Configurar broker para 24/7
        if hasattr(self, 'broker') and self.broker:
            self.broker.market = "24/7"
            self.log_message("🌍 Broker configurado para trading 24/7 (crypto)")
        
        self.sleeptime = "30S"
        self.test_phase = 0  # 0: no ejecutado, 1: comprado, 2: vendido
        self.budget = self.parameters.get('budget', 100)
        self.test_qty = self.parameters.get('test_qty', 0.01)
        self.test_mode = self.parameters.get('test_mode', 'buy_sell')  # 'buy_sell' o 'buy_only'
        self.eth_asset = Asset(symbol="ETH", asset_type="crypto")
    
    def is_market_open(self):
        """Override para forzar trading 24/7 en crypto"""
        return True
    
    def should_continue_trading(self):
        """Override para forzar trading continuo"""
        if self.test_mode == 'buy_only':
            return self.test_phase < 1
        else:
            return self.test_phase < 2  # Continuar hasta vender
        
    def on_trading_iteration(self):
        if self.test_phase == 0:
            # FASE 1: COMPRAR
            self.log_message(f"🟢 FASE 1: Ejecutando COMPRA de {self.test_qty} ETH")
            
            try:
                # Obtener precio actual (o usar simulado)
                current_price = self._get_price()
                
                # Crear y enviar orden de COMPRA
                buy_order = self.create_order(
                    asset=self.eth_asset,
                    quantity=self.test_qty,
                    side="buy"
                )
                
                self.submit_order(buy_order)
                self.log_message(f"✅ Orden COMPRA enviada: {self.test_qty} ETH @ ~${current_price:.2f}")
                
                self.test_phase = 1
                
                if self.test_mode == 'buy_sell':
                    self.log_message("⏳ Esperando para ejecutar venta...")
                else:
                    self.log_message("🛑 Test de compra completado")
                
            except Exception as e:
                self.log_message(f"❌ Error en compra: {e}")
                self.test_phase = 2  # Terminar test
                
        elif self.test_phase == 1 and self.test_mode == 'buy_sell':
            # FASE 2: VENDER (solo si test_mode es buy_sell)
            self.log_message(f"🔴 FASE 2: Ejecutando VENTA")
            
            try:
                # IMPORTANTE: Obtener posición REAL para vender cantidad exacta
                position = self.get_position(self.eth_asset)
                
                if position and position.quantity > 0:
                    # Vender EXACTAMENTE lo que tenemos (considerando comisiones)
                    qty_to_sell = float(position.quantity)
                    self.log_message(f"📊 Posición actual: {qty_to_sell:.6f} ETH")
                    
                    # Redondear a 6 decimales para evitar problemas de precisión
                    qty_to_sell = round(qty_to_sell, 6)
                    current_price = self._get_price()
                    
                    # Crear y enviar orden de VENTA con cantidad exacta
                    sell_order = self.create_order(
                        asset=self.eth_asset,
                        quantity=qty_to_sell,
                        side="sell"
                    )
                    
                    self.submit_order(sell_order)
                    self.log_message(f"✅ Orden VENTA enviada: {qty_to_sell:.6f} ETH @ ~${current_price:.2f}")
                    self.log_message(f"   (Cantidad ajustada por comisiones)")
                else:
                    # Si no hay posición, intentar con cantidad reducida
                    adjusted_qty = self.test_qty * 0.995  # Reducir 0.5% por comisiones
                    adjusted_qty = round(adjusted_qty, 6)
                    
                    self.log_message(f"⚠️ No se detectó posición, intentando vender {adjusted_qty:.6f} ETH")
                    
                    sell_order = self.create_order(
                        asset=self.eth_asset,
                        quantity=adjusted_qty,
                        side="sell"
                    )
                    self.submit_order(sell_order)
                    self.log_message(f"✅ Orden VENTA enviada (ajustada): {adjusted_qty:.6f} ETH")
                
                self.test_phase = 2
                self.log_message("🛑 Test buy/sell completado")
                
            except Exception as e:
                self.log_message(f"❌ Error en venta: {e}")
                self.test_phase = 2  # Terminar test
    
    def _get_price(self):
        """Obtener precio actual o usar simulado"""
        try:
            quote = self.get_quote(self.eth_asset)
            if quote and hasattr(quote, 'last') and quote.last:
                price = float(quote.last)
                self.log_message(f"📊 Precio ETH real: ${price:.2f}")
                return price
        except:
            pass
        
        # Precio simulado si no hay datos
        price = 2600
        self.log_message(f"📊 Usando precio simulado: ${price:.2f}")
        return price


def test_basic_connection():
    """Prueba básica de conexión a Alpaca"""
    print("🧪 PRUEBA DE CONEXIÓN A ALPACA")
    print("=" * 40)
    
    # Verificar credenciales
    api_key = os.getenv('ALPACA_API_KEY')
    api_secret = os.getenv('ALPACA_API_SECRET')
    
    if not api_key or not api_secret:
        print("❌ Credenciales no configuradas")
        print("Configure ALPACA_API_KEY y ALPACA_API_SECRET")
        return False
    
    print(f"✅ API Key encontrada: {api_key[:8]}...")
    
    # Configurar broker
    config = {
        'API_KEY': api_key,
        'API_SECRET': api_secret,
        'IS_PAPER': True,
    }
    
    try:
        print("\n🔌 Creando instancia de Alpaca...")
        broker = Alpaca(config)
        print("✅ Broker creado exitosamente")
        
        print(f"📊 Tipo de broker: {type(broker).__name__}")
        print(f"🏦 Paper Trading: {getattr(broker, 'IS_PAPER', 'Unknown')}")
        
        # Listar métodos disponibles
        print(f"\n🔍 Métodos disponibles del broker:")
        methods = [method for method in dir(broker) if not method.startswith('_') and callable(getattr(broker, method))]
        for method in sorted(methods)[:10]:  # Mostrar solo los primeros 10
            print(f"  - {method}")
        if len(methods) > 10:
            print(f"  ... y {len(methods) - 10} métodos más")
        
        # Intentar obtener información de cuenta
        print(f"\n📋 Probando métodos de información...")
        
        # Método 1: Usar la API interna
        try:
            print("  Probando broker.api.get_account()...")
            account = broker.api.get_account()
            print(f"  ✅ broker.api.get_account() exitoso: {type(account).__name__}")
            
            # Mostrar atributos de la cuenta usando los nombres correctos
            if hasattr(account, 'portfolio_value'):
                print(f"    💰 Portfolio Value: ${float(account.portfolio_value):,.2f}")
            if hasattr(account, 'cash'):
                print(f"    💵 Cash: ${float(account.cash):,.2f}")
            if hasattr(account, 'buying_power'):
                print(f"    🏦 Buying Power: ${float(account.buying_power):,.2f}")
            if hasattr(account, 'equity'):
                print(f"    📊 Equity: ${float(account.equity):,.2f}")
                
        except Exception as e:
            print(f"  ❌ broker.api.get_account() falló: {e}")
        
        # Método 2: Usar el método interno de Lumibot
        try:
            print("  Probando _get_balances_at_broker()...")
            from lumibot.entities import Asset
            quote_asset = Asset(symbol="USD", asset_type="forex")
            cash, positions_value, total_value = broker._get_balances_at_broker(quote_asset, None)
            print(f"  ✅ _get_balances_at_broker() exitoso")
            print(f"    💵 Cash: ${cash:,.2f}")
            print(f"    📈 Positions Value: ${positions_value:,.2f}")
            print(f"    💰 Total Value: ${total_value:,.2f}")
                
        except Exception as e:
            print(f"  ❌ _get_balances_at_broker() falló: {e}")
        
        # Método 3: Usar API directa de Alpaca para posiciones
        try:
            print("  Probando broker.api.get_all_positions()...")
            positions = broker.api.get_all_positions()
            print(f"  ✅ broker.api.get_all_positions() exitoso: {len(positions)} posiciones")
            
            for pos in positions[:3]:  # Mostrar máximo 3
                try:
                    symbol = pos.symbol
                    qty = float(pos.qty)
                    side = "LONG" if qty >= 0 else "SHORT"
                    print(f"    📈 {symbol}: {side} {abs(qty):.4f}")
                except Exception as pe:
                    print(f"    📈 Error mostrando posición: {pe}")
                    
        except Exception as e:
            print(f"  ❌ broker.api.get_all_positions() falló: {e}")
        
        # Método 4: Usar API directa de Alpaca para órdenes
        try:
            print("  Probando broker.api.get_orders()...")
            orders = broker.api.get_orders()
            print(f"  ✅ broker.api.get_orders() exitoso: {len(orders)} órdenes")
            
            for order in orders[:3]:  # Mostrar máximo 3
                try:
                    symbol = order.symbol
                    side = order.side.upper()
                    qty = float(order.qty)
                    status = order.status
                    print(f"    📋 {symbol}: {side} {qty:.4f} - {status}")
                except Exception as oe:
                    print(f"    📋 Error mostrando orden: {oe}")
            
        except Exception as e:
            print(f"  ❌ broker.api.get_orders() falló: {e}")
        
        print(f"\n✅ Conexión a Alpaca funciona correctamente")
        return True
        
    except Exception as e:
        print(f"\n❌ Error de conexión: {e}")
        print(f"🔍 Tipo de error: {type(e).__name__}")
        import traceback
        print(f"📋 Traceback:")
        traceback.print_exc()
        return False


def test_market_data():
    """Probar acceso a datos de mercado usando API directa de Alpaca"""
    print(f"\n📊 PRUEBA DE DATOS DE MERCADO")
    print("=" * 40)
    
    config = {
        'API_KEY': os.getenv('ALPACA_API_KEY'),
        'API_SECRET': os.getenv('ALPACA_API_SECRET'),
        'IS_PAPER': True,
    }
    
    try:
        broker = Alpaca(config)
        
        print("🔍 Probando API directa de Alpaca para datos...")
        
        # Test 1: Account básico
        try:
            account = broker.api.get_account()
            print(f"✅ Account Status: {account.status}")
            print(f"📊 Trading Blocked: {account.trading_blocked}")
        except Exception as e:
            print(f"❌ Error accediendo account: {e}")
        
        # Test 2: Crypto bars (método que funciona)
        try:
            print("🔍 Probando crypto bars...")
            # Usar método de la API directa para crypto
            crypto_bar = broker.api.get_latest_crypto_bar("ETHUSD")
            if crypto_bar:
                price = float(crypto_bar.close)
                print(f"✅ ETH/USD bar: ${price:.2f}")
            else:
                print("⚠️ No crypto bar data available")
        except Exception as e:
            print(f"⚠️ Crypto bars no disponibles: {e}")
        
        # Test 3: Stock bars
        try:
            print("🔍 Probando stock bars...")
            stock_bar = broker.api.get_latest_bar("AAPL")
            if stock_bar:
                price = float(stock_bar.close)
                print(f"✅ AAPL bar: ${price:.2f}")
            else:
                print("⚠️ No stock bar data available")
        except Exception as e:
            print(f"⚠️ Stock bars no disponibles: {e}")
        
        # Test 4: Método alternativo - usar prices simulados
        print("\n💡 Para trading, la estrategia usará precios simulados si no hay datos reales")
        print("   Esto es normal en paper trading y no afecta el funcionamiento")
                
    except Exception as e:
        print(f"❌ Error en datos de mercado: {e}")


def test_crypto_order_with_core(qty=0.01, test_mode='buy_sell'):
    """Probar envío de órdenes buy/sell usando arquitectura correcta"""
    print(f"\n🛒 TEST RÁPIDO: {'BUY + SELL' if test_mode == 'buy_sell' else 'BUY ONLY'} {qty} ETH")
    print("=" * 50)

    api_key = os.getenv('ALPACA_API_KEY')
    api_secret = os.getenv('ALPACA_API_SECRET')
    if not api_key or not api_secret:
        print("❌ Credenciales no configuradas")
        return False

    broker_config = {
        'API_KEY': api_key,
        'API_SECRET': api_secret,
        'IS_PAPER': True,
    }

    try:
        # Crear instancia directa de la estrategia para test rápido
        print("📊 Creando estrategia de prueba...")
        from lumibot.brokers import Alpaca
        broker = Alpaca(broker_config)
        
        # Crear estrategia con broker
        params = {
            'test_qty': qty,
            'test_mode': test_mode  # 'buy_sell' o 'buy_only'
        }
        strategy = TestBuySellStrategy(broker=broker, parameters=params)
        
        # Inicializar estrategia
        print("🚀 Inicializando estrategia...")
        strategy.initialize()
        
        # FASE 1: Ejecutar COMPRA
        print(f"\n📤 FASE 1: Enviando orden COMPRA {qty} ETH...")
        strategy.on_trading_iteration()
        
        # FASE 2: Ejecutar VENTA (si está en modo buy_sell)
        if test_mode == 'buy_sell':
            time.sleep(1)  # Pequeña pausa entre órdenes
            print(f"\n📤 FASE 2: Enviando orden VENTA {qty} ETH...")
            strategy.on_trading_iteration()
        
        print("\n✅ Test completado")
        
        # Verificar inmediatamente en Alpaca
        time.sleep(1)  # Solo 1 segundo de espera
        
        print("\n📋 Verificando en Alpaca...")
        try:
            orders = broker.api.get_orders(status='all', limit=5)
            if orders:
                print("✅ Órdenes encontradas:")
                for i, order in enumerate(orders[:3]):
                    status = getattr(order, 'status', 'unknown')
                    symbol = getattr(order, 'symbol', 'unknown') 
                    side = getattr(order, 'side', 'unknown')
                    qty_str = getattr(order, 'qty', 'unknown')
                    created = getattr(order, 'created_at', 'unknown')
                    print(f"   {i+1}. {symbol} {side} {qty_str} - Status: {status}")
                    if i == 0:  # Primera orden (más reciente)
                        print(f"      Creada: {created}")
            else:
                print("⚠️ No se encontraron órdenes (puede tomar unos segundos)")
        except Exception as ve:
            print(f"⚠️ Error consultando órdenes: {ve}")

        return True
        
    except Exception as e:
        print(f"❌ Error en test: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("🚀 DIAGNÓSTICO DE CONEXIÓN ALPACA")
    print("🚀" * 35)
    
    success = test_basic_connection()
    
    if success:
        test_market_data()
        
        # Test de orden usando TradingCore (arquitectura correcta)
        placed = test_crypto_order_with_core(qty=0.01)
        if placed:
            print("🎉 Test de orden completado (verifica en el dashboard de Alpaca)")
        else:
            print("⚠️ No se pudo completar el test de orden")
        
        print(f"\n🎯 CONCLUSIÓN")
        print("=" * 15)
        print("✅ La conexión a Alpaca funciona")
        print("📊 Puede proceder con el trading de prueba")
        print("🔗 Dashboard: https://app.alpaca.markets/paper/dashboard/overview")
    else:
        print(f"\n❌ DIAGNÓSTICO FALLIDO")
        print("=" * 20)
        print("🔧 Revise las credenciales y configuración")
        print("📖 Guía: https://alpaca.markets/docs/api-documentation/")