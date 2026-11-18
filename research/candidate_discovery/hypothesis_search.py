"""
Hermes Research Engine: Multi-Hypothesis Quantitative Search.
Strictly executed on Discovery / Train Period: 2021-09-30 to 2024-12-31.
Tests 12 distinct quantitative hypotheses across price structure, time, volatility, volume, and derivatives.
Rules:
- Strict no-lookahead-bias execution.
- Deterministic entries & exits.
- Standard 3.0 points friction included.
"""

import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Any


def load_dataset_split():
    conn = sqlite3.connect(root_dir / "data" / "hermes_research" / "market_data.db")
    query = """
        SELECT timestamp, open, high, low, close, volume, open_interest
        FROM normalized_bars
        WHERE symbol = 'NIFTY' AND timeframe = '15M'
        ORDER BY timestamp ASC
    """
    df = pd.read_sql_query(query, conn)
    
    # Load ATM options if needed
    ce_df = pd.read_sql_query("SELECT timestamp, open as ce_open, high as ce_high, low as ce_low, close as ce_close FROM normalized_bars WHERE symbol='NIFTY_ATM_CE' ORDER BY timestamp ASC", conn)
    pe_df = pd.read_sql_query("SELECT timestamp, open as pe_open, high as pe_high, low as pe_low, close as pe_close FROM normalized_bars WHERE symbol='NIFTY_ATM_PE' ORDER BY timestamp ASC", conn)
    conn.close()

    df['dt'] = pd.to_datetime(df['timestamp'], format='ISO8601')
    df.drop_duplicates(subset=['dt'], inplace=True)
    df.set_index('dt', inplace=True)
    df.sort_index(inplace=True)

    df['ist'] = df.index + pd.Timedelta(hours=5, minutes=30)
    df['date'] = df['ist'].dt.date
    df['time_str'] = df['ist'].dt.strftime('%H:%M')
    df['year'] = df['ist'].dt.year

    # Regular market hours
    df = df[(df['time_str'] >= '09:15') & (df['time_str'] <= '15:30')].copy()

    # Technical features
    c = df['close']
    h = df['high']
    l = df['low']
    v = df['volume']

    df['ema_9'] = c.ewm(span=9, adjust=False).mean()
    df['ema_14'] = c.ewm(span=14, adjust=False).mean()
    df['ema_20'] = c.ewm(span=20, adjust=False).mean()
    df['ema_50'] = c.ewm(span=50, adjust=False).mean()
    df['ema_200'] = c.ewm(span=200, adjust=False).mean()

    # RSI 14
    delta = c.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df['rsi_14'] = 100 - (100 / (1 + rs))

    # ATR 14
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    df['atr_14'] = tr.rolling(14).mean()

    # Session VWAP & Stdev
    tp = (h + l + c) / 3.0
    pv = tp * v
    df['cum_pv'] = pv.groupby(df['date']).cumsum()
    df['cum_vol'] = v.groupby(df['date']).cumsum()
    df['vwap'] = np.where(df['cum_vol'] > 0, df['cum_pv'] / df['cum_vol'], df['close'])
    
    tp_diff_sq = (tp - df['vwap']) ** 2
    df['cum_var'] = (tp_diff_sq * v).groupby(df['date']).cumsum()
    df['vwap_std'] = np.sqrt(np.where(df['cum_vol'] > 0, np.maximum(0.0, df['cum_var'] / df['cum_vol']), 1.0))
    df['vwap_upper_2'] = df['vwap'] + (2.0 * df['vwap_std'])
    df['vwap_lower_2'] = df['vwap'] - (2.0 * df['vwap_std'])

    # Volume ratio
    df['vol_sma_20'] = v.rolling(20).mean()
    df['vol_ratio'] = df['volume'] / df['vol_sma_20'].replace(0, 1)

    # Daily Pivots (Classic + CPR)
    daily = df.groupby('date').agg(day_h=('high', 'max'), day_l=('low', 'min'), day_c=('close', 'last'), day_o=('open', 'first'))
    daily_prev = daily.shift(1)
    
    p = (daily_prev['day_h'] + daily_prev['day_l'] + daily_prev['day_c']) / 3.0
    r1 = (2.0 * p) - daily_prev['day_l']
    s1 = (2.0 * p) - daily_prev['day_h']
    r2 = p + (daily_prev['day_h'] - daily_prev['day_l'])
    s2 = p - (daily_prev['day_h'] - daily_prev['day_l'])
    bc = (daily_prev['day_h'] + daily_prev['day_l']) / 2.0
    tc = (2.0 * p) - bc
    cpr_top = np.maximum(tc, bc)
    cpr_bot = np.minimum(tc, bc)

    pivots_df = pd.DataFrame({
        'pdh': daily_prev['day_h'], 'pdl': daily_prev['day_l'], 'pdc': daily_prev['day_c'], 'pdo': daily_prev['day_o'],
        'pivot': p, 'r1': r1, 's1': s1, 'r2': r2, 's2': s2,
        'cpr_top': cpr_top, 'cpr_bot': cpr_bot,
    }, index=daily.index)

    df = df.join(pivots_df, on='date')

    # Merge Straddle data if available
    ce_df.drop_duplicates(subset=['timestamp'], inplace=True)
    pe_df.drop_duplicates(subset=['timestamp'], inplace=True)
    df_opt = pd.merge(df.reset_index(), ce_df, on='timestamp', how='left')
    df_opt = pd.merge(df_opt, pe_df, on='timestamp', how='left')
    df_opt.set_index('dt', inplace=True)

    # Strict Dataset Split (Section 9)
    # Train / Discovery: 2021 to 2024
    # Validation: 2025
    # Out of Sample: 2026
    train_df = df_opt[df_opt['year'] <= 2024].copy()
    val_df = df_opt[df_opt['year'] == 2025].copy()
    oos_df = df_opt[df_opt['year'] >= 2026].copy()

    return train_df, val_df, oos_df


def run_backtest_simulation(
    df: pd.DataFrame,
    long_condition: pd.Series,
    short_condition: pd.Series,
    hypothesis_id: str,
    hypothesis_name: str,
    sl_points: float = 30.0,
    tp_points: float = 60.0,
    cost_points: float = 3.0,
    entry_start_time: str = '09:30',
    entry_end_time: str = '13:30',
) -> Dict[str, Any]:
    """
    Deterministic bar-by-bar backtest simulation.
    Zero look-ahead bias: Entry happens on bar close; fills at exact close;
    evaluates subsequent bars sequentially for SL, TP, or EOD (15:15 IST).
    """
    days = df['date'].unique()
    trades = []

    for d in days:
        day_df = df[df['date'] == d]
        if len(day_df) < 8:
            continue

        in_trade = False
        direction = None
        entry_price = 0.0
        sl_price = 0.0
        tp_price = 0.0

        for idx, row in day_df.iterrows():
            t = row['time_str']
            c = row['close']
            h = row['high']
            l = row['low']

            if not in_trade:
                if entry_start_time <= t <= entry_end_time:
                    if long_condition.loc[idx]:
                        in_trade = True
                        direction = "LONG"
                        entry_price = c
                        sl_price = entry_price - sl_points
                        tp_price = entry_price + tp_points
                    elif short_condition.loc[idx]:
                        in_trade = True
                        direction = "SHORT"
                        entry_price = c
                        sl_price = entry_price + sl_points
                        tp_price = entry_price - tp_points
            else:
                exit_price = None
                reason = None

                if direction == "LONG":
                    if l <= sl_price:
                        exit_price = sl_price
                        reason = "SL"
                    elif h >= tp_price:
                        exit_price = tp_price
                        reason = "TP"
                    elif t >= '15:15':
                        exit_price = c
                        reason = "EOD"
                else:
                    if h >= sl_price:
                        exit_price = sl_price
                        reason = "SL"
                    elif l <= tp_price:
                        exit_price = tp_price
                        reason = "TP"
                    elif t >= '15:15':
                        exit_price = c
                        reason = "EOD"

                if exit_price is not None:
                    pnl = (exit_price - entry_price) if direction == "LONG" else (entry_price - exit_price)
                    pnl -= cost_points
                    trades.append({
                        "date": d,
                        "year": row['year'],
                        "direction": direction,
                        "entry": entry_price,
                        "exit": exit_price,
                        "pnl": pnl,
                        "reason": reason,
                    })
                    break  # Max 1 trade per day for strict discipline

    tdf = pd.DataFrame(trades)
    if len(tdf) == 0:
        return {
            "hypothesis_id": hypothesis_id,
            "name": hypothesis_name,
            "trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "net_pts": 0.0,
            "expectancy": 0.0,
            "max_dd": 0.0,
            "survives_60": False,
        }

    wins = tdf[tdf['pnl'] > 0]
    losses = tdf[tdf['pnl'] <= 0]
    wr = len(wins) / len(tdf) * 100.0

    tot_p = wins['pnl'].sum() if len(wins) > 0 else 0.0
    tot_l = abs(losses['pnl'].sum()) if len(losses) > 0 else 1.0
    pf = tot_p / max(1.0, tot_l)
    net_pts = tdf['pnl'].sum()
    expectancy = tdf['pnl'].mean()

    tdf['cum'] = tdf['pnl'].cumsum()
    max_dd = (tdf['cum'].cummax() - tdf['cum']).max()

    # 95% Confidence Interval for Win Rate (Wilson Score)
    n = len(tdf)
    p_hat = len(wins) / n
    z = 1.96  # 95% confidence
    denom = 1 + (z**2 / n)
    center = (p_hat + (z**2 / (2 * n))) / denom
    margin = (z * np.sqrt((p_hat * (1 - p_hat) / n) + (z**2 / (4 * n**2)))) / denom
    ci_lower = max(0.0, round((center - margin) * 100.0, 1))
    ci_upper = min(100.0, round((center + margin) * 100.0, 1))

    yearly = tdf.groupby('year')['pnl'].agg(
        trades='count',
        win_rate=lambda x: round((x > 0).mean() * 100.0, 1),
        net_pts=lambda x: round(x.sum(), 1)
    ).to_dict(orient='index')

    survives = (wr >= 60.0) and (n >= 50) and (pf > 1.0) and (expectancy > 0)

    return {
        "hypothesis_id": hypothesis_id,
        "name": hypothesis_name,
        "trades": len(tdf),
        "win_rate": round(wr, 1),
        "ci_95": f"[{ci_lower}% - {ci_upper}%]",
        "profit_factor": round(pf, 2),
        "net_pts": round(net_pts, 1),
        "expectancy": round(expectancy, 1),
        "max_dd": round(max_dd, 1),
        "survives_60": survives,
        "yearly": yearly,
        "trades_df": tdf,
    }


