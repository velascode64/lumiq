#!/usr/bin/env python3
"""
Ejemplo simple de uso de la estrategia Mean Reversion Momentum
Demuestra cómo ejecutar backtests rápidos con diferentes configuraciones
"""

import sys
import os

# Agregar path para imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.mean_reversion_runner import MeanReversionRunner
from loguru import logger

def example_basic_backtest():
    """Ejemplo básico de backtest con configuración por defecto"""
    
    print("\n🎯 EJEMPLO 1: Backtest Básico (TSLA, GOOGL, QQQ - 2 años)")
    print("=" * 60)
    
    runner = MeanReversionRunner()
    
    # Configuración básica
    runner.setup_cerebro(
        initial_cash=100000,
        commission=0.001,
        # Parámetros por defecto
        daily_gain_threshold=0.05,   # 5%
        pullback_pct=0.02,          # 2%
        static_days=3,              # 3 días
        static_sd=0.01,             # 1%
        trailing_stop_pct=0.02      # 2%
    )
    
    # Agregar datos
    runner.add_data_feeds(
        tickers=['TSLA', 'GOOGL', 'QQQ'], 
        period='2y'
    )
    
    # Ejecutar
    strategy = runner.run_backtest()
    
    return strategy

def example_aggressive_params():
    """Ejemplo con parámetros más agresivos"""
    
    print("\n🔥 EJEMPLO 2: Configuración Agresiva (Solo TSLA - 1 año)")
    print("=" * 60)
    
    runner = MeanReversionRunner()
    
    # Configuración agresiva
    runner.setup_cerebro(
        initial_cash=50000,
        commission=0.001,
        # Parámetros más agresivos
        daily_gain_threshold=0.03,   # 3% (más sensible)
        pullback_pct=0.015,         # 1.5% (stop más ajustado)
        static_days=2,              # 2 días (re-entrada más rápida)
        static_sd=0.008,            # 0.8% (precio estático más estricto)
        trailing_stop_pct=0.025     # 2.5% (trailing stop más amplio)
    )
    
    # Solo TSLA para mayor concentración
    runner.add_data_feeds(
        tickers=['TSLA'], 
        period='1y'
    )
    
    # Ejecutar
    strategy = runner.run_backtest()
    
    return strategy

def example_conservative_params():
    """Ejemplo con parámetros conservadores"""
    
    print("\n🛡️ EJEMPLO 3: Configuración Conservadora (ETFs - 3 años)")
    print("=" * 60)
    
    runner = MeanReversionRunner()
    
    # Configuración conservadora
    runner.setup_cerebro(
        initial_cash=200000,
        commission=0.001,
        # Parámetros conservadores
        daily_gain_threshold=0.08,   # 8% (menos sensible)
        pullback_pct=0.03,          # 3% (stop más amplio)
        static_days=5,              # 5 días (esperar más para re-entrar)
        static_sd=0.015,            # 1.5% (precio estático más permisivo)
        trailing_stop_pct=0.015     # 1.5% (trailing stop más ajustado)
    )
    
    # ETFs más estables
    runner.add_data_feeds(
        tickers=['QQQ', 'SPY', 'IWM'], 
        period='3y'
    )
    
    # Ejecutar
    strategy = runner.run_backtest()
    
    return strategy

def compare_strategies():
    """Compara diferentes configuraciones"""
    
    print("\n📊 COMPARACIÓN DE ESTRATEGIAS")
    print("=" * 60)
    
    configs = [
        {
            'name': 'Básica',
            'params': {
                'daily_gain_threshold': 0.05,
                'pullback_pct': 0.02,
                'static_days': 3,
                'static_sd': 0.01,
                'trailing_stop_pct': 0.02
            }
        },
        {
            'name': 'Agresiva',
            'params': {
                'daily_gain_threshold': 0.03,
                'pullback_pct': 0.015,
                'static_days': 2,
                'static_sd': 0.008,
                'trailing_stop_pct': 0.025
            }
        },
        {
            'name': 'Conservadora',
            'params': {
                'daily_gain_threshold': 0.08,
                'pullback_pct': 0.03,
                'static_days': 5,
                'static_sd': 0.015,
                'trailing_stop_pct': 0.015
            }
        }
    ]
    
    results = []
    
    for config in configs:
        print(f"\n🔄 Probando configuración: {config['name']}")
        
        runner = MeanReversionRunner()
        runner.setup_cerebro(
            initial_cash=100000,
            commission=0.001,
            **config['params']
        )
        
        runner.add_data_feeds(
            tickers=['TSLA', 'GOOGL'], 
            period='1y'
        )
        
        strategy = runner.run_backtest()
        
        # Guardar resultados para comparación
        final_value = runner.cerebro.broker.getvalue()
        total_return = ((final_value - 100000) / 100000) * 100
        
        results.append({
            'config': config['name'],
            'return': total_return,
            'final_value': final_value
        })
    
    # Mostrar resumen comparativo
    print("\n📈 RESUMEN COMPARATIVO")
    print("=" * 40)
    for result in results:
        print(f"{result['config']:12}: {result['return']:+6.2f}% (${result['final_value']:,.0f})")

def main():
    """Función principal - ejecuta todos los ejemplos"""
    
    # Configurar logging simple
    logger.remove()
    logger.add(sys.stdout, 
               format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
               level="INFO")
    
    print("🚀 EJEMPLOS DE USO - MEAN REVERSION MOMENTUM STRATEGY")
    print("=" * 70)
    
    try:
        # Ejecutar ejemplos
        example_basic_backtest()
        example_aggressive_params()
        example_conservative_params()
        
        # Comparación final
        compare_strategies()
        
        print("\n✅ Todos los ejemplos ejecutados exitosamente!")
        print("\n💡 TIPS:")
        print("  • Usa parámetros agresivos para mayor actividad de trading")
        print("  • Usa parámetros conservadores para menor riesgo")
        print("  • Ajusta 'static_days' y 'static_sd' para controlar re-entradas")
        print("  • El trailing_stop_pct es clave para proteger ganancias")
        
    except Exception as e:
        logger.error(f"Error ejecutando ejemplos: {e}")
        return False
        
    return True

if __name__ == "__main__":
    main() 