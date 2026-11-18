import sqlite3
import pandas as pd

conn = sqlite3.connect('data/hermes_research/market_data.db')

df_5m = pd.read_sql_query("""
    SELECT timestamp, open, high, low, close, volume
    FROM normalized_bars
    WHERE symbol = 'NIFTY' AND timeframe = '5M'
    ORDER BY timestamp ASC
""", conn)
conn.close()

df_5m['dt'] = pd.to_datetime(df_5m['timestamp'])
df_5m['dt_ist'] = df_5m['dt'].dt.tz_convert('Asia/Kolkata')
df_5m['date'] = df_5m['dt_ist'].dt.date
df_5m['time'] = df_5m['dt_ist'].dt.time

# Pick a full regular trading day in 2023 or 2024
sample_date = df_5m['date'].iloc[5000]
print(f"Sample date: {sample_date}")
df_day = df_5m[df_5m['date'] == sample_date]
print(f"Number of bars on {sample_date}: {len(df_day)}")
print(df_day[['timestamp', 'time', 'open', 'high', 'low', 'close', 'volume']].head(15))
print(df_day[['timestamp', 'time', 'open', 'high', 'low', 'close', 'volume']].tail(10))

# Check distribution of bar counts per day
bars_per_day = df_5m.groupby('date').size()
print("\nBar count per day distribution:")
print(bars_per_day.value_counts().head(10))
