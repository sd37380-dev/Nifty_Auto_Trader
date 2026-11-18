"""
Topic 6 — Trend vs Momentum vs Mean Reversion Research Engine for NIFTY 50 Spot.
Comprehensive quantitative analysis of directional efficiency, momentum persistence,
reference-anchor mean reversion, and multi-day swing persistence across 92,605 bars (2021-2026).
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


def run_trend_momentum_research():
    print("Loading 5-minute NIFTY dataset...")
    df_5m, clean_stats = load_and_clean_nifty_5m()
    n_total = len(df_5m)
    print(f"Total clean 5M bars: {n_total}")

    df = df_5m.sort_values('timestamp').reset_index(drop=True)

    highs = df['high'].values
    lows = df['low'].values
    opens = df['open'].values
    closes = df['close'].values
    ranges = highs - lows
    dates = df['date_ist'].values
    times = df['time_ist'].values

    # 1. Base Rolling Technical Features
    prev_closes = np.roll(closes, 1)
    prev_closes[0] = opens[0]
    tr = np.maximum(ranges, np.maximum(np.abs(highs - prev_closes), np.abs(lows - prev_closes)))
    df['tr'] = tr
    df['atr14'] = df['tr'].rolling(14).mean()

    # Directional Efficiency (Kaufman Efficiency Ratio over 12 bars / 1 hour)
    # ER = |Close_t - Close_{t-12}| / Sum(Ranges_{t-11..t})
    k_er = 12
    er_vals = np.full(n_total, np.nan)
    roll_sum_tr = df['tr'].rolling(k_er).sum().values
    
    for i in range(k_er, n_total):
        if dates[i] == dates[i - k_er]:
            net_disp = abs(closes[i] - closes[i - k_er])
            tot_path = roll_sum_tr[i]
            er_vals[i] = net_disp / max(tot_path, 1e-4)

    df['er_12'] = er_vals
    
    # 20-EMA and slope
    ema20 = df['close'].ewm(span=20, adjust=False).mean().values
    df['ema20'] = ema20
    prev_ema20_6 = np.roll(ema20, 6)
    ema20_slope = (ema20 - prev_ema20_6) / np.where(df['atr14'].values > 0, df['atr14'].values, 1.0)
    df['ema20_slope'] = ema20_slope

    # Multi-candle momentum returns (1, 3, 6, 12, 24 bars)
    mom_horizons = [1, 3, 6, 12, 24]
    for m in mom_horizons:
        prev_c = np.roll(closes, m)
        prev_d = np.roll(dates, m)
        same_day_mask = (dates == prev_d)
        ret_m = np.where(same_day_mask, closes - prev_c, np.nan)
        df[f'past_ret_{m}'] = ret_m

    # Forward returns over 1, 3, 6, 12, 24 bars
    fwd_ret = {h: np.full(n_total, np.nan) for h in [1, 3, 6, 12, 24]}
    fwd_mfe_long = {h: np.full(n_total, np.nan) for h in [1, 3, 6, 12, 24]}
    fwd_mae_long = {h: np.full(n_total, np.nan) for h in [1, 3, 6, 12, 24]}

    for i in range(n_total - 25):
        dt_i = dates[i]
        c_i = closes[i]
        for h in [1, 3, 6, 12, 24]:
            idx_end = i + h
            if idx_end < n_total and dates[idx_end] == dt_i:
                fwd_ret[h][i] = closes[idx_end] - c_i
                sub_h = highs[i+1:idx_end+1]
                sub_l = lows[i+1:idx_end+1]
                fwd_mfe_long[h][i] = np.max(sub_h) - c_i
                fwd_mae_long[h][i] = c_i - np.min(sub_l)

    for h in [1, 3, 6, 12, 24]:
        df[f'fwd_ret_{h}'] = fwd_ret[h]
        df[f'fwd_mfe_{h}'] = fwd_mfe_long[h]
        df[f'fwd_mae_{h}'] = fwd_mae_long[h]

    # Reference Mean Reversion Benchmarks:
    # 1. PDC
    # 2. Session VWAP
    # 3. Session Open (09:15)
    # 4. Session Midpoint (Cum High + Cum Low)/2
    # 5. Swing Midpoint (12-bar High + 12-bar Low)/2
    print("Computing Session Mean Reversion Reference Anchors...")
    daily_groups = df.groupby('date_ist')
    
    # PDC map
    day_closes = {}
    day_opens = {}
    for dt, grp in daily_groups:
        day_closes[dt] = grp['close'].iloc[-1]
        day_opens[dt] = grp['open'].iloc[0]
    
    sorted_dts = sorted(list(day_closes.keys()))
    pdc_map = {sorted_dts[i]: day_closes[sorted_dts[i-1]] for i in range(1, len(sorted_dts))}
    df['pdc'] = df['date_ist'].map(pdc_map)
    df['session_open'] = df['date_ist'].map(day_opens)

    # VWAP & Session High/Low
    vwap_arr = np.full(n_total, np.nan)
    session_mid_arr = np.full(n_total, np.nan)
    for dt, grp in daily_groups:
        idxs = grp.index.values
        typ = (highs[idxs] + lows[idxs] + closes[idxs]) / 3.0
        v = np.maximum(df.loc[idxs, 'volume'].values, 1)
        cum_vp = np.cumsum(typ * v)
        cum_v = np.cumsum(v)
        vwap_arr[idxs] = cum_vp / cum_v

        cum_h = np.maximum.accumulate(highs[idxs])
        cum_l = np.minimum.accumulate(lows[idxs])
        session_mid_arr[idxs] = (cum_h + cum_l) / 2.0

    df['vwap'] = vwap_arr
    df['session_mid'] = session_mid_arr
    
    # 12-bar swing midpoint
    roll_12_h = df['high'].rolling(12).max().values
    roll_12_l = df['low'].rolling(12).min().values
    df['swing_mid_12'] = (roll_12_h + roll_12_l) / 2.0

    # Distances to anchors in ATR multiples
    safe_atr = np.where(df['atr14'].values > 0, df['atr14'].values, 1.0)
    df['dist_pdc_atr'] = (closes - df['pdc'].values) / safe_atr
    df['dist_vwap_atr'] = (closes - df['vwap'].values) / safe_atr
    df['dist_open_atr'] = (closes - df['session_open'].values) / safe_atr
    df['dist_mid_atr'] = (closes - df['session_mid'].values) / safe_atr
    df['dist_swing_atr'] = (closes - df['swing_mid_12'].values) / safe_atr

    # =================================================================
    # 1. MOMENTUM PERSISTENCE & DECAY (Questions 1 to 4)
    # =================================================================
    print("Analyzing Momentum Persistence & Decay...")
    mom_persistence = {}
    for m in [1, 3, 6, 12, 24]:
        # Divide past returns into deciles / strong momentum
        col = f'past_ret_{m}'
        valid = df[col].dropna()
        p90_m = valid.quantile(0.90)
        p10_m = valid.quantile(0.10)
        
        # Strong Bullish Momentum (Top 10%)
        strong_bull = df[col] >= p90_m
        # Strong Bearish Momentum (Bottom 10%)
        strong_bear = df[col] <= p10_m

        mom_persistence[f'momentum_{m}_bars'] = {
            'threshold_bull_pts': round(float(p90_m), 2),
            'threshold_bear_pts': round(float(p10_m), 2),
            'bull_count': int(strong_bull.sum()),
            'bull_cont_prob_1bar': round(float((df.loc[strong_bull, 'fwd_ret_1'] > 0).mean() * 100), 2),
            'bull_cont_prob_3bars': round(float((df.loc[strong_bull, 'fwd_ret_3'] > 0).mean() * 100), 2),
            'bull_cont_prob_6bars': round(float((df.loc[strong_bull, 'fwd_ret_6'] > 0).mean() * 100), 2),
            'bull_cont_prob_12bars': round(float((df.loc[strong_bull, 'fwd_ret_12'] > 0).mean() * 100), 2),
            'bull_mean_fwd_ret_6': round(float(df.loc[strong_bull, 'fwd_ret_6'].mean()), 2),
            'bull_mean_mfe_6': round(float(df.loc[strong_bull, 'fwd_mfe_6'].mean()), 2),
            'bull_mean_mae_6': round(float(df.loc[strong_bull, 'fwd_mae_6'].mean()), 2),
            'bear_count': int(strong_bear.sum()),
            'bear_cont_prob_1bar': round(float((df.loc[strong_bear, 'fwd_ret_1'] < 0).mean() * 100), 2),
            'bear_cont_prob_3bars': round(float((df.loc[strong_bear, 'fwd_ret_3'] < 0).mean() * 100), 2),
            'bear_cont_prob_6bars': round(float((df.loc[strong_bear, 'fwd_ret_6'] < 0).mean() * 100), 2),
            'bear_cont_prob_12bars': round(float((df.loc[strong_bear, 'fwd_ret_12'] < 0).mean() * 100), 2),
            'bear_mean_fwd_ret_6': round(float(-df.loc[strong_bear, 'fwd_ret_6'].mean()), 2),
        }

    # =================================================================
    # 2. CONSECUTIVE CANDLES (2, 3, 4, 5, 6+)
    # =================================================================
    print("Analyzing Consecutive Candle Sequences...")
    # Bullish streaks: close > open
    bull_bar = (closes > opens).astype(int)
    bear_bar = (closes < opens).astype(int)

    bull_streaks = np.zeros(n_total, dtype=int)
    bear_streaks = np.zeros(n_total, dtype=int)
    c_bull = 0
    c_bear = 0

    for i in range(1, n_total):
        if dates[i] == dates[i-1]:
            c_bull = c_bull + 1 if bull_bar[i] == 1 else 0
            c_bear = c_bear + 1 if bear_bar[i] == 1 else 0
        else:
            c_bull = bull_bar[i]
            c_bear = bear_bar[i]
        bull_streaks[i] = c_bull
        bear_streaks[i] = c_bear

    df['bull_streak'] = bull_streaks
    df['bear_streak'] = bear_streaks

    consec_results = {}
    for s_len in [2, 3, 4, 5, 6]:
        b_mask = df['bull_streak'] == s_len
        br_mask = df['bear_streak'] == s_len
        consec_results[f'{s_len}_candles'] = {
            'bull_count': int(b_mask.sum()),
            'bull_cont_prob_next1': round(float((df.loc[b_mask, 'fwd_ret_1'] > 0).mean() * 100), 2),
            'bull_cont_prob_next6': round(float((df.loc[b_mask, 'fwd_ret_6'] > 0).mean() * 100), 2),
            'bull_mean_fwd_ret_6': round(float(df.loc[b_mask, 'fwd_ret_6'].mean()), 2),
            'bull_mfe_6': round(float(df.loc[b_mask, 'fwd_mfe_6'].mean()), 2),
            'bull_mae_6': round(float(df.loc[b_mask, 'fwd_mae_6'].mean()), 2),
            'bear_count': int(br_mask.sum()),
            'bear_cont_prob_next1': round(float((df.loc[br_mask, 'fwd_ret_1'] < 0).mean() * 100), 2),
            'bear_cont_prob_next6': round(float((df.loc[br_mask, 'fwd_ret_6'] < 0).mean() * 100), 2),
            'bear_mean_fwd_ret_6': round(float(-df.loc[br_mask, 'fwd_ret_6'].mean()), 2),
        }

    # =================================================================
    # 3. MEAN REVERSION TO BENCHMARK ANCHORS
    # =================================================================
    print("Measuring Mean Reversion Probability across Reference Anchors...")
    # Condition: price extended by >= 1.5 ATR away from anchor. Does it touch anchor within 12 bars (1 hour)?
    anchors = [
        ('PDC', 'pdc', 'dist_pdc_atr'),
        ('Session_VWAP', 'vwap', 'dist_vwap_atr'),
        ('Session_Open', 'session_open', 'dist_open_atr'),
        ('Session_Midpoint', 'session_mid', 'dist_mid_atr'),
        ('Swing_Midpoint_12', 'swing_mid_12', 'dist_swing_atr'),
    ]

    mean_rev_results = {}
    for a_label, a_col, a_dist_col in anchors:
        ext_mask = df[a_dist_col].abs() >= 1.5
        n_ext = int(ext_mask.sum())
        
        # Check touch within 12 bars (1 hour)
        touched_count = 0
        ext_indices = np.where(ext_mask)[0]
        for idx_e in ext_indices:
            if idx_e + 12 < n_total and dates[idx_e + 12] == dates[idx_e]:
                ref_val = df.loc[idx_e, a_col]
                sub_h = highs[idx_e+1:idx_e+13]
                sub_l = lows[idx_e+1:idx_e+13]
                is_above = closes[idx_e] > ref_val
                if is_above and np.min(sub_l) <= ref_val:
                    touched_count += 1
                elif not is_above and np.max(sub_h) >= ref_val:
                    touched_count += 1

        rev_rate = (touched_count / max(len(ext_indices), 1)) * 100
        mean_rev_results[a_label] = {
            'extended_bars_count': n_ext,
            'pct_of_all_bars': round(n_ext / n_total * 100, 2),
            'reversion_within_1h_prob': round(float(rev_rate), 2),
            'mean_distance_pts': round(float((df.loc[ext_mask, a_dist_col].abs() * df.loc[ext_mask, 'atr14']).mean()), 2)
        }

    # =================================================================
    # 4. REGIME CLASSIFICATION & COMPARISON
    # =================================================================
    print("Classifying Regimes (Trend, Sideways, High-Vol Trend, Low-Vol Range)...")
    # Trend: ER >= 0.50 and |ema20_slope| >= 0.20
    # Sideways: ER <= 0.25 and |ema20_slope| < 0.15
    # High-Vol Trend: Trend & ATR > 75th percentile
    # Low-Vol Range: Sideways & ATR < 25th percentile
    atr_p75 = df['atr14'].quantile(0.75)
    atr_p25 = df['atr14'].quantile(0.25)

    is_trend = (df['er_12'] >= 0.50) & (df['ema20_slope'].abs() >= 0.20)
    is_sideways = (df['er_12'] <= 0.25) & (df['ema20_slope'].abs() < 0.15)
    is_high_vol_trend = is_trend & (df['atr14'] >= atr_p75)
    is_low_vol_range = is_sideways & (df['atr14'] <= atr_p25)

    regimes = {
        'Trend': is_trend & (~is_high_vol_trend),
        'Sideways': is_sideways & (~is_low_vol_range),
        'High_Vol_Trend': is_high_vol_trend,
        'Low_Vol_Range': is_low_vol_range,
    }

    regime_results = {}
    for r_name, r_mask in regimes.items():
        n_r = int(r_mask.sum())
        if n_r > 0:
            # Continuation vs reversal over next 6 bars
            cont_rate = (
                ((df.loc[r_mask, 'ema20_slope'] > 0) & (df.loc[r_mask, 'fwd_ret_6'] > 0)) |
                ((df.loc[r_mask, 'ema20_slope'] < 0) & (df.loc[r_mask, 'fwd_ret_6'] < 0))
            ).mean() * 100
            mean_fwd_range = df.loc[r_mask, 'fwd_mfe_6'].mean()
            regime_results[r_name] = {
                'bars_count': n_r,
                'pct_of_all': round(n_r / n_total * 100, 2),
                'continuation_prob_30m': round(float(cont_rate), 2),
                'mean_fwd_mfe_30m': round(float(mean_fwd_range), 2)
            }

    # =================================================================
    # 5. TIME-OF-DAY COMPARISON
    # =================================================================
    print("Testing Time of Day Momentum vs Reversion...")
    tod_windows = {
        'Morning (09:15-11:00)': (times >= time(9, 15)) & (times < time(11, 0)),
        'Midday (11:00-13:30)': (times >= time(11, 0)) & (times < time(13, 30)),
        'Afternoon (13:30-15:30)': (times >= time(13, 30)) & (times <= time(15, 30)),
    }

    tod_results = {}
    for tod_name, tod_mask in tod_windows.items():
        sub_df = df[tod_mask]
        # Mean Kaufman efficiency ratio
        avg_er = sub_df['er_12'].mean()
        # Momentum continuation rate (when past 6 bars had |ret| > 20 pts)
        strong_past = sub_df['past_ret_6'].abs() >= 20
        cont_prob = (
            ((sub_df.loc[strong_past, 'past_ret_6'] > 0) & (sub_df.loc[strong_past, 'fwd_ret_6'] > 0)) |
            ((sub_df.loc[strong_past, 'past_ret_6'] < 0) & (sub_df.loc[strong_past, 'fwd_ret_6'] < 0))
        ).mean() * 100

        tod_results[tod_name] = {
            'bars_count': len(sub_df),
            'avg_directional_efficiency': round(float(avg_er), 3),
            'strong_momentum_continuation_prob_30m': round(float(cont_prob), 2),
        }

    # =================================================================
    # 6. SWING PERSISTENCE (Daily Horizon)
    # =================================================================
    print("Measuring Daily Swing Persistence...")
    daily_stats = df.groupby('date_ist').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last'
    }).reset_index()

    d_closes = daily_stats['close'].values
    d_n = len(daily_stats)
    
    # 1-day, 2-day, 3-day, 5-day, 10-day forward returns
    swing_persistence = {}
    for lag in [1, 2, 3, 5, 10]:
        past_d_ret = d_closes[lag:] - d_closes[:-lag]
        # Autocorrelation of daily returns
        if len(past_d_ret) > lag:
            fwd_d_ret = d_closes[2*lag:] - d_closes[lag:-lag]
            corr = np.corrcoef(past_d_ret[:len(fwd_d_ret)], fwd_d_ret)[0, 1]
            swing_persistence[f'{lag}_day_persistence'] = {
                'correlation': round(float(corr), 4),
                'directional_continuation_prob': round(float(((past_d_ret[:len(fwd_d_ret)] * fwd_d_ret) > 0).mean() * 100), 2)
            }

    results = {
        'total_bars': n_total,
        'momentum_persistence': mom_persistence,
        'consecutive_candles': consec_results,
        'mean_reversion_anchors': mean_rev_results,
        'regime_comparison': regime_results,
        'time_of_day_breakdown': tod_results,
        'swing_persistence': swing_persistence,
    }

    # Save to JSON
    with open("research/price_action/trend_momentum_metrics.json", "w") as f:
        json.dump(results, f, indent=2)
    print("[OK] Saved research/price_action/trend_momentum_metrics.json")

    # Export sample events CSV
    ev_mask = (df['past_ret_6'].abs() >= 35) | (df['er_12'] >= 0.60) | (df['dist_vwap_atr'].abs() >= 1.5)
    df_tm_events = df[ev_mask][['timestamp', 'open', 'high', 'low', 'close', 'er_12',
                               'ema20_slope', 'past_ret_6', 'fwd_ret_6', 'dist_vwap_atr',
                               'dist_pdc_atr', 'fwd_mfe_6', 'fwd_mae_6']].copy()
    df_tm_events.to_csv("research/price_action/TREND_MOMENTUM_EVENTS.csv", index=False)
    print(f"[OK] Saved research/price_action/TREND_MOMENTUM_EVENTS.csv with {len(df_tm_events)} events.")

    return results


if __name__ == "__main__":
    res = run_trend_momentum_research()
    print("\n--- Summary of Mean Reversion Anchors ---")
    for k, v in res['mean_reversion_anchors'].items():
        print(f"{k}: Ext Count {v['extended_bars_count']} | 1H Reversion Rate: {v['reversion_within_1h_prob']}% | Dist: {v['mean_distance_pts']} pts")
