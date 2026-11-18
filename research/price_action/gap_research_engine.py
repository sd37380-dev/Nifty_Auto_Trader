"""
Deep Opening Gap Behaviour Research Engine for NIFTY 50 Spot.
Comprehensive quantitative analysis of overnight gaps across 5 years (2021-2026).
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


def build_daily_and_gap_dataset(df_5m: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Constructs clean daily summaries and opening gap metrics for every trading day.
    Includes zero look-ahead rolling daily features (ATR14, 20-MA, 50-MA, PDH, PDL, PDC, PDO).
    """
    # Group 5m bars by date
    days = []
    grouped = df_5m.groupby('date_ist')
    
    for dt, group in grouped:
        if len(group) < 30:  # Skip incomplete sessions (e.g. truncated / irregular)
            continue
        days.append({
            'date': dt,
            'open': group.iloc[0]['open'],
            'high': group['high'].max(),
            'low': group['low'].min(),
            'close': group.iloc[-1]['close'],
            'bars_count': len(group),
            'start_time': group.iloc[0]['time_ist'],
            'end_time': group.iloc[-1]['time_ist'],
        })

    df_daily = pd.DataFrame(days).sort_values('date').reset_index(drop=True)

    # Compute daily True Range and ATR
    prev_close = df_daily['close'].shift(1)
    tr1 = df_daily['high'] - df_daily['low']
    tr2 = (df_daily['high'] - prev_close).abs()
    tr3 = (df_daily['low'] - prev_close).abs()
    df_daily['tr'] = np.maximum(tr1, np.maximum(tr2, tr3))
    df_daily['atr14'] = df_daily['tr'].rolling(window=14).mean()
    df_daily['ma20'] = df_daily['close'].rolling(window=20).mean()
    df_daily['ma50'] = df_daily['close'].rolling(window=50).mean()

    # Prior day features strictly shifted by 1 (no look-ahead for day T)
    df_daily['pdc'] = df_daily['close'].shift(1)
    df_daily['pdo'] = df_daily['open'].shift(1)
    df_daily['pdh'] = df_daily['high'].shift(1)
    df_daily['pdl'] = df_daily['low'].shift(1)
    df_daily['pdrange'] = df_daily['pdh'] - df_daily['pdl']
    df_daily['pdatr14'] = df_daily['atr14'].shift(1)
    df_daily['pd_ma20'] = df_daily['ma20'].shift(1)
    df_daily['pd_ma50'] = df_daily['ma50'].shift(1)
    df_daily['pd_is_bullish'] = df_daily['pdc'] > df_daily['pdo']

    # Filter out initial warmup days
    df_daily_valid = df_daily.dropna(subset=['pdc', 'pdatr14', 'pd_ma50']).copy().reset_index(drop=True)

    # Now calculate gap metrics for each valid day
    gap_records = []
    
    # Pre-index 5m groups for fast retrieval
    group_dict = {dt: g.reset_index(drop=True) for dt, g in grouped}

    for idx, row in df_daily_valid.iterrows():
        dt = row['date']
        bars = group_dict.get(dt)
        if bars is None or len(bars) == 0:
            continue

        open_0915 = bars.iloc[0]['open']
        pdc = row['pdc']
        pdo = row['pdo']
        pdh = row['pdh']
        pdl = row['pdl']
        pdrange = row['pdrange']
        pdatr = row['pdatr14']
        
        gap = open_0915 - pdc
        gap_abs = abs(gap)
        gap_pct = (gap / pdc) * 100.0 if pdc > 0 else 0.0
        gap_in_atr = gap_abs / pdatr if pdatr > 0 else 0.0
        gap_in_pdrange = gap_abs / pdrange if pdrange > 0 else 0.0
        gap_dir = 'UP' if gap > 2.0 else ('DOWN' if gap < -2.0 else 'FLAT')

        # First 5M, 15M, 30M bar metrics
        bar_5m = bars.iloc[0]
        c_5m = bar_5m['close']
        h_5m = bar_5m['high']
        l_5m = bar_5m['low']
        ret_5m = c_5m - open_0915
        dir_5m = 'UP' if ret_5m > 0 else ('DOWN' if ret_5m < 0 else 'FLAT')

        # First 15M (first 3 bars)
        bars_15m = bars.iloc[:min(3, len(bars))]
        h_15m = bars_15m['high'].max()
        l_15m = bars_15m['low'].min()
        c_15m = bars_15m.iloc[-1]['close']
        ret_15m = c_15m - open_0915
        dir_15m = 'UP' if ret_15m > 0 else ('DOWN' if ret_15m < 0 else 'FLAT')

        # First 30M (first 6 bars)
        bars_30m = bars.iloc[:min(6, len(bars))]
        h_30m = bars_30m['high'].max()
        l_30m = bars_30m['low'].min()
        c_30m = bars_30m.iloc[-1]['close']
        ret_30m = c_30m - open_0915
        dir_30m = 'UP' if ret_30m > 0 else ('DOWN' if ret_30m < 0 else 'FLAT')

        # Session Extremes
        day_high = row['high']
        day_low = row['low']
        day_close = row['close']
        close_to_close_ret = day_close - pdc
        open_to_close_ret = day_close - open_0915

        # Check Gap Fill (Did price touch PDC?)
        is_filled = False
        fill_bar_idx = None
        fill_time = None
        minutes_to_fill = None

        if gap_dir == 'UP':
            # Price touches PDC if Low <= PDC
            fill_mask = bars['low'] <= pdc
            if fill_mask.any():
                is_filled = True
                fill_bar_idx = fill_mask.idxmax()
                fill_time = bars.iloc[fill_bar_idx]['time_ist']
                minutes_to_fill = (fill_bar_idx + 1) * 5
        elif gap_dir == 'DOWN':
            # Price touches PDC if High >= PDC
            fill_mask = bars['high'] >= pdc
            if fill_mask.any():
                is_filled = True
                fill_bar_idx = fill_mask.idxmax()
                fill_time = bars.iloc[fill_bar_idx]['time_ist']
                minutes_to_fill = (fill_bar_idx + 1) * 5
        else: # FLAT
            is_filled = True
            fill_bar_idx = 0
            fill_time = bars.iloc[0]['time_ist']
            minutes_to_fill = 5

        # Fill timing checkpoints
        filled_before_1000 = False
        filled_before_1100 = False
        filled_before_1200 = False
        filled_before_close = is_filled

        if is_filled and fill_time is not None:
            filled_before_1000 = fill_time < time(10, 0)
            filled_before_1100 = fill_time < time(11, 0)
            filled_before_1200 = fill_time < time(12, 0)

        # Continuation & Excursion Measures
        if gap_dir == 'UP':
            mfe_gap_dir = day_high - open_0915
            mae_against_gap = open_0915 - day_low
            signed_day_ret = open_to_close_ret
            # Forward returns at bar intervals
            fwd_ret_5m = ret_5m
            fwd_ret_15m = ret_15m
            fwd_ret_30m = ret_30m
            fwd_ret_1h = bars.iloc[min(11, len(bars)-1)]['close'] - open_0915
            fwd_ret_2h = bars.iloc[min(23, len(bars)-1)]['close'] - open_0915
            fwd_ret_4h = bars.iloc[min(47, len(bars)-1)]['close'] - open_0915
        elif gap_dir == 'DOWN':
            mfe_gap_dir = open_0915 - day_low
            mae_against_gap = day_high - open_0915
            signed_day_ret = -open_to_close_ret
            fwd_ret_5m = -ret_5m
            fwd_ret_15m = -ret_15m
            fwd_ret_30m = -ret_30m
            fwd_ret_1h = -(bars.iloc[min(11, len(bars)-1)]['close'] - open_0915)
            fwd_ret_2h = -(bars.iloc[min(23, len(bars)-1)]['close'] - open_0915)
            fwd_ret_4h = -(bars.iloc[min(47, len(bars)-1)]['close'] - open_0915)
        else:
            mfe_gap_dir = 0.0
            mae_against_gap = 0.0
            signed_day_ret = 0.0
            fwd_ret_5m = 0.0
            fwd_ret_15m = 0.0
            fwd_ret_30m = 0.0
            fwd_ret_1h = 0.0
            fwd_ret_2h = 0.0
            fwd_ret_4h = 0.0

        # Multi-day forward returns (Day T close to T+1, T+2, T+3, T+5 close)
        ret_t1 = np.nan
        ret_t2 = np.nan
        ret_t3 = np.nan
        ret_t5 = np.nan
        if idx + 1 < len(df_daily_valid):
            ret_t1 = df_daily_valid.iloc[idx + 1]['close'] - day_close
        if idx + 2 < len(df_daily_valid):
            ret_t2 = df_daily_valid.iloc[idx + 2]['close'] - day_close
        if idx + 3 < len(df_daily_valid):
            ret_t3 = df_daily_valid.iloc[idx + 3]['close'] - day_close
        if idx + 5 < len(df_daily_valid):
            ret_t5 = df_daily_valid.iloc[idx + 5]['close'] - day_close

        # Signed multi-day return in gap direction
        if gap_dir == 'DOWN':
            ret_t1 = -ret_t1 if not np.isnan(ret_t1) else np.nan
            ret_t2 = -ret_t2 if not np.isnan(ret_t2) else np.nan
            ret_t3 = -ret_t3 if not np.isnan(ret_t3) else np.nan
            ret_t5 = -ret_t5 if not np.isnan(ret_t5) else np.nan
        elif gap_dir == 'FLAT':
            ret_t1, ret_t2, ret_t3, ret_t5 = 0.0, 0.0, 0.0, 0.0

        # Structure relationship with PDH / PDL
        gap_rel_structure = "INSIDE_RANGE"
        if open_0915 > pdh:
            gap_rel_structure = "ABOVE_PDH"
        elif open_0915 < pdl:
            gap_rel_structure = "BELOW_PDL"
        elif gap_dir == 'UP' and open_0915 > pdc:
            gap_rel_structure = "UP_INTO_PDH"
        elif gap_dir == 'DOWN' and open_0915 < pdc:
            gap_rel_structure = "DOWN_INTO_PDL"

        # Gap Regime Classification
        # 1. Fill Regime: touched PDC during session
        # 2. Continuation Regime: Never touched PDC AND closed further in gap direction
        # 3. Reversal Regime: Touched PDC AND closed past PDC in opposite direction
        if not is_filled and signed_day_ret > 0:
            regime = "CONTINUATION"
        elif is_filled:
            if (gap_dir == 'UP' and day_close < pdc) or (gap_dir == 'DOWN' and day_close > pdc):
                regime = "REVERSAL"
            else:
                regime = "FILL_AND_HOLD"
        else:
            regime = "FAILED_NO_FILL"

        gap_records.append({
            'date': dt,
            'year': dt.year,
            'open_0915': open_0915,
            'pdc': pdc,
            'pdo': pdo,
            'pdh': pdh,
            'pdl': pdl,
            'pdrange': pdrange,
            'pdatr14': pdatr,
            'pd_is_bullish': row['pd_is_bullish'],
            'pd_ma20': row['pd_ma20'],
            'pd_ma50': row['pd_ma50'],
            'macro_regime': 'BULLISH' if row['pd_ma20'] > row['pd_ma50'] else 'BEARISH',
            'gap': gap,
            'gap_abs': gap_abs,
            'gap_pct': gap_pct,
            'gap_in_atr': gap_in_atr,
            'gap_in_pdrange': gap_in_pdrange,
            'gap_dir': gap_dir,
            'dir_5m': dir_5m,
            'dir_15m': dir_15m,
            'dir_30m': dir_30m,
            'h_15m': h_15m,
            'l_15m': l_15m,
            'c_15m': c_15m,
            'h_30m': h_30m,
            'l_30m': l_30m,
            'c_30m': c_30m,
            'day_high': day_high,
            'day_low': day_low,
            'day_close': day_close,
            'close_to_close_ret': close_to_close_ret,
            'open_to_close_ret': open_to_close_ret,
            'signed_day_ret': signed_day_ret,
            'is_filled': is_filled,
            'fill_time': str(fill_time) if fill_time is not None else None,
            'minutes_to_fill': minutes_to_fill,
            'filled_before_1000': filled_before_1000,
            'filled_before_1100': filled_before_1100,
            'filled_before_1200': filled_before_1200,
            'mfe_gap_dir': mfe_gap_dir,
            'mae_against_gap': mae_against_gap,
            'fwd_ret_5m': fwd_ret_5m,
            'fwd_ret_15m': fwd_ret_15m,
            'fwd_ret_30m': fwd_ret_30m,
            'fwd_ret_1h': fwd_ret_1h,
            'fwd_ret_2h': fwd_ret_2h,
            'fwd_ret_4h': fwd_ret_4h,
            'ret_t1': ret_t1,
            'ret_t2': ret_t2,
            'ret_t3': ret_t3,
            'ret_t5': ret_t5,
            'gap_rel_structure': gap_rel_structure,
            'regime': regime
        })

    df_gaps = pd.DataFrame(gap_records)
    return df_daily_valid, df_gaps


