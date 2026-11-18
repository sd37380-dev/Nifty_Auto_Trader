import sqlite3
import pandas as pd
import numpy as np

conn = sqlite3.connect('data/hermes_research/market_data.db')

df_5m = pd.read_sql_query("""
    SELECT timestamp, open, high, low, close, volume
    FROM normalized_bars
    WHERE symbol = 'NIFTY' AND timeframe = '5M'
    ORDER BY timestamp ASC
""", conn)

df_15m = pd.read_sql_query("""
    SELECT timestamp, open, high, low, close, volume
    FROM normalized_bars
    WHERE symbol = 'NIFTY' AND timeframe = '15M' AND timestamp NOT LIKE '%.%'
    ORDER BY timestamp ASC
""", conn)
conn.close()

# Let's check alignment
df_5m['dt'] = pd.to_datetime(df_5m['timestamp'])
df_15m['dt'] = pd.to_datetime(df_15m['timestamp'])

# Resample 5m to 15m
# Standard bars start at 09:15, 09:30, 09:45, etc.
# In UTC, 09:15 IST is 03:45 UTC.
# Let's set dt as index
df_5m_resampled = df_5m.set_index('dt').resample('15min', origin='start_day', closed='left', label='left').agg({
    'open': 'first',
    'high': 'max',
    'low': 'min',
    'close': 'last',
    'volume': 'sum'
}).dropna().reset_index()

print("5M resampled count:", len(df_5m_resampled))
print("Stored 15M count:", len(df_15m))

# Merge and compare on matching timestamps
merged = pd.merge(df_15m, df_5m_resampled, on='dt', suffixes=('_stored', '_resampled'))
print(f"Matching timestamps count: {len(merged)}")

diff_close = (merged['close_stored'] - merged['close_resampled']).abs().max()
diff_open = (merged['open_stored'] - merged['open_resampled']).abs().max()
diff_high = (merged['high_stored'] - merged['high_resampled']).abs().max()
diff_low = (merged['low_stored'] - merged['low_resampled']).abs().max()

print(f"Max differences: open={diff_open}, high={diff_high}, low={diff_low}, close={diff_close}")
