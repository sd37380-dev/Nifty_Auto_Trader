import sqlite3
import pandas as pd

pd.set_option('display.max_columns', None)
pd.set_option('display.width', 1000)

db_path = 'data/hermes_research/market_data.db'
conn = sqlite3.connect(db_path)

df_summary = pd.read_sql_query("""
    SELECT symbol, timeframe, count(*) as bar_count, 
           min(timestamp) as min_ts, max(timestamp) as max_ts
    FROM normalized_bars
    GROUP BY symbol, timeframe
""", conn)
print("=== GROUP BY SYMBOL, TIMEFRAME ===")
print(df_summary)

print("\n=== SAMPLE 5M ROWS WITH ALL COLUMNS ===")
df_5m = pd.read_sql_query("""
    SELECT * FROM normalized_bars 
    WHERE symbol = 'NIFTY' AND timeframe = '5M'
    ORDER BY timestamp ASC
    LIMIT 10
""", conn)
print(df_5m)

print("\n=== SAMPLE 5M LATEST ROWS ===")
df_5m_latest = pd.read_sql_query("""
    SELECT * FROM normalized_bars 
    WHERE symbol = 'NIFTY' AND timeframe = '5M'
    ORDER BY timestamp DESC
    LIMIT 10
""", conn)
print(df_5m_latest)

print("\n=== SAMPLE 15M ROWS WITH ALL COLUMNS ===")
df_15m = pd.read_sql_query("""
    SELECT * FROM normalized_bars 
    WHERE symbol = 'NIFTY' AND timeframe = '15M'
    ORDER BY timestamp ASC
    LIMIT 10
""", conn)
print(df_15m)

conn.close()
