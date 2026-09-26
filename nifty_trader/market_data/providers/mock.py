"""
Mock Market Data Provider for Deterministic Offline Testing.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from nifty_trader.market_data.base import MarketDataProvider
from nifty_trader.market_data.models import Candle, MarketSessionStatus, Timeframe


class MockMarketDataProvider(MarketDataProvider):
    """
    Deterministic in-memory market data provider for unit testing.
    """

    def __init__(self, base_price: float = 23140.50):
        self.base_price = base_price
        self._custom_candles: Dict[str, List[Candle]] = {}
        self._simulate_failure = False
        self._forced_market_status = MarketSessionStatus.OPEN

    def set_forced_market_status(self, status: MarketSessionStatus) -> None:
        self._forced_market_status = status

    def set_simulate_failure(self, fail: bool) -> None:
        self._simulate_failure = fail

    def load_candles(self, timeframe: Timeframe, candles: List[Candle]) -> None:
        self._custom_candles[timeframe.value] = sorted(candles, key=lambda c: c.timestamp)

    def generate_synthetic_series(
        self,
        symbol: str = "NIFTY",
        timeframe: Timeframe = Timeframe.M15,
        count: int = 50,
        start_time: Optional[datetime] = None,
    ) -> List[Candle]:
        """Generates realistic synthetic test candles."""
        duration = timedelta(hours=1) if timeframe == Timeframe.H1 else timedelta(minutes=15)
        start = start_time or (datetime.now(timezone.utc) - (duration * count))

        candles = []
        cur_price = self.base_price

        for i in range(count):
            t = start + (duration * i)
            o = cur_price
            h = o + 25.0
            l = o - 20.0
            c = o + 10.0
            cur_price = c

            candle = Candle(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=t,
                open=round(o, 2),
                high=round(h, 2),
                low=round(l, 2),
                close=round(c, 2),
                volume=150000.0,
                is_closed=True,
                source="mock",
            )
            candles.append(candle)

        self._custom_candles[timeframe.value] = candles
        return candles

    async def get_latest_candle(self, symbol: str, timeframe: Timeframe) -> Optional[Candle]:
        if self._simulate_failure:
            raise ConnectionError("Mock provider connection failed")

        candles = self._custom_candles.get(timeframe.value)
        if not candles:
            candles = self.generate_synthetic_series(symbol=symbol, timeframe=timeframe, count=10)

        closed = [c for c in candles if c.is_closed]
        return closed[-1] if closed else None

    async def get_recent_candles(self, symbol: str, timeframe: Timeframe, count: int = 100) -> List[Candle]:
        if self._simulate_failure:
            raise ConnectionError("Mock provider connection failed")

        candles = self._custom_candles.get(timeframe.value)
        if not candles:
            candles = self.generate_synthetic_series(symbol=symbol, timeframe=timeframe, count=count)

        return candles[-count:]

    async def get_historical_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        start_time: datetime,
        end_time: Optional[datetime] = None,
    ) -> List[Candle]:
        if self._simulate_failure:
            raise ConnectionError("Mock provider connection failed")

        candles = self._custom_candles.get(timeframe.value)
        if not candles:
            candles = self.generate_synthetic_series(symbol=symbol, timeframe=timeframe, count=50, start_time=start_time)

        end = end_time or datetime.now(timezone.utc)
        return [c for c in candles if start_time <= c.timestamp <= end]

    async def get_market_status(self) -> MarketSessionStatus:
        return self._forced_market_status

    async def health_check(self) -> Dict[str, Any]:
        return {
            "provider": "MockMarketDataProvider",
            "is_healthy": not self._simulate_failure,
            "status": "ONLINE" if not self._simulate_failure else "OFFLINE",
        }
