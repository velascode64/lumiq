"""
Tests de integración para TradingCore con LiveTestStrategy
"""

import sys
import os
import pytest

# Añadir el directorio padre al path para imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import Mock, patch
from datetime import datetime

from trading_core import TradingCore, TradingMode
from strategies.live.live_test_strategy import LiveTestStrategy
from lumibot.strategies import Strategy
from lumibot.brokers import Alpaca


class TestTradingCoreIntegration:
    """Tests de integración para TradingCore"""
    
    def test_core_initialization(self, mock_trading_core_config):
        """Test de inicialización del core"""
        core = TradingCore(mock_trading_core_config)
        
        assert core.broker_config == mock_trading_core_config
        assert core._current_strategy is None
        assert core._current_mode is None
        assert core.factory is not None
    
    def test_register_strategy(self, mock_trading_core_config):
        """Test de registro de estrategia"""
        core = TradingCore(mock_trading_core_config)
        
        # Registrar estrategia de prueba
        core.register_strategy('test_live', LiveTestStrategy)
        
        # Verificar que se registró correctamente
        strategies = core.list_strategies()
        assert 'test_live' in strategies
        assert strategies['test_live']['class'] == 'LiveTestStrategy'
    
    def test_list_strategies(self, mock_trading_core_config):
        """Test de listado de estrategias"""
        core = TradingCore(mock_trading_core_config)
        core.register_strategy('test_strategy', LiveTestStrategy)
        
        strategies = core.list_strategies()
        
        assert isinstance(strategies, dict)
        assert 'test_strategy' in strategies
        assert 'class' in strategies['test_strategy']
        assert 'module' in strategies['test_strategy']
        assert 'parameters' in strategies['test_strategy']
        assert 'description' in strategies['test_strategy']
    
    @patch('trading_core.AlpacaBacktesting')
    @patch.object(LiveTestStrategy, 'run_backtest')
    def test_run_backtest_mode(self, mock_run_backtest, mock_alpaca_backtesting, 
                               mock_trading_core_config, test_strategy_params):
        """Test de ejecución en modo backtest"""
        # Configurar mocks
        mock_strategy_instance = Mock(spec=Strategy)
        mock_results = {'total_return': 0.15, 'sharpe_ratio': 1.2}
        mock_run_backtest.return_value = (mock_results, mock_strategy_instance)
        
        core = TradingCore(mock_trading_core_config)
        core.register_strategy('test_live', LiveTestStrategy)
        
        # Ejecutar backtest
        results = core.run('test_live', 'backtest', test_strategy_params)
        
        # Verificaciones
        assert results == mock_results
        assert core._current_mode == TradingMode.BACKTEST
        assert core._current_strategy == mock_strategy_instance
        mock_run_backtest.assert_called_once()
    
    @patch('trading_core.Alpaca')
    def test_run_paper_mode(self, mock_alpaca_broker, mock_trading_core_config, 
                           test_strategy_params):
        """Test de ejecución en modo paper trading"""
        # Configurar mock del broker
        mock_broker_instance = Mock(spec=Alpaca)
        mock_alpaca_broker.return_value = mock_broker_instance
        
        core = TradingCore(mock_trading_core_config)
        core.register_strategy('test_live', LiveTestStrategy)
        
        # Mock de create_strategy para evitar ejecución real
        with patch.object(core.factory, 'create_strategy') as mock_create:
            mock_strategy = Mock(spec=LiveTestStrategy)
            mock_create.return_value = mock_strategy
            
            # Ejecutar paper trading
            strategy = core.run('test_live', 'paper', test_strategy_params)
            
            # Verificaciones
            assert strategy == mock_strategy
            assert core._current_mode == TradingMode.PAPER
            assert core._current_strategy == mock_strategy
            
            # Verificar que se creó el broker con IS_PAPER=True
            expected_config = {**mock_trading_core_config, 'IS_PAPER': True}
            mock_alpaca_broker.assert_called_once_with(expected_config)
            
            # Verificar que se llamó run_live
            mock_strategy.run_live.assert_called_once()
    
    @patch('trading_core.Alpaca')
    def test_run_live_mode(self, mock_alpaca_broker, mock_trading_core_config, 
                           test_strategy_params):
        """Test de ejecución en modo live trading"""
        # Configurar mock del broker
        mock_broker_instance = Mock(spec=Alpaca)
        mock_alpaca_broker.return_value = mock_broker_instance
        
        core = TradingCore(mock_trading_core_config)
        core.register_strategy('test_live', LiveTestStrategy)
        
        # Mock de create_strategy para evitar ejecución real
        with patch.object(core.factory, 'create_strategy') as mock_create:
            mock_strategy = Mock(spec=LiveTestStrategy)
            mock_create.return_value = mock_strategy
            
            # Ejecutar live trading
            strategy = core.run('test_live', 'live', test_strategy_params)
            
            # Verificaciones
            assert strategy == mock_strategy
            assert core._current_mode == TradingMode.LIVE
            assert core._current_strategy == mock_strategy
            
            # Verificar que se creó el broker con IS_PAPER=False
            expected_config = {**mock_trading_core_config, 'IS_PAPER': False}
            mock_alpaca_broker.assert_called_once_with(expected_config)
            
            # Verificar que se llamó run_live
            mock_strategy.run_live.assert_called_once()
    
    def test_run_without_broker_config_paper(self):
        """Test que falla al ejecutar paper trading sin configuración de broker"""
        core = TradingCore()  # Sin configuración de broker
        core.register_strategy('test_live', LiveTestStrategy)
        
        with pytest.raises(ValueError, match="Broker configuration required for paper trading"):
            core.run('test_live', 'paper', {})
    
    def test_run_without_broker_config_live(self):
        """Test que falla al ejecutar live trading sin configuración de broker"""
        core = TradingCore()  # Sin configuración de broker
        core.register_strategy('test_live', LiveTestStrategy)
        
        with pytest.raises(ValueError, match="Broker configuration required for live trading"):
            core.run('test_live', 'live', {})
    
    def test_run_invalid_mode(self, mock_trading_core_config):
        """Test con modo de trading inválido"""
        core = TradingCore(mock_trading_core_config)
        core.register_strategy('test_live', LiveTestStrategy)
        
        with pytest.raises(ValueError, match="Unsupported trading mode"):
            core.run('test_live', 'invalid_mode', {})
    
    def test_convenience_methods(self, mock_trading_core_config):
        """Test de métodos de conveniencia"""
        core = TradingCore(mock_trading_core_config)
        core.register_strategy('test_live', LiveTestStrategy)
        
        # Mock del método run principal
        with patch.object(core, 'run') as mock_run:
            # Test backtest
            core.backtest('test_live', {'param': 'value'})
            mock_run.assert_called_with('test_live', 'backtest', {'param': 'value'})
            
            # Test paper_trade
            core.paper_trade('test_live', {'param': 'value'})
            mock_run.assert_called_with('test_live', 'paper', {'param': 'value'})
            
            # Test live_trade
            core.live_trade('test_live', {'param': 'value'})
            mock_run.assert_called_with('test_live', 'live', {'param': 'value'})
    
    def test_get_current_strategy(self, mock_trading_core_config):
        """Test de obtener estrategia actual"""
        core = TradingCore(mock_trading_core_config)
        
        assert core.get_current_strategy() is None
        
        # Simular una estrategia en ejecución
        mock_strategy = Mock(spec=Strategy)
        core._current_strategy = mock_strategy
        
        assert core.get_current_strategy() == mock_strategy
    
    def test_get_current_mode(self, mock_trading_core_config):
        """Test de obtener modo actual"""
        core = TradingCore(mock_trading_core_config)
        
        assert core.get_current_mode() is None
        
        # Simular modo activo
        core._current_mode = TradingMode.PAPER
        
        assert core.get_current_mode() == TradingMode.PAPER
    
    def test_stop_strategy(self, mock_trading_core_config):
        """Test de detener estrategia"""
        core = TradingCore(mock_trading_core_config)
        
        # Simular estrategia en ejecución
        mock_strategy = Mock(spec=Strategy)
        core._current_strategy = mock_strategy
        
        # Ejecutar stop
        core.stop()
        
        # Por ahora solo verifica que no lanza excepción
        # En implementación real debería llamar strategy.stop() si existe
    
    def test_default_dates(self, mock_trading_core_config):
        """Test de fechas por defecto para backtest"""
        core = TradingCore(mock_trading_core_config)
        
        # Obtener fechas por defecto
        start_date = core._get_default_start_date()
        end_date = core._get_default_end_date()
        
        # Verificar tipos
        assert isinstance(start_date, datetime)
        assert isinstance(end_date, datetime)
        
        # Verificar timezone
        assert start_date.tzinfo is not None
        assert end_date.tzinfo is not None
        
        # Verificar que start_date es antes que end_date
        assert start_date < end_date
        
        # Verificar que la diferencia es aproximadamente 6 meses
        diff = end_date - start_date
        assert 170 <= diff.days <= 190  # Aproximadamente 6 meses


