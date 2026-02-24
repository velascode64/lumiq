"""
Configuración y fixtures para pytest
"""

import pytest
import os
from unittest.mock import Mock, MagicMock
from datetime import datetime, timedelta
import pytz

from lumibot.entities import Asset
from lumibot.brokers import Alpaca


@pytest.fixture
def mock_broker():
    """Mock del broker Alpaca para testing"""
    broker = Mock()
    broker.api = Mock()
    broker.IS_PAPER = True
    broker.name = "alpaca"
    broker.market = "NASDAQ"
    broker._data_source = Mock()
    broker._unprocessed_orders = []
    broker._filled_orders = []
    broker._new_orders = []
    broker._partially_filled_orders = []
    broker.unprocessed_orders = []
    broker.market_hours = Mock()
    
    # Mock data_source con datetime_start y datetime_end
    broker.data_source = Mock()
    broker.data_source.datetime_start = None
    broker.data_source.datetime_end = None
    
    # Métodos del broker
    broker.get_last_price = Mock(return_value=450.0)
    broker.submit_order = Mock()
    broker.get_orders = Mock(return_value=[])
    broker.get_positions = Mock(return_value=[])
    broker.cancel_order = Mock()
    broker.is_market_open = Mock(return_value=True)
    
    return broker


@pytest.fixture
def mock_strategy_config():
    """Configuración mock para estrategias"""
    return {
        'market': 'NASDAQ',
        'sleeptime': '1S',
        'benchmark_asset': 'SPY',
        'risk_free_rate': 0.04,
    }


@pytest.fixture
def test_strategy_params():
    """Parámetros de prueba para LiveTestStrategy"""
    return {
        'test_symbols': ['SPY', 'QQQ'],
        'order_interval_minutes': 1,
        'order_size_usd': 100,
        'max_position_per_symbol': 500,
        'test_duration_hours': 0.1,  # 6 minutos
        'enable_stop_loss': True,
        'enable_take_profit': True,
        'stop_loss_pct': 0.02,
        'take_profit_pct': 0.03,
    }


@pytest.fixture
def mock_trading_core_config():
    """Configuración mock para TradingCore"""
    return {
        'API_KEY': 'test_api_key',
        'API_SECRET': 'test_api_secret',
        'IS_PAPER': True,
    }


@pytest.fixture
def spy_asset():
    """Asset mock para SPY"""
    return Asset(symbol='SPY')


@pytest.fixture
def qqq_asset():
    """Asset mock para QQQ"""
    return Asset(symbol='QQQ')


@pytest.fixture
def mock_position():
    """Mock de una posición"""
    position = Mock()
    position.asset = Asset(symbol='SPY')
    position.quantity = 10.0
    position.avg_price = 450.0
    return position


@pytest.fixture
def mock_order():
    """Mock de una orden"""
    order = Mock()
    order.id = 'test_order_123'
    order.asset = Asset(symbol='SPY')
    order.side = 'buy'
    order.quantity = 10.0
    order.status = 'pending'
    order.type = 'market'
    return order


@pytest.fixture
def mock_datetime_now(monkeypatch):
    """Fixture para controlar datetime.now()"""
    fixed_time = datetime(2024, 1, 15, 9, 30, 0)
    
    class MockDatetime:
        @classmethod
        def now(cls):
            return fixed_time
            
    monkeypatch.setattr('datetime.datetime', MockDatetime)
    return fixed_time


@pytest.fixture
def mock_get_last_price():
    """Mock para get_last_price que retorna precios simulados"""
    def _get_price(asset):
        prices = {
            'SPY': 450.0,
            'QQQ': 375.0,
            'IWM': 200.0,
        }
        return prices.get(asset.symbol, 100.0)
    return _get_price


@pytest.fixture(autouse=True)
def reset_environment():
    """Reset environment variables antes de cada test"""
    # Guardar valores originales
    original_env = os.environ.copy()
    
    # Limpiar variables de Alpaca
    for key in ['ALPACA_API_KEY', 'ALPACA_API_SECRET']:
        if key in os.environ:
            del os.environ[key]
    
    yield
    
    # Restaurar valores originales
    os.environ.clear()
    os.environ.update(original_env)