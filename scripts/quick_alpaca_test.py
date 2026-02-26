#!/usr/bin/env python3
"""
Test rápido de conexión a Alpaca para verificar que funciona con la estrategia
"""

import os
from lumibot.brokers import Alpaca
from lumibot.entities import Asset

def quick_test():
    print("🧪 TEST RÁPIDO ALPACA")
    print("=" * 25)
    
    # Credenciales
    api_key = os.getenv('ALPACA_API_KEY')
    api_secret = os.getenv('ALPACA_API_SECRET')
    
    if not api_key or not api_secret:
        print("❌ No hay credenciales configuradas")
        return False
    
    print(f"✅ API Key: {api_key[:8]}...")
    
    # Configurar broker
    config = {
        'API_KEY': api_key,
        'API_SECRET': api_secret,
        'IS_PAPER': True,
    }
    
    try:
        broker = Alpaca(config)
        print("✅ Broker conectado")
        
        # Test ETH quote (mismo que usa la estrategia)
        eth_asset = Asset(symbol="ETH", asset_type="crypto")
        usd_quote = Asset(symbol="USD", asset_type="forex")
        
        print("🔍 Obteniendo precio ETH...")
        quote = broker.get_quote(eth_asset, quote=usd_quote)
        
        if quote and hasattr(quote, 'last') and quote.last:
            price = float(quote.last)
            print(f"✅ ETH Price: ${price:.2f}")
            return True
        else:
            print("⚠️ No se pudo obtener precio ETH")
            print(f"Quote object: {quote}")
            if quote:
                attrs = [attr for attr in dir(quote) if not attr.startswith('_')]
                print(f"Available attributes: {attrs}")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    success = quick_test()
    if success:
        print("\n🎉 ¡Alpaca funciona correctamente!")
        print("   La estrategia debería poder obtener precios")
    else:
        print("\n⚠️  Hay problemas con la conexión")
        print("   La estrategia usará precios simulados")