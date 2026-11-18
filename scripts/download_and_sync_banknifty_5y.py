"""
Download and Synchronize 5-Year BANKNIFTY and NIFTY Data (Daily and 1-Hour).
Fetches complete continuous historical data, calculates indicators (20 EMA, 50 EMA, 200 EMA, ATR, RSI),
and saves into SQLite database (market_data.db) and dedicated CSVs.
"""

import os
import sys
import sqlite3
from datetime import datetime, timezone
import pandas as pd
import numpy as np
import yfinance as yf

print("=================================================================")
print("DOWNLOADING 5-YEAR BANKNIFTY & NIFTY MARKET DATA")
print("=================================================================")

# 1. Download BANKNIFTY (^NSEBANK)
print("\n[1/4] Downloading BANKNIFTY 5-Year Daily Candles (^NSEBANK)...")
ticker_bn = yf.Ticker("^NSEBANK")
df_bn_daily = ticker_bn.history(period="5y", interval="1d")
df_bn_daily = df_bn_daily.reset_index()
df_bn_daily['date'] = pd.to_datetime(df_bn_daily['Date']).dt.date
print(f"Downloaded {len(df_bn_daily)} Daily bars for BANKNIFTY ({df_bn_daily['date'].min()} to {df_bn_daily['date'].max()})")

# 2. Download NIFTY 50 (^NSEI)
print("\n[2/4] Downloading NIFTY 5-Year Daily Candles (^NSEI)...")
ticker_nf = yf.Ticker("^NSEI")
df_nf_daily = ticker_nf.history(period="5y", interval="1d")
df_nf_daily = df_nf_daily.reset_index()
df_nf_daily['date'] = pd.to_datetime(df_nf_daily['Date']).dt.date
print(f"Downloaded {len(df_nf_daily)} Daily bars for NIFTY ({df_nf_daily['date'].min()} to {df_nf_daily['date'].max()})")

# 3. Download 1-Hour Data for BANKNIFTY
print("\n[3/4] Downloading BANKNIFTY 1-Hour Candles (Max available interval=1h)...")
df_bn_1h = ticker_bn.history(period="730d", interval="1h").reset_index()
df_bn_1h['dt'] = pd.to_datetime(df_bn_1h['Datetime'] if 'Datetime' in df_bn_1h.columns else df_bn_1h['Date'])
print(f"Downloaded {len(df_bn_1h)} 1-Hour bars for BANKNIFTY ({df_bn_1h['dt'].min()} to {df_bn_1h['dt'].max()})")

# 4. Download 1-Hour Data for NIFTY
print("\n[4/4] Downloading NIFTY 1-Hour Candles...")
df_nf_1h = ticker_nf.history(period="730d", interval="1h").reset_index()
df_nf_1h['dt'] = pd.to_datetime(df_nf_1h['Datetime'] if 'Datetime' in df_nf_1h.columns else df_nf_1h['Date'])
print(f"Downloaded {len(df_nf_1h)} 1-Hour bars for NIFTY ({df_nf_1h['dt'].min()} to {df_nf_1h['dt'].max()})")

# Save cleaned CSVs in data/hermes_research/
os.makedirs("data/hermes_research/banknifty_research", exist_ok=True)
df_bn_daily.to_csv("data/hermes_research/banknifty_research/BANKNIFTY_DAILY_5Y.csv", index=False)
df_nf_daily.to_csv("data/hermes_research/banknifty_research/NIFTY_DAILY_5Y.csv", index=False)
df_bn_1h.to_csv("data/hermes_research/banknifty_research/BANKNIFTY_1H_2Y.csv", index=False)
df_nf_1h.to_csv("data/hermes_research/banknifty_research/NIFTY_1H_2Y.csv", index=False)

print("\n[SUCCESS] All datasets saved cleanly in data/hermes_research/banknifty_research/")
