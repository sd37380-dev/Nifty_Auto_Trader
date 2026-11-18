import sqlite3
import pandas as pd

conn = sqlite3.connect("data/hermes_research/market_data.db")
print("=== DATABASE SUMMARY FOR NIFTY & BANKNIFTY ===")
df_summary = pd.read_sql_query("""
SELECT symbol, timeframe, MIN(timestamp) as min_ts, MAX(timestamp) as max_ts, COUNT(*) as count 
FROM normalized_bars 
WHERE symbol IN ('NIFTY', 'BANKNIFTY')
GROUP BY symbol, timeframe
""", conn)
print(df_summary.to_string(index=False))

print("\n=== RECENT BARS SAMPLE FOR BANKNIFTY (LATEST 10 BARS) ===")
df_bn = pd.read_sql_query("""
SELECT timestamp, open, high, low, close, volume 
FROM normalized_bars 
WHERE symbol = 'BANKNIFTY' 
ORDER BY timestamp DESC LIMIT 10
""", conn)
print(df_bn.to_string(index=False))

print("\n=== RECENT BARS SAMPLE FOR NIFTY (LATEST 10 BARS) ===")
df_nf = pd.read_sql_query("""
SELECT timestamp, open, high, low, close, volume 
FROM normalized_bars 
WHERE symbol = 'NIFTY' 
ORDER BY timestamp DESC LIMIT 10
""", conn)
print(df_nf.to_string(index=False))
conn.close()
