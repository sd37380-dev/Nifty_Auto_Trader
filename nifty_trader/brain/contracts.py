"""
Trading Brain Domain Models & Canonical Reasoning Contracts (Package 4).

Defines the cognitive interpretation schemas consumed and produced by the
Trading Brain. Formulates market regimes, scenarios, hypotheses, auditable
reasoning summaries, and bounded trade candidates.

STRICT INVARIANT: Reasoning output only. Zero trade orders, zero broker execution,
zero position sizing, zero deterministic risk approval.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field


# ==============================================================================
# 1. Cognitive Enums
# ==============================================================================

class MarketRegime(str, Enum):
    """Broad structural market classification."""
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING = "RANGING"
    TRANSITIONING = "TRANSITIONING"
    EXPANDING = "EXPANDING"
    CONTRACTING = "CONTRACTING"
    UNCLEAR = "UNCLEAR"


class SetupState(str, Enum):
    """
    Cognitive state of the trading brain for the current observation cycle.
    WAIT, NO_TRADE, and WATCH are first-class, valid decision states.
    None of these states authorizes execution.
    """
    NO_TRADE = "NO_TRADE"       # No meaningful actionable hypothesis exists
    WAIT = "WAIT"               # Important conditions have not yet developed or confirmation missing
    WATCH = "WATCH"             # A potentially meaningful situation is developing and should be monitored
    DEVELOPING = "DEVELOPING"   # Several conditions are aligning, but the setup is incomplete
    CANDIDATE = "CANDIDATE"     # Coherent trade thesis exists; could be passed to future Strategy/Risk


class CandidateDirection(str, Enum):
    """Directional bias of a candidate trade thesis."""
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


class UncertaintyType(str, Enum):
    """Categories of cognitive and perceptual uncertainty."""
    STALE_DATA = "STALE_DATA"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    AMBIGUOUS_STRUCTURE = "AMBIGUOUS_STRUCTURE"
    MISSING_OPTION_CHAIN = "MISSING_OPTION_CHAIN"
    LOW_VISUAL_CONFIDENCE = "LOW_VISUAL_CONFIDENCE"
    SESSION_TRANSITION = "SESSION_TRANSITION"


# ==============================================================================
# 2. Structural & Uncertainty Models
# ==============================================================================

class Uncertainty(BaseModel):
    """Explicitly documented ambiguity impacting the analysis."""
    type: UncertaintyType
    description: str
    affected_conclusion: str
    severity: str = "MEDIUM"  # LOW, MEDIUM, HIGH


class BoundedConfidence(BaseModel):
    """
    Confidence representation (0.0 to 1.0) with explicit empirical basis.
    DOES NOT represent statistical probability of trade profitability.
    """
    value: float = Field(ge=0.0, le=1.0)
    basis: List[str] = Field(
        default_factory=list,
        description="Factors supporting this confidence (e.g. source agreement, structural clarity)."
    )


class ObservationRequest(BaseModel):
    """
    Allows the brain to request additional or refreshed observations
    when information is missing or stale.
    """
    request_id: str = Field(default_factory=lambda: f"req_{uuid.uuid4().hex[:8]}")
    source: str  # "sensibull", "tradingview", "numerical"
    reason: str
    requested_information: str
    priority: str = "NORMAL"  # NORMAL, HIGH, URGENT
    expires_at: Optional[datetime] = None


# ==============================================================================
# 3. Scenario & Hypothesis Models
# ==============================================================================

class Scenario(BaseModel):
    """
    Plausible market scenario evaluated by the brain.
    Multiple simultaneous scenarios are normal and encouraged.
    """
    scenario_id: str = Field(default_factory=lambda: f"scen_{uuid.uuid4().hex[:6]}")
    description: str
    supporting_evidence: List[str] = Field(default_factory=list)
    contradictory_evidence: List[str] = Field(default_factory=list)
    confirmation_conditions: List[str] = Field(default_factory=list)
    invalidation_conditions: List[str] = Field(default_factory=list)
    missing_information: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class MarketHypothesis(BaseModel):
    """
    An interpretation that can be tested against future observations.
    NOT a trade order.
    """
    hypothesis_id: str = Field(default_factory=lambda: f"hyp_{uuid.uuid4().hex[:6]}")
    description: str
    timeframe: str  # Strictly "1H" or "15M"
    supporting_evidence: List[str] = Field(default_factory=list)
    contradictory_evidence: List[str] = Field(default_factory=list)
    confirmation_conditions: List[str] = Field(default_factory=list)
    invalidation_conditions: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class TradeCandidate(BaseModel):
    """
    Structured candidate trade thesis formed when state == CANDIDATE.
    STRICTLY NON-EXECUTABLE: Does not include broker parameters or risk approvals.
    """
    direction: CandidateDirection
    thesis: str
    market_context: str
    setup_conditions: List[str] = Field(default_factory=list)
    confirmation_conditions: List[str] = Field(default_factory=list)
    invalidation_conditions: List[str] = Field(
        default_factory=list,
        description="Conceptual conditions that invalidate this thesis. NOT a broker stop order."
    )
    observations_supporting: List[str] = Field(default_factory=list)
    observations_against: List[str] = Field(default_factory=list)
    uncertainty: str
    reasoning_confidence: float = Field(ge=0.0, le=1.0)
    required_downstream_information: List[str] = Field(
        default_factory=lambda: ["position_size", "risk_budget", "broker_margin", "approval_engine_signoff"],
        description="Downstream requirements that must be resolved by Risk/Approval before execution."
    )


# ==============================================================================
# 4. Canonical Output Contract: BrainReasoningOutput
# ==============================================================================

class BrainReasoningOutput(BaseModel):
    """
    The canonical reasoning output produced by Package 4 Trading Brain.
    Auditable, evidence-traceable, and strictly decoupled from order execution.
    """
    schema_version: str = "1.0"
    brain_run_id: str = Field(default_factory=lambda: f"brain_{uuid.uuid4().hex[:10]}")
    observation_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    instrument: str = "NIFTY"

    # Multi-timeframe and multi-source synthesis
    regime: MarketRegime
    regime_confidence: float = Field(ge=0.0, le=1.0)
    regime_evidence: List[str] = Field(default_factory=list)
    one_hour_interpretation: str
    fifteen_minute_interpretation: str
    multi_source_synthesis: str
    source_disagreement_assessment: Optional[str] = None

    # Scenarios and hypotheses
    scenarios: List[Scenario] = Field(default_factory=list)
    hypotheses: List[MarketHypothesis] = Field(default_factory=list)

    # Brain state decision
    current_state: SetupState
    state_rationale: str
    next_observation_needed: str

    # Optional candidate thesis (only populated when state == CANDIDATE or DEVELOPING)
    candidate_thesis: Optional[TradeCandidate] = None

    # Feedback loop: requests for missing/stale observations
    observation_requests: List[ObservationRequest] = Field(default_factory=list)

    # Uncertainty & confidence metrics
    confidence: BoundedConfidence
    uncertainties: List[Uncertainty] = Field(default_factory=list)

    # Human-readable auditable executive summary
    auditable_summary: str
