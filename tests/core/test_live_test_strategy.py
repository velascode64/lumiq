"""
Tests para LiveTestStrategy usando pytest
"""

import sys
import os
import pytest

# Añadir el directorio padre al path para imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import Mock, patch
from datetime import datetime, timedelta

from strategies.live.live_test_strategy import LiveTestStrategy
from lumibot.entities import Asset


class TestLiveTestStrategy:
    """Tests para la clase LiveTestStrategy"""
    
    def test_initialization(self, mock_broker, test_strategy_params):
        """Test de inicialización de la estrategia"""
        strategy = LiveTestStrategy(broker=mock_broker, parameters=test_strategy_params)
        
        # Mock de métodos necesarios para initialize
        strategy.log_message = Mock()
        
        strategy.initialize()
        
        # Verificar que se inicializaron los parámetros correctamente
        assert strategy.test_symbols == ['SPY', 'QQQ']
        assert strategy.order_interval_minutes == 1
        assert strategy.order_size_usd == 100
        assert strategy.max_position_per_symbol == 500
        assert strategy.test_duration_hours == 0.1
        assert strategy.enable_stop_loss == True
        assert strategy.enable_take_profit == True
        assert strategy.stop_loss_pct == 0.02
        assert strategy.take_profit_pct == 0.03
        
        # Verificar estado interno
        assert strategy.order_count == 0
        assert strategy.successful_orders == 0
        assert strategy.failed_orders == 0
        assert strategy.total_value_traded == 0
        assert strategy.test_phase == 'BUY'
        
        # Verificar que se llamó log_message
        assert strategy.log_message.called
    
    def test_check_test_duration(self, mock_broker, test_strategy_params):
        """Test de verificación de duración de prueba"""
        strategy = LiveTestStrategy(broker=mock_broker, parameters=test_strategy_params)
        strategy.initialize()
        
        # Al inicio, no debe haber excedido el tiempo
        assert strategy._check_test_duration() == False
        
        # Simular que ha pasado el tiempo de prueba
        strategy.start_time = datetime.now() - timedelta(hours=0.2)
        assert strategy._check_test_duration() == True
    
    def test_format_timedelta(self, mock_broker, test_strategy_params):
        """Test del formateo de timedelta"""
        strategy = LiveTestStrategy(broker=mock_broker, parameters=test_strategy_params)
        
        # Test varios casos
        td1 = timedelta(hours=2, minutes=30, seconds=45)
        assert strategy._format_timedelta(td1) == "02:30:45"
        
        td2 = timedelta(minutes=5, seconds=10)
        assert strategy._format_timedelta(td2) == "00:05:10"
        
        td3 = timedelta(hours=10, minutes=0, seconds=0)
        assert strategy._format_timedelta(td3) == "10:00:00"
    
    def test_get_target_weight(self, mock_broker):
        """Test para obtener el peso objetivo de un símbolo"""
        params = {
            'portfolio_weights': [
                {'base_asset': Asset(symbol='BTC'), 'weight': 0.5},
                {'base_asset': Asset(symbol='ETH'), 'weight': 0.5},
            ]
        }
        strategy = LiveTestStrategy(broker=mock_broker, parameters=params)
        
        assert strategy._get_target_weight('BTC') == 50.0
        assert strategy._get_target_weight('ETH') == 50.0
        assert strategy._get_target_weight('SPY') == 0
    
    @patch('strategies.live.live_test_strategy.datetime')
    def test_create_buy_order(self, mock_datetime, mock_broker, test_strategy_params):
        """Test de creación de orden de compra"""
        mock_datetime.now.return_value = datetime(2024, 1, 15, 10, 0, 0)
        
        strategy = LiveTestStrategy(broker=mock_broker, parameters=test_strategy_params)
        strategy.initialize()
        
        # Mocks necesarios
        strategy.log_message = Mock()
        strategy.create_order = Mock(return_value=Mock(id='order_123'))
        strategy._create_bracket_orders = Mock()
        
        asset = Asset(symbol='SPY')
        current_price = 450.0
        
        # Ejecutar creación de orden de compra
        strategy._create_buy_order(asset, current_price)
        
        # Verificar que se creó la orden correctamente
        expected_quantity = 100 / 450.0  # order_size_usd / current_price
        strategy.create_order.assert_called_once_with(
            asset,
            expected_quantity,
            "buy",
            type="market"
        )
        
        # Verificar actualizaciones de estado
        assert strategy.order_count == 1
        assert strategy.successful_orders == 1
        assert strategy.total_value_traded == 100
        
        # Verificar que se crearon órdenes bracket
        strategy._create_bracket_orders.assert_called_once_with(
            asset, expected_quantity, current_price
        )
    
    @patch('strategies.live.live_test_strategy.datetime')
    def test_create_sell_order(self, mock_datetime, mock_broker, test_strategy_params):
        """Test de creación de orden de venta"""
        mock_datetime.now.return_value = datetime(2024, 1, 15, 10, 0, 0)
        
        strategy = LiveTestStrategy(broker=mock_broker, parameters=test_strategy_params)
        strategy.initialize()
        
        # Mocks necesarios
        strategy.log_message = Mock()
        strategy.create_order = Mock(return_value=Mock(id='order_456'))
        
        asset = Asset(symbol='SPY')
        position = Mock(quantity=10.0)
        current_price = 450.0
        
        # Ejecutar creación de orden de venta
        strategy._create_sell_order(asset, position, current_price)
        
        # Verificar que se creó la orden correctamente
        expected_quantity = min(10.0 * 0.5, 100 / 450.0)
        strategy.create_order.assert_called_once_with(
            asset,
            expected_quantity,
            "sell",
            type="market"
        )
        
        # Verificar actualizaciones de estado
        assert strategy.order_count == 1
        assert strategy.successful_orders == 1
        assert strategy.total_value_traded == expected_quantity * current_price
    
    def test_process_symbol_buy_phase(self, mock_broker, test_strategy_params):
        """Test del procesamiento de símbolo en fase de compra"""
        strategy = LiveTestStrategy(broker=mock_broker, parameters=test_strategy_params)
        strategy.initialize()
        
        # Configurar mocks
        strategy.get_last_price = Mock(return_value=450.0)
        strategy.get_position = Mock(return_value=None)
        strategy._create_buy_order = Mock()
        
        current_time = datetime.now()
        strategy.last_order_time['SPY'] = current_time - timedelta(minutes=2)
        
        # Ejecutar procesamiento
        strategy._process_symbol('SPY', current_time)
        
        # Verificar que se intentó crear orden de compra
        strategy._create_buy_order.assert_called_once()
        assert strategy.test_phase == 'SELL'
        assert strategy.last_order_time['SPY'] == current_time
    
    def test_process_symbol_sell_phase(self, mock_broker, test_strategy_params, mock_position):
        """Test del procesamiento de símbolo en fase de venta"""
        strategy = LiveTestStrategy(broker=mock_broker, parameters=test_strategy_params)
        strategy.initialize()
        strategy.test_phase = 'SELL'
        
        # Configurar mocks
        strategy.get_last_price = Mock(return_value=450.0)
        strategy.get_position = Mock(return_value=mock_position)
        strategy._create_sell_order = Mock()
        
        current_time = datetime.now()
        strategy.last_order_time['SPY'] = current_time - timedelta(minutes=2)
        
        # Ejecutar procesamiento
        strategy._process_symbol('SPY', current_time)
        
        # Verificar que se intentó crear orden de venta
        strategy._create_sell_order.assert_called_once()
        assert strategy.test_phase == 'BUY'
        assert strategy.last_order_time['SPY'] == current_time
    
    def test_manage_existing_orders(self, mock_broker, test_strategy_params, mock_order):
        """Test de gestión de órdenes existentes"""
        strategy = LiveTestStrategy(broker=mock_broker, parameters=test_strategy_params)
        strategy.initialize()
        
        # Mock de log_message
        strategy.log_message = Mock()
        
        # Mock de get_orders
        strategy.get_orders = Mock(return_value=[mock_order])
        
        # Ejecutar gestión de órdenes
        strategy._manage_existing_orders()
        
        # Verificar que se llamó get_orders y se logeó correctamente
        strategy.get_orders.assert_called_once()
        assert strategy.log_message.call_count >= 2  # Al menos el título y una orden
    
    def test_close_all_positions(self, mock_broker, test_strategy_params, mock_position):
        """Test de cierre de todas las posiciones"""
        strategy = LiveTestStrategy(broker=mock_broker, parameters=test_strategy_params)
        strategy.initialize()
        
        # Mocks necesarios
        strategy.log_message = Mock()
        strategy.get_positions = Mock(return_value=[mock_position])
        strategy.create_order = Mock()
        
        # Ejecutar cierre de posiciones
        strategy._close_all_positions()
        
        # Verificar que se intentó cerrar la posición
        strategy.create_order.assert_called_once_with(
            mock_position.asset,
            mock_position.quantity,
            "sell",
            type="market"
        )
    
    def test_on_filled_order_callback(self, mock_broker, test_strategy_params, mock_order, mock_position):
        """Test del callback cuando se completa una orden"""
        strategy = LiveTestStrategy(broker=mock_broker, parameters=test_strategy_params)
        strategy.initialize()
        strategy.log_message = Mock()
        
        # Ejecutar callback
        strategy.on_filled_order(
            position=mock_position,
            order=mock_order,
            price=450.0,
            quantity=10.0,
            multiplier=1
        )
        
        # Verificar que se logeó la información
        assert strategy.log_message.called
        calls = strategy.log_message.call_args_list
        assert any("ORDEN COMPLETADA" in str(call) for call in calls)
    
    def test_on_aborted_order_callback(self, mock_broker, test_strategy_params, mock_order):
        """Test del callback cuando se aborta una orden"""
        strategy = LiveTestStrategy(broker=mock_broker, parameters=test_strategy_params)
        strategy.initialize()
        strategy.log_message = Mock()
        
        # Ejecutar callback
        strategy.on_aborted_order(mock_order)
        
        # Verificar que se logeó la información
        assert strategy.log_message.called
        calls = strategy.log_message.call_args_list
        assert any("ORDEN ABORTADA" in str(call) for call in calls)
    
    def test_on_canceled_order_callback(self, mock_broker, test_strategy_params, mock_order):
        """Test del callback cuando se cancela una orden"""
        strategy = LiveTestStrategy(broker=mock_broker, parameters=test_strategy_params)
        strategy.initialize()
        strategy.log_message = Mock()
        
        # Ejecutar callback
        strategy.on_canceled_order(mock_order)
        
        # Verificar que se logeó la información
        assert strategy.log_message.called
        calls = strategy.log_message.call_args_list
        assert any("ORDEN CANCELADA" in str(call) for call in calls)
    
    @patch('strategies.live.live_test_strategy.datetime')
    def test_on_trading_iteration_full(self, mock_datetime, mock_broker, test_strategy_params):
        """Test completo de una iteración de trading"""
        mock_datetime.now.return_value = datetime(2024, 1, 15, 10, 0, 0)
        
        strategy = LiveTestStrategy(broker=mock_broker, parameters=test_strategy_params)
        strategy.initialize()
        
        # Configurar todos los mocks necesarios
        strategy.portfolio_value = 10000.0
        strategy.cash = 5000.0
        strategy.log_message = Mock()
        strategy._check_test_duration = Mock(return_value=False)
        strategy._log_iteration_status = Mock()
        strategy._process_symbol = Mock()
        strategy._manage_existing_orders = Mock()
        strategy.get_positions = Mock(return_value=[])
        
        # Ejecutar iteración
        strategy.on_trading_iteration()
        
        # Verificar que se ejecutaron todos los pasos
        strategy._check_test_duration.assert_called_once()
        strategy._log_iteration_status.assert_called_once()
        assert strategy._process_symbol.call_count == len(strategy.test_symbols)
        strategy._manage_existing_orders.assert_called_once()
        
        # Verificar que se guardó el valor inicial del portfolio
        assert strategy.initial_portfolio_value == 10000.0
    
    @patch('strategies.live.live_test_strategy.datetime')
    def test_finalize_test(self, mock_datetime, mock_broker, test_strategy_params):
        """Test de finalización de la prueba"""
        mock_datetime.now.return_value = datetime(2024, 1, 15, 10, 30, 0)
        
        strategy = LiveTestStrategy(broker=mock_broker, parameters=test_strategy_params)
        strategy.initialize()
        strategy.start_time = datetime(2024, 1, 15, 10, 0, 0)
        
        # Configurar estado de prueba
        strategy.order_count = 10
        strategy.successful_orders = 8
        strategy.failed_orders = 2
        strategy.total_value_traded = 1000.0
        strategy.portfolio_value = 10500.0
        
        # Mocks necesarios
        strategy.log_message = Mock()
        strategy._close_all_positions = Mock()
        
        # Ejecutar finalización
        strategy._finalize_test()
        
        # Verificar que se cerraron las posiciones
        strategy._close_all_positions.assert_called_once()
        
        # Verificar que se logeó el resumen
        assert strategy.log_message.called
        calls = [str(call) for call in strategy.log_message.call_args_list]
        assert any("PRUEBA FINALIZADA" in call for call in calls)
        assert any("Tasa de éxito: 80.0%" in call for call in calls)