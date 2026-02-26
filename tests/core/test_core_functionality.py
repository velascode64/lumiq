"""
Tests funcionales para el TradingCore sin dependencias complejas
"""

import sys
import os

# Añadir el directorio padre al path para imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import Mock, patch
from datetime import datetime

from trading_core import TradingCore, TradingMode


class TestTradingCoreFunctionality:
    """Tests funcionales para TradingCore"""
    
    def test_trading_mode_enum(self):
        """Test de los valores del enum TradingMode"""
        assert TradingMode.BACKTEST.value == "backtest"
        assert TradingMode.PAPER.value == "paper" 
        assert TradingMode.LIVE.value == "live"
    
    def test_core_initialization_no_config(self):
        """Test de inicialización sin configuración"""
        core = TradingCore()
        
        assert core.broker_config == {}
        assert core._current_strategy is None
        assert core._current_mode is None
        assert core.factory is not None
    
    def test_core_initialization_with_config(self):
        """Test de inicialización con configuración"""
        config = {
            'API_KEY': 'test_key',
            'API_SECRET': 'test_secret',
            'IS_PAPER': True
        }
        
        core = TradingCore(config)
        
        assert core.broker_config == config
        assert core._current_strategy is None
        assert core._current_mode is None
    
    def test_default_dates_logic(self):
        """Test de la lógica de fechas por defecto"""
        core = TradingCore()
        
        start_date = core._get_default_start_date()
        end_date = core._get_default_end_date()
        
        # Verificar tipos
        assert isinstance(start_date, datetime)
        assert isinstance(end_date, datetime)
        
        # Verificar que start_date es antes que end_date
        assert start_date < end_date
        
        # Verificar que la diferencia es aproximadamente 6 meses
        diff = end_date - start_date
        assert 170 <= diff.days <= 190  # Aproximadamente 6 meses
    
    def test_get_current_strategy_none(self):
        """Test cuando no hay estrategia actual"""
        core = TradingCore()
        
        assert core.get_current_strategy() is None
    
    def test_get_current_mode_none(self):
        """Test cuando no hay modo actual"""
        core = TradingCore()
        
        assert core.get_current_mode() is None
    
    def test_broker_config_validation_paper(self):
        """Test de validación de configuración para paper trading"""
        core = TradingCore()  # Sin configuración
        
        try:
            # Esto debería fallar porque no hay configuración
            core._run_paper_trading('dummy', {})
            assert False, "Debería haber fallado sin configuración"
        except ValueError as e:
            assert "Broker configuration required" in str(e)
    
    def test_broker_config_validation_live(self):
        """Test de validación de configuración para live trading"""
        core = TradingCore()  # Sin configuración
        
        try:
            # Esto debería fallar porque no hay configuración
            core._run_live_trading('dummy', {})
            assert False, "Debería haber fallado sin configuración"
        except ValueError as e:
            assert "Broker configuration required" in str(e)
    
    def test_invalid_trading_mode(self):
        """Test con modo de trading inválido"""
        core = TradingCore({'API_KEY': 'test'})
        
        try:
            core.run('dummy', 'invalid_mode', {})
            assert False, "Debería haber fallado con modo inválido"
        except ValueError as e:
            assert "not a valid TradingMode" in str(e)
    
    def test_convenience_methods_exist(self):
        """Test que los métodos de conveniencia existen"""
        core = TradingCore()
        
        # Verificar que los métodos existen
        assert hasattr(core, 'backtest')
        assert hasattr(core, 'paper_trade')
        assert hasattr(core, 'live_trade')
        assert callable(core.backtest)
        assert callable(core.paper_trade)
        assert callable(core.live_trade)
    
    @patch.object(TradingCore, 'run')
    def test_convenience_methods_call_run(self, mock_run):
        """Test que los métodos de conveniencia llaman a run"""
        core = TradingCore()
        
        # Test backtest
        core.backtest('test_strategy', {'param': 'value'})
        mock_run.assert_called_with('test_strategy', 'backtest', {'param': 'value'})
        
        # Test paper_trade
        core.paper_trade('test_strategy', {'param': 'value'})
        mock_run.assert_called_with('test_strategy', 'paper', {'param': 'value'})
        
        # Test live_trade
        core.live_trade('test_strategy', {'param': 'value'})
        mock_run.assert_called_with('test_strategy', 'live', {'param': 'value'})
    
    def test_stop_method_no_strategy(self):
        """Test del método stop cuando no hay estrategia"""
        core = TradingCore()
        
        # No debería lanzar excepción
        core.stop()
        
        assert core._current_strategy is None
    
    def test_list_strategies_empty(self):
        """Test de listado de estrategias cuando no hay ninguna"""
        core = TradingCore()
        
        strategies = core.list_strategies()
        
        assert isinstance(strategies, dict)
        # Puede estar vacío o tener estrategias auto-descubiertas
    
    def test_timezone_handling(self):
        """Test del manejo de timezones en fechas por defecto"""
        core = TradingCore()
        
        start_date = core._get_default_start_date()
        end_date = core._get_default_end_date()
        
        # Verificar que tienen timezone
        assert start_date.tzinfo is not None
        assert end_date.tzinfo is not None
        
        # Verificar que es el timezone correcto (America/New_York)
        assert str(start_date.tzinfo).startswith('America/New_York') or 'EST' in str(start_date.tzinfo) or 'EDT' in str(start_date.tzinfo)
        assert str(end_date.tzinfo).startswith('America/New_York') or 'EST' in str(end_date.tzinfo) or 'EDT' in str(end_date.tzinfo)