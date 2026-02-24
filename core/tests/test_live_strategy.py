#!/usr/bin/env python3
"""
Script de prueba para la estrategia LiveTestStrategy
Ejecuta pruebas live del core con órdenes simuladas periódicas
"""

import os
import sys
from datetime import datetime
from pathlib import Path

# Añadir el directorio padre al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.trading_core import TradingCore
from core.strategies.live.live_test_strategy import LiveTestStrategy
from lumibot.entities import Asset


def run_live_test(mode='paper'):
    """
    Ejecuta la estrategia de prueba en modo paper o live
    
    Args:
        mode: 'paper' para paper trading, 'live' para trading real
    """
    
    print("\n" + "🚀" * 30)
    print("INICIANDO PRUEBA DE ESTRATEGIA LIVE")
    print("🚀" * 30 + "\n")
    
    # Configuración del broker (Alpaca)
    # IMPORTANTE: Configurar estas variables de entorno antes de ejecutar
    broker_config = {
        'API_KEY': os.getenv('ALPACA_API_KEY', 'your-api-key'),
        'API_SECRET': os.getenv('ALPACA_API_SECRET', 'your-api-secret'),
        'IS_PAPER': mode == 'paper',  # True para paper trading
    }
    
    # Verificar credenciales
    if broker_config['API_KEY'] == 'your-api-key':
        print("⚠️  ADVERTENCIA: No se han configurado las credenciales de Alpaca")
        print("Por favor, configure las siguientes variables de entorno:")
        print("  - ALPACA_API_KEY")
        print("  - ALPACA_API_SECRET")
        print("\nPara modo paper trading, use las credenciales de paper de Alpaca")
        print("Para modo live, use las credenciales de producción (¡con cuidado!)")
        return
    
    # Crear instancia del core
    core = TradingCore(broker_config)
    
    # Registrar la estrategia de prueba
    core.register_strategy('live_test', LiveTestStrategy)
    
    # Parámetros de la estrategia de prueba
    test_params = {
        # Símbolos a operar (usar ETFs líquidos para pruebas)
        'test_symbols': ['SPY', 'QQQ', 'IWM'],
        
        # Intervalo entre órdenes en minutos
        'order_interval_minutes': 2,  # Orden cada 2 minutos para prueba rápida
        
        # Tamaño de cada orden en USD
        'order_size_usd': 100,  # $100 por orden
        
        # Posición máxima por símbolo
        'max_position_per_symbol': 500,  # Máximo $500 por símbolo
        
        # Duración total de la prueba en horas
        'test_duration_hours': 0.5,  # 30 minutos de prueba
        
        # Configuración de gestión de riesgo
        'enable_stop_loss': True,
        'enable_take_profit': True,
        'stop_loss_pct': 0.02,  # Stop loss al 2%
        'take_profit_pct': 0.03,  # Take profit al 3%
    }
    
    # Parámetros adicionales para la estrategia
    strategy_config = {
        'market': 'NASDAQ',
        'sleeptime': '30S',  # Revisar cada 30 segundos
        'stats_file': f'test_results_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv',
        'risk_free_rate': 0.04,
        'benchmark_asset': 'SPY',
    }
    
    print("📋 CONFIGURACIÓN DE PRUEBA:")
    print("-" * 40)
    print(f"Modo: {'PAPER TRADING' if mode == 'paper' else '⚠️ LIVE TRADING ⚠️'}")
    print(f"Símbolos: {', '.join(test_params['test_symbols'])}")
    print(f"Intervalo de órdenes: {test_params['order_interval_minutes']} minutos")
    print(f"Tamaño de orden: ${test_params['order_size_usd']}")
    print(f"Duración: {test_params['test_duration_hours']} horas")
    print(f"Stop Loss: {test_params['stop_loss_pct']*100:.1f}%")
    print(f"Take Profit: {test_params['take_profit_pct']*100:.1f}%")
    print("-" * 40 + "\n")
    
    if mode == 'live':
        print("⚠️" * 20)
        print("¡ADVERTENCIA! Está a punto de ejecutar en modo LIVE")
        print("Esto utilizará DINERO REAL")
        print("⚠️" * 20)
        response = input("\n¿Está seguro de que desea continuar? (escriba 'SI' para confirmar): ")
        if response != 'SI':
            print("Operación cancelada")
            return
    
    try:
        print("\n🏁 Iniciando estrategia de prueba...\n")
        
        # Ejecutar la estrategia
        if mode == 'paper':
            strategy = core.paper_trade('live_test', test_params, **strategy_config)
        else:
            strategy = core.live_trade('live_test', test_params, **strategy_config)
            
        print("\n✅ Estrategia iniciada exitosamente")
        print("La estrategia se ejecutará durante el tiempo configurado")
        print("Presione Ctrl+C para detener manualmente\n")
        
    except KeyboardInterrupt:
        print("\n\n🛑 Deteniendo estrategia...")
        core.stop()
        print("Estrategia detenida por el usuario")
        
    except Exception as e:
        print(f"\n❌ Error ejecutando la estrategia: {str(e)}")
        import traceback
        traceback.print_exc()
        

def run_quick_test():
    """
    Ejecuta una prueba rápida con parámetros mínimos
    """
    print("\n⚡ MODO DE PRUEBA RÁPIDA ⚡")
    print("Ejecutando prueba de 5 minutos con parámetros mínimos\n")
    
    # Configuración mínima para prueba rápida
    broker_config = {
        'API_KEY': os.getenv('ALPACA_API_KEY', 'your-api-key'),
        'API_SECRET': os.getenv('ALPACA_API_SECRET', 'your-api-secret'),
        'IS_PAPER': True,
    }
    
    if broker_config['API_KEY'] == 'your-api-key':
        print("Por favor configure las credenciales de Alpaca primero")
        return
    
    core = TradingCore(broker_config)
    core.register_strategy('live_test', LiveTestStrategy)
    
    quick_params = {
        'test_symbols': ['SPY'],  # Solo un símbolo
        'order_interval_minutes': 1,  # Orden cada minuto
        'order_size_usd': 50,  # $50 por orden
        'max_position_per_symbol': 200,  # Máximo $200
        'test_duration_hours': 0.083,  # 5 minutos
        'enable_stop_loss': False,
        'enable_take_profit': False,
    }
    
    try:
        strategy = core.paper_trade('live_test', quick_params, 
                                   market='NASDAQ', 
                                   sleeptime='10S')
        print("Prueba rápida completada")
        
    except KeyboardInterrupt:
        print("\nPrueba interrumpida")
        core.stop()
        

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Ejecutar estrategia de prueba live')
    parser.add_argument(
        '--mode', 
        choices=['paper', 'live', 'quick'],
        default='paper',
        help='Modo de ejecución: paper (default), live, o quick (prueba rápida)'
    )
    
    args = parser.parse_args()
    
    if args.mode == 'quick':
        run_quick_test()
    else:
        run_live_test(args.mode)