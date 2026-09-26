"""
Observation Models and Data Schemas for Package 3.1.

Defines canonical models for Sensibull option-chain observations,
multi-source cross-validation, and pluggable observation source telemetry.
STRICTLY NON-TRADING: Contains perception metrics only.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field


class SensibullStatus(str, Enum):
    """Lifecycle and operational status for Sensibull observation."""
    OBSERVED = "OBSERVED"
    NOT_VISIBLE = "NOT_VISIBLE"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    NOT_LOADED = "NOT_LOADED"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    PARSE_FAILED = "PARSE_FAILED"
    STALE = "STALE"
    ERROR = "ERROR"


class ObservationFreshness(str, Enum):
    """Freshness classification for time-sensitive market perception data."""
    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class ObservationSourceType(str, Enum):
    """Categorization of perception source channels."""
    NUMERICAL = "NUMERICAL"
    CHART_VISUAL = "CHART_VISUAL"
    DERIVATIVES_OPTION_CHAIN = "DERIVATIVES_OPTION_CHAIN"


class OptionChainStrike(BaseModel):
    """Perceptual record of a single visible strike in the option chain."""
    strike: float
    call_oi: Optional[float] = None
    call_oi_change: Optional[float] = None
    call_iv: Optional[float] = None
    call_ltp: Optional[float] = None
    put_oi: Optional[float] = None
    put_oi_change: Optional[float] = None
    put_iv: Optional[float] = None
    put_ltp: Optional[float] = None


class SensibullObservation(BaseModel):
    """
    Structured perceptual observation extracted from Sensibull option chain.
    
    IMPORTANT: Distinguishes between observed values and missing data.
    Missing fields remain None; they are NEVER coerced to 0.0.
    """
    observation_id: str = Field(default_factory=lambda: f"sensi_{uuid.uuid4().hex[:8]}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "sensibull"
    status: SensibullStatus
    instrument: str = "NIFTY"
    underlying: str = "NIFTY 50"
    expiry: Optional[str] = None
    spot_reference: Optional[float] = None
    option_chain_available: bool = False
    visible_option_chain_data: Dict[str, Any] = Field(default_factory=dict)
    
    # Core Derivatives Metrics (None when unobserved, never 0.0)
    pcr: Optional[float] = None
    oi_information: Dict[str, Any] = Field(default_factory=dict)
    oi_change_information: Dict[str, Any] = Field(default_factory=dict)
    iv_information: Dict[str, Any] = Field(default_factory=dict)
    strike_information: List[OptionChainStrike] = Field(default_factory=list)
    max_pain_information: Optional[float] = None
    important_levels: List[float] = Field(default_factory=list)
    
    screenshot_reference: Optional[str] = None
    visible_text: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    freshness: ObservationFreshness = ObservationFreshness.UNKNOWN
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def is_successful(self) -> bool:
        return self.status == SensibullStatus.OBSERVED

    @property
    def requires_auth(self) -> bool:
        return self.status == SensibullStatus.AUTHENTICATION_REQUIRED


class SourceObservationResult(BaseModel):
    """Standardized output wrapper from any IMarketObservationSource."""
    source_id: str
    source_type: ObservationSourceType
    success: bool
    status: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    data: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MultiSourceComparisonResult(BaseModel):
    """
    Cross-validation comparing multiple observation sources against authoritative numerical feeds.
    Detects discrepancies without silently overwriting any source.
    """
    sensibull_spot: Optional[float] = None
    tradingview_spot: Optional[float] = None
    numerical_close: Optional[float] = None

    # Sensibull vs Numerical Feed
    sensibull_vs_numerical_diff: Optional[float] = None
    sensibull_vs_numerical_pct: Optional[float] = None
    sensibull_vs_numerical_status: str = "INSUFFICIENT_DATA"  # MATCH, MINOR_DIFFERENCE, SIGNIFICANT_DIFFERENCE, INSUFFICIENT_DATA

    # TradingView vs Numerical Feed
    tradingview_vs_numerical_diff: Optional[float] = None
    tradingview_vs_numerical_pct: Optional[float] = None
    tradingview_vs_numerical_status: str = "INSUFFICIENT_DATA"

    details: List[str] = Field(default_factory=list)

    @property
    def is_consistent(self) -> bool:
        """Returns True if no significant discrepancies exist among available sources."""
        return (
            self.sensibull_vs_numerical_status in ["MATCH", "MINOR_DIFFERENCE", "INSUFFICIENT_DATA"]
            and self.tradingview_vs_numerical_status in ["MATCH", "MINOR_DIFFERENCE", "INSUFFICIENT_DATA"]
        )
