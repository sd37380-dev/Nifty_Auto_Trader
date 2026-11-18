"""
Topic 3 — Previous Day High (PDH) and Low (PDL) Sweep & Rejection Behaviour Research Engine.
Exhaustive empirical analysis of price dynamics around previous day extremes across 5 years.
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


def run_pdh_pdl_research():
    print("Loading 5-minute NIFTY dataset...")
    df_5m, clean_stats = load_and_clean_nifty_5m()
    print(f"Total clean 5M bars: {len(df_5m)}")

    # Group by date
    grouped = df_5m.groupby('date_ist')
    daily_rows = []
    group_dict = {}

    for dt, group in grouped:
        if len(group) < 30:
            continue
        group_dict[dt] = group.reset_index(drop=True)
        daily_rows.append({
            'date': dt,
            'open': group.iloc[0]['open'],
            'high': group['high'].max(),
            'low': group['low'].min(),
            'close': group.iloc[-1]['close'],
            'range': group['high'].max() - group['low'].min(),
        })

    df_daily = pd.DataFrame(daily_rows).sort_values('date').reset_index(drop=True)
    prev_close = df_daily['close'].shift(1)
    tr = np.maximum(df_daily['high'] - df_daily['low'],
                    np.maximum((df_daily['high'] - prev_close).abs(),
                               (df_daily['low'] - prev_close).abs()))
    df_daily['tr'] = tr
    df_daily['atr14'] = tr.rolling(14).mean()
    df_daily['ma20'] = df_daily['close'].rolling(20).mean()
    df_daily['ma50'] = df_daily['close'].rolling(50).mean()
    
    # Zero look-ahead shift by 1
    df_daily['pdatr14'] = df_daily['atr14'].shift(1)
    df_daily['pdc'] = df_daily['close'].shift(1)
    df_daily['pdo'] = df_daily['open'].shift(1)
    df_daily['pdh'] = df_daily['high'].shift(1)
    df_daily['pdl'] = df_daily['low'].shift(1)
    df_daily['pd_ma20'] = df_daily['ma20'].shift(1)
    df_daily['pd_ma50'] = df_daily['ma50'].shift(1)
    df_daily['pd_is_bullish'] = df_daily['pdc'] > df_daily['pdo']

    df_daily_valid = df_daily.dropna(subset=['pdatr14', 'pd_ma50']).copy().reset_index(drop=True)
    print(f"Total valid trading days: {len(df_daily_valid)}")

    events_list = []
    
    # Trackers for approach, touch, breakout, sweep
    touch_stats = {
        'PDH': {'first_touch': [], 'second_touch': [], 'third_touch': []},
        'PDL': {'first_touch': [], 'second_touch': [], 'third_touch': []}
    }
    
    breakout_pen_levels = [1, 5, 10]
    wick_thresholds = [0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.60]
    
    # Proximity volatility tracking
    prox_distances = [50, 25, 10, 5, 0]
    prox_vol_records = {f'dist_{d}': [] for d in prox_distances}
    prox_vol_records['baseline'] = []

    for idx, d_row in df_daily_valid.iterrows():
        dt = d_row['date']
        bars = group_dict.get(dt)
        if bars is None or len(bars) < 30:
            continue

        pdh = d_row['pdh']
        pdl = d_row['pdl']
        pdc = d_row['pdc']
        pdatr = d_row['pdatr14']
        open_0915 = bars.iloc[0]['open']
        gap = open_0915 - pdc
        gap_dir = 'UP' if gap > 2 else ('DOWN' if gap < -2 else 'FLAT')
        macro_trend = 'BULLISH' if d_row['pd_ma20'] > d_row['pd_ma50'] else 'BEARISH'
        
        # Calculate session VWAP
        # Volume-weighted average price (or typical price mean if volume flat)
        typ_price = (bars['high'] + bars['low'] + bars['close']) / 3.0
        vols = bars['volume'].replace(0, 1)
        cum_vp = (typ_price * vols).cumsum()
        cum_v = vols.cumsum()
        session_vwap = cum_vp / cum_v

        # Track touch counts during the day
        pdh_touch_count = 0
        pdl_touch_count = 0
        
        # State tracking: has price been above PDH or below PDL?
        above_pdh = False
        below_pdl = False

        for b_idx in range(len(bars)):
            bar = bars.iloc[b_idx]
            b_high = bar['high']
            b_low = bar['low']
            b_open = bar['open']
            b_close = bar['close']
            b_time = bar['time_ist']
            b_range = b_high - b_low
            vwap_val = session_vwap.iloc[b_idx]
            dist_vwap = b_close - vwap_val

            # Candle geometry
            upper_wick = b_high - max(b_open, b_close)
            lower_wick = min(b_open, b_close) - b_low
            body = abs(b_close - b_open)
            upper_wick_ratio = upper_wick / b_range if b_range > 0 else 0
            lower_wick_ratio = lower_wick / b_range if b_range > 0 else 0
            close_loc = (b_close - b_low) / b_range if b_range > 0 else 0.5

            # Proximity check
            min_dist_pdh = abs(b_high - pdh)
            min_dist_pdl = abs(b_low - pdl)
            min_dist_both = min(min_dist_pdh, min_dist_pdl)
            prox_vol_records['baseline'].append(b_range)
            for d in prox_distances:
                if min_dist_both <= d:
                    prox_vol_records[f'dist_{d}'].append(b_range)

            # Check PDH interaction
            # Touch: High >= PDH and Low <= PDH (or High >= PDH if coming from below)
            if b_high >= pdh and (b_idx == 0 or bars.iloc[b_idx-1]['high'] < pdh):
                pdh_touch_count += 1
                touch_order = 'first_touch' if pdh_touch_count == 1 else ('second_touch' if pdh_touch_count == 2 else 'third_touch')
                if touch_order in touch_stats['PDH']:
                    # Forward outcome over next 6 bars (30m), 12 bars (1h), EOD
                    subseq = bars.iloc[b_idx+1:]
                    if len(subseq) >= 6:
                        ret_30m = subseq.iloc[5]['close'] - pdh
                        cont_30m = ret_30m > 0
                    else:
                        ret_30m, cont_30m = 0, False
                    
                    if len(subseq) >= 12:
                        ret_1h = subseq.iloc[11]['close'] - pdh
                    else:
                        ret_1h = 0
                    
                    eod_ret = bars.iloc[-1]['close'] - pdh if len(subseq) > 0 else 0
                    touch_stats['PDH'][touch_order].append({
                        'date': dt,
                        'time': b_time,
                        'b_idx': b_idx,
                        'cont_30m': cont_30m,
                        'ret_30m': ret_30m,
                        'ret_1h': ret_1h,
                        'eod_ret': eod_ret,
                        'broken': (subseq['high'] > pdh + 5).any() if len(subseq) > 0 else False
                    })

            # Check PDL interaction
            if b_low <= pdl and (b_idx == 0 or bars.iloc[b_idx-1]['low'] > pdl):
                pdl_touch_count += 1
                touch_order = 'first_touch' if pdl_touch_count == 1 else ('second_touch' if pdl_touch_count == 2 else 'third_touch')
                if touch_order in touch_stats['PDL']:
                    subseq = bars.iloc[b_idx+1:]
                    if len(subseq) >= 6:
                        ret_30m = pdl - subseq.iloc[5]['close'] # positive if continues down
                        cont_30m = ret_30m > 0
                    else:
                        ret_30m, cont_30m = 0, False
                    
                    if len(subseq) >= 12:
                        ret_1h = pdl - subseq.iloc[11]['close']
                    else:
                        ret_1h = 0
                    
                    eod_ret = pdl - bars.iloc[-1]['close'] if len(subseq) > 0 else 0
                    touch_stats['PDL'][touch_order].append({
                        'date': dt,
                        'time': b_time,
                        'b_idx': b_idx,
                        'cont_30m': cont_30m,
                        'ret_30m': ret_30m,
                        'ret_1h': ret_1h,
                        'eod_ret': eod_ret,
                        'broken': (subseq['low'] < pdl - 5).any() if len(subseq) > 0 else False
                    })

            # =========================================================
            # SWEEP + RE-ENTRY DETECTION
            # =========================================================
            # PDH Sweep: High > PDH, but Close < PDH (pierced and closed back inside)
            is_pdh_sweep = (b_high > pdh) and (b_close < pdh)
            # PDL Sweep: Low < PDL, but Close > PDL
            is_pdl_sweep = (b_low < pdl) and (b_close > pdl)

            if is_pdh_sweep or is_pdl_sweep:
                event_type = "PDH_SWEEP_SHORT" if is_pdh_sweep else "PDL_SWEEP_LONG"
                level = pdh if is_pdh_sweep else pdl
                penetration = (b_high - pdh) if is_pdh_sweep else (pdl - b_low)
                wick_ratio = upper_wick_ratio if is_pdh_sweep else lower_wick_ratio
                
                # Forward outcomes
                post_bars = bars.iloc[b_idx+1:]
                if len(post_bars) > 0:
                    next_open = post_bars.iloc[0]['open']
                    # Signed forward returns in reversal direction
                    # For Short (PDH): profit when price drops
                    # For Long (PDL): profit when price rises
                    if is_pdh_sweep:
                        fwd_5m = next_open - post_bars.iloc[0]['close']
                        fwd_15m = next_open - post_bars.iloc[min(2, len(post_bars)-1)]['close']
                        fwd_30m = next_open - post_bars.iloc[min(5, len(post_bars)-1)]['close']
                        fwd_1h = next_open - post_bars.iloc[min(11, len(post_bars)-1)]['close']
                        fwd_2h = next_open - post_bars.iloc[min(23, len(post_bars)-1)]['close']
                        fwd_4h = next_open - post_bars.iloc[min(47, len(post_bars)-1)]['close']
                        fwd_eod = next_open - post_bars.iloc[-1]['close']
                        mfe = next_open - post_bars['low'].min()
                        mae = post_bars['high'].max() - next_open
                    else:
                        fwd_5m = post_bars.iloc[0]['close'] - next_open
                        fwd_15m = post_bars.iloc[min(2, len(post_bars)-1)]['close'] - next_open
                        fwd_30m = post_bars.iloc[min(5, len(post_bars)-1)]['close'] - next_open
                        fwd_1h = post_bars.iloc[min(11, len(post_bars)-1)]['close'] - next_open
                        fwd_2h = post_bars.iloc[min(23, len(post_bars)-1)]['close'] - next_open
                        fwd_4h = post_bars.iloc[min(47, len(post_bars)-1)]['close'] - next_open
                        fwd_eod = post_bars.iloc[-1]['close'] - next_open
                        mfe = post_bars['high'].max() - next_open
                        mae = next_open - post_bars['low'].min()

                    # Multi-day returns
                    ret_t1 = np.nan
                    ret_t3 = np.nan
                    ret_t5 = np.nan
                    if idx + 1 < len(df_daily_valid):
                        raw_t1 = df_daily_valid.iloc[idx + 1]['close'] - d_row['close']
                        ret_t1 = -raw_t1 if is_pdh_sweep else raw_t1
                    if idx + 3 < len(df_daily_valid):
                        raw_t3 = df_daily_valid.iloc[idx + 3]['close'] - d_row['close']
                        ret_t3 = -raw_t3 if is_pdh_sweep else raw_t3
                    if idx + 5 < len(df_daily_valid):
                        raw_t5 = df_daily_valid.iloc[idx + 5]['close'] - d_row['close']
                        ret_t5 = -raw_t5 if is_pdh_sweep else raw_t5

                    events_list.append({
                        'date': dt,
                        'year': dt.year,
                        'time': str(b_time),
                        'b_idx': b_idx,
                        'event_type': event_type,
                        'level': level,
                        'price': b_close,
                        'penetration': penetration,
                        'wick_ratio': wick_ratio,
                        'close_loc': close_loc,
                        'gap_dir': gap_dir,
                        'macro_trend': macro_trend,
                        'dist_vwap': dist_vwap,
                        'fwd_5m': fwd_5m,
                        'fwd_15m': fwd_15m,
                        'fwd_30m': fwd_30m,
                        'fwd_1h': fwd_1h,
                        'fwd_2h': fwd_2h,
                        'fwd_4h': fwd_4h,
                        'fwd_eod': fwd_eod,
                        'mfe': mfe,
                        'mae': mae,
                        'ret_t1': ret_t1,
                        'ret_t3': ret_t3,
                        'ret_t5': ret_t5,
                        'is_reversal_win_30m': fwd_30m > 0,
                        'is_reversal_win_1h': fwd_1h > 0,
                    })

    df_events = pd.DataFrame(events_list)
    print(f"Total Sweep Events captured: {len(df_events)}")

    # =================================================================
    # 1. LEVEL APPROACH & PROXIMITY VOLATILITY
    # =================================================================
    prox_vol_results = {}
    baseline_vol = np.mean(prox_vol_records['baseline'])
    for d in prox_distances:
        bars_near = prox_vol_records[f'dist_{d}']
        if len(bars_near) > 0:
            avg_rng = np.mean(bars_near)
            ratio = avg_rng / baseline_vol
            prox_vol_results[f'dist_{d}_pts'] = {
                'count_bars': len(bars_near),
                'avg_range': round(float(avg_rng), 2),
                'relative_volatility': round(float(ratio), 2)
            }

    # =================================================================
    # 2. TOUCH FREQUENCY & REPEAT TOUCH COMPARISON
    # =================================================================
    touch_comparison = {}
    for lvl in ['PDH', 'PDL']:
        touch_comparison[lvl] = {}
        for t_order in ['first_touch', 'second_touch', 'third_touch']:
            data = touch_stats[lvl][t_order]
            if len(data) > 0:
                df_t = pd.DataFrame(data)
                touch_comparison[lvl][t_order] = {
                    'count': len(df_t),
                    'continuation_rate_30m': round(float(df_t['cont_30m'].mean() * 100), 2),
                    'broken_rate': round(float(df_t['broken'].mean() * 100), 2),
                    'mean_ret_30m': round(float(df_t['ret_30m'].mean()), 2),
                    'mean_ret_1h': round(float(df_t['ret_1h'].mean()), 2),
                    'mean_eod_ret': round(float(df_t['eod_ret'].mean()), 2)
                }

    # =================================================================
    # 3. WICK THRESHOLD SENSITIVITY (20% to 60%)
    # =================================================================
    wick_sensitivity = {}
    for w_thresh in wick_thresholds:
        subset = df_events[df_events['wick_ratio'] >= w_thresh]
        if len(subset) > 0:
            wick_sensitivity[f'wick_{int(w_thresh*100)}pct'] = {
                'events_count': len(subset),
                'win_rate_30m': round(float((subset['fwd_30m'] > 0).mean() * 100), 2),
                'win_rate_1h': round(float((subset['fwd_1h'] > 0).mean() * 100), 2),
                'mean_fwd_30m_pts': round(float(subset['fwd_30m'].mean()), 2),
                'mean_fwd_1h_pts': round(float(subset['fwd_1h'].mean()), 2),
                'mean_mfe': round(float(subset['mfe'].mean()), 2),
                'mean_mae': round(float(subset['mae'].mean()), 2),
                'mfe_mae_ratio': round(float(subset['mfe'].mean() / subset['mae'].mean()), 2) if subset['mae'].mean() > 0 else 0
            }

    # =================================================================
    # 4. LONG / SHORT ASYMMETRY (PDH vs PDL)
    # =================================================================
    asymmetry_summary = {}
    for ev_type in ['PDH_SWEEP_SHORT', 'PDL_SWEEP_LONG']:
        sub = df_events[df_events['event_type'] == ev_type]
        if len(sub) > 0:
            asymmetry_summary[ev_type] = {
                'count': len(sub),
                'avg_penetration_pts': round(float(sub['penetration'].mean()), 2),
                'avg_wick_ratio': round(float(sub['wick_ratio'].mean()), 3),
                'win_rate_30m': round(float((sub['fwd_30m'] > 0).mean() * 100), 2),
                'win_rate_1h': round(float((sub['fwd_1h'] > 0).mean() * 100), 2),
                'mean_fwd_30m_pts': round(float(sub['fwd_30m'].mean()), 2),
                'mean_fwd_1h_pts': round(float(sub['fwd_1h'].mean()), 2),
                'mean_mfe': round(float(sub['mfe'].mean()), 2),
                'mean_mae': round(float(sub['mae'].mean()), 2),
                'mean_t1_drift': round(float(sub['ret_t1'].mean()), 2),
                'mean_t3_drift': round(float(sub['ret_t3'].mean()), 2),
            }

    # =================================================================
    # 5. CHRONOLOGICAL WALK-FORWARD STABILITY (35% Wick Threshold)
    # =================================================================
    df_events_35 = df_events[df_events['wick_ratio'] >= 0.35].copy()
    wf_splits = {
        'Train (2021-2023)': df_events_35[df_events_35['year'] <= 2023],
        'Validation (2024)': df_events_35[df_events_35['year'] == 2024],
        'Test (2025-2026)': df_events_35[df_events_35['year'] >= 2025],
    }
    wf_stability = {}
    for split_name, s_df in wf_splits.items():
        if len(s_df) > 0:
            wf_stability[split_name] = {
                'count': len(s_df),
                'win_rate_30m': round(float((s_df['fwd_30m'] > 0).mean() * 100), 2),
                'win_rate_1h': round(float((s_df['fwd_1h'] > 0).mean() * 100), 2),
                'mean_fwd_30m': round(float(s_df['fwd_30m'].mean()), 2),
                'mean_fwd_1h': round(float(s_df['fwd_1h'].mean()), 2),
                'mean_mfe': round(float(s_df['mfe'].mean()), 2),
                'mean_mae': round(float(s_df['mae'].mean()), 2),
            }

    # =================================================================
    # 6. TIME-OF-DAY BREAKDOWN OF SWEEPS
    # =================================================================
    df_events['tod_bucket'] = 'MIDDAY (11:00-13:30)'
    # Parse time
    for i, r in df_events.iterrows():
        t_str = r['time']
        t_val = datetime.strptime(t_str, "%H:%M:%S").time()
        if t_val < time(10, 0):
            df_events.at[i, 'tod_bucket'] = 'EARLY_MORNING (09:15-10:00)'
        elif t_val < time(11, 0):
            df_events.at[i, 'tod_bucket'] = 'MORNING (10:00-11:00)'
        elif t_val > time(13, 30):
            df_events.at[i, 'tod_bucket'] = 'AFTERNOON (13:30-15:00)'

    tod_summary = {}
    for tod_name, grp in df_events[df_events['wick_ratio'] >= 0.30].groupby('tod_bucket'):
        tod_summary[tod_name] = {
            'count': len(grp),
            'win_rate_30m': round(float((grp['fwd_30m'] > 0).mean() * 100), 2),
            'mean_fwd_30m': round(float(grp['fwd_30m'].mean()), 2),
            'mean_mfe': round(float(grp['mfe'].mean()), 2),
            'mean_mae': round(float(grp['mae'].mean()), 2),
        }

    results = {
        'total_valid_days': len(df_daily_valid),
        'total_sweeps_captured': len(df_events),
        'proximity_volatility': prox_vol_results,
        'touch_comparison': touch_comparison,
        'wick_sensitivity': wick_sensitivity,
        'asymmetry_summary': asymmetry_summary,
        'walk_forward_stability': wf_stability,
        'time_of_day_summary': tod_summary,
    }

    # Save to JSON
    with open("research/price_action/pdh_pdl_metrics.json", "w") as f:
        json.dump(results, f, indent=2)
    print("[OK] Saved research/price_action/pdh_pdl_metrics.json")

    # Export clean CSV
    df_events.to_csv("research/price_action/PDH_PDL_EVENTS.csv", index=False)
    print(f"[OK] Saved research/price_action/PDH_PDL_EVENTS.csv with {len(df_events)} events.")

    return results


if __name__ == "__main__":
    res = run_pdh_pdl_research()
    print("\n--- Summary of Wick Sensitivity ---")
    for k, v in res['wick_sensitivity'].items():
        print(f"{k}: Count {v['events_count']} | Win Rate 30M: {v['win_rate_30m']}% | MFE/MAE: {v['mfe_mae_ratio']}")
