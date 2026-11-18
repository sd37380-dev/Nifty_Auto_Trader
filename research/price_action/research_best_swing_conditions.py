"""
Comprehensive Research on Best Conditions for Swing Trading in NIFTY 50 (5 Years: 2021-2026).
Evaluates:
1. EMA 200 Conditions (Macro Regime, Distance, Slope)
2. EMA 20 Conditions (Momentum, Pullback/Bounce, Dynamic Support)
3. EMA Multi-Alignment (EMA 20 > EMA 50 > EMA 200)
4. Other Key Factors: Volatility Regime (ATR Percentile), RSI Pullbacks, Market Structure, Candle Confirmation
5. Combined Optimal Conditions (The Ultimate High-Probability Swing State)
Calculates: Forward 3D, 5D, 7D, 10D Win Rates, Mean PnL Points, MFE (Max Favorable Excursion), MAE (Max Adverse Excursion), Profit Factor.
"""

import os
import sys
import sqlite3
import json
import numpy as np
import pandas as pd

# Load 15M continuous data and aggregate to daily
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

# Calculate Technical Indicators
n = len(df_daily)
c = df_daily['close']
h = df_daily['high']
l = df_daily['low']
o = df_daily['open']

# EMAs
df_daily['ema20'] = c.ewm(span=20, adjust=False).mean()
df_daily['ema50'] = c.ewm(span=50, adjust=False).mean()
df_daily['ema100'] = c.ewm(span=100, adjust=False).mean()
df_daily['ema200'] = c.ewm(span=200, adjust=False).mean()

# Slopes (5-day rate of change)
df_daily['ema20_slope'] = (df_daily['ema20'] - df_daily['ema20'].shift(5)) / df_daily['ema20'].shift(5) * 100
df_daily['ema50_slope'] = (df_daily['ema50'] - df_daily['ema50'].shift(5)) / df_daily['ema50'].shift(5) * 100
df_daily['ema200_slope'] = (df_daily['ema200'] - df_daily['ema200'].shift(10)) / df_daily['ema200'].shift(10) * 100

# Distances from EMAs (in %)
df_daily['dist_ema200_pct'] = (c - df_daily['ema200']) / df_daily['ema200'] * 100
df_daily['dist_ema20_pct'] = (c - df_daily['ema20']) / df_daily['ema20'] * 100

# ATR 14
prev_c = c.shift(1).fillna(o)
tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
df_daily['tr'] = tr
df_daily['atr14'] = tr.rolling(14).mean().bfill()
df_daily['atr_pct'] = df_daily['atr14'] / c * 100
# Volatility percentile (rolling 100-day rank)
df_daily['vol_rank'] = df_daily['atr14'].rolling(100).rank(pct=True).fillna(0.5)

# RSI 14
delta = c.diff()
gain = delta.where(delta > 0, 0.0)
loss = -delta.where(delta < 0, 0.0)
avg_gain = gain.rolling(14).mean()
avg_loss = loss.rolling(14).mean()
rs = avg_gain / avg_loss.replace(0, 1e-9)
df_daily['rsi14'] = 100 - (100 / (1 + rs))
df_daily['rsi14'] = df_daily['rsi14'].bfill()

# Candle Rejection / Geometry
df_daily['candle_range'] = h - l
df_daily['body'] = (c - o).abs()
df_daily['lower_wick'] = np.minimum(o, c) - l
df_daily['upper_wick'] = h - np.maximum(o, c)
df_daily['is_bull_rejection'] = (df_daily['lower_wick'] >= 0.35 * df_daily['candle_range']) | ((c > o) & (c > (l + 0.6 * df_daily['candle_range'])))
df_daily['is_bear_rejection'] = (df_daily['upper_wick'] >= 0.35 * df_daily['candle_range']) | ((c < o) & (c < (h - 0.6 * df_daily['candle_range'])))

