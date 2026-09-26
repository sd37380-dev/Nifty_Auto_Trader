"""
Abstract Market Data Provider Interface.

Decouples NIFTY Autonomous Trader from vendor-specific market data feeds.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional
from nifty_trader.market_data.models import Candle, MarketSessionStatus, Timeframe


class MarketDataProvider(ABC):
    """
    Abstract interface for retrieving deterministic numerical OHLCV market data.
    """

    @property
    def name(self) -> str:
        """Name of the data provider."""
        return self.__class__.__name__

    @abstractmethod
    async def get_latest_candle(self, symbol: str, timeframe: Timeframe) -> Optional[Candle]:
        """Returns the most recent completed candle."""
        pass

    @abstractmethod
    async def get_recent_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        count: int = 100,
    ) -> List[Candle]:
        """Returns recent completed candles sorted chronologically."""
        pass

    @abstractmethod
    async def get_historical_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        start_time: datetime,
        end_time: Optional[datetime] = None,
    ) -> List[Candle]:
        """Fetches historical candles between start_time and end_time."""
        pass

    @abstractmethod
    async def get_market_status(self) -> MarketSessionStatus:
        """Determines current market status from exchange schedule."""
        pass

    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """Verifies feed connectivity, latency, and data freshness."""
        pass