def assign_gap_buckets(df: pd.DataFrame) -> pd.DataFrame:
    """
    Assigns absolute point buckets and percentile buckets.
    """
    df = df.copy()

    # Absolute point bins
    # 0-5, 5-15, 15-30, 30-50, 50-75, 75-100, 100-150, 150-200, 200+
    bins = [0, 5, 15, 30, 50, 75, 100, 150, 200, 10000]
    labels = [
        '0-5 pts',
        '5-15 pts',
        '15-30 pts',
        '30-50 pts',
        '50-75 pts',
        '75-100 pts',
        '100-150 pts',
        '150-200 pts',
        '200+ pts'
    ]
    df['point_bucket'] = pd.cut(df['gap_abs'], bins=bins, labels=labels, right=True, include_lowest=True)

    # ATR-normalized bins
    # 0-0.2x, 0.2-0.5x, 0.5-0.8x, 0.8-1.2x, 1.2-1.5x, >1.5x
    atr_bins = [0, 0.2, 0.5, 0.8, 1.2, 1.5, 100]
    atr_labels = ['0-0.2x ATR', '0.2-0.5x ATR', '0.5-0.8x ATR', '0.8-1.2x ATR', '1.2-1.5x ATR', '>1.5x ATR']
    df['atr_bucket'] = pd.cut(df['gap_in_atr'], bins=atr_bins, labels=atr_labels, right=True, include_lowest=True)

    # Percentile categories
    df['gap_pctile'] = df['gap_abs'].rank(pct=True) * 100.0

    # Volatility regime (based on pdatr14 percentiles)
    atr_p25 = df['pdatr14'].quantile(0.25)
    atr_p75 = df['pdatr14'].quantile(0.75)
    df['vol_regime'] = 'NORMAL_VOL'
    df.loc[df['pdatr14'] > atr_p75, 'vol_regime'] = 'HIGH_VOL'
    df.loc[df['pdatr14'] < atr_p25, 'vol_regime'] = 'LOW_VOL'

    return df


