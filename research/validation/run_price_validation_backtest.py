"""
Execution Runner for Phase 7 Price-Only Long/Short Data Validation.
Runs:
  A. LONG ONLY
  B. SHORT ONLY
  C. LONG + SHORT
Extracts all required performance and risk statistics, formats the report,
and saves detailed trade logs.
"""

import os
import sys
from datetime import datetime, time, timezone
import json
import sqlite3
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath("."))

from nifty_trader.strategies.price_validation_strategy import (
    BacktestConfig,
    Direction,
    TransactionCostModel,
    calculate_performance_metrics,
    prepare_multi_timeframe_data,
    simulate_strategy,
)


def run_all_tests():
    db_path = 'data/hermes_research/market_data.db'
    conn = sqlite3.connect(db_path)
    
    print("[1/4] Loading historical datasets from SQLite...")
    df_5m = pd.read_sql_query("""
        SELECT bar_id, symbol, timeframe, timestamp, open, high, low, close, volume, open_interest
        FROM normalized_bars
        WHERE symbol = 'NIFTY' AND timeframe = '5M'
        ORDER BY timestamp ASC
    """, conn)
    
    # Exclude microsecond synthetic/test rows from 15M
    df_15m = pd.read_sql_query("""
        SELECT bar_id, symbol, timeframe, timestamp, open, high, low, close, volume, open_interest
        FROM normalized_bars
        WHERE symbol = 'NIFTY' AND timeframe = '15M' AND timestamp NOT LIKE '%.%'
        ORDER BY timestamp ASC
    """, conn)
    conn.close()
    
    print(f"Loaded {len(df_5m)} 5M rows and {len(df_15m)} 15M rows.")
    
    # Data Quality Pre-Checks
    print("[2/4] Conducting pre-backtest data quality checks...")
    # Check invalid OHLC
    invalid_mask = (df_5m['high'] < df_5m['low']) | (df_5m['high'] < df_5m['open']) | (df_5m['high'] < df_5m['close']) | (df_5m['low'] > df_5m['open']) | (df_5m['low'] > df_5m['close'])
    invalid_count = invalid_mask.sum()
    print(f"Detected {invalid_count} invalid OHLC bars in 5M dataset.")
    if invalid_count > 0:
        print("Invalid bars detail:")
        print(df_5m[invalid_mask][['timestamp', 'open', 'high', 'low', 'close']])
    
    cost_model = TransactionCostModel(
        brokerage_per_order=20.0,
        exchange_charge_rate=0.0000173,
        stt_rate_sell=0.0002,
        sebi_charge_rate=0.000001,
        stamp_duty_rate_buy=0.00002,
        gst_rate=0.18,
        slippage_points_per_side=0.5,  # 1.0 point round-trip
        lot_size=50,
    )
    
    # Prepare indicator merged dataframe (zero look-ahead)
    print("[3/4] Preparing multi-timeframe indicators with zero look-ahead alignment...")
    config_base = BacktestConfig(
        ema_fast_15m=20,
        ema_slow_15m=50,
        ema_5m=20,
        atr_period_5m=14,
        atr_distance_mult=0.25,
        sl_buffer_points=5.0,
        risk_reward_ratio=2.0,
        cutoff_time=time(15, 0),
        square_off_time=time(15, 25),
        require_breakout=False,
    )
    df_merged = prepare_multi_timeframe_data(df_5m, df_15m, config_base)
    print(f"Indicator dataframe prepared: {len(df_merged)} rows.")
    
    # ------------------------------------------------------------
    # Run 3 Tests
    # ------------------------------------------------------------
    print("[4/4] Executing Simulations...")
    
    # Test A: LONG ONLY
    print("  -> Running Test A: LONG ONLY...")
    config_long = BacktestConfig(**{**config_base.__dict__, "mode": "LONG_ONLY"})
    trades_long, df_t_long = simulate_strategy(df_merged, config_long, cost_model)
    metrics_long = calculate_performance_metrics(trades_long, df_merged)
    print(f"     Long Only: {metrics_long['total_trades']} trades | Win Rate: {metrics_long['win_rate']}% | Net P&L: {metrics_long['net_points']} pts (INR {metrics_long['net_pnl_inr']}) | PF: {metrics_long['profit_factor']}")
    
    # Test B: SHORT ONLY
    print("  -> Running Test B: SHORT ONLY...")
    config_short = BacktestConfig(**{**config_base.__dict__, "mode": "SHORT_ONLY"})
    trades_short, df_t_short = simulate_strategy(df_merged, config_short, cost_model)
    metrics_short = calculate_performance_metrics(trades_short, df_merged)
    print(f"     Short Only: {metrics_short['total_trades']} trades | Win Rate: {metrics_short['win_rate']}% | Net P&L: {metrics_short['net_points']} pts (INR {metrics_short['net_pnl_inr']}) | PF: {metrics_short['profit_factor']}")
    
    # Test C: LONG + SHORT
    print("  -> Running Test C: LONG + SHORT...")
    config_both = BacktestConfig(**{**config_base.__dict__, "mode": "LONG_AND_SHORT"})
    trades_both, df_t_both = simulate_strategy(df_merged, config_both, cost_model)
    metrics_both = calculate_performance_metrics(trades_both, df_merged)
    print(f"     Long + Short: {metrics_both['total_trades']} trades | Win Rate: {metrics_both['win_rate']}% | Net P&L: {metrics_both['net_points']} pts (INR {metrics_both['net_pnl_inr']}) | PF: {metrics_both['profit_factor']}")
    
    # Also evaluate the optional breakout confirmation for complete objective audit
    print("  -> Running Optional Breakout Confirmation Check (Long + Short)...")
    config_breakout = BacktestConfig(**{**config_base.__dict__, "mode": "LONG_AND_SHORT", "require_breakout": True})
    trades_breakout, df_t_breakout = simulate_strategy(df_merged, config_breakout, cost_model)
    metrics_breakout = calculate_performance_metrics(trades_breakout, df_merged)
    print(f"     With Breakout Conf: {metrics_breakout['total_trades']} trades | Win Rate: {metrics_breakout['win_rate']}% | Net P&L: {metrics_breakout['net_points']} pts | PF: {metrics_breakout['profit_factor']}")
    
    # Save results to JSON for reporting
    results = {
        "dataset_metadata": {
            "table": "normalized_bars",
            "database": "data/hermes_research/market_data.db",
            "symbol": "NIFTY",
            "exchange": "NSE (IDX_I)",
            "instrument_type": "INDEX (Spot)",
            "instrument_id": "13",
            "total_5m_rows": len(df_5m),
            "total_15m_rows_clean": len(df_15m),
            "earliest_timestamp_utc": str(df_5m['timestamp'].min()),
            "latest_timestamp_utc": str(df_5m['timestamp'].max()),
            "timezone": "UTC (converted to Asia/Kolkata IST)",
            "invalid_ohlc_bars": int(invalid_count),
        },
        "test_a_long_only": metrics_long,
        "test_b_short_only": metrics_short,
        "test_c_long_and_short": metrics_both,
        "test_c_with_breakout_confirmation": metrics_breakout,
    }
    
    with open("research/validation/price_validation_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    
    # Export trade logs to CSV for verification
    if not df_t_both.empty:
        df_t_both.to_csv("research/validation/trades_long_and_short.csv", index=False)
    if not df_t_long.empty:
        df_t_long.to_csv("research/validation/trades_long_only.csv", index=False)
    if not df_t_short.empty:
        df_t_short.to_csv("research/validation/trades_short_only.csv", index=False)
        
    print("[DONE] Price validation backtest complete. Results written to JSON & CSV.")
    return results


if __name__ == "__main__":
    run_all_tests()
