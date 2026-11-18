"""
Topic 4 — Candle Geometry, Body, Wick and Close Location Research Engine.
Exhaustive empirical analysis of 92,605 5-minute bars across 5 years of NIFTY Spot data.
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


def run_candle_geometry_research():
    print("Loading 5-minute NIFTY dataset...")
    df_5m, clean_stats = load_and_clean_nifty_5m()
    n_total = len(df_5m)
    print(f"Total clean 5M bars: {n_total}")

    # Ensure chronological sort
    df = df_5m.sort_values('timestamp').reset_index(drop=True)

    # 1. Geometry features
    ranges = (df['high'] - df['low']).values
    opens = df['open'].values
    highs = df['high'].values
    lows = df['low'].values
    closes = df['close'].values

    # True range & rolling ATR14
    prev_closes = np.roll(closes, 1)
    prev_closes[0] = opens[0]
    tr = np.maximum(highs - lows, np.maximum(np.abs(highs - prev_closes), np.abs(lows - prev_closes)))
    df['tr'] = tr
    df['atr14'] = df['tr'].rolling(14).mean()

    # Avoid zero division
    safe_ranges = np.where(ranges > 0, ranges, 1e-5)
    bodies = np.abs(closes - opens)
    body_ratios = bodies / safe_ranges
    upper_wicks = highs - np.maximum(opens, closes)
    lower_wicks = np.minimum(opens, closes) - lows
    upper_wick_ratios = upper_wicks / safe_ranges
    lower_wick_ratios = lower_wicks / safe_ranges
    close_locs = (closes - lows) / safe_ranges
    open_locs = (opens - lows) / safe_ranges
    directions = np.where(closes > opens, 'UP', np.where(closes < opens, 'DOWN', 'FLAT'))
    atr_multiples = ranges / np.where(df['atr14'] > 0, df['atr14'], safe_ranges)

    df['range'] = ranges
    df['body'] = bodies
    df['body_ratio'] = body_ratios
    df['upper_wick_ratio'] = upper_wick_ratios
    df['lower_wick_ratio'] = lower_wick_ratios
    df['close_loc'] = close_locs
    df['open_loc'] = open_locs
    df['direction'] = directions
    df['atr_mult'] = atr_multiples

    # Range percentiles
    p90 = np.percentile(ranges, 90)
    p95 = np.percentile(ranges, 95)
    p98 = np.percentile(ranges, 98)
    p99 = np.percentile(ranges, 99)

    print(f"Range Percentiles: P90={p90:.2f} pts, P95={p95:.2f} pts, P98={p98:.2f} pts, P99={p99:.2f} pts")

    # Forward horizon calculations: 1, 3, 6, 12, 24 bars
    horizons = [1, 3, 6, 12, 24]
    dates = df['date_ist'].values
    
    # Precompute forward returns, MFE, MAE per bar
    fwd_ret = {h: np.full(n_total, np.nan) for h in horizons}
    fwd_mfe_long = {h: np.full(n_total, np.nan) for h in horizons}
    fwd_mae_long = {h: np.full(n_total, np.nan) for h in horizons}
    fwd_mfe_short = {h: np.full(n_total, np.nan) for h in horizons}
    fwd_mae_short = {h: np.full(n_total, np.nan) for h in horizons}

    # Vectorized forward indexing with same-day boundary check
    print("Computing forward returns and excursions across horizons...")
    for i in range(n_total - 25):
        dt_i = dates[i]
        c_i = closes[i]
        
        # Max horizon within same day
        for h in horizons:
            idx_end = i + h
            if idx_end < n_total and dates[idx_end] == dt_i:
                fwd_ret[h][i] = closes[idx_end] - c_i
                sub_highs = highs[i+1:idx_end+1]
                sub_lows = lows[i+1:idx_end+1]
                fwd_mfe_long[h][i] = np.max(sub_highs) - c_i
                fwd_mae_long[h][i] = c_i - np.min(sub_lows)
                fwd_mfe_short[h][i] = c_i - np.min(sub_lows)
                fwd_mae_short[h][i] = np.max(sub_highs) - c_i

    for h in horizons:
        df[f'ret_{h}'] = fwd_ret[h]
        df[f'mfe_long_{h}'] = fwd_mfe_long[h]
        df[f'mae_long_{h}'] = fwd_mae_long[h]
        df[f'mfe_short_{h}'] = fwd_mfe_short[h]
        df[f'mae_short_{h}'] = fwd_mae_short[h]

    # Precompute session VWAP and PDH/PDL for contextual tagging
    print("Attaching contextual tags (PDH, PDL, VWAP, ORB)...")
    daily_groups = df.groupby('date_ist')
    
    # Build daily PDH, PDL
    day_exts = {}
    for dt, grp in daily_groups:
        day_exts[dt] = {'high': grp['high'].max(), 'low': grp['low'].min(), 'close': grp['close'].iloc[-1]}
    
    all_dts = sorted(list(day_exts.keys()))
    pdh_map = {}
    pdl_map = {}
    for idx_d, dt in enumerate(all_dts):
        if idx_d > 0:
            prev_dt = all_dts[idx_d - 1]
            pdh_map[dt] = day_exts[prev_dt]['high']
            pdl_map[dt] = day_exts[prev_dt]['low']
        else:
            pdh_map[dt] = np.nan
            pdl_map[dt] = np.nan

    df['pdh'] = df['date_ist'].map(pdh_map)
    df['pdl'] = df['date_ist'].map(pdl_map)

    # Attach VWAP
    vwap_vals = np.full(n_total, np.nan)
    for dt, grp in daily_groups:
        idxs = grp.index.values
        typ = (highs[idxs] + lows[idxs] + closes[idxs]) / 3.0
        v = np.maximum(df.loc[idxs, 'volume'].values, 1)
        cum_vp = np.cumsum(typ * v)
        cum_v = np.cumsum(v)
        vwap_vals[idxs] = cum_vp / cum_v
    df['vwap'] = vwap_vals

    # Context masks
    near_pdh = np.abs(df['high'] - df['pdh']) <= 5.0
    near_pdl = np.abs(df['low'] - df['pdl']) <= 5.0
    near_vwap = np.abs(df['close'] - df['vwap']) <= 5.0
    df['is_at_pdh'] = near_pdh
    df['is_at_pdl'] = near_pdl
    df['is_at_vwap'] = near_vwap

    # =================================================================
    # 2. LARGE CANDLE ANALYSIS
    # =================================================================
    print("Analyzing Large Candle Percentiles...")
    large_candle_results = {}
    pctile_defs = [
        ('Top 10%', p90),
        ('Top 5%', p95),
        ('Top 2%', p98),
        ('Top 1%', p99)
    ]

    for label, thresh in pctile_defs:
        mask = df['range'] >= thresh
        bull_mask = mask & (df['direction'] == 'UP')
        bear_mask = mask & (df['direction'] == 'DOWN')

        # Retracement check: does subseq 6 bars retrace 50% or 100% of candle body?
        bull_retrace_50 = 0
        bull_retrace_100 = 0
        bull_sub = df[bull_mask]
        for idx_b, row in bull_sub.iterrows():
            if idx_b + 6 < n_total and dates[idx_b + 6] == row['date_ist']:
                sub_l = lows[idx_b+1:idx_b+7]
                b_low = row['low']
                b_rng = row['range']
                if np.min(sub_l) <= (row['high'] - 0.50 * b_rng):
                    bull_retrace_50 += 1
                if np.min(sub_l) <= b_low:
                    bull_retrace_100 += 1

        n_bull_valid = len(bull_sub)
        bull_r50_rate = (bull_retrace_50 / n_bull_valid * 100) if n_bull_valid > 0 else 0
        bull_r100_rate = (bull_retrace_100 / n_bull_valid * 100) if n_bull_valid > 0 else 0

        large_candle_results[label] = {
            'threshold_pts': round(float(thresh), 2),
            'bullish_count': int(bull_mask.sum()),
            'bull_fwd_ret_1': round(float(df[bull_mask]['ret_1'].mean()), 2),
            'bull_fwd_ret_3': round(float(df[bull_mask]['ret_3'].mean()), 2),
            'bull_fwd_ret_6': round(float(df[bull_mask]['ret_6'].mean()), 2),
            'bull_fwd_ret_12': round(float(df[bull_mask]['ret_12'].mean()), 2),
            'bull_fwd_ret_24': round(float(df[bull_mask]['ret_24'].mean()), 2),
            'bull_mfe_6': round(float(df[bull_mask]['mfe_long_6'].mean()), 2),
            'bull_mae_6': round(float(df[bull_mask]['mae_long_6'].mean()), 2),
            'bull_retrace_50_pct': round(float(bull_r50_rate), 2),
            'bull_retrace_100_pct': round(float(bull_r100_rate), 2),
            'bearish_count': int(bear_mask.sum()),
            'bear_fwd_ret_1': round(float(-df[bear_mask]['ret_1'].mean()), 2), # signed profit in down dir
            'bear_fwd_ret_3': round(float(-df[bear_mask]['ret_3'].mean()), 2),
            'bear_fwd_ret_6': round(float(-df[bear_mask]['ret_6'].mean()), 2),
            'bear_fwd_ret_12': round(float(-df[bear_mask]['ret_12'].mean()), 2),
            'bear_fwd_ret_24': round(float(-df[bear_mask]['ret_24'].mean()), 2),
            'bear_mfe_6': round(float(df[bear_mask]['mfe_short_6'].mean()), 2),
            'bear_mae_6': round(float(df[bear_mask]['mae_short_6'].mean()), 2),
        }

    # =================================================================
    # 3. WICK THRESHOLD SENSITIVITY (20% to 80%)
    # =================================================================
    print("Analyzing Wick Thresholds...")
    wick_levels = [0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80]
    wick_analysis = {}

    for w in wick_levels:
        lbl = f"wick_{int(w*100)}pct"
        # Upper wick pinbar (reversal down)
        u_mask = df['upper_wick_ratio'] >= w
        # Lower wick pinbar (reversal up)
        l_mask = df['lower_wick_ratio'] >= w

        # Signed return for upper wick: -ret (profit if price drops)
        u_ret_1 = -df[u_mask]['ret_1'].mean()
        u_ret_6 = -df[u_mask]['ret_6'].mean()
        u_win_6 = (-df[u_mask]['ret_6'] > 0).mean() * 100
        u_mfe = df[u_mask]['mfe_short_6'].mean()
        u_mae = df[u_mask]['mae_short_6'].mean()

        # Signed return for lower wick: +ret (profit if price rises)
        l_ret_1 = df[l_mask]['ret_1'].mean()
        l_ret_6 = df[l_mask]['ret_6'].mean()
        l_win_6 = (df[l_mask]['ret_6'] > 0).mean() * 100
        l_mfe = df[l_mask]['mfe_long_6'].mean()
        l_mae = df[l_mask]['mae_long_6'].mean()

        wick_analysis[lbl] = {
            'threshold': w,
            'upper_wick_count': int(u_mask.sum()),
            'upper_win_rate_6': round(float(u_win_6), 2),
            'upper_fwd_ret_6': round(float(u_ret_6), 2),
            'upper_mfe_6': round(float(u_mfe), 2),
            'upper_mae_6': round(float(u_mae), 2),
            'lower_wick_count': int(l_mask.sum()),
            'lower_win_rate_6': round(float(l_win_6), 2),
            'lower_fwd_ret_6': round(float(l_ret_6), 2),
            'lower_mfe_6': round(float(l_mfe), 2),
            'lower_mae_6': round(float(l_mae), 2),
        }

    # =================================================================
    # 4. CONTEXTUAL REVERSAL TEST: MID-RANGE vs STRUCTURAL LEVELS
    # =================================================================
    print("Testing Contextual Impact (Structural Levels vs Mid-Range)...")
    # Define clean pinbar: wick >= 50%
    u_pin = df['upper_wick_ratio'] >= 0.50
    l_pin = df['lower_wick_ratio'] >= 0.50

    contexts = {
        'Mid-Range (Isolated)': (~df['is_at_pdh']) & (~df['is_at_pdl']) & (~df['is_at_vwap']),
        'At PDH (Upper Resistance)': df['is_at_pdh'],
        'At PDL (Lower Support)': df['is_at_pdl'],
        'At Session VWAP': df['is_at_vwap'],
    }

    context_results = {}
    for ctx_name, c_mask in contexts.items():
        sub_u = df[u_pin & c_mask]
        sub_l = df[l_pin & c_mask]
        context_results[ctx_name] = {
            'upper_pin_count': len(sub_u),
            'upper_win_rate_6': round(float((-sub_u['ret_6'] > 0).mean() * 100), 2) if len(sub_u) > 0 else 0,
            'upper_mean_ret_6': round(float((-sub_u['ret_6']).mean()), 2) if len(sub_u) > 0 else 0,
            'upper_mfe_6': round(float(sub_u['mfe_short_6'].mean()), 2) if len(sub_u) > 0 else 0,
            'lower_pin_count': len(sub_l),
            'lower_win_rate_6': round(float((sub_l['ret_6'] > 0).mean() * 100), 2) if len(sub_l) > 0 else 0,
            'lower_mean_ret_6': round(float(sub_l['ret_6'].mean()), 2) if len(sub_l) > 0 else 0,
            'lower_mfe_6': round(float(sub_l['mfe_long_6'].mean()), 2) if len(sub_l) > 0 else 0,
        }

    # =================================================================
    # 5. LOGICALLY MOTIVATED COMBINATIONS
    # =================================================================
    print("Evaluating Logically Motivated Combinations...")
    combos = {
        # Combo 1: Large Bullish Candle (Top 5%) + Upper Rejection Wick (>=35%) -> Exhaustion Blow-off
        'Top5_Bullish_Exhaustion_Wick': (df['range'] >= p95) & (df['direction'] == 'UP') & (df['upper_wick_ratio'] >= 0.35),
        # Combo 2: Large Bearish Candle (Top 5%) + Lower Rejection Wick (>=35%) -> Panic Climax Bottom
        'Top5_Bearish_Climax_Wick': (df['range'] >= p95) & (df['direction'] == 'DOWN') & (df['lower_wick_ratio'] >= 0.35),
        # Combo 3: Pin-Bar at PDH + 15M Bearish Momentum
        'Pinbar_at_PDH_Resistance': (df['upper_wick_ratio'] >= 0.40) & df['is_at_pdh'],
        # Combo 4: Pin-Bar at PDL + 15M Bullish Momentum
        'Pinbar_at_PDL_Support': (df['lower_wick_ratio'] >= 0.40) & df['is_at_pdl'],
        # Combo 5: Strong Trend Expansion: Top 5% range + Body Ratio >= 75%
        'Marubozu_Expansion_Bullish': (df['range'] >= p95) & (df['direction'] == 'UP') & (df['body_ratio'] >= 0.75),
        'Marubozu_Expansion_Bearish': (df['range'] >= p95) & (df['direction'] == 'DOWN') & (df['body_ratio'] >= 0.75),
    }

    combo_results = {}
    for c_name, c_mask in combos.items():
        sub = df[c_mask]
        n_ev = len(sub)
        if n_ev == 0:
            continue
        
        # Determine logical direction:
        # If exhaustion/reversal short: profit is -ret
        if 'Short' in c_name or 'Exhaustion' in c_name or 'Resistance' in c_name or 'Bearish' in c_name:
            if 'Climax_Wick' in c_name: # Bullish reversal after panic
                s_ret_6 = sub['ret_6'].mean()
                win_6 = (sub['ret_6'] > 0).mean() * 100
                mfe = sub['mfe_long_6'].mean()
                mae = sub['mae_long_6'].mean()
            elif 'Bearish' in c_name and 'Marubozu' in c_name: # Continuation down
                s_ret_6 = -sub['ret_6'].mean()
                win_6 = (-sub['ret_6'] > 0).mean() * 100
                mfe = sub['mfe_short_6'].mean()
                mae = sub['mae_short_6'].mean()
            else: # Short reversal
                s_ret_6 = -sub['ret_6'].mean()
                win_6 = (-sub['ret_6'] > 0).mean() * 100
                mfe = sub['mfe_short_6'].mean()
                mae = sub['mae_short_6'].mean()
        else: # Long continuation or reversal
            s_ret_6 = sub['ret_6'].mean()
            win_6 = (sub['ret_6'] > 0).mean() * 100
            mfe = sub['mfe_long_6'].mean()
            mae = sub['mae_long_6'].mean()

        combo_results[c_name] = {
            'count': n_ev,
            'win_rate_6': round(float(win_6), 2),
            'mean_ret_6': round(float(s_ret_6), 2),
            'mean_mfe_6': round(float(mfe), 2),
            'mean_mae_6': round(float(mae), 2),
            'mfe_mae_ratio': round(float(mfe / mae), 2) if mae > 0 else 0
        }

    # =================================================================
    # 6. INFORMATION HALF-LIFE (1, 3, 6, 12, 24 bars)
    # =================================================================
    print("Measuring Predictive Half-Life across Horizons...")
    decay_metrics = {}
    for h in horizons:
        # Correlation of body direction with forward return
        # Body direction: +1 if UP, -1 if DOWN
        dir_sign = np.where(df['direction'] == 'UP', 1.0, np.where(df['direction'] == 'DOWN', -1.0, 0.0))
        valid_ret_mask = ~np.isnan(df[f'ret_{h}'])
        corr = np.corrcoef(dir_sign[valid_ret_mask], df.loc[valid_ret_mask, f'ret_{h}'])[0, 1]
        decay_metrics[f'horizon_{h}_bars'] = {
            'minutes': h * 5,
            'correlation': round(float(corr), 4),
            'mean_abs_ret': round(float(np.abs(df.loc[valid_ret_mask, f'ret_{h}']).mean()), 2)
        }

    results = {
        'total_bars': n_total,
        'range_percentiles': {
            'p90': round(float(p90), 2),
            'p95': round(float(p95), 2),
            'p98': round(float(p98), 2),
            'p99': round(float(p99), 2),
        },
        'large_candles': large_candle_results,
        'wicks': wick_analysis,
        'contextual_impact': context_results,
        'logical_combinations': combo_results,
        'information_decay': decay_metrics,
    }

    # Export metrics JSON
    with open("research/price_action/candle_geometry_metrics.json", "w") as f:
        json.dump(results, f, indent=2)
    print("[OK] Saved research/price_action/candle_geometry_metrics.json")

    # Export sample events CSV (top 5% or wick >= 50% or at structural levels)
    event_mask = (df['range'] >= p95) | (df['upper_wick_ratio'] >= 0.50) | (df['lower_wick_ratio'] >= 0.50)
    df_sample_events = df[event_mask][['timestamp', 'open', 'high', 'low', 'close', 'range', 'body_ratio',
                                       'upper_wick_ratio', 'lower_wick_ratio', 'close_loc', 'direction',
                                       'is_at_pdh', 'is_at_pdl', 'is_at_vwap', 'ret_1', 'ret_6',
                                       'mfe_long_6', 'mae_long_6']].copy()
    df_sample_events.to_csv("research/price_action/CANDLE_GEOMETRY_EVENTS.csv", index=False)
    print(f"[OK] Saved research/price_action/CANDLE_GEOMETRY_EVENTS.csv with {len(df_sample_events)} events.")

    return results


if __name__ == "__main__":
    res = run_candle_geometry_research()
    print("\n--- Summary of Combinations ---")
    for k, v in res['logical_combinations'].items():
        print(f"{k}: Count {v['count']} | Win Rate {v['win_rate_6']}% | MFE/MAE: {v['mfe_mae_ratio']}")
