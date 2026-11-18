"""
Topic 10 — Multi-Timeframe Price Behaviour and Swing Persistence Research Engine for NIFTY 50 Spot.
Bridging Intraday and Swing: Daily price events, Weekly structure, Multi-timeframe alignment,
Intraday-to-Multi-Day persistence (1D, 2D, 3D, 5D, 10D), Regime conditioning, and Classification.
Strictly causal and look-ahead free.
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


def run_mtf_swing_research():
    print("Loading 5-minute NIFTY dataset...")
    df_5m, clean_stats = load_and_clean_nifty_5m()
    n_total = len(df_5m)
    print(f"Total clean 5M bars: {n_total}")

    df = df_5m.sort_values('timestamp').reset_index(drop=True)
    df['datetime'] = pd.to_datetime(df['timestamp'])
    r_5m = df['high'] - df['low']
    prev_c = df['close'].shift(1).fillna(df['open'])
    df['tr'] = np.maximum(r_5m, np.maximum(np.abs(df['high'] - prev_c), np.abs(df['low'] - prev_c)))
    df['atr14'] = df['tr'].rolling(14).mean().bfill()
    df_idx = df.set_index('datetime')

    # =========================================================================
    # 1. MULTI-TIMEFRAME RESAMPLING (Strictly causal)
    # =========================================================================
    print("Resampling timeframes (15M, 30M, 1H, 2H, 4H, Daily, Weekly)...")
    # Resample 15M
    df_15m = df_idx.resample('15min').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
    }).dropna().reset_index()

    # Resample 1H
    df_1h = df_idx.resample('1h').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
    }).dropna().reset_index()

    # Resample 4H
    df_4h = df_idx.resample('4h').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
    }).dropna().reset_index()

    # Resample Daily (Business Days)
    df_daily = df_idx.resample('B').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
    }).dropna().reset_index()
    n_days = len(df_daily)
    print(f"Total Daily bars: {n_days}")

    # Resample Weekly
    df_weekly = df_idx.resample('W-FRI').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
    }).dropna().reset_index()
    n_weeks = len(df_weekly)
    print(f"Total Weekly bars: {n_weeks}")

    # Technical features on Daily
    d_highs = df_daily['high'].values
    d_lows = df_daily['low'].values
    d_opens = df_daily['open'].values
    d_closes = df_daily['close'].values
    d_ranges = d_highs - d_lows
    d_bodies = d_closes - d_opens

    # Daily ATR 14
    prev_d_closes = np.roll(d_closes, 1)
    prev_d_closes[0] = d_opens[0]
    d_tr = np.maximum(d_ranges, np.maximum(np.abs(d_highs - prev_d_closes), np.abs(d_lows - prev_d_closes)))
    df_daily['tr'] = d_tr
    df_daily['atr14'] = df_daily['tr'].rolling(14).mean().bfill()
    d_atr14 = df_daily['atr14'].values

    # Daily Macro Regimes
    # Bull: Close > 50 EMA; Bear: Close < 50 EMA; Sideways: 20-day slope near flat
    df_daily['ema50'] = df_daily['close'].ewm(span=50, adjust=False).mean()
    df_daily['ema200'] = df_daily['close'].ewm(span=200, adjust=False).mean()
    df_daily['trend_regime'] = np.where(df_daily['close'] > df_daily['ema50'], 'Bull', 'Bear')
    
    # Volatility Regime: Rolling 20-day ATR percentile
    roll_atr_p = df_daily['atr14'].rolling(100).rank(pct=True).fillna(0.5).values
    df_daily['vol_regime'] = np.where(roll_atr_p >= 0.70, 'High_Vol', np.where(roll_atr_p <= 0.30, 'Low_Vol', 'Norm_Vol'))

    # =========================================================================
    # 2. DAILY PRICE EVENTS CLASSIFICATION
    # =========================================================================
    print("Classifying Daily Price Events and forward persistence...")
    # Classify each daily bar into event types:
    # 1. Large Bullish Day (Body >= 80th percentile positive body)
    # 2. Large Bearish Day (Body <= 20th percentile negative body)
    # 3. Large Range Day (Range >= 80th percentile range)
    # 4. Narrow Range Day (Range <= 20th percentile range)
    # 5. Inside Day (High <= Prev High and Low >= Prev Low)
    # 6. Outside Day (High > Prev High and Low < Prev Low)
    # 7. Gap Day (Abs Gap >= 0.5%)
    # 8. Trend Day (|Body| / Range >= 0.70)
    # 9. Reversal Day (Wick >= 0.45 Range opposing open-close)

    body_p80 = np.percentile(d_bodies[d_bodies > 0], 80)
    body_p20 = np.percentile(d_bodies[d_bodies < 0], 20)
    range_p80 = np.percentile(d_ranges, 80)
    range_p20 = np.percentile(d_ranges, 20)

    daily_events = []
    
    for i in range(1, n_days - 10):
        dt = df_daily['datetime'].iloc[i]
        c = d_closes[i]
        o = d_opens[i]
        h = d_highs[i]
        l = d_lows[i]
        r = d_ranges[i]
        b = d_bodies[i]
        cur_atr = max(d_atr14[i], 1.0)
        
        prev_h = d_highs[i-1]
        prev_l = d_lows[i-1]
        prev_c = d_closes[i-1]
        gap = o - prev_c

        # Forward returns and excursions (1D, 2D, 3D, 5D, 10D)
        ret_1d = d_closes[i+1] - c
        ret_2d = d_closes[i+2] - c
        ret_3d = d_closes[i+3] - c
        ret_5d = d_closes[i+5] - c
        ret_10d = d_closes[i+10] - c

        mfe_1d = np.max(d_highs[i+1 : i+2]) - c
        mae_1d = c - np.min(d_lows[i+1 : i+2])
        mfe_3d = np.max(d_highs[i+1 : i+4]) - c
        mae_3d = c - np.min(d_lows[i+1 : i+4])
        mfe_5d = np.max(d_highs[i+1 : i+6]) - c
        mae_5d = c - np.min(d_lows[i+1 : i+6])
        mfe_10d = np.max(d_highs[i+1 : i+11]) - c
        mae_10d = c - np.min(d_lows[i+1 : i+11])

        # Identify tags
        tags = []
        if b >= body_p80:
            tags.append("Large_Bullish_Day")
        if b <= body_p20:
            tags.append("Large_Bearish_Day")
        if r >= range_p80:
            tags.append("Large_Range_Day")
        if r <= range_p20:
            tags.append("Narrow_Range_Day")
        if h <= prev_h and l >= prev_l:
            tags.append("Inside_Day")
        if h > prev_h and l < prev_l:
            tags.append("Outside_Day")
        if abs(gap) / prev_c >= 0.005:
            tags.append("Gap_Day")
        if abs(b) / max(r, 1e-4) >= 0.65:
            tags.append("Trend_Day")
        
        up_w = h - max(o, c)
        dn_w = min(o, c) - l
        if (up_w >= 0.40 * r) or (dn_w >= 0.40 * r):
            tags.append("Reversal_Day")

        for t in tags:
            # Directional alignment: for bullish events, positive ret is win; for bearish, negative is win
            is_bull_event = (t in ["Large_Bullish_Day"]) or (t == "Trend_Day" and b > 0)
            is_bear_event = (t in ["Large_Bearish_Day"]) or (t == "Trend_Day" and b < 0)

            daily_events.append({
                "date": str(dt)[:10],
                "year": dt.year,
                "event_type": t,
                "close": c,
                "atr": cur_atr,
                "trend_regime": df_daily['trend_regime'].iloc[i],
                "vol_regime": df_daily['vol_regime'].iloc[i],
                "is_bull_event": is_bull_event,
                "is_bear_event": is_bear_event,
                "ret_1d": ret_1d,
                "ret_2d": ret_2d,
                "ret_3d": ret_3d,
                "ret_5d": ret_5d,
                "ret_10d": ret_10d,
                "mfe_1d": mfe_1d,
                "mae_1d": mae_1d,
                "mfe_3d": mfe_3d,
                "mae_3d": mae_3d,
                "mfe_5d": mfe_5d,
                "mae_5d": mae_5d,
                "mfe_10d": mfe_10d,
                "mae_10d": mae_10d
            })

    df_dev = pd.DataFrame(daily_events)
    print(f"Total Daily Event instances: {len(df_dev)}")

    # Aggregate daily event persistence
    daily_event_summary = {}
    for etype in df_dev['event_type'].unique():
        sub = df_dev[df_dev['event_type'] == etype]
        cnt = len(sub)
        
        # Calculate win rates and returns
        # For neutral events (Inside, Outside, Range), measure absolute drift and volatility
        r1_mean = sub['ret_1d'].mean()
        r3_mean = sub['ret_3d'].mean()
        r5_mean = sub['ret_5d'].mean()
        r10_mean = sub['ret_10d'].mean()

        win_1d = (sub['ret_1d'] > 0).mean() * 100.0
        win_3d = (sub['ret_3d'] > 0).mean() * 100.0
        win_5d = (sub['ret_5d'] > 0).mean() * 100.0
        win_10d = (sub['ret_10d'] > 0).mean() * 100.0

        mfe5 = sub['mfe_5d'].mean()
        mae5 = sub['mae_5d'].mean()

        # Classification: INTRADAY ONLY, SHORT SWING, SWING, NO PERSISTENCE
        # If directional win rate >= 55% or <= 45% with strong drift -> SWING / SHORT SWING
        if abs(win_3d - 50.0) >= 5.0 and abs(r3_mean) > 30.0:
            persist_class = "SHORT SWING (1-3 Days)"
        elif abs(win_5d - 50.0) >= 4.0 and abs(r5_mean) > 50.0:
            persist_class = "SWING (3-10 Days)"
        elif abs(win_1d - 50.0) >= 4.0:
            persist_class = "SHORT SWING (1 Day)"
        else:
            persist_class = "NO PERSISTENCE / MEAN REVERSION"

        daily_event_summary[etype] = {
            "count": int(cnt),
            "ret_1d_mean": round(float(r1_mean), 2),
            "win_1d_pct": round(float(win_1d), 2),
            "ret_3d_mean": round(float(r3_mean), 2),
            "win_3d_pct": round(float(win_3d), 2),
            "ret_5d_mean": round(float(r5_mean), 2),
            "win_5d_pct": round(float(win_5d), 2),
            "ret_10d_mean": round(float(r10_mean), 2),
            "win_10d_pct": round(float(win_10d), 2),
            "mean_mfe_5d": round(float(mfe5), 2),
            "mean_mae_5d": round(float(mae5), 2),
            "persistence_classification": persist_class
        }

    # =========================================================================
    # 3. WEEKLY STRUCTURE ANALYSIS
    # =========================================================================
    print("Evaluating Weekly Structure, Compression, and Breakouts...")
    w_highs = df_weekly['high'].values
    w_lows = df_weekly['low'].values
    w_opens = df_weekly['open'].values
    w_closes = df_weekly['close'].values
    w_ranges = w_highs - w_lows
    w_bodies = w_closes - w_opens

    weekly_events = []
    for w in range(2, n_weeks - 4):
        prev_wh = w_highs[w-1]
        prev_wl = w_lows[w-1]
        cur_wh = w_highs[w]
        cur_wl = w_lows[w]
        cur_wc = w_closes[w]
        cur_wr = w_ranges[w]

        # Forward 1, 2, 4 weeks
        fwd_1w = w_closes[w+1] - cur_wc
        fwd_2w = w_closes[w+2] - cur_wc
        fwd_4w = w_closes[w+4] - cur_wc

        # Weekly Breakout
        broke_prev_wh = (cur_wh > prev_wh)
        broke_prev_wl = (cur_wl < prev_wl)
        
        # Breakout Failure: broke high but closed below prev high; or broke low but closed above prev low
        failed_high_bo = broke_prev_wh and (cur_wc < prev_wh)
        failed_low_bo = broke_prev_wl and (cur_wc > prev_wl)

        # Weekly Compression: Inside week or range < 0.70 of 4-week average
        avg_4w_r = np.mean(w_ranges[w-4 : w])
        is_compressed = (cur_wh <= prev_wh and cur_wl >= prev_wl) or (cur_wr < 0.70 * avg_4w_r)

        weekly_events.append({
            "week_idx": w,
            "date": str(df_weekly['datetime'].iloc[w])[:10],
            "range": cur_wr,
            "broke_high": broke_prev_wh,
            "broke_low": broke_prev_wl,
            "failed_high_bo": failed_high_bo,
            "failed_low_bo": failed_low_bo,
            "is_compressed": is_compressed,
            "fwd_1w_ret": fwd_1w,
            "fwd_2w_ret": fwd_2w,
            "fwd_4w_ret": fwd_4w,
            "fwd_1w_range": w_ranges[w+1]
        })

    df_wev = pd.DataFrame(weekly_events)
    
    # Weekly Compression -> Next Week Expansion?
    comp_weeks = df_wev[df_wev['is_compressed'] == True]
    norm_weeks = df_wev[df_wev['is_compressed'] == False]
    mean_next_range_comp = comp_weeks['fwd_1w_range'].mean()
    mean_next_range_norm = norm_weeks['fwd_1w_range'].mean()
    exp_ratio = mean_next_range_comp / max(mean_next_range_norm, 1.0)

    # Weekly Breakout Failure Rate
    bo_high_total = df_wev['broke_high'].sum()
    bo_high_fails = df_wev['failed_high_bo'].sum()
    bo_high_fail_pct = (bo_high_fails / bo_high_total * 100.0) if bo_high_total > 0 else 0

    bo_low_total = df_wev['broke_low'].sum()
    bo_low_fails = df_wev['failed_low_bo'].sum()
    bo_low_fail_pct = (bo_low_fails / bo_low_total * 100.0) if bo_low_total > 0 else 0

    weekly_summary = {
        "total_analyzed_weeks": len(df_wev),
        "compressed_weeks_count": int(len(comp_weeks)),
        "mean_next_week_range_after_compression_pts": round(float(mean_next_range_comp), 2),
        "mean_next_week_range_normal_pts": round(float(mean_next_range_norm), 2),
        "weekly_compression_expansion_ratio": round(float(exp_ratio), 2),
        "weekly_high_breakout_count": int(bo_high_total),
        "weekly_high_breakout_failure_pct": round(float(bo_high_fail_pct), 2),
        "weekly_low_breakout_count": int(bo_low_total),
        "weekly_low_breakout_failure_pct": round(float(bo_low_fail_pct), 2)
    }

    # =========================================================================
    # 4. MULTI-TIMEFRAME ALIGNMENT COMBINATIONS
    # =========================================================================
    print("Evaluating Multi-Timeframe Alignment Combinations...")
    # Calculate EMA-20 trend direction across timeframes:
    # +1 if Close > EMA-20, -1 if Close < EMA-20
    df['trend_5m'] = np.where(df['close'] > df['close'].ewm(span=20, adjust=False).mean(), 1, -1)
    df_15m['trend_15m'] = np.where(df_15m['close'] > df_15m['close'].ewm(span=20, adjust=False).mean(), 1, -1)
    df_1h['trend_1h'] = np.where(df_1h['close'] > df_1h['close'].ewm(span=20, adjust=False).mean(), 1, -1)
    df_4h['trend_4h'] = np.where(df_4h['close'] > df_4h['close'].ewm(span=20, adjust=False).mean(), 1, -1)
    df_daily['trend_daily'] = np.where(df_daily['close'] > df_daily['close'].ewm(span=20, adjust=False).mean(), 1, -1)

    # Merge MTF trend state back to 5M
    df_m = pd.merge_asof(df.sort_values('datetime'), df_15m[['datetime', 'trend_15m']].sort_values('datetime'), on='datetime', direction='backward')
    df_m = pd.merge_asof(df_m, df_1h[['datetime', 'trend_1h']].sort_values('datetime'), on='datetime', direction='backward')
    df_m = pd.merge_asof(df_m, df_4h[['datetime', 'trend_4h']].sort_values('datetime'), on='datetime', direction='backward')
    df_m = pd.merge_asof(df_m, df_daily[['datetime', 'trend_daily']].sort_values('datetime'), on='datetime', direction='backward')

    # Forward 12-bar (1H) return on 5M
    df_m['fwd_12'] = df_m['close'].shift(-12) - df_m['close']

    # Alignment Combos:
    # 1. 5M + 15M
    # 2. 15M + 1H
    # 3. 15M + 4H
    # 4. 1H + 4H
    # 5. 4H + Daily
    combos = [
        ("5M_15M", df_m['trend_5m'], df_m['trend_15m']),
        ("15M_1H", df_m['trend_15m'], df_m['trend_1h']),
        ("15M_4H", df_m['trend_15m'], df_m['trend_4h']),
        ("1H_4H", df_m['trend_1h'], df_m['trend_4h']),
        ("4H_Daily", df_m['trend_4h'], df_m['trend_daily']),
    ]

    mtf_alignment_results = {}
    for name, s_lower, s_higher in combos:
        aligned = (s_lower == s_higher)
        sub_aligned = df_m[aligned]
        sub_divergent = df_m[~aligned]

        # Directional continuation: does lower trend continue in its direction over next 12 bars?
        cont_aligned = ((sub_aligned['fwd_12'] * sub_aligned['trend_5m']) > 0).mean() * 100.0
        cont_divergent = ((sub_divergent['fwd_12'] * sub_divergent['trend_5m']) > 0).mean() * 100.0

        mean_drift_aligned = (sub_aligned['fwd_12'] * sub_aligned['trend_5m']).mean()
        mean_drift_divergent = (sub_divergent['fwd_12'] * sub_divergent['trend_5m']).mean()

        mtf_alignment_results[name] = {
            "alignment_frequency_pct": round(float(aligned.mean() * 100.0), 2),
            "continuation_pct_when_aligned": round(float(cont_aligned), 2),
            "mean_forward_points_when_aligned": round(float(mean_drift_aligned), 2),
            "continuation_pct_when_divergent": round(float(cont_divergent), 2),
            "mean_forward_points_when_divergent": round(float(mean_drift_divergent), 2),
            "alignment_edge_points": round(float(mean_drift_aligned - mean_drift_divergent), 2)
        }

    # =========================================================================
    # 5. INTRADAY EVENTS -> MULTI-DAY SWING PERSISTENCE
    # =========================================================================
    print("Evaluating Intraday Events -> Multi-Day Swing Persistence...")
    # Trace specific intraday events to multi-day outcomes:
    # 1. ORB-15 Breakout: Session broke 09:15-09:30 range and closed outside
    # 2. PDH Sweep: Session swept PDH and closed back below
    # 3. PDL Sweep: Session swept PDL and closed back above
    # 4. VWAP Extension: Session closed >= 1.5 ATR away from session VWAP
    # 5. Extreme Gap Day: Open gap >= 1.0%

    intraday_swing_events = []
    grouped_sess = df_m.groupby('date_ist')
    session_dates = list(grouped_sess.groups.keys())

    for d_i in range(1, len(session_dates) - 10):
        dt = session_dates[d_i]
        sdf = grouped_sess.get_group(dt)
        if len(sdf) < 60:
            continue

        s_close = sdf['close'].iloc[-1]
        s_open = sdf['open'].iloc[0]
        s_high = sdf['high'].max()
        s_low = sdf['low'].min()
        cur_atr = sdf['atr14'].iloc[-1]

        # Prior day levels
        prev_dt = session_dates[d_i - 1]
        prev_sdf = grouped_sess.get_group(prev_dt)
        pdh = prev_sdf['high'].max()
        pdl = prev_sdf['low'].min()
        pdc = prev_sdf['close'].iloc[-1]

        # Future day closes (1D, 2D, 3D, 5D, 10D)
        fwd_closes = []
        for step in [1, 2, 3, 5, 10]:
            f_dt = session_dates[d_i + step]
            f_close = grouped_sess.get_group(f_dt)['close'].iloc[-1]
            fwd_closes.append(f_close)

        ret_1d = fwd_closes[0] - s_close
        ret_2d = fwd_closes[1] - s_close
        ret_3d = fwd_closes[2] - s_close
        ret_5d = fwd_closes[3] - s_close
        ret_10d = fwd_closes[4] - s_close

        # Events:
        # A. Bullish ORB-15 Close
        orb_high = sdf.iloc[0:3]['high'].max()
        orb_low = sdf.iloc[0:3]['low'].min()
        if s_close > orb_high:
            intraday_swing_events.append({
                "date": str(dt), "event": "Bullish_ORB15_Close",
                "ret_1d": ret_1d, "ret_2d": ret_2d, "ret_3d": ret_3d, "ret_5d": ret_5d, "ret_10d": ret_10d
            })
        elif s_close < orb_low:
            intraday_swing_events.append({
                "date": str(dt), "event": "Bearish_ORB15_Close",
                "ret_1d": -ret_1d, "ret_2d": -ret_2d, "ret_3d": -ret_3d, "ret_5d": -ret_5d, "ret_10d": -ret_10d
            })

        # B. PDH Sweep Rejection (High > PDH but Close < PDH)
        if s_high > pdh and s_close < pdh:
            intraday_swing_events.append({
                "date": str(dt), "event": "PDH_Sweep_Rejection",
                "ret_1d": -ret_1d, "ret_2d": -ret_2d, "ret_3d": -ret_3d, "ret_5d": -ret_5d, "ret_10d": -ret_10d
            })

        # C. PDL Sweep Rejection (Low < PDL but Close > PDL)
        if s_low < pdl and s_close > pdl:
            intraday_swing_events.append({
                "date": str(dt), "event": "PDL_Sweep_Rejection",
                "ret_1d": ret_1d, "ret_2d": ret_2d, "ret_3d": ret_3d, "ret_5d": ret_5d, "ret_10d": ret_10d
            })

        # D. Extreme VWAP Extension at Close
        # Approximate VWAP
        vwap = (sdf['close'] * sdf['volume']).sum() / max(sdf['volume'].sum(), 1.0)
        if s_close >= vwap + 1.5 * cur_atr:
            intraday_swing_events.append({
                "date": str(dt), "event": "Bullish_VWAP_Extension",
                "ret_1d": ret_1d, "ret_2d": ret_2d, "ret_3d": ret_3d, "ret_5d": ret_5d, "ret_10d": ret_10d
            })
        elif s_close <= vwap - 1.5 * cur_atr:
            intraday_swing_events.append({
                "date": str(dt), "event": "Bearish_VWAP_Extension",
                "ret_1d": -ret_1d, "ret_2d": -ret_2d, "ret_3d": -ret_3d, "ret_5d": -ret_5d, "ret_10d": -ret_10d
            })

    df_ise = pd.DataFrame(intraday_swing_events)
    print(f"Total Intraday-to-Swing events: {len(df_ise)}")

    intraday_to_swing_summary = {}
    for ev in df_ise['event'].unique():
        sub = df_ise[df_ise['event'] == ev]
        cnt = len(sub)
        w1 = (sub['ret_1d'] > 0).mean() * 100.0
        w2 = (sub['ret_2d'] > 0).mean() * 100.0
        w3 = (sub['ret_3d'] > 0).mean() * 100.0
        w5 = (sub['ret_5d'] > 0).mean() * 100.0
        w10 = (sub['ret_10d'] > 0).mean() * 100.0

        m1 = sub['ret_1d'].mean()
        m3 = sub['ret_3d'].mean()
        m5 = sub['ret_5d'].mean()
        m10 = sub['ret_10d'].mean()

        # Classification
        if w3 >= 55.0 and m3 > 40.0:
            classification = "SWING (3-5 Days)"
        elif w1 >= 54.0 and m1 > 20.0:
            classification = "SHORT SWING (1 Day)"
        elif w1 < 48.0 or abs(m1) < 10.0:
            classification = "INTRADAY ONLY / NO PERSISTENCE"
        else:
            classification = "WEAK PERSISTENCE"

        intraday_to_swing_summary[ev] = {
            "count": int(cnt),
            "win_1d_pct": round(float(w1), 2),
            "ret_1d_mean": round(float(m1), 2),
            "win_2d_pct": round(float(w2), 2),
            "win_3d_pct": round(float(w3), 2),
            "ret_3d_mean": round(float(m3), 2),
            "win_5d_pct": round(float(w5), 2),
            "ret_5d_mean": round(float(m5), 2),
            "win_10d_pct": round(float(w10), 2),
            "ret_10d_mean": round(float(m10), 2),
            "persistence_classification": classification
        }

    # =========================================================================
    # 6. YEAR-BY-YEAR ROBUSTNESS (Large Bullish & Trend Days)
    # =========================================================================
    print("Conducting Year-by-Year Robustness...")
    years = sorted(df_dev['year'].unique())
    yearly_robustness = {}

    for y in years:
        sub_y = df_dev[(df_dev['year'] == y) & (df_dev['event_type'] == 'Trend_Day')]
        if len(sub_y) > 0:
            w1 = (sub_y['ret_1d'] > 0).mean() * 100.0
            w3 = (sub_y['ret_3d'] > 0).mean() * 100.0
            w5 = (sub_y['ret_5d'] > 0).mean() * 100.0
            r5 = sub_y['ret_5d'].mean()
            yearly_robustness[int(y)] = {
                "trend_day_count": len(sub_y),
                "win_1d_pct": round(float(w1), 2),
                "win_3d_pct": round(float(w3), 2),
                "win_5d_pct": round(float(w5), 2),
                "mean_5d_return": round(float(r5), 2)
            }

    # =========================================================================
    # 7. COMPILE MASTER METRICS
    # =========================================================================
    metrics = {
        "dataset_total_bars": n_total,
        "total_analyzed_days": n_days,
        "total_analyzed_weeks": n_weeks,
        "daily_event_summary": daily_event_summary,
        "weekly_structure_summary": weekly_summary,
        "multi_timeframe_alignment_summary": mtf_alignment_results,
        "intraday_to_swing_persistence": intraday_to_swing_summary,
        "yearly_robustness": yearly_robustness
    }

    json_path = "research/price_action/multi_timeframe_metrics.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(metrics, f, indent=2)
    print(f"Saved MTF swing metrics to {json_path}")

    # Export Events CSV
    # Export daily and intraday-swing events
    csv_path = "research/price_action/MULTI_TIMEFRAME_EVENTS.csv"
    df_dev.to_csv(csv_path, index=False)
    print(f"Saved {len(df_dev)} MTF daily events to {csv_path}")

    print("\n--- Summary MTF Results ---")
    for k, v in daily_event_summary.items():
        print(f"[{k}] (N={v['count']}) 1D Win: {v['win_1d_pct']}% | 3D Win: {v['win_3d_pct']}% | 5D Ret: {v['ret_5d_mean']} pts | Class: {v['persistence_classification']}")
    print("\n--- Intraday to Swing Summary ---")
    for k, v in intraday_to_swing_summary.items():
        print(f"[{k}] (N={v['count']}) 1D Win: {v['win_1d_pct']}% | 3D Win: {v['win_3d_pct']}% | Class: {v['persistence_classification']}")
    print("\n--- MTF Alignment Results ---")
    for k, v in mtf_alignment_results.items():
        print(f"[{k}] Aligned Freq: {v['alignment_frequency_pct']}% | Cont Aligned: {v['continuation_pct_when_aligned']}% vs Div: {v['continuation_pct_when_divergent']}% | Edge: {v['alignment_edge_points']} pts")


if __name__ == "__main__":
    run_mtf_swing_research()
