import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

db_path = 'data/hermes_research/market_data.db'
conn = sqlite3.connect(db_path)

print("=" * 70)
print("AUDITING EXISTING NIFTY DATASET")
print("=" * 70)

# 1. Load 5M bars
df_5m = pd.read_sql_query("""
    SELECT bar_id, symbol, timeframe, timestamp, open, high, low, close, volume, open_interest
    FROM normalized_bars
    WHERE symbol = 'NIFTY' AND timeframe = '5M'
    ORDER BY timestamp ASC
""", conn)

# 2. Load 15M bars
df_15m = pd.read_sql_query("""
    SELECT bar_id, symbol, timeframe, timestamp, open, high, low, close, volume, open_interest
    FROM normalized_bars
    WHERE symbol = 'NIFTY' AND timeframe = '15M'
    ORDER BY timestamp ASC
""", conn)

conn.close()

print(f"5M Bar Count: {len(df_5m)}")
print(f"15M Bar Count: {len(df_15m)}")

def audit_df(df, name):
    print(f"\n==================================================")
    print(f"AUDIT FOR: {name}")
    print(f"==================================================")
    df['dt'] = pd.to_datetime(df['timestamp'], format='ISO8601')
    
    # Timezone check
    tz_info = df['dt'].dt.tz
    print(f"Timezone: {tz_info}")
    
    # Earliest & latest
    min_dt = df['dt'].min()
    max_dt = df['dt'].max()
    print(f"Earliest Timestamp (UTC): {min_dt}")
    print(f"Latest Timestamp (UTC): {max_dt}")
    
    # Convert to IST (UTC + 5:30)
    df['dt_ist'] = df['dt'].dt.tz_convert('Asia/Kolkata')
    print(f"Earliest IST: {df['dt_ist'].min()}")
    print(f"Latest IST: {df['dt_ist'].max()}")
    
    # Duplicates
    dup_count = df.duplicated(subset=['timestamp']).sum()
    print(f"Duplicate Timestamps: {dup_count}")
    
    # Invalid OHLC
    invalid_mask = (
        (df['high'] < df['low']) |
        (df['high'] < df['open']) |
        (df['high'] < df['close']) |
        (df['low'] > df['open']) |
        (df['low'] > df['close']) |
        (df['open'] <= 0) | (df['close'] <= 0)
    )
    invalid_ohlc = invalid_mask.sum()
    print(f"Invalid OHLC Bars: {invalid_ohlc}")
    if invalid_ohlc > 0:
        print("Invalid OHLC Rows:")
        print(df[invalid_mask][['timestamp', 'open', 'high', 'low', 'close']])
    
    # Volume & OI statistics
    zero_vol = (df['volume'] == 0).sum()
    zero_oi = (df['open_interest'] == 0).sum()
    print(f"Zero Volume Bars: {zero_vol} / {len(df)} ({zero_vol / len(df) * 100:.2f}%)")
    print(f"Zero OI Bars: {zero_oi} / {len(df)} ({zero_oi / len(df) * 100:.2f}%)")
    
    # Check if OI is ever non-zero
    non_zero_oi = df[df['open_interest'] > 0]
    print(f"Non-Zero OI Bars: {len(non_zero_oi)}")
    
    # Weekend checks (Monday=0, Sunday=6)
    weekend_bars = (df['dt_ist'].dt.dayofweek >= 5).sum()
    print(f"Weekend Bars (Sat/Sun): {weekend_bars}")
    if weekend_bars > 0:
        weekends = df[df['dt_ist'].dt.dayofweek >= 5]['dt_ist'].dt.date.unique()
        print(f"  Weekend trading dates: {weekends}")
    
    # Market hour check
    df['time_ist'] = df['dt_ist'].dt.time
    unique_times = sorted(df['time_ist'].unique())
    print(f"Unique IST bar times count: {len(unique_times)}")
    print(f"Earliest bar time in day: {unique_times[0]}, Latest bar time in day: {unique_times[-1]}")
    
    # Standard trading session: 09:15 to 15:30 IST
    # 5-minute bars during 09:15 - 15:30 typically have timestamps:
    # If timestamp is bar start: 09:15, 09:20, ..., 15:25 (75 bars/day)
    # If timestamp is bar end: 09:20, 09:25, ..., 15:30
    outside_hours = df[(df['time_ist'] < datetime.strptime("09:15", "%H:%M").time()) | 
                       (df['time_ist'] > datetime.strptime("15:30", "%H:%M").time())]
    print(f"Bars outside 09:15-15:30 IST: {len(outside_hours)}")
    if len(outside_hours) > 0:
        print("  Sample outside hours (first 10):")
        print(outside_hours[['timestamp', 'time_ist', 'open', 'close', 'volume']].head(10))
        print("  Sample outside hours (last 10):")
        print(outside_hours[['timestamp', 'time_ist', 'open', 'close', 'volume']].tail(10))

audit_df(df_5m, "5-Minute NIFTY Dataset")
audit_df(df_15m, "15-Minute NIFTY Dataset")
