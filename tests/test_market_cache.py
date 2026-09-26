"""
Unit tests for MarketDataCache SQLite Engine.
"""

from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
import pytest

from nifty_trader.market_data.cache import MarketDataCache
from nifty_trader.market_data.models import Candle, Timeframe


@pytest.fixture
def temp_cache(tmp_path):
    db_path = tmp_path / "test_market_cache.db"
    cache = MarketDataCache(db_path=db_path)
    return cache


def test_cache_initial_empty_stats(temp_cache):
    stats = temp_cache.get_stats("NIFTY")
    assert stats[Timeframe.H1] == 0
    assert stats[Timeframe.M15] == 0
    assert temp_cache.get_latest_timestamp("NIFTY", Timeframe.H1) is None


def test_cache_store_and_retrieve_candles(temp_cache):
    now = datetime(2026, 9, 25, 9, 15, tzinfo=timezone.utc)
    candles = [
        Candle(
            symbol="NIFTY",
            timeframe=Timeframe.M15,
            timestamp=now + timedelta(minutes=15 * i),
            open=23100.0 + i,
            high=23110.0 + i,
            low=23090.0 + i,
            close=23105.0 + i,
            volume=1000.0,
            is_closed=True,
        )
        for i in range(10)
    ]

    stored = temp_cache.store_candles(candles)
    assert stored == 10

    stats = temp_cache.get_stats("NIFTY")
    assert stats[Timeframe.M15] == 10
    assert stats[Timeframe.H1] == 0

    # Retrieve candles
    retrieved = temp_cache.get_candles("NIFTY", Timeframe.M15, limit=5)
    assert len(retrieved) == 5
    # Should be in ascending chronological order
    assert retrieved[0].timestamp < retrieved[-1].timestamp
    assert retrieved[-1].close == candles[-1].close


def test_cache_duplicate_prevention_and_update(temp_cache):
    now = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)
    candle1 = Candle(
        symbol="NIFTY",
        timeframe=Timeframe.H1,
        timestamp=now,
        open=23100.0,
        high=23120.0,
        low=23080.0,
        close=23110.0,
        is_closed=False,
    )
    temp_cache.store_candles([candle1])
    assert temp_cache.get_candle_count("NIFTY", Timeframe.H1) == 1

    # Update forming candle to closed with new close
    candle1_updated = Candle(
        symbol="NIFTY",
        timeframe=Timeframe.H1,
        timestamp=now,
        open=23100.0,
        high=23150.0,
        low=23080.0,
        close=23145.0,
        is_closed=True,
    )
    temp_cache.store_candles([candle1_updated])

    # Count must remain 1 (no duplicate insertion)
    assert temp_cache.get_candle_count("NIFTY", Timeframe.H1) == 1
    candles = temp_cache.get_candles("NIFTY", Timeframe.H1, limit=1)
    assert len(candles) == 1
    assert candles[0].close == 23145.0
    assert candles[0].is_closed is True


def test_cache_latest_timestamp_only_closed(temp_cache):
    now = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)
    c_closed = Candle(
        symbol="NIFTY",
        timeframe=Timeframe.H1,
        timestamp=now,
        open=23100.0,
        high=23120.0,
        low=23080.0,
        close=23110.0,
        is_closed=True,
    )
    c_forming = Candle(
        symbol="NIFTY",
        timeframe=Timeframe.H1,
        timestamp=now + timedelta(hours=1),
        open=23110.0,
        high=23130.0,
        low=23100.0,
        close=23125.0,
        is_closed=False,
    )
    temp_cache.store_candles([c_closed, c_forming])

    # latest_timestamp should be the closed candle's timestamp
    latest_ts = temp_cache.get_latest_timestamp("NIFTY", Timeframe.H1)
    assert latest_ts == now
