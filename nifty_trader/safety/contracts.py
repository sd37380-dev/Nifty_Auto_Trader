"""
Contracts and Schemas for Deterministic Safety Guard.

Deterministic invariants:
1. Total portfolio daily loss maximum: ₹2,000.
2. Single active instrument constraint: Only 1 instrument active at a time.
3. Position sizing: Exactly 1 lot per trade.
4. Per-instrument trade limit: Maximum 3 trades per day (NIFTY: 3, BANKNIFTY: 3).
5. Per-instrument daily loss limit: Maximum ₹1,000 daily loss (NIFTY: ₹1,000, BANKNIFTY: ₹1,000).
6. Risk-to-Reward ratio: Minimum 1:3 (3.0).
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class InstrumentRiskConfig(BaseModel):
    """Risk constraints for a specific tradable instrument."""
    symbol: str
    lot_size: int
    max_lots: int = 1
    max_trades_per_day: int = 3
    max_daily_loss: float = 1000.0
    minimum_rr: float = 3.0


class PortfolioRiskConfig(BaseModel):
    """System-wide portfolio risk configuration."""
    max_portfolio_daily_loss: float = 2000.0
    max_lots_per_trade: int = 1
    max_concurrent_instruments: int = 1
    max_concurrent_positions: int = 1
    minimum_rr: float = 3.0
    instruments: Dict[str, InstrumentRiskConfig] = Field(
        default_factory=lambda: {
            "NIFTY": InstrumentRiskConfig(
                symbol="NIFTY",
                lot_size=65,
                max_lots=1,
                max_trades_per_day=3,
                max_daily_loss=1000.0,
                minimum_rr=3.0,
            ),
            "BANKNIFTY": InstrumentRiskConfig(
                symbol="BANKNIFTY",
                lot_size=30,
                max_lots=1,
                max_trades_per_day=3,
                max_daily_loss=1000.0,
                minimum_rr=3.0,
            ),
        }
    )


class SafetyCheckResult(BaseModel):
    """Result of deterministic safety validation before order execution."""
    passed: bool
    reason: str
    rejection_code: Optional[str] = None
    violations: List[str] = Field(default_factory=list)
    details: Dict[str, Any] = Field(default_factory=dict)
