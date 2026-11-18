"""
Unit & Regression Tests for Price-Only Long/Short Data Validation Strategy.
Verifies no-look-ahead execution, exact mathematical formulas, and transaction cost logic.
"""

from datetime import datetime, time, timezone
import numpy as np
import pandas as pd
import pytest

from nifty_trader.strategies.price_validation_strategy import (
    BacktestConfig,
    Direction,
    ExitReason,
    TransactionCostModel,
    calculate_performance_metrics,
    calculate_wilder_atr,
    prepare_multi_timeframe_data,
    simulate_strategy,
)


def test_transaction_cost_model():
    """Verifies that transaction costs are computed accurately per regulatory rates."""
    model = TransactionCostModel(lot_size=50, slippage_points_per_side=0.5)
    
    # Buy at 25000, Sell at 25100 (Long win)
    costs = model.calculate_trade_costs(25000.0, 25100.0, Direction.LONG)
    
    # Brokerage: 20 * 2 = 40.0
    assert costs["brokerage"] == 40.0
    
    # Turnover = (25000 * 50) + (25100 * 50) = 1,250,000 + 1,255,000 = 2,505,000
    expected_exchange = round(2505000 * 0.0000173, 2)
    assert costs["exchange_charges"] == expected_exchange
    
    # Stamp duty on buy: 1,250,000 * 0.00002 = 25.0
    assert costs["stamp_duty"] == 25.0
    
    # STT on sell: 1,255,000 * 0.0002 = 251.0
    assert costs["stt"] == 251.0
    
    # Slippage points = 1.0 (0.5 * 2) -> 1.0 * 50 = ₹50
    assert costs["slippage_points"] == 1.0
    assert costs["slippage_cost_inr"] == 50.0


def test_no_lookahead_alignment():
    """
    Verifies that a 5M candle at 09:20 IST does NOT see the 09:15-09:30 15M candle,
    and only sees the completed 15M candle from before 09:15.
    """
    config = BacktestConfig()
    
    # Create synthetic 15M bars
    # Bar 1: 03:30 UTC (09:00 IST) -> closes 03:45 UTC (09:15 IST)
    # Bar 2: 03:45 UTC (09:15 IST) -> closes 04:00 UTC (09:30 IST)
    df_15 = pd.DataFrame([
        {"timestamp": "2024-01-01T03:30:00+00:00", "open": 20000.0, "high": 20050.0, "low": 19990.0, "close": 20040.0},
        {"timestamp": "2024-01-01T03:45:00+00:00", "open": 20040.0, "high": 20150.0, "low": 20030.0, "close": 20140.0},
    ])
    
    # Create synthetic 5M bars
    # Bar 1: 03:45 UTC (09:15 IST) -> closes 03:50 UTC (09:20 IST)
    # Bar 2: 03:50 UTC (09:20 IST) -> closes 03:55 UTC (09:25 IST)
    # Bar 3: 03:55 UTC (09:25 IST) -> closes 04:00 UTC (09:30 IST)
    df_5 = pd.DataFrame([
        {"timestamp": "2024-01-01T03:45:00+00:00", "open": 20040.0, "high": 20060.0, "low": 20030.0, "close": 20050.0},
        {"timestamp": "2024-01-01T03:50:00+00:00", "open": 20050.0, "high": 20080.0, "low": 20045.0, "close": 20070.0},
        {"timestamp": "2024-01-01T03:55:00+00:00", "open": 20070.0, "high": 20140.0, "low": 20065.0, "close": 20140.0},
    ])
    
    merged = prepare_multi_timeframe_data(df_5, df_15, config)
    
    # 5M bar 1 closes at 03:50 UTC. The 15M bar that closed at 04:00 UTC must NOT be visible!
    # It must map to the 15M bar that closed at 03:45 UTC.
    assert merged.loc[0, 'tf15_close_time'] == pd.Timestamp("2024-01-01T03:45:00+00:00")
    assert merged.loc[1, 'tf15_close_time'] == pd.Timestamp("2024-01-01T03:45:00+00:00")
    
    # 5M bar 3 closes at 04:00 UTC. Now the 15M bar that closed at 04:00 UTC is finalized!
    assert merged.loc[2, 'tf15_close_time'] == pd.Timestamp("2024-01-01T04:00:00+00:00")


def test_next_candle_entry_execution():
    """
    Verifies that when a signal occurs on candle k close, entry execution occurs
    strictly on candle k+1 OPEN price, not candle k CLOSE.
    """
    config = BacktestConfig(mode="LONG_ONLY")
    cost_model = TransactionCostModel(slippage_points_per_side=0.0)
    
    # Build minimal synthetic dataset where candle 2 meets all Long criteria
    # and candle 3 opens higher
    df_merged = pd.DataFrame([
        {
            "timestamp": "2024-01-01T03:45:00+00:00",
            "open": 20000.0, "high": 20020.0, "low": 19990.0, "close": 20010.0,
            "dt_ist": pd.Timestamp("2024-01-01 09:15:00+05:30"),
            "time_ist": time(9, 15),
            "date_ist": datetime(2024, 1, 1).date(),
            "ema20": 20005.0,
            "atr14": 20.0,
            "prev_high": 20010.0,
            "prev_low": 19980.0,
            "trend_long_15m": True,
            "trend_short_15m": False,
        },
        {
            # Signal Candle: Pullback Low <= EMA20 (19995 <= 20000), Close >= EMA20 (20002 >= 20000)
            # Distance: 20002 - 20000 = 2.0 <= 20 * 0.25 (5.0) -> Valid!
            # Bullish rejection: Close > Open (20002 > 19998)
            "timestamp": "2024-01-01T03:50:00+00:00",
            "open": 19998.0, "high": 20010.0, "low": 19995.0, "close": 20002.0,
            "dt_ist": pd.Timestamp("2024-01-01 09:20:00+05:30"),
            "time_ist": time(9, 20),
            "date_ist": datetime(2024, 1, 1).date(),
            "ema20": 20000.0,
            "atr14": 20.0,
            "prev_high": 20020.0,
            "prev_low": 19990.0,
            "trend_long_15m": True,
            "trend_short_15m": False,
        },
        {
            # Entry Candle: Opens at 20005.0 (different from previous close 20002.0)
            "timestamp": "2024-01-01T03:55:00+00:00",
            "open": 20005.0, "high": 20050.0, "low": 20004.0, "close": 20045.0,
            "dt_ist": pd.Timestamp("2024-01-01 09:25:00+05:30"),
            "time_ist": time(9, 25),
            "date_ist": datetime(2024, 1, 1).date(),
            "ema20": 20005.0,
            "atr14": 20.0,
            "prev_high": 20010.0,
            "prev_low": 19995.0,
            "trend_long_15m": True,
            "trend_short_15m": False,
        },
    ])
    
    trades, df_trades = simulate_strategy(df_merged, config, cost_model)
    assert len(trades) >= 1
    t0 = trades[0]
    # Entry price must be candle 3 open (20005.0), NOT candle 2 close (20002.0)
    assert t0.entry_price == 20005.0
    # SL = Rejection Low (19995.0) - 5 = 19990.0
    assert t0.sl_price == 19990.0
    # Risk = 20005 - 19990 = 15.0
    assert t0.risk_points == 15.0
    # Target = 20005 + (15 * 2) = 20035.0
    assert t0.target_price == 20035.0
    # Candle 3 High is 20050.0 >= 20035.0, so Target was hit!
    assert t0.exit_reason == ExitReason.TARGET
    assert t0.exit_price == 20035.0
    assert t0.gross_points == 30.0
