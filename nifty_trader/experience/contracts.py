"""
Canonical Contracts and Domain Models for Stage 10: Performance Analysis & Experience Memory.

STRICT INVARIANTS:
1. Distinguishes: WHAT WAS KNOWN -> WHAT WAS REASONED -> WHAT ACTION WAS TAKEN -> WHAT HAPPENED -> WHAT CAN BE LEARNED.
2. Decoupled evaluation: Never equate PROFIT = GOOD REASONING or LOSS = BAD REASONING.
3. Separates Decision Quality, Execution Quality, and Market Outcome.
4. Epistemic traceability: Categorizes facts into OBSERVED, INFERRED, HYPOTHESIS, and UNKNOWN.
5. No automatic strategy rules: Lessons are purely descriptive historical experiences.
6. Schema versioning enforced (EXPERIENCE_SCHEMA_VERSION = "1.0").
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field

EXPERIENCE_SCHEMA_VERSION = "1.0"


# ==============================================================================
# 1. Enums
# ==============================================================================

class TradeOutcome(str, Enum):
    """Categorization of verified economic outcome."""
    PROFITABLE = "PROFITABLE"
    LOSS = "LOSS"
    BREAKEVEN = "BREAKEVEN"
    UNKNOWN = "UNKNOWN"


class ReasoningOutcomeCategory(str, Enum):
    """Evaluation of the cognitive thesis validity during trade evolution."""
    THESIS_CONFIRMED = "THESIS_CONFIRMED"
    THESIS_INVALIDATED = "THESIS_INVALIDATED"
    THESIS_PARTIALLY_CONFIRMED = "THESIS_PARTIALLY_CONFIRMED"
    THESIS_REMAINED_UNRESOLVED = "THESIS_REMAINED_UNRESOLVED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class ExecutionOutcomeCategory(str, Enum):
    """Evaluation of platform interaction and order lifecycle execution."""
    EXECUTION_CONFIRMED = "EXECUTION_CONFIRMED"
    EXECUTION_PARTIALLY_CONFIRMED = "EXECUTION_PARTIALLY_CONFIRMED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    EXECUTION_UNKNOWN = "EXECUTION_UNKNOWN"


class EvidenceQuality(str, Enum):
    """Data completeness and integrity rating for the analyzed trade."""
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    CONFLICTED = "CONFLICTED"
    STALE = "STALE"
    INSUFFICIENT = "INSUFFICIENT"


class EpistemicStatus(str, Enum):
    """Separates verifiable facts from analytical interpretations."""
    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"
    HYPOTHESIS = "HYPOTHESIS"
    UNKNOWN = "UNKNOWN"


class MemoryStatus(str, Enum):
    """Lifecycle state of an experience record in persistent memory."""
    RAW = "RAW"
    VALIDATED = "VALIDATED"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    REJECTED = "REJECTED"


class LessonType(str, Enum):
    """Categorization of descriptive takeaways derived from trade evidence."""
    OBSERVATION_LESSON = "OBSERVATION_LESSON"
    REASONING_LESSON = "REASONING_LESSON"
    WAITING_LESSON = "WAITING_LESSON"
    EXECUTION_LESSON = "EXECUTION_LESSON"
    POSITION_MANAGEMENT_LESSON = "POSITION_MANAGEMENT_LESSON"
    DATA_QUALITY_LESSON = "DATA_QUALITY_LESSON"
    SOURCE_CONFLICT_LESSON = "SOURCE_CONFLICT_LESSON"


class ExperienceTag(str, Enum):
    """Standardized metadata taxonomy tags for structured memory search."""
    MARKET_STRUCTURE = "MARKET_STRUCTURE"
    BREAKOUT = "BREAKOUT"
    REVERSAL = "REVERSAL"
    RANGE = "RANGE"
    TREND = "TREND"
    CONSOLIDATION = "CONSOLIDATION"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    WAITING = "WAITING"
    EXECUTION = "EXECUTION"
    POSITION_MANAGEMENT = "POSITION_MANAGEMENT"
    DATA_QUALITY = "DATA_QUALITY"
    SLIPPAGE = "SLIPPAGE"


# ==============================================================================
# 2. Timeline & Structural Components
# ==============================================================================

class TimelineEvent(BaseModel):
    """A chronologically ordered milestone in the trade lifecycle."""
    event_id: str = Field(default_factory=lambda: f"tevt_{uuid.uuid4().hex[:8]}")
    timestamp: datetime
    source: str  # BRAIN, MARKET_OBSERVATION, SAFETY, SENSIBULL_PAPER, POSITION_MONITOR, OPERATOR
    event_type: str  # ORDER_SUBMITTED, ORDER_FILLED, CANDLE_CLOSED, REASSESSMENT, SQUARE_OFF_REQUESTED, POSITION_CLOSED
    description: str
    details: Dict[str, Any] = Field(default_factory=dict)
    evidence_refs: List[str] = Field(default_factory=list)


class TradeTimeline(BaseModel):
    """Chronologically ordered reconstruction of the full trade lifecycle."""
    trade_id: str
    events: List[TimelineEvent] = Field(default_factory=list)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_minutes: float = 0.0
    has_gaps: bool = False
    gap_descriptions: List[str] = Field(default_factory=list)


# ==============================================================================
# 3. Decoupled Dimension Analyses
# ==============================================================================

class ReasoningAnalysis(BaseModel):
    """Evaluation of the cognitive setup, hypotheses, and thesis evolution."""
    original_hypothesis: Optional[str] = None
    original_thesis: Optional[str] = None
    original_direction: Optional[str] = None
    confirmation_conditions: List[str] = Field(default_factory=list)
    invalidation_conditions: List[str] = Field(default_factory=list)
    uncertainties: List[str] = Field(default_factory=list)
    initial_confidence: float = 0.0
    reasoning_outcome: ReasoningOutcomeCategory = ReasoningOutcomeCategory.INSUFFICIENT_EVIDENCE
    thesis_evaluation: str
    reassessment_count: int = 0
    source_conflicts: List[str] = Field(default_factory=list)
    evidence_quality: EvidenceQuality = EvidenceQuality.COMPLETE
    evidence_refs: List[str] = Field(default_factory=list)


class ExecutionAnalysis(BaseModel):
    """Evaluation of platform interaction fidelity, slippage, and latency."""
    execution_outcome: ExecutionOutcomeCategory = ExecutionOutcomeCategory.EXECUTION_UNKNOWN
    entry_requested_price: Optional[float] = None
    entry_executed_price: Optional[float] = None
    entry_slippage: float = 0.0
    exit_requested_price: Optional[float] = None
    exit_executed_price: Optional[float] = None
    exit_slippage: float = 0.0
    order_duration_seconds: float = 0.0
    idempotency_verified: bool = False
    visual_confirmation: bool = False
    sensibull_environment: str = "UNKNOWN"
    reconciliation_discrepancies: List[str] = Field(default_factory=list)
    notes: str = ""


class OutcomeAnalysis(BaseModel):
    """Verified economic results from Sensibull ground truth."""
    outcome: TradeOutcome = TradeOutcome.UNKNOWN
    realized_pnl: float = 0.0
    pnl_percentage: float = 0.0
    max_favorable_excursion_pnl: float = 0.0
    max_adverse_excursion_pnl: float = 0.0
    holding_duration_minutes: float = 0.0
    exit_reason: str = "UNKNOWN"
    is_verified_pnl: bool = False
    data_quality: EvidenceQuality = EvidenceQuality.COMPLETE


class Lesson(BaseModel):
    """
    Evidence-grounded takeaway from trade analysis.
    STRICTLY NON-DETERMINISTIC: Never an imperative strategy rule.
    """
    lesson_id: str = Field(default_factory=lambda: f"lsn_{uuid.uuid4().hex[:8]}")
    lesson_type: LessonType
    statement: str
    epistemic_status: EpistemicStatus = EpistemicStatus.INFERRED
    evidence_refs: List[str] = Field(default_factory=list)
    supporting_events: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    is_validated: bool = False


# ==============================================================================
# 4. Master Experience Record
# ==============================================================================

class ExperienceRecord(BaseModel):
    """
    Canonical post-trade experience record preserved in persistent memory.
    """
    experience_id: str = Field(default_factory=lambda: f"exp_{uuid.uuid4().hex[:10]}")
    trade_id: str
    position_id: Optional[str] = None
    symbol: str = "NIFTY"
    strike: float
    option_type: str  # CE, PE, FUT
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: str = EXPERIENCE_SCHEMA_VERSION
    market_context: str
    original_thesis: str
    timeline: TradeTimeline
    reasoning_analysis: ReasoningAnalysis
    execution_analysis: ExecutionAnalysis
    outcome_analysis: OutcomeAnalysis
    lessons: List[Lesson] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    evidence_quality: EvidenceQuality = EvidenceQuality.COMPLETE
    memory_status: MemoryStatus = MemoryStatus.RAW
    similar_experience_count: int = 1
    summary: str


# ==============================================================================
# 5. Performance Summary & Metrics
# ==============================================================================

class PerformanceSummary(BaseModel):
    """
    Aggregated descriptive performance statistics derived from verified trades.
    Zero composite strategy scores.
    """
    total_completed_trades: int = 0
    verified_trades_count: int = 0
    unverified_trades_count: int = 0
    profitable_trades: int = 0
    loss_trades: int = 0
    breakeven_trades: int = 0
    win_rate_pct: float = 0.0
    total_realized_pnl: float = 0.0
    avg_pnl: float = 0.0
    median_pnl: float = 0.0
    largest_gain: float = 0.0
    largest_loss: float = 0.0
    max_drawdown: float = 0.0
    profit_factor: float = 0.0
    avg_duration_minutes: float = 0.0

    # Operational & Cognitive Metrics
    total_reassessments: int = 0
    avg_reassessments_per_trade: float = 0.0
    wait_frequency: int = 0
    source_conflicts_encountered: int = 0
    brain_failures_encountered: int = 0
    execution_failures_encountered: int = 0
    reconciliation_events_encountered: int = 0
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
