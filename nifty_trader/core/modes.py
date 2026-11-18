"""
Canonical Trading Modes, TradeIntent, TradeRecord, and Audit Contracts.

Implements the foundational domain models for Dual Autonomous Hermes Modes:
- Mode A: EXISTING_SYSTEM (Market Perception + Trading Brain)
- Mode B: HERMES_RESEARCH (Dhan Data + Data Engineering + Quantitative Research)

STRICT INVARIANTS:
1. Two independent modes: EXISTING_SYSTEM and HERMES_RESEARCH.
2. Every trade, intent, execution, and event MUST preserve its source mode.
3. No combination of scores, no voting, no mutual dependency.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field

from nifty_trader.paper.contracts import PaperAction, PaperOptionType, PaperTradeOrderRequest


class TradingMode(str, Enum):
    """
    Strict identity enumeration for autonomous trading modes.
    Never combine or make one subordinate to the other.
    """
    EXISTING_SYSTEM = "EXISTING_SYSTEM"
    HERMES_RESEARCH = "HERMES_RESEARCH"


class TradeIntent(BaseModel):
    """
    Structured trade intent formulated independently by either mode.
    Must be validated by the Deterministic Safety Guard before execution.
    """
    trade_intent_id: str = Field(default_factory=lambda: f"ti_{uuid.uuid4().hex[:10]}")
    mode: TradingMode = Field(..., description="MANDATORY: Source autonomous trading mode.")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    instrument: str = Field(default="NIFTY", description="Target tradable index or stock.")
    direction: str = Field(default="BUY", description="Directional intent: BUY or SELL.")
    setup: str = Field(description="Name or classification of the technical/quantitative setup.")
    entry_thesis: str = Field(description="Cognitive or empirical reasoning for the entry.")
    invalidation: str = Field(description="Strict invalidation condition for the thesis.")
    evidence_refs: List[str] = Field(default_factory=list, description="Traceable evidence references.")
    assessment_id: str = Field(description="Identifier of the assessment that produced this intent.")
    research_id: Optional[str] = Field(
        default=None,
        description="Mandatory for HERMES_RESEARCH; optional/null for EXISTING_SYSTEM.",
    )
    score: float = Field(description="Assessment score (-100 to +100 or 0 to 100).")
    confidence: float = Field(ge=0.0, le=1.0, description="Epistemic confidence rating.")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Downstream execution parameters for Sensibull paper trading
    expiry: Optional[str] = None
    strike: Optional[float] = None
    option_type: Optional[str] = "CE"  # CE or PE
    lots: int = 1
    quantity: Optional[int] = None
    limit_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    target_price: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_order_request(self) -> PaperTradeOrderRequest:
        """Converts TradeIntent into an executable Sensibull PaperTradeOrderRequest."""
        opt_type = PaperOptionType.PE if str(self.option_type).upper() == "PE" else PaperOptionType.CE
        action = PaperAction.SELL if str(self.direction).upper() == "SELL" else PaperAction.BUY

        return PaperTradeOrderRequest(
            symbol=self.instrument,
            expiry=self.expiry or "CURRENT_WEEK",
            strike=self.strike or 22650.0,
            option_type=opt_type,
            action=action,
            lots=self.lots,
            quantity=self.quantity,
            limit_price=self.limit_price,
            stop_loss_price=self.stop_loss_price,
            target_price=self.target_price,
            source_candidate_id=self.trade_intent_id,
            mode=self.mode,
            trade_intent_id=self.trade_intent_id,
            assessment_id=self.assessment_id,
            research_id=self.research_id,
        )


class TradeRecord(BaseModel):
    """
    Canonical persistent trade log entry with mandatory source attribution.
    """
    trade_id: str = Field(default_factory=lambda: f"trd_{uuid.uuid4().hex[:10]}")
    decision_source: TradingMode = Field(..., description="MANDATORY: EXISTING_SYSTEM or HERMES_RESEARCH.")
    trade_intent_id: str
    assessment_id: str
    research_id: Optional[str] = None  # Populated for HERMES_RESEARCH, null for EXISTING_SYSTEM
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    instrument: str = "NIFTY"
    direction: str = "BUY"
    strike: Optional[float] = None
    option_type: Optional[str] = None

    entry: Optional[float] = None
    stop_loss: Optional[float] = None
    target: Optional[float] = None

    score: float = 0.0
    confidence: float = 0.0
    thesis: str = ""

    safety_decision: str = "ALLOWED"  # ALLOWED or BLOCKED
    safety_block_reason: Optional[str] = None
    execution_status: str = "PENDING"  # FILLED, REJECTED, FAILED, CLOSED

    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None

    pnl: float = 0.0
    outcome: str = "OPEN"  # OPEN, PROFITABLE, LOSS, BREAKEVEN
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TradeLifecycleEventType(str, Enum):
    """Event types representing milestones in the trade lifecycle."""
    ASSESSMENT_CREATED = "ASSESSMENT_CREATED"
    TRADE_INTENT_CREATED = "TRADE_INTENT_CREATED"
    INTENT_FORMULATED = "TRADE_INTENT_CREATED"
    SAFETY_CHECK_STARTED = "SAFETY_CHECK_STARTED"
    SAFETY_ALLOWED = "SAFETY_ALLOWED"
    SAFETY_VALIDATED = "SAFETY_ALLOWED"
    SAFETY_BLOCKED = "SAFETY_BLOCKED"
    EXECUTION_REQUESTED = "EXECUTION_REQUESTED"
    EXECUTION_ATTEMPTED = "EXECUTION_REQUESTED"
    EXECUTION_STARTED = "EXECUTION_STARTED"
    EXECUTION_CONFIRMED = "EXECUTION_CONFIRMED"
    ORDER_SUBMITTED = "EXECUTION_CONFIRMED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    POSITION_OPENED = "POSITION_OPENED"
    POSITION_UPDATED = "POSITION_UPDATED"
    CLOSE_REQUESTED = "CLOSE_REQUESTED"
    POSITION_CLOSED = "POSITION_CLOSED"
    TRADE_COMPLETED = "TRADE_COMPLETED"
    POSITION_COLLISION_DETECTED = "POSITION_COLLISION_DETECTED"


class TradeEvent(BaseModel):
    """Auditable lifecycle milestone event tagged with strict mode attribution."""
    event_id: str = Field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:10]}")
    trade_id: Optional[str] = None
    mode: TradingMode
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event_type: TradeLifecycleEventType
    assessment_id: Optional[str] = None
    research_id: Optional[str] = None
    trade_intent_id: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)
