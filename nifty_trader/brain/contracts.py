"""
Package 4: Canonical Trading Brain Domain Models & Exact Domain Contracts.

Strict, versioned domain contracts governing cognitive interpretation between
canonical market observations (Package 3/3.1) and future Strategy/Risk/Paper Trading layers.

STRICT INVARIANT: Reasoning output only. Zero trade orders, zero broker execution,
zero position sizing, zero deterministic risk approval.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union
import uuid
from pydantic import BaseModel, Field, model_validator

from nifty_trader.contracts.models import (
    ManualInstructionContext,
    UnifiedMarketObservation,
)

PACKAGE4_SCHEMA_VERSION = "1.0"
DEFAULT_PROMPT_VERSION = "brain_prompt_v1.0"


# ==============================================================================
# 1. Enumerations
# ==============================================================================

class MarketRegime(str, Enum):
    """Broad structural market classification (descriptive, not trade signals)."""
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING = "RANGING"
    TRANSITIONING = "TRANSITIONING"
    EXPANDING = "EXPANDING"
    CONTRACTING = "CONTRACTING"
    UNCLEAR = "UNCLEAR"


class StructureType(str, Enum):
    """Recognized price action structure types."""
    HIGHER_HIGH = "HIGHER_HIGH"
    HIGHER_LOW = "HIGHER_LOW"
    LOWER_HIGH = "LOWER_HIGH"
    LOWER_LOW = "LOWER_LOW"
    RANGE_HIGH = "RANGE_HIGH"
    RANGE_LOW = "RANGE_LOW"
    BREAKOUT_ATTEMPT = "BREAKOUT_ATTEMPT"
    FAILED_BREAKOUT = "FAILED_BREAKOUT"
    REJECTION = "REJECTION"
    ACCEPTANCE = "ACCEPTANCE"
    CONSOLIDATION = "CONSOLIDATION"
    EXPANSION = "EXPANSION"
    UNKNOWN = "UNKNOWN"


class ReasoningState(str, Enum):
    """
    Primary cognitive state of the Trading Brain.
    WAIT, NO_TRADE, and WATCH are first-class, valid decision states.
    CANDIDATE is not an approval or execution order.
    """
    NO_TRADE = "NO_TRADE"       # No meaningful hypothesis exists
    WAIT = "WAIT"               # Something may develop, but required confirmation is missing
    WATCH = "WATCH"             # A meaningful situation is developing and deserves continued observation
    DEVELOPING = "DEVELOPING"   # Several conditions are aligning, but the thesis is incomplete
    CANDIDATE = "CANDIDATE"     # Coherent trade thesis exists for future downstream Strategy/Risk


class Direction(str, Enum):
    """Directional bias."""
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"


class EvidenceType(str, Enum):
    """Separates verifiable perceptual facts from model interpretations."""
    OBSERVATION = "OBSERVATION"
    INFERENCE = "INFERENCE"
    HYPOTHESIS = "HYPOTHESIS"
    UNKNOWN = "UNKNOWN"


class UncertaintyType(str, Enum):
    """Categories of cognitive and perceptual uncertainty."""
    STALE_DATA = "STALE_DATA"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    AMBIGUOUS_STRUCTURE = "AMBIGUOUS_STRUCTURE"
    MISSING_OPTION_CHAIN = "MISSING_OPTION_CHAIN"
    LOW_VISUAL_CONFIDENCE = "LOW_VISUAL_CONFIDENCE"
    MISSING_DATA = "MISSING_DATA"
    MODEL_UNCERTAINTY = "MODEL_UNCERTAINTY"
    OTHER = "OTHER"


class Severity(str, Enum):
    """Severity classification for uncertainties and issues."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# ==============================================================================
# 2. Traceability & Epistemic Foundations
# ==============================================================================

class ObservationReference(BaseModel):
    """Traceability link connecting reasoning statements to Package 3 evidence."""
    observation_id: str
    source_id: Optional[str] = None
    evidence_id: Optional[str] = None
    description: str


class Confidence(BaseModel):
    """
    Confidence representation (0.0 to 1.0) indicating reasoning support.
    DOES NOT represent statistical probability of trade profitability or win rate.
    """
    value: float = Field(ge=0.0, le=1.0)
    basis: List[str]
    data_completeness: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    source_agreement: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    structural_clarity: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    scenario_consistency: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class Uncertainty(BaseModel):
    """Explicitly documented ambiguity affecting conclusions."""
    type: UncertaintyType
    severity: Severity
    description: str
    affected_conclusion: Optional[str] = None
    evidence: List[ObservationReference] = Field(default_factory=list)


