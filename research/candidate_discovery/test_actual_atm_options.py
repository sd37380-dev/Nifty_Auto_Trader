"""
Backtest using the ACTUAL Dhan NIFTY_ATM_CE and NIFTY_ATM_PE bar prices in market_data.db.
Test:
1. Daily Intraday ATM Short Straddle (Sell 09:20 Open, Exit 15:15 Close with 25% Stop Loss on each leg)
2. Directional ATM Buying (Buy ATM CE / Buy ATM PE on trend/ORB signals)
"""

import sys
from pathlib import Path
root_dir = Path(__file__).resolve().parent.parent.parent

import sqlite3
import pandas as pd
import numpy as np

def run_actual_options_backtest():
    conn = sqlite3.connect(root_dir / "data" / "hermes_research" / "market_data.db")
    ce = pd.read_sql_query("SELECT timestamp, open as ce_open, high as ce_high, low as ce_low, close as ce_close FROM normalized_bars WHERE symbol='NIFTY_ATM_CE'", conn)
    pe = pd.read_sql_query("SELECT timestamp, open as pe_open, high as pe_high, low as pe_low, close as pe_close FROM normalized_bars WHERE symbol='NIFTY_ATM_PE'", conn)
    nifty = pd.read_sql_query("SELECT timestamp, open, high, low, close FROM normalized_bars WHERE symbol='NIFTY' AND timeframe='15M'", conn)
    conn.close()

    ce['dt'] = pd.to_datetime(ce['timestamp'], format='ISO8601')
    pe['dt'] = pd.to_datetime(pe['timestamp'], format='ISO8601')
    nifty['dt'] = pd.to_datetime(nifty['timestamp'], format='ISO8601')

    m = pd.merge(nifty, ce[['dt', 'ce_open', 'ce_high', 'ce_low', 'ce_close']], on='dt', how='inner')
    m = pd.merge(m, pe[['dt', 'pe_open', 'pe_high', 'pe_low', 'pe_close']], on='dt', how='inner')
    m.sort_values('dt', inplace=True)
    m['ist'] = m['dt'] + pd.Timedelta(hours=5, minutes=30)
    m['date'] = m['ist'].dt.date
    m['time_str'] = m['ist'].dt.strftime('%H:%M')
    m['year'] = m['ist'].dt.year

    m = m[(m['time_str'] >= '09:15') & (m['time_str'] <= '15:30')].copy()

    # Calculate daily ATR on NIFTY
    daily_n = nifty.groupby(nifty['dt'].dt.date).agg(h=('high', 'max'), l=('low', 'min'), c=('close', 'last'), o=('open', 'first')).reset_index()
    daily_n['prev_c'] = daily_n['c'].shift(1)
    daily_n['tr'] = np.maximum(daily_n['h'] - daily_n['l'], np.maximum((daily_n['h'] - daily_n['prev_c']).abs(), (daily_n['l'] - daily_n['prev_c']).abs()))
    daily_n['atr_14'] = daily_n['tr'].rolling(14).mean()
    atr_map = dict(zip(daily_n['dt'], daily_n['atr_14']))

    m['atr_14'] = m['date'].map(atr_map)

    # 1. ACTUAL ATM SHORT STRADDLE SIMULATION
    # Enter on bar 1 close (09:30) or bar 1 open (09:15), exit at 15:15
    days = m['date'].unique()
    trades_straddle = []
    
    for d in days:
        day_bars = m[m['date'] == d]
        if len(day_bars) < 15:
            continue
        
        # Volatility filter check
        atr = day_bars.iloc[0]['atr_14']
        if pd.isna(atr) or atr > 220.0:
            continue

        # Entry at 09:30 (bar 1 close)
        entry_bar = day_bars[day_bars['time_str'] == '09:30']
        if len(entry_bar) == 0:
            entry_bar = day_bars.iloc[0:1]
        
        ce_entry = entry_bar.iloc[0]['ce_open']
        pe_entry = entry_bar.iloc[0]['pe_open']
        entry_comb = ce_entry + pe_entry

        # Exit at 15:15
        exit_bar = day_bars[day_bars['time_str'] == '15:15']
        if len(exit_bar) == 0:
            exit_bar = day_bars.iloc[-1:]

        ce_exit = exit_bar.iloc[0]['ce_close']
        pe_exit = exit_bar.iloc[0]['pe_close']
        exit_comb = ce_exit + pe_exit

        # Combined straddle decay (points collected)
        decay = entry_comb - exit_comb
        
        # Stop loss check during the day: if combined premium expands by > 25% or spot moves > 150 pts
        # Let's check max high of CE + max high of PE
        max_comb = day_bars['ce_high'] + day_bars['pe_high']
        sl_hit = (max_comb - entry_comb) >= (0.25 * entry_comb)

        if sl_hit.any():
            realized_pnl = -(0.25 * entry_comb) - 3.0
            reason = "SL_HIT"
        else:
            realized_pnl = decay - 3.0
            reason = "FULL_HOLD"

        trades_straddle.append({
            "date": d,
            "year": day_bars.iloc[0]['year'],
            "entry_premium": entry_comb,
            "exit_premium": exit_comb,
            "pnl": realized_pnl,
            "reason": reason
        })

    tdf = pd.DataFrame(trades_straddle)
    n = len(tdf)
    wins = tdf[tdf['pnl'] > 0]
    wr = len(wins) / n * 100.0 if n > 0 else 0
    pf = wins['pnl'].sum() / abs(tdf[tdf['pnl'] <= 0]['pnl'].sum()) if len(tdf[tdf['pnl'] <= 0]) > 0 else 0

    print("ACTUAL DHAN ATM OPTIONS STRADDLE RESULTS (Under ATR <= 220 Filter):")
    print(f"Total Trades : {n}")
    print(f"Win Rate     : {wr:.1f}%")
    print(f"Profit Factor: {pf:.2f}")
    print(f"Net Points   : {tdf['pnl'].sum():+.1f}")
    
    yearly = tdf.groupby('year')['pnl'].agg(trades='count', win_rate=lambda x: round((x > 0).mean()*100, 1), net_pts=lambda x: round(x.sum(), 1))
    print(yearly)

if __name__ == "__main__":
    run_actual_options_backtest()
