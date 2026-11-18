"""
Comprehensive Empirical Backtest of 3 Swing Trading Archetypes on 5-Year NIFTY Data (2021-2026):
1. LONG Swing Trades (Trend-following pullbacks)
2. SHORT Swing Trades (Downtrend momentum & rallies to resistance)
3. REVERSAL Swing Trades (Mean reversion based on distance stretch from EMA 200)

Evaluates:
- Exact distance thresholds from EMA 200 (in % and in ATR)
- Trigger confirmations (rejection wicks, RSI extremes)
- Forward 3D, 5D, 7D, 10D Win Rates, Mean Return (pts), Profit Factor, MFE / MAE ratios.
"""

import os
import sys
import sqlite3
import json
import numpy as np
import pandas as pd

conn = sqlite3.connect("data/hermes_research/market_data.db")
query = """
SELECT timestamp, open, high, low, close, volume 
FROM normalized_bars 
WHERE symbol = 'NIFTY' AND timeframe = '15M' 
ORDER BY timestamp ASC
"""
df_raw = pd.read_sql_query(query, conn)
conn.close()

df = df_raw.copy()
df['dt_utc'] = pd.to_datetime(df['timestamp'], format='ISO8601')
df['dt_ist'] = df['dt_utc'].dt.tz_convert('Asia/Kolkata')
df['date_ist'] = df['dt_ist'].dt.date
df['time_ist'] = df['dt_ist'].dt.time
from datetime import time
df = df[(df['time_ist'] >= time(9, 15)) & (df['time_ist'] <= time(15, 30))].copy()
df = df.sort_values('dt_utc').reset_index(drop=True)

# Build Daily Bars
df_daily = df.groupby('date_ist').agg({
    'open': 'first',
    'high': 'max',
    'low': 'min',
    'close': 'last',
    'volume': 'sum'
}).reset_index()
df_daily['date'] = pd.to_datetime(df_daily['date_ist'])
df_daily = df_daily.sort_values('date').reset_index(drop=True)

c = df_daily['close']
h = df_daily['high']
l = df_daily['low']
o = df_daily['open']

# Indicators
df_daily['ema20'] = c.ewm(span=20, adjust=False).mean()
df_daily['ema50'] = c.ewm(span=50, adjust=False).mean()
df_daily['ema200'] = c.ewm(span=200, adjust=False).mean()

# ATR 14
prev_c = c.shift(1).fillna(o)
tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
df_daily['tr'] = tr
df_daily['atr14'] = tr.rolling(14).mean().bfill()
df_daily['vol_rank'] = df_daily['atr14'].rolling(100).rank(pct=True).fillna(0.5)

# Distance Factor from EMA 200
# Percentage distance: (Close - EMA 200) / EMA 200 * 100
df_daily['dist_ema200_pct'] = (c - df_daily['ema200']) / df_daily['ema200'] * 100
# Normalized ATR distance: (Close - EMA 200) / ATR 14
df_daily['dist_ema200_atr'] = (c - df_daily['ema200']) / df_daily['atr14']

# Distance from EMA 20
df_daily['dist_ema20_pct'] = (c - df_daily['ema20']) / df_daily['ema20'] * 100
df_daily['dist_ema20_atr'] = (c - df_daily['ema20']) / df_daily['atr14']

# RSI 14
delta = c.diff()
gain = delta.where(delta > 0, 0.0)
loss = -delta.where(delta < 0, 0.0)
avg_gain = gain.rolling(14).mean()
avg_loss = loss.rolling(14).mean()
rs = avg_gain / avg_loss.replace(0, 1e-9)
df_daily['rsi14'] = 100 - (100 / (1 + rs))
df_daily['rsi14'] = df_daily['rsi14'].bfill()

# Candle Rejection
candle_range = np.maximum(h - l, 0.1)
lower_wick = np.minimum(o, c) - l
upper_wick = h - np.maximum(o, c)
df_daily['candle_range'] = candle_range
df_daily['is_bull_rejection'] = (lower_wick >= 0.30 * candle_range) | ((c > o) & (c >= (l + 0.55 * candle_range)))
df_daily['is_bear_rejection'] = (upper_wick >= 0.30 * candle_range) | ((c < o) & (c <= (l + 0.45 * candle_range)))

