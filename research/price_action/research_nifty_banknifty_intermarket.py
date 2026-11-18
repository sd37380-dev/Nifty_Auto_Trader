"""
HERMES INTER-MARKET PRICE ACTION RESEARCH
NIFTY vs BANKNIFTY RELATIONSHIP, 200 EMA DISTANCE DYNAMICS & 3 SWING TRADE ARCHETYPES

Evaluates 5 Years of Continuous Data (2021-2026) across 1,234 Daily Sessions & 5,043 1H Bars:
1. Inter-market Correlation, Lead-Lag Dynamics & Spread Ratio (BankNifty / Nifty)
2. Dual 200 EMA Distance Factor (Confluence of Rubber-Band Stretches)
3. Inter-market Divergence (BankNifty Higher Low vs Nifty Lower Low)
4. Full Backtest of 3 Swing Types (LONG, SHORT, REVERSAL) on BANKNIFTY and NIFTY
5. Exact Highly Profitable Sweet-Spot Conditions
"""

import os
import sys
import numpy as np
import pandas as pd

# 1. Load 5-Year Daily Datasets
df_bn = pd.read_csv("data/hermes_research/banknifty_research/BANKNIFTY_DAILY_5Y.csv")
df_nf = pd.read_csv("data/hermes_research/banknifty_research/NIFTY_DAILY_5Y.csv")

df_bn['date'] = pd.to_datetime(df_bn['date'])
df_nf['date'] = pd.to_datetime(df_nf['date'])

# Merge on common trading days
df = pd.merge(
    df_bn[['date', 'Open', 'High', 'Low', 'Close', 'Volume']].rename(
        columns={'Open': 'bn_open', 'High': 'bn_high', 'Low': 'bn_low', 'Close': 'bn_close', 'Volume': 'bn_vol'}
    ),
    df_nf[['date', 'Open', 'High', 'Low', 'Close', 'Volume']].rename(
        columns={'Open': 'nf_open', 'High': 'nf_high', 'Low': 'nf_low', 'Close': 'nf_close', 'Volume': 'nf_vol'}
    ),
    on='date'
).sort_values('date').reset_index(drop=True)

n = len(df)
print(f"Total Synchronized Daily Sessions (5 Years): {n} days ({df['date'].min().date()} to {df['date'].max().date()})")

# 2. Compute Technical Indicators for BANKNIFTY
df['bn_ema20'] = df['bn_close'].ewm(span=20, adjust=False).mean()
df['bn_ema50'] = df['bn_close'].ewm(span=50, adjust=False).mean()
df['bn_ema200'] = df['bn_close'].ewm(span=200, adjust=False).mean()

bn_prev_c = df['bn_close'].shift(1).fillna(df['bn_open'])
bn_tr = np.maximum(df['bn_high'] - df['bn_low'], np.maximum(np.abs(df['bn_high'] - bn_prev_c), np.abs(df['bn_low'] - bn_prev_c)))
df['bn_atr14'] = bn_tr.rolling(14).mean().bfill()
df['bn_dist_200_pct'] = (df['bn_close'] - df['bn_ema200']) / df['bn_ema200'] * 100
df['bn_dist_20_pct'] = (df['bn_close'] - df['bn_ema20']) / df['bn_ema20'] * 100

# 3. Compute Technical Indicators for NIFTY
df['nf_ema20'] = df['nf_close'].ewm(span=20, adjust=False).mean()
df['nf_ema50'] = df['nf_close'].ewm(span=50, adjust=False).mean()
df['nf_ema200'] = df['nf_close'].ewm(span=200, adjust=False).mean()

nf_prev_c = df['nf_close'].shift(1).fillna(df['nf_open'])
nf_tr = np.maximum(df['nf_high'] - df['nf_low'], np.maximum(np.abs(df['nf_high'] - nf_prev_c), np.abs(df['nf_low'] - nf_prev_c)))
df['nf_atr14'] = nf_tr.rolling(14).mean().bfill()
df['nf_dist_200_pct'] = (df['nf_close'] - df['nf_ema200']) / df['nf_ema200'] * 100
df['nf_dist_20_pct'] = (df['nf_close'] - df['nf_ema20']) / df['nf_ema20'] * 100

# 4. Inter-Market Spread & Relative Strength
df['spread_ratio'] = df['bn_close'] / df['nf_close']
df['spread_ratio_ema50'] = df['spread_ratio'].ewm(span=50, adjust=False).mean()
df['spread_divergence_pct'] = (df['spread_ratio'] - df['spread_ratio_ema50']) / df['spread_ratio_ema50'] * 100

# RSI 14 for both
for sym in ['bn', 'nf']:
    c = df[f'{sym}_close']
    delta = c.diff()
    gain = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs = gain / loss.replace(0, 1e-9)
    df[f'{sym}_rsi14'] = (100 - (100 / (1 + rs))).bfill()

# Rejection Candles
for sym in ['bn', 'nf']:
    c, o, h, l = df[f'{sym}_close'], df[f'{sym}_open'], df[f'{sym}_high'], df[f'{sym}_low']
    rng = np.maximum(h - l, 0.1)
    lw = np.minimum(o, c) - l
    uw = h - np.maximum(o, c)
    df[f'{sym}_bull_rej'] = (lw >= 0.30 * rng) | ((c > o) & (c >= (l + 0.55 * rng)))
    df[f'{sym}_bear_rej'] = (uw >= 0.30 * rng) | ((c < o) & (c <= (l + 0.45 * rng)))

# Forward Returns for both assets (5D and 10D)
for hold in [5, 10]:
    df[f'bn_fwd_{hold}d_long'] = df['bn_close'].shift(-hold) - df['bn_close']
    df[f'bn_fwd_{hold}d_short'] = df['bn_close'] - df['bn_close'].shift(-hold)
    df[f'nf_fwd_{hold}d_long'] = df['nf_close'].shift(-hold) - df['nf_close']
    df[f'nf_fwd_{hold}d_short'] = df['nf_close'] - df['nf_close'].shift(-hold)

    # Excursions for Bank Nifty
    mfe_l, mae_l, mfe_s, mae_s = [], [], [], []
    for i in range(len(df)):
        if i + hold < len(df):
            fwd_h = df.loc[i+1 : i+hold, 'bn_high']
            fwd_l = df.loc[i+1 : i+hold, 'bn_low']
            curr_c = df.loc[i, 'bn_close']
            mfe_l.append(fwd_h.max() - curr_c)
            mae_l.append(curr_c - fwd_l.min())
            mfe_s.append(curr_c - fwd_l.min())
            mae_s.append(fwd_h.max() - curr_c)
        else:
            mfe_l.append(np.nan)
            mae_l.append(np.nan)
            mfe_s.append(np.nan)
            mae_s.append(np.nan)
    df[f'bn_mfe_{hold}d_l'] = mfe_l
    df[f'bn_mae_{hold}d_l'] = mae_l
    df[f'bn_mfe_{hold}d_s'] = mfe_s
    df[f'bn_mae_{hold}d_s'] = mae_s


def evaluate_bn_setup(name: str, mask: pd.Series, side: str = 'LONG', hold: int = 5):
    sub = df[mask].dropna(subset=[f'bn_fwd_{hold}d_{side.lower()}', f'bn_mfe_{hold}d_{side.lower()[0]}', f'bn_mae_{hold}d_{side.lower()[0]}'])
    cnt = len(sub)
    if cnt == 0:
        return None
    ret = sub[f'bn_fwd_{hold}d_{side.lower()}']
    win_cnt = (ret > 0).sum()
    win_rate = (win_cnt / cnt) * 100.0
    mean_ret = ret.mean()
    median_ret = ret.median()
    mfe = sub[f'bn_mfe_{hold}d_{side.lower()[0]}'].mean()
    mae = sub[f'bn_mae_{hold}d_{side.lower()[0]}'].mean()
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
        'BN Mean Pts': round(mean_ret, 2),
        'BN Median Pts': round(median_ret, 2),
        'MFE (pts)': round(mfe, 2),
        'MAE (pts)': round(mae, 2),
        'MFE/MAE': round(ratio_mfe_mae, 2),
        'Profit Factor': round(pf, 2)
    }

