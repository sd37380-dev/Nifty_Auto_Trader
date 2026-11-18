"""
Test Directional Strategies under Regime Filters (Low Vol, High Vol, Trend Alignment)
To objectively verify whether ANY directional strategy can reach >=60% Win Rate.
"""

import sys
from pathlib import Path
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import pandas as pd
import numpy as np
from research.candidate_discovery.hypothesis_search import load_dataset_split, run_backtest_simulation

def test_directional_regimes():
    train_df, val_df, oos_df = load_dataset_split()
    
    # Test across Train, Val, OOS for:
    # 1. ORB + 200 EMA
    # 2. PDH/PDL Sweep Reversal
    # 3. 20 EMA Pullback
    # 4. CPR / EMA14
    for split_name, df in [("Train (2021-2024)", train_df), ("Validation (2025)", val_df), ("OOS (2026)", oos_df)]:
        print(f"\n=== {split_name} Directional Evaluation ===")
        # ORB
        f30_h = df.groupby('date')['high'].transform(lambda x: x.iloc[:2].max() if len(x) >= 2 else np.nan)
        f30_l = df.groupby('date')['low'].transform(lambda x: x.iloc[:2].min() if len(x) >= 2 else np.nan)
        h1_l = (df['close'] > f30_h) & (df['close'].shift(1) <= f30_h) & (df['close'] > df['ema_200']) & ('09:45' <= df['time_str']) & (df['time_str'] <= '11:15')
        h1_s = (df['close'] < f30_l) & (df['close'].shift(1) >= f30_l) & (df['close'] < df['ema_200']) & ('09:45' <= df['time_str']) & (df['time_str'] <= '11:15')
        r1 = run_backtest_simulation(df, h1_l, h1_s, "H1_ORB", "09:45 ORB + 200 EMA (1:2 R:R)", sl_points=35.0, tp_points=70.0)

        # PDH Sweep
        h2_l = (df['low'] < df['pdl']) & (df['close'] > df['pdl']) & (df['pdl'] - df['low'] <= 40.0) & (df['close'] > df['open'])
        h2_s = (df['high'] > df['pdh']) & (df['close'] < df['pdh']) & (df['high'] - df['pdh'] <= 40.0) & (df['close'] < df['open'])
        r2 = run_backtest_simulation(df, h2_l, h2_s, "H2_SWEEP", "PDH/PDL Sweep (1:1.4 R:R)", sl_points=25.0, tp_points=35.0)

        # CPR Rebound EMA 14
        s_levels = [df['s1'], df['s2'], df['cpr_bot']]
        r_levels = [df['r1'], df['r2'], df['cpr_top']]
        conds_s = [(abs(df['low'] - s) <= 20.0) | ((df['low'] < s) & (df['close'] > s)) for s in s_levels]
        near_s = conds_s[0] | conds_s[1] | conds_s[2]
        conds_r = [(abs(df['high'] - r) <= 20.0) | ((df['high'] > r) & (df['close'] < r)) for r in r_levels]
        near_r = conds_r[0] | conds_r[1] | conds_r[2]
        h8_l = near_s & (df['close'] > df['ema_14']) & (df['close'] > df['open'])
        h8_s = near_r & (df['close'] < df['ema_14']) & (df['close'] < df['open'])
        r8 = run_backtest_simulation(df, h8_l, h8_s, "H8_CPR_EMA14", "CPR Rebound + EMA 14 (1:3 R:R)", sl_points=28.0, tp_points=84.0)

        for r in [r1, r2, r8]:
            print(f"  {r['name']:<35} | Trades: {r['trades']:<4} | Win Rate: {r['win_rate']:>5.1f}% | PF: {r['profit_factor']:>5.2f} | Net: {r['net_pts']:>+8.1f} pts")

if __name__ == "__main__":
    test_directional_regimes()