# Calculate Forward Returns and Excursions for Long and Short
for hold in [3, 5, 7, 10]:
    # For Longs: Close[t+hold] - Close[t]
    df_daily[f'fwd_{hold}d_long'] = df_daily['close'].shift(-hold) - df_daily['close']
    # For Shorts: Close[t] - Close[t+hold]
    df_daily[f'fwd_{hold}d_short'] = df_daily['close'] - df_daily['close'].shift(-hold)

    # Excursions for Long
    mfe_long, mae_long = [], []
    # Excursions for Short
    mfe_short, mae_short = [], []
    
    for i in range(len(df_daily)):
        if i + hold < len(df_daily):
            fwd_highs = df_daily.loc[i+1 : i+hold, 'high']
            fwd_lows = df_daily.loc[i+1 : i+hold, 'low']
            curr_c = df_daily.loc[i, 'close']
            
            # Long excursions
            mfe_long.append(fwd_highs.max() - curr_c)
            mae_long.append(curr_c - fwd_lows.min())
            
            # Short excursions
            mfe_short.append(curr_c - fwd_lows.min())
            mae_short.append(fwd_highs.max() - curr_c)
        else:
            mfe_long.append(np.nan)
            mae_long.append(np.nan)
            mfe_short.append(np.nan)
            mae_short.append(np.nan)
            
    df_daily[f'mfe_{hold}d_long'] = mfe_long
    df_daily[f'mae_{hold}d_long'] = mae_long
    df_daily[f'mfe_{hold}d_short'] = mfe_short
    df_daily[f'mae_{hold}d_short'] = mae_short


def evaluate_setup(name: str, mask: pd.Series, side: str = 'LONG', hold: int = 5):
    sub = df_daily[mask].dropna(subset=[f'fwd_{hold}d_{side.lower()}', f'mfe_{hold}d_{side.lower()}', f'mae_{hold}d_{side.lower()}'])
    cnt = len(sub)
    if cnt == 0:
        return None
    ret = sub[f'fwd_{hold}d_{side.lower()}']
    win_cnt = (ret > 0).sum()
    win_rate = (win_cnt / cnt) * 100.0
    mean_ret = ret.mean()
    median_ret = ret.median()
    mfe = sub[f'mfe_{hold}d_{side.lower()}'].mean()
    mae = sub[f'mae_{hold}d_{side.lower()}'].mean()
    ratio_mfe_mae = mfe / mae if mae > 0 else 0.0
    wins = ret[ret > 0].sum()
    losses = abs(ret[ret < 0].sum())
    pf = (wins / losses) if losses > 0 else 999.0

    return {
        'Type': side,
        'Setup Name': name,
        'Horizon': f"{hold}D",
        'Samples': cnt,
        'Win Rate %': round(win_rate, 2),
        'Mean Pts': round(mean_ret, 2),
        'Median Pts': round(median_ret, 2),
        'MFE (pts)': round(mfe, 2),
        'MAE (pts)': round(mae, 2),
        'MFE/MAE': round(ratio_mfe_mae, 2),
        'Profit Factor': round(pf, 2)
    }

print("\n==========================================================================")
print("1. EVALUATING DISTANCE FACTOR FROM EMA 200 FOR REVERSALS")
print("==========================================================================")

# Distance Sweep for Bullish Reversal (Oversold extreme below EMA 200)
print("\n--- A. Bullish Reversal (Price Stretched BELOW EMA 200 -> Snapback LONG) ---")
rev_bull_results = []
for d_thresh in [-3.0, -5.0, -7.0, -9.0]:
    mask_dist = df_daily['dist_ema200_pct'] <= d_thresh
    rev_bull_results.append(evaluate_setup(f"Price <= {d_thresh}% below EMA 200", mask_dist, side='LONG', hold=5))
    # Add trigger: Rejection candle + RSI <= 38
    mask_trig = mask_dist & df_daily['is_bull_rejection'] & (df_daily['rsi14'] <= 40)
    rev_bull_results.append(evaluate_setup(f"Price <= {d_thresh}% below EMA 200 + Rejection + RSI<=40", mask_trig, side='LONG', hold=5))

print(pd.DataFrame([r for r in rev_bull_results if r]).to_string(index=False))

