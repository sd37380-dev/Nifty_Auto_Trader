import sqlite3
import pandas as pd

conn = sqlite3.connect('data/hermes_research/market_data.db')

# How many rows in 15M before microsecond rows were added?
# Let's see the timestamp distribution of 15M
df_15 = pd.read_sql_query("""
    SELECT timestamp, open, high, low, close, volume, open_interest
    FROM normalized_bars
    WHERE symbol = 'NIFTY' AND timeframe = '15M'
    ORDER BY timestamp ASC
""", conn)
conn.close()

df_15['has_dot'] = df_15['timestamp'].str.contains(r'\.')
print("15M rows total:", len(df_15))
print("15M rows with dot (microseconds):", df_15['has_dot'].sum())
print("15M rows without dot:", (~df_15['has_dot']).sum())

# Let's check date range of without dot
df_nodot = df_15[~df_15['has_dot']].copy()
df_nodot['dt'] = pd.to_datetime(df_nodot['timestamp'])
df_nodot['dt_ist'] = df_nodot['dt'].dt.tz_convert('Asia/Kolkata')
print("Without dot date range:", df_nodot['dt_ist'].min(), "to", df_nodot['dt_ist'].max())

# Let's check date range of with dot
df_dot = df_15[df_15['has_dot']].copy()
df_dot['dt'] = pd.to_datetime(df_dot['timestamp'], format='ISO8601')
df_dot['dt_ist'] = df_dot['dt'].dt.tz_convert('Asia/Kolkata')
print("With dot date range:", df_dot['dt_ist'].min(), "to", df_dot['dt_ist'].max())

# Let's see where the microsecond rows came from
print("\nSample dot rows:")
print(df_dot[['timestamp', 'open', 'high', 'low', 'close', 'open_interest']].head())

# Check overlap: are there overlapping dates between dot and nodot?
overlap = set(df_nodot['dt_ist'].dt.date).intersection(set(df_dot['dt_ist'].dt.date))
print(f"Overlapping trading dates between clean and microsecond bars: {len(overlap)}")
if len(overlap) > 0:
    print(f"Sample overlapping dates: {list(overlap)[:5]}")
