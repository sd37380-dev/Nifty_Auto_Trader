"""
Hermes Research Engine: Comprehensive Candidate Validation & Stress Testing.
Evaluates surviving candidate:
- Defined-Risk Theta Option Spread (OTM Credit Spreads / Iron Condor)
Across:
1. Discovery/Train (2021-2024)
2. Validation Set (2025)
3. True Out-of-Sample (2026)
4. Walk-Forward Stability
5. Cost & Slippage Stress (0, 1, 2, 3, 5, 8 pts)
6. Parameter Sensitivity Grid (Strike distance & Stop Loss)
7. Regime Breakdown (Trending vs Sideways, High Vol vs Low Vol)
8. Contradiction & Edge-Case Failure Analysis
"""

import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import sqlite3
import pandas as pd
import numpy as np
import json
from typing import Dict, List, Any


def load_full_dataset():
    conn = sqlite3.connect(root_dir / "data" / "hermes_research" / "market_data.db")
    query = """
        SELECT timestamp, open, high, low, close, volume, open_interest
        FROM normalized_bars
        WHERE symbol = 'NIFTY' AND timeframe = '15M'
        ORDER BY timestamp ASC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    df['dt'] = pd.to_datetime(df['timestamp'], format='ISO8601')
    df.drop_duplicates(subset=['dt'], inplace=True)
    df.set_index('dt', inplace=True)
    df.sort_index(inplace=True)

    df['ist'] = df.index + pd.Timedelta(hours=5, minutes=30)
    df['date'] = df['ist'].dt.date
    df['time_str'] = df['ist'].dt.strftime('%H:%M')
    df['year'] = df['ist'].dt.year

    df = df[(df['time_str'] >= '09:15') & (df['time_str'] <= '15:30')].copy()

    # Calculate Daily Range & Daily ATR
    daily = df.groupby('date').agg(
        day_open=('open', 'first'),
        day_high=('high', 'max'),
        day_low=('low', 'min'),
        day_close=('close', 'last'),
        bars_count=('close', 'count'),
        year=('year', 'first')
    ).reset_index()

    daily['day_range'] = daily['day_high'] - daily['day_low']
    daily['prev_close'] = daily['day_close'].shift(1)
    daily['gap_pct'] = (daily['day_open'] - daily['prev_close']) / daily['prev_close'] * 100.0
    daily['tr'] = np.maximum(
        daily['day_high'] - daily['day_low'],
        np.maximum(
            (daily['day_high'] - daily['prev_close']).abs(),
            (daily['day_low'] - daily['prev_close']).abs()
        )
    )
    daily['atr_14'] = daily['tr'].rolling(14).mean()

    return df, daily


def simulate_theta_spread(
    daily_df: pd.DataFrame,
    strike_distance: float = 150.0,
    stop_loss_pts: float = 60.0,
    target_premium: float = 32.0,
    cost_pts: float = 3.0,
    trend_filter_atr: bool = False,
    max_atr_threshold: float = 220.0
) -> Dict[str, Any]:
    """
    Simulates daily non-directional credit spread / Iron Condor.
    Sells OTM Call at (Open + strike_distance) and OTM Put at (Open - strike_distance).
    If price moves beyond (strike + 30 pts buffer), triggered Stop Loss (-stop_loss_pts - cost).
    If price stays within range, collects target_premium - cost.
    """
    trades = []
    
    for idx, row in daily_df.iterrows():
        if row['bars_count'] < 15 or pd.isna(row['atr_14']):
            continue

        # Optional Regime filter: skip if macro volatility is extreme
        if trend_filter_atr and (row['atr_14'] > max_atr_threshold):
            continue

        d_open = row['day_open']
        d_high = row['day_high']
        d_low = row['day_low']
        year = row['year']
        date_str = str(row['date'])

        call_strike = d_open + strike_distance
        put_strike = d_open - strike_distance

        breached_high = d_high >= (call_strike + 30.0)
        breached_low = d_low <= (put_strike - 30.0)

        if not breached_high and not breached_low:
            pnl = target_premium - cost_pts
            reason = "FULL_DECAY_WIN"
        else:
            pnl = -stop_loss_pts - cost_pts
            reason = "BREACH_STOP_LOSS"

        trades.append({
            "date": date_str,
            "year": int(year),
            "pnl": pnl,
            "reason": reason,
            "day_range": row['day_range'],
            "atr_14": row['atr_14'],
            "gap_pct": row['gap_pct']
        })

    tdf = pd.DataFrame(trades)
    if len(tdf) == 0:
        return {"trades": 0, "win_rate": 0.0, "profit_factor": 0.0, "net_pts": 0.0}

    wins = tdf[tdf['pnl'] > 0]
    losses = tdf[tdf['pnl'] <= 0]
    n = len(tdf)
    n_wins = len(wins)
    wr = n_wins / n * 100.0

    tot_win = wins['pnl'].sum() if n_wins > 0 else 0.0
    tot_loss = abs(losses['pnl'].sum()) if len(losses) > 0 else 1.0
    pf = tot_win / max(1.0, tot_loss)
    net_pts = tdf['pnl'].sum()
    expectancy = tdf['pnl'].mean()

    # Wilson Score 95% Confidence Interval
    p_hat = n_wins / n
    z = 1.96
    denom = 1 + (z**2 / n)
    center = (p_hat + (z**2 / (2 * n))) / denom
    margin = (z * np.sqrt((p_hat * (1 - p_hat) / n) + (z**2 / (4 * n**2)))) / denom
    ci_lower = max(0.0, round((center - margin) * 100.0, 1))
    ci_upper = min(100.0, round((center + margin) * 100.0, 1))

    # Max Drawdown
    tdf['cum'] = tdf['pnl'].cumsum()
    max_dd = (tdf['cum'].cummax() - tdf['cum']).max()

    # Sharpe ratio proxy (daily expectancy / daily std) * sqrt(250)
    std_pnl = tdf['pnl'].std()
    sharpe = (expectancy / std_pnl * np.sqrt(250)) if std_pnl > 0 else 0.0

    # Max consecutive losses
    is_loss = (tdf['pnl'] <= 0).astype(int)
    max_consec_losses = 0
    current_consec = 0
    for l in is_loss:
        if l == 1:
            current_consec += 1
            if current_consec > max_consec_losses:
                max_consec_losses = current_consec
        else:
            current_consec = 0

    yearly = tdf.groupby('year')['pnl'].agg(
        trades='count',
        win_rate=lambda x: round((x > 0).mean() * 100.0, 1),
        net_pts=lambda x: round(x.sum(), 1)
    ).to_dict(orient='index')

    return {
        "trades": n,
        "wins": n_wins,
        "losses": len(losses),
        "win_rate": round(wr, 1),
        "ci_95": f"[{ci_lower}% - {ci_upper}%]",
        "profit_factor": round(pf, 2),
        "net_pts": round(net_pts, 1),
        "expectancy": round(expectancy, 1),
        "max_dd": round(max_dd, 1),
        "sharpe": round(sharpe, 2),
        "max_consec_losses": max_consec_losses,
        "yearly": yearly,
        "trades_df": tdf
    }


def run_full_validation_suite():
    print("=" * 85)
    print("      HERMES RESEARCH ENGINE — CANDIDATE COMPREHENSIVE VALIDATION SUITE      ")
    print("=" * 85)

    _, daily = load_full_dataset()
    print(f"Total Trading Sessions Loaded: {len(daily)} days ({daily['date'].min()} to {daily['date'].max()})")

    # Split datasets
    train_daily = daily[daily['year'] <= 2024].copy()
    val_daily = daily[daily['year'] == 2025].copy()
    oos_daily = daily[daily['year'] >= 2026].copy()

    print(f"Train / Discovery Sessions (2021-2024): {len(train_daily)} sessions")
    print(f"Validation Sessions (2025)             : {len(val_daily)} sessions")
    print(f"Out-of-Sample Sessions (2026)          : {len(oos_daily)} sessions")
    print("-" * 85)

    # 1. Base Strategy Results across Splits
    print("\n--- 1. PERFORMANCE ACROSS TRAIN, VALIDATION & OUT-OF-SAMPLE ---")
    train_res = simulate_theta_spread(train_daily, 150.0, 60.0, 32.0, cost_pts=3.0)
    val_res = simulate_theta_spread(val_daily, 150.0, 60.0, 32.0, cost_pts=3.0)
    oos_res = simulate_theta_spread(oos_daily, 150.0, 60.0, 32.0, cost_pts=3.0)
    full_res = simulate_theta_spread(daily, 150.0, 60.0, 32.0, cost_pts=3.0)

    splits = [
        ("Train / Discovery (2021-2024)", train_res),
        ("Validation (2025)", val_res),
        ("True Out-of-Sample (2026)", oos_res),
        ("Full 5-Year Master (2021-2026)", full_res),
    ]

    print(f"{'Split / Period':<32} | {'Trades':<6} | {'Win %':<6} | {'95% CI':<15} | {'PF':<5} | {'Net Pts':<10} | {'MaxDD':<7} | {'Sharpe':<6}")
    print("-" * 92)
    for name, r in splits:
        print(f"{name:<32} | {r['trades']:<6} | {r['win_rate']:>5.1f}% | {r['ci_95']:<15} | {r['profit_factor']:>5.2f} | {r['net_pts']:>+9.1f} | {r['max_dd']:>6.1f} | {r['sharpe']:>5.2f}")

    print("\nYearly Breakdown across Full 5 Years:")
    for yr, s in full_res['yearly'].items():
        print(f"  Year {yr}: {s['trades']:3d} trades | Win Rate: {s['win_rate']:5.1f}% | Net: {s['net_pts']:+8.1f} pts")

    # 2. Walk-Forward Testing
    print("\n--- 2. WALK-FORWARD ROLLING STABILITY ---")
    wf_windows = [
        ("Train 2021-2022 -> Test 2023", daily[daily['year'].isin([2021, 2022])], daily[daily['year'] == 2023]),
        ("Train 2022-2023 -> Test 2024", daily[daily['year'].isin([2022, 2023])], daily[daily['year'] == 2024]),
        ("Train 2023-2024 -> Test 2025", daily[daily['year'].isin([2023, 2024])], daily[daily['year'] == 2025]),
        ("Train 2024-2025 -> Test 2026", daily[daily['year'].isin([2024, 2025])], daily[daily['year'] == 2026]),
    ]
    print(f"{'Walk-Forward Window':<32} | {'In-Sample WR':<14} | {'Out-of-Sample WR':<17} | {'OOS PF':<7} | {'OOS Net Pts':<11}")
    print("-" * 88)
    for name, in_df, out_df in wf_windows:
        in_r = simulate_theta_spread(in_df, 150.0, 60.0, 32.0, cost_pts=3.0)
        out_r = simulate_theta_spread(out_df, 150.0, 60.0, 32.0, cost_pts=3.0)
        print(f"{name:<32} | {in_r['win_rate']:>5.1f}% ({in_r['trades']} tr) | {out_r['win_rate']:>5.1f}% ({out_r['trades']} tr)   | {out_r['profit_factor']:>5.2f} | {out_r['net_pts']:>+9.1f}")

    # 3. Cost & Slippage Stress Testing
    print("\n--- 3. SLIPPAGE & COST STRESS TESTING (Full Dataset) ---")
    cost_levels = [0.0, 1.0, 2.0, 3.0, 5.0, 8.0]
    print(f"{'Cost per Trade':<16} | {'Trades':<6} | {'Win %':<6} | {'PF':<5} | {'Net Points':<10} | {'Expectancy':<10} | {'Status':<10}")
    print("-" * 75)
    for c in cost_levels:
        c_res = simulate_theta_spread(daily, 150.0, 60.0, 32.0, cost_pts=c)
        status = "HEALTHY" if c_res['profit_factor'] > 1.15 else ("MARGINAL" if c_res['profit_factor'] >= 1.0 else "UNPROFITABLE")
        print(f"{c:>4.1f} NIFTY pts     | {c_res['trades']:<6} | {c_res['win_rate']:>5.1f}% | {c_res['profit_factor']:>5.2f} | {c_res['net_pts']:>+9.1f} | {c_res['expectancy']:>+7.2f} pts/tr | {status:<10}")

    # 4. Parameter Sensitivity Grid
    print("\n--- 4. PARAMETER SENSITIVITY MATRIX (Strike Distance vs Stop Loss) ---")
    strike_grid = [130.0, 140.0, 150.0, 160.0, 180.0]
    sl_grid = [45.0, 50.0, 60.0, 70.0]
    print(f"{'Strike Dist':<12} | {'Stop Loss':<10} | {'Win %':<6} | {'PF':<5} | {'Net Points':<10} | {'MaxDD':<7}")
    print("-" * 60)
    for s_dist in strike_grid:
        for sl_pt in sl_grid:
            p_res = simulate_theta_spread(daily, strike_distance=s_dist, stop_loss_pts=sl_pt, target_premium=32.0, cost_pts=3.0)
            print(f"{s_dist:>6.0f} pts     | {sl_pt:>5.0f} pts    | {p_res['win_rate']:>5.1f}% | {p_res['profit_factor']:>5.2f} | {p_res['net_pts']:>+9.1f} | {p_res['max_dd']:>6.1f}")

    # 5. Market Regime Breakdown (Trending vs Sideways)
    print("\n--- 5. REGIME BREAKDOWN & BEHAVIORAL CONTRADICTION ANALYSIS ---")
    tdf_full = full_res['trades_df']
    sideways_trades = tdf_full[tdf_full['day_range'] <= 160.0]
    trending_trades = tdf_full[tdf_full['day_range'] > 160.0]
    extreme_trend_trades = tdf_full[tdf_full['day_range'] > 250.0]

    print(f"Sideways Days (Range <= 160 pts): {len(sideways_trades)} days | Win Rate: {(sideways_trades['pnl'] > 0).mean()*100:.1f}% | Net: {sideways_trades['pnl'].sum():+.1f} pts")
    print(f"Trending Days (Range > 160 pts) : {len(trending_trades)} days | Win Rate: {(trending_trades['pnl'] > 0).mean()*100:.1f}% | Net: {trending_trades['pnl'].sum():+.1f} pts")
    print(f"Extreme Days  (Range > 250 pts) : {len(extreme_trend_trades)} days | Win Rate: {(extreme_trend_trades['pnl'] > 0).mean()*100:.1f}% | Net: {extreme_trend_trades['pnl'].sum():+.1f} pts")

    # High Vol vs Low Vol
    median_atr = tdf_full['atr_14'].median()
    low_vol = tdf_full[tdf_full['atr_14'] <= median_atr]
    high_vol = tdf_full[tdf_full['atr_14'] > median_atr]
    print(f"Low Volatility Days (ATR <= {median_atr:.1f}): {len(low_vol)} days | Win Rate: {(low_vol['pnl'] > 0).mean()*100:.1f}% | Net: {low_vol['pnl'].sum():+.1f} pts")
    print(f"High Volatility Days (ATR > {median_atr:.1f}): {len(high_vol)} days | Win Rate: {(high_vol['pnl'] > 0).mean()*100:.1f}% | Net: {high_vol['pnl'].sum():+.1f} pts")

    # Gap Days Analysis
    gap_days = tdf_full[tdf_full['gap_pct'].abs() >= 0.5]
    non_gap_days = tdf_full[tdf_full['gap_pct'].abs() < 0.5]
    print(f"Gap Days (|Gap| >= 0.5%)        : {len(gap_days)} days | Win Rate: {(gap_days['pnl'] > 0).mean()*100:.1f}% | Net: {gap_days['pnl'].sum():+.1f} pts")
    print(f"Normal Days (|Gap| < 0.5%)      : {len(non_gap_days)} days | Win Rate: {(non_gap_days['pnl'] > 0).mean()*100:.1f}% | Net: {non_gap_days['pnl'].sum():+.1f} pts")

    # Save summary results to JSON for documentation
    summary_data = {
        "train_res": {k: v for k, v in train_res.items() if k != 'trades_df'},
        "val_res": {k: v for k, v in val_res.items() if k != 'trades_df'},
        "oos_res": {k: v for k, v in oos_res.items() if k != 'trades_df'},
        "full_res": {k: v for k, v in full_res.items() if k != 'trades_df'},
    }
    with open(root_dir / "data" / "hermes_research" / "validation_summary.json", "w") as f:
        json.dump(summary_data, f, indent=2)

    print("\n[+] Validation suite completed successfully. Summary saved to validation_summary.json.")


if __name__ == "__main__":
    run_full_validation_suite()
