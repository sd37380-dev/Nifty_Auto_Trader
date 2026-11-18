"""
NIFTY Option Paper Trade Simulator Package.
"""

from nifty_trader.simulator.charges import IndianFOChargesCalculator
from nifty_trader.simulator.contracts import OptionPosition, SignalType, TradeResult, TradeSignal
from nifty_trader.simulator.engine import NiftyOptionSimulator
from nifty_trader.simulator.rules import BaseStrategyRule, EMAPivotBounceRule, SupertrendMomentumRule
from nifty_trader.simulator.user_rule import CustomUserRule

__all__ = [
    "NiftyOptionSimulator",
    "IndianFOChargesCalculator",
    "BaseStrategyRule",
    "EMAPivotBounceRule",
    "SupertrendMomentumRule",
    "CustomUserRule",
    "TradeSignal",
    "SignalType",
    "OptionPosition",
    "TradeResult",
]
