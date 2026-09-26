"""
Numerical Market Data Observation Source.

Provides authoritative numerical OHLCV candlestick data across 1H and 15M timeframes.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional

from nifty_trader.market_data.base import MarketDataProvider
from nifty_trader.market_data.cache import MarketDataCache
from nifty_trader.market_data.models import Timeframe
from nifty_trader.observation.models import ObservationSourceType, SourceObservationResult
from nifty_trader.observation.sources.base import IMarketObservationSource

logger = logging.getLogger(__name__)


class NumericalMarketDataSource(IMarketObservationSource):
    """
    Pluggable observation source for authoritative numerical OHLCV feeds.
    """

    def __init__(
        self,
        provider: MarketDataProvider,
        cache: Optional[MarketDataCache] = None,
        enabled: bool = True,
    ):
        self.provider = provider
        self.cache = cache or MarketDataCache()
        self.enabled = enabled

    @property
    def source_id(self) -> str:
        return "numerical"

    @property
    def source_type(self) -> ObservationSourceType:
        return ObservationSourceType.NUMERICAL

    @property
    def capabilities(self) -> List[str]:
        return ["ohlcv", "multi_timeframe", "1h_candles", "15m_candles", "session_status"]

    async def is_available(self) -> bool:
        return self.enabled

    async def observe(self, symbol: str = "NIFTY", **kwargs) -> SourceObservationResult:
        now = datetime.now(timezone.utc)
        if not self.enabled:
            return SourceObservationResult(
                source_id=self.source_id,
                source_type=self.source_type,
                success=False,
                status="DISABLED",
                timestamp=now,
                warnings=["Numerical data source is disabled."],
            )

        try:
            h1 = self.cache.get_candles(symbol=symbol, timeframe=Timeframe.H1, limit=30, only_closed=True)
            m15 = self.cache.get_candles(symbol=symbol, timeframe=Timeframe.M15, limit=50, only_closed=True)
            session = await self.provider.get_market_status()

            latest_close = m15[-1].close if m15 else (h1[-1].close if h1 else None)

            return SourceObservationResult(
                source_id=self.source_id,
                source_type=self.source_type,
                success=True,
                status="OBSERVED",
                timestamp=now,
                data={
                    "symbol": symbol,
                    "session_status": session.value,
                    "latest_close": latest_close,
                    "cached_1h_count": len(h1),
                    "cached_15m_count": len(m15),
                },
            )
        except Exception as e:
            logger.warning("Numerical observation failed: %s", e)
            return SourceObservationResult(
                source_id=self.source_id,
                source_type=self.source_type,
                success=False,
                status="ERROR",
                timestamp=now,
                errors=[str(e)],
            )
