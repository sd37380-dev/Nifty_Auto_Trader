import sqlite3
import pandas as pd

conn = sqlite3.connect('data/hermes_research/market_data.db')

df_15m = pd.read_sql_query("""
    SELECT timestamp, open, high, low, close, volume
    FROM normalized_bars
    WHERE symbol = 'NIFTY' AND timeframe = '15M' AND timestamp NOT LIKE '%.%'
    ORDER BY timestamp ASC
""", conn)
conn.close()

df_15m['dt'] = pd.to_datetime(df_15m['timestamp'])
df_15m['dt_ist'] = df_15m['dt'].dt.tz_convert('Asia/Kolkata')
df_15m['date'] = df_15m['dt_ist'].dt.date
df_15m['time'] = df_15m['dt_ist'].dt.time

df_day = df_15m[df_15m['date'] == pd.to_datetime("2022-01-06").date()]
print("15M bars on 2022-01-06:")
print(f"Count: {len(df_day)}")
print(df_day[['timestamp', 'time', 'open', 'high', 'low', 'close']])

bars_per_day_15m = df_15m.groupby('date').size()
print("\n15M Bar count per day distribution:")
print(bars_per_day_15m.value_counts().head(10))