def run_full_gap_research() -> Dict[str, Any]:
    print("Loading 5-minute NIFTY dataset...")
    df_5m, clean_stats = load_and_clean_nifty_5m()
    print(f"Total clean 5M bars: {len(df_5m)}")

    print("Building daily summaries and zero-lookahead gap metrics...")
    df_daily, df_gaps = build_daily_and_gap_dataset(df_5m)
    df_gaps = assign_gap_buckets(df_gaps)
    print(f"Total analyzed gap sessions: {len(df_gaps)}")

    # =================================================================
    # SECTION 1: UNCONDITIONAL GAP DISTRIBUTION
    # =================================================================
    total_sessions = len(df_gaps)
    gap_abs_series = df_gaps['gap_abs']
    gap_signed_series = df_gaps['gap']

    uncond_dist = {
        'total_sessions': total_sessions,
        'mean_signed_gap': round(float(gap_signed_series.mean()), 2),
        'median_signed_gap': round(float(gap_signed_series.median()), 2),
        'mean_abs_gap': round(float(gap_abs_series.mean()), 2),
        'median_abs_gap': round(float(gap_abs_series.median()), 2),
        'std_gap': round(float(gap_signed_series.std()), 2),
        'min_gap': round(float(gap_signed_series.min()), 2),
        'max_gap': round(float(gap_signed_series.max()), 2),
        'gap_up_count': int((df_gaps['gap_dir'] == 'UP').sum()),
        'gap_up_pct': round(float((df_gaps['gap_dir'] == 'UP').mean() * 100), 2),
        'gap_down_count': int((df_gaps['gap_dir'] == 'DOWN').sum()),
        'gap_down_pct': round(float((df_gaps['gap_dir'] == 'DOWN').mean() * 100), 2),
        'flat_count': int((df_gaps['gap_dir'] == 'FLAT').sum()),
        'flat_pct': round(float((df_gaps['gap_dir'] == 'FLAT').mean() * 100), 2),
        'percentiles': {
            'p10': round(float(gap_abs_series.quantile(0.10)), 2),
            'p25': round(float(gap_abs_series.quantile(0.25)), 2),
            'p50': round(float(gap_abs_series.quantile(0.50)), 2),
            'p75': round(float(gap_abs_series.quantile(0.75)), 2),
            'p90': round(float(gap_abs_series.quantile(0.90)), 2),
            'p95': round(float(gap_abs_series.quantile(0.95)), 2),
            'p99': round(float(gap_abs_series.quantile(0.99)), 2),
        }
    }

    # Bucket frequency table
    bucket_freq = {}
    for b_label, group in df_gaps.groupby('point_bucket', observed=False):
        bucket_freq[str(b_label)] = {
            'count': len(group),
            'pct_of_all': round(len(group) / total_sessions * 100.0, 2),
            'avg_gap_pts': round(float(group['gap_abs'].mean()), 2) if len(group) > 0 else 0.0,
            'fill_rate': round(float(group['is_filled'].mean() * 100.0), 2) if len(group) > 0 else 0.0,
            'avg_minutes_to_fill': round(float(group[group['is_filled']]['minutes_to_fill'].mean()), 1) if group['is_filled'].sum() > 0 else 0.0,
            'fill_before_1000_rate': round(float(group['filled_before_1000'].mean() * 100.0), 2) if len(group) > 0 else 0.0,
            'fill_before_1100_rate': round(float(group['filled_before_1100'].mean() * 100.0), 2) if len(group) > 0 else 0.0,
            'fill_before_1200_rate': round(float(group['filled_before_1200'].mean() * 100.0), 2) if len(group) > 0 else 0.0,
            'mfe_gap_dir_pts': round(float(group['mfe_gap_dir'].mean()), 2) if len(group) > 0 else 0.0,
            'mae_against_gap_pts': round(float(group['mae_against_gap'].mean()), 2) if len(group) > 0 else 0.0,
            'signed_day_ret_pts': round(float(group['signed_day_ret'].mean()), 2) if len(group) > 0 else 0.0,
            'fwd_ret_30m': round(float(group['fwd_ret_30m'].mean()), 2) if len(group) > 0 else 0.0,
            'fwd_ret_1h': round(float(group['fwd_ret_1h'].mean()), 2) if len(group) > 0 else 0.0,
            'fwd_ret_t1': round(float(group['ret_t1'].mean()), 2) if len(group) > 0 else 0.0,
            'fwd_ret_t3': round(float(group['ret_t3'].mean()), 2) if len(group) > 0 else 0.0,
        }

    # ATR bucket frequency table
    atr_bucket_freq = {}
    for b_label, group in df_gaps.groupby('atr_bucket', observed=False):
        atr_bucket_freq[str(b_label)] = {
            'count': len(group),
            'pct_of_all': round(len(group) / total_sessions * 100.0, 2),
            'fill_rate': round(float(group['is_filled'].mean() * 100.0), 2) if len(group) > 0 else 0.0,
            'signed_day_ret_pts': round(float(group['signed_day_ret'].mean()), 2) if len(group) > 0 else 0.0,
        }

    # Yearly breakdown
    yearly_stats = {}
    for yr, group in df_gaps.groupby('year'):
        yearly_stats[str(yr)] = {
            'sessions': len(group),
            'avg_abs_gap': round(float(group['gap_abs'].mean()), 2),
            'median_abs_gap': round(float(group['gap_abs'].median()), 2),
            'large_gaps_gt_100_pct': round(float((group['gap_abs'] >= 100).mean() * 100.0), 2),
            'fill_rate': round(float(group['is_filled'].mean() * 100.0), 2),
            'avg_day_signed_ret': round(float(group['signed_day_ret'].mean()), 2),
        }

    # Volatility regime breakdown
    vol_stats = {}
    for v_reg, group in df_gaps.groupby('vol_regime'):
        vol_stats[str(v_reg)] = {
            'sessions': len(group),
            'avg_abs_gap': round(float(group['gap_abs'].mean()), 2),
            'fill_rate': round(float(group['is_filled'].mean() * 100.0), 2),
            'large_gaps_pct': round(float((group['gap_abs'] >= 100).mean() * 100.0), 2),
        }

    # Large Gap Clustering
    # Are large gaps (>75 pts) more likely to be followed by another large gap?
    df_gaps['is_large_gap'] = df_gaps['gap_abs'] >= 75
    df_gaps['next_is_large_gap'] = df_gaps['is_large_gap'].shift(-1)
    large_gap_cluster_prob = round(float(df_gaps[df_gaps['is_large_gap']]['next_is_large_gap'].mean() * 100.0), 2)
    uncond_large_gap_prob = round(float(df_gaps['is_large_gap'].mean() * 100.0), 2)

    # Directional Gap Fill comparison
    dir_fill_comp = {}
    for g_dir in ['UP', 'DOWN']:
        grp = df_gaps[df_gaps['gap_dir'] == g_dir]
        dir_fill_comp[g_dir] = {
            'count': len(grp),
            'fill_rate': round(float(grp['is_filled'].mean() * 100.0), 2),
            'avg_abs_gap': round(float(grp['gap_abs'].mean()), 2),
            'avg_mfe': round(float(grp['mfe_gap_dir'].mean()), 2),
            'avg_mae': round(float(grp['mae_against_gap'].mean()), 2),
            'avg_signed_day_ret': round(float(grp['signed_day_ret'].mean()), 2),
        }

    # Prior Day Trend interaction
    prior_trend_stats = {}
    for p_bull in [True, False]:
        for g_dir in ['UP', 'DOWN']:
            grp = df_gaps[(df_gaps['pd_is_bullish'] == p_bull) & (df_gaps['gap_dir'] == g_dir)]
            lbl = f"{'Bullish' if p_bull else 'Bearish'} Day -> Gap {g_dir}"
            prior_trend_stats[lbl] = {
                'count': len(grp),
                'fill_rate': round(float(grp['is_filled'].mean() * 100.0), 2),
                'avg_signed_day_ret': round(float(grp['signed_day_ret'].mean()), 2),
                'avg_mfe': round(float(grp['mfe_gap_dir'].mean()), 2),
                'avg_mae': round(float(grp['mae_against_gap'].mean()), 2),
            }

    # Proximity to PDH / PDL
    structure_stats = {}
    for s_label, group in df_gaps.groupby('gap_rel_structure'):
        structure_stats[str(s_label)] = {
            'count': len(group),
            'fill_rate': round(float(group['is_filled'].mean() * 100.0), 2),
            'avg_mfe': round(float(group['mfe_gap_dir'].mean()), 2),
            'avg_mae': round(float(group['mae_against_gap'].mean()), 2),
            'avg_signed_day_ret': round(float(group['signed_day_ret'].mean()), 2),
        }

    # First 15M candle prediction
    first_15m_pred = {}
    for f_dir in ['UP', 'DOWN']:
        for g_dir in ['UP', 'DOWN']:
            grp = df_gaps[(df_gaps['dir_15m'] == f_dir) & (df_gaps['gap_dir'] == g_dir)]
            lbl = f"Gap {g_dir} + 15M {f_dir}"
            first_15m_pred[lbl] = {
                'count': len(grp),
                'fill_rate': round(float(grp['is_filled'].mean() * 100.0), 2),
                'continuation_day_ret': round(float(grp['signed_day_ret'].mean()), 2),
            }

    # Gap Regime Frequencies
    regime_freq = {}
    for reg, grp in df_gaps.groupby('regime'):
        regime_freq[str(reg)] = {
            'count': len(grp),
            'pct_of_all': round(len(grp) / total_sessions * 100.0, 2),
            'avg_abs_gap': round(float(grp['gap_abs'].mean()), 2),
            'avg_signed_day_ret': round(float(grp['signed_day_ret'].mean()), 2),
            'avg_ret_t1': round(float(grp['ret_t1'].mean()), 2),
            'avg_ret_t3': round(float(grp['ret_t3'].mean()), 2),
        }

    # Multi-day continuation for unfilled large gaps (>100 pts)
    unfilled_large = df_gaps[(df_gaps['gap_abs'] >= 100) & (~df_gaps['is_filled'])]
    filled_large = df_gaps[(df_gaps['gap_abs'] >= 100) & (df_gaps['is_filled'])]
    unfilled_large_stats = {
        'unfilled_count': len(unfilled_large),
        'avg_day_signed_ret': round(float(unfilled_large['signed_day_ret'].mean()), 2),
        't1_continuation_rate': round(float((unfilled_large['ret_t1'] > 0).mean() * 100.0), 2),
        'avg_t1_signed_ret': round(float(unfilled_large['ret_t1'].mean()), 2),
        'avg_t3_signed_ret': round(float(unfilled_large['ret_t3'].mean()), 2),
        'avg_t5_signed_ret': round(float(unfilled_large['ret_t5'].mean()), 2),
    }

    results = {
        'unconditional_distribution': uncond_dist,
        'bucket_frequency': bucket_freq,
        'atr_bucket_frequency': atr_bucket_freq,
        'yearly_stats': yearly_stats,
        'volatility_stats': vol_stats,
        'large_gap_cluster_prob': large_gap_cluster_prob,
        'uncond_large_gap_prob': uncond_large_gap_prob,
        'directional_fill_comparison': dir_fill_comp,
        'prior_trend_stats': prior_trend_stats,
        'structure_stats': structure_stats,
        'first_15m_prediction': first_15m_pred,
        'regime_frequencies': regime_freq,
        'unfilled_large_gap_stats': unfilled_large_stats,
    }

    # Save to JSON
    with open("research/price_action/gap_research_metrics.json", "w") as f:
        json.dump(results, f, indent=2)
    print("[OK] Saved research/price_action/gap_research_metrics.json")

    # Export clean GAP_EVENTS.csv
    df_gaps.to_csv("research/price_action/GAP_EVENTS.csv", index=False)
    print(f"[OK] Saved research/price_action/GAP_EVENTS.csv with {len(df_gaps)} sessions.")

    return results


if __name__ == "__main__":
    res = run_full_gap_research()
    print("\n--- Summary of Core Gap Distribution ---")
    print(f"Total Sessions: {res['unconditional_distribution']['total_sessions']}")
    print(f"Mean Abs Gap: {res['unconditional_distribution']['mean_abs_gap']} pts")
    print(f"Median Abs Gap: {res['unconditional_distribution']['median_abs_gap']} pts")
    print(f"P(Large Gap Cluster): {res['large_gap_cluster_prob']}% vs Unconditional: {res['uncond_large_gap_prob']}%")
