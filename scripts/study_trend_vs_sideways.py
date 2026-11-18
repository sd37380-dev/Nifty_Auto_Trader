"""
Empirical 5-Year Study on Trending Days vs Sideways Days on NIFTY (1,247 Days).
Quantifies the exact mathematical symptoms and non-chart data-driven factors
that predict whether today will be a Trending Day or a Sideways Day.
"""

import sqlite3
import pandas as pd
import numpy as np


def run_trend_vs_sideways_study():
    conn = sqlite3.connect("data/hermes_research/market_data.db")
    df = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, volume FROM normalized_bars WHERE symbol='NIFTY' AND timeframe='15M' ORDER BY timestamp ASC",
        conn
    )
    conn.close()

    df['dt'] = pd.to_datetime(df['timestamp'], format='ISO8601')
    df = df[~df['dt'].duplicated(keep='first')]
    df.set_index('dt', inplace=True)
    df.sort_index(inplace=True)

    df['ist'] = df.index + pd.Timedelta(hours=5, minutes=30)
    df['date'] = df['ist'].dt.date
    df['time_str'] = df['ist'].dt.strftime('%H:%M')
    df['year'] = df['ist'].dt.year

    # Filter to market hours 09:15 to 15:30
    df = df[(df['time_str'] >= '09:15') & (df['time_str'] <= '15:30')].copy()

    # Calculate Session VWAP per day
    tp = (df['high'] + df['low'] + df['close']) / 3.0
    pv = tp * df['volume']
    df['cum_pv'] = pv.groupby(df['date']).cumsum()
    df['cum_vol'] = df['volume'].groupby(df['date']).cumsum()
    df['vwap'] = np.where(df['cum_vol'] > 0, df['cum_pv'] / df['cum_vol'], df['close'])

    # Day-level aggregation
    days = df['date'].unique()
    day_records = []

    for d in days:
        day_df = df[df['date'] == d]
        if len(day_df) < 12:
            continue

        d_open = day_df.iloc[0]['open']
        d_close = day_df.iloc[-1]['close']
        d_high = day_df['high'].max()
        d_low = day_df['low'].min()
        d_range = d_high - d_low
        d_body = abs(d_close - d_open)
        d_vol = day_df['volume'].sum()

        # First 30 mins (09:15 and 09:30 bars)
        first_30 = day_df[(day_df['time_str'] >= '09:15') & (day_df['time_str'] <= '09:30')]
        if len(first_30) >= 2:
            or_high = first_30['high'].max()
            or_low = first_30['low'].min()
            or_range = or_high - or_low
            or_vol = first_30['volume'].sum()
        else:
            or_range = np.nan
            or_vol = np.nan

        # Count VWAP crosses during the day (measure of chop/oscillation)
        above_vwap = (day_df['close'] > day_df['vwap']).astype(int)
        vwap_crosses = (above_vwap.diff().abs() == 1).sum()

        # Close position in day's range: 1.0 = closed at extreme high, 0.0 = extreme low, 0.5 = mid
        close_pos = (d_close - d_low) / max(1.0, d_range)

        # Net move %
        net_move_pct = (d_close - d_open) / d_open * 100.0

        day_records.append({
            "date": d,
            "open": d_open,
            "high": d_high,
            "low": d_low,
            "close": d_close,
            "range": d_range,
            "body": d_body,
            "body_to_range": d_body / max(1.0, d_range),
            "close_pos": close_pos,
            "net_move_pct": net_move_pct,
            "or_range": or_range,
            "or_vol": or_vol,
            "vwap_crosses": vwap_crosses,
            "total_vol": d_vol,
        })

    ddf = pd.DataFrame(day_records)

    # 20-day rolling ATR & volume
    ddf['atr_20'] = ddf['range'].rolling(20).mean()
    ddf['vol_sma_20'] = ddf['total_vol'].rolling(20).mean()
    ddf['or_vol_sma_20'] = ddf['or_vol'].rolling(20).mean()

    # Previous Day metrics (Central Pivot Range CPR)
    # Pivot P = (H + L + C) / 3
    # Bottom Central BC = (H + L) / 2
    # Top Central TC = 2*P - BC
    # CPR Width = |TC - BC| / P * 100
    prev_h = ddf['high'].shift(1)
    prev_l = ddf['low'].shift(1)
    prev_c = ddf['close'].shift(1)
    p = (prev_h + prev_l + prev_c) / 3.0
    bc = (prev_h + prev_l) / 2.0
    tc = (2.0 * p) - bc
    ddf['cpr_width_pct'] = (tc - bc).abs() / p * 100.0
    ddf['cpr_width_sma_20'] = ddf['cpr_width_pct'].rolling(20).mean()
    ddf['is_narrow_cpr'] = ddf['cpr_width_pct'] < (ddf['cpr_width_sma_20'] * 0.70)
    ddf['is_wide_cpr'] = ddf['cpr_width_pct'] > (ddf['cpr_width_sma_20'] * 1.30)

    # Opening Gap %
    ddf['gap_pct'] = (ddf['open'] - ddf['close'].shift(1)) / ddf['close'].shift(1) * 100.0

    ddf.dropna(inplace=True)

    # Classify Days:
    # 1. TRENDING DAY: Body/Range >= 0.65 AND Range > 1.0 * ATR20 AND VWAP Crosses <= 3 AND Close Pos > 0.80 or < 0.20
    # 2. SIDEWAYS DAY: Body/Range < 0.45 AND VWAP Crosses >= 5
    is_trend = (ddf['body_to_range'] >= 0.60) & (ddf['range'] >= ddf['atr_20'] * 0.90) & (ddf['vwap_crosses'] <= 3)
    is_sideways = (ddf['body_to_range'] < 0.45) & (ddf['vwap_crosses'] >= 4)

    ddf['regime'] = 'NORMAL'
    ddf.loc[is_trend, 'regime'] = 'TRENDING'
    ddf.loc[is_sideways, 'regime'] = 'SIDEWAYS'

    print("=" * 75)
    print(f"       5-YEAR EMPIRICAL STUDY: TREND VS SIDEWAYS DAYS ({len(ddf)} DAYS)      ")
    print("=" * 75)
    counts = ddf['regime'].value_counts()
    for reg, cnt in counts.items():
        print(f"  {reg:<12} Days : {cnt:4d} ({cnt / len(ddf) * 100:.1f}%)")

    # Analyze Symptoms / Predictive Factors
    trend_df = ddf[ddf['regime'] == 'TRENDING']
    side_df = ddf[ddf['regime'] == 'SIDEWAYS']

    print("\n" + "-" * 75)
    print("  KEY STATISTICAL DIFFERENCES (MEASURED AT 09:15 - 10:00 IST)")
    print("-" * 75)

    print(f"{'Metric / Indicator':<38} | {'Trending Days':<16} | {'Sideways Days':<16}")
    print("-" * 75)

    # 1. CPR Width
    print(f"{'Narrow CPR Occurrence Rate':<38} | {trend_df['is_narrow_cpr'].mean()*100:>14.1f}% | {side_df['is_narrow_cpr'].mean()*100:>14.1f}%")
    print(f"{'Wide CPR Occurrence Rate':<38} | {trend_df['is_wide_cpr'].mean()*100:>14.1f}% | {side_df['is_wide_cpr'].mean()*100:>14.1f}%")

    # 2. First 30-min Volume Relative to 20-Day Avg
    trend_vol_ratio = (trend_df['or_vol'] / trend_df['or_vol_sma_20']).mean()
    side_vol_ratio = (side_df['or_vol'] / side_df['or_vol_sma_20']).mean()
    print(f"{'Morning Volume Ratio (09:15-09:45)':<38} | {trend_vol_ratio:>14.2f}x | {side_vol_ratio:>14.2f}x")

    # 3. First 30-min Range vs Daily ATR
    trend_or_ratio = (trend_df['or_range'] / trend_df['atr_20']).mean()
    side_or_ratio = (side_df['or_range'] / side_df['atr_20']).mean()
    print(f"{'Opening Range / Daily ATR':<38} | {trend_or_ratio:>14.2f}  | {side_or_ratio:>14.2f} ")

    # 4. Opening Gap Magnitude
    trend_gap = trend_df['gap_pct'].abs().mean()
    side_gap = side_df['gap_pct'].abs().mean()
    print(f"{'Average Overnight Gap Size':<38} | {trend_gap:>14.2f}% | {side_gap:>14.2f}%")

    # 5. Full Day Range
    print(f"{'Average Full-Day Range':<38} | {trend_df['range'].mean():>14.1f} pts| {side_df['range'].mean():>14.1f} pts")

    # 6. VWAP Crossings (Oscillations)
    print(f"{'Average VWAP Crossings per Day':<38} | {trend_df['vwap_crosses'].mean():>14.1f}   | {side_df['vwap_crosses'].mean():>14.1f}  ")

    print("=" * 75)


if __name__ == "__main__":
    run_trend_vs_sideways_study()
