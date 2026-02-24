#!/usr/bin/env python3
"""
TEST DE COMPRA DIRECTA DE ETH CON ALPACA
OBJETIVO: Comprar 0.01 ETH en ETHUSD y confirmar que aparece en la cuenta
"""

import os
import time
from datetime import datetime

def test_eth_purchase():
    """
    Prueba directa de compra de 0.01 ETH usando API nativa de Alpaca
    Sin Lumibot - directo a la API para confirmar funcionamiento
    """
    
    print("🚀 TEST DE COMPRA DIRECTA DE ETH")
    print("=" * 50)
    print("Objetivo: Comprar 0.01 ETH y confirmar en cuenta Alpaca")
    print("=" * 50)
    
    # Verificar credenciales
    api_key = "PKIV1RARWR371EGM2D2I"
    api_secret = "agQeh664YZBVSd1boWUfrEhOqDck7sb03A8XHeb6"
    
    if not api_key or not api_secret:
        print("❌ ERROR: Credenciales no configuradas")
        print("Configure ALPACA_API_KEY y ALPACA_API_SECRET")
        return False
    
    print(f"✅ API Key: {api_key[:10]}...")
    print(f"✅ API Secret: {api_secret[:10]}...")
    
    try:
        # Importar cliente de trading de Alpaca
        from alpaca.trading.client import TradingClient
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce
        
        print("\n📊 Inicializando cliente Alpaca (Paper Trading)...")
        
        # Cliente para paper trading
        trading_client = TradingClient(
            api_key=api_key,
            secret_key=api_secret,
            paper=True  # Paper trading para pruebas
        )
        
        # Verificar cuenta
        print("🏦 Verificando información de cuenta...")
        account = trading_client.get_account()
        
        print(f"✅ Estado cuenta: {account.status}")
        print(f"💰 Buying Power: ${float(account.buying_power):,.2f}")
        print(f"💼 Portfolio Value: ${float(account.portfolio_value):,.2f}")
        print(f"💵 Cash disponible: ${float(account.cash):,.2f}")
        
        # Verificar estado crypto
        if hasattr(account, 'crypto_status'):
            print(f"🪙 Crypto Status: {account.crypto_status}")
        
        # Obtener precio actual de ETH
        print("\n📈 Obteniendo precio actual de ETH...")
        
        from alpaca.data.historical import CryptoHistoricalDataClient
        from alpaca.data.requests import CryptoBarsRequest
        from alpaca.data.timeframe import TimeFrame
        
        data_client = CryptoHistoricalDataClient(api_key, api_secret)
        
        # Obtener último precio
        bars_request = CryptoBarsRequest(
            symbol_or_symbols="ETH/USD",
            timeframe=TimeFrame.Minute,
            limit=1
        )
        
        bars = data_client.get_crypto_bars(bars_request)
        
        if "ETH/USD" not in bars.data:
            print("❌ ERROR: No se pudo obtener datos de ETH")
            return False
            
        latest_bar = bars.data["ETH/USD"][-1]
        eth_price = float(latest_bar.close)
        
        print(f"💰 Precio actual ETH: ${eth_price:,.2f}")
        
        # Validar precio
        if eth_price < 1000 or eth_price > 10000:
            print(f"🚨 ADVERTENCIA: Precio ETH ${eth_price:,.2f} parece incorrecto")
            print("Expected range: $1,000 - $10,000")
        else:
            print(f"✅ Precio ETH ${eth_price:,.2f} está en rango normal")
        
        # Calcular valor de la orden
        quantity = 0.01
        estimated_value = eth_price * quantity
        
        print(f"\n🛒 PREPARANDO ORDEN DE COMPRA")
        print(f"   Símbolo: ETH/USD")
        print(f"   Lado: BUY")
        print(f"   Cantidad: {quantity} ETH")
        print(f"   Tipo: MARKET")
        print(f"   Valor estimado: ${estimated_value:.2f}")
        
        # Verificar fondos suficientes
        if float(account.buying_power) < estimated_value:
            print(f"❌ ERROR: Fondos insuficientes")
            print(f"   Necesario: ${estimated_value:.2f}")
            print(f"   Disponible: ${float(account.buying_power):,.2f}")
            return False
        
        print(f"✅ Fondos suficientes para la compra")
        
        # Crear orden de mercado
        print(f"\n🚀 EJECUTANDO ORDEN DE COMPRA...")
        
        market_order = MarketOrderRequest(
            symbol="ETH/USD",
            qty=quantity,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.GTC
        )
        
        # Enviar orden
        order = trading_client.submit_order(order_data=market_order)
        
        print(f"🎉 ORDEN ENVIADA EXITOSAMENTE!")
        print(f"   📋 Order ID: {order.id}")
        print(f"   📊 Status: {order.status}")
        print(f"   💰 Símbolo: {order.symbol}")
        print(f"   🔢 Cantidad: {order.qty}")
        print(f"   💵 Lado: {order.side}")
        
        # Esperar y verificar ejecución
        print(f"\n⏳ Esperando ejecución de orden...")
        
        for attempt in range(10):  # Máximo 10 intentos (30 segundos)
            time.sleep(3)
            
            try:
                updated_order = trading_client.get_order_by_id(order.id)
                print(f"   Intento {attempt + 1}: Status = {updated_order.status}")
                
                if updated_order.status in ["filled", "partially_filled"]:
                    print(f"\n✅ ORDEN EJECUTADA!")
                    
                    if updated_order.filled_qty:
                        filled_qty = float(updated_order.filled_qty)
                        print(f"   📊 Cantidad ejecutada: {filled_qty:.6f} ETH")
                    
                    if updated_order.filled_avg_price:
                        fill_price = float(updated_order.filled_avg_price)
                        fill_value = filled_qty * fill_price
                        print(f"   💰 Precio promedio: ${fill_price:.2f}")
                        print(f"   💵 Valor total: ${fill_value:.2f}")
                    
                    break
                    
                elif updated_order.status in ["rejected", "canceled"]:
                    print(f"❌ ORDEN RECHAZADA/CANCELADA: {updated_order.status}")
                    return False
                    
            except Exception as e:
                print(f"   ⚠️ Error verificando orden: {e}")
        
        else:
            print(f"⚠️ Orden aún pendiente después de 30 segundos")
        
        # Verificar posiciones actuales
        print(f"\n📊 VERIFICANDO POSICIONES...")
        
        positions = trading_client.get_all_positions()
        
        eth_position = None
        for position in positions:
            if position.symbol == "ETH/USD":
                eth_position = position
                break
        
        if eth_position:
            qty = float(eth_position.qty)
            market_value = float(eth_position.market_value)
            avg_cost = float(eth_position.avg_cost)
            unrealized_pnl = float(position.unrealized_pl)
            
            print(f"✅ POSICIÓN ETH ENCONTRADA!")
            print(f"   📊 Cantidad: {qty:.6f} ETH")
            print(f"   💰 Valor de mercado: ${market_value:.2f}")
            print(f"   💵 Costo promedio: ${avg_cost:.2f}")
            print(f"   📈 P&L no realizado: ${unrealized_pnl:.2f}")
        else:
            print(f"❌ No se encontró posición ETH")
            print(f"   (Puede ser que la orden aún se esté procesando)")
        
        # Información final
        print(f"\n🎯 RESUMEN DEL TEST")
        print("=" * 30)
        print(f"✅ Conexión a Alpaca: OK")
        print(f"✅ Orden de compra: Enviada")
        print(f"✅ Order ID: {order.id}")
        print(f"📊 Verificar en dashboard:")
        print(f"   https://app.alpaca.markets/paper/dashboard/overview")
        
        return True
        
    except ImportError as e:
        print(f"❌ ERROR: Falta instalar alpaca-py")
        print(f"   Ejecute: pip install alpaca-py")
        print(f"   Error: {e}")
        return False
        
    except Exception as e:
        print(f"\n❌ ERROR INESPERADO: {str(e)}")
        print(f"🔍 Tipo de error: {type(e).__name__}")
        
        import traceback
        print(f"\n📋 Traceback completo:")
        print(traceback.format_exc())
        
        return False


if __name__ == "__main__":
    print("🌟 ALPACA ETH PURCHASE TEST")
    print("🌟" * 30)
    
    success = test_eth_purchase()
    
    if success:
        print(f"\n🎉 TEST COMPLETADO EXITOSAMENTE!")
        print(f"📊 Revise su dashboard de Alpaca para confirmar la compra")
        print(f"🔗 https://app.alpaca.markets/paper/dashboard/overview")
    else:
        print(f"\n❌ TEST FALLIDO")
        print(f"🔧 Revise los errores y configuración")
    
    print(f"\n🚀 Siguiente paso: Arreglar run_eth_strategy.py")