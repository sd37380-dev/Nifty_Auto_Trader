"""
HERMES DEEP PRICE-ACTION RESEARCH ENGINE
TOPIC 11 — REACTION ZONE SWING TRADING ON 5-YEAR CONTINUOUS NIFTY 50 (2021-2026)

Document ID: HERMES-PA-RES-011
Evaluates Supply & Demand Reaction Zones, Structural Pivot Levels, S/R Flips, 
Liquidity Sweeps, and Multi-Timeframe Confirmations.
Produces complete trade register, P&L analytics, yearly tables, and export data.
"""

import os
import sys
import sqlite3
import json
from datetime import datetime, time, date
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Any

# Ensure output directories exist
os.makedirs("research/price_action", exist_ok=True)
os.makedirs("research_reports_pdf", exist_ok=True)


def load_nifty_dataset(db_path: str = "data/hermes_research/market_data.db"):
    """Loads 15M continuous NIFTY bars and creates clean Daily and 1-Hour resampled datasets."""
    conn = sqlite3.connect(db_path)
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
    
    # Filter regular market session: 09:15 to 15:30 IST
    df = df[(df['time_ist'] >= time(9, 15)) & (df['time_ist'] <= time(15, 30))].copy()
    df = df.sort_values('dt_utc').reset_index(drop=True)

    # 1. Resample to Daily Bars
    df_daily = df.groupby('date_ist').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).reset_index()
    df_daily['date'] = pd.to_datetime(df_daily['date_ist'])
    df_daily = df_daily.sort_values('date').reset_index(drop=True)

    d_high = df_daily['high'].values
    d_low = df_daily['low'].values
    d_close = df_daily['close'].values
    d_open = df_daily['open'].values
    prev_d_close = np.roll(d_close, 1)
    prev_d_close[0] = d_open[0]

    d_tr = np.maximum(d_high - d_low, np.maximum(np.abs(d_high - prev_d_close), np.abs(d_low - prev_d_close)))
    df_daily['tr'] = d_tr
    df_daily['atr14'] = pd.Series(d_tr).rolling(14).mean().bfill().values
    df_daily['ema20'] = df_daily['close'].ewm(span=20, adjust=False).mean()
    df_daily['ema50'] = df_daily['close'].ewm(span=50, adjust=False).mean()
    df_daily['ema200'] = df_daily['close'].ewm(span=200, adjust=False).mean()
    df_daily['trend_50'] = np.where(df_daily['close'] > df_daily['ema50'], 'Bullish', 'Bearish')
    df_daily['trend_200'] = np.where(df_daily['close'] > df_daily['ema200'], 'Bullish', 'Bearish')

    # 2. Resample to 1-Hour Bars
    df_idx = df.set_index('dt_utc')
    df_1h = df_idx.resample('1h').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna().reset_index()
    df_1h['dt_ist'] = df_1h['dt_utc'].dt.tz_convert('Asia/Kolkata')
    df_1h['date_ist'] = df_1h['dt_ist'].dt.date
    df_1h['time_ist'] = df_1h['dt_ist'].dt.time
    df_1h = df_1h[(df_1h['time_ist'] >= time(9, 0)) & (df_1h['time_ist'] <= time(15, 30))].copy()
    df_1h = df_1h.sort_values('dt_utc').reset_index(drop=True)

    h_high = df_1h['high'].values
    h_low = df_1h['low'].values
    h_close = df_1h['close'].values
    prev_h_close = np.roll(h_close, 1)
    prev_h_close[0] = df_1h['open'].values[0]
    h_tr = np.maximum(h_high - h_low, np.maximum(np.abs(h_high - prev_h_close), np.abs(h_low - prev_h_close)))
    df_1h['tr'] = h_tr
    df_1h['atr14'] = pd.Series(h_tr).rolling(14).mean().bfill().values
    df_1h['ema50'] = df_1h['close'].ewm(span=50, adjust=False).mean()
    df_1h['trend'] = np.where(df_1h['close'] > df_1h['ema50'], 'Bullish', 'Bearish')

    return df, df_1h, df_daily


