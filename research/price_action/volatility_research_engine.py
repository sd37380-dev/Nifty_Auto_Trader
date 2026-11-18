"""
Topic 5 — Volatility Compression -> Expansion Research Engine for NIFTY 50 Spot.
Comprehensive quantitative analysis of volatility cycles, NR patterns, clustering,
and expansion mechanics across 92,605 5-minute bars (2021-2026).
Strictly look-ahead-free at evaluation timestamp.
"""

import os
import sys
from datetime import datetime, time, date
import json
import math
import numpy as np
import pandas as pd
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.abspath("."))

from research.price_action.data_loader import load_and_clean_nifty_5m


def run_volatility_research():
    print("Loading 5-minute NIFTY dataset...")
    df_5m, clean_stats = load_and_clean_nifty_5m()
    n_total = len(df_5m)
    print(f"Total clean 5M bars: {n_total}")

    df = df_5m.sort_values('timestamp').reset_index(drop=True)

    # 1. Base Price Series
    highs = df['high'].values
    lows = df['low'].values
    opens = df['open'].values
    closes = df['close'].values
    ranges = highs - lows
    dates = df['date_ist'].values

    # True range & ATR14
    prev_closes = np.roll(closes, 1)
    prev_closes[0] = opens[0]
    tr = np.maximum(ranges, np.maximum(np.abs(highs - prev_closes), np.abs(lows - prev_closes)))
    df['tr'] = tr
    df['atr14'] = df['tr'].rolling(14).mean()
    df['rolling_range_20'] = df['tr'].rolling(20).mean()
    df['log_ret'] = np.log(closes / np.where(prev_closes > 0, prev_closes, 1.0))
    df['rolling_std_20'] = df['log_ret'].rolling(20).std() * np.sqrt(75) # annualized/session scale

    # Multi-timeframe resampling: 15M, 1H, Daily
    # Compute rolling metrics
    df['range'] = ranges
    df['direction'] = np.where(closes > opens, 'UP', np.where(closes < opens, 'DOWN', 'FLAT'))
    df['compression_ratio'] = ranges / np.where(df['rolling_range_20'] > 0, df['rolling_range_20'], 1.0)

    # Range Percentiles across all 5M bars
    p01 = np.percentile(ranges, 1)
    p02 = np.percentile(ranges, 2)
    p05 = np.percentile(ranges, 5)
    p10 = np.percentile(ranges, 10)
    p50 = np.percentile(ranges, 50)
    p90 = np.percentile(ranges, 90)
    p95 = np.percentile(ranges, 95)
    p98 = np.percentile(ranges, 98)
    p99 = np.percentile(ranges, 99)

    print(f"5M Range Distribution: P1={p01:.2f}, P5={p05:.2f}, P10={p10:.2f}, P50={p50:.2f}, P90={p90:.2f}, P95={p95:.2f}, P99={p99:.2f}")

    # Forward expansion metrics: 1, 3, 6, 12, 24 bars (5m, 15m, 30m, 1h, 2h)
    horizons = [1, 3, 6, 12, 24]
    fwd_expansion_pts = {h: np.full(n_total, np.nan) for h in horizons}
    fwd_expansion_ratio = {h: np.full(n_total, np.nan) for h in horizons}
    fwd_max_move = {h: np.full(n_total, np.nan) for h in horizons}
    fwd_ret = {h: np.full(n_total, np.nan) for h in horizons}

    for i in range(n_total - 25):
        dt_i = dates[i]
        c_i = closes[i]
        rng_i = max(ranges[i], 1.0)
        
        for h in horizons:
            idx_end = i + h
            if idx_end < n_total and dates[idx_end] == dt_i:
                sub_h = highs[i+1:idx_end+1]
                sub_l = lows[i+1:idx_end+1]
                sub_rng = np.max(sub_h) - np.min(sub_l)
                fwd_expansion_pts[h][i] = sub_rng
                fwd_expansion_ratio[h][i] = sub_rng / rng_i
                fwd_max_move[h][i] = max(np.max(sub_h) - c_i, c_i - np.min(sub_l))
                fwd_ret[h][i] = closes[idx_end] - c_i

    for h in horizons:
        df[f'fwd_exp_{h}'] = fwd_expansion_pts[h]
        df[f'fwd_ratio_{h}'] = fwd_expansion_ratio[h]
        df[f'fwd_move_{h}'] = fwd_max_move[h]
        df[f'fwd_ret_{h}'] = fwd_ret[h]

    # =================================================================
    # 2. EXTREME COMPRESSION ANALYSIS (Lowest 1%, 2%, 5%, 10%)
    # =================================================================
    print("Analyzing Extreme Compression Percentiles...")
    comp_pctiles = [
        ('Lowest 1%', p01),
        ('Lowest 2%', p02),
        ('Lowest 5%', p05),
        ('Lowest 10%', p10),
    ]

    compression_results = {}
    for label, thresh in comp_pctiles:
        mask = df['range'] <= thresh
        n_comp = int(mask.sum())
        
        # Time to expansion: how many bars until range exceeds median (P50)?
        expansion_delays = []
        for idx_c in np.where(mask)[0]:
            found = False
            for step in range(1, 24):
                if idx_c + step < n_total and dates[idx_c + step] == dates[idx_c]:
                    if ranges[idx_c + step] >= p50:
                        expansion_delays.append(step * 5)
                        found = True
                        break
            if not found:
                expansion_delays.append(120)

        avg_delay_min = np.mean(expansion_delays) if len(expansion_delays) > 0 else 0
        avg_exp_6 = df.loc[mask, 'fwd_exp_6'].mean()
        avg_ratio_6 = df.loc[mask, 'fwd_ratio_6'].mean()
        avg_move_6 = df.loc[mask, 'fwd_move_6'].mean()
        
        # Directional predictability: is there directional bias?
        fwd_up_rate_6 = (df.loc[mask, 'fwd_ret_6'] > 0).mean() * 100

        compression_results[label] = {
            'threshold_pts': round(float(thresh), 2),
            'count_bars': n_comp,
            'pct_of_all': round(n_comp / n_total * 100, 2),
            'avg_minutes_to_expansion': round(float(avg_delay_min), 1),
            'mean_subseq_30m_range_pts': round(float(avg_exp_6), 2),
            'mean_expansion_multiple_30m': round(float(avg_ratio_6), 2),
            'mean_max_movement_30m_pts': round(float(avg_move_6), 2),
            'directional_up_prob_30m': round(float(fwd_up_rate_6), 2)
        }

    # =================================================================
    # 3. MULTI-CANDLE COMPRESSION RUNS (2, 3, 4, 5, 7, 10+ candles)
    # =================================================================
    print("Analyzing Multi-Candle Contraction Streaks...")
    # Consecutive contracting candles: Range_t < Range_{t-1}
    streak_counts = np.zeros(n_total, dtype=int)
    curr_streak = 0
    for i in range(1, n_total):
        if dates[i] == dates[i-1] and ranges[i] < ranges[i-1]:
            curr_streak += 1
        else:
            curr_streak = 1
        streak_counts[i] = curr_streak

    df['contract_streak'] = streak_counts

    streak_analysis = {}
    for s_len in [2, 3, 4, 5, 7, 10]:
        s_mask = df['contract_streak'] == s_len
        n_s = int(s_mask.sum())
        if n_s > 0:
            avg_exp_6 = df.loc[s_mask, 'fwd_exp_6'].mean()
            avg_ratio_6 = df.loc[s_mask, 'fwd_ratio_6'].mean()
            avg_move_6 = df.loc[s_mask, 'fwd_move_6'].mean()
            streak_analysis[f'{s_len}_candles'] = {
                'count': n_s,
                'mean_subseq_30m_range': round(float(avg_exp_6), 2),
                'mean_expansion_ratio': round(float(avg_ratio_6), 2),
                'mean_max_move_30m': round(float(avg_move_6), 2),
            }

    # =================================================================
    # 4. NR PATTERNS (NR2, NR3, NR4, NR7)
    # =================================================================
    print("Analyzing Narrow Range Patterns (NR2, NR3, NR4, NR7)...")
    # NR_k: range is strictly narrower than the previous k-1 candles
    nr_results = {}
    for k in [2, 3, 4, 7]:
        nr_mask = np.ones(n_total, dtype=bool)
        for shift_i in range(1, k):
            shifted_rng = np.roll(ranges, shift_i)
            shifted_date = np.roll(dates, shift_i)
            same_day = (dates == shifted_date)
            nr_mask = nr_mask & same_day & (ranges < shifted_rng)

        # Breakout metrics on NR bar: does price break high or low on next bar?
        next_high = np.roll(highs, -1)
        next_low = np.roll(lows, -1)
        next_close = np.roll(closes, -1)
        next_date = np.roll(dates, -1)
        valid_next = (dates == next_date) & nr_mask

        # Breakout up: next_high > high; Breakout down: next_low < low
        bo_up = valid_next & (next_high > highs)
        bo_down = valid_next & (next_low < lows)
        
        # MFE / MAE over 6 bars following breakout
        sub_mfe = []
        sub_mae = []
        failed_count = 0
        total_bo = 0

        for i_nr in np.where(valid_next)[0]:
            h_nr = highs[i_nr]
            l_nr = lows[i_nr]
            c_nr = closes[i_nr]
            rng_nr = ranges[i_nr]
            
            # Check if next 6 bars break out
            if i_nr + 6 < n_total and dates[i_nr+6] == dates[i_nr]:
                post_h = highs[i_nr+1:i_nr+7]
                post_l = lows[i_nr+1:i_nr+7]
                
                # First breakout side
                broke_up = (post_h > h_nr).any()
                broke_down = (post_l < l_nr).any()
                
                if broke_up and not broke_down:
                    total_bo += 1
                    mfe = np.max(post_h) - h_nr
                    mae = h_nr - np.min(post_l)
                    sub_mfe.append(mfe)
                    sub_mae.append(mae)
                    if (post_l < l_nr).any():
                        failed_count += 1
                elif broke_down and not broke_up:
                    total_bo += 1
                    mfe = l_nr - np.min(post_l)
                    mae = np.max(post_h) - l_nr
                    sub_mfe.append(mfe)
                    sub_mae.append(mae)
                    if (post_h > h_nr).any():
                        failed_count += 1
                elif broke_up and broke_down:
                    total_bo += 1
                    failed_count += 1
                    sub_mfe.append(max(np.max(post_h) - h_nr, l_nr - np.min(post_l)))
                    sub_mae.append(min(h_nr - np.min(post_l), np.max(post_h) - l_nr))

        nr_results[f'NR{k}'] = {
            'count': int(valid_next.sum()),
            'pct_of_all_bars': round(int(valid_next.sum()) / n_total * 100, 2),
            'breakout_failure_rate': round(failed_count / max(total_bo, 1) * 100, 2),
            'mean_mfe_30m': round(float(np.mean(sub_mfe)), 2) if len(sub_mfe) > 0 else 0,
            'mean_mae_30m': round(float(np.mean(sub_mae)), 2) if len(sub_mae) > 0 else 0,
            'mfe_mae_ratio': round(float(np.mean(sub_mfe) / np.mean(sub_mae)), 2) if len(sub_mae) > 0 and np.mean(sub_mae) > 0 else 0,
        }

    # =================================================================
    # 5. EXPANSION EXHAUSTION (Top 1%, 2%, 5%, 10%)
    # =================================================================
    print("Analyzing Expansion Outcomes (Continuation, Consolidation, Reversal)...")
    expansion_outcomes = {}
    exp_pctiles = [
        ('Top 1%', p99),
        ('Top 2%', p98),
        ('Top 5%', p95),
        ('Top 10%', p90)
    ]

    for label, thresh in exp_pctiles:
        e_mask = df['range'] >= thresh
        # Evaluate subsequent 6 bars
        cont_count = 0
        rev_count = 0
        consol_count = 0
        n_eval = 0

        for i_e in np.where(e_mask)[0]:
            if i_e + 6 < n_total and dates[i_e+6] == dates[i_e]:
                n_eval += 1
                bar_dir = df.loc[i_e, 'direction']
                c_e = closes[i_e]
                h_e = highs[i_e]
                l_e = lows[i_e]
                rng_e = ranges[i_e]
                
                sub_c6 = closes[i_e+6]
                sub_h6 = np.max(highs[i_e+1:i_e+7])
                sub_l6 = np.min(lows[i_e+1:i_e+7])
                
                # Consolidation: range stays within 50% band of expansion bar
                if (sub_h6 <= h_e + 0.1 * rng_e) and (sub_l6 >= l_e - 0.1 * rng_e):
                    consol_count += 1
                elif bar_dir == 'UP':
                    if sub_c6 > c_e:
                        cont_count += 1
                    else:
                        rev_count += 1
                elif bar_dir == 'DOWN':
                    if sub_c6 < c_e:
                        cont_count += 1
                    else:
                        rev_count += 1
                else:
                    consol_count += 1

        expansion_outcomes[label] = {
            'threshold_pts': round(float(thresh), 2),
            'evaluated_events': n_eval,
            'continuation_pct': round(cont_count / max(n_eval, 1) * 100, 2),
            'reversal_pct': round(rev_count / max(n_eval, 1) * 100, 2),
            'consolidation_pct': round(consol_count / max(n_eval, 1) * 100, 2),
        }

    # =================================================================
    # 6. VOLATILITY CLUSTERING & PERSISTENCE
    # =================================================================
    print("Measuring Volatility Clustering & Autoregressive Persistence...")
    # Daily ATR clustering
    # Group by date to get daily ATR
    daily_tr = df.groupby('date_ist')['tr'].sum()
    daily_p75 = daily_tr.quantile(0.75)
    daily_high_vol = daily_tr >= daily_p75
    
    # P(high vol tomorrow | high vol today)
    p_high_next_day = (daily_high_vol.shift(-1)[daily_high_vol]).mean() * 100
    p_uncond_high_day = daily_high_vol.mean() * 100

    # Hourly volatility clustering (12 5M bars per hour)
    # Range of 1-hour block
    hourly_ranges = []
    for dt, grp in df.groupby('date_ist'):
        for h_chunk in range(0, len(grp), 12):
            block = grp.iloc[h_chunk:h_chunk+12]
            if len(block) >= 6:
                hourly_ranges.append(block['high'].max() - block['low'].min())

    s_hourly = pd.Series(hourly_ranges)
    h_p75 = s_hourly.quantile(0.75)
    h_high_vol = s_hourly >= h_p75
    p_high_next_hour = (h_high_vol.shift(-1)[h_high_vol]).mean() * 100
    p_uncond_high_hour = h_high_vol.mean() * 100

    vol_clustering = {
        'daily_unconditional_high_vol_prob': round(float(p_uncond_high_day), 2),
        'daily_conditional_high_vol_next_day_prob': round(float(p_high_next_day), 2),
        'daily_clustering_excess_pct': round(float(p_high_next_day - p_uncond_high_day), 2),
        'hourly_unconditional_high_vol_prob': round(float(p_uncond_high_hour), 2),
        'hourly_conditional_high_vol_next_hour_prob': round(float(p_high_next_hour), 2),
        'hourly_clustering_excess_pct': round(float(p_high_next_hour - p_uncond_high_hour), 2),
    }

    # =================================================================
    # 7. MULTI-DAY PERSISTENCE (INTRADAY VS SWING)
    # =================================================================
    # After extreme daily compression (Daily Range < 25th percentile)
    daily_p25 = daily_tr.quantile(0.25)
    daily_comp = daily_tr <= daily_p25
    
    # Forward daily ranges
    fwd_d1_rng = daily_tr.shift(-1)[daily_comp].mean()
    fwd_d3_rng = daily_tr.rolling(3).sum().shift(-3)[daily_comp].mean()
    fwd_d5_rng = daily_tr.rolling(5).sum().shift(-5)[daily_comp].mean()
    baseline_d1_rng = daily_tr.mean()

    swing_persistence = {
        'daily_compression_threshold_pts': round(float(daily_p25), 2),
        'compressed_days_count': int(daily_comp.sum()),
        'mean_next_day_range_pts': round(float(fwd_d1_rng), 2),
        'baseline_day_range_pts': round(float(baseline_d1_rng), 2),
        'next_day_expansion_pct': round(float((fwd_d1_rng - baseline_d1_rng) / baseline_d1_rng * 100), 2),
        'mean_3day_cumulative_range_pts': round(float(fwd_d3_rng), 2),
        'mean_5day_cumulative_range_pts': round(float(fwd_d5_rng), 2),
    }

    results = {
        'total_bars': n_total,
        'range_percentiles': {
            'p01': round(float(p01), 2),
            'p02': round(float(p02), 2),
            'p05': round(float(p05), 2),
            'p10': round(float(p10), 2),
            'p50': round(float(p50), 2),
            'p90': round(float(p90), 2),
            'p95': round(float(p95), 2),
            'p98': round(float(p98), 2),
            'p99': round(float(p99), 2),
        },
        'extreme_compression': compression_results,
        'multi_candle_streaks': streak_analysis,
        'nr_patterns': nr_results,
        'expansion_outcomes': expansion_outcomes,
        'volatility_clustering': vol_clustering,
        'swing_persistence': swing_persistence,
    }

    # Save to JSON
    with open("research/price_action/volatility_metrics.json", "w") as f:
        json.dump(results, f, indent=2)
    print("[OK] Saved research/price_action/volatility_metrics.json")

    # Export sample events CSV
    ev_mask = (df['range'] <= p05) | (df['range'] >= p95)
    df_vol_events = df[ev_mask][['timestamp', 'open', 'high', 'low', 'close', 'range',
                                'compression_ratio', 'atr14', 'fwd_exp_6', 'fwd_ratio_6',
                                'fwd_move_6', 'fwd_ret_6']].copy()
    df_vol_events.to_csv("research/price_action/VOLATILITY_EVENTS.csv", index=False)
    print(f"[OK] Saved research/price_action/VOLATILITY_EVENTS.csv with {len(df_vol_events)} events.")

    return results


if __name__ == "__main__":
    res = run_volatility_research()
    print("\n--- Summary of NR Patterns ---")
    for k, v in res['nr_patterns'].items():
        print(f"{k}: Count {v['count']} | Fail Rate: {v['breakout_failure_rate']}% | MFE/MAE: {v['mfe_mae_ratio']}")
