"""
Unit and Integration Tests for Volume Candlestick Engine and Signal Detector.
"""

from datetime import datetime, timedelta, timezone
import numpy as np
import pandas as pd
import pytest

from nifty_trader.features.volume_candles import VolumeBar, VolumeBarAggregator
from nifty_trader.features.volume_signals import VolumePatternDetector
from nifty_trader.research_zone.contracts import NormalizedBar
from nifty_trader.research_zone.data_engineering import DataEngineeringZone
from nifty_trader.strategies.custom_strategies.volume_candle_daytrader import generate_signals


def _create_synthetic_bars(count: int = 100, base_price: float = 24500.0, base_volume: int = 250):
    """Creates deterministic synthetic NormalizedBars."""
    bars = []
    curr_time = datetime(2026, 11, 20, 9, 15, tzinfo=timezone.utc)
    price = base_price

    for i in range(count):
        drift = float(np.sin(i / 5.0) * 10.0)
        open_p = price
        high_p = price + 15.0 + abs(drift)
        low_p = price - 12.0 - abs(drift)
        close_p = price + drift
        vol = base_volume if (i % 10 != 0) else base_volume * 4  # occasional volume spike

        bars.append(
            NormalizedBar(
                symbol="NIFTY",
                timeframe="1M",
                timestamp=curr_time + timedelta(minutes=i),
                open=round(open_p, 2),
                high=round(high_p, 2),
                low=round(low_p, 2),
                close=round(close_p, 2),
                volume=int(vol),
                open_interest=500000 + i * 100,
                vwap=round((open_p + high_p + low_p + close_p) / 4.0, 2),
                trades_count=max(10, int(vol / 5)),
            )
        )
        price = close_p

    return bars


def test_volume_bar_aggregation():
    """Verify constant-volume bar generation and invariant conservation."""
    bars = _create_synthetic_bars(count=50, base_volume=500)
    total_raw_volume = sum(b.volume for b in bars)

    target_vol = 2000
    aggregator = VolumeBarAggregator(default_target_volume=target_vol)
    vbars = aggregator.aggregate_from_normalized_bars(bars, target_volume=target_vol, slice_overflow=True)

    assert len(vbars) > 0

    # Invariants check on each VolumeBar
    for vb in vbars:
        assert vb.target_volume == target_vol
        assert vb.high >= vb.low
        assert vb.high >= min(vb.open, vb.close)
        assert vb.low <= max(vb.open, vb.close)
        assert vb.vwap > 0
        assert vb.trades_count > 0
        assert vb.duration_seconds >= 0

    # Volume conservation
    total_vbar_volume = sum(vb.volume for vb in vbars)
    assert abs(total_vbar_volume - total_raw_volume) < 1.0


def test_volume_bar_dataframe_resampling():
    """Verify DataFrame-level volume aggregation."""
    bars = _create_synthetic_bars(count=30, base_volume=600)
    df_raw = pd.DataFrame([
        {
            "timestamp": b.timestamp,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
            "open_interest": b.open_interest,
        }
        for b in bars
    ])

    aggregator = VolumeBarAggregator()
    vdf = aggregator.aggregate_from_dataframe(df_raw, target_volume=3000)

    assert not vdf.empty
    assert "timestamp" in vdf.columns
    assert "vwap" in vdf.columns
    assert "duration_seconds" in vdf.columns
    assert (vdf["high"] >= vdf["low"]).all()


def test_volume_pattern_detector():
    """Verify VPA metric calculations and breakout/absorption signals."""
    detector = VolumePatternDetector(vol_ma_period=5, rvol_threshold=1.5, atr_period=5)

    # Construct test DataFrame with a deliberate breakout and absorption bar
    data = []
    base_ts = datetime(2026, 11, 20, 9, 15, tzinfo=timezone.utc)
    for i in range(15):
        data.append({
            "timestamp": base_ts + timedelta(minutes=i),
            "open": 24000.0 + i * 2,
            "high": 24010.0 + i * 2,
            "low": 23995.0 + i * 2,
            "close": 24005.0 + i * 2,
            "volume": 1000,
        })

    # Bar 15: Strong High-Volume Bullish Breakout
    data.append({
        "timestamp": base_ts + timedelta(minutes=15),
        "open": 24040.0,
        "high": 24100.0,
        "low": 24038.0,
        "close": 24098.0,  # Closes near high
        "volume": 5000,     # RVOL >> 2.0
    })

    # Bar 16: Bearish Absorption (Heavy volume, huge upper wick rejection)
    data.append({
        "timestamp": base_ts + timedelta(minutes=16),
        "open": 24095.0,
        "high": 24150.0,
        "low": 24090.0,
        "close": 24092.0,  # Closes near low despite spike
        "volume": 6000,
    })

    df = pd.DataFrame(data)
    signals_df = detector.detect_signals(df)

    assert "rvol" in signals_df.columns
    assert "clv" in signals_df.columns
    assert "vol_breakout_long" in signals_df.columns
    assert "vol_absorption_short" in signals_df.columns

    # Bar 15 should trigger long breakout
    assert bool(signals_df.iloc[15]["vol_breakout_long"]) is True
    # Bar 16 should trigger short absorption
    assert bool(signals_df.iloc[16]["vol_absorption_short"]) is True


def test_custom_strategy_generate_signals():
    """Verify integration of volume_candle_daytrader with backtester interface."""
    bars = _create_synthetic_bars(count=40, base_volume=1000)
    df = pd.DataFrame([
        {
            "timestamp": b.timestamp,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
        }
        for b in bars
    ])

    params = {
        "rvol_threshold": 1.5,
        "vol_ma_period": 10,
        "atr_period": 10,
    }

    res_df, overlays = generate_signals(df, params)

    assert "long_condition" in res_df.columns
    assert "short_condition" in res_df.columns
    assert isinstance(res_df["long_condition"].iloc[0], (bool, np.bool_))
    assert "EMA 20" in overlays
    assert "VWMA 20" in overlays


def test_data_engineering_resample_to_volume_bars():
    """Verify DataEngineeringZone integration."""
    de = DataEngineeringZone()
    bars = _create_synthetic_bars(count=20, base_volume=800)
    vbars = de.resample_to_volume_bars(bars, target_volume=2400)

    assert len(vbars) > 0
    assert all(isinstance(v, VolumeBar) for v in vbars)
