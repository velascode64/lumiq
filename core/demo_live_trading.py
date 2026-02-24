#!/usr/bin/env python3
"""
Demo de Trading Live - Muestra trades reales en tiempo real
Conecta a Alpaca Paper Trading y muestra toda la actividad en la consola
"""

import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Añadir el directorio actual al path
sys.path.insert(0, str(Path(__file__).parent))

from trading_core import TradingCore
from strategies.live.live_test_strategy import LiveTestStrategy


def setup_console_display():
    """Configurar la consola para mejor visualización"""
    # Limpiar consola
    os.system('clear' if os.name == 'posix' else 'cls')
    
    print("🚀" * 30)
    print("DEMO DE TRADING LIVE - PAPER TRADING")
    print("🚀" * 30)
    print()


def validate_credentials():
    """Validar que las credenciales estén configuradas"""
    api_key = os.getenv('ALPACA_API_KEY')
    api_secret = os.getenv('ALPACA_API_SECRET')
    
    if not api_key or not api_secret:
        print("❌ CREDENCIALES NO CONFIGURADAS")
        print()
        print("Para conectar a Alpaca Paper Trading, configure:")
        print("  export ALPACA_API_KEY='tu-paper-api-key'")
        print("  export ALPACA_API_SECRET='tu-paper-api-secret'")
        print()
        print("📍 Obtenga las credenciales en: https://app.alpaca.markets/paper/dashboard/overview")
        print("   (Sección 'Your API Keys' para Paper Trading)")
        return False
    
    print("✅ Credenciales encontradas")
    print(f"🔑 API Key: {api_key[:8]}...")
    return True


def test_connection(broker_config):
    """Probar conexión a Alpaca"""
    try:
        from lumibot.brokers import Alpaca
        
        print("\n🔌 Probando conexión a Alpaca...")
        broker = Alpaca(broker_config)
        
        # Obtener información de cuenta usando la API correcta de Alpaca
        account = broker.api.get_account()
        portfolio_value = float(account.portfolio_value) if hasattr(account, 'portfolio_value') else 0
        cash = float(account.cash) if hasattr(account, 'cash') else 0
        
        print(f"✅ Conexión exitosa")
        print(f"💰 Valor del Portfolio: ${portfolio_value:,.2f}")
        print(f"💵 Cash Disponible: ${cash:,.2f}")
        
        # Mostrar posiciones actuales usando la API de Alpaca
        try:
            positions = broker.api.get_all_positions()
            print(f"📊 Posiciones Actuales: {len(positions)}")
            
            if positions:
                print("\n📈 POSICIONES EXISTENTES:")
                for pos in positions[:5]:  # Máximo 5
                    try:
                        symbol = pos.symbol
                        qty = float(pos.qty)
                        avg_price = float(pos.avg_cost)
                        current_value = abs(qty * avg_price)  # abs para posiciones cortas
                        side = "LONG" if float(pos.qty) >= 0 else "SHORT"
                        print(f"  {symbol}: {side} {abs(qty):.4f} @ ${avg_price:.2f} = ${current_value:,.2f}")
                    except Exception as pe:
                        print(f"  Error mostrando posición: {pe}")
        except Exception as pe:
            print(f"📊 No se pudieron obtener posiciones: {pe}")
        
        return True, broker
        
    except Exception as e:
        print(f"❌ Error de conexión: {str(e)}")
        print(f"🔍 Detalle del error: {type(e).__name__}")
        return False, None


def show_strategy_config(params):
    """Mostrar configuración de la estrategia"""
    print("\n⚙️  CONFIGURACIÓN DE LA ESTRATEGIA:")
    print("-" * 50)
    print(f"Símbolos a operar: {', '.join(params['test_symbols'])}")
    print(f"Intervalo entre órdenes: {params['order_interval_minutes']} minutos")
    print(f"Tamaño de cada orden: ${params['order_size_usd']}")
    print(f"Posición máxima por símbolo: ${params['max_position_per_symbol']}")
    print(f"Duración de la demo: {params['test_duration_hours'] * 60:.0f} minutos")
    print(f"Stop Loss: {'Sí' if params['enable_stop_loss'] else 'No'}")
    print(f"Take Profit: {'Sí' if params['enable_take_profit'] else 'No'}")
    print("-" * 50)


