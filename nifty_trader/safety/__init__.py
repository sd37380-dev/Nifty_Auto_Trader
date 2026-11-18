"""
Deterministic Safety Guard & Risk Engine.

Non-bypassable safety boundary enforcing:
- Total portfolio daily loss maximum: ₹2,000.
- Per-instrument daily loss maximum: ₹1,000 (NIFTY & BANKNIFTY).
- Per-instrument max trades: 3 per day (NIFTY & BANKNIFTY).
- Position sizing: Exactly 1 lot per trade.
- Single active instrument constraint: 1 active instrument at a time.
- Risk-to-Reward ratio: Minimum 1:3 (3.0).
"""

from nifty_trader.safety.contracts import (
    InstrumentRiskConfig,
    PortfolioRiskConfig,
    SafetyCheckResult,
)
from nifty_trader.safety.guard import DeterministicSafetyGuard

__all__ = [
    "DeterministicSafetyGuard",
    "InstrumentRiskConfig",
    "PortfolioRiskConfig",
    "SafetyCheckResult",
]