# EMA 20 Touch / Test: Low touches EMA 20 or penetrates within 0.3 ATR
df_daily['ema20_touch'] = (l <= df_daily['ema20'] + 0.2 * df_daily['atr14']) & (h >= df_daily['ema20'] - 0.2 * df_daily['atr14'])
df_daily['ema50_touch'] = (l <= df_daily['ema50'] + 0.2 * df_daily['atr14']) & (h >= df_daily['ema50'] - 0.2 * df_daily['atr14'])
df_daily['ema200_touch'] = (l <= df_daily['ema200'] + 0.3 * df_daily['atr14']) & (h >= df_daily['ema200'] - 0.3 * df_daily['atr14'])

# Forward Returns and Excursions for 3D, 5D, 7D, 10D
for hold in [3, 5, 7, 10]:
    df_daily[f'fwd_{hold}d_ret'] = df_daily['close'].shift(-hold) - df_daily['close']
    df_daily[f'fwd_{hold}d_pct'] = (df_daily['close'].shift(-hold) - df_daily['close']) / df_daily['close'] * 100
    
    # MFE (Maximum Favorable Excursion) and MAE (Maximum Adverse Excursion)
    mfe_list = []
    mae_list = []
    for i in range(len(df_daily)):
        if i + hold < len(df_daily):
            fwd_highs = df_daily.loc[i+1 : i+hold, 'high']
            fwd_lows = df_daily.loc[i+1 : i+hold, 'low']
            curr_c = df_daily.loc[i, 'close']
            mfe_list.append(fwd_highs.max() - curr_c)
            mae_list.append(curr_c - fwd_lows.min())
        else:
            mfe_list.append(np.nan)
            mae_list.append(np.nan)
    df_daily[f'mfe_{hold}d'] = mfe_list
    df_daily[f'mae_{hold}d'] = mae_list

# Save enriched dataset for analysis
print(f"Data ready: {len(df_daily)} bars from {df_daily['date_ist'].min()} to {df_daily['date_ist'].max()}")

# Helper to analyze any condition
def evaluate_condition(name: str, mask: pd.Series, hold: int = 5):
    sub = df_daily[mask].dropna(subset=[f'fwd_{hold}d_ret', f'mfe_{hold}d', f'mae_{hold}d'])
    cnt = len(sub)
    if cnt == 0:
        return None
    ret = sub[f'fwd_{hold}d_ret']
    win_cnt = (ret > 0).sum()
    win_rate = (win_cnt / cnt) * 100
    mean_ret = ret.mean()
    median_ret = ret.median()
    mfe = sub[f'mfe_{hold}d'].mean()
    mae = sub[f'mae_{hold}d'].mean()
    ratio_mfe_mae = mfe / mae if mae > 0 else 0
    
    # Profit factor calculation
    wins = ret[ret > 0].sum()
    losses = abs(ret[ret < 0].sum())
    pf = (wins / losses) if losses > 0 else 999.0
    
    return {
        'Condition': name,
        'Samples': cnt,
        f'{hold}D_WinRate%': round(win_rate, 2),
        f'{hold}D_Mean_Pts': round(mean_ret, 2),
        f'{hold}D_Median_Pts': round(median_ret, 2),
        f'{hold}D_MFE_Pts': round(mfe, 2),
        f'{hold}D_MAE_Pts': round(mae, 2),
        'MFE/MAE': round(ratio_mfe_mae, 2),
        'Profit_Factor': round(pf, 2)
    }

# -------------------------------------------------------------------------
# 1. EMA 200 CONDITION BENCHMARKS
# -------------------------------------------------------------------------
print("\n--- 1. EMA 200 REGIME ANALYSIS (5-DAY HORIZON) ---")
c_ema200_above = df_daily['close'] > df_daily['ema200']
c_ema200_below = df_daily['close'] < df_daily['ema200']
c_ema200_slope_up = df_daily['ema200_slope'] > 0.2
c_ema200_slope_down = df_daily['ema200_slope'] < -0.2
c_ema200_near = (df_daily['dist_ema200_pct'] >= 0) & (df_daily['dist_ema200_pct'] <= 3.0)
c_ema200_extended = df_daily['dist_ema200_pct'] > 8.0

