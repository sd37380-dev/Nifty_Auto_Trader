"""
Market Observation, Agent Observation Context, and Perception Output Schemas.

Structures multi-timeframe market perceptions, manual operator instructions,
and visual chart data for objective evaluation by ModelRouter/Gemini.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field

from nifty_trader.browser.models import BrowserObservation
from nifty_trader.instruction.models import AgentInstruction
from nifty_trader.market_data.cross_check import CrossCheckResult
from nifty_trader.market_data.models import (
    Candle,
    DataQuality,
    MarketSessionStatus,
    ObservationEvent,
)
from nifty_trader.observation.models import (
    MultiSourceComparisonResult,
    SensibullObservation,
    SensibullStatus,
)


class MarketObservation(BaseModel):
    """
    Consolidated perceptual record containing multi-timeframe numerical candles,
    browser observation, Sensibull option-chain data, and multi-source cross-check telemetry.
    STRICTLY NON-TRADING: Omits buy/sell/target/stop loss fields.
    """
    observation_id: str = Field(default_factory=lambda: f"obs_{uuid.uuid4().hex[:8]}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    symbol: str = "NIFTY"
    market_status: MarketSessionStatus
    one_hour_candles: List[Candle] = Field(default_factory=list)
    fifteen_minute_candles: List[Candle] = Field(default_factory=list)
    browser_observation: Optional[BrowserObservation] = None
    sensibull_observation: Optional[SensibullObservation] = None
    data_quality: DataQuality = DataQuality.VALID
    source_status: Dict[str, Any] = Field(default_factory=dict)
    cross_check: Optional[CrossCheckResult] = None
    multi_source_cross_check: Optional[MultiSourceComparisonResult] = None

    @property
    def latest_1h(self) -> Optional[Candle]:
        return self.one_hour_candles[-1] if self.one_hour_candles else None

    @property
    def latest_15m(self) -> Optional[Candle]:
        return self.fifteen_minute_candles[-1] if self.fifteen_minute_candles else None

    @property
    def timestamp_ist(self) -> datetime:
        from nifty_trader.market_data.models import IST
        return self.timestamp.astimezone(IST)

    @property
    def h1_summary(self) -> str:
        if not self.one_hour_candles:
            return "No 1H candles available."
        latest = self.one_hour_candles[-1]
        return f"Latest 1H close: {latest.close:.2f} (O:{latest.open:.2f}, H:{latest.high:.2f}, L:{latest.low:.2f}) at {latest.timestamp_ist.strftime('%Y-%m-%d %H:%M IST')}"

    @property
    def m15_summary(self) -> str:
        if not self.fifteen_minute_candles:
            return "No 15M candles available."
        latest = self.fifteen_minute_candles[-1]
        return f"Latest 15M close: {latest.close:.2f} (O:{latest.open:.2f}, H:{latest.high:.2f}, L:{latest.low:.2f}) at {latest.timestamp_ist.strftime('%Y-%m-%d %H:%M IST')}"

    @property
    def cross_check_match(self) -> bool:
        if not self.cross_check:
            return False
        return self.cross_check.is_aligned

    @property
    def cross_check_discrepancy_pct(self) -> float:
        if not self.cross_check or self.cross_check.discrepancy_pct is None:
            return 0.0
        return self.cross_check.discrepancy_pct

    @property
    def pcr_summary(self) -> str:
        if not self.sensibull_observation:
            return "Sensibull not observed."
        if self.sensibull_observation.status == SensibullStatus.AUTHENTICATION_REQUIRED:
            return "Sensibull: Authentication required (unobserved)."
        if self.sensibull_observation.pcr is not None:
            mp_str = f" | Max Pain: {self.sensibull_observation.max_pain_information:.0f}" if self.sensibull_observation.max_pain_information else ""
            iv_str = f" | ATM IV: {self.sensibull_observation.iv_information.get('atm_iv')}%" if self.sensibull_observation.iv_information.get('atm_iv') else ""
            return f"PCR: {self.sensibull_observation.pcr:.2f}{mp_str}{iv_str}"
        return f"Sensibull Status: {self.sensibull_observation.status.value}"

    @property
    def sensibull_summary(self) -> str:
        if not self.sensibull_observation:
            return "Sensibull derivatives option-chain observation was not performed."
        s = self.sensibull_observation
        if s.status == SensibullStatus.AUTHENTICATION_REQUIRED:
            return "Sensibull option chain could not be viewed: user broker login required."
        if s.status == SensibullStatus.OBSERVED:
            strikes_cnt = len(s.strike_information)
            pcr_val = f"{s.pcr:.2f}" if s.pcr is not None else "N/A"
            mp_val = f"{s.max_pain_information:.0f}" if s.max_pain_information is not None else "N/A"
            spot_val = f"{s.spot_reference:.2f}" if s.spot_reference is not None else "N/A"
            return (
                f"Sensibull Option Chain Observed: Spot Ref={spot_val}, PCR={pcr_val}, "
                f"Max Pain={mp_val}, {strikes_cnt} strike(s) visible."
            )
        return f"Sensibull observation incomplete: {s.status.value}."


class AgentObservationContext(BaseModel):
    """
    Complete contextual bundle presented to the reasoning layer.
    """
    latest_market_observation: MarketObservation
    manual_instructions: List[AgentInstruction] = Field(default_factory=list)
    recent_events: List[ObservationEvent] = Field(default_factory=list)
    has_meaningful_change: bool = False
    change_reasons: List[str] = Field(default_factory=list)


class MarketPerceptionOutput(BaseModel):
    """
    Strictly non-trading schema returned by Gemini for market perception.
    Excludes trading execution directives.
    """
    market_regime_description: str = Field(
        description="Factual assessment of the overarching higher-timeframe market regime (e.g. trending up, consolidating in range, volatile expansion)."
    )
    one_hour_structure_description: str = Field(
        description="Objective structural observation on the 1H timeframe (e.g. sequence of higher swing highs and higher lows, proximity to major swing levels)."
    )
    fifteen_minute_structure_description: str = Field(
        description="Tactical price behavior on the 15M timeframe (e.g. pullback into key moving average, consolidation at resistance, rejection wick)."
    )
    notable_levels: List[float] = Field(
        default_factory=list,
        description="Prominent visible numerical price levels, swing highs, swing lows, or round-number inflection zones.",
    )
    recent_changes: List[str] = Field(
        default_factory=list,
        description="Deterministic changes observed between recent candle periods or events.",
    )
    uncertainties: List[str] = Field(
        default_factory=list,
        description="Unknowns, data ambiguities, conflicting signals, or missing information.",
    )
    data_quality_assessment: str = Field(
        description="Evaluation of source data integrity, alignment between visual and numerical data, and data freshness.",
    )
    observation_summary: str = Field(
        description="Concise neutral executive summary of current market conditions."
    )
