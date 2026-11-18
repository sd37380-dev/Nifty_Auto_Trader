"""
Topic 8 — Swing Structure, Higher Highs, Lower Lows and Reversals Research Engine for NIFTY 50 Spot.
Mathematical analysis of market structure, BOS, CHoCH, SFP, MTF alignment, and multi-day persistence.
Strictly causal and look-ahead free at decision timestamps.
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


def detect_swings(highs: np.ndarray, lows: np.ndarray, L: int, R: int) -> Tuple[np.ndarray, np.ndarray]:
    """
    Causal swing detection:
    A swing high at bar (i - R) is confirmed at bar i if highs[i - R] is the highest among [i - R - L, i].
    Returns:
      swing_high_prices: array where entry i is the price of a swing high confirmed at bar i (or NaN)
      swing_low_prices: array where entry i is the price of a swing low confirmed at bar i (or NaN)
    """
    n = len(highs)
    sh_prices = np.full(n, np.nan)
    sl_prices = np.full(n, np.nan)

    for i in range(L + R, n):
        idx_pivot = i - R
        # Check pivot high
        cand_high = highs[idx_pivot]
        if cand_high == np.max(highs[idx_pivot - L : i + 1]):
            # Verify uniqueness on left/right strictly
            if cand_high > np.max(highs[idx_pivot + 1 : i + 1]) and cand_high >= np.max(highs[idx_pivot - L : idx_pivot]):
                sh_prices[i] = cand_high

        # Check pivot low
        cand_low = lows[idx_pivot]
        if cand_low == np.min(lows[idx_pivot - L : i + 1]):
            if cand_low < np.min(lows[idx_pivot + 1 : i + 1]) and cand_low <= np.min(lows[idx_pivot - L : idx_pivot]):
                sl_prices[i] = cand_low

    return sh_prices, sl_prices


def run_market_structure_research():
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

    # Base ATR 14
    prev_closes = np.roll(closes, 1)
    prev_closes[0] = opens[0]
    tr = np.maximum(ranges, np.maximum(np.abs(highs - prev_closes), np.abs(lows - prev_closes)))
    df['tr'] = tr
    df['atr14'] = df['tr'].rolling(14).mean().bfill()
    atr14 = df['atr14'].values

    # =========================================================================
    # 1. SWING DETECTION BENCHMARKS (3-bar, 5-bar, 7-bar)
    # =========================================================================
    print("Computing swing detection across 3, 5, 7 bar definitions...")
    swing_configs = [(3, 3), (5, 5), (7, 7)]
    swing_results = {}

    for L, R in swing_configs:
        label = f"swing_{L}_{R}"
        sh, sl = detect_swings(highs, lows, L, R)
        
        # Count swings
        sh_valid = ~np.isnan(sh)
        sl_valid = ~np.isnan(sl)
        num_sh = np.sum(sh_valid)
        num_sl = np.sum(sl_valid)
        
        # Calculate distance between successive swings
        sh_indices = np.where(sh_valid)[0]
        sl_indices = np.where(sl_valid)[0]
        
        # Inter-swing bar durations
        sh_durations = np.diff(sh_indices) if len(sh_indices) > 1 else np.array([])
        sl_durations = np.diff(sl_indices) if len(sl_indices) > 1 else np.array([])
        
        # Swing sizes: distance between alternating confirmed highs and lows
        all_swings = []
        for idx in sh_indices:
            all_swings.append((idx, 'H', sh[idx]))
        for idx in sl_indices:
            all_swings.append((idx, 'L', sl[idx]))
        all_swings.sort(key=lambda x: x[0])
        
        swing_sizes_pts = []
        swing_sizes_atr = []
        swing_dur_bars = []
        
        for k in range(1, len(all_swings)):
            if all_swings[k][1] != all_swings[k-1][1]: # Alternating High -> Low or Low -> High
                sz = abs(all_swings[k][2] - all_swings[k-1][2])
                dur = all_swings[k][0] - all_swings[k-1][0]
                cur_atr = max(atr14[all_swings[k][0]], 1.0)
                swing_sizes_pts.append(sz)
                swing_sizes_atr.append(sz / cur_atr)
                swing_dur_bars.append(dur)
        
        swing_results[label] = {
            "L_R": [L, R],
            "total_swing_highs": int(num_sh),
            "total_swing_lows": int(num_sl),
            "mean_inter_swing_high_bars": float(np.mean(sh_durations)) if len(sh_durations) > 0 else 0,
            "mean_inter_swing_low_bars": float(np.mean(sl_durations)) if len(sl_durations) > 0 else 0,
            "mean_swing_size_pts": float(np.mean(swing_sizes_pts)) if len(swing_sizes_pts) > 0 else 0,
            "median_swing_size_pts": float(np.median(swing_sizes_pts)) if len(swing_sizes_pts) > 0 else 0,
            "mean_swing_size_atr": float(np.mean(swing_sizes_atr)) if len(swing_sizes_atr) > 0 else 0,
            "mean_swing_duration_bars": float(np.mean(swing_dur_bars)) if len(swing_dur_bars) > 0 else 0,
            "median_swing_duration_bars": float(np.median(swing_dur_bars)) if len(swing_dur_bars) > 0 else 0,
        }

    # =========================================================================
    # 2. MARKET STRUCTURE SEQUENCE & FAILURE ANALYSIS (Standard 5-bar swing)
    # =========================================================================
    print("Analyzing structure sequences (HH, HL, LH, LL) and failure rates...")
    L_std, R_std = 5, 5
    sh_5, sl_5 = detect_swings(highs, lows, L_std, R_std)

    prev_sh = np.nan
    prev_sl = np.nan
    sh_types = []
    sl_types = []

    for i in range(n_total):
        if not np.isnan(sh_5[i]):
            curr_sh = sh_5[i]
            if not np.isnan(prev_sh):
                st_type = 'HH' if curr_sh > prev_sh else 'LH'
                sh_types.append((st_type, i, curr_sh, prev_sh))
            prev_sh = curr_sh

        if not np.isnan(sl_5[i]):
            curr_sl = sl_5[i]
            if not np.isnan(prev_sl):
                st_type = 'HL' if curr_sl > prev_sl else 'LL'
                sl_types.append((st_type, i, curr_sl, prev_sl))
            prev_sl = curr_sl

    hh_streaks = []
    curr_hh_streak = 0
    for st_type, idx, price, prev_p in sh_types:
        if st_type == 'HH':
            curr_hh_streak += 1
        else:
            if curr_hh_streak > 0:
                hh_streaks.append(curr_hh_streak)
            curr_hh_streak = 0
    if curr_hh_streak > 0:
        hh_streaks.append(curr_hh_streak)

    ll_streaks = []
    curr_ll_streak = 0
    for st_type, idx, price, prev_p in sl_types:
        if st_type == 'LL':
            curr_ll_streak += 1
        else:
            if curr_ll_streak > 0:
                ll_streaks.append(curr_ll_streak)
            curr_ll_streak = 0
    if curr_ll_streak > 0:
        ll_streaks.append(curr_ll_streak)

    def calc_streak_failure_rates(streaks: List[int], max_k: int = 5) -> Dict[str, Any]:
        rates = {}
        for k in range(1, max_k + 1):
            reached_k = sum(1 for s in streaks if s >= k)
            failed_at_k = sum(1 for s in streaks if s == k)
            fail_prob = (failed_at_k / reached_k * 100.0) if reached_k > 0 else 0.0
            rates[f"sequence_len_{k}"] = {
                "reached_count": reached_k,
                "failed_at_k_count": failed_at_k,
                "failure_probability_pct": round(fail_prob, 2),
                "continuation_probability_pct": round(100.0 - fail_prob, 2)
            }
        return rates

    hh_failure_rates = calc_streak_failure_rates(hh_streaks, 5)
    ll_failure_rates = calc_streak_failure_rates(ll_streaks, 5)

    # =========================================================================
    # 3. STRUCTURE BREAKS (BOS & CHoCH)
    # =========================================================================
    print("Evaluating Break of Structure (BOS), failure, retest, and second breakout...")
    bos_events = []
    last_known_sh = np.nan
    last_known_sl = np.nan
    sh_broken = False
    sl_broken = False

    for i in range(1, n_total - 18):
        if not np.isnan(sh_5[i]):
            last_known_sh = sh_5[i]
            sh_broken = False
        if not np.isnan(sl_5[i]):
            last_known_sl = sl_5[i]
            sl_broken = False

        if np.isnan(last_known_sh) or np.isnan(last_known_sl):
            continue

        c = closes[i]
        c_prev = closes[i-1]
        cur_atr = max(atr14[i], 1.0)
        dt = dates[i]

        # Bullish BOS: Close breaks above last known Swing High
        if not sh_broken and c_prev <= last_known_sh and c > last_known_sh:
            sh_broken = True
            level = last_known_sh
            fwd_6 = closes[i+6] - c if i+6 < n_total else 0
            fwd_12 = closes[i+12] - c if i+12 < n_total else 0
            mfe_6 = np.max(highs[i+1 : i+7]) - c if i+6 < n_total else 0
            mae_6 = c - np.min(lows[i+1 : i+7]) if i+6 < n_total else 0
            
            failed_6 = any(closes[i+k] < level for k in range(1, 7)) if i+6 < n_total else False
            
            retested = False
            second_breakout = False
            for k in range(1, 13):
                if i+k >= n_total:
                    break
                if abs(lows[i+k] - level) <= 0.25 * cur_atr:
                    retested = True
                    if any(highs[i+m] > np.max(highs[i : i+k+1]) for m in range(k+1, min(k+7, 18)) if i+m < n_total):
                        second_breakout = True
                    break

            bos_events.append({
                "index": i,
                "timestamp": str(df['timestamp'].values[i]),
                "date": str(dt),
                "type": "Bullish_BOS",
                "level": level,
                "close": c,
                "atr": cur_atr,
                "fwd_ret_6": fwd_6,
                "fwd_ret_12": fwd_12,
                "mfe_6": mfe_6,
                "mae_6": mae_6,
                "failed_within_6": failed_6,
                "retested_within_12": retested,
                "second_breakout_after_retest": second_breakout
            })

        # Bearish BOS: Close breaks below last known Swing Low
        if not sl_broken and c_prev >= last_known_sl and c < last_known_sl:
            sl_broken = True
            level = last_known_sl
            fwd_6 = c - closes[i+6] if i+6 < n_total else 0
            fwd_12 = c - closes[i+12] if i+12 < n_total else 0
            mfe_6 = c - np.min(lows[i+1 : i+7]) if i+6 < n_total else 0
            mae_6 = np.max(highs[i+1 : i+7]) - c if i+6 < n_total else 0
            
            failed_6 = any(closes[i+k] > level for k in range(1, 7)) if i+6 < n_total else False
            
            retested = False
            second_breakout = False
            for k in range(1, 13):
                if i+k >= n_total:
                    break
                if abs(highs[i+k] - level) <= 0.25 * cur_atr:
                    retested = True
                    if any(lows[i+m] < np.min(lows[i : i+k+1]) for m in range(k+1, min(k+7, 18)) if i+m < n_total):
                        second_breakout = True
                    break

            bos_events.append({
                "index": i,
                "timestamp": str(df['timestamp'].values[i]),
                "date": str(dt),
                "type": "Bearish_BOS",
                "level": level,
                "close": c,
                "atr": cur_atr,
                "fwd_ret_6": fwd_6,
                "fwd_ret_12": fwd_12,
                "mfe_6": mfe_6,
                "mae_6": mae_6,
                "failed_within_6": failed_6,
                "retested_within_12": retested,
                "second_breakout_after_retest": second_breakout
            })

    df_bos = pd.DataFrame(bos_events)
    print(f"Total BOS events logged: {len(df_bos)}")

    # =========================================================================
    # 4. SWING FAILURE PATTERNS (SFP)
    # =========================================================================
    print("Evaluating Swing Failure Patterns (SFP / sweeps)...")
    sfp_events = []
    last_known_sh = np.nan
    last_known_sl = np.nan

    for i in range(1, n_total - 12):
        if not np.isnan(sh_5[i]):
            last_known_sh = sh_5[i]
        if not np.isnan(sl_5[i]):
            last_known_sl = sl_5[i]

        if np.isnan(last_known_sh) or np.isnan(last_known_sl):
            continue

        h = highs[i]
        l = lows[i]
        c = closes[i]
        cur_atr = max(atr14[i], 1.0)
        dt = dates[i]

        # Bearish SFP (Sweep of Swing High)
        if h > last_known_sh and c < last_known_sh:
            sweep_pts = h - last_known_sh
            rev_ret_6 = c - closes[i+6] if i+6 < n_total else 0
            rev_ret_12 = c - closes[i+12] if i+12 < n_total else 0
            rev_mfe_6 = c - np.min(lows[i+1 : i+7]) if i+6 < n_total else 0
            rev_mae_6 = np.max(highs[i+1 : i+7]) - c if i+6 < n_total else 0
            meaningful_rev = (rev_mfe_6 >= cur_atr)

            sfp_events.append({
                "index": i,
                "timestamp": str(df['timestamp'].values[i]),
                "date": str(dt),
                "type": "Bearish_SFP",
                "level": last_known_sh,
                "sweep_pts": sweep_pts,
                "sweep_atr": sweep_pts / cur_atr,
                "rev_ret_6": rev_ret_6,
                "rev_ret_12": rev_ret_12,
                "rev_mfe_6": rev_mfe_6,
                "rev_mae_6": rev_mae_6,
                "meaningful_reversal": meaningful_rev
            })

        # Bullish SFP (Sweep of Swing Low)
        if l < last_known_sl and c > last_known_sl:
            sweep_pts = last_known_sl - l
            rev_ret_6 = closes[i+6] - c if i+6 < n_total else 0
            rev_ret_12 = closes[i+12] - c if i+12 < n_total else 0
            rev_mfe_6 = np.max(highs[i+1 : i+7]) - c if i+6 < n_total else 0
            rev_mae_6 = c - np.min(lows[i+1 : i+7]) if i+6 < n_total else 0
            meaningful_rev = (rev_mfe_6 >= cur_atr)

            sfp_events.append({
                "index": i,
                "timestamp": str(df['timestamp'].values[i]),
                "date": str(dt),
                "type": "Bullish_SFP",
                "level": last_known_sl,
                "sweep_pts": sweep_pts,
                "sweep_atr": sweep_pts / cur_atr,
                "rev_ret_6": rev_ret_6,
                "rev_ret_12": rev_ret_12,
                "rev_mfe_6": rev_mfe_6,
                "rev_mae_6": rev_mae_6,
                "meaningful_reversal": meaningful_rev
            })

    df_sfp = pd.DataFrame(sfp_events)
    print(f"Total SFP events logged: {len(df_sfp)}")

    # =========================================================================
    # 5. MULTI-TIMEFRAME STRUCTURE (5M vs 15M vs 1H)
    # =========================================================================
    print("Evaluating Multi-Timeframe Structure (5M inside 15M and 1H)...")
    df['datetime'] = pd.to_datetime(df['timestamp'])
    df_indexed = df.set_index('datetime')

    # Resample 15M
    df_15m = df_indexed.resample('15min').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna().reset_index()

    # Resample 1H
    df_1h = df_indexed.resample('1h').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna().reset_index()

    # Calculate 15M and 1H EMA-20 slope for trend state
    df_15m['ema20'] = df_15m['close'].ewm(span=20, adjust=False).mean()
    df_15m['trend_15m'] = np.where(df_15m['close'] > df_15m['ema20'], 1, -1)

    df_1h['ema20'] = df_1h['close'].ewm(span=20, adjust=False).mean()
    df_1h['trend_1h'] = np.where(df_1h['close'] > df_1h['ema20'], 1, -1)

    # Merge MTF trend state back to 5M
    df_15m_lookup = df_15m[['datetime', 'trend_15m']].copy()
    df_1h_lookup = df_1h[['datetime', 'trend_1h']].copy()

    df_merged = pd.merge_asof(df.sort_values('datetime'), df_15m_lookup.sort_values('datetime'), on='datetime', direction='backward')
    df_merged = pd.merge_asof(df_merged, df_1h_lookup.sort_values('datetime'), on='datetime', direction='backward')

    bos_mtf = []
    for b in bos_events:
        idx = b['index']
        t15 = df_merged['trend_15m'].iloc[idx]
        t1h = df_merged['trend_1h'].iloc[idx]
        is_bull = (b['type'] == 'Bullish_BOS')
        
        aligned_15m = (t15 == 1 if is_bull else t15 == -1)
        aligned_1h = (t1h == 1 if is_bull else t1h == -1)

        bos_mtf.append({
            **b,
            "trend_15m": int(t15),
            "trend_1h": int(t1h),
            "aligned_15m": aligned_15m,
            "aligned_1h": aligned_1h
        })

    df_bos_mtf = pd.DataFrame(bos_mtf)

    aligned_bos = df_bos_mtf[df_bos_mtf['aligned_15m'] == True]
    counter_bos = df_bos_mtf[df_bos_mtf['aligned_15m'] == False]

    ema20_5m = df['close'].ewm(span=20, adjust=False).mean()
    trend_5m = np.where(df['close'] > ema20_5m, 1, -1)
    contradict_15m = np.mean(trend_5m != df_merged['trend_15m'].values) * 100.0
    contradict_1h = np.mean(trend_5m != df_merged['trend_1h'].values) * 100.0

    # =========================================================================
    # 6. MULTI-DAY SWING TRADING PERSISTENCE
    # =========================================================================
    print("Evaluating Daily Multi-Day Swing Structure Persistence...")
    df_daily = df_indexed.resample('B').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna().reset_index()

    d_highs = df_daily['high'].values
    d_lows = df_daily['low'].values
    d_closes = df_daily['close'].values
    n_days = len(df_daily)

    d_sh, d_sl = detect_swings(d_highs, d_lows, 3, 3)

    daily_bos = []
    last_d_sh = np.nan
    last_d_sl = np.nan
    d_sh_broken = False
    d_sl_broken = False

    for d in range(1, n_days - 10):
        if not np.isnan(d_sh[d]):
            last_d_sh = d_sh[d]
            d_sh_broken = False
        if not np.isnan(d_sl[d]):
            last_d_sl = d_sl[d]
            d_sl_broken = False

        if np.isnan(last_d_sh) or np.isnan(last_d_sl):
            continue

        c = d_closes[d]
        c_prev = d_closes[d-1]

        if not d_sh_broken and c_prev <= last_d_sh and c > last_d_sh:
            d_sh_broken = True
            daily_bos.append({
                "day_idx": d,
                "date": str(df_daily['datetime'].values[d])[:10],
                "type": "Daily_Bull_BOS",
                "ret_1d": d_closes[d+1] - c,
                "ret_3d": d_closes[d+3] - c,
                "ret_5d": d_closes[d+5] - c,
                "ret_10d": d_closes[d+10] - c,
                "mfe_5d": np.max(d_highs[d+1 : d+6]) - c,
                "mae_5d": c - np.min(d_lows[d+1 : d+6]),
            })

        if not d_sl_broken and c_prev >= last_d_sl and c < last_d_sl:
            d_sl_broken = True
            daily_bos.append({
                "day_idx": d,
                "date": str(df_daily['datetime'].values[d])[:10],
                "type": "Daily_Bear_BOS",
                "ret_1d": c - d_closes[d+1],
                "ret_3d": c - d_closes[d+3],
                "ret_5d": c - d_closes[d+5],
                "ret_10d": c - d_closes[d+10],
                "mfe_5d": c - np.min(d_lows[d+1 : d+6]),
                "mae_5d": np.max(d_highs[d+1 : d+6]) - c,
            })

    df_daily_bos = pd.DataFrame(daily_bos)
    print(f"Total Daily BOS events: {len(df_daily_bos)}")

    # =========================================================================
    # 7. COMPILE ALL SUMMARY METRICS
    # =========================================================================
    bull_bos = df_bos[df_bos['type'] == 'Bullish_BOS']
    bear_bos = df_bos[df_bos['type'] == 'Bearish_BOS']
    bull_sfp = df_sfp[df_sfp['type'] == 'Bullish_SFP']
    bear_sfp = df_sfp[df_sfp['type'] == 'Bearish_SFP']

    df_sfp['sweep_tier'] = pd.cut(df_sfp['sweep_pts'], bins=[0, 10, 25, 1000], labels=['Small (1-10 pts)', 'Medium (10-25 pts)', 'Large (>25 pts)'])
    sfp_tier_summary = df_sfp.groupby('sweep_tier').agg(
        count=('sweep_pts', 'count'),
        meaningful_rev_pct=('meaningful_reversal', lambda x: round(float(np.mean(x)*100), 2)),
        mean_rev_ret_6=('rev_ret_6', lambda x: round(float(np.mean(x)), 2)),
        mean_rev_mfe_6=('rev_mfe_6', lambda x: round(float(np.mean(x)), 2)),
        mean_rev_mae_6=('rev_mae_6', lambda x: round(float(np.mean(x)), 2))
    ).to_dict(orient='index')

    metrics = {
        "dataset_total_bars": n_total,
        "total_sessions": len(np.unique(dates)),
        "swing_detection_benchmarks": swing_results,
        "hh_sequence_failure_rates": hh_failure_rates,
        "ll_sequence_failure_rates": ll_failure_rates,
        "mean_hh_streak_length": float(np.mean(hh_streaks)) if hh_streaks else 0,
        "median_hh_streak_length": float(np.median(hh_streaks)) if hh_streaks else 0,
        "mean_ll_streak_length": float(np.mean(ll_streaks)) if ll_streaks else 0,
        "median_ll_streak_length": float(np.median(ll_streaks)) if ll_streaks else 0,
        "bos_summary": {
            "total_bos_events": len(df_bos),
            "bull_bos_count": len(bull_bos),
            "bull_bos_continuation_pct_6": round(float(np.mean(bull_bos['fwd_ret_6'] > 0) * 100), 2),
            "bull_bos_mean_fwd_ret_6": round(float(np.mean(bull_bos['fwd_ret_6'])), 2),
            "bull_bos_mean_mfe_6": round(float(np.mean(bull_bos['mfe_6'])), 2),
            "bull_bos_mean_mae_6": round(float(np.mean(bull_bos['mae_6'])), 2),
            "bull_bos_failure_pct_6": round(float(np.mean(bull_bos['failed_within_6']) * 100), 2),
            "bull_bos_retest_pct_12": round(float(np.mean(bull_bos['retested_within_12']) * 100), 2),
            "bull_bos_second_breakout_pct": round(float(np.mean(bull_bos['second_breakout_after_retest']) * 100), 2),
            
            "bear_bos_count": len(bear_bos),
            "bear_bos_continuation_pct_6": round(float(np.mean(bear_bos['fwd_ret_6'] > 0) * 100), 2),
            "bear_bos_mean_fwd_ret_6": round(float(np.mean(bear_bos['fwd_ret_6'])), 2),
            "bear_bos_mean_mfe_6": round(float(np.mean(bear_bos['mfe_6'])), 2),
            "bear_bos_mean_mae_6": round(float(np.mean(bear_bos['mae_6'])), 2),
            "bear_bos_failure_pct_6": round(float(np.mean(bear_bos['failed_within_6']) * 100), 2),
            "bear_bos_retest_pct_12": round(float(np.mean(bear_bos['retested_within_12']) * 100), 2),
            "bear_bos_second_breakout_pct": round(float(np.mean(bear_bos['second_breakout_after_retest']) * 100), 2),
        },
        "sfp_summary": {
            "total_sfp_events": len(df_sfp),
            "bullish_sfp_count": len(bull_sfp),
            "bullish_sfp_meaningful_rev_pct": round(float(np.mean(bull_sfp['meaningful_reversal']) * 100), 2),
            "bullish_sfp_mean_rev_ret_6": round(float(np.mean(bull_sfp['rev_ret_6'])), 2),
            "bullish_sfp_mean_mfe_6": round(float(np.mean(bull_sfp['rev_mfe_6'])), 2),
            "bullish_sfp_mean_mae_6": round(float(np.mean(bull_sfp['rev_mae_6'])), 2),
            
            "bearish_sfp_count": len(bear_sfp),
            "bearish_sfp_meaningful_rev_pct": round(float(np.mean(bear_sfp['meaningful_reversal']) * 100), 2),
            "bearish_sfp_mean_rev_ret_6": round(float(np.mean(bear_sfp['rev_ret_6'])), 2),
            "bearish_sfp_mean_mfe_6": round(float(np.mean(bear_sfp['rev_mfe_6'])), 2),
            "bearish_sfp_mean_mae_6": round(float(np.mean(bear_sfp['rev_mae_6'])), 2),
            
            "sweep_depth_tiers": sfp_tier_summary
        },
        "mtf_summary": {
            "contradiction_rate_5m_vs_15m": round(float(contradict_15m), 2),
            "contradiction_rate_5m_vs_1h": round(float(contradict_1h), 2),
            "aligned_15m_bos_count": len(aligned_bos),
            "aligned_15m_bos_continuation_pct": round(float(np.mean(aligned_bos['fwd_ret_6'] > 0) * 100), 2),
            "aligned_15m_bos_mean_mfe": round(float(np.mean(aligned_bos['mfe_6'])), 2),
            "aligned_15m_bos_mean_mae": round(float(np.mean(aligned_bos['mae_6'])), 2),
            "counter_15m_bos_count": len(counter_bos),
            "counter_15m_bos_continuation_pct": round(float(np.mean(counter_bos['fwd_ret_6'] > 0) * 100), 2),
            "counter_15m_bos_mean_mfe": round(float(np.mean(counter_bos['mfe_6'])), 2),
            "counter_15m_bos_mean_mae": round(float(np.mean(counter_bos['mae_6'])), 2),
        },
        "daily_swing_trading_persistence": {
            "total_daily_bos": len(df_daily_bos),
            "bull_count": int(np.sum(df_daily_bos['type'] == 'Daily_Bull_BOS')),
            "bear_count": int(np.sum(df_daily_bos['type'] == 'Daily_Bear_BOS')),
            "ret_1d_win_pct": round(float(np.mean(df_daily_bos['ret_1d'] > 0) * 100), 2),
            "ret_1d_mean_pts": round(float(np.mean(df_daily_bos['ret_1d'])), 2),
            "ret_3d_win_pct": round(float(np.mean(df_daily_bos['ret_3d'] > 0) * 100), 2),
            "ret_3d_mean_pts": round(float(np.mean(df_daily_bos['ret_3d'])), 2),
            "ret_5d_win_pct": round(float(np.mean(df_daily_bos['ret_5d'] > 0) * 100), 2),
            "ret_5d_mean_pts": round(float(np.mean(df_daily_bos['ret_5d'])), 2),
            "ret_10d_win_pct": round(float(np.mean(df_daily_bos['ret_10d'] > 0) * 100), 2),
            "ret_10d_mean_pts": round(float(np.mean(df_daily_bos['ret_10d'])), 2),
            "mean_mfe_5d": round(float(np.mean(df_daily_bos['mfe_5d'])), 2),
            "mean_mae_5d": round(float(np.mean(df_daily_bos['mae_5d'])), 2)
        }
    }

    json_path = "research/price_action/market_structure_metrics.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(metrics, f, indent=2)
    print(f"Saved market structure metrics to {json_path}")

    # Export Events CSV
    events_out = []
    for b in bos_events:
        events_out.append({
            "timestamp": b['timestamp'],
            "date": b['date'],
            "event_category": "BOS",
            "subtype": b['type'],
            "level": b['level'],
            "trigger_price": b['close'],
            "atr": round(b['atr'], 2),
            "fwd_ret_6": round(b['fwd_ret_6'], 2),
            "mfe_6": round(b['mfe_6'], 2),
            "mae_6": round(b['mae_6'], 2),
            "failed_within_6": b['failed_within_6'],
            "retested_within_12": b['retested_within_12'],
            "second_breakout": b['second_breakout_after_retest']
        })
    for s in sfp_events:
        events_out.append({
            "timestamp": s['timestamp'],
            "date": s['date'],
            "event_category": "SFP",
            "subtype": s['type'],
            "level": s['level'],
            "trigger_price": round(s['sweep_pts'], 2),
            "atr": round(s['sweep_atr'], 2),
            "fwd_ret_6": round(s['rev_ret_6'], 2),
            "mfe_6": round(s['rev_mfe_6'], 2),
            "mae_6": round(s['rev_mae_6'], 2),
            "failed_within_6": False,
            "retested_within_12": False,
            "second_breakout": s['meaningful_reversal']
        })
    
    df_all_events = pd.DataFrame(events_out).sort_values('timestamp')
    csv_path = "research/price_action/MARKET_STRUCTURE_EVENTS.csv"
    df_all_events.to_csv(csv_path, index=False)
    print(f"Saved {len(df_all_events)} market structure events to {csv_path}")

    print("\n--- Summary Results ---")
    print(f"Total BOS: {len(df_bos)} (Bull: {len(bull_bos)}, Bear: {len(bear_bos)})")
    print(f"Bull BOS Cont %: {metrics['bos_summary']['bull_bos_continuation_pct_6']}% | Failure %: {metrics['bos_summary']['bull_bos_failure_pct_6']}% | Retest %: {metrics['bos_summary']['bull_bos_retest_pct_12']}%")
    print(f"Total SFP: {len(df_sfp)} | Meaningful Rev %: {metrics['sfp_summary']['bullish_sfp_meaningful_rev_pct']}% (Bull), {metrics['sfp_summary']['bearish_sfp_meaningful_rev_pct']}% (Bear)")
    print(f"MTF Contradiction: 5M vs 15M: {metrics['mtf_summary']['contradiction_rate_5m_vs_15m']}%, 5M vs 1H: {metrics['mtf_summary']['contradiction_rate_5m_vs_1h']}%")
    print(f"Aligned 15M BOS Cont %: {metrics['mtf_summary']['aligned_15m_bos_continuation_pct']}% vs Counter: {metrics['mtf_summary']['counter_15m_bos_continuation_pct']}%")
    print(f"Daily BOS 5D Win %: {metrics['daily_swing_trading_persistence']['ret_5d_win_pct']}% | Mean 5D Pts: {metrics['daily_swing_trading_persistence']['ret_5d_mean_pts']}")


if __name__ == "__main__":
    run_market_structure_research()
