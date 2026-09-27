"""
Package 5: Autonomous Observation & Waiting Engine Contracts.

Defines the domain contracts, enums, cycle state containers, wait decisions,
wake conditions, observation plans, and cycle execution results for the
autonomous temporal-control layer.

STRICT INVARIANTS:
1. Temporal control and observation scheduling only.
2. Zero trade generation, zero order execution, zero position sizing, zero risk approval.
3. Consumes Package 3/3.1 (UnifiedMarketObservation) and Package 4 (BrainResult/BrainOutput).
4. WAIT is an action, not an error.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Tuple
import uuid
from pydantic import BaseModel, Field

from nifty_trader.contracts.models import (
    CanonicalObservationStatus,
    UnifiedMarketObservation,
    IST,
)
from nifty_trader.brain.contracts import (
    BrainFailure,
    BrainInput,
    BrainOutput,
    BrainResult,
    BrainState,
    ObservationRequest,
    ReasoningState,
)

PACKAGE5_SCHEMA_VERSION = "1.0"


# ==============================================================================
# 1. State Machine & Wait Enums
# ==============================================================================

class AutonomousState(str, Enum):
    """
    Primary operational state of the Package 5 Autonomous Engine.
    """
    IDLE = "IDLE"                               # No autonomous cycle is active
    STARTING = "STARTING"                       # Autonomous session is being initialized
    OBSERVING = "OBSERVING"                     # Package 3/3.1 observation is being gathered
    ANALYZING = "ANALYZING"                     # Package 4 Trading Brain is evaluating observation
    WAITING = "WAITING"                         # Brain decided another observation should happen later
    WATCHING = "WATCHING"                       # Market situation is interesting and requires continued monitoring
    REOBSERVE_REQUESTED = "REOBSERVE_REQUESTED" # Package 4 explicitly requested additional information
    CANDIDATE_READY = "CANDIDATE_READY"         # Package 4 produced a trade candidate; cycle halts
    NO_TRADE = "NO_TRADE"                       # Reasoning concluded no meaningful candidate currently
    SESSION_PAUSED = "SESSION_PAUSED"           # Temporarily paused (e.g. pre-market or operator paused)
    SESSION_ENDED = "SESSION_ENDED"             # Market closed or session duration reached
    ERROR = "ERROR"                             # Unrecoverable error requiring operator intervention
    STOPPED = "STOPPED"                         # User or system explicitly stopped the engine


class WaitReason(str, Enum):
    """
    Categorized justification for entering a WAITING state.
    """
    NEXT_CANDLE = "NEXT_CANDLE"                 # Waiting for 15M or 1H candle boundary closure
    PRICE_CHANGE = "PRICE_CHANGE"               # Waiting for significant price movement
    STRUCTURAL_CHANGE = "STRUCTURAL_CHANGE"     # Waiting for structural development
    SOURCE_REFRESH = "SOURCE_REFRESH"           # Waiting for specific source refresh (e.g. Sensibull)
    OBSERVATION_REQUEST = "OBSERVATION_REQUEST" # Brain explicitly requested specific data refresh
    TIME_DELAY = "TIME_DELAY"                   # General time-based pacing delay
    SESSION_EVENT = "SESSION_EVENT"             # Waiting for market open or session phase change
    MANUAL_INSTRUCTION = "MANUAL_INSTRUCTION"   # Waiting for operator instruction update
    RETRY_BACKOFF = "RETRY_BACKOFF"             # Waiting due to bounded retry backoff
    MARKET_OPEN = "MARKET_OPEN"                 # Waiting for 09:15 IST market open
    MARKET_RESUME = "MARKET_RESUME"             # Waiting for session resumption after pause
    BRAIN_UNAVAILABLE = "BRAIN_UNAVAILABLE"     # Package 4 model failure backoff
    OBSERVATION_FAILED = "OBSERVATION_FAILED"   # Package 3 perception failure backoff
    UNKNOWN = "UNKNOWN"


class WakeConditionType(str, Enum):
    """
    Event or temporal trigger that satisfies a waiting state and wakes the engine.
    """
    TIME = "TIME"
    CANDLE_COMPLETION = "CANDLE_COMPLETION"
    PRICE_CHANGE = "PRICE_CHANGE"
    STRUCTURE_CHANGE = "STRUCTURE_CHANGE"
    SOURCE_REFRESH = "SOURCE_REFRESH"
    OBSERVATION_REQUEST = "OBSERVATION_REQUEST"
    MANUAL_INSTRUCTION = "MANUAL_INSTRUCTION"
    SESSION_EVENT = "SESSION_EVENT"
    ERROR_RECOVERY = "ERROR_RECOVERY"
    USER_COMMAND = "USER_COMMAND"


class ObservationPriority(str, Enum):
    """Priority tier for scheduling observation requests."""
    CRITICAL = "CRITICAL"   # Refresh immediately
    HIGH = "HIGH"           # Refresh at next safe opportunity
    NORMAL = "NORMAL"       # Refresh according to standard cycle
    LOW = "LOW"             # Refresh opportunistically


class SourceFreshnessStatus(str, Enum):
    """Freshness evaluation of an observation source."""
    FRESH = "FRESH"
    AGING = "AGING"
    STALE = "STALE"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


# ==============================================================================
# 2. Wake Conditions, Wait Decisions & Observation Plans
# ==============================================================================

class WakeCondition(BaseModel):
    """
    A declarative trigger condition that will cause the engine to wake and re-evaluate.
    Multiple wake conditions can coexist (first to trigger wakes the engine).
    """
    schema_version: str = PACKAGE5_SCHEMA_VERSION
    condition_id: str = Field(default_factory=lambda: f"wake_{uuid.uuid4().hex[:8]}")
    type: WakeConditionType
    source: Optional[str] = None
    timeframe: Optional[str] = None  # e.g. "15M" or "1H"
    threshold: Optional[float] = None
    scheduled_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None
    reason: str
    satisfied: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def scheduled_at_ist(self) -> datetime:
        return self.scheduled_at.astimezone(IST)


class WaitDecision(BaseModel):
    """
    The structured waiting decision derived from Package 4 output or session conditions.
    """
    schema_version: str = PACKAGE5_SCHEMA_VERSION
    decision_id: str = Field(default_factory=lambda: f"wait_{uuid.uuid4().hex[:8]}")
    should_wait: bool = True
    reason: WaitReason = WaitReason.NEXT_CANDLE
    wake_conditions: List[WakeCondition] = Field(default_factory=list)
    earliest_wake_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    latest_wake_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    observation_requests: List[ObservationRequest] = Field(default_factory=list)
    explanation: str

    @property
    def earliest_wake_at_ist(self) -> datetime:
        return self.earliest_wake_at.astimezone(IST)

    @property
    def latest_wake_at_ist(self) -> datetime:
        return self.latest_wake_at.astimezone(IST)


class ScheduledObservationPlan(BaseModel):
    """
    A scheduled observation action planned by Package 5 to refresh specific source data.
    """
    schema_version: str = PACKAGE5_SCHEMA_VERSION
    plan_id: str = Field(default_factory=lambda: f"splan_{uuid.uuid4().hex[:8]}")
    source: str
    requested_information: List[str] = Field(default_factory=list)
    priority: ObservationPriority = ObservationPriority.NORMAL
    scheduled_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None
    request_fingerprint: str
    reason: str
    status: str = "PENDING"  # PENDING, EXECUTED, CANCELLED, EXPIRED, SUPPRESSED

    @property
    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        return datetime.now(timezone.utc) > self.expires_at


# ==============================================================================
# 3. Cycle & Session Contracts
# ==============================================================================

class AutonomousCycle(BaseModel):
    """
    Audit record for a single execution cycle of the autonomous observation loop.
    """
    schema_version: str = PACKAGE5_SCHEMA_VERSION
    cycle_id: str = Field(default_factory=lambda: f"cycle_{uuid.uuid4().hex[:8]}")
    session_id: str
    cycle_index: int
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    observation_id: Optional[str] = None
    brain_request_id: Optional[str] = None
    previous_state: AutonomousState
    resulting_state: AutonomousState
    wake_reason: Optional[str] = None
    wait_reason: Optional[WaitReason] = None
    observation_count: int = 0
    model_call_count: int = 0
    errors: List[str] = Field(default_factory=list)


class CycleResult(BaseModel):
    """
    Result returned by the execution of a single autonomous cycle.
    STRICT INVARIANT: No order or execution parameters.
    """
    schema_version: str = PACKAGE5_SCHEMA_VERSION
    success: bool
    state: AutonomousState
    cycle_id: str
    brain_output: Optional[BrainOutput] = None
    next_wait: Optional[WaitDecision] = None
    observation_plans: List[ScheduledObservationPlan] = Field(default_factory=list)
    failure: Optional[str] = None
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AutonomousSession(BaseModel):
    """
    Lifecycle tracking record for an autonomous operational session.
    """
    schema_version: str = PACKAGE5_SCHEMA_VERSION
    session_id: str = Field(default_factory=lambda: f"asess_{uuid.uuid4().hex[:8]}")
    symbol: str = "NIFTY"
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: Optional[datetime] = None
    status: AutonomousState = AutonomousState.IDLE
    cycles_completed: int = 0
    model_calls: int = 0
    observation_requests_count: int = 0
    consecutive_failures: int = 0


class AutonomousLimits(BaseModel):
    """
    Configurable operational safety limits governing autonomous execution.
    These are safety thresholds, not trading strategy parameters.
    """
    max_cycles: int = 100
    max_observation_requests: int = 20
    max_model_calls: int = 50
    max_consecutive_failures: int = 5
    max_session_duration_minutes: int = 390  # 6.5 hours (full NSE session)
    min_wait_seconds: float = 5.0
    max_wait_seconds: float = 3600.0
    default_cooldown_seconds: float = 30.0
    sensibull_cooldown_seconds: float = 60.0
    tradingview_cooldown_seconds: float = 30.0
    restore_after_restart: bool = True


# ==============================================================================
# 4. Explicit Package 4 Output Contract Validator (Spec 52A)
# ==============================================================================

class Package4OutputContractValidator:
    """
    Enforces strict Package 4 domain invariants on BrainOutput consumed by Package 5.
    (Specification Section 52A.9)
    """

    @staticmethod
    def validate(output: BrainOutput) -> Tuple[bool, Optional[str]]:
        # Invariant 1: CANDIDATE requires non-null candidate
        if output.reasoning_state == ReasoningState.CANDIDATE:
            if output.candidate is None:
                return False, "Invariant violation: reasoning_state == CANDIDATE requires candidate != None"
        else:
            # Invariant 2: WAIT / WATCH / DEVELOPING / NO_TRADE forbids non-null candidate
            if output.candidate is not None:
                return False, f"Invariant violation: reasoning_state == {output.reasoning_state.value} forbids non-null candidate"

        # Invariant 3: 1H and 15M assessments must exist
        tf_set = {t.timeframe for t in output.timeframe_assessments}
        if "1H" not in tf_set or "15M" not in tf_set:
            return False, f"Invariant violation: both 1H and 15M timeframe assessments are required (found: {sorted(list(tf_set))})"

        # Invariant 4: Confidence value bounded in [0.0, 1.0]
        if not (0.0 <= output.confidence.value <= 1.0):
            return False, f"Invariant violation: confidence.value ({output.confidence.value}) must be in [0.0, 1.0]"

        return True, None

