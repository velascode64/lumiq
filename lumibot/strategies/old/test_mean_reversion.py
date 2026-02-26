#!/usr/bin/env python3
"""
Test rápido para verificar que la estrategia Mean Reversion funciona correctamente
"""

import sys
import os

# Agregar path para imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.mean_reversion_runner import MeanReversionRunner
from loguru import logger
import traceback

def test_strategy_creation():
    """Test básico de creación de estrategia"""
    try:
        print("🧪 Test 1: Creación de MeanReversionRunner...")
        runner = MeanReversionRunner()
        print("✅ MeanReversionRunner creado exitosamente")
        return True
    except Exception as e:
        print(f"❌ Error creando runner: {e}")
        return False

def test_cerebro_setup():
    """Test de configuración del cerebro"""
    try:
        print("\n🧪 Test 2: Configuración del cerebro...")
        runner = MeanReversionRunner()
        runner.setup_cerebro(
            initial_cash=50000,
            daily_gain_threshold=0.05,
            pullback_pct=0.02,
            static_days=3,
            static_sd=0.01,
            trailing_stop_pct=0.02
        )
        print("✅ Cerebro configurado exitosamente")
        print(f"   Parámetros: {runner.strategy_params}")
        return True
    except Exception as e:
        print(f"❌ Error configurando cerebro: {e}")
        traceback.print_exc()
        return False

def test_data_download():
    """Test de descarga de datos"""
    try:
        print("\n🧪 Test 3: Descarga de datos...")
        runner = MeanReversionRunner()
        runner.setup_cerebro(initial_cash=50000)
        
        # Intentar con un ticker simple y período corto
        runner.add_data_feeds(tickers=['AAPL'], period='6mo')
        print("✅ Datos descargados exitosamente")
        return True
    except Exception as e:
        print(f"❌ Error descargando datos: {e}")
        traceback.print_exc()
        return False

def test_mini_backtest():
    """Test de backtest mínimo"""
    try:
        print("\n🧪 Test 4: Mini backtest...")
        runner = MeanReversionRunner()
        
        # Configuración mínima
        runner.setup_cerebro(
            initial_cash=10000,
            commission=0.001,
            daily_gain_threshold=0.05,
            pullback_pct=0.02,
            static_days=3,
            static_sd=0.01,
            trailing_stop_pct=0.02
        )
        
        # Un solo ticker, período corto
        runner.add_data_feeds(tickers=['AAPL'], period='3mo')
        
        # Ejecutar backtest
        print("   Ejecutando backtest...")
        strategy = runner.run_backtest()
        print("✅ Mini backtest ejecutado exitosamente")
        return True
    except Exception as e:
        print(f"❌ Error en mini backtest: {e}")
        traceback.print_exc()
        return False

def test_imports():
    """Test de imports necesarios"""
    try:
        print("🧪 Test 0: Verificando imports...")
        
        import backtrader as bt
        print("   ✅ backtrader OK")
        
        import yfinance as yf
        print("   ✅ yfinance OK")
        
        import numpy as np
        print("   ✅ numpy OK")
        
        import pandas as pd
        print("   ✅ pandas OK")
        
        from loguru import logger
        print("   ✅ loguru OK")
        
        try:
            import alpaca_trade_api as tradeapi
            print("   ✅ alpaca-trade-api OK")
        except ImportError:
            print("   ⚠️  alpaca-trade-api no disponible (opcional para paper trading)")
        
        # Test import de nuestra estrategia
        from strategies.mean_reversion_momentum_strategy import MeanReversionMomentumStrategy
        print("   ✅ MeanReversionMomentumStrategy OK")
        
        print("✅ Todos los imports necesarios disponibles")
        return True
    except Exception as e:
        print(f"❌ Error en imports: {e}")
        return False

def main():
    """Ejecuta todos los tests"""
    
    # Configurar logging simple para tests
    logger.remove()
    logger.add(sys.stdout, 
               format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
               level="WARNING")  # Solo warnings y errores para tests
    
    print("🚀 TESTS MEAN REVERSION MOMENTUM STRATEGY")
    print("=" * 50)
    
    tests = [
        test_imports,
        test_strategy_creation,
        test_cerebro_setup,
        test_data_download,
        test_mini_backtest
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                print("   ⚠️  Test falló")
        except Exception as e:
            print(f"   💥 Test crashed: {e}")
        
        print()  # Línea en blanco
    
    # Resumen
    print("=" * 50)
    print(f"📊 RESUMEN: {passed}/{total} tests pasaron")
    
    if passed == total:
        print("🎉 ¡Todos los tests pasaron! La estrategia está lista para usar.")
        print("\n💡 Próximos pasos:")
        print("   1. Ejecutar: python strategies/example_mean_reversion.py")
        print("   2. Probar: python strategies/mean_reversion_runner.py --mode backtest")
        print("   3. Leer documentación: strategies/README_MEAN_REVERSION.md")
        return True
    else:
        print("❌ Algunos tests fallaron. Revisar errores arriba.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 