ema200_res = [
    evaluate_condition("All Days (Baseline)", pd.Series(True, index=df_daily.index)),
    evaluate_condition("Close > EMA 200 (Macro Bull)", c_ema200_above),
    evaluate_condition("Close < EMA 200 (Macro Bear)", c_ema200_below),
    evaluate_condition("EMA 200 Slope Rising (>0.2%)", c_ema200_slope_up),
    evaluate_condition("EMA 200 Slope Falling (<-0.2%)", c_ema200_slope_down),
    evaluate_condition("Near EMA 200 (0% to +3% above)", c_ema200_near),
    evaluate_condition("Overextended from EMA 200 (>8% above)", c_ema200_extended),
]
print(pd.DataFrame([r for r in ema200_res if r]).to_string(index=False))

# -------------------------------------------------------------------------
# 2. EMA 20 CONDITIONS & PULLBACKS
# -------------------------------------------------------------------------
print("\n--- 2. EMA 20 MOMENTUM & PULLBACK ANALYSIS ---")
c_ema20_above = df_daily['close'] > df_daily['ema20']
c_ema20_below = df_daily['close'] < df_daily['ema20']
c_ema20_touch_bull = (df_daily['close'] > df_daily['ema200']) & df_daily['ema20_touch'] & (df_daily['close'] >= df_daily['ema20'])
c_ema20_bounce = c_ema20_touch_bull & df_daily['is_bull_rejection']
c_ema20_slope_up = df_daily['ema20_slope'] > 0.5
c_ema20_slope_down = df_daily['ema20_slope'] < -0.5

ema20_res = [
    evaluate_condition("Close > EMA 20", c_ema20_above),
    evaluate_condition("Close < EMA 20", c_ema20_below),
    evaluate_condition("EMA 20 Rising (>0.5%)", c_ema20_slope_up),
    evaluate_condition("EMA 20 Falling (<-0.5%)", c_ema20_slope_down),
    evaluate_condition("EMA 20 Pullback Touch in Bull", c_ema20_touch_bull),
    evaluate_condition("EMA 20 Pullback + Bull Rejection", c_ema20_bounce),
]
print(pd.DataFrame([r for r in ema20_res if r]).to_string(index=False))

# -------------------------------------------------------------------------
# 3. MULTI-EMA ALIGNMENT HIERARCHIES
# -------------------------------------------------------------------------
print("\n--- 3. MULTI-EMA ALIGNMENT HIERARCHY ---")
# Full Bullish Alignment: Close > EMA20 > EMA50 > EMA200
c_triple_bull = (df_daily['close'] > df_daily['ema20']) & (df_daily['ema20'] > df_daily['ema50']) & (df_daily['ema50'] > df_daily['ema200'])
# Full Bearish Alignment: Close < EMA20 < EMA50 < EMA200
c_triple_bear = (df_daily['close'] < df_daily['ema20']) & (df_daily['ema20'] < df_daily['ema50']) & (df_daily['ema50'] < df_daily['ema200'])
# Golden Cross Regime: EMA50 > EMA200
c_golden_cross = df_daily['ema50'] > df_daily['ema200']
# Pullback in Triple Bull: EMA20 > EMA50 > EMA200 BUT Price pulls back to EMA 20 (Low <= EMA20)
c_pullback_in_triple_bull = (df_daily['ema20'] > df_daily['ema50']) & (df_daily['ema50'] > df_daily['ema200']) & (df_daily['low'] <= df_daily['ema20'] + 0.15*df_daily['atr14']) & (df_daily['close'] >= df_daily['ema20'] - 0.2*df_daily['atr14'])

multi_ema_res = [
    evaluate_condition("Golden Cross Regime (50 > 200)", c_golden_cross),
    evaluate_condition("Full Bull Alignment (Close > 20 > 50 > 200)", c_triple_bull),
    evaluate_condition("Full Bear Alignment (Close < 20 < 50 < 200)", c_triple_bear),
    evaluate_condition("Pullback to 20 in Triple Bull", c_pullback_in_triple_bull),
]
print(pd.DataFrame([r for r in multi_ema_res if r]).to_string(index=False))

# -------------------------------------------------------------------------
# 4. OTHER KEY STRUCTURAL & VOLATILITY ASPECTS
# -------------------------------------------------------------------------
print("\n--- 4. OTHER ASPECTS: VOLATILITY, RSI & CANDLE REJECTION ---")
# Volatility Regimes
c_low_vol = df_daily['vol_rank'] <= 0.30
c_norm_vol = (df_daily['vol_rank'] > 0.30) & (df_daily['vol_rank'] < 0.70)
c_high_vol = df_daily['vol_rank'] >= 0.70

