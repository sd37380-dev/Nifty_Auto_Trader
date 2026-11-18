"""
Test Regime-Filtered Theta Spread across Train, Validation, and OOS.
Hypothesis: By skipping high ATR or high gap days, can the strategy maintain >60% Win Rate AND PF > 1.2 across ALL splits?
"""

import sys
from pathlib import Path
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import pandas as pd
import numpy as np
from research.validation.validate_candidate import load_full_dataset, simulate_theta_spread

def test_regime_filters():
    _, daily = load_full_dataset()
    train_daily = daily[daily['year'] <= 2024].copy()
    val_daily = daily[daily['year'] == 2025].copy()
    oos_daily = daily[daily['year'] >= 2026].copy()

    thresholds = [180.0, 200.0, 220.0, 240.0]
    strikes = [150.0, 160.0, 180.0]
    
    print("Testing Regime Filters across Splits:")
    print(f"{'Strike':<7} | {'ATR Max':<8} | {'Split':<12} | {'Trades':<6} | {'Win %':<6} | {'PF':<5} | {'Net Pts':<9}")
    print("-" * 65)

    for st in strikes:
        for atr_max in thresholds:
            for split_name, split_df in [("Train", train_daily), ("Validation", val_daily), ("OOS-2026", oos_daily)]:
                res = simulate_theta_spread(split_df, strike_distance=st, stop_loss_pts=50.0, target_premium=32.0, cost_pts=3.0, trend_filter_atr=True, max_atr_threshold=atr_max)
                print(f"{st:>5.0f} pt | <={atr_max:>5.0f} | {split_name:<12} | {res['trades']:<6} | {res['win_rate']:>5.1f}% | {res['profit_factor']:>5.2f} | {res['net_pts']:>+8.1f}")
            print("-" * 65)

if __name__ == "__main__":
    test_regime_filters()