print("\n==========================================================================")
print("1. NIFTY vs BANKNIFTY CORRELATION & LEAD-LAG DYNAMICS")
print("==========================================================================")
daily_corr = df['bn_close'].pct_change().corr(df['nf_close'].pct_change())
print(f"Overall 5-Year Daily Return Correlation: {daily_corr:.4f} (~{daily_corr*100:.1f}%)")

# Beta of Bank Nifty relative to Nifty
cov = np.cov(df['bn_close'].pct_change().dropna(), df['nf_close'].pct_change().dropna())[0][1]
var_nf = np.var(df['nf_close'].pct_change().dropna())
beta_bn = cov / var_nf
print(f"BankNifty Beta to Nifty: {beta_bn:.2f} (BankNifty moves {beta_bn:.2f}x for every 1.0% in Nifty)")

print("\n==========================================================================")
print("2. DUAL 200 EMA DISTANCE DYNAMICS (RUBBER-BAND CONFLUENCE)")
print("==========================================================================")

# A. Single vs Dual Stretches for Bullish Reversals
c_bn_stretch_5 = df['bn_dist_200_pct'] <= -5.0
c_dual_stretch_4 = (df['bn_dist_200_pct'] <= -4.0) & (df['nf_dist_200_pct'] <= -3.5)
c_dual_stretch_5 = (df['bn_dist_200_pct'] <= -5.0) & (df['nf_dist_200_pct'] <= -4.5)

dual_rev_results = [
    evaluate_bn_setup("BankNifty Stretched <= -5% below 200 EMA", c_bn_stretch_5, side='LONG', hold=5),
    evaluate_bn_setup("DUAL STRETCH: Both BN <= -4% and NF <= -3.5%", c_dual_stretch_4, side='LONG', hold=5),
    evaluate_bn_setup("DUAL EXTREME: Both BN <= -5% and NF <= -4.5%", c_dual_stretch_5, side='LONG', hold=5),
    evaluate_bn_setup("BankNifty Stretched <= -5% below 200 EMA", c_bn_stretch_5, side='LONG', hold=10),
    evaluate_bn_setup("DUAL STRETCH: Both BN <= -4% and NF <= -3.5%", c_dual_stretch_4, side='LONG', hold=10),
    evaluate_bn_setup("DUAL EXTREME: Both BN <= -5% and NF <= -4.5%", c_dual_stretch_5, side='LONG', hold=10),
]
print(pd.DataFrame([r for r in dual_rev_results if r]).to_string(index=False))

# B. Dual Stretches for Bearish Reversals
print("\n--- Bearish Reversals (Overbought Dual Stretches above 200 EMA) ---")
c_bn_over_8 = df['bn_dist_200_pct'] >= 8.0
c_dual_over_7 = (df['bn_dist_200_pct'] >= 7.0) & (df['nf_dist_200_pct'] >= 6.0) & df['bn_bear_rej']

dual_bear_results = [
    evaluate_bn_setup("BankNifty Stretched >= +8% above 200 EMA", c_bn_over_8, side='SHORT', hold=5),
    evaluate_bn_setup("DUAL OVERBOUGHT: Both BN >= +7% & NF >= +6% + Bear Rej", c_dual_over_7, side='SHORT', hold=5),
]
print(pd.DataFrame([r for r in dual_bear_results if r]).to_string(index=False))

print("\n==========================================================================")
print("3. INTER-MARKET DIVERGENCE: BANKNIFTY HIGHER LOW vs NIFTY LOWER LOW")
print("==========================================================================")
# Detect divergence over a 5-day window:
# BankNifty Low > 5-day min Low, but Nifty Low <= 5-day min Low
df['bn_low_5d_min'] = df['bn_low'].shift(1).rolling(5).min()
df['nf_low_5d_min'] = df['nf_low'].shift(1).rolling(5).min()

