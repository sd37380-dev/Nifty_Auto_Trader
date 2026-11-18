"""
Compare Chart Analysis with Recent 1-Month Broker Market Data (NIFTY & BANKNIFTY).
Loads recent 30 trading sessions from database, computes exact:
- Moving averages (20 EMA, 50 EMA, 200 EMA)
- Highs, Lows, Support & Resistance levels
- Distance from 200 EMA and 20 EMA
- Relative Strength & Divergence between NIFTY and BANKNIFTY
- Formulates exact swing trading trade plan.
"""

import os
import sys
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, time

conn = sqlite3.connect("data/hermes_research/market_data.db")

# 1. Load Bank Nifty 15M Data
df_bn_raw = pd.read_sql_query("""
SELECT timestamp, open, high, low, close, volume 
FROM normalized_bars 
WHERE symbol = 'BANKNIFTY' AND timeframe = '15M' 
ORDER BY timestamp ASC
""", conn)

# 2. Load Nifty 15M Data
df_nf_raw = pd.read_sql_query("""
SELECT timestamp, open, high, low, close, volume 
FROM normalized_bars 
WHERE symbol = 'NIFTY' AND timeframe = '15M' 
ORDER BY timestamp ASC
""", conn)
conn.close()

# Process Bank Nifty
df_bn_raw['dt_utc'] = pd.to_datetime(df_bn_raw['timestamp'], format='ISO8601')
df_bn_raw['dt_ist'] = df_bn_raw['dt_utc'].dt.tz_convert('Asia/Kolkata')
df_bn_raw['date_ist'] = df_bn_raw['dt_ist'].dt.date
df_bn_raw['time_ist'] = df_bn_raw['dt_ist'].dt.time
df_bn = df_bn_raw[(df_bn_raw['time_ist'] >= time(9, 15)) & (df_bn_raw['time_ist'] <= time(15, 30))].copy()
df_bn = df_bn.sort_values('dt_utc').reset_index(drop=True)

# Process Nifty
df_nf_raw['dt_utc'] = pd.to_datetime(df_nf_raw['timestamp'], format='ISO8601')
df_nf_raw['dt_ist'] = df_nf_raw['dt_utc'].dt.tz_convert('Asia/Kolkata')
df_nf_raw['date_ist'] = df_nf_raw['dt_ist'].dt.date
df_nf_raw['time_ist'] = df_nf_raw['dt_ist'].dt.time
df_nf = df_nf_raw[(df_nf_raw['time_ist'] >= time(9, 15)) & (df_nf_raw['time_ist'] <= time(15, 30))].copy()
df_nf = df_nf.sort_values('dt_utc').reset_index(drop=True)

# Build Daily for both
df_bn_daily = df_bn.groupby('date_ist').agg({
    'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
}).reset_index()
df_bn_daily['date'] = pd.to_datetime(df_bn_daily['date_ist'])
df_bn_daily = df_bn_daily.sort_values('date').reset_index(drop=True)

df_nf_daily = df_nf.groupby('date_ist').agg({
    'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
}).reset_index()
df_nf_daily['date'] = pd.to_datetime(df_nf_daily['date_ist'])
df_nf_daily = df_nf_daily.sort_values('date').reset_index(drop=True)

# Compute Daily EMAs
for df_d in [df_bn_daily, df_nf_daily]:
    df_d['ema20'] = df_d['close'].ewm(span=20, adjust=False).mean()
    df_d['ema50'] = df_d['close'].ewm(span=50, adjust=False).mean()
    df_d['ema200'] = df_d['close'].ewm(span=200, adjust=False).mean()
    df_d['dist_200_pct'] = (df_d['close'] - df_d['ema200']) / df_d['ema200'] * 100
    df_d['dist_20_pct'] = (df_d['close'] - df_d['ema20']) / df_d['ema20'] * 100