def execute_discovery():
    print("=" * 80)
    print("      HERMES RESEARCH ENGINE — SYSTEMATIC HYPOTHESIS DISCOVERY      ")
    print("=" * 80)
    print("Dataset Split: Discovery / Train Period = 2021-09-30 to 2024-12-31")
    print("Friction Assumption: 3.0 NIFTY Points per trade (Slippage + Brokerage)")
    print("-" * 80)

    train_df, val_df, oos_df = load_dataset_split()
    print(f"Loaded Train Dataset: {len(train_df):,} bars ({train_df['date'].nunique()} sessions)")

    hypotheses_results = []

    # -------------------------------------------------------------------------
    # H1: 09:45 Opening Range Breakout (ORB) + 200 EMA Trend Alignment (1:2 R:R)
    # -------------------------------------------------------------------------
    f30_h = train_df.groupby('date')['high'].transform(lambda x: x.iloc[:2].max() if len(x) >= 2 else np.nan)
    f30_l = train_df.groupby('date')['low'].transform(lambda x: x.iloc[:2].min() if len(x) >= 2 else np.nan)
    h1_l = (train_df['close'] > f30_h) & (train_df['close'].shift(1) <= f30_h) & (train_df['close'] > train_df['ema_200']) & ('09:45' <= train_df['time_str']) & (train_df['time_str'] <= '11:15')
    h1_s = (train_df['close'] < f30_l) & (train_df['close'].shift(1) >= f30_l) & (train_df['close'] < train_df['ema_200']) & ('09:45' <= train_df['time_str']) & (train_df['time_str'] <= '11:15')
    r1 = run_backtest_simulation(train_df, h1_l, h1_s, "H1_ORB_TREND", "09:45 ORB + 200 EMA Trend (1:2 R:R)", sl_points=35.0, tp_points=70.0)
    hypotheses_results.append(r1)

    # -------------------------------------------------------------------------
    # H2: Liquidity Sweep / PDH-PDL Fakeout Reversal (Turtle Soup)
    # -------------------------------------------------------------------------
    h2_l = (train_df['low'] < train_df['pdl']) & (train_df['close'] > train_df['pdl']) & (train_df['pdl'] - train_df['low'] <= 40.0) & (train_df['close'] > train_df['open'])
    h2_s = (train_df['high'] > train_df['pdh']) & (train_df['close'] < train_df['pdh']) & (train_df['high'] - train_df['pdh'] <= 40.0) & (train_df['close'] < train_df['open'])
    r2 = run_backtest_simulation(train_df, h2_l, h2_s, "H2_PDH_PDL_SWEEP", "PDH/PDL Liquidity Sweep Reversal", sl_points=25.0, tp_points=35.0)
    hypotheses_results.append(r2)

    # -------------------------------------------------------------------------
    # H3: Overnight Gap Exhaustion (Gap Fade to Previous Close)
    # -------------------------------------------------------------------------
    gap_up = (train_df['open'] - train_df['pdc']) / train_df['pdc'] * 100.0 >= 0.35
    gap_down = (train_df['open'] - train_df['pdc']) / train_df['pdc'] * 100.0 <= -0.35
    h3_l = gap_down & (train_df['time_str'] == '09:30') & (train_df['close'] > train_df['open'])
    h3_s = gap_up & (train_df['time_str'] == '09:30') & (train_df['close'] < train_df['open'])
    r3 = run_backtest_simulation(train_df, h3_l, h3_s, "H3_GAP_FADE", "Overnight Gap Exhaustion Fade", sl_points=28.0, tp_points=42.0)
    hypotheses_results.append(r3)

    # -------------------------------------------------------------------------
    # H4: Extreme Mean Reversion (VWAP 2.0 Sigma Rejection to VWAP)
    # -------------------------------------------------------------------------
    h4_l = (train_df['low'] < train_df['vwap_lower_2']) & (train_df['close'] > train_df['open']) & (train_df['vwap'] - train_df['close'] >= 45.0)
    h4_s = (train_df['high'] > train_df['vwap_upper_2']) & (train_df['close'] < train_df['open']) & (train_df['close'] - train_df['vwap'] >= 45.0)
    r4 = run_backtest_simulation(train_df, h4_l, h4_s, "H4_VWAP_MEAN_REV", "VWAP 2.0 Sigma Extreme Fade", sl_points=25.0, tp_points=40.0)
    hypotheses_results.append(r4)

    # -------------------------------------------------------------------------
    # H5: 20 EMA Pullback Continuation (with 200 EMA Macro Alignment)
    # -------------------------------------------------------------------------
    h5_l = (train_df['close'] > train_df['ema_200']) & (train_df['low'] <= train_df['ema_20']) & (train_df['close'] > train_df['ema_20']) & (train_df['close'] > train_df['open']) & (train_df['rsi_14'] > 50)
    h5_s = (train_df['close'] < train_df['ema_200']) & (train_df['high'] >= train_df['ema_20']) & (train_df['close'] < train_df['ema_20']) & (train_df['close'] < train_df['open']) & (train_df['rsi_14'] < 50)
    r5 = run_backtest_simulation(train_df, h5_l, h5_s, "H5_EMA_PULLBACK", "20 EMA Trend Pullback Continuation", sl_points=30.0, tp_points=60.0)
    hypotheses_results.append(r5)

    # -------------------------------------------------------------------------
    # H6: Volatility Compression Breakout (NR4 + Volume Expansion)
    # -------------------------------------------------------------------------
    bar_rng = train_df['high'] - train_df['low']
    is_nr4 = (bar_rng < bar_rng.shift(1)) & (bar_rng < bar_rng.shift(2)) & (bar_rng < bar_rng.shift(3))
    h6_l = is_nr4.shift(1) & (train_df['close'] > train_df['high'].shift(1)) & (train_df['vol_ratio'] > 1.3) & (train_df['close'] > train_df['ema_50'])
    h6_s = is_nr4.shift(1) & (train_df['close'] < train_df['low'].shift(1)) & (train_df['vol_ratio'] > 1.3) & (train_df['close'] < train_df['ema_50'])
    r6 = run_backtest_simulation(train_df, h6_l, h6_s, "H6_VOL_EXPANSION_BREAK", "NR4 Volatility Compression Breakout", sl_points=28.0, tp_points=56.0)
    hypotheses_results.append(r6)

    # -------------------------------------------------------------------------
    # H7: Quick Scalp Momentum (1:1 R:R, SL: 24, TP: 24)
    # -------------------------------------------------------------------------
    h7_l = (train_df['close'] > train_df['high'].shift(1)) & (train_df['close'] > train_df['ema_20']) & (train_df['close'] > train_df['vwap']) & (train_df['vol_ratio'] > 1.2)
    h7_s = (train_df['close'] < train_df['low'].shift(1)) & (train_df['close'] < train_df['ema_20']) & (train_df['close'] < train_df['vwap']) & (train_df['vol_ratio'] > 1.2)
    r7 = run_backtest_simulation(train_df, h7_l, h7_s, "H7_QUICK_SCALP_MOMENTUM", "Quick Momentum Scalp (1:1 R:R)", sl_points=24.0, tp_points=24.0)
    hypotheses_results.append(r7)

    # -------------------------------------------------------------------------
    # H8: Pivot/CPR Support-Resistance + EMA 14 Reclaim (1:3 R:R)
    # -------------------------------------------------------------------------
    s_levels = [train_df['s1'], train_df['s2'], train_df['cpr_bot']]
    r_levels = [train_df['r1'], train_df['r2'], train_df['cpr_top']]
    conds_s = [(abs(train_df['low'] - s) <= 20.0) | ((train_df['low'] < s) & (train_df['close'] > s)) for s in s_levels]
    near_s = conds_s[0] | conds_s[1] | conds_s[2]
    conds_r = [(abs(train_df['high'] - r) <= 20.0) | ((train_df['high'] > r) & (train_df['close'] < r)) for r in r_levels]
    near_r = conds_r[0] | conds_r[1] | conds_r[2]
    h8_l = near_s & (train_df['close'] > train_df['ema_14']) & (train_df['close'] > train_df['open'])
    h8_s = near_r & (train_df['close'] < train_df['ema_14']) & (train_df['close'] < train_df['open'])
    r8 = run_backtest_simulation(train_df, h8_l, h8_s, "H8_CPR_REBOUND_EMA14", "CPR/Pivot Support-Resistance + EMA 14", sl_points=28.0, tp_points=84.0)
    hypotheses_results.append(r8)

    # -------------------------------------------------------------------------
    # H9: Afternoon Institutional VWAP Breakout (13:30 to 14:30 IST)
    # -------------------------------------------------------------------------
    h9_l = ('13:30' <= train_df['time_str']) & (train_df['time_str'] <= '14:30') & (train_df['close'] > train_df['vwap']) & (train_df['close'].shift(1) <= train_df['vwap'].shift(1)) & (train_df['vol_ratio'] > 1.3)
    h9_s = ('13:30' <= train_df['time_str']) & (train_df['time_str'] <= '14:30') & (train_df['close'] < train_df['vwap']) & (train_df['close'].shift(1) >= train_df['vwap'].shift(1)) & (train_df['vol_ratio'] > 1.3)
    r9 = run_backtest_simulation(train_df, h9_l, h9_s, "H9_AFTERNOON_VWAP_BREAK", "Afternoon Institutional VWAP Breakout", sl_points=25.0, tp_points=50.0)
    hypotheses_results.append(r9)

    # -------------------------------------------------------------------------
    # H10: RSI Extreme Divergence at Bollinger Extremes
    # -------------------------------------------------------------------------
    h10_l = (train_df['rsi_14'] < 28) & (train_df['low'] < train_df['vwap_lower_2']) & (train_df['close'] > train_df['open'])
    h10_s = (train_df['rsi_14'] > 72) & (train_df['high'] > train_df['vwap_upper_2']) & (train_df['close'] < train_df['open'])
    r10 = run_backtest_simulation(train_df, h10_l, h10_s, "H10_RSI_BOLLINGER_EXTREME", "RSI Extreme + Bollinger 2.0 Reversal", sl_points=25.0, tp_points=35.0)
    hypotheses_results.append(r10)

    # -------------------------------------------------------------------------
    # H11: Pure 1:1 Inverted Risk Scalp (SL: 35, TP: 20) -> Testing if high WR is achievable
    # -------------------------------------------------------------------------
    h11_l = (train_df['close'] > train_df['ema_9']) & (train_df['ema_9'] > train_df['ema_20']) & (train_df['vol_ratio'] > 1.1)
    h11_s = (train_df['close'] < train_df['ema_9']) & (train_df['ema_9'] < train_df['ema_20']) & (train_df['vol_ratio'] > 1.1)
    r11 = run_backtest_simulation(train_df, h11_l, h11_s, "H11_INVERTED_SCALP", "Inverted Risk Scalp (SL: 35, TP: 20)", sl_points=35.0, tp_points=20.0)
    hypotheses_results.append(r11)

    # -------------------------------------------------------------------------
    # H12: Defined-Risk Theta Option Spread (150 pt OTM Credit Spreads)
    # -------------------------------------------------------------------------
    # Simulate on daily sessions of Train period
    days_train = train_df['date'].unique()
    trades_theta = []
    for d in days_train:
        day_df = train_df[train_df['date'] == d]
        if len(day_df) < 15:
            continue
        d_open = day_df.iloc[0]['open']
        d_high = day_df['high'].max()
        d_low = day_df['low'].min()
        put_strike = d_open - 150.0
        call_strike = d_open + 150.0
        breached_high = d_high >= (call_strike + 30.0)
        breached_low = d_low <= (put_strike - 30.0)
        year = day_df.iloc[0]['year']
        if not breached_high and not breached_low:
            trades_theta.append({"date": d, "year": year, "pnl": 32.0, "reason": "THETA_WIN"})
        else:
            trades_theta.append({"date": d, "year": year, "pnl": -60.0, "reason": "BREACH_LOSS"})

    tdf_theta = pd.DataFrame(trades_theta)
    wins_th = tdf_theta[tdf_theta['pnl'] > 0]
    wr_th = len(wins_th) / len(tdf_theta) * 100.0 if len(tdf_theta) > 0 else 0.0
    tot_p_th = wins_th['pnl'].sum() if len(wins_th) > 0 else 0.0
    tot_l_th = abs(tdf_theta[tdf_theta['pnl'] <= 0]['pnl'].sum()) if len(tdf_theta[tdf_theta['pnl'] <= 0]) > 0 else 1.0
    pf_th = tot_p_th / max(1.0, tot_l_th)
    
    n_th = len(tdf_theta)
    p_h_th = len(wins_th) / n_th
    z = 1.96
    denom_th = 1 + (z**2 / n_th)
    center_th = (p_h_th + (z**2 / (2 * n_th))) / denom_th
    margin_th = (z * np.sqrt((p_h_th * (1 - p_h_th) / n_th) + (z**2 / (4 * n_th**2)))) / denom_th
    ci_th = f"[{max(0.0, round((center_th - margin_th)*100, 1))}% - {min(100.0, round((center_th + margin_th)*100, 1))}%]"

    yearly_th = tdf_theta.groupby('year')['pnl'].agg(
        trades='count',
        win_rate=lambda x: round((x > 0).mean() * 100.0, 1),
        net_pts=lambda x: round(x.sum(), 1)
    ).to_dict(orient='index')

    r12 = {
        "hypothesis_id": "H12_THETA_CREDIT_SPREAD",
        "name": "Defined-Risk Theta Option Spread (150 pt OTM)",
        "trades": n_th,
        "win_rate": round(wr_th, 1),
        "ci_95": ci_th,
        "profit_factor": round(pf_th, 2),
        "net_pts": round(tdf_theta['pnl'].sum(), 1),
        "expectancy": round(tdf_theta['pnl'].mean(), 1),
        "max_dd": round((tdf_theta['pnl'].cumsum().cummax() - tdf_theta['pnl'].cumsum()).max(), 1),
        "survives_60": (wr_th >= 60.0) and (n_th >= 50) and (pf_th > 1.0),
        "yearly": yearly_th,
        "trades_df": tdf_theta,
    }
    hypotheses_results.append(r12)

    # -------------------------------------------------------------------------
    # Print Discovery Tournament Results
    # -------------------------------------------------------------------------
    print("\n" + "=" * 95)
    print(f"{'Hypothesis ID & Name':<46} | {'Trades':<6} | {'Win %':<6} | {'95% CI':<15} | {'PF':<5} | {'Net Pts':<9} | {'Survives 60%':<12}")
    print("=" * 95)
    
    surviving_candidates = []
    for r in hypotheses_results:
        surv_str = "[PASS]" if r["survives_60"] else "[FAIL]"
        ci_str = r.get("ci_95", "N/A")
        print(f"{r['name']:<46} | {r['trades']:<6} | {r['win_rate']:>5.1f}% | {ci_str:<15} | {r['profit_factor']:>5.2f} | {r['net_pts']:>+8.1f} | {surv_str:<12}")
        if r["survives_60"]:
            surviving_candidates.append(r)

    print("-" * 95)
    print(f"\n[+] Total Hypotheses Tested on Discovery Dataset: {len(hypotheses_results)}")
    print(f"[+] Hypotheses Failing 60% Discovery Gate    : {len(hypotheses_results) - len(surviving_candidates)}")
    print(f"[+] Hypotheses Surviving Discovery Gate (>=60%): {len(surviving_candidates)}")

    for sc in surviving_candidates:
        print(f"\n---> SURVIVING CANDIDATE: {sc['name']} (WR: {sc['win_rate']}%, PF: {sc['profit_factor']}, Net: {sc['net_pts']:+,} pts)")
        print("     Yearly Discovery Performance:")
        for yr, s in sc['yearly'].items():
            print(f"       Year {yr}: {s['trades']:3d} trades | Win Rate: {s['win_rate']:5.1f}% | Net Points: {s['net_pts']:+8.1f} pts")

    return surviving_candidates, val_df, oos_df


if __name__ == "__main__":
    execute_discovery()
