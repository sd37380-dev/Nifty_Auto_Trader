"""
Unit and Look-Ahead Regression Tests for Price Action Research Framework.
Verifies no-look-ahead integrity, candle metrics, and execution invariants.
"""

from datetime import datetime, time, timezone
import numpy as np
import pandas as pd
import pytest

from nifty_trader.strategies.price_validation_strategy import Direction, ExitReason, TransactionCostModel
from research.price_action.data_loader import compute_price_action_features
from research.price_action.engine import (
    HypothesisDefinition,
    run_hypothesis_simulation,
    summarize_trade_metrics,
)
from research.price_action.hypotheses import get_all_hypotheses


def test_no_lookahead_pdh_pdl():
    """Verifies that previous day high and low only use PRIOR days, never the current day."""
    # Day 1: 2024-01-01, High = 20100, Low = 19900
    # Day 2: 2024-01-02, High = 20500, Low = 20050
    dates = []
    times = []
    opens, highs, lows, closes = [], [], [], []
    
    # 2 days of 3 bars each
    for day, h_val, l_val in [(1, 20100.0, 19900.0), (2, 20500.0, 20050.0)]:
        d_str = f"2024-01-0{day}"
        for h, m in [(9, 15), (9, 20), (9, 25)]:
            dates.append(pd.to_datetime(d_str).date())
            times.append(time(h, m))
            opens.append(20000.0)
            highs.append(h_val)
            lows.append(l_val)
            closes.append(20000.0)
            
    df = pd.DataFrame({
        "timestamp": [f"2024-01-0{1 if i < 3 else 2}T03:{45+5*(i%3)}:00+00:00" for i in range(6)],
        "dt_utc": pd.date_range("2024-01-01 03:45", periods=6, freq="5min", tz="UTC"),
        "dt_ist": pd.date_range("2024-01-01 09:15", periods=6, freq="5min", tz="Asia/Kolkata"),
        "date_ist": dates,
        "time_ist": times,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": [1000] * 6,
        "open_interest": [0] * 6,
        "is_valid_ohlc": [True] * 6,
    })
    
    df_feats = compute_price_action_features(df)
    
    # On Day 1 (first 3 bars), PDH and PDL must be NaN (no prior day in dataset)
    assert pd.isna(df_feats.loc[0, 'pdh'])
    assert pd.isna(df_feats.loc[1, 'pdh'])
    assert pd.isna(df_feats.loc[2, 'pdh'])
    
    # On Day 2 (bars 3, 4, 5), PDH must strictly be 20100.0 (Day 1 high) and PDL 19900.0
    # NOT 20500.0 (Day 2 high)!
    for idx in [3, 4, 5]:
        assert df_feats.loc[idx, 'pdh'] == 20100.0
        assert df_feats.loc[idx, 'pdl'] == 19900.0


def test_candle_geometry_features():
    """Verifies body_ratio, close_position, and wick ratios."""
    # Hammer candle: Open 100, High 102, Low 90, Close 101
    # Range = 102 - 90 = 12.0
    # Body = abs(101 - 100) = 1.0 -> Body ratio = 1/12 = 0.0833 (Doji/Pinbar)
    # Lower wick = 100 - 90 = 10.0 -> Lower wick ratio = 10/12 = 0.8333
    # Upper wick = 102 - 101 = 1.0 -> Upper wick ratio = 1/12 = 0.0833
    # Close pos = (101 - 90) / 12 = 11/12 = 0.9167
    df = pd.DataFrame([{
        "timestamp": "2024-01-01T03:45:00+00:00",
        "dt_utc": pd.Timestamp("2024-01-01 03:45:00+00:00"),
        "dt_ist": pd.Timestamp("2024-01-01 09:15:00+05:30"),
        "date_ist": datetime(2024, 1, 1).date(),
        "time_ist": time(9, 15),
        "open": 100.0, "high": 102.0, "low": 90.0, "close": 101.0,
        "volume": 500, "open_interest": 0, "is_valid_ohlc": True
    }])
    df_feats = compute_price_action_features(df)
    row = df_feats.iloc[0]
    
    assert round(row['range'], 2) == 12.0
    assert round(row['lower_wick_ratio'], 3) == round(10.0 / 12.0, 3)
    assert round(row['close_position'], 3) == round(11.0 / 12.0, 3)
    assert row['is_bullish_pinbar'] == True


def test_all_hypotheses_definitions():
    """Verifies that all 12 hypotheses instantiate properly with unique IDs."""
    hyps = get_all_hypotheses()
    assert len(hyps) == 12
    ids = [h.hypothesis_id for h in hyps]
    assert len(ids) == len(set(ids)), "Hypothesis IDs must be strictly unique!"