# ==============================================================================
# 3. Market Context & Timeframe Assessments
# ==============================================================================

class MarketContext(BaseModel):
    """The brain's interpretation of market context and regime."""
    regime: MarketRegime
    regime_confidence: Confidence
    structures: List[StructureType] = Field(default_factory=list)
    summary: str
    key_levels: List[str] = Field(
        default_factory=list,
        description="Descriptive structural levels; NOT automatic entry, stop, or target prices."
    )
    evidence: List[ObservationReference] = Field(default_factory=list)
    uncertainties: List[Uncertainty] = Field(default_factory=list)


class TimeframeAssessment(BaseModel):
    """Separate cognitive evaluation for supported timeframes (1H and 15M)."""
    timeframe: Literal["1H", "15M"]
    summary: str
    structures: List[StructureType] = Field(default_factory=list)
    directional_context: Direction
    important_observations: List[str] = Field(default_factory=list)
    evidence: List[ObservationReference] = Field(default_factory=list)
    uncertainties: List[Uncertainty] = Field(default_factory=list)


# ==============================================================================
# 4. Scenarios, Hypotheses, Conditions & Candidates
# ==============================================================================

class Scenario(BaseModel):
    """Plausible future market development. Multiple concurrent scenarios may coexist."""
    scenario_id: str = Field(default_factory=lambda: f"scen_{uuid.uuid4().hex[:6]}")
    description: str
    direction: Direction
    supporting_evidence: List[ObservationReference] = Field(default_factory=list)
    contradictory_evidence: List[ObservationReference] = Field(default_factory=list)
    confirmation_conditions: List[str] = Field(default_factory=list)
    invalidation_conditions: List[str] = Field(default_factory=list)
    missing_information: List[str] = Field(default_factory=list)
    confidence: Confidence


class MarketHypothesis(BaseModel):
    """A testable interpretation evaluated against ongoing market observations."""
    hypothesis_id: str = Field(default_factory=lambda: f"hyp_{uuid.uuid4().hex[:6]}")
    statement: str
    direction: Direction
    supporting_evidence: List[ObservationReference] = Field(default_factory=list)
    contradictory_evidence: List[ObservationReference] = Field(default_factory=list)
    confirmation_conditions: List[str] = Field(default_factory=list)
    invalidation_conditions: List[str] = Field(default_factory=list)
    missing_information: List[str] = Field(default_factory=list)
    confidence: Confidence
    uncertainties: List[Uncertainty] = Field(default_factory=list)


class SetupCondition(BaseModel):
    """Observable condition required for setup maturation."""
    condition_id: str = Field(default_factory=lambda: f"cond_{uuid.uuid4().hex[:6]}")
    description: str
    timeframe: Optional[Literal["1H", "15M"]] = None
    required: bool = True
    evidence_required: bool = True
    satisfied: Optional[bool] = None  # None = cannot determine, unknown stays unknown


class TradeCandidate(BaseModel):
    """
    Highest-level candidate trade thesis produced by Package 4.
    STRICTLY NON-EXECUTABLE: Does not include broker parameters or risk approvals.
    """
    candidate_id: str = Field(default_factory=lambda: f"cand_{uuid.uuid4().hex[:8]}")
    direction: Direction
    thesis: str
    market_context: str
    setup_conditions: List[SetupCondition] = Field(default_factory=list)
    confirmation_conditions: List[str] = Field(default_factory=list)
    invalidation_conditions: List[str] = Field(
        default_factory=list,
        description="Conceptual conditions that invalidate this thesis. NOT a broker stop order."
    )
    supporting_evidence: List[ObservationReference] = Field(default_factory=list)
    opposing_evidence: List[ObservationReference] = Field(default_factory=list)
    uncertainties: List[Uncertainty] = Field(default_factory=list)
    reasoning_confidence: Confidence
    required_downstream_information: List[str] = Field(
        default_factory=lambda: ["position_size", "risk_budget", "broker_margin", "approval_engine_signoff"],
        description="Downstream requirements that must be resolved by Risk/Approval before execution."
    )


class ObservationRequest(BaseModel):
    """Requests additional or refreshed observations from perception sources."""
    request_id: str = Field(default_factory=lambda: f"req_{uuid.uuid4().hex[:8]}")
    source: str
    reason: str
    requested_information: List[str] = Field(default_factory=list)
    priority: Literal["LOW", "NORMAL", "HIGH", "CRITICAL"] = "NORMAL"
    expires_at: Optional[datetime] = None


