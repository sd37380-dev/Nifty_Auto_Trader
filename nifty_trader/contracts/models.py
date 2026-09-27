"""
Canonical Observation Contracts for NIFTY Autonomous Trader.

Defines the universal, immutable data contracts feeding the Package 4 Trading Brain.
All observation sources (TradingView, Sensibull, Yahoo Finance, NSE, Operator Steering)
normalize their perceptions into these traceable, versioned contracts.

STRICT INVARIANT: Observation only. Purely descriptive evidence, zero trade signals.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field

# Timezone helper
try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
except Exception:
    from datetime import timedelta
    IST = timezone(timedelta(hours=5, minutes=30), name="IST")


# ==============================================================================
# 1. Enums and Primitives
# ==============================================================================

class SourceChannelType(str, Enum):
    """Categorization of perception source channels."""
    BROWSER = "BROWSER"
    NUMERICAL = "NUMERICAL"
    OTHER = "OTHER"


class CanonicalObservationStatus(str, Enum):
    """
    Standardized observation outcome status.
    Missing information is never represented as a fake zero value.
    """
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    NOT_VISIBLE = "NOT_VISIBLE"
    NOT_LOADED = "NOT_LOADED"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    STALE = "STALE"
    PARSE_FAILED = "PARSE_FAILED"
    SOURCE_ERROR = "SOURCE_ERROR"
    TIMEOUT = "TIMEOUT"


class EvidenceType(str, Enum):
    """Categorization of verifiable perceptual evidence."""
    SCREENSHOT = "SCREENSHOT"
    VISIBLE_TEXT = "VISIBLE_TEXT"
    DOM = "DOM"
    NUMERICAL_DATA = "NUMERICAL_DATA"
    USER_INSTRUCTION = "USER_INSTRUCTION"


class CrossSourceValidationStatus(str, Enum):
    """Outcome classification of cross-source price comparisons."""
    MATCH = "MATCH"
    MINOR_DIFFERENCE = "MINOR_DIFFERENCE"
    SIGNIFICANT_DIFFERENCE = "SIGNIFICANT_DIFFERENCE"
    UNCOMPARABLE = "UNCOMPARABLE"


class WarningSeverity(str, Enum):
    """Severity classification for perceptual warnings."""
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


# ==============================================================================
# 2. Source Identification & Traceable Evidence
# ==============================================================================

class ObservationSource(BaseModel):
    """Consistent metadata declaration for any observation source."""
    schema_version: str = "1.0"
    source_id: str
    source_type: SourceChannelType
    provider: str
    version: Optional[str] = None
    capabilities: List[str] = Field(default_factory=list)


class ObservationEvidence(BaseModel):
    """
    Verifiable perceptual artifact enabling Package 4 to distinguish
    'The agent saw this' from 'The model inferred this'.
    """
    schema_version: str = "1.0"
    evidence_id: str = Field(default_factory=lambda: f"ev_{uuid.uuid4().hex[:10]}")
    source_id: str
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    evidence_type: EvidenceType
    reference: Optional[str] = None  # File path, URL, or identifier
    excerpt: Optional[str] = None    # Text snippet or extracted fragment
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ==============================================================================
# 3. Canonical Numerical & Candle Observations
# ==============================================================================

class CandleObservation(BaseModel):
    """
    Canonical OHLCV candle record.
    UTC storage with IST presentation helper. Completed vs forming strictly segregated.
    """
    schema_version: str = "1.0"
    instrument: str = "NIFTY"
    timeframe: str  # Strictly "1H" or "15M"
    timestamp: datetime  # UTC
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None
    is_complete: bool = True
    source: str = "yahoo_finance"

    @property
    def timestamp_ist(self) -> datetime:
        return self.timestamp.astimezone(IST)


class NumericalObservation(BaseModel):
    """Aggregated numerical candlestick feeds across canonical 1H and 15M timeframes."""
    schema_version: str = "1.0"
    instrument: str = "NIFTY"
    candles_1h: List[CandleObservation] = Field(default_factory=list)
    candles_15m: List[CandleObservation] = Field(default_factory=list)

    @property
    def latest_1h(self) -> Optional[CandleObservation]:
        return self.candles_1h[-1] if self.candles_1h else None

    @property
    def latest_15m(self) -> Optional[CandleObservation]:
        return self.candles_15m[-1] if self.candles_15m else None


# ==============================================================================
# 4. Canonical Visual & Chart Observations (TradingView)
# ==============================================================================

class TradingViewObservation(BaseModel):
    """
    Canonical visual observation from TradingView.
    STRICTLY NON-TRADING: visible_chart_context describes visual patterns without trading signals.
    """
    schema_version: str = "1.0"
    status: CanonicalObservationStatus
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    instrument: str = "NIFTY"
    timeframe_views: Dict[str, Any] = Field(default_factory=dict)  # e.g. {"1H": {...}, "15M": {...}}
    visible_price: Optional[float] = None
    visible_chart_context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Factual observations: trend_appearance, range_appearance, recent_swing_structure, visible_levels."
    )
    visible_text: Optional[str] = None
    screenshot: Optional[str] = None
    page_url: Optional[str] = None
    evidence_ids: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


# ==============================================================================
# 5. Canonical Derivatives & Option Chain Observations (Sensibull)
# ==============================================================================

class OptionLegObservation(BaseModel):
    """Call or Put option quote details for a specific strike."""
    ltp: Optional[float] = None
    oi: Optional[float] = None
    oi_change: Optional[float] = None
    volume: Optional[float] = None
    iv: Optional[float] = None


class OptionStrikeObservation(BaseModel):
    """Normalized strike row across call and put legs."""
    strike: float
    call: OptionLegObservation = Field(default_factory=OptionLegObservation)
    put: OptionLegObservation = Field(default_factory=OptionLegObservation)


class OptionChainObservation(BaseModel):
    """Normalized option chain dataset."""
    schema_version: str = "1.0"
    underlying: str = "NIFTY"
    expiry: Optional[str] = None
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    spot: Optional[float] = None
    strikes: List[OptionStrikeObservation] = Field(default_factory=list)
    source: str = "sensibull"


class SensibullObservation(BaseModel):
    """
    Canonical derivatives observation from Sensibull.
    Null values represent unavailable data, never fake 0.0 values.
    """
    schema_version: str = "1.0"
    status: CanonicalObservationStatus
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    underlying: str = "NIFTY"
    expiry: Optional[str] = None
    spot_reference: Optional[float] = None
    option_chain: Optional[OptionChainObservation] = None
    pcr: Optional[float] = None  # None when unobserved, never 0.0
    open_interest: Dict[str, Any] = Field(default_factory=dict)
    oi_change: Dict[str, Any] = Field(default_factory=dict)
    implied_volatility: Dict[str, Any] = Field(default_factory=dict)
    max_pain: Optional[float] = None
    visible_strikes: List[float] = Field(default_factory=list)
    important_visible_levels: List[float] = Field(default_factory=list)
    screenshot: Optional[str] = None
    visible_text: Optional[str] = None
    page_url: Optional[str] = None
    evidence_ids: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class VisualObservation(BaseModel):
    """Container grouping all browser-based visual perception channels."""
    schema_version: str = "1.0"
    tradingview: Optional[TradingViewObservation] = None
    sensibull: Optional[SensibullObservation] = None


# ==============================================================================
# 6. Source Telemetry, Cross-Validation & Warnings
# ==============================================================================

class SourceStatus(BaseModel):
    """Health, latency, and data completeness telemetry for a perception source."""
    schema_version: str = "1.0"
    source_id: str
    status: CanonicalObservationStatus
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    latency_ms: Optional[float] = None
    data_age_seconds: Optional[float] = None
    completeness: float = Field(default=1.0, ge=0.0, le=1.0)
    warnings: List[str] = Field(default_factory=list)


class CrossSourceValidation(BaseModel):
    """
    Objective comparison between two independent sources without declaring one 'right'.
    Preserves source independence.
    """
    schema_version: str = "1.0"
    comparison_id: str = Field(default_factory=lambda: f"csv_{uuid.uuid4().hex[:8]}")
    field: str  # e.g. "spot_price"
    source_a: str
    value_a: Optional[float] = None
    source_b: str
    value_b: Optional[float] = None
    absolute_difference: Optional[float] = None
    relative_difference: Optional[float] = None  # Percentage e.g. 0.04%
    tolerance: float = 0.5  # Max tolerance threshold
    status: CrossSourceValidationStatus = CrossSourceValidationStatus.UNCOMPARABLE
    details: Optional[str] = None


class ManualInstructionContext(BaseModel):
    """Traceable human operator guidance injected into the observation context."""
    schema_version: str = "1.0"
    instruction_id: str
    text: str
    priority: str
    status: str
    created_at: datetime
    created_by: str = "human_operator"
    expires_at: Optional[datetime] = None
    applicable_sources: List[str] = Field(default_factory=list)


class ObservationWarning(BaseModel):
    """Structured perception warning flagged during an observation cycle."""
    schema_version: str = "1.0"
    code: str  # STALE_SOURCE, MISSING_OPTION_CHAIN, AUTH_REQUIRED, CHART_NOT_LOADED, SOURCE_DISAGREEMENT, PARTIAL_OBSERVATION
    severity: WarningSeverity
    source: str
    message: str
    evidence_id: Optional[str] = None


# ==============================================================================
# 7. UnifiedMarketObservation (The Sole Canonical Package 4 Input Contract)
# ==============================================================================

class UnifiedMarketObservation(BaseModel):
    """
    The Single Canonical Input Contract consumed by Package 4 Trading Brain.
    
    Package 3 reports what was observed and where it came from.
    Package 4 interprets what the observations mean.
    """
    schema_version: str = "1.0"
    observation_id: str = Field(default_factory=lambda: f"umo_{uuid.uuid4().hex[:10]}")
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    instrument: str = "NIFTY"
    session: str = "OPEN"  # OPEN, CLOSED, PRE_MARKET, POST_MARKET

    # Core observation channels
    numerical: NumericalObservation = Field(default_factory=NumericalObservation)
    visual: VisualObservation = Field(default_factory=VisualObservation)

    # Telemetry and contextual layers
    source_status: Dict[str, SourceStatus] = Field(default_factory=dict)
    cross_source_validation: List[CrossSourceValidation] = Field(default_factory=list)
    manual_instruction_context: List[ManualInstructionContext] = Field(default_factory=list)
    evidence: List[ObservationEvidence] = Field(default_factory=list)
    warnings: List[ObservationWarning] = Field(default_factory=list)

    @property
    def observed_at_ist(self) -> datetime:
        return self.observed_at.astimezone(IST)

    @property
    def is_partial(self) -> bool:
        """Indicates whether any critical observation source was incomplete or unavailable."""
        return any(
            s.status != CanonicalObservationStatus.SUCCESS
            for s in self.source_status.values()
        )

    @property
    def summary_text(self) -> str:
        """Concise neutral overview of all compiled observation channels."""
        c1h = self.numerical.latest_1h
        c15m = self.numerical.latest_15m
        h1_str = f"{c1h.close:.2f}" if c1h else "N/A"
        m15_str = f"{c15m.close:.2f}" if c15m else "N/A"
        
        sensi_str = "Not Observed"
        if self.visual.sensibull:
            s = self.visual.sensibull
            if s.status == CanonicalObservationStatus.SUCCESS and s.pcr is not None:
                sensi_str = f"PCR={s.pcr:.2f}, Max Pain={s.max_pain or 'N/A'}"
            else:
                sensi_str = f"Status={s.status.value}"
                
        tv_str = "Not Observed"
        if self.visual.tradingview:
            tv = self.visual.tradingview
            tv_str = f"Price={tv.visible_price or 'N/A'}, Status={tv.status.value}"

        return (
            f"Unified Observation ({self.instrument} at {self.observed_at_ist.strftime('%Y-%m-%d %H:%M IST')}): "
            f"Session={self.session}, 1H Close={h1_str}, 15M Close={m15_str}, "
            f"Sensibull=[{sensi_str}], TradingView=[{tv_str}]."
        )
