"""
Integration test for AlpacaDataService with real API.

Requires ALPACA_API_KEY and ALPACA_SECRET_KEY in environment.
"""

import os
import pytest


pytestmark = pytest.mark.integration


def _has_alpaca_creds() -> bool:
    return bool(os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_SECRET_KEY"))


@pytest.mark.skipif(not _has_alpaca_creds(), reason="Missing Alpaca credentials")
def test_real_alpaca_connection():
    from alerts.services.alpaca_data_service import AlpacaDataService

    service = AlpacaDataService()
    bars = service.get_stock_bars("SPY", days=5)

    assert bars is not None
    assert not bars.empty
