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

    # Test trading mode switching
    res_live = bs.set_trading_mode("LIVE")
    assert res_live["trading_mode"] == "LIVE"
    res_paper = bs.set_trading_mode("PAPER")
    assert res_paper["trading_mode"] == "PAPER"
    assert bs.trading_mode == "PAPER"
