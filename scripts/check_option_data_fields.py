import sqlite3
import pandas as pd

conn = sqlite3.connect("data/hermes_research/market_data.db")
ce_df = pd.read_sql_query("SELECT timestamp, open, high, low, close, volume, open_interest FROM normalized_bars WHERE symbol='NIFTY_ATM_CE' ORDER BY timestamp ASC", conn)
pe_df = pd.read_sql_query("SELECT timestamp, open, high, low, close, volume, open_interest FROM normalized_bars WHERE symbol='NIFTY_ATM_PE' ORDER BY timestamp ASC", conn)
spot_df = pd.read_sql_query("SELECT timestamp, open, high, low, close, volume FROM normalized_bars WHERE symbol='NIFTY' AND timeframe='15M' ORDER BY timestamp ASC", conn)
conn.close()

print(f"Underlying NIFTY Spot Bars : {len(spot_df):,} bars ({spot_df['timestamp'].min()[:10]} to {spot_df['timestamp'].max()[:10]})")
print(f"Real ATM CE Option Bars   : {len(ce_df):,} bars ({ce_df['timestamp'].min()[:10]} to {ce_df['timestamp'].max()[:10]})")
print(f"Real ATM PE Option Bars   : {len(pe_df):,} bars ({pe_df['timestamp'].min()[:10]} to {pe_df['timestamp'].max()[:10]})")

print("\nSample Real Option Bar (NIFTY_ATM_CE):")
sample = ce_df.iloc[-5]
print(f"  Timestamp    : {sample['timestamp']}")
print(f"  Option Open  : Rs. {sample['open']}")
print(f"  Option High  : Rs. {sample['high']}")
print(f"  Option Low   : Rs. {sample['low']}")
print(f"  Option Close : Rs. {sample['close']}")
print(f"  Option Volume: {sample['volume']:,} contracts")
print(f"  Option OI    : {sample['open_interest']:,} contracts")
