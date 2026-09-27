"""
Canonical Schemas and Contracts for Stage 9: Autonomous Trade Monitoring & Position Management.

STRICT INVARIANTS:
- No hard-coded strategy engine (no IF profit > X, IF loss > X, IF RSI < X).
- Does NOT decide whether a trade is good (that belongs to Hermes + AI Brain).
- Preserves original entry thesis and distinguishes it from current evidence.
- Full audit trail recorded in SQLite.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field

from nifty_trader.brain.contracts import (
    Direction,
    OpenPositionContext,
    PositionManagementAction,
    ReasoningState,
)
from nifty_trader.paper.contracts import (
    PaperAction,
    PaperOptionType,
    PaperPosition,
    PaperPositionStatus,
    SensibullEnvironmentType,
)


STAGE9_SCHEMA_VERSION = "1.0.0"


class MonitoringState(str, Enum):
    """Lifecycle state of an open position monitoring session."""
    IDLE = "IDLE"
    MONITORING = "MONITORING"
    WAITING = "WAITING"
    REASSESSING = "REASSESSING"
    MODIFICATION_REQUESTED = "MODIFICATION_REQUESTED"
    MODIFICATION_IN_PROGRESS = "MODIFICATION_IN_PROGRESS"
    CLOSE_REQUESTED = "CLOSE_REQUESTED"
    CLOSING = "CLOSING"
    VERIFYING = "VERIFYING"
    CLOSED = "CLOSED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    UNKNOWN = "UNKNOWN"
    ERROR = "ERROR"


class PositionMonitoringRecord(BaseModel):
    """Auditable record of a single position monitoring cycle / turn."""
    monitoring_id: str = Field(default_factory=lambda: f"mon_{uuid.uuid4().hex[:10]}")
    position_id: str
    trade_id: Optional[str] = None
    symbol: str = "NIFTY"
    strike: float
    option_type: str
    lots: int
    quantity: int
    entry_price: float
    current_price: float
    unrealized_pnl: float = 0.0
    pnl_percentage: float = 0.0
    holding_duration_minutes: float = 0.0
    monitoring_state: MonitoringState = MonitoringState.MONITORING
    wake_reason: Optional[str] = None
    market_observation_id: Optional[str] = None
    sensibull_observation_id: Optional[str] = None
    brain_request_id: Optional[str] = None
    brain_reasoning_state: Optional[ReasoningState] = None
    brain_position_action: Optional[PositionManagementAction] = None
    brain_summary: Optional[str] = None
    action_executed: Optional[str] = None
    action_result: Optional[str] = None
    discrepancy_detected: Optional[str] = None
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PositionEvent(BaseModel):
    """Auditable lifecycle event during trade monitoring."""
    event_id: str = Field(default_factory=lambda: f"pevt_{uuid.uuid4().hex[:8]}")
    event_type: str  # e.g. position-observed, brain-reassessment-completed, position-closed
    position_id: str
    details: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
