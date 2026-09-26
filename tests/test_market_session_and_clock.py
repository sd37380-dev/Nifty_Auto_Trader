"""
Unit tests for MarketSessionManager and CandleClock.
"""

from datetime import datetime, timezone, timedelta
import pytest

from nifty_trader.market_data.clock import CandleClock
from nifty_trader.market_data.models import IST, MarketSessionStatus, Timeframe
from nifty_trader.market_data.session import MarketSessionManager


def test_session_manager_weekday_open():
    # Friday 11:30 AM IST -> Regular session OPEN
    # 11:30 IST is 06:00 UTC
    dt_utc = datetime(2026, 9, 25, 6, 0, tzinfo=timezone.utc)
    status = MarketSessionManager.get_current_session_status(dt_utc)
    assert status == MarketSessionStatus.OPEN
    assert MarketSessionManager.is_market_open(dt_utc) is True


def test_session_manager_pre_market():
    # Friday 09:05 AM IST -> PRE_MARKET
    # 09:05 IST is 03:35 UTC
    dt_utc = datetime(2026, 9, 25, 3, 35, tzinfo=timezone.utc)
    status = MarketSessionManager.get_current_session_status(dt_utc)
    assert status == MarketSessionStatus.PRE_MARKET
    assert MarketSessionManager.is_market_open(dt_utc) is False


def test_session_manager_post_market():
    # Friday 15:45 IST -> POST_MARKET
    # 15:45 IST is 10:15 UTC
    dt_utc = datetime(2026, 9, 25, 10, 15, tzinfo=timezone.utc)
    status = MarketSessionManager.get_current_session_status(dt_utc)
    assert status == MarketSessionStatus.POST_MARKET
    assert MarketSessionManager.is_market_open(dt_utc) is False


def test_session_manager_night_closed():
    # Friday 21:00 IST -> CLOSED
    # 21:00 IST is 15:30 UTC
    dt_utc = datetime(2026, 9, 25, 15, 30, tzinfo=timezone.utc)
    status = MarketSessionManager.get_current_session_status(dt_utc)
    assert status == MarketSessionStatus.CLOSED


def test_session_manager_weekend_closed():
    # Saturday 12:00 PM IST -> CLOSED
    dt_utc = datetime(2026, 9, 26, 6, 30, tzinfo=timezone.utc)
    status = MarketSessionManager.get_current_session_status(dt_utc)
    assert status == MarketSessionStatus.CLOSED
    assert MarketSessionManager.is_market_open(dt_utc) is False


def test_candle_clock_is_candle_closed():
    clock = CandleClock()
    candle_ts = datetime(2026, 9, 25, 6, 0, tzinfo=timezone.utc)  # 11:30 IST

    # Current time is 11:40 IST (10 mins after 15M candle open) -> not closed yet
    cur_time_before = datetime(2026, 9, 25, 6, 10, tzinfo=timezone.utc)
    assert clock.is_candle_closed(candle_ts, Timeframe.M15, current_time=cur_time_before) is False

    # Current time is 11:45 IST (exact 15M close) -> closed
    cur_time_at_close = datetime(2026, 9, 25, 6, 15, tzinfo=timezone.utc)
    assert clock.is_candle_closed(candle_ts, Timeframe.M15, current_time=cur_time_at_close) is True


def test_candle_clock_next_candle_close():
    clock = CandleClock()
    # 11:20 IST (05:50 UTC)
    ref_dt = datetime(2026, 9, 25, 5, 50, tzinfo=timezone.utc)

    # Next 15M close should be 11:30 IST (06:00 UTC)
    next_15m = clock.get_next_candle_close(Timeframe.M15, current_time=ref_dt)
    assert next_15m.minute in [0, 15, 30, 45]
    assert next_15m > ref_dt

    # Next 1H close should be 12:00 IST (06:30 UTC)
    next_1h = clock.get_next_candle_close(Timeframe.H1, current_time=ref_dt)
    assert next_1h > ref_dt