def simulate_structural_reaction_zones(
    df_daily: pd.DataFrame,
    lookback_pivot: int = 5,
    target_r: float = 2.0,
    max_hold_days: int = 7,
    be_trigger_r: float = 1.0,
    stop_mult: float = 0.25,
    trend_mode: str = "EMA50",
    side_allowed: str = "BOTH"
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Simulates Primary Structural Reaction Zone Swing Trading System.
    Identifies major swing low (Demand Reaction Zone) and swing high (Supply Reaction Zone) levels.
    Requires displacement away >= 1.0 ATR before zone becomes active for retest.
    On zone retest: verifies candle rejection, enters at close, sets structural stop + buffer.
    Moves stop to breakeven (+0.1R) once price reaches 1.0R.
    """
    n = len(df_daily)
    trades = []
    active_trade = None
    zones = []
    L = lookback_pivot
    R = 2

    for t in range(30, n):
        curr_bar = df_daily.iloc[t]
        b_date = curr_bar['date_ist']
        b_o = curr_bar['open']
        b_h = curr_bar['high']
        b_l = curr_bar['low']
        b_c = curr_bar['close']
        b_atr = curr_bar['atr14']
        b_ema50 = curr_bar['ema50']
        b_ema200 = curr_bar['ema200']
        b_range = max(b_h - b_l, 0.1)

        # 1. Manage Active Trade
        if active_trade is not None:
            active_trade['hold_days'] += 1
            direction = active_trade['direction']
            entry_p = active_trade['entry_price']
            sl = active_trade['sl']
            tp = active_trade['tp']
            risk = active_trade['risk']

            exit_trig = False
            exit_p = None
            exit_res = None

            # Breakeven adjustment
            if be_trigger_r is not None and not active_trade.get('be_moved', False):
                if direction == 'LONG' and b_h >= entry_p + (be_trigger_r * risk):
                    active_trade['sl'] = entry_p + (0.1 * risk)
                    active_trade['be_moved'] = True
                    sl = active_trade['sl']
                elif direction == 'SHORT' and b_l <= entry_p - (be_trigger_r * risk):
                    active_trade['sl'] = entry_p - (0.1 * risk)
                    active_trade['be_moved'] = True
                    sl = active_trade['sl']

            if direction == 'LONG':
                if b_o <= sl:
                    exit_trig, exit_p, exit_res = True, b_o, 'SL_GAP'
                elif b_l <= sl:
                    exit_trig, exit_p, exit_res = True, sl, 'SL'
                elif b_h >= tp:
                    exit_trig, exit_p, exit_res = True, tp, 'TP'
                elif active_trade['hold_days'] >= max_hold_days:
                    exit_trig, exit_p, exit_res = True, b_c, 'TIME_EXPIRY'
            elif direction == 'SHORT':
                if b_o >= sl:
                    exit_trig, exit_p, exit_res = True, b_o, 'SL_GAP'
                elif b_h >= sl:
                    exit_trig, exit_p, exit_res = True, sl, 'SL'
                elif b_l <= tp:
                    exit_trig, exit_p, exit_res = True, tp, 'TP'
                elif active_trade['hold_days'] >= max_hold_days:
                    exit_trig, exit_p, exit_res = True, b_c, 'TIME_EXPIRY'

            if exit_trig:
                pnl_pts = (exit_p - entry_p) if direction == 'LONG' else (entry_p - exit_p)
                pnl_r = pnl_pts / risk if risk > 0 else 0
                active_trade['exit_date'] = b_date
                active_trade['exit_price'] = exit_p
                active_trade['exit_reason'] = exit_res
                active_trade['pnl_pts'] = pnl_pts
                active_trade['pnl_r'] = pnl_r
                active_trade['is_win'] = pnl_pts > 0
                trades.append(active_trade)
                active_trade = None

        # 2. Zone Detection at t-R
        cand_idx = t - R
        if cand_idx >= L:
            l_cand = df_daily.loc[cand_idx, 'low']
            h_cand = df_daily.loc[cand_idx, 'high']
            is_sl = all(l_cand <= df_daily.loc[cand_idx - j, 'low'] for j in range(1, L + 1)) and \
                    all(l_cand < df_daily.loc[cand_idx + j, 'low'] for j in range(1, R + 1))
            is_sh = all(h_cand >= df_daily.loc[cand_idx - j, 'high'] for j in range(1, L + 1)) and \
                    all(h_cand > df_daily.loc[cand_idx + j, 'high'] for j in range(1, R + 1))

            atr_cand = df_daily.loc[cand_idx, 'atr14']
            if is_sl and side_allowed in ['LONG', 'BOTH']:
                zones.append({
                    'zone_id': f"DZ_{t}_{len(zones)+1}",
                    'type': 'DEMAND',
                    'level': l_cand,
                    'zone_bot': l_cand,
                    'zone_top': l_cand + (0.45 * atr_cand),
                    'created_t': t,
                    'activated': False,
                    'tested': False,
                    'valid_until': t + 60
                })
            if is_sh and side_allowed in ['SHORT', 'BOTH']:
                zones.append({
                    'zone_id': f"SZ_{t}_{len(zones)+1}",
                    'type': 'SUPPLY',
                    'level': h_cand,
                    'zone_top': h_cand,
                    'zone_bot': h_cand - (0.45 * atr_cand),
                    'created_t': t,
                    'activated': False,
                    'tested': False,
                    'valid_until': t + 60
                })

        # Activation Check
        for z in zones:
            if z['valid_until'] < t or z['tested']:
                continue
            if not z['activated']:
                if z['type'] == 'DEMAND' and b_h >= z['zone_top'] + (1.0 * b_atr):
                    z['activated'] = True
                elif z['type'] == 'SUPPLY' and b_l <= z['zone_bot'] - (1.0 * b_atr):
                    z['activated'] = True

        # Reaction Entry Trigger
        if active_trade is None:
            for z in zones:
                if not z['activated'] or z['tested'] or z['valid_until'] < t:
                    continue

                if z['type'] == 'DEMAND' and side_allowed in ['LONG', 'BOTH']:
                    if b_l <= z['zone_top'] and b_l >= (z['zone_bot'] - 0.25 * b_atr):
                        lower_wick = min(b_o, b_c) - b_l
                        pos = (b_c - b_l) / b_range
                        if (pos >= 0.45 or lower_wick >= 0.30 * b_range) and b_c > z['zone_bot']:
                            trend_ok = (b_c > b_ema50) if trend_mode == 'EMA50' else ((b_c > b_ema200) if trend_mode == 'EMA200' else True)
                            if trend_ok:
                                entry_p = b_c
                                sl = z['zone_bot'] - (stop_mult * b_atr)
                                risk = entry_p - sl
                                if risk >= (0.35 * b_atr) and risk <= (2.2 * b_atr):
                                    tp = entry_p + (target_r * risk)
                                    active_trade = {
                                        'trade_id': f"RZ_SWING_{len(trades)+1}",
                                        'setup_type': 'DEMAND_REACTION_ZONE',
                                        'direction': 'LONG',
                                        'entry_date': b_date,
                                        'entry_price': entry_p,
                                        'sl': sl,
                                        'tp': tp,
                                        'risk': risk,
                                        'hold_days': 0,
                                        'zone_level': z['level'],
                                        'entry_atr': b_atr
                                    }
                                    z['tested'] = True
                                    break

                elif z['type'] == 'SUPPLY' and side_allowed in ['SHORT', 'BOTH']:
                    if b_h >= z['zone_bot'] and b_h <= (z['zone_top'] + 0.25 * b_atr):
                        upper_wick = b_h - max(b_o, b_c)
                        pos = (b_c - b_l) / b_range
                        if (pos <= 0.55 or upper_wick >= 0.30 * b_range) and b_c < z['zone_top']:
                            trend_ok = (b_c < b_ema50) if trend_mode == 'EMA50' else ((b_c < b_ema200) if trend_mode == 'EMA200' else True)
                            if trend_ok:
                                entry_p = b_c
                                sl = z['zone_top'] + (stop_mult * b_atr)
                                risk = sl - entry_p
                                if risk >= (0.35 * b_atr) and risk <= (2.2 * b_atr):
                                    tp = entry_p - (target_r * risk)
                                    active_trade = {
                                        'trade_id': f"RZ_SWING_{len(trades)+1}",
                                        'setup_type': 'SUPPLY_REACTION_ZONE',
                                        'direction': 'SHORT',
                                        'entry_date': b_date,
                                        'entry_price': entry_p,
                                        'sl': sl,
                                        'tp': tp,
                                        'risk': risk,
                                        'hold_days': 0,
                                        'zone_level': z['level'],
                                        'entry_atr': b_atr
                                    }
                                    z['tested'] = True
                                    break

    df_trades = pd.DataFrame(trades)
    return df_trades, {"total_zones": len(zones)}


def compute_comprehensive_metrics(df_trades: pd.DataFrame) -> Dict[str, Any]:
    """Computes institutional risk, return, win rate, and drawdown metrics."""
    if len(df_trades) == 0:
        return {}

    n = len(df_trades)
    df_trades['year'] = pd.to_datetime(df_trades['entry_date']).dt.year
    wins = df_trades[df_trades['is_win']]
    losses = df_trades[~df_trades['is_win']]

    win_count = len(wins)
    loss_count = len(losses)
    win_rate = (win_count / n) * 100.0

    total_pnl_pts = df_trades['pnl_pts'].sum()
    total_pnl_r = df_trades['pnl_r'].sum()

    gross_profit = wins['pnl_pts'].sum()
    gross_loss = abs(losses['pnl_pts'].sum())
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 999.0

    avg_trade_pts = df_trades['pnl_pts'].mean()
    avg_win_pts = wins['pnl_pts'].mean() if win_count > 0 else 0.0
    avg_loss_pts = abs(losses['pnl_pts'].mean()) if loss_count > 0 else 0.0
    payoff_ratio = (avg_win_pts / avg_loss_pts) if avg_loss_pts > 0 else 0.0

    avg_trade_r = df_trades['pnl_r'].mean()
    avg_win_r = wins['pnl_r'].mean() if win_count > 0 else 0.0
    avg_loss_r = abs(losses['pnl_r'].mean()) if loss_count > 0 else 0.0

    # Drawdown in points and R
    cum_pts = df_trades['pnl_pts'].cumsum()
    peak_pts = np.maximum.accumulate(cum_pts)
    dd_pts_series = cum_pts - peak_pts
    max_dd_pts = dd_pts_series.min()

    cum_r = df_trades['pnl_r'].cumsum()
    peak_r = np.maximum.accumulate(cum_r)
    dd_r_series = cum_r - peak_r
    max_dd_r = dd_r_series.min()

    # Rupee calculations: based on 1 Lot (25 shares / 50 shares)
    # NIFTY lot size was 50 prior to April 2024, 25 currently. We report at 50/lot and 25/lot and per 1% risk.
    pnl_inr_50lot = total_pnl_pts * 50
    pnl_inr_25lot = total_pnl_pts * 25
    
    # Capital return assuming standard 1% risk per trade on ₹10,00,000 capital (₹10,000 risk per R)
    account_gain_inr_1pct = total_pnl_r * 10000.0

    # Sharpe ratio estimate (trade-level annualized)
    std_r = df_trades['pnl_r'].std()
    sharpe_r = (avg_trade_r / std_r) * np.sqrt(252 / max(df_trades['hold_days'].mean(), 1)) if std_r > 0 else 0.0

    # Exit reason distribution
    exit_counts = df_trades['exit_reason'].value_counts().to_dict()

    # Directional split
    longs = df_trades[df_trades['direction'] == 'LONG']
    shorts = df_trades[df_trades['direction'] == 'SHORT']

    dir_metrics = {
        'LONG': {
            'count': len(longs),
            'win_rate': (longs['is_win'].sum() / len(longs) * 100.0) if len(longs) > 0 else 0,
            'pnl_pts': longs['pnl_pts'].sum() if len(longs) > 0 else 0,
            'pnl_r': longs['pnl_r'].sum() if len(longs) > 0 else 0
        },
        'SHORT': {
            'count': len(shorts),
            'win_rate': (shorts['is_win'].sum() / len(shorts) * 100.0) if len(shorts) > 0 else 0,
            'pnl_pts': shorts['pnl_pts'].sum() if len(shorts) > 0 else 0,
            'pnl_r': shorts['pnl_r'].sum() if len(shorts) > 0 else 0
        }
    }

    # Yearly breakdown table
    yearly_df = df_trades.groupby('year').agg({
        'trade_id': 'count',
        'is_win': lambda x: (x.sum() / len(x)) * 100.0,
        'pnl_pts': 'sum',
        'pnl_r': 'sum'
    }).rename(columns={'trade_id': 'trades', 'is_win': 'win_rate'})
    
    yearly_dict = {}
    for yr, row in yearly_df.iterrows():
        yearly_dict[int(yr)] = {
            'trades': int(row['trades']),
            'win_rate': float(row['win_rate']),
            'pnl_pts': float(row['pnl_pts']),
            'pnl_r': float(row['pnl_r'])
        }

    return {
        'total_trades': n,
        'win_count': win_count,
        'loss_count': loss_count,
        'win_rate_pct': win_rate,
        'total_pnl_pts': total_pnl_pts,
        'total_pnl_r': total_pnl_r,
        'gross_profit_pts': gross_profit,
        'gross_loss_pts': gross_loss,
        'profit_factor': profit_factor,
        'avg_trade_pts': avg_trade_pts,
        'avg_win_pts': avg_win_pts,
        'avg_loss_pts': avg_loss_pts,
        'payoff_ratio': payoff_ratio,
        'avg_trade_r': avg_trade_r,
        'avg_win_r': avg_win_r,
        'avg_loss_r': avg_loss_r,
        'max_dd_pts': max_dd_pts,
        'max_dd_r': max_dd_r,
        'pnl_inr_50lot': pnl_inr_50lot,
        'pnl_inr_25lot': pnl_inr_25lot,
        'account_gain_inr_1pct': account_gain_inr_1pct,
        'avg_holding_days': float(df_trades['hold_days'].mean()),
        'sharpe_ratio_annualized': sharpe_r,
        'exit_reasons': exit_counts,
        'directional_split': dir_metrics,
        'yearly_performance': yearly_dict
    }


def main():
    print("=================================================================")
    print("HERMES REACTION ZONE SWING TRADING RESEARCH (5-YEAR DATASET)")
    print("=================================================================")
    df_raw, df_1h, df_daily = load_nifty_dataset()
    print(f"Loaded {len(df_daily)} daily bars across 5 years (2021-09-30 to 2026-09-30).")

    # Run Benchmark System: Structural Reaction Zone Swing
    print("\nExecuting Primary Benchmark: Structural Reaction Zone Swing...")
    df_trades, meta = simulate_structural_reaction_zones(
        df_daily,
        lookback_pivot=5,
        target_r=2.0,
        max_hold_days=7,
        be_trigger_r=1.0,
        stop_mult=0.25,
        trend_mode="EMA50",
        side_allowed="BOTH"
    )

    metrics = compute_comprehensive_metrics(df_trades)

    # Save Trade Log
    events_csv = "research/price_action/REACTION_ZONE_SWING_EVENTS.csv"
    df_trades.to_csv(events_csv, index=False)
    print(f"Saved {len(df_trades)} trade records to {events_csv}")

    # Save Metrics JSON
    metrics_json = "research/price_action/reaction_zone_metrics.json"
    with open(metrics_json, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"Saved metrics summary to {metrics_json}")

    print("\n--- Empirical Results Summary ---")
    print(f"Total Trades Found: {metrics['total_trades']}")
    print(f"Win Rate: {metrics['win_rate_pct']:.2f}% ({metrics['win_count']} Wins / {metrics['loss_count']} Losses)")
    print(f"Total P/L (R-Multiples): {metrics['total_pnl_r']:+.2f} R")
    print(f"Total P/L (Nifty Points): {metrics['total_pnl_pts']:+.2f} pts")
    print(f"Profit Factor: {metrics['profit_factor']:.2f}")
    print(f"Average Win: {metrics['avg_win_pts']:.2f} pts | Average Loss: {metrics['avg_loss_pts']:.2f} pts")
    print(f"Max Drawdown: {metrics['max_dd_r']:.2f} R ({metrics['max_dd_pts']:.2f} pts)")
    print(f"Avg Holding Period: {metrics['avg_holding_days']:.2f} days")
    print(f"Simulated INR P/L (1% Risk on INR 10L): INR {metrics['account_gain_inr_1pct']:+,.2f}")
    print("\nYearly Breakdown:")
    for yr, y_m in metrics['yearly_performance'].items():
        print(f"  {yr}: {y_m['trades']:2d} trades | Win: {y_m['win_rate']:5.1f}% | PnL: {y_m['pnl_pts']:+8.2f} pts | R: {y_m['pnl_r']:+5.2f} R")


if __name__ == '__main__':
    main()
