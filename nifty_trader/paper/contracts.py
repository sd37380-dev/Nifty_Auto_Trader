"""
Canonical Contracts and Schemas for Stage 8: Sensibull Paper Trading.

STRICT INVARIANT:
- Does NOT decide whether a trade is good (that belongs to Hermes + AI Brain).
- Represents execution state, DOM position telemetry, order status, and reconciliation.
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field


STAGE8_SCHEMA_VERSION = "1.0.0"


class SensibullEnvironmentType(str, Enum):
    VIRTUAL_TRADE = "VIRTUAL_TRADE"
    LIVE_BROKER = "LIVE_BROKER"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    UNKNOWN = "UNKNOWN"
    ERROR = "ERROR"


class PaperAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class PaperOptionType(str, Enum):
    CE = "CE"
    PE = "PE"
    FUT = "FUT"


class PaperOrderStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTING = "SUBMITTING"
    OPEN = "OPEN"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class PaperPositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    EXTERNAL_CLOSED = "EXTERNAL_CLOSED"


class PaperTradeOrderRequest(BaseModel):
    """Execution request generated from an approved trade plan."""
    request_id: str = Field(default_factory=lambda: f"preq_{uuid.uuid4().hex[:10]}")
    symbol: str = "NIFTY"
    expiry: str
    strike: float
    option_type: PaperOptionType
    action: PaperAction = PaperAction.BUY
    lots: int = 1
    quantity: Optional[int] = None
    limit_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    target_price: Optional[float] = None
    source_candidate_id: Optional[str] = None
    mode: str = "EXISTING_SYSTEM"
    trade_intent_id: Optional[str] = None
    assessment_id: Optional[str] = None
    research_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def model_post_init(self, __context: Any) -> None:
        if self.quantity is None or self.quantity <= 0:
            lot_multiplier = 30 if "BANKNIFTY" in self.symbol.upper() else 65
            self.quantity = self.lots * lot_multiplier

    @property
    def idempotency_key(self) -> str:
        """Deterministic SHA-256 fingerprint preventing duplicate submissions."""
        content = f"{self.mode}_{self.symbol}_{self.expiry}_{self.strike}_{self.option_type.value}_{self.action.value}_{self.lots}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


class PaperTradeOrder(BaseModel):
    """Auditable record of a paper trade order."""
    order_id: str = Field(default_factory=lambda: f"pord_{uuid.uuid4().hex[:10]}")
    request_id: str
    idempotency_key: str
    symbol: str = "NIFTY"
    expiry: str
    strike: float
    option_type: PaperOptionType
    action: PaperAction
    lots: int
    quantity: int
    entry_price: Optional[float] = None
    mode: str = "EXISTING_SYSTEM"
    trade_intent_id: Optional[str] = None
    assessment_id: Optional[str] = None
    research_id: Optional[str] = None
    status: PaperOrderStatus = PaperOrderStatus.PENDING
    status_reason: Optional[str] = None
    pre_execution_screenshot: Optional[str] = None
    post_execution_screenshot: Optional[str] = None
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    verified_at: Optional[datetime] = None


class PaperPosition(BaseModel):
    """An open or closed virtual position on Sensibull Virtual Portfolio."""
    position_id: str = Field(default_factory=lambda: f"ppos_{uuid.uuid4().hex[:10]}")
    symbol: str = "NIFTY"
    expiry: str
    strike: float
    option_type: PaperOptionType
    action: PaperAction = PaperAction.BUY
    lots: int = 1
    quantity: int = 25
    avg_price: float
    current_ltp: float
    mode: str = "EXISTING_SYSTEM"
    trade_intent_id: Optional[str] = None
    assessment_id: Optional[str] = None
    research_id: Optional[str] = None
    unrealized_pnl: float = 0.0
    pnl_percentage: float = 0.0
    realized_pnl: float = 0.0
    status: PaperPositionStatus = PaperPositionStatus.OPEN
    first_detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: Optional[datetime] = None
    exit_price: Optional[float] = None


class PaperPortfolioSummary(BaseModel):
    """Executive summary of the Sensibull paper trading portfolio."""
    environment: SensibullEnvironmentType
    is_safe_environment: bool
    total_positions: int = 0
    open_positions_count: int = 0
    total_unrealized_pnl: float = 0.0
    total_realized_pnl: float = 0.0
    net_pnl: float = 0.0
    positions: List[PaperPosition] = Field(default_factory=list)
    last_synced_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PaperPositionObservation(BaseModel):
    """Telemetry fed back to Hermes and the AI Brain during collaboration cycles."""
    schema_version: str = STAGE8_SCHEMA_VERSION
    observation_id: str = Field(default_factory=lambda: f"pobs_{uuid.uuid4().hex[:10]}")
    environment: SensibullEnvironmentType
    has_open_position: bool = False
    open_positions: List[PaperPosition] = Field(default_factory=list)
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    net_exposure_lots: int = 0
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ReconciliationDiscrepancy(BaseModel):
    """Discrepancy between Hermes local state and Sensibull remote ground truth."""
    discrepancy_id: str = Field(default_factory=lambda: f"disc_{uuid.uuid4().hex[:8]}")
    discrepancy_type: str  # MISSING_REMOTE, EXTRA_REMOTE, QUANTITY_MISMATCH, STATUS_MISMATCH
    hermes_state: Optional[Dict[str, Any]] = None
    sensibull_state: Optional[Dict[str, Any]] = None
    resolution_action: str
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
