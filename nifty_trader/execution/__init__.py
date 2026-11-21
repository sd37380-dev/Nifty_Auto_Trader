"""
Execution and broker connectivity package for NIFTY Autonomous Trader.
"""

from nifty_trader.execution.broker_service import BrokerService, get_broker_service

__all__ = ["BrokerService", "get_broker_service"]
