"""
Unit tests for Market Data Providers (Mock & Yahoo).
"""

from datetime import datetime, timezone, timedelta
import pytest

from nifty_trader.market_data.models import Candle, MarketSessionStatus, Timeframe
from nifty_trader.market_data.providers.mock import MockMarketDataProvider
from nifty_trader.market_data.providers.yahoo import YahooFinanceProvider


@pytest.mark.asyncio
async def test_mock_provider_synthetic_series():
    provider = MockMarketDataProvider(base_price=23140.50)
    series_15m = provider.generate_synthetic_series(symbol="NIFTY", timeframe=Timeframe.M15, count=20)
    assert len(series_15m) == 20
    assert all(isinstance(c, Candle) for c in series_15m)
    assert all(c.timeframe == Timeframe.M15 for c in series_15m)
    assert all(c.is_closed for c in series_15m[:-1])

    series_1h = provider.generate_synthetic_series(symbol="NIFTY", timeframe=Timeframe.H1, count=10)
    assert len(series_1h) == 10
    assert all(c.timeframe == Timeframe.H1 for c in series_1h)


@pytest.mark.asyncio
async def test_mock_provider_fetch_recent_and_latest():
    provider = MockMarketDataProvider(base_price=23000.0)
    candles = await provider.get_recent_candles(symbol="NIFTY", timeframe=Timeframe.M15, count=25)
    assert len(candles) == 25

    latest = await provider.get_latest_candle(symbol="NIFTY", timeframe=Timeframe.M15)
    assert latest is not None
    assert latest.close == candles[-1].close


@pytest.mark.asyncio
async def test_mock_provider_historical_filter():
    provider = MockMarketDataProvider(base_price=23000.0)
    start_time = datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)
    provider.generate_synthetic_series(symbol="NIFTY", timeframe=Timeframe.H1, count=30, start_time=start_time)

    filter_start = start_time + timedelta(hours=5)
    filter_end = start_time + timedelta(hours=15)
    filtered = await provider.get_historical_candles(
        symbol="NIFTY",
        timeframe=Timeframe.H1,
        start_time=filter_start,
        end_time=filter_end,
    )
    assert len(filtered) > 0
    assert all(filter_start <= c.timestamp <= filter_end for c in filtered)


@pytest.mark.asyncio
async def test_mock_provider_health_check():
    provider = MockMarketDataProvider()
    health = await provider.health_check()
    assert health["status"] == "ONLINE"
    assert health["is_healthy"] is True
    assert health["provider"] == "MockMarketDataProvider"

    # Simulate failure
    provider.set_simulate_failure(True)
    health_fail = await provider.health_check()
    assert health_fail["status"] == "OFFLINE"
    assert health_fail["is_healthy"] is False


def test_yahoo_provider_timeframe_mapping():
    provider = YahooFinanceProvider()
    assert provider.name == "YahooFinanceProvider"
    assert provider.TIMEFRAME_MAP[Timeframe.H1] == "1h"
    assert provider.TIMEFRAME_MAP[Timeframe.M15] == "15m"
    assert provider.TICKER_MAP["NIFTY"] == "^NSEI"