# RSI Zones in Bull Market
c_rsi_pullback = (df_daily['close'] > df_daily['ema200']) & (df_daily['rsi14'] >= 40) & (df_daily['rsi14'] <= 55)
c_rsi_overbought = (df_daily['close'] > df_daily['ema200']) & (df_daily['rsi14'] >= 70)
c_rsi_oversold = df_daily['rsi14'] <= 35

other_res = [
    evaluate_condition("Low Volatility Regime (Compression)", c_low_vol),
    evaluate_condition("Normal Volatility Regime", c_norm_vol),
    evaluate_condition("High Volatility Regime (Chaotic)", c_high_vol),
    evaluate_condition("RSI 40-55 Pullback in Bull", c_rsi_pullback),
    evaluate_condition("RSI Overbought (>70) in Bull", c_rsi_overbought),
    evaluate_condition("RSI Oversold (<=35)", c_rsi_oversold),
]
print(pd.DataFrame([r for r in other_res if r]).to_string(index=False))

# -------------------------------------------------------------------------
# 5. COMBINED OPTIMAL SWING CONDITIONS ("THE GOLDEN SWING STATE")
# -------------------------------------------------------------------------
print("\n--- 5. COMBINED MULTI-FACTOR SWING CONDITIONS ---")
# Combination 1: The Classic Trend Pullback (Close > EMA200 + EMA20 > EMA50 + Touch EMA20 + Bull Rejection)
combo1 = (df_daily['close'] > df_daily['ema200']) & (df_daily['ema20'] > df_daily['ema50']) & df_daily['ema20_touch'] & df_daily['is_bull_rejection']

# Combination 2: Golden Pocket Pullback (Close > EMA200 + EMA50 > EMA200 + RSI 40-55 + Rejection)
combo2 = (df_daily['close'] > df_daily['ema200']) & (df_daily['ema50'] > df_daily['ema200']) & (df_daily['rsi14'] >= 40) & (df_daily['rsi14'] <= 55) & df_daily['is_bull_rejection']

# Combination 3: Low Volatility Compression Breakout (Low Vol Rank <= 0.35 + Close > EMA20 + EMA20 > EMA50 + EMA50 > EMA200)
combo3 = (df_daily['vol_rank'] <= 0.35) & (df_daily['close'] > df_daily['ema20']) & (df_daily['ema20'] > df_daily['ema50']) & (df_daily['ema50'] > df_daily['ema200'])

# Combination 4: The Institutional Dip Absorption (Touch EMA50 in Bull + Close > EMA50 + Bull Wick)
combo4 = (df_daily['close'] > df_daily['ema200']) & df_daily['ema50_touch'] & (df_daily['close'] >= df_daily['ema50']) & df_daily['is_bull_rejection']

# Evaluate across multiple holding horizons (3D, 5D, 7D, 10D)
combo_res_5d = [
    evaluate_condition("Combo 1: EMA 20 Bounce in Strong Bull", combo1, hold=5),
    evaluate_condition("Combo 2: RSI 40-55 Dip + Rejection in Bull", combo2, hold=5),
    evaluate_condition("Combo 3: Low Vol Compression in Triple Bull", combo3, hold=5),
    evaluate_condition("Combo 4: EMA 50 Institutional Dip Absorption", combo4, hold=5),
]
print("\n5-Day Holding Performance:")
print(pd.DataFrame([r for r in combo_res_5d if r]).to_string(index=False))

combo_res_10d = [
    evaluate_condition("Combo 1: EMA 20 Bounce in Strong Bull", combo1, hold=10),
    evaluate_condition("Combo 2: RSI 40-55 Dip + Rejection in Bull", combo2, hold=10),
    evaluate_condition("Combo 3: Low Vol Compression in Triple Bull", combo3, hold=10),
    evaluate_condition("Combo 4: EMA 50 Institutional Dip Absorption", combo4, hold=10),
]
print("\n10-Day Holding Performance:")
print(pd.DataFrame([r for r in combo_res_10d if r]).to_string(index=False))