def run_live_demo():
    """Ejecutar demo de trading live"""
    setup_console_display()
    
    # Validar credenciales
    if not validate_credentials():
        return
    
    # Configuración del broker
    broker_config = {
        'API_KEY': os.getenv('ALPACA_API_KEY'),
        'API_SECRET': os.getenv('ALPACA_API_SECRET'),
        'IS_PAPER': True,  # SIEMPRE paper trading para demos
    }
    
    # Probar conexión
    success, broker = test_connection(broker_config)
    if not success:
        return
    
    print("\n" + "="*60)
    print("🎯 PREPARANDO DEMO DE TRADING")
    print("="*60)
    
    # Parámetros de demo (muy conservadores)
    demo_params = {
        # Usar los símbolos por defecto de la estrategia (ETH, BTC, LTC)
        'test_symbols': ['ETH', 'BTC', 'LTC'],  # Criptos como en la estrategia
        'order_interval_minutes': 2,  # Orden cada 2 minutos
        'order_size_usd': 25,  # $25 por orden (pequeño para demo)
        'max_position_per_symbol': 100,  # Máximo $100 por símbolo
        'test_duration_hours': 0.1,  # 6 minutos de demo
        'enable_stop_loss': True,
        'enable_take_profit': True,
        'stop_loss_pct': 0.02,
        'take_profit_pct': 0.03,
    }
    
    show_strategy_config(demo_params)
    
    # Confirmar ejecución
    print(f"\n⚠️  Esta demo realizará trades reales en PAPER TRADING")
    print(f"📊 Los trades aparecerán en su dashboard de Alpaca Paper")
    response = input("\n¿Continuar con la demo? (escriba 'SI' para confirmar): ")
    
    if response.upper() != 'SI':
        print("Demo cancelada")
        return
    
    # Crear y configurar el core
    core = TradingCore(broker_config)
    core.register_strategy('live_test', LiveTestStrategy)
    
    print("\n" + "🚀" * 20)
    print("INICIANDO DEMO DE TRADING LIVE")
    print("🚀" * 20)
    print(f"⏰ Hora de inicio: {datetime.now().strftime('%H:%M:%S')}")
    print("📱 Puede monitorear los trades también en: https://app.alpaca.markets/paper/dashboard/overview")
    print("⏹️  Presione Ctrl+C para detener en cualquier momento")
    print()
    
    try:
        # Ejecutar la estrategia
        strategy = core.paper_trade(
            'live_test', 
            demo_params,
            sleeptime='10S'  # Revisar cada 10 segundos
        )
        
        print("\n✅ Demo completada exitosamente")
        
    except KeyboardInterrupt:
        print("\n\n⏹️  Demo detenida por el usuario")
        core.stop()
        
    except Exception as e:
        print(f"\n❌ Error durante la demo: {str(e)}")
        import traceback
        traceback.print_exc()
    
    finally:
        print("\n📊 Revise los trades en su dashboard de Alpaca Paper Trading")
        print("🔗 https://app.alpaca.markets/paper/dashboard/overview")


def show_help():
    """Mostrar ayuda"""
    print("DEMO DE TRADING LIVE - Ayuda")
    print("=" * 40)
    print()
    print("Este script demuestra trading live conectándose a Alpaca Paper Trading.")
    print()
    print("REQUISITOS:")
    print("1. Cuenta de Alpaca (gratuita): https://alpaca.markets")
    print("2. API Keys de Paper Trading configuradas")
    print("3. Variables de entorno configuradas:")
    print("   export ALPACA_API_KEY='tu-paper-api-key'")
    print("   export ALPACA_API_SECRET='tu-paper-api-secret'")
    print()
    print("QUÉ HACE:")
    print("- Conecta a Alpaca Paper Trading")
    print("- Ejecuta órdenes reales de criptomonedas")
    print("- Muestra actividad en tiempo real en la consola")
    print("- Los trades aparecen en tu dashboard de Alpaca")
    print()
    print("SEGURIDAD:")
    print("- Solo usa Paper Trading (dinero simulado)")
    print("- Órdenes muy pequeñas ($25)")
    print("- Duración limitada (6 minutos)")
    print("- Fácil de cancelar (Ctrl+C)")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Demo de Trading Live con Paper Trading')
    parser.add_argument('--help-setup', action='store_true', 
                       help='Mostrar ayuda detallada de configuración')
    
    args = parser.parse_args()
    
    if args.help_setup:
        show_help()
    else:
        run_live_demo()