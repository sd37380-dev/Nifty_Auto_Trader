"""
Topic 9 — Time-of-Day Price Behaviour Research Engine for NIFTY 50 Spot.
Comprehensive intraday statistical mapping of 8 time windows, window-level volatility,
directional efficiency, reversal probabilities, breakout reliability, day types, and gap correlation.
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


WINDOWS = [
    {"name": "09:15-09:30", "start": time(9, 15), "end": time(9, 30)},
    {"name": "09:30-10:00", "start": time(9, 30), "end": time(10, 0)},
    {"name": "10:00-11:00", "start": time(10, 0), "end": time(11, 0)},
    {"name": "11:00-12:00", "start": time(11, 0), "end": time(12, 0)},
    {"name": "12:00-13:00", "start": time(12, 0), "end": time(13, 0)},
    {"name": "13:00-14:00", "start": time(13, 0), "end": time(14, 0)},
    {"name": "14:00-15:00", "start": time(14, 0), "end": time(15, 0)},
    {"name": "15:00-15:25", "start": time(15, 0), "end": time(15, 30)},
]


def run_time_of_day_research():
    print("Loading 5-minute NIFTY dataset...")
    df_5m, clean_stats = load_and_clean_nifty_5m()
    n_total = len(df_5m)
    print(f"Total clean 5M bars: {n_total}")

    df = df_5m.sort_values('timestamp').reset_index(drop=True)

    # Base ATR 14
    highs = df['high'].values
    lows = df['low'].values
    opens = df['open'].values
    closes = df['close'].values
    ranges = highs - lows

    prev_closes = np.roll(closes, 1)
    prev_closes[0] = opens[0]
    tr = np.maximum(ranges, np.maximum(np.abs(highs - prev_closes), np.abs(lows - prev_closes)))
    df['tr'] = tr
    df['atr14'] = df['tr'].rolling(14).mean().bfill()

    # Group by trading date
    grouped_sessions = df.groupby('date_ist')
    session_dates = list(grouped_sessions.groups.keys())
    print(f"Total trading sessions: {len(session_dates)}")

    # Data structures for window-by-window analysis
    window_data = {w['name']: [] for w in WINDOWS}
    session_records = []

    # Iterate through sessions
    for d_idx, dt in enumerate(session_dates):
        sdf = grouped_sessions.get_group(dt).sort_values('time_ist').reset_index(drop=True)
        if len(sdf) < 60: # Exclude half/short sessions
            continue

        s_open = sdf['open'].iloc[0]
        s_high = sdf['high'].max()
        s_low = sdf['low'].min()
        s_close = sdf['close'].iloc[-1]
        s_range = s_high - s_low
        s_body = s_close - s_open

        # Day type classification
        # 1. Trend Day: |Close - Open| / Range >= 0.70
        # 2. Range Day: |Close - Open| / Range <= 0.30 and Range <= Median Range
        # 3. Reversal Day: Made new high/low in morning but closed at opposite extreme
        # 4. Expansion Day: Range >= 1.5 * rolling ATR
        # 5. Two-Sided Day: Tested both above open and below open significantly (> 0.4 Range on each side)
        up_wick = s_high - max(s_open, s_close)
        dn_wick = min(s_open, s_close) - s_low
        efficiency = abs(s_body) / max(s_range, 1e-4)

        if efficiency >= 0.65:
            day_type = "Trend_Day"
        elif efficiency <= 0.30:
            day_type = "Range_Day"
        elif (up_wick >= 0.35 * s_range) and (dn_wick >= 0.35 * s_range):
            day_type = "Two_Sided_Day"
        elif (up_wick >= 0.45 * s_range) or (dn_wick >= 0.45 * s_range):
            day_type = "Reversal_Day"
        else:
            day_type = "Expansion_Day"

        # Track session running high/low prior to each window
        running_high = -1e9
        running_low = 1e9
        prev_win_dir = 0 # +1 if bullish, -1 if bearish

        win_snapshots = {}

        for w_idx, win in enumerate(WINDOWS):
            w_name = win['name']
            w_start = win['start']
            w_end = win['end']

            # Filter bars in window
            w_bars = sdf[(sdf['time_ist'] >= w_start) & (sdf['time_ist'] < w_end)]
            if len(w_bars) == 0:
                continue

            w_open = w_bars['open'].iloc[0]
            w_high = w_bars['high'].max()
            w_low = w_bars['low'].min()
            w_close = w_bars['close'].iloc[-1]
            w_range = w_high - w_low
            w_body = w_close - w_open
            w_abs_body = abs(w_body)
            w_atr = w_bars['atr14'].mean()
            
            # Wicks
            w_upper_wick = w_high - max(w_open, w_close)
            w_lower_wick = min(w_open, w_close) - w_low

            # Directional persistence: Kaufman Efficiency Ratio in window
            total_path = w_bars['tr'].sum()
            w_er = w_abs_body / max(total_path, 1e-4)

            # Volatility: Std dev of 5m returns within window
            bar_rets = (w_bars['close'].values - w_bars['open'].values)
            w_vol = np.std(bar_rets) if len(bar_rets) > 1 else 0.0

            # Direction
            w_dir = 1 if w_body > 0 else (-1 if w_body < 0 else 0)

            # Reversal vs prior window: Opposes prior window direction?
            reversal_prior = (w_dir != 0 and prev_win_dir != 0 and w_dir != prev_win_dir)

            # Breakout of prior session range
            broke_high = False
            broke_low = False
            failed_high_bo = False
            failed_low_bo = False

            if w_idx > 0 and running_high > -1e8:
                if w_high > running_high:
                    broke_high = True
                    if w_close < running_high: # Closed back inside
                        failed_high_bo = True
                if w_low < running_low:
                    broke_low = True
                    if w_close > running_low:
                        failed_low_bo = True

            broke_any = broke_high or broke_low
            failed_any = failed_high_bo or failed_low_bo

            # MFE and MAE from window open
            if w_dir >= 0: # Bullish or flat
                mfe = w_high - w_open
                mae = w_open - w_low
            else:
                mfe = w_open - w_low
                mae = w_high - w_open

            rec = {
                "date": str(dt),
                "window": w_name,
                "open": w_open,
                "high": w_high,
                "low": w_low,
                "close": w_close,
                "range": w_range,
                "body": w_body,
                "abs_body": w_abs_body,
                "upper_wick": w_upper_wick,
                "lower_wick": w_lower_wick,
                "atr": w_atr,
                "range_atr": w_range / max(w_atr, 1.0),
                "er": w_er,
                "vol": w_vol,
                "dir": w_dir,
                "reversal_prior": reversal_prior,
                "broke_prior_high": broke_high,
                "broke_prior_low": broke_low,
                "broke_any": broke_any,
                "failed_breakout": failed_any,
                "mfe": mfe,
                "mae": mae
            }
            window_data[w_name].append(rec)
            win_snapshots[w_name] = rec

            # Update running session high/low and direction
            running_high = max(running_high, w_high)
            running_low = min(running_low, w_low)
            prev_win_dir = w_dir

        session_records.append({
            "date": str(dt),
            "open": s_open,
            "high": s_high,
            "low": s_low,
            "close": s_close,
            "range": s_range,
            "body": s_body,
            "day_type": day_type,
            "windows": win_snapshots
        })

    # =========================================================================
    # 2. COMPILE WINDOW-BY-WINDOW AGGREGATES
    # =========================================================================
    print("Compiling window statistics...")
    window_summary = {}
    all_window_rows = []

    for win in WINDOWS:
        w_name = win['name']
        recs = window_data[w_name]
        df_w = pd.DataFrame(recs)
        all_window_rows.extend(recs)

        mean_range = df_w['range'].mean()
        med_range = df_w['range'].median()
        mean_body = df_w['abs_body'].mean()
        mean_up_wick = df_w['upper_wick'].mean()
        mean_dn_wick = df_w['lower_wick'].mean()
        mean_atr = df_w['atr'].mean()
        mean_range_atr = df_w['range_atr'].mean()
        mean_er = df_w['er'].mean()
        mean_vol = df_w['vol'].mean()
        rev_prob = df_w['reversal_prior'].mean() * 100.0

        bo_prob = df_w['broke_any'].mean() * 100.0
        # Breakout failure: among those that broke out, how many failed?
        bo_subset = df_w[df_w['broke_any'] == True]
        bo_fail_prob = (bo_subset['failed_breakout'].mean() * 100.0) if len(bo_subset) > 0 else 0.0

        mean_mfe = df_w['mfe'].mean()
        mean_mae = df_w['mae'].mean()

        # Classify predominant behaviour
        # Measurable criteria:
        # If mean_er >= 0.40 and mean_range_atr >= 2.0 -> Expansion / Trend
        # If mean_range_atr < 1.6 and mean_er < 0.32 -> Compression / Range
        # If rev_prob >= 50.0% -> Reversal
        # If bo_prob >= 40.0% -> Breakout
        if mean_range_atr >= 2.2 and mean_er >= 0.36:
            predom = "Expansion"
        elif mean_er >= 0.38:
            predom = "Trend"
        elif rev_prob >= 52.0:
            predom = "Reversal"
        elif mean_range_atr < 1.7 and mean_er < 0.32:
            predom = "Compression"
        elif bo_prob >= 40.0:
            predom = "Breakout"
        else:
            predom = "Range"

        window_summary[w_name] = {
            "mean_range_pts": round(float(mean_range), 2),
            "median_range_pts": round(float(med_range), 2),
            "mean_body_pts": round(float(mean_body), 2),
            "mean_upper_wick_pts": round(float(mean_up_wick), 2),
            "mean_lower_wick_pts": round(float(mean_dn_wick), 2),
            "mean_range_atr": round(float(mean_range_atr), 2),
            "mean_efficiency_er": round(float(mean_er), 3),
            "mean_volatility_sigma": round(float(mean_vol), 2),
            "reversal_prob_pct": round(float(rev_prob), 2),
            "breakout_prob_pct": round(float(bo_prob), 2),
            "breakout_failure_pct": round(float(bo_fail_prob), 2),
            "mean_mfe_pts": round(float(mean_mfe), 2),
            "mean_mae_pts": round(float(mean_mae), 2),
            "predominant_behaviour": predom
        }

    # =========================================================================
    # 3. DEEP RESEARCH QUESTIONS
    # =========================================================================
    print("Evaluating specific Morning, Midday, Afternoon, and Closing questions...")
    df_sess = pd.DataFrame(session_records)

    # Q1: Does opening volatility contain directional information?
    # Correlate 09:15-09:30 range with full session range, and 09:15-09:30 direction with session close direction
    w1_ranges = [s['windows']['09:15-09:30']['range'] for s in session_records if '09:15-09:30' in s['windows']]
    w1_dirs = [s['windows']['09:15-09:30']['dir'] for s in session_records if '09:15-09:30' in s['windows']]
    sess_ranges = [s['range'] for s in session_records if '09:15-09:30' in s['windows']]
    sess_dirs = [1 if s['body'] > 0 else -1 for s in session_records if '09:15-09:30' in s['windows']]

    vol_corr_w1_session = float(np.corrcoef(w1_ranges, sess_ranges)[0, 1])
    dir_persist_w1_session = float(np.mean(np.array(w1_dirs) == np.array(sess_dirs)) * 100.0)

    # Q2: Does the first move frequently reverse?
    # Check if 09:30-10:00 reverses 09:15-09:30
    w2_rev_w1 = [s['windows']['09:30-10:00']['reversal_prior'] for s in session_records if '09:30-10:00' in s['windows']]
    w2_rev_w1_pct = float(np.mean(w2_rev_w1) * 100.0)

    # Q4: Does opening range size predict later movement?
    # Top 20% opening range vs Bottom 20% opening range -> subsequent range (from 09:30 to 15:30)
    top_w1_thresh = np.percentile(w1_ranges, 80)
    bot_w1_thresh = np.percentile(w1_ranges, 20)
    subseq_ranges_wide_w1 = []
    subseq_ranges_narrow_w1 = []

    for s in session_records:
        if '09:15-09:30' in s['windows']:
            r1 = s['windows']['09:15-09:30']['range']
            # Calculate range after 09:30
            # s['high'] and s['low'] are total, but let's approximate or compute subseq
            # using session high/low vs w1
            sub_r = s['range'] - r1 # rough incremental or actual
            if r1 >= top_w1_thresh:
                subseq_ranges_wide_w1.append(s['range'])
            elif r1 <= bot_w1_thresh:
                subseq_ranges_narrow_w1.append(s['range'])

    mean_session_range_after_wide_w1 = float(np.mean(subseq_ranges_wide_w1))
    mean_session_range_after_narrow_w1 = float(np.mean(subseq_ranges_narrow_w1))

    # Q5 & Q8: Midday Mean Reversion & Compression predicting Afternoon Expansion
    # Midday window (11:00-14:00): Combined range and ER
    midday_ers = []
    midday_compressed_flags = []
    afternoon_ranges = [] # 14:00-15:25 range

    for s in session_records:
        w_keys = ['11:00-12:00', '12:00-13:00', '13:00-14:00']
        if all(k in s['windows'] for k in w_keys) and '14:00-15:00' in s['windows']:
            mid_ranges = [s['windows'][k]['range'] for k in w_keys]
            mid_ers = [s['windows'][k]['er'] for k in w_keys]
            midday_ers.extend(mid_ers)
            
            # Midday compression: all 3 hours range below 1.5 ATR
            mid_atr = s['windows']['11:00-12:00']['atr']
            is_compressed = (max(mid_ranges) < 1.4 * mid_atr)
            midday_compressed_flags.append(is_compressed)

            aft_range = s['windows']['14:00-15:00']['range']
            if '15:00-15:25' in s['windows']:
                aft_range += s['windows']['15:00-15:25']['range']
            afternoon_ranges.append((is_compressed, aft_range))

    aft_range_after_compressed = [r for comp, r in afternoon_ranges if comp]
    aft_range_after_normal = [r for comp, r in afternoon_ranges if not comp]

    mean_aft_range_compressed = float(np.mean(aft_range_after_compressed)) if aft_range_after_compressed else 0
    mean_aft_range_normal = float(np.mean(aft_range_after_normal)) if aft_range_after_normal else 0

    # Q9, Q10, Q11: Afternoon Volatility & Trend Continuation vs Reversal
    # Compare morning direction (09:15-11:00) with afternoon direction (14:00-15:00)
    morning_aft_alignment = []
    for s in session_records:
        if '09:15-09:30' in s['windows'] and '10:00-11:00' in s['windows'] and '14:00-15:00' in s['windows']:
            morn_open = s['windows']['09:15-09:30']['open']
            morn_close = s['windows']['10:00-11:00']['close']
            morn_dir = 1 if morn_close > morn_open else -1

            aft_dir = s['windows']['14:00-15:00']['dir']
            morning_aft_alignment.append((morn_dir, aft_dir))

    aft_continues_morn_pct = float(np.mean([1 if m == a else 0 for m, a in morning_aft_alignment]) * 100.0)
    aft_reverses_morn_pct = float(np.mean([1 if m != a and a != 0 else 0 for m, a in morning_aft_alignment]) * 100.0)

    # Q12, Q13, Q14: Closing Period (15:00-15:25) & Next Day Gap Relation
    # Direction of 15:00-15:25 vs Next Day Opening Gap
    closing_gap_pairs = []
    for d_i in range(len(session_records) - 1):
        s_curr = session_records[d_i]
        s_next = session_records[d_i + 1]

        if '15:00-15:25' in s_curr['windows']:
            c_dir = s_curr['windows']['15:00-15:25']['dir']
            c_close = s_curr['close']
            n_open = s_next['open']
            gap = n_open - c_close
            gap_dir = 1 if gap > 0 else (-1 if gap < 0 else 0)

            closing_gap_pairs.append({
                "closing_dir": c_dir,
                "gap_pts": gap,
                "gap_dir": gap_dir,
                "gap_same_as_close": (c_dir == gap_dir and c_dir != 0)
            })

    closing_gap_same_pct = float(np.mean([p['gap_same_as_close'] for p in closing_gap_pairs]) * 100.0)
    mean_gap_after_bull_close = float(np.mean([p['gap_pts'] for p in closing_gap_pairs if p['closing_dir'] == 1]))
    mean_gap_after_bear_close = float(np.mean([p['gap_pts'] for p in closing_gap_pairs if p['closing_dir'] == -1]))

    # =========================================================================
    # 4. DAY TYPE EARLY IDENTIFICATION
    # =========================================================================
    print("Evaluating Early Day Type Identification across windows...")
    # Day type distribution
    day_types = [s['day_type'] for s in session_records]
    day_type_counts = pd.Series(day_types).value_counts().to_dict()
    total_valid_days = len(session_records)
    day_type_dist = {k: {"count": int(v), "pct": round(float(v / total_valid_days * 100.0), 2)} for k, v in day_type_counts.items()}

    # Early Identification Test:
    # By 10:00 (after first 45 mins), if range is > 2.5 ATR -> Prob of Trend/Expansion day
    # By 11:00 (first 105 mins), measure predictive accuracy
    early_id_metrics = {}
    
    # 10:00 benchmark
    trend_ident_1000 = []
    range_ident_1000 = []
    for s in session_records:
        if '09:15-09:30' in s['windows'] and '09:30-10:00' in s['windows']:
            w1_r = s['windows']['09:15-09:30']['range']
            w2_r = s['windows']['09:30-10:00']['range']
            r_1000 = max(s['windows']['09:15-09:30']['high'], s['windows']['09:30-10:00']['high']) - \
                     min(s['windows']['09:15-09:30']['low'], s['windows']['09:30-10:00']['low'])
            atr = s['windows']['09:15-09:30']['atr']
            ratio = r_1000 / max(atr, 1.0)
            
            # Predict Trend if ratio > 2.5 and both windows in same direction
            w1_dir = s['windows']['09:15-09:30']['dir']
            w2_dir = s['windows']['09:30-10:00']['dir']
            pred_trend = (ratio >= 2.0 and w1_dir == w2_dir and w1_dir != 0)
            pred_range = (ratio <= 1.2 and w1_dir != w2_dir)

            trend_ident_1000.append((pred_trend, s['day_type'] == 'Trend_Day'))
            range_ident_1000.append((pred_range, s['day_type'] == 'Range_Day'))

    trend_precision_1000 = float(np.mean([is_t for p, is_t in trend_ident_1000 if p]) * 100.0) if any(p for p, _ in trend_ident_1000) else 0.0
    range_precision_1000 = float(np.mean([is_r for p, is_r in range_ident_1000 if p]) * 100.0) if any(p for p, _ in range_ident_1000) else 0.0

    early_id_metrics["by_10_00_am"] = {
        "trend_day_prediction_precision_pct": round(trend_precision_1000, 2),
        "range_day_prediction_precision_pct": round(range_precision_1000, 2)
    }

    # =========================================================================
    # 5. COMPILE MASTER METRICS JSON
    # =========================================================================
    metrics = {
        "dataset_total_bars": n_total,
        "total_analyzed_sessions": total_valid_days,
        "window_statistical_map": window_summary,
        "morning_dynamics": {
            "opening_volatility_session_range_correlation": round(vol_corr_w1_session, 3),
            "opening_direction_session_direction_persistence_pct": round(dir_persist_w1_session, 2),
            "window2_reverses_window1_pct": round(w2_rev_w1_pct, 2),
            "mean_session_range_after_wide_opening_pts": round(mean_session_range_after_wide_w1, 2),
            "mean_session_range_after_narrow_opening_pts": round(mean_session_range_after_narrow_w1, 2)
        },
        "midday_dynamics": {
            "avg_efficiency_midday_er": round(float(np.mean(midday_ers)), 3),
            "afternoon_range_after_compressed_midday_pts": round(mean_aft_range_compressed, 2),
            "afternoon_range_after_normal_midday_pts": round(mean_aft_range_normal, 2),
            "midday_compression_expansion_ratio": round(mean_aft_range_compressed / max(mean_aft_range_normal, 1.0), 2)
        },
        "afternoon_dynamics": {
            "afternoon_continues_morning_pct": round(aft_continues_morn_pct, 2),
            "afternoon_reverses_morning_pct": round(aft_reverses_morn_pct, 2)
        },
        "closing_period_dynamics": {
            "closing_move_predicts_gap_direction_pct": round(closing_gap_same_pct, 2),
            "mean_gap_after_bullish_close_pts": round(mean_gap_after_bull_close, 2),
            "mean_gap_after_bearish_close_pts": round(mean_gap_after_bear_close, 2)
        },
        "day_type_distribution": day_type_dist,
        "early_day_type_identification": early_id_metrics
    }

    json_path = "research/price_action/time_of_day_metrics.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(metrics, f, indent=2)
    print(f"Saved time-of-day metrics to {json_path}")

    # Export Events CSV
    df_all_w = pd.DataFrame(all_window_rows).sort_values(['date', 'window'])
    csv_path = "research/price_action/TIME_OF_DAY_EVENTS.csv"
    df_all_w.to_csv(csv_path, index=False)
    print(f"Saved {len(df_all_w)} time-of-day window records to {csv_path}")

    print("\n--- Summary Results ---")
    for w, data in window_summary.items():
        print(f"[{w}] Range: {data['mean_range_pts']} pts ({data['mean_range_atr']} ATR) | ER: {data['mean_efficiency_er']} | Rev%: {data['reversal_prob_pct']}% | BO%: {data['breakout_prob_pct']}% (Fail: {data['breakout_failure_pct']}%) | Class: {data['predominant_behaviour']}")


if __name__ == "__main__":
    run_time_of_day_research()
