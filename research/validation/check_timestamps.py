import sqlite3
import pandas as pd
import numpy as np

conn = sqlite3.connect('data/hermes_research/market_data.db')

# Check microsecond timestamps in 15M
df_micro = pd.read_sql_query("""
    SELECT * FROM normalized_bars 
    WHERE symbol = 'NIFTY' AND timeframe = '15M' AND timestamp LIKE '%.%'
    ORDER BY timestamp ASC
""", conn)
print(f"Total 15M rows with fractional microsecond timestamps: {len(df_micro)}")
if len(df_micro) > 0:
    print("First 3 microsecond rows:")
    print(df_micro.head(3))
    print("Last 3 microsecond rows:")
    print(df_micro.tail(3))

# Check clean 15M rows without microseconds
df_clean_15m = pd.read_sql_query("""
    SELECT * FROM normalized_bars 
    WHERE symbol = 'NIFTY' AND timeframe = '15M' AND timestamp NOT LIKE '%.%'
    ORDER BY timestamp ASC
""", conn)
print(f"Total 15M rows WITHOUT fractional timestamps: {len(df_clean_15m)}")
print(f"Min timestamp clean: {df_clean_15m['timestamp'].min()}, Max: {df_clean_15m['timestamp'].max()}")

# Notice user stated:
# "We currently have approximately:
# 92,739 NIFTY 5-minute rows
# 37,239 NIFTY 15-minute rows"
# Let's check 38,248 - len(df_micro)
print(f"38248 - {len(df_micro)} = {38248 - len(df_micro)}")

conn.close()
