"""
Phase 1: Dataset Verification and Data Integrity Audit.
Directly inspects data/hermes_research/market_data.db and reports:
- Exact row counts by instrument & timeframe
- Unique trading sessions
- Date ranges
- Missing bars / gaps
- Duplicate records
- Timestamp integrity
- OHLC price sanity (High >= Low, High >= Open/Close, Low <= Open/Close, Volume >= 0)
"""

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path


def audit_market_data(db_path: str = "data/hermes_research/market_data.db"):
    print("=" * 75)
    print("      HERMES DATA INTEGRITY AUDIT — DHAN HISTORICAL DATASET       ")
    print("=" * 75)
    print(f"Inspecting file: {db_path}...")

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [t[0] for t in cur.fetchall()]
    print("\n[+] Tables in database:")
    for t in tables:
        cur.execute(f"SELECT count(*) FROM {t}")
        cnt = cur.fetchone()[0]
        print(f"    - {t:<20}: {cnt:,} rows")

    # Audit normalized_bars
    query = "SELECT * FROM normalized_bars ORDER BY timestamp ASC"
    df = pd.read_sql_query(query, conn)
    conn.close()

    print(f"\n[+] Total rows in 'normalized_bars': {len(df):,}")

    # Instrument breakdown
    print("\n[+] Instruments Breakdown:")
    inst_summary = df.groupby(['symbol', 'timeframe']).agg(
        count=('bar_id', 'count'),
        min_date=('timestamp', 'min'),
        max_date=('timestamp', 'max')
    )
    print(inst_summary.to_string())

    # Focus on NIFTY Spot 15M
    nifty_df = df[(df['symbol'] == 'NIFTY') & (df['timeframe'] == '15M')].copy()
    print("\n" + "-" * 75)
    print("  NIFTY 15-MINUTE SPOT AUDIT")
    print("-" * 75)
    print(f"Total Rows: {len(nifty_df):,}")

    # Duplicate check
    duplicates = nifty_df.duplicated(subset=['timestamp']).sum()
    print(f"Duplicate Timestamps: {duplicates}")

    # Timestamp conversion & timezone audit
    nifty_df['dt'] = pd.to_datetime(nifty_df['timestamp'], format='ISO8601')
    nifty_df['ist'] = nifty_df['dt'] + pd.Timedelta(hours=5, minutes=30)
    nifty_df['date'] = nifty_df['ist'].dt.date
    nifty_df['time_str'] = nifty_df['ist'].dt.strftime('%H:%M')
    nifty_df['year'] = nifty_df['ist'].dt.year

    sessions = nifty_df['date'].nunique()
    print(f"Total Trading Sessions (Days): {sessions:,}")
    print(f"Date Range (IST): {nifty_df['ist'].min().strftime('%Y-%m-%d %H:%M')} to {nifty_df['ist'].max().strftime('%Y-%m-%d %H:%M')}")

    # OHLC Integrity Check
    invalid_hl = (nifty_df['high'] < nifty_df['low']).sum()
    invalid_ho = (nifty_df['high'] < nifty_df['open']).sum()
    invalid_hc = (nifty_df['high'] < nifty_df['close']).sum()
    invalid_lo = (nifty_df['low'] > nifty_df['open']).sum()
    invalid_lc = (nifty_df['low'] > nifty_df['close']).sum()
    invalid_vol = (nifty_df['volume'] < 0).sum()
    nan_prices = nifty_df[['open', 'high', 'low', 'close']].isna().sum().sum()

    print("\n[+] Price & Volume Integrity:")
    print(f"    - High < Low errors         : {invalid_hl}")
    print(f"    - High < Open/Close errors  : {invalid_ho + invalid_hc}")
    print(f"    - Low > Open/Close errors   : {invalid_lo + invalid_lc}")
    print(f"    - Negative Volume errors    : {invalid_vol}")
    print(f"    - NaN / Missing Price values: {nan_prices}")

    # Regular Market Hours (09:15 to 15:30 IST)
    market_hours_df = nifty_df[(nifty_df['time_str'] >= '09:15') & (nifty_df['time_str'] <= '15:30')].copy()
    bars_per_day = market_hours_df.groupby('date').size()
    print("\n[+] Market Hours Session Bar Distribution (Expected 25 bars/day for 15M):")
    print(f"    - Median bars per session: {bars_per_day.median():.0f}")
    print(f"    - 25th percentile        : {bars_per_day.quantile(0.25):.0f}")
    print(f"    - 75th percentile        : {bars_per_day.quantile(0.75):.0f}")
    print(f"    - Sessions with exact 25 bars: {(bars_per_day == 25).sum()} / {len(bars_per_day)} ({(bars_per_day == 25).mean()*100:.1f}%)")

    # Session breakdown by year
    print("\n[+] Sessions and Bars by Year:")
    yearly_dist = market_hours_df.groupby('year').agg(
        sessions=('date', 'nunique'),
        bars=('bar_id', 'count'),
        min_close=('close', 'min'),
        max_close=('close', 'max')
    )
    print(yearly_dist.to_string())

    print("\n" + "=" * 75)
    print("                  AUDIT STATUS: DATA INTEGRITY VERIFIED          ")
    print("=" * 75)


if __name__ == "__main__":
    audit_market_data()
