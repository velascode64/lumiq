#!/usr/bin/env python3
"""
Test directo de crypto trading sin verificaciones de horario
Bypass completo de las restricciones de mercado
"""

import os
import sys
import time
from pathlib import Path
from datetime import datetime

# Añadir el directorio actual al path
sys.path.insert(0, str(Path(__file__).parent))

from lumibot.brokers import Alpaca
from lumibot.entities import Asset


def test_direct_crypto_order():
    """Test directo de orden de crypto bypassing Lumibot strategy"""
    
    print("\n🧪 TEST DIRECTO DE CRYPTO TRADING")
    print("=" * 50)
    
    # Verificar credenciales
    api_key = os.getenv('ALPACA_API_KEY')
    api_secret = os.getenv('ALPACA_API_SECRET')
    
    if not api_key or not api_secret:
        print("❌ Credenciales no configuradas")
        return
    
    print(f"✅ Credenciales: {api_key[:8]}...")
    
    # Configuración
    config = {
        'API_KEY': api_key,
        'API_SECRET': api_secret,
        'IS_PAPER': True,
    }
    
    try:
        # Crear broker
        print("\n🔌 Conectando a Alpaca...")
        broker = Alpaca(config)
        
        # Obtener info de cuenta
        account = broker.api.get_account()
        print(f"💰 Cash: ${float(account.cash):,.2f}")
        print(f"📊 Portfolio: ${float(account.portfolio_value):,.2f}")
        print(f"🏦 Account Status: {account.status}")
        
        # Crear asset de crypto
        print(f"\n📈 Probando con BTC/USD...")
        
        # Crear orden directamente usando la API de Alpaca
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce
        
        print(f"🎯 Creando orden de compra de $10 BTC...")
        
        # Crear order request
        market_order_data = MarketOrderRequest(
            symbol="BTC/USD",
            notional=10.0,  # $10 worth of BTC
            side=OrderSide.BUY,
            time_in_force=TimeInForce.GTC,
        )
        
        # Enviar orden
        print(f"📤 Enviando orden...")
        order = broker.api.submit_order(order_data=market_order_data)
        
        print(f"✅ ¡ORDEN ENVIADA EXITOSAMENTE!")
        print(f"   Order ID: {order.id}")
        print(f"   Symbol: {order.symbol}")
        print(f"   Side: {order.side}")
        print(f"   Notional: ${order.notional}")
        print(f"   Status: {order.status}")
        print(f"   Submitted At: {order.submitted_at}")
        
        # Esperar un poco y verificar status
        print(f"\n⏳ Esperando 5 segundos para verificar ejecución...")
        time.sleep(5)
        
        # Obtener orden actualizada
        updated_order = broker.api.get_order_by_id(order.id)
        print(f"\n📊 STATUS ACTUALIZADO:")
        print(f"   Status: {updated_order.status}")
        
        if hasattr(updated_order, 'filled_qty') and updated_order.filled_qty:
            print(f"   Filled Qty: {updated_order.filled_qty}")
        if hasattr(updated_order, 'filled_avg_price') and updated_order.filled_avg_price:
            print(f"   Filled Price: ${float(updated_order.filled_avg_price):.6f}")
        
        # Verificar posiciones
        print(f"\n📈 Verificando posiciones...")
        positions = broker.api.get_all_positions()
        
        btc_positions = [pos for pos in positions if pos.symbol == "BTC/USD"]
        if btc_positions:
            pos = btc_positions[0]
            print(f"✅ Posición BTC encontrada:")
            print(f"   Quantity: {pos.qty}")
            print(f"   Market Value: ${float(pos.market_value):,.6f}")
            print(f"   Avg Cost: ${float(pos.avg_cost):,.6f}")
        else:
            print(f"📊 No se encontraron posiciones BTC (puede estar procesándose)")
        
        print(f"\n🔗 Verifique en su dashboard:")
        print(f"   https://app.alpaca.markets/paper/dashboard/overview")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print(f"\n🚀 TEST DIRECTO DE CRYPTO - {datetime.now().strftime('%H:%M:%S')}")
    print("Este script bypass las verificaciones de horario de Lumibot")
    print("y envía órdenes crypto directamente a Alpaca API\n")
    
    response = input("¿Ejecutar test directo? (SI/NO): ")
    if response.upper() != 'SI':
        print("Cancelado")
        return
    
    success = test_direct_crypto_order()
    
    if success:
        print(f"\n🎉 ¡TEST EXITOSO!")
        print("La orden crypto se envió correctamente bypassing horarios")
        print("Ahora sabes que el problema es la verificación de horario en Lumibot")
    else:
        print(f"\n❌ Test falló, revisar errores arriba")


if __name__ == "__main__":
    main()