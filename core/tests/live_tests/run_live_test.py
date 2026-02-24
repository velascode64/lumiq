#!/usr/bin/env python3
"""
Script para ejecutar la estrategia de test live
Usa los métodos correctos de Lumibot
"""

import os
import sys
from pathlib import Path

# Añadir el directorio actual al path
sys.path.insert(0, str(Path(__file__).parent))

from trading_core import TradingCore
from strategies.live.live_test_strategy import LiveTestStrategy


def main():
    print("\n" + "🚀" * 30)
    print("EJECUTANDO ESTRATEGIA DE TEST LIVE")
    print("🚀" * 30 + "\n")
    
    # Verificar credenciales
    api_key = os.getenv('ALPACA_API_KEY')
    api_secret = os.getenv('ALPACA_API_SECRET')
    
    if not api_key or not api_secret:
        print("❌ Credenciales no configuradas")
        print("Configure ALPACA_API_KEY y ALPACA_API_SECRET")
        return
    
    print(f"✅ Credenciales encontradas: {api_key[:8]}...")
    
    # Configuración del broker
    broker_config = {
        'API_KEY': api_key,
        'API_SECRET': api_secret,
        'IS_PAPER': True,  # SIEMPRE paper trading para pruebas
    }
    
    # Crear el core
    print("\n📊 Inicializando Trading Core...")
    core = TradingCore(broker_config)
    
    # Registrar la estrategia
    print("📝 Registrando estrategia de test...")
    core.register_strategy('live_test', LiveTestStrategy)
    
    # Parámetros de la estrategia (conservadores para prueba)
    test_params = {
        # Usar formato correcto para crypto: BASE/QUOTE (trading 24/7)
        'test_symbols': ['BTC/USD', 'ETH/USD', 'SOL/USD'],  # Criptos con formato correcto
        'order_interval_minutes': 2,  # Orden cada 2 minutos
        'order_size_usd': 10,  # Solo $10 por orden (muy pequeño)
        'max_position_per_symbol': 30,  # Máximo $30 por símbolo
        'test_duration_hours': 0.1,  # 6 minutos de prueba
        'enable_stop_loss': False,  # Sin stop loss para simplificar
        'enable_take_profit': False,  # Sin take profit para simplificar
    }
    
    print("\n⚙️  CONFIGURACIÓN:")
    print(f"  Símbolos: {', '.join(test_params['test_symbols'])}")
    print(f"  Tipo: Criptomonedas (trading 24/7) 🌍")
    print(f"  Intervalo: {test_params['order_interval_minutes']} min")
    print(f"  Tamaño orden: ${test_params['order_size_usd']}")
    print(f"  Duración: {test_params['test_duration_hours'] * 60:.0f} minutos")
    print(f"  Modo: Paper Trading (simulado)")
    
    print("\n📱 Los trades aparecerán en:")
    print("   https://app.alpaca.markets/paper/dashboard/overview")
    
    response = input("\n¿Ejecutar test? (SI/NO): ")
    if response.upper() != 'SI':
        print("Cancelado")
        return
    
    print("\n🎯 Iniciando estrategia...")
    print("⏹️  Presione Ctrl+C para detener\n")
    
    try:
        # Ejecutar en paper trading con configuración para crypto
        _ = core.paper_trade(
            'live_test',
            test_params,
            sleeptime='10S',  # Revisar cada 10 segundos
            market='crypto',  # Especificar mercado crypto
            force_trading=True,  # Forzar trading aunque parezca cerrado
        )
        
        print("\n✅ Test completado exitosamente")
        
    except KeyboardInterrupt:
        print("\n\n⏹️  Test detenido por el usuario")
        core.stop()
        
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
    
    finally:
        print("\n📊 Revise los trades en su dashboard de Alpaca")
        print("🔗 https://app.alpaca.markets/paper/dashboard/overview")


if __name__ == "__main__":
    main()