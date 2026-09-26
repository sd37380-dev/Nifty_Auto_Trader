"""
Unit tests for Candle and Market Perception Models.
"""

from datetime import datetime, timezone, timedelta
import pytest
from pydantic import ValidationError

from nifty_trader.market_data.models import (
    Candle,
    DataQuality,
    MarketSessionStatus,
    ObservationEvent,
    ObservationEventType,
    Timeframe,
    IST,
)


def test_valid_candle_creation():
    now = datetime(2026, 9, 25, 9, 15, tzinfo=timezone.utc)
    candle = Candle(
        symbol="NIFTY",
        timeframe=Timeframe.H1,
        timestamp=now,
        open=23100.0,
        high=23150.0,
        low=23080.0,
        close=23120.0,
        volume=500000.0,
        is_closed=True,
        source="YAHOO",
    )
    assert candle.symbol == "NIFTY"
    assert candle.timeframe == Timeframe.H1
    assert candle.open == 23100.0
    assert candle.high == 23150.0
    assert candle.low == 23080.0
    assert candle.close == 23120.0
    assert candle.is_closed is True
    # Test IST property
    assert candle.timestamp_ist.tzinfo is not None
    assert candle.timestamp_ist.hour == 14  # 9 UTC + 5:30 = 14:45
    assert candle.timestamp_ist.minute == 45


def test_invalid_ohlc_high_less_than_low():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        Candle(
            symbol="NIFTY",
            timeframe=Timeframe.M15,
            timestamp=now,
            open=23100.0,
            high=23000.0,  # Invalid: high < open/low
            low=23050.0,
            close=23080.0,
        )


def test_invalid_ohlc_high_less_than_open():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        Candle(
            symbol="NIFTY",
            timeframe=Timeframe.M15,
            timestamp=now,
            open=23150.0,
            high=23100.0,  # Invalid: high < open
            low=23050.0,
            close=23080.0,
        )


def test_invalid_ohlc_low_greater_than_close():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        Candle(
            symbol="NIFTY",
            timeframe=Timeframe.M15,
            timestamp=now,
            open=23100.0,
            high=23150.0,
            low=23090.0,  # Invalid: low > close
            close=23050.0,
        )


def test_invalid_negative_price():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        Candle(
            symbol="NIFTY",
            timeframe=Timeframe.M15,
            timestamp=now,
            open=-100.0,
            high=23150.0,
            low=23050.0,
            close=23080.0,
        )


def test_forming_candle_vs_closed():
    now = datetime.now(timezone.utc)
    forming = Candle(
        symbol="NIFTY",
        timeframe=Timeframe.M15,
        timestamp=now,
        open=23100.0,
        high=23120.0,
        low=23090.0,
        close=23110.0,
        is_closed=False,
    )
    assert forming.is_closed is False

    closed = Candle(
        symbol="NIFTY",
        timeframe=Timeframe.M15,
        timestamp=now,
        open=23100.0,
        high=23120.0,
        low=23090.0,
        close=23110.0,
        is_closed=True,
    )
    assert closed.is_closed is True


def test_observation_event_model():
    ev = ObservationEvent(
        event_type=ObservationEventType.CANDLE_CLOSED,
        symbol="NIFTY",
        timeframe=Timeframe.M15,
        message="15M candle completed",
        data={"close": 23140.50},
    )
    assert ev.event_id.startswith("evt_")
    assert ev.event_type == ObservationEventType.CANDLE_CLOSED
    assert ev.timeframe == Timeframe.M15
    assert ev.data["close"] == 23140.50
