"""
TradingView Market Observation Source.

Provides visual chart observations for NIFTY 50 via browser automation.
STRICT INVARIANT: Neutral perception only, no trade signals.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional

from nifty_trader.browser.browser_agent import BrowserAgent
from nifty_trader.browser.models import BrowserObservation
from nifty_trader.observation.models import ObservationSourceType, SourceObservationResult
from nifty_trader.observation.sources.base import IMarketObservationSource

logger = logging.getLogger(__name__)


class TradingViewObservationSource(IMarketObservationSource):
    """
    Pluggable observation source for TradingView charts.
    """

    def __init__(
        self,
        browser_agent: Optional[BrowserAgent] = None,
        enabled: bool = True,
    ):
        self.browser_agent = browser_agent
        self.enabled = enabled

    @property
    def source_id(self) -> str:
        return "tradingview"

    @property
    def source_type(self) -> ObservationSourceType:
        return ObservationSourceType.CHART_VISUAL

    @property
    def capabilities(self) -> List[str]:
        return ["chart", "candlesticks", "timeframe_1h", "timeframe_15m"]

    async def is_available(self) -> bool:
        if not self.enabled:
            return False
        if not self.browser_agent:
            return False
        return True

    async def observe(self, symbol: str = "NIFTY", timeframe: str = "1h", **kwargs) -> SourceObservationResult:
        now = datetime.now(timezone.utc)
        if not self.enabled or not self.browser_agent:
            return SourceObservationResult(
                source_id=self.source_id,
                source_type=self.source_type,
                success=False,
                status="UNAVAILABLE",
                timestamp=now,
                warnings=["TradingView observation source is disabled or browser agent is unavailable."],
            )

        try:
            logger.info("Executing TradingView observation for %s (timeframe=%s)...", symbol, timeframe)
            obs: BrowserObservation = await self.browser_agent.inspect_tradingview_nifty(timeframe=timeframe)
            return SourceObservationResult(
                source_id=self.source_id,
                source_type=self.source_type,
                success=True,
                status="OBSERVED",
                timestamp=now,
                data=obs.model_dump(),
                warnings=obs.warnings,
                errors=obs.errors,
            )
        except Exception as e:
            logger.warning("TradingView observation failed: %s", e)
            return SourceObservationResult(
                source_id=self.source_id,
                source_type=self.source_type,
                success=False,
                status="ERROR",
                timestamp=now,
                errors=[str(e)],
            )
