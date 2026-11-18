import sqlite3
import pandas as pd

conn = sqlite3.connect('data/hermes_research/market_data.db')

df_micro = pd.read_sql_query("""
    SELECT bar_id, symbol, timeframe, timestamp, open, high, low, close, volume, open_interest, vwap, trades_count
    FROM normalized_bars 
    WHERE symbol = 'NIFTY' AND timeframe = '15M' AND timestamp LIKE '%.%'
    ORDER BY timestamp ASC
""", conn)

print("Microsecond 15M rows count:", len(df_micro))
print("Min timestamp:", df_micro['timestamp'].min())
print("Max timestamp:", df_micro['timestamp'].max())
print("\nFirst 5 rows:")
print(df_micro.head())
print("\nLast 5 rows:")
print(df_micro.tail())

# Now check the clean 15M rows
df_clean = pd.read_sql_query("""
    SELECT bar_id, symbol, timeframe, timestamp, open, high, low, close, volume, open_interest, vwap, trades_count
    FROM normalized_bars 
    WHERE symbol = 'NIFTY' AND timeframe = '15M' AND timestamp NOT LIKE '%.%'
    ORDER BY timestamp ASC
""", conn)
print("\nClean 15M rows count:", len(df_clean))
print("Min timestamp:", df_clean['timestamp'].min())
print("Max timestamp:", df_clean['timestamp'].max())
print("\nFirst 5 rows:")
print(df_clean.head())
print("\nLast 5 rows:")
print(df_clean.tail())

conn.close()
