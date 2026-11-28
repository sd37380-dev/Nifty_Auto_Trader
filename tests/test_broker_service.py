"""
Unit tests for BrokerService and real-time Dhan endpoints.
"""

from pathlib import Path
from nifty_trader.execution.broker_service import BrokerService, get_broker_service


def test_broker_service_singleton():
    bs1 = get_broker_service()
    bs2 = get_broker_service()
    assert bs1 is bs2


def test_broker_service_paper_defaults():
    bs = BrokerService(root_dir=Path(__file__).resolve().parent.parent)
    # When credentials are not set or mock:
    pos_data = bs.get_broker_positions()
    assert "positions" in pos_data
    assert isinstance(pos_data["positions"], list)

    ord_data = bs.get_broker_orders()
    assert "orders" in ord_data
    assert isinstance(ord_data["orders"], list)

    funds_data = bs.get_broker_funds()
    assert "availMargin" in funds_data
