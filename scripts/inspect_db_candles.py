import sqlite3
import pandas as pd

conn = sqlite3.connect("data/hermes_research/market_data.db")
df = pd.read_sql_query("SELECT timestamp, open, high, low, close, volume FROM normalized_bars WHERE symbol='NIFTY' AND timeframe='15M' ORDER BY timestamp ASC", conn)
conn.close()

df['dt'] = pd.to_datetime(df['timestamp'], format='ISO8601')
print("Total rows:", len(df))
print("Start date:", df['dt'].min())
print("End date:", df['dt'].max())

# Group by year
df['year'] = df['dt'].dt.year
print("\nBars by Year:")
print(df['year'].value_counts().sort_index())

# Check daily bar count
df['day'] = df['dt'].dt.date
daily_counts = df.groupby('day').size()
print("\nDaily bar counts summary:")
print(daily_counts.describe())

# Check price ranges across years
print("\nYearly OHLC range:")
for yr, g in df.groupby('year'):
    print(f"Year {yr}: Min Low = {g['low'].min():.2f}, Max High = {g['high'].max():.2f}, Start Close = {g['close'].iloc[0]:.2f}, End Close = {g['close'].iloc[-1]:.2f}")