# Distance Sweep for Bearish Reversal (Overbought extreme above EMA 200)
print("\n--- B. Bearish Reversal (Price Stretched ABOVE EMA 200 -> Snapback SHORT) ---")
rev_bear_results = []
for d_thresh in [6.0, 8.0, 10.0, 12.0]:
    mask_dist = df_daily['dist_ema200_pct'] >= d_thresh
    rev_bear_results.append(evaluate_setup(f"Price >= +{d_thresh}% above EMA 200", mask_dist, side='SHORT', hold=5))
    # Add trigger: Bearish rejection candle + RSI >= 70
    mask_trig = mask_dist & df_daily['is_bear_rejection'] & (df_daily['rsi14'] >= 68)
    rev_bear_results.append(evaluate_setup(f"Price >= +{d_thresh}% above EMA 200 + Bear Rej + RSI>=68", mask_trig, side='SHORT', hold=5))

print(pd.DataFrame([r for r in rev_bear_results if r]).to_string(index=False))

print("\n==========================================================================")
print("2. EVALUATING THE 3 CORE SWING TRADING TYPES")
print("==========================================================================")

# TYPE 1: BEST LONG SWING TRADE (Trend Continuation Pullback)
# Condition: Close > EMA 200 + EMA 20 > EMA 50 + Low Vol Compression + RSI 40-55 Pullback to EMA 20
mask_long_trend = (df_daily['close'] > df_daily['ema200']) & \
                  (df_daily['ema20'] > df_daily['ema50']) & \
                  (df_daily['low'] <= df_daily['ema20'] + 0.20 * df_daily['atr14']) & \
                  (df_daily['close'] >= df_daily['ema20'] - 0.25 * df_daily['atr14']) & \
                  (df_daily['rsi14'] >= 40) & (df_daily['rsi14'] <= 58) & \
                  df_daily['is_bull_rejection']

# TYPE 2: BEST SHORT SWING TRADE (Downtrend Continuation & Bear Rally Exhaustion)
# Condition: Close < EMA 200 + EMA 20 < EMA 50 + Rally to EMA 20 + Bearish Rejection
mask_short_trend = (df_daily['close'] < df_daily['ema200']) & \
                   (df_daily['ema20'] < df_daily['ema50']) & \
                   (df_daily['high'] >= df_daily['ema20'] - 0.20 * df_daily['atr14']) & \
                   (df_daily['close'] <= df_daily['ema20'] + 0.25 * df_daily['atr14']) & \
                   (df_daily['rsi14'] >= 42) & (df_daily['rsi14'] <= 60) & \
                   df_daily['is_bear_rejection']

# TYPE 3A: BEST BULLISH REVERSAL SWING TRADE (Oversold Rubber-Band Snapback)
# Condition: Stretched <= -5% below EMA 200 + RSI <= 38 + Bullish Rejection Candle
mask_reversal_long = (df_daily['dist_ema200_pct'] <= -5.0) & \
                     (df_daily['rsi14'] <= 40) & \
                     df_daily['is_bull_rejection']

# TYPE 3B: BEST BEARISH REVERSAL SWING TRADE (Overbought Rubber-Band Snapback)
# Condition: Stretched >= +8.5% above EMA 200 + RSI >= 68 + Bearish Rejection Candle
mask_reversal_short = (df_daily['dist_ema200_pct'] >= 8.5) & \
                      (df_daily['rsi14'] >= 68) & \
                      df_daily['is_bear_rejection']

archetype_rows = []
for h in [5, 10]:
    archetype_rows.append(evaluate_setup("Type 1: Trend Pullback LONG (EMA 20 Bounce in Bull)", mask_long_trend, side='LONG', hold=h))
    archetype_rows.append(evaluate_setup("Type 2: Downtrend Rally Exhaustion SHORT (EMA 20 Reject in Bear)", mask_short_trend, side='SHORT', hold=h))
    archetype_rows.append(evaluate_setup("Type 3A: Oversold Rubber-Band REVERSAL LONG (Dist <= -5% EMA 200)", mask_reversal_long, side='LONG', hold=h))
    archetype_rows.append(evaluate_setup("Type 3B: Overbought Rubber-Band REVERSAL SHORT (Dist >= +8.5% EMA 200)", mask_reversal_short, side='SHORT', hold=h))

df_arch = pd.DataFrame([r for r in archetype_rows if r])
print("\n=== PERFORMANCE MATRIX OF THE 3 SWING TRADING TYPES ===")
print(df_arch.to_string(index=False))