class TestEndToEndIntegration:
    """Tests de integración end-to-end"""
    
    @patch('trading_core.Alpaca')
    @patch.object(LiveTestStrategy, 'run_live')
    def test_complete_paper_trading_flow(self, mock_run_live, mock_alpaca_broker, 
                                        mock_trading_core_config):
        """Test del flujo completo de paper trading"""
        # Configurar mocks
        mock_broker_instance = Mock(spec=Alpaca)
        mock_alpaca_broker.return_value = mock_broker_instance
        
        # Crear core y registrar estrategia
        core = TradingCore(mock_trading_core_config)
        core.register_strategy('live_test', LiveTestStrategy)
        
        # Parámetros de prueba
        params = {
            'test_symbols': ['SPY'],
            'order_interval_minutes': 1,
            'order_size_usd': 50,
            'max_position_per_symbol': 200,
            'test_duration_hours': 0.05,  # 3 minutos
            'enable_stop_loss': False,
            'enable_take_profit': False,
        }
        
        # Ejecutar paper trading
        strategy = core.paper_trade('live_test', params)
        
        # Verificaciones
        assert isinstance(strategy, LiveTestStrategy)
        assert core._current_mode == TradingMode.PAPER
        mock_run_live.assert_called_once()
    
    @patch.object(LiveTestStrategy, 'run_backtest')
    def test_complete_backtest_flow(self, mock_run_backtest, mock_trading_core_config):
        """Test del flujo completo de backtesting"""
        # Configurar mock de backtest
        mock_results = {
            'total_return': 0.25,
            'sharpe_ratio': 1.5,
            'max_drawdown': -0.10,
            'total_trades': 50,
        }
        mock_strategy = Mock(spec=LiveTestStrategy)
        mock_run_backtest.return_value = (mock_results, mock_strategy)
        
        # Crear core y registrar estrategia
        core = TradingCore(mock_trading_core_config)
        core.register_strategy('live_test', LiveTestStrategy)
        
        # Parámetros de backtest
        params = {
            'test_symbols': ['SPY', 'QQQ'],
            'order_interval_minutes': 5,
            'order_size_usd': 100,
            'max_position_per_symbol': 1000,
            'test_duration_hours': 1,
        }
        
        # Ejecutar backtest
        results = core.backtest('live_test', params)
        
        # Verificaciones
        assert results == mock_results
        assert core._current_mode == TradingMode.BACKTEST
        assert core._current_strategy == mock_strategy
        mock_run_backtest.assert_called_once()
    
    def test_strategy_validation(self, mock_trading_core_config):
        """Test de validación de configuración de estrategia"""
        core = TradingCore(mock_trading_core_config)
        core.register_strategy('live_test', LiveTestStrategy)
        
        # Parámetros válidos
        valid_params = {
            'test_symbols': ['SPY'],
            'order_interval_minutes': 5,
        }
        
        # Debería ejecutar sin errores con parámetros válidos
        with patch.object(core.factory, 'validate_strategy_config') as mock_validate:
            with patch.object(core, '_run_paper_trading') as mock_run:
                mock_run.return_value = Mock(spec=Strategy)
                core.run('live_test', 'paper', valid_params)
                mock_validate.assert_called_once_with('live_test', valid_params)