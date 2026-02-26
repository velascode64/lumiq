#!/usr/bin/env python3
"""
Script para ejecutar la estrategia ETH MACD directamente
Debe funcionar 24/7 con crypto
"""

import os
import sys
from pathlib import Path

# Añadir el directorio actual al path
sys.path.insert(0, str(Path(__file__).parent))

# Añadir el directorio core al path para importar módulos
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from trading_core import TradingCore
from strategies.live.eth_5min_macd_strategy import ETH5MinMACDStrategy


def ui_callback(tick_data):
    """Callback para imprimir actualizaciones de la estrategia en consola"""
    print("\n" + "="*60)
    print(f"📊 TICK #{tick_data['tick_number']} - {tick_data['timestamp']}")
    print(f"💰 Precio: ${tick_data['price']:.2f}")
    print(f"🎯 Acción: {tick_data['action']}")
    print(f"📝 Razón: {tick_data['reason']}")
    print(f"📈 Señal: {tick_data['signal']}")
    
    # Mostrar indicadores
    indicators = tick_data.get('indicators', {})
    if indicators:
        print(f"📊 Indicadores:")
        print(f"   • RSI: {indicators.get('RSI', 0):.1f}")
        print(f"   • MACD: {indicators.get('MACD', 0):.4f}")
        print(f"   • MA20: {indicators.get('MA20', 0):.2f}")
        print(f"   • Volumen: {indicators.get('Volume', 0):.0f}")
    
    # Resaltar acciones importantes
    if tick_data['action'] == 'BUY':
        print("🟢 " + "COMPRANDO " * 5 + "🟢")
    elif tick_data['action'] == 'SELL':
        print("🔴 " + "VENDIENDO " * 5 + "🔴")
    
    print("="*60 + "\n")


def main():
    print("\n" + "🚀" * 30)
    print("EJECUTANDO ESTRATEGIA ETH MACD 5MIN")
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
    
    # Registrar la estrategia ETH
    print("📝 Registrando estrategia ETH MACD...")
    core.register_strategy('ETH5MinMACD', ETH5MinMACDStrategy)
    
    # Parámetros de la estrategia ETH
    eth_params = {
        # ⚠️ AGGRESSIVE TEST SETTINGS – más señales y salidas rápidas
        'macd_fast': 5,        # antes 8
        'macd_slow': 13,       # antes 17
        'macd_signal': 4,      # antes 9 → cruces más sensibles
        'ma_period': 10,       # antes 20 → media más reactiva
        'rsi_period': 7,       # antes 14 → RSI más volátil
        'stop_loss': 0.002,    # 0.2% (antes 0.5%) → corta pérdidas rápido
        'take_profit': 0.003,  # 0.3% (antes 1%) → toma ganancias rápido
        'position_size': 0.10,  # 10% del portfolio (antes 2%) para ver fills claros
        'budget': 1000         # mismo presupuesto para pruebas
    }
    
    print("\n⚙️  CONFIGURACIÓN ETH MACD:")
    print(f"  Símbolo: ETH/USD 🚀")
    print(f"  Timeframe: 5 minutos")
    print(f"  MACD: ({eth_params['macd_fast']},{eth_params['macd_slow']},{eth_params['macd_signal']})")
    print(f"  MA Period: {eth_params['ma_period']}")
    print(f"  RSI Period: {eth_params['rsi_period']}")
    print(f"  Stop Loss: {eth_params['stop_loss']*100}%")
    print(f"  Take Profit: {eth_params['take_profit']*100}%")
    print(f"  Position Size: {eth_params['position_size']*100}% del portfolio")
    print(f"  Budget: ${eth_params['budget']}")
    print(f"  Modo: Paper Trading (simulado)")
    print(f"  Trading: 24/7 (Crypto) 🌍")
    
    print("\n📱 Los trades aparecerán en:")
    print("   https://app.alpaca.markets/paper/dashboard/overview")
    
    # response = input("\n¿Ejecutar estrategia ETH? (SI/NO): ")
    # if response.upper() != 'SI':
    #     print("Cancelado")
    #     return
    print("\n▶️  Ejecutando automáticamente...")
    
    print("\n🎯 Iniciando estrategia ETH MACD...")
    print("⏹️  Presione Ctrl+C para detener\n")
    
    try:
        # Ejecutar estrategia ETH en paper trading con callback UI
        _ = core.paper_trade(
            'ETH5MinMACD',  # Nombre registrado
            eth_params,
            ui_callback=ui_callback,  # Callback para mostrar ticks
            sleeptime='5M',  # Cada 5 minutos
        )
        
        print("\n✅ Estrategia ETH completada exitosamente")
        
    except KeyboardInterrupt:
        print("\n\n⏹️  Estrategia ETH detenida por el usuario")
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