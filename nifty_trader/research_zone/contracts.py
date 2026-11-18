"""
Canonical Contracts and Domain Models for the Hermes Research & Intelligence Zone.

STRICT INVARIANTS:
1. Complete isolation from live/paper trading execution loops.
2. Dynamic importance weighting: No fixed or static percentage weights for segments.
3. Negative knowledge preservation: Failed hypotheses are first-class empirical findings.
4. Dhan-Ready: Raw payload representations map directly to Dhan Broker schemas without live dependencies.
5. Schema version enforced (RESEARCH_ZONE_SCHEMA_VERSION = "1.0").
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field

RESEARCH_ZONE_SCHEMA_VERSION = "1.0"


# ==============================================================================
# 1. Enumerations
# ==============================================================================

class MarketDirection(str, Enum):
    """Directional bias derived from empirical analysis."""
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    UNCLEAR = "UNCLEAR"


class PatternType(str, Enum):
    """Classification of quantitative or structural patterns."""
    BREAKOUT = "BREAKOUT"
    MEAN_REVERSION = "MEAN_REVERSION"
    MOMENTUM_CONTINUATION = "MOMENTUM_CONTINUATION"
    VOLATILITY_COMPRESSION = "VOLATILITY_COMPRESSION"
    RANGE_BOUNCE = "RANGE_BOUNCE"
    OI_ACCUMULATION = "OI_ACCUMULATION"
    FAILED_BREAKOUT = "FAILED_BREAKOUT"
    OTHER = "OTHER"


class HypothesisStatus(str, Enum):
    """Lifecycle status of a research hypothesis."""
    DRAFT = "DRAFT"
    TESTING = "TESTING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    INCONCLUSIVE = "INCONCLUSIVE"


class DataQualityRating(str, Enum):
    """Integrity score of ingested data."""
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"


# ==============================================================================
# 2. Data Engineering Models
# ==============================================================================

class DhanRawPayload(BaseModel):
    """Represents raw payload delivered by Dhan Broker APIs or WebSockets."""
    payload_id: str = Field(default_factory=lambda: f"raw_{uuid.uuid4().hex[:8]}")
    symbol: str
    security_id: Optional[str] = None
    exchange_segment: str = "NSE_FNO"  # NSE_EQ, NSE_FNO, IDX_I
    payload_type: str  # HISTORICAL_MINUTE, INTRADAY_TICK, OPTION_CHAIN, MARKET_DEPTH
    raw_data: Any
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class NormalizedBar(BaseModel):
    """Standardized OHLCV bar with Open Interest and VWAP across all timeframes."""
    bar_id: str = Field(default_factory=lambda: f"bar_{uuid.uuid4().hex[:8]}")
    symbol: str
    timeframe: str  # 1M, 5M, 15M, 1H, 1D
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    open_interest: int = 0
    vwap: float = 0.0
    trades_count: int = 0


class DataQualityReport(BaseModel):
    """Telemetry validating data completeness, sanity, and time continuity."""
    report_id: str = Field(default_factory=lambda: f"dqr_{uuid.uuid4().hex[:8]}")
    symbol: str
    timeframe: str
    total_bars: int
    missing_bars_count: int = 0
    invalid_candles_count: int = 0
    completeness_percentage: float = 100.0
    gap_events: List[str] = Field(default_factory=list)
    quality_rating: DataQualityRating = DataQualityRating.EXCELLENT
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FeatureRow(BaseModel):
    """Enriched quantitative features computed for a specific bar."""
    timestamp: datetime
    close: float
    ema_9: Optional[float] = None
    ema_20: Optional[float] = None
    ema_50: Optional[float] = None
    ema_200: Optional[float] = None
    rsi_14: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_hist: Optional[float] = None
    atr_14: Optional[float] = None
    vwap: Optional[float] = None
    vwap_std_upper: Optional[float] = None
    vwap_std_lower: Optional[float] = None
    volume_ratio_20: Optional[float] = None
    oi_change_pct: Optional[float] = None
    regime_tag: str = "UNDEFINED"


class FeatureSet(BaseModel):
    """A prepared time-series dataset of features ready for research."""
    feature_set_id: str = Field(default_factory=lambda: f"fset_{uuid.uuid4().hex[:8]}")
    symbol: str
    timeframe: str
    rows: List[FeatureRow] = Field(default_factory=list)
    total_bars: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==============================================================================
# 3. Hermes Research Engine Models
# ==============================================================================

class ResearchQuestion(BaseModel):
    """A specific inquiry formulated by Hermes to investigate market behavior."""
    question_id: str = Field(default_factory=lambda: f"rq_{uuid.uuid4().hex[:8]}")
    topic: str
    description: str
    target_symbol: str = "NIFTY"
    target_timeframe: str = "15M"
    parameters: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PatternDefinition(BaseModel):
    """Specification of an observable market structure or statistical setup."""
    pattern_id: str = Field(default_factory=lambda: f"pat_{uuid.uuid4().hex[:8]}")
    name: str
    pattern_type: PatternType
    description: str
    conditions: List[str] = Field(default_factory=list)
    required_features: List[str] = Field(default_factory=list)


class Hypothesis(BaseModel):
    """A falsifiable hypothesis formulated for empirical backtesting."""
    hypothesis_id: str = Field(default_factory=lambda: f"hyp_{uuid.uuid4().hex[:8]}")
    question_id: str
    statement: str
    testable_condition: str
    null_hypothesis: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    status: HypothesisStatus = HypothesisStatus.DRAFT
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TestResult(BaseModel):
    """Empirical testing metrics evaluating a hypothesis over historical bars."""
    test_id: str = Field(default_factory=lambda: f"test_{uuid.uuid4().hex[:8]}")
    hypothesis_id: str
    sample_size: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    p_value: Optional[float] = None
    summary: str
    tested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ContradictionSearch(BaseModel):
    """Investigation actively seeking counter-evidence, edge cases, and failure modes."""
    search_id: str = Field(default_factory=lambda: f"cntr_{uuid.uuid4().hex[:8]}")
    hypothesis_id: str
    counter_examples_count: int = 0
    failure_regimes: List[str] = Field(default_factory=list)
    false_positive_rate: float = 0.0
    findings: str
    conducted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FollowUpResearch(BaseModel):
    """A subsequent research direction spawned by discoveries or contradictions."""
    followup_id: str = Field(default_factory=lambda: f"fup_{uuid.uuid4().hex[:8]}")
    parent_research_id: str
    new_question: str
    rationale: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==============================================================================
# 4. Hermes Assessment & Dynamic Scoring Models
# ==============================================================================

class AssessmentSegment(BaseModel):
    """
    An independent segment of market analysis with dynamic importance.
    STRICT INVARIANT: No fixed weights. Hermes dynamically decides importance.
    """
    segment_id: str = Field(default_factory=lambda: f"seg_{uuid.uuid4().hex[:6]}")
    name: str  # e.g., "Market Structure", "Momentum & Volatility", "OI Flow & Positioning", "Contradiction Check"
    score: float = Field(ge=-100.0, le=100.0, description="Segment score from -100 (Extremely Bearish) to +100 (Extremely Bullish)")
    importance: float = Field(ge=0.0, le=1.0, description="Dynamic importance assigned by Hermes for this specific context")
    evidence: List[str] = Field(default_factory=list, description="Traceable evidence IDs or observation references")
    reasoning_summary: str = Field(description="Why this score and importance were assigned")


class HermesResearchAssessment(BaseModel):
    """
    Master research assessment generated by Hermes with dynamically weighted segments.
    """
    research_id: str = Field(default_factory=lambda: f"rass_{uuid.uuid4().hex[:8]}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    instrument: str = "NIFTY"
    timeframe: str = "15M"
    segments: List[AssessmentSegment] = Field(default_factory=list)
    total_score: float = Field(ge=-100.0, le=100.0)
    confidence: float = Field(ge=0.0, le=1.0)
    direction: MarketDirection = MarketDirection.NEUTRAL
    trade_finding: str
    supporting_evidence: List[str] = Field(default_factory=list)
    contradictory_evidence: List[str] = Field(default_factory=list)
    uncertainty: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ==============================================================================
# 5. Research Memory Models
# ==============================================================================

class ResearchFinding(BaseModel):
    """A verified empirical finding stored for future research recall."""
    finding_id: str = Field(default_factory=lambda: f"fnd_{uuid.uuid4().hex[:8]}")
    pattern_name: str
    statistical_edge: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_refs: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FailedHypothesis(BaseModel):
    """
    Crucial negative knowledge: Records an idea that was tested and failed,
    preventing Hermes from repeatedly exploring dead ends.
    """
    failed_id: str = Field(default_factory=lambda: f"fhyp_{uuid.uuid4().hex[:8]}")
    hypothesis_id: str
    statement: str
    failure_reason: str
    counter_evidence: List[str] = Field(default_factory=list)
    lessons_learned: str
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ResearchHistoryEntry(BaseModel):
    """An auditable log entry documenting the progression of a research inquiry."""
    entry_id: str = Field(default_factory=lambda: f"rhist_{uuid.uuid4().hex[:8]}")
    research_id: str
    stage: str  # e.g., "QUESTION_FORMULATION", "DATASET_PREPARATION", "TESTING", "CONTRADICTION_SEARCH", "ASSESSMENT"
    summary: str
    details: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
