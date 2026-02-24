#!/usr/bin/env python3
"""
Script para probar la estrategia ETH MACD con la nueva arquitectura
Usa log_message estructurado y TradingCore con UI callbacks
"""

import os
import sys
from pathlib import Path

# Añadir directorio actual al path
sys.path.insert(0, str(Path(__file__).parent))

from trading_core import TradingCore
from strategies.live.eth_5min_macd_strategy import ETH5MinMACDStrategy
from strategies.live.eth_max_min_5min import ETH10MinHighLowMidStrategy

def ui_callback(tick_data):
    """Callback para mostrar señales de trading en consola"""
    print("\n" + "="*60)
    print(f"📊 TICK #{tick_data['tick_number']} - {tick_data['timestamp']}")
    print(f"💰 Precio ETH: ${tick_data['price']:.2f}")
    print(f"🎯 Acción: {tick_data['action']}")
    print(f"📝 Razón: {tick_data['reason']}")
    print(f"📈 Señal: {tick_data['signal']}")
    
    # Mostrar indicadores técnicos
    indicators = tick_data.get('indicators', {})
    if indicators:
        print(f"📊 Indicadores:")
        print(f"   • RSI: {indicators.get('RSI', 0):.1f}")
        print(f"   • MACD: {indicators.get('MACD', 0):.4f}")
        print(f"   • MA20: ${indicators.get('MA20', 0):.2f}")
        print(f"   • Volumen: {indicators.get('Volume', 0):,.0f}")
    
    # Resaltar acciones importantes
    if tick_data['action'] == 'BUY':
        print("🟢 " + "COMPRANDO " * 6 + "🟢")
    elif tick_data['action'] == 'SELL':
        print("🔴 " + "VENDIENDO " * 6 + "🔴")
    elif tick_data['action'] == 'HOLD' and 'Posición abierta' in tick_data['reason']:
        print("🟡 " + "MANTENIENDO POSICIÓN " + "🟡")
    
    print("="*60)


def main():
    print("\n🚀 ESTRATEGIA ETH MACD 5MIN - NUEVA ARQUITECTURA")
    print("=" * 50)
    
    # Verificar credenciales de Alpaca
    api_key = os.getenv('ALPACA_API_KEY')
    api_secret = os.getenv('ALPACA_API_SECRET')
    
    if not api_key or not api_secret:
        print("⚠️  Credenciales de Alpaca no encontradas")
        print("   Configure ALPACA_API_KEY y ALPACA_API_SECRET en .env")
        return
    
    print(f"✅ Credenciales Alpaca: {api_key[:8]}...")
    
    # Configuración del broker (Paper Trading)
    broker_config = {
        'API_KEY': api_key,
        'API_SECRET': api_secret,
        'IS_PAPER': True,  # SIEMPRE paper trading para pruebas
    }
    
    print("\n📊 Inicializando Trading Core...")
    core = TradingCore(broker_config)
    
    print("📝 Registrando estrategia ETH High/Low Mid...")
    core.register_strategy('ETH10MinHighLowMidStrategy', ETH10MinHighLowMidStrategy)
    
    # Parámetros optimizados para la estrategia High/Low Mid
    strategy_params = {
        # Configuración de ventana de máximos/mínimos
        'window_minutes': 3,        # Ventana de 3 minutos
        'profit_target_pct': 0.01,  # 1% profit target
        'stop_loss_pct': 0.005,     # 0.5% stop loss
        'position_size': 0.10,      # 10% del portfolio
        'budget': 10000,             # Presupuesto inicial
        
        # Límites de trading
        'max_trades_per_day': 20,   # Máximo 20 trades por día
    }
    
    print("\n⚙️  CONFIGURACIÓN ETH HIGH/LOW MID STRATEGY:")
    print(f"  • Símbolo: ETH/USD")
    print(f"  • Timeframe: 1 minuto (ventana de {strategy_params['window_minutes']} min)")
    print(f"  • Profit Target: {strategy_params['profit_target_pct']*100:.1f}%")
    print(f"  • Stop Loss: {strategy_params['stop_loss_pct']*100:.1f}%")
    print(f"  • Tamaño Posición: {strategy_params['position_size']*100:.0f}%")
    print(f"  • Presupuesto: ${strategy_params['budget']:,}")
    print(f"  • Max trades/día: {strategy_params['max_trades_per_day']}")
    print(f"  • Modo: Paper Trading 📝")
    print(f"  • Horario: 24/7 (Crypto) 🌍")
    print(f"\n💡 Estrategia: Compra cuando precio <= punto medio H/L de ventana {strategy_params['window_minutes']}min")
    
    print("\n📱 Dashboard Alpaca:")
    print("   https://app.alpaca.markets/paper/dashboard/overview")
    
    print(f"\n🎯 Iniciando estrategia...")
    print(f"⏹️  Presiona Ctrl+C para detener")
    print(f"📊 Las señales aparecerán abajo:\n")
    
    try:
        # Ejecutar estrategia con UI callback
        strategy_instance = core.run(
            strategy='ETH10MinHighLowMidStrategy',
            mode='paper',
            params=strategy_params,
            ui_callback=ui_callback,
            sleeptime='1M'  # La estrategia ya tiene sleeptime="1M" interno
        )
        
        print("\n✅ Estrategia completada")
        
    except KeyboardInterrupt:
        print("\n\n⏹️  Estrategia detenida por el usuario")
        try:
            core.stop()
        except:
            pass
        
    except Exception as e:
        print(f"\n❌ Error ejecutando estrategia:")
        print(f"   {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
    
    finally:
        print(f"\n📊 Revisa tus trades en el dashboard de Alpaca")
        print(f"🔗 https://app.alpaca.markets/paper/dashboard/overview")


if __name__ == "__main__":
    main()