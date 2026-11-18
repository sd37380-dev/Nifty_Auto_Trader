"""
Detailed Multi-Angle Analysis of the Regime-Filtered Defined-Risk Theta Spread Strategy.
Produces all metrics, tables, distributions, and stress-tests required for the final report.
"""

import sys
from pathlib import Path
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import pandas as pd
import numpy as np
import json
from research.validation.validate_candidate import load_full_dataset, simulate_theta_spread

def run_detailed_analysis():
    _, daily = load_full_dataset()

    train_daily = daily[daily['year'] <= 2024].copy()
    val_daily = daily[daily['year'] == 2025].copy()
    oos_daily = daily[daily['year'] >= 2026].copy()

    # Base parameters for candidate:
    # Strike Distance: 160 pts OTM
    # ATR 14 Threshold: <= 220.0 pts
    # Stop Loss: 50.0 pts
    # Target Premium: 32.0 pts
    # Cost: 3.0 pts
    
    print("=" * 80)
    print(" DETAILED CANDIDATE: ATR-FILTERED DEFINED-RISK THETA SPREAD (160 PT OTM)")
    print("=" * 80)

    # 1. Performance across Splits
    train_res = simulate_theta_spread(train_daily, 160.0, 50.0, 32.0, cost_pts=3.0, trend_filter_atr=True, max_atr_threshold=220.0)
    val_res = simulate_theta_spread(val_daily, 160.0, 50.0, 32.0, cost_pts=3.0, trend_filter_atr=True, max_atr_threshold=220.0)
    oos_res = simulate_theta_spread(oos_daily, 160.0, 50.0, 32.0, cost_pts=3.0, trend_filter_atr=True, max_atr_threshold=220.0)
    full_res = simulate_theta_spread(daily, 160.0, 50.0, 32.0, cost_pts=3.0, trend_filter_atr=True, max_atr_threshold=220.0)

    print("\n--- 1. SPLIT PERFORMANCE ---")
    splits = [
        ("Train / Discovery (2021-2024)", train_res),
        ("Validation (2025)", val_res),
        ("True Out-of-Sample (2026)", oos_res),
        ("Full 5-Year Combined (2021-2026)", full_res),
    ]
    print(f"{'Split / Period':<32} | {'Trades':<6} | {'Win %':<6} | {'95% CI':<15} | {'PF':<5} | {'Net Pts':<10} | {'MaxDD':<7} | {'Sharpe':<6}")
    print("-" * 92)
    for name, r in splits:
        print(f"{name:<32} | {r['trades']:<6} | {r['win_rate']:>5.1f}% | {r['ci_95']:<15} | {r['profit_factor']:>5.2f} | {r['net_pts']:>+9.1f} | {r['max_dd']:>6.1f} | {r['sharpe']:>5.2f}")

    # 2. Yearly Breakdown
    print("\n--- 2. YEAR-BY-YEAR DETAILED METRICS ---")
    tdf = full_res['trades_df']
    for yr in sorted(tdf['year'].unique()):
        ydf = tdf[tdf['year'] == yr]
        y_wins = ydf[ydf['pnl'] > 0]
        y_losses = ydf[ydf['pnl'] <= 0]
        y_wr = len(y_wins) / len(ydf) * 100.0
        y_tot_w = y_wins['pnl'].sum() if len(y_wins) > 0 else 0.0
        y_tot_l = abs(y_losses['pnl'].sum()) if len(y_losses) > 0 else 1.0
        y_pf = y_tot_w / max(1.0, y_tot_l)
        y_net = ydf['pnl'].sum()
        print(f"Year {yr}: {len(ydf):3d} trades | Wins: {len(y_wins):3d} | Losses: {len(y_losses):2d} | Win Rate: {y_wr:5.1f}% | PF: {y_pf:4.2f} | Net: {y_net:+8.1f} pts")

    # 3. Cost Stress Matrix
    print("\n--- 3. SLIPPAGE & TRANSACTION COST STRESS TEST ---")
    costs = [0.0, 1.0, 2.0, 3.0, 5.0, 7.5, 10.0]
    print(f"{'Cost per Trade':<16} | {'Trades':<6} | {'Win %':<6} | {'PF':<5} | {'Net Points':<10} | {'Expectancy':<12} | {'MaxDD':<7}")
    print("-" * 75)
    for c in costs:
        cr = simulate_theta_spread(daily, 160.0, 50.0, 32.0, cost_pts=c, trend_filter_atr=True, max_atr_threshold=220.0)
        print(f"{c:>4.1f} NIFTY pts     | {cr['trades']:<6} | {cr['win_rate']:>5.1f}% | {cr['profit_factor']:>5.2f} | {cr['net_pts']:>+9.1f} | {cr['expectancy']:>+7.2f} pts/tr | {cr['max_dd']:>6.1f}")

    # 4. Parameter Sensitivity (Strike Distance x ATR Threshold)
    print("\n--- 4. PARAMETER SENSITIVITY GRID (Strike vs ATR Max) ---")
    for s_dist in [140.0, 150.0, 160.0, 170.0, 180.0]:
        for atr_m in [180.0, 200.0, 220.0, 240.0]:
            pr = simulate_theta_spread(daily, strike_distance=s_dist, stop_loss_pts=50.0, target_premium=32.0, cost_pts=3.0, trend_filter_atr=True, max_atr_threshold=atr_m)
            print(f"Strike: {s_dist:3.0f} pt | ATR <= {atr_m:3.0f} | Trades: {pr['trades']:3d} | Win Rate: {pr['win_rate']:5.1f}% | PF: {pr['profit_factor']:4.2f} | Net: {pr['net_pts']:+8.1f} pts | MaxDD: {pr['max_dd']:6.1f}")

    # 5. Day of Week Breakdown
    print("\n--- 5. DAY OF WEEK PERFORMANCE ---")
    # Date to day of week
    tdf['dow'] = pd.to_datetime(tdf['date']).dt.day_name()
    for dow in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']:
        dow_df = tdf[tdf['dow'] == dow]
        if len(dow_df) > 0:
            d_wr = (dow_df['pnl'] > 0).mean() * 100.0
            d_net = dow_df['pnl'].sum()
            print(f"{dow:<10} | Trades: {len(dow_df):3d} | Win Rate: {d_wr:5.1f}% | Net Points: {d_net:+8.1f} pts")

    # 6. Consecutive Win/Loss Streaks
    print("\n--- 6. STREAK AND DRAWDOWN PROFILE ---")
    print(f"Max Consecutive Losses: {full_res['max_consec_losses']}")
    
    # Calculate Max Consecutive Wins
    is_win = (tdf['pnl'] > 0).astype(int)
    max_c_w = 0
    cur_c_w = 0
    for w in is_win:
        if w == 1:
            cur_c_w += 1
            if cur_c_w > max_c_w:
                max_c_w = cur_c_w
        else:
            cur_c_w = 0
    print(f"Max Consecutive Wins  : {max_c_w}")
    print(f"Total Net Points      : {full_res['net_pts']:+,.1f} NIFTY pts")
    print(f"Max Peak-to-Trough DD : {full_res['max_dd']:.1f} pts")
    print(f"Return / Max DD Ratio : {full_res['net_pts'] / full_res['max_dd']:.2f}")

    # Save detailed data for reporting
    report_dict = {
        "candidate_name": "ATR-Filtered Defined-Risk Theta Spread (160 pt OTM)",
        "train": {k: v for k, v in train_res.items() if k != 'trades_df'},
        "validation": {k: v for k, v in val_res.items() if k != 'trades_df'},
        "oos": {k: v for k, v in oos_res.items() if k != 'trades_df'},
        "full": {k: v for k, v in full_res.items() if k != 'trades_df'},
    }
    with open(root_dir / "data" / "hermes_research" / "detailed_candidate_metrics.json", "w") as f:
        json.dump(report_dict, f, indent=2)

if __name__ == "__main__":
    run_detailed_analysis()
