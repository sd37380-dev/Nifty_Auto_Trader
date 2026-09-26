"""
Yahoo Finance Market Data Provider.

Fetches 1H and 15M NIFTY 50 candles from Yahoo Finance v8 chart API.
"""

from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, List, Optional
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from nifty_trader.market_data.base import MarketDataProvider
from nifty_trader.market_data.models import Candle, MarketSessionStatus, Timeframe

logger = logging.getLogger(__name__)


class YahooFinanceProvider(MarketDataProvider):
    """
    Market data provider accessing Yahoo Finance v8 chart endpoints for NIFTY (^NSEI).
    """

    TICKER_MAP = {
        "NIFTY": "^NSEI",
        "NIFTY50": "^NSEI",
    }

    TIMEFRAME_MAP = {
        Timeframe.H1: "1h",
        Timeframe.M15: "15m",
    }

    TIMEFRAME_DURATIONS = {
        Timeframe.H1: timedelta(hours=1),
        Timeframe.M15: timedelta(minutes=15),
    }

    def __init__(self, timeout_seconds: float = 10.0):
        self.timeout = timeout_seconds
        self.base_url = "https://query1.finance.yahoo.com/v8/finance/chart"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

    def _resolve_ticker(self, symbol: str) -> str:
        return self.TICKER_MAP.get(symbol.upper(), symbol)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4))
    async def _fetch_chart_data(self, ticker: str, interval: str, range_str: Optional[str] = None, period1: Optional[int] = None, period2: Optional[int] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {"interval": interval}
        if period1 and period2:
            params["period1"] = period1
            params["period2"] = period2
        elif range_str:
            params["range"] = range_str
        else:
            params["range"] = "5d"

        url = f"{self.base_url}/{ticker}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url, params=params, headers=self.headers)
            resp.raise_for_status()
            data = resp.json()

        result = data.get("chart", {}).get("result")
        if not result or len(result) == 0:
            raise ValueError(f"No chart data returned for {ticker}: {data.get('chart', {}).get('error')}")

        return result[0]

    def _parse_candles(self, raw_result: Dict[str, Any], symbol: str, timeframe: Timeframe) -> List[Candle]:
        timestamps = raw_result.get("timestamp", [])
        quote = raw_result.get("indicators", {}).get("quote", [{}])[0]

        opens = quote.get("open", [])
        highs = quote.get("high", [])
        lows = quote.get("low", [])
        closes = quote.get("close", [])
        volumes = quote.get("volume", [])

        candles: List[Candle] = []
        now_utc = datetime.now(timezone.utc)
        duration = self.TIMEFRAME_DURATIONS[timeframe]

        for i, ts in enumerate(timestamps):
            o = opens[i] if i < len(opens) else None
            h = highs[i] if i < len(highs) else None
            l = lows[i] if i < len(lows) else None
            c = closes[i] if i < len(closes) else None
            v = volumes[i] if i < len(volumes) else None

            # Skip nulls or empty candles
            if o is None or h is None or l is None or c is None:
                continue

            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            # Candle is closed if the current time has passed its start time + duration
            is_closed = now_utc >= (dt + duration)

            try:
                candle = Candle(
                    symbol=symbol,
                    timeframe=timeframe,
                    timestamp=dt,
                    open=round(float(o), 2),
                    high=round(float(h), 2),
                    low=round(float(l), 2),
                    close=round(float(c), 2),
                    volume=round(float(v), 2) if v is not None else None,
                    is_closed=is_closed,
                    source="yahoo",
                )
                candles.append(candle)
            except Exception as e:
                logger.warning("Skipping invalid candle at %s: %s", dt, e)

        return sorted(candles, key=lambda c: c.timestamp)

    async def get_latest_candle(self, symbol: str, timeframe: Timeframe) -> Optional[Candle]:
        candles = await self.get_recent_candles(symbol=symbol, timeframe=timeframe, count=5)
        # Filter for completed candles
        closed_candles = [c for c in candles if c.is_closed]
        return closed_candles[-1] if closed_candles else None

    async def get_recent_candles(self, symbol: str, timeframe: Timeframe, count: int = 100) -> List[Candle]:
        ticker = self._resolve_ticker(symbol)
        interval = self.TIMEFRAME_MAP[timeframe]
        range_str = "1mo" if timeframe == Timeframe.H1 else "5d"

        try:
            raw = await self._fetch_chart_data(ticker=ticker, interval=interval, range_str=range_str)
            candles = self._parse_candles(raw, symbol=symbol, timeframe=timeframe)
            return candles[-count:]
        except Exception as e:
            logger.error("Failed to fetch recent %s candles for %s: %s", timeframe.value, symbol, e)
            return []

    async def get_historical_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        start_time: datetime,
        end_time: Optional[datetime] = None,
    ) -> List[Candle]:
        ticker = self._resolve_ticker(symbol)
        interval = self.TIMEFRAME_MAP[timeframe]
        p1 = int(start_time.timestamp())
        p2 = int((end_time or datetime.now(timezone.utc)).timestamp())

        try:
            raw = await self._fetch_chart_data(ticker=ticker, interval=interval, period1=p1, period2=p2)
            candles = self._parse_candles(raw, symbol=symbol, timeframe=timeframe)
            return [c for c in candles if start_time <= c.timestamp <= (end_time or datetime.now(timezone.utc))]
        except Exception as e:
            logger.error("Failed to fetch historical %s candles for %s: %s", timeframe.value, symbol, e)
            return []

    async def get_market_status(self) -> MarketSessionStatus:
        from nifty_trader.market_data.session import MarketSessionManager
        return MarketSessionManager.get_current_session_status()

    async def health_check(self) -> Dict[str, Any]:
        ticker = self._resolve_ticker("NIFTY")
        try:
            raw = await self._fetch_chart_data(ticker=ticker, interval="1h", range_str="1d")
            return {
                "provider": "YahooFinanceProvider",
                "is_healthy": True,
                "ticker": ticker,
                "regular_market_price": raw.get("meta", {}).get("regularMarketPrice"),
                "status": "ONLINE",
            }
        except Exception as e:
            return {
                "provider": "YahooFinanceProvider",
                "is_healthy": False,
                "error": str(e),
                "status": "OFFLINE",
            }