c_bull_divergence = (df['bn_low'] > df['bn_low_5d_min']) & \
                    (df['nf_low'] <= df['nf_low_5d_min'] + 0.1 * df['nf_atr14']) & \
                    (df['bn_close'] < df['bn_ema50']) & \
                    df['bn_bull_rej']

div_res = [
    evaluate_bn_setup("Inter-Market Bullish Divergence (BN Higher Low vs NF Lower Low)", c_bull_divergence, side='LONG', hold=5),
    evaluate_bn_setup("Inter-Market Bullish Divergence (BN Higher Low vs NF Lower Low)", c_bull_divergence, side='LONG', hold=10),
]
print(pd.DataFrame([r for r in div_res if r]).to_string(index=False))

print("\n==========================================================================")
print("4. FULL 3 SWING TRADE ARCHETYPES BENCHMARK (NIFTY & BANKNIFTY CONFLUENCE)")
print("==========================================================================")

# TYPE 1: CONFLUENT LONG SWING TRADE
# Both above 200 EMA + Both EMA 20 > EMA 50 + Pullback to EMA 20 in BN
c_confluent_long = (df['bn_close'] > df['bn_ema200']) & (df['nf_close'] > df['nf_ema200']) & \
                   (df['bn_ema20'] > df['bn_ema50']) & (df['nf_ema20'] > df['nf_ema50']) & \
                   (df['bn_low'] <= df['bn_ema20'] + 0.25 * df['bn_atr14']) & \
                   (df['bn_close'] >= df['bn_ema20'] - 0.25 * df['bn_atr14']) & \
                   (df['bn_rsi14'] >= 40) & (df['bn_rsi14'] <= 58) & \
                   df['bn_bull_rej']

# TYPE 2: CONFLUENT SHORT SWING TRADE
# Both below 200 EMA + Both EMA 20 < EMA 50 + Bear rally to EMA 20 in BN
c_confluent_short = (df['bn_close'] < df['bn_ema200']) & (df['nf_close'] < df['nf_ema200']) & \
                    (df['bn_ema20'] < df['bn_ema50']) & (df['nf_ema20'] < df['nf_ema50']) & \
                    (df['bn_high'] >= df['bn_ema20'] - 0.25 * df['bn_atr14']) & \
                    (df['bn_close'] <= df['bn_ema20'] + 0.25 * df['bn_atr14']) & \
                    (df['bn_rsi14'] >= 42) & (df['bn_rsi14'] <= 62) & \
                    df['bn_bear_rej']

# TYPE 3: CONFLUENT REVERSAL SWING TRADE (Extreme Dual Rubber-Band Stretch)
c_confluent_reversal_long = (df['bn_dist_200_pct'] <= -4.5) & (df['nf_dist_200_pct'] <= -4.0) & df['bn_bull_rej']
c_confluent_reversal_short = (df['bn_dist_200_pct'] >= 7.5) & (df['nf_dist_200_pct'] >= 6.5) & df['bn_bear_rej']

three_types_results = []
for h in [5, 10]:
    three_types_results.append(evaluate_bn_setup("Type 1: Confluent LONG (Both in Bull Trend + BN 20 EMA Pullback)", c_confluent_long, side='LONG', hold=h))
    three_types_results.append(evaluate_bn_setup("Type 2: Confluent SHORT (Both in Bear Trend + BN 20 EMA Exhaustion)", c_confluent_short, side='SHORT', hold=h))
    three_types_results.append(evaluate_bn_setup("Type 3A: Confluent Bull REVERSAL (Dual Rubber-Band <= -4.5% below 200)", c_confluent_reversal_long, side='LONG', hold=h))
    three_types_results.append(evaluate_bn_setup("Type 3B: Confluent Bear REVERSAL (Dual Rubber-Band >= +7.5% above 200)", c_confluent_reversal_short, side='SHORT', hold=h))

df_final = pd.DataFrame([r for r in three_types_results if r])
print("\n=== MASTER PERFORMANCE TABLE: 3 SWING TYPES WITH NIFTY-BANKNIFTY CONFLUENCE ===")
print(df_final.to_string(index=False))