class ReasoningSummary(BaseModel):
    """Auditable, human-readable executive reasoning explanation."""
    context: str
    key_observations: List[str] = Field(default_factory=list)
    interpretation: str
    supporting_evidence: List[ObservationReference] = Field(default_factory=list)
    contradictory_evidence: List[ObservationReference] = Field(default_factory=list)
    what_would_change_assessment: List[str] = Field(default_factory=list)


# ==============================================================================
# 5. Exact Input, State & Output Contracts
# ==============================================================================

class BrainInput(BaseModel):
    """Exact input boundary contract feeding Package 4."""
    schema_version: str = PACKAGE4_SCHEMA_VERSION
    brain_request_id: str = Field(default_factory=lambda: f"breq_{uuid.uuid4().hex[:10]}")
    observation: UnifiedMarketObservation
    task: Literal["MARKET_ANALYSIS", "SETUP_CONFIRMATION"] = "MARKET_ANALYSIS"
    manual_instruction_context: List[ManualInstructionContext] = Field(default_factory=list)
    previous_brain_state: Optional["BrainState"] = None
    requested_focus: List[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BrainState(BaseModel):
    """Main persisted cognitive state representation."""
    schema_version: str = PACKAGE4_SCHEMA_VERSION
    state_id: str = Field(default_factory=lambda: f"bstate_{uuid.uuid4().hex[:10]}")
    reasoning_state: ReasoningState
    market_context: MarketContext
    timeframe_assessments: List[TimeframeAssessment] = Field(default_factory=list)
    scenarios: List[Scenario] = Field(default_factory=list)
    hypotheses: List[MarketHypothesis] = Field(default_factory=list)
    active_candidate: Optional[TradeCandidate] = None
    observation_requests: List[ObservationRequest] = Field(default_factory=list)
    uncertainties: List[Uncertainty] = Field(default_factory=list)
    confidence: Confidence
    reasoning_summary: ReasoningSummary
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_observation_id: str


class BrainOutput(BaseModel):
    """
    Exact canonical output contract returned by the Trading Brain.
    Auditable, evidence-traceable, and strictly decoupled from order execution.
    """
    schema_version: str = PACKAGE4_SCHEMA_VERSION
    brain_request_id: str
    observation_id: str
    reasoning_state: ReasoningState
    market_context: MarketContext
    timeframe_assessments: List[TimeframeAssessment] = Field(default_factory=list)
    scenarios: List[Scenario] = Field(default_factory=list)
    hypotheses: List[MarketHypothesis] = Field(default_factory=list)
    candidate: Optional[TradeCandidate] = None
    observation_requests: List[ObservationRequest] = Field(default_factory=list)
    uncertainties: List[Uncertainty] = Field(default_factory=list)
    confidence: Confidence
    reasoning_summary: ReasoningSummary
    required_downstream_information: List[str] = Field(
        default_factory=lambda: ["position_size", "risk_budget", "broker_margin", "approval_engine_signoff"]
    )
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BrainFailure(BaseModel):
    """Structured failure representation when reasoning cannot be safely completed."""
    schema_version: str = PACKAGE4_SCHEMA_VERSION
    brain_request_id: str
    observation_id: str
    code: Literal[
        "MODEL_ERROR",
        "VALIDATION_ERROR",
        "TIMEOUT",
        "PROVIDER_UNAVAILABLE",
        "INSUFFICIENT_CONTEXT",
        "CONTRACT_ERROR",
    ]
    message: str
    retryable: bool
    provider: Optional[str] = None
    model: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BrainResult(BaseModel):
    """Runtime result wrapper enforcing success/failure exclusivity invariant."""
    success: bool
    output: Optional[BrainOutput] = None
    failure: Optional[BrainFailure] = None

    @model_validator(mode="after")
    def validate_exclusivity(self) -> "BrainResult":
        if self.success:
            if self.output is None or self.failure is not None:
                raise ValueError("Invariant violation: success=True requires output != None and failure == None")
        else:
            if self.output is not None or self.failure is None:
                raise ValueError("Invariant violation: success=False requires output == None and failure != None")
        return self


class BrainRecord(BaseModel):
    """Normalized SQLite persistence record header for reasoning history."""
    record_id: str = Field(default_factory=lambda: f"brec_{uuid.uuid4().hex[:10]}")
    schema_version: str = PACKAGE4_SCHEMA_VERSION
    brain_request_id: str
    observation_id: str
    model_provider: str
    model_name: str
    task: str = "MARKET_ANALYSIS"
    prompt_version: str = DEFAULT_PROMPT_VERSION
    brain_schema_version: str = PACKAGE4_SCHEMA_VERSION
    reasoning_state: ReasoningState
    confidence: Confidence
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
