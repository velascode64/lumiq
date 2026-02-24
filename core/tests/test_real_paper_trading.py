"""
Test de integración REAL con Alpaca Paper Trading
Requiere credenciales de Alpaca configuradas en variables de entorno

IMPORTANTE: Este test hace conexiones reales a Alpaca Paper Trading
"""

import sys
import os
import pytest
from datetime import datetime

# Añadir el directorio padre al path para imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trading_core import TradingCore
from strategies.live.live_test_strategy import LiveTestStrategy


class TestRealPaperTrading:
    """Tests de integración real con Alpaca Paper Trading"""
    
    @pytest.fixture
    def alpaca_credentials(self):
        """Fixture para credenciales de Alpaca"""
        api_key = os.getenv('ALPACA_API_KEY')
        api_secret = os.getenv('ALPACA_API_SECRET')
        
        if not api_key or not api_secret:
            pytest.skip("Credenciales de Alpaca no configuradas. Configure ALPACA_API_KEY y ALPACA_API_SECRET")
        
        return {
            'API_KEY': api_key,
            'API_SECRET': api_secret,
            'IS_PAPER': True,
        }
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_real_connection_to_alpaca(self, alpaca_credentials):
        """Test de conexión real a Alpaca Paper Trading"""
        from lumibot.brokers import Alpaca
        
        # Crear broker real
        broker = Alpaca(alpaca_credentials)
        
        # Verificar que podemos conectarnos
        assert broker is not None
        assert broker.IS_PAPER == True
        
        # Intentar obtener información de cuenta
        try:
            account_info = broker.get_portfolio_value()
            print(f"📊 Valor del portfolio: ${account_info:,.2f}")
            assert account_info >= 0
        except Exception as e:
            pytest.fail(f"Error conectando a Alpaca: {e}")
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_live_test_strategy_with_real_broker(self, alpaca_credentials):
        """Test de la estrategia con broker real (muy corto para no hacer trades reales)"""
        
        # Crear core con credenciales reales
        core = TradingCore(alpaca_credentials)
        core.register_strategy('live_test', LiveTestStrategy)
        
        # Parámetros muy conservadores para test
        params = {
            'test_symbols': ['SPY'],  # Solo un símbolo muy líquido
            'order_interval_minutes': 10,  # Intervalo muy largo
            'order_size_usd': 10,  # Monto muy pequeño
            'max_position_per_symbol': 20,  # Límite muy bajo
            'test_duration_hours': 0.01,  # Solo 36 segundos
            'enable_stop_loss': False,  # Sin stop loss para simplificar
            'enable_take_profit': False,
        }
        
        try:
            print(f"\n🧪 Iniciando test REAL de {params['test_duration_hours'] * 60:.1f} minutos")
            print("📈 Monitoreando trades en paper trading...")
            
            # Ejecutar en paper trading (muy corto)
            strategy = core.paper_trade('live_test', params, sleeptime='5S')
            
            print("✅ Test completado sin errores")
            
        except KeyboardInterrupt:
            print("\n⏹️  Test interrumpido por usuario")
        except Exception as e:
            print(f"\n❌ Error durante test real: {e}")
            raise
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_portfolio_and_positions_access(self, alpaca_credentials):
        """Test de acceso a portfolio y posiciones reales"""
        from lumibot.brokers import Alpaca
        
        broker = Alpaca(alpaca_credentials)
        
        try:
            # Obtener valor del portfolio
            portfolio_value = broker.get_portfolio_value()
            print(f"💰 Portfolio Value: ${portfolio_value:,.2f}")
            
            # Obtener cash disponible
            cash = broker.get_cash()
            print(f"💵 Cash Disponible: ${cash:,.2f}")
            
            # Obtener posiciones actuales
            positions = broker.get_positions()
            print(f"📊 Posiciones actuales: {len(positions)}")
            
            for pos in positions[:3]:  # Mostrar máximo 3 posiciones
                print(f"  - {pos.asset.symbol}: {pos.quantity} @ ${pos.avg_price:.2f}")
            
            # Obtener órdenes pendientes
            orders = broker.get_orders()
            print(f"📋 Órdenes pendientes: {len(orders)}")
            
            # Verificaciones básicas
            assert portfolio_value >= 0
            assert cash >= 0
            assert isinstance(positions, list)
            assert isinstance(orders, list)
            
        except Exception as e:
            pytest.fail(f"Error accediendo a datos del broker: {e}")
    
    @pytest.mark.integration
    def test_market_data_access(self, alpaca_credentials):
        """Test de acceso a datos de mercado"""
        from lumibot.brokers import Alpaca
        from lumibot.entities import Asset
        
        broker = Alpaca(alpaca_credentials)
        
        try:
            # Test con SPY (muy líquido)
            spy = Asset(symbol='SPY')
            price = broker.get_last_price(spy)
            
            print(f"📈 Precio actual de SPY: ${price:.2f}")
            
            assert price > 0
            assert isinstance(price, (int, float))
            
        except Exception as e:
            pytest.fail(f"Error obteniendo datos de mercado: {e}")


if __name__ == "__main__":
    """Ejecutar solo este test manualmente"""
    print("🚀 Ejecutando test de integración real con Alpaca...")
    print("⚠️  Requiere credenciales configuradas en variables de entorno")
    print()
    
    # Verificar credenciales
    if not os.getenv('ALPACA_API_KEY') or not os.getenv('ALPACA_API_SECRET'):
        print("❌ Credenciales no configuradas. Configure:")
        print("   export ALPACA_API_KEY='tu-api-key'")
        print("   export ALPACA_API_SECRET='tu-api-secret'")
        exit(1)
    
    # Ejecutar tests
    pytest.main([__file__, "-v", "-s"])