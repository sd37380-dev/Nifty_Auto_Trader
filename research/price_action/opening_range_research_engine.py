"""
Topic 2 — Opening Range and First-Hour Behaviour Research Engine.
Comprehensive quantitative analysis of OR-5, OR-10, OR-15, OR-30, OR-45, and OR-60
across 5-year NIFTY Spot 5-minute dataset.
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


def run_opening_range_research():
    print("Loading 5-minute NIFTY dataset...")
    df_5m, clean_stats = load_and_clean_nifty_5m()
    print(f"Total clean 5M bars: {len(df_5m)}")

    # Group by date
    grouped = df_5m.groupby('date_ist')
    
    # Calculate daily statistics and ATR14 for normalization
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
    
    # Shift daily features to prevent look-ahead
    df_daily['pdatr14'] = df_daily['atr14'].shift(1)
    df_daily['pdc'] = df_daily['close'].shift(1)
    df_daily['pdo'] = df_daily['open'].shift(1)
    df_daily['pdh'] = df_daily['high'].shift(1)
    df_daily['pdl'] = df_daily['low'].shift(1)
    df_daily['pd_ma20'] = df_daily['ma20'].shift(1)
    df_daily['pd_ma50'] = df_daily['ma50'].shift(1)
    
    df_daily_valid = df_daily.dropna(subset=['pdatr14', 'pd_ma50']).copy().reset_index(drop=True)
    valid_dates = set(df_daily_valid['date'])
    daily_lookup = {r['date']: r for _, r in df_daily_valid.iterrows()}

    print(f"Total valid trading days: {len(df_daily_valid)}")

    # Durations in bars: 5m (1 bar), 10m (2 bars), 15m (3 bars), 30m (6 bars), 45m (9 bars), 60m (12 bars)
    or_durations = {
        'OR-5': 1,
        'OR-10': 2,
        'OR-15': 3,
        'OR-30': 6,
        'OR-45': 9,
        'OR-60': 12
    }

    # Data collection
    session_records = []
    breakout_records = []

    for idx, d_row in df_daily_valid.iterrows():
        dt = d_row['date']
        bars = group_dict.get(dt)
        if bars is None or len(bars) < 15:
            continue

        day_high = d_row['high']
        day_low = d_row['low']
        day_open = d_row['open']
        day_close = d_row['close']
        day_range = d_row['range']
        pdatr = d_row['pdatr14']
        pdc = d_row['pdc']
        gap = day_open - pdc
        gap_abs = abs(gap)
        gap_cat = "SMALL" if gap_abs < 30 else ("MEDIUM" if gap_abs < 75 else "LARGE")
        macro_trend = "BULLISH" if d_row['pd_ma20'] > d_row['pd_ma50'] else "BEARISH"
        
        # Volatility category
        vol_cat = "NORMAL"
        # We'll assign percentiles later

        rec = {
            'date': dt,
            'year': dt.year,
            'gap': gap,
            'gap_abs': gap_abs,
            'gap_cat': gap_cat,
            'macro_trend': macro_trend,
            'pdatr14': pdatr,
            'day_range': day_range,
            'day_open': day_open,
            'day_high': day_high,
            'day_low': day_low,
            'day_close': day_close,
        }

        # For each OR duration
        for or_name, n_bars in or_durations.items():
            or_bars = bars.iloc[:n_bars]
            or_high = or_bars['high'].max()
            or_low = or_bars['low'].min()
            or_open = or_bars.iloc[0]['open']
            or_close = or_bars.iloc[-1]['close']
            or_range = or_high - or_low
            or_range_atr = or_range / pdatr if pdatr > 0 else 0
            or_body = or_close - or_open
            or_dir = 'UP' if or_body > 1.0 else ('DOWN' if or_body < -1.0 else 'FLAT')
            close_loc = (or_close - or_low) / or_range if or_range > 0 else 0.5

            # Subsequent bars after opening range
            subseq_bars = bars.iloc[n_bars:]
            subseq_range = (subseq_bars['high'].max() - subseq_bars['low'].min()) if len(subseq_bars) > 0 else 0
            subseq_expansion = subseq_range / or_range if or_range > 0 else 1.0

            # Daily extreme occurrences within OR
            # Day high set in OR? (Within 0.5 point tolerance)
            dh_in_or = abs(or_high - day_high) <= 0.5
            dl_in_or = abs(or_low - day_low) <= 0.5
            either_in_or = dh_in_or or dl_in_or
            both_in_or = dh_in_or and dl_in_or

            rec[f'{or_name}_high'] = or_high
            rec[f'{or_name}_low'] = or_low
            rec[f'{or_name}_range'] = or_range
            rec[f'{or_name}_range_atr'] = or_range_atr
            rec[f'{or_name}_dir'] = or_dir
            rec[f'{or_name}_close_loc'] = close_loc
            rec[f'{or_name}_dh_in_or'] = dh_in_or
            rec[f'{or_name}_dl_in_or'] = dl_in_or
            rec[f'{or_name}_either_in_or'] = either_in_or
            rec[f'{or_name}_both_in_or'] = both_in_or
            rec[f'{or_name}_subseq_range'] = subseq_range
            rec[f'{or_name}_subseq_expansion'] = subseq_expansion

            # Breakout tracking (for OR-5, OR-15, OR-30, OR-60)
            if or_name in ['OR-5', 'OR-15', 'OR-30', 'OR-60']:
                first_bo_side = None
                first_bo_idx = None
                first_bo_time = None
                first_bo_price = None

                high_broken = False
                low_broken = False
                high_break_idx = None
                low_break_idx = None

                for b_idx in range(n_bars, len(bars)):
                    bar = bars.iloc[b_idx]
                    # Check High breakout
                    if not high_broken and bar['high'] > or_high:
                        high_broken = True
                        high_break_idx = b_idx
                        if first_bo_side is None:
                            first_bo_side = 'UP'
                            first_bo_idx = b_idx
                            first_bo_time = bar['time_ist']
                            first_bo_price = bar['close']
                    # Check Low breakdown
                    if not low_broken and bar['low'] < or_low:
                        low_broken = True
                        low_break_idx = b_idx
                        if first_bo_side is None:
                            first_bo_side = 'DOWN'
                            first_bo_idx = b_idx
                            first_bo_time = bar['time_ist']
                            first_bo_price = bar['close']

                two_sided = high_broken and low_broken
                rec[f'{or_name}_first_bo_side'] = first_bo_side
                rec[f'{or_name}_two_sided'] = two_sided

                # Breakout analytics if breakout occurred
                if first_bo_side is not None and first_bo_idx < len(bars) - 1:
                    post_bo_bars = bars.iloc[first_bo_idx + 1:]
                    if len(post_bo_bars) > 0:
                        if first_bo_side == 'UP':
                            mfe = post_bo_bars['high'].max() - or_high
                            mae = or_high - post_bo_bars['low'].min()
                            # Failure: did price re-enter OR? (Low < or_high)
                            reentered = (post_bo_bars['low'] < or_high).any()
                            # Retracement of 25%, 50% of OR range
                            retrace_25 = (post_bo_bars['low'] <= (or_high - 0.25 * or_range)).any()
                            retrace_50 = (post_bo_bars['low'] <= (or_high - 0.50 * or_range)).any()
                            full_reversal = (post_bo_bars['low'] < or_low).any()
                            # Time to MFE
                            mfe_idx = post_bo_bars['high'].idxmax()
                            time_to_mfe = (mfe_idx - first_bo_idx) * 5
                            final_close_diff = post_bo_bars.iloc[-1]['close'] - or_high
                        else: # DOWN
                            mfe = or_low - post_bo_bars['low'].min()
                            mae = post_bo_bars['high'].max() - or_low
                            reentered = (post_bo_bars['high'] > or_low).any()
                            retrace_25 = (post_bo_bars['high'] >= (or_low + 0.25 * or_range)).any()
                            retrace_50 = (post_bo_bars['high'] >= (or_low + 0.50 * or_range)).any()
                            full_reversal = (post_bo_bars['high'] > or_high).any()
                            mfe_idx = post_bo_bars['low'].idxmin()
                            time_to_mfe = (mfe_idx - first_bo_idx) * 5
                            final_close_diff = or_low - post_bo_bars.iloc[-1]['close']

                        breakout_records.append({
                            'date': dt,
                            'or_name': or_name,
                            'side': first_bo_side,
                            'bo_time': str(first_bo_time),
                            'mfe': mfe,
                            'mae': mae,
                            'reentered': reentered,
                            'retrace_25': retrace_25,
                            'retrace_50': retrace_50,
                            'full_reversal': full_reversal,
                            'time_to_mfe': time_to_mfe,
                            'final_close_diff': final_close_diff,
                            'is_continuation': final_close_diff > 0,
                            'gap_dir': 'UP' if gap > 0 else 'DOWN',
                            'aligned_with_gap': (first_bo_side == 'UP' and gap > 0) or (first_bo_side == 'DOWN' and gap < 0),
                            'aligned_with_trend': (first_bo_side == 'UP' and macro_trend == 'BULLISH') or (first_bo_side == 'DOWN' and macro_trend == 'BEARISH'),
                        })

        # Forward multi-day returns from today's close
        rec['ret_t1'] = np.nan
        rec['ret_t2'] = np.nan
        rec['ret_t3'] = np.nan
        if idx + 1 < len(df_daily_valid):
            rec['ret_t1'] = df_daily_valid.iloc[idx + 1]['close'] - day_close
        if idx + 2 < len(df_daily_valid):
            rec['ret_t2'] = df_daily_valid.iloc[idx + 2]['close'] - day_close
        if idx + 3 < len(df_daily_valid):
            rec['ret_t3'] = df_daily_valid.iloc[idx + 3]['close'] - day_close

        session_records.append(rec)

    df_sessions = pd.DataFrame(session_records)
    df_bo = pd.DataFrame(breakout_records)

    # Classify volatility regimes
    p25 = df_sessions['pdatr14'].quantile(0.25)
    p75 = df_sessions['pdatr14'].quantile(0.75)
    df_sessions['vol_regime'] = 'NORMAL'
    df_sessions.loc[df_sessions['pdatr14'] > p75, 'vol_regime'] = 'HIGH'
    df_sessions.loc[df_sessions['pdatr14'] < p25, 'vol_regime'] = 'LOW'

    total_n = len(df_sessions)

    # =================================================================
    # 1. OPENING RANGE STATS & EXTREMES
    # =================================================================
    or_summary = {}
    for or_name in or_durations.keys():
        rng = df_sessions[f'{or_name}_range']
        rng_atr = df_sessions[f'{or_name}_range_atr']
        dh = df_sessions[f'{or_name}_dh_in_or'].mean() * 100
        dl = df_sessions[f'{or_name}_dl_in_or'].mean() * 100
        either = df_sessions[f'{or_name}_either_in_or'].mean() * 100
        both = df_sessions[f'{or_name}_both_in_or'].mean() * 100
        sub_exp = df_sessions[f'{or_name}_subseq_expansion'].mean()

        # Correlation between OR range and subsequent range
        corr_rng = df_sessions[f'{or_name}_range'].corr(df_sessions[f'{or_name}_subseq_range'])
        
        # Persistence of opening direction (does day close in same direction as OR?)
        same_dir = (
            ((df_sessions[f'{or_name}_dir'] == 'UP') & (df_sessions['day_close'] > df_sessions['day_open'])) |
            ((df_sessions[f'{or_name}_dir'] == 'DOWN') & (df_sessions['day_close'] < df_sessions['day_open']))
        ).mean() * 100

        or_summary[or_name] = {
            'mean_range_pts': round(float(rng.mean()), 2),
            'median_range_pts': round(float(rng.median()), 2),
            'mean_range_atr': round(float(rng_atr.mean()), 3),
            'day_high_prob': round(float(dh), 2),
            'day_low_prob': round(float(dl), 2),
            'either_extreme_prob': round(float(either), 2),
            'both_extremes_prob': round(float(both), 2),
            'subseq_expansion_multiple': round(float(sub_exp), 2),
            'correlation_with_subseq_range': round(float(corr_rng), 3),
            'directional_persistence_prob': round(float(same_dir), 2)
        }

    # =================================================================
    # 2. BREAKOUT BEHAVIOUR (OR-5, OR-15, OR-30, OR-60)
    # =================================================================
    bo_summary = {}
    for or_name in ['OR-5', 'OR-15', 'OR-30', 'OR-60']:
        sub_bo = df_bo[df_bo['or_name'] == or_name]
        if len(sub_bo) == 0:
            continue
        bo_summary[or_name] = {
            'total_breakouts': len(sub_bo),
            'reentered_or_rate': round(float(sub_bo['reentered'].mean() * 100), 2),
            'retrace_25_rate': round(float(sub_bo['retrace_25'].mean() * 100), 2),
            'retrace_50_rate': round(float(sub_bo['retrace_50'].mean() * 100), 2),
            'full_reversal_rate': round(float(sub_bo['full_reversal'].mean() * 100), 2),
            'continuation_rate': round(float(sub_bo['is_continuation'].mean() * 100), 2),
            'mean_mfe': round(float(sub_bo['mfe'].mean()), 2),
            'mean_mae': round(float(sub_bo['mae'].mean()), 2),
            'mean_time_to_mfe_min': round(float(sub_bo['time_to_mfe'].mean()), 1),
            # Gap alignment impact
            'mfe_aligned_with_gap': round(float(sub_bo[sub_bo['aligned_with_gap']]['mfe'].mean()), 2),
            'mfe_opposed_gap': round(float(sub_bo[~sub_bo['aligned_with_gap']]['mfe'].mean()), 2),
            # Trend alignment impact
            'mfe_aligned_with_trend': round(float(sub_bo[sub_bo['aligned_with_trend']]['mfe'].mean()), 2),
            'mfe_opposed_trend': round(float(sub_bo[~sub_bo['aligned_with_trend']]['mfe'].mean()), 2),
        }

    # =================================================================
    # 3. TWO-SIDED BREAKOUTS
    # =================================================================
    two_sided_summary = {}
    for or_name in ['OR-5', 'OR-15', 'OR-30', 'OR-60']:
        col = f'{or_name}_two_sided'
        rate = df_sessions[col].mean() * 100
        # Average day range on two-sided vs one-sided days
        rng_two = df_sessions[df_sessions[col]]['day_range'].mean()
        rng_one = df_sessions[~df_sessions[col]]['day_range'].mean()
        two_sided_summary[or_name] = {
            'two_sided_breakout_rate': round(float(rate), 2),
            'mean_day_range_two_sided': round(float(rng_two), 2),
            'mean_day_range_one_sided': round(float(rng_one), 2)
        }

    # =================================================================
    # 4. VOLATILITY & GAP REGIME BREAKDOWNS (OR-15 Focus)
    # =================================================================
    or15_by_vol = {}
    for v_reg, grp in df_sessions.groupby('vol_regime'):
        or15_by_vol[v_reg] = {
            'sessions': len(grp),
            'mean_range_pts': round(float(grp['OR-15_range'].mean()), 2),
            'either_extreme_prob': round(float(grp['OR-15_either_in_or'].mean() * 100), 2),
            'two_sided_rate': round(float(grp['OR-15_two_sided'].mean() * 100), 2)
        }

    or15_by_gap = {}
    for g_cat, grp in df_sessions.groupby('gap_cat'):
        or15_by_gap[g_cat] = {
            'sessions': len(grp),
            'mean_range_pts': round(float(grp['OR-15_range'].mean()), 2),
            'either_extreme_prob': round(float(grp['OR-15_either_in_or'].mean() * 100), 2),
            'two_sided_rate': round(float(grp['OR-15_two_sided'].mean() * 100), 2)
        }

    # Multi-Day Predictive Utility (OR-15 Direction predicting T+1, T+2, T+3)
    or15_swing = {}
    for o_dir in ['UP', 'DOWN']:
        grp = df_sessions[df_sessions['OR-15_dir'] == o_dir]
        signed_factor = 1.0 if o_dir == 'UP' else -1.0
        or15_swing[o_dir] = {
            'sessions': len(grp),
            'same_day_dir_prob': round(float((grp['day_close'] > grp['day_open'] if o_dir == 'UP' else grp['day_close'] < grp['day_open']).mean() * 100), 2),
            't1_continuation_prob': round(float(((grp['ret_t1'] * signed_factor) > 0).mean() * 100), 2),
            'mean_t1_signed_drift': round(float((grp['ret_t1'] * signed_factor).mean()), 2),
            'mean_t3_signed_drift': round(float((grp['ret_t3'] * signed_factor).mean()), 2),
        }

    # Yearly breakdown for OR-15
    yearly_or15 = {}
    for yr, grp in df_sessions.groupby('year'):
        yearly_or15[str(yr)] = {
            'sessions': len(grp),
            'mean_range_pts': round(float(grp['OR-15_range'].mean()), 2),
            'either_extreme_prob': round(float(grp['OR-15_either_in_or'].mean() * 100), 2),
            'two_sided_rate': round(float(grp['OR-15_two_sided'].mean() * 100), 2),
        }

    output_metrics = {
        'total_sessions': total_n,
        'or_summary': or_summary,
        'bo_summary': bo_summary,
        'two_sided_summary': two_sided_summary,
        'or15_by_vol': or15_by_vol,
        'or15_by_gap': or15_by_gap,
        'or15_swing': or15_swing,
        'yearly_or15': yearly_or15,
    }

    # Export metrics to JSON
    with open("research/price_action/opening_range_metrics.json", "w") as f:
        json.dump(output_metrics, f, indent=2)
    print("[OK] Saved research/price_action/opening_range_metrics.json")

    # Export clean events CSV
    df_sessions.to_csv("research/price_action/OPENING_RANGE_EVENTS.csv", index=False)
    print(f"[OK] Saved research/price_action/OPENING_RANGE_EVENTS.csv with {len(df_sessions)} sessions.")

    return output_metrics


if __name__ == "__main__":
    res = run_opening_range_research()
    print("\n--- Summary of OR Extremes ---")
    for k, v in res['or_summary'].items():
        print(f"{k}: Range {v['mean_range_pts']} pts | Either Extreme: {v['either_extreme_prob']}% | Both: {v['both_extremes_prob']}%")
