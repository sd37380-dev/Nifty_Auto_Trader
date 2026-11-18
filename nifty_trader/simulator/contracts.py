"""
Data contracts and models for the Real-Feel NIFTY Option Paper Trade Simulator.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class SignalType(str, Enum):
    BUY_CE = "BUY_CE"
    BUY_PE = "BUY_PE"
    CLOSE = "CLOSE"
    HOLD = "HOLD"


class ExitReason(str, Enum):
    TARGET = "TARGET"
    STOP_LOSS = "STOP_LOSS"
    TRAILING_SL = "TRAILING_SL"
    EOD_SQUAREOFF = "EOD_SQUAREOFF"
    RULE_EXIT = "RULE_EXIT"
    CIRCUIT_BREAKER = "CIRCUIT_BREAKER"


@dataclass
class TradeSignal:
    """Signal produced by local rule evaluation."""
    signal_type: SignalType
    reason: str
    strike: Optional[int] = None
    sl_points: float = 20.0       # Points or Percent
    target_points: float = 40.0   # Points or Percent
    sl_mode: str = "POINTS"       # "POINTS" or "PERCENT"
    target_mode: str = "POINTS"   # "POINTS" or "PERCENT"
    trailing_sl: bool = False
    trail_points: float = 10.0


@dataclass
class OptionPosition:
    """Active option paper position."""
    trade_id: str
    symbol: str
    option_type: str             # "CE" or "PE"
    strike: int
    qty: int
    lots: int
    entry_time: str
    entry_spot: float
    entry_premium: float         # Executed price including slippage
    current_premium: float
    sl_price: float
    target_price: float
    highest_premium: float
    trailing_sl: bool = False
    trail_step: float = 10.0
    sl_mode: str = "POINTS"
    target_mode: str = "POINTS"
    mtm_pnl: float = 0.0
    status: str = "OPEN"


@dataclass
class TradeResult:
    """Historical completed trade record."""
    trade_id: str
    symbol: str
    option_type: str
    strike: int
    lots: int
    qty: int
    entry_time: str
    exit_time: str
    entry_spot: float
    exit_spot: float
    entry_premium: float
    exit_premium: float
    exit_reason: ExitReason
    gross_pnl: float
    brokerage: float
    taxes: float
    total_charges: float
    net_pnl: float
    pnl_pct: float
    duration_minutes: int
    rule_name: str


@dataclass
class SimulationSummary:
    """Comprehensive performance statistics for the paper trading simulation."""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    breakeven_trades: int = 0
    win_rate: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    gross_pnl: float = 0.0
    total_charges: float = 0.0
    net_pnl: float = 0.0
    profit_factor: float = 0.0
    avg_trade_pnl: float = 0.0
    max_profit_trade: float = 0.0
    max_loss_trade: float = 0.0
    max_drawdown_amount: float = 0.0
    max_drawdown_pct: float = 0.0
    avg_holding_minutes: float = 0.0
    trades: List[TradeResult] = field(default_factory=list)