# 1H Resampling for both
df_bn_idx = df_bn.set_index('dt_utc')
df_bn_1h = df_bn_idx.resample('1h').agg({
    'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
}).dropna().reset_index()
df_bn_1h['dt_ist'] = df_bn_1h['dt_utc'].dt.tz_convert('Asia/Kolkata')
df_bn_1h['date_ist'] = df_bn_1h['dt_ist'].dt.date
df_bn_1h['time_ist'] = df_bn_1h['dt_ist'].dt.time
df_bn_1h = df_bn_1h.sort_values('dt_utc').reset_index(drop=True)
df_bn_1h['ema20'] = df_bn_1h['close'].ewm(span=20, adjust=False).mean()
df_bn_1h['ema200'] = df_bn_1h['close'].ewm(span=200, adjust=False).mean()

df_nf_idx = df_nf.set_index('dt_utc')
df_nf_1h = df_nf_idx.resample('1h').agg({
    'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
}).dropna().reset_index()
df_nf_1h['dt_ist'] = df_nf_1h['dt_utc'].dt.tz_convert('Asia/Kolkata')
df_nf_1h['date_ist'] = df_nf_1h['dt_ist'].dt.date
df_nf_1h['time_ist'] = df_nf_1h['dt_ist'].dt.time
df_nf_1h = df_nf_1h.sort_values('dt_utc').reset_index(drop=True)
df_nf_1h['ema20'] = df_nf_1h['close'].ewm(span=20, adjust=False).mean()
df_nf_1h['ema200'] = df_nf_1h['close'].ewm(span=200, adjust=False).mean()

print("=== RECENT 1-MONTH DAILY DATA (LAST 15 SESSIONS) ===")
print("\n--- BANK NIFTY RECENT DAILY SESSIONS ---")
print(df_bn_daily[['date_ist', 'open', 'high', 'low', 'close', 'ema20', 'ema200', 'dist_200_pct']].tail(15).to_string(index=False))

print("\n--- NIFTY RECENT DAILY SESSIONS ---")
print(df_nf_daily[['date_ist', 'open', 'high', 'low', 'close', 'ema20', 'ema200', 'dist_200_pct']].tail(15).to_string(index=False))

# Compare Recent 1-Month Range and High/Low
recent_bn = df_bn_daily.tail(22)
recent_nf = df_nf_daily.tail(22)

print("\n=== RECENT 1-MONTH METRICS COMPARISON ===")
print(f"BANKNIFTY 1-Month High: {recent_bn['high'].max():.2f} | Low: {recent_bn['low'].min():.2f} | Range: {recent_bn['high'].max() - recent_bn['low'].min():.2f} pts")
print(f"NIFTY 1-Month High:     {recent_nf['high'].max():.2f} | Low: {recent_nf['low'].min():.2f} | Range: {recent_nf['high'].max() - recent_nf['low'].min():.2f} pts")

# Correlation & Relative Strength
# Merge on date_ist
df_merged = pd.merge(df_bn_daily[['date_ist', 'close']].rename(columns={'close': 'bn_close'}),
                     df_nf_daily[['date_ist', 'close']].rename(columns={'close': 'nf_close'}),
                     on='date_ist').tail(22)
df_merged['bn_ret_pct'] = (df_merged['bn_close'] - df_merged['bn_close'].iloc[0]) / df_merged['bn_close'].iloc[0] * 100
df_merged['nf_ret_pct'] = (df_merged['nf_close'] - df_merged['nf_close'].iloc[0]) / df_merged['nf_close'].iloc[0] * 100
df_merged['relative_strength (BN - NF)'] = df_merged['bn_ret_pct'] - df_merged['nf_ret_pct']

print("\n--- RECENT 1-MONTH RELATIVE STRENGTH (BANKNIFTY vs NIFTY) ---")
print(df_merged[['date_ist', 'bn_close', 'nf_close', 'bn_ret_pct', 'nf_ret_pct', 'relative_strength (BN - NF)']].tail(10).to_string(index=False))

corr = df_merged['bn_ret_pct'].corr(df_merged['nf_ret_pct'])
print(f"\nRecent 1-Month 15-day Correlation between Bank Nifty and Nifty: {corr:.4f}")
