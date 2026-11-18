"""
Backtest Option Selling (Theta Decay) vs Option Buying directly on Real Option Contract Premiums.
"""

import sqlite3
import pandas as pd
import numpy as np


def load_merged_data():
    conn = sqlite3.connect("data/hermes_research/market_data.db")
    spot_df = pd.read_sql_query(
        "SELECT timestamp, open as spot_open, high as spot_high, low as spot_low, close as spot_close, volume as spot_vol FROM normalized_bars WHERE symbol='NIFTY' AND timeframe='15M' ORDER BY timestamp ASC",
        conn
    )
    ce_df = pd.read_sql_query(
        "SELECT timestamp, open as ce_open, high as ce_high, low as ce_low, close as ce_close, volume as ce_vol, open_interest as ce_oi FROM normalized_bars WHERE symbol='NIFTY_ATM_CE' ORDER BY timestamp ASC",
        conn
    )
    pe_df = pd.read_sql_query(
        "SELECT timestamp, open as pe_open, high as pe_high, low as pe_low, close as pe_close, volume as pe_vol, open_interest as pe_oi FROM normalized_bars WHERE symbol='NIFTY_ATM_PE' ORDER BY timestamp ASC",
        conn
    )
    conn.close()

    spot_df.drop_duplicates(subset=['timestamp'], inplace=True)
    ce_df.drop_duplicates(subset=['timestamp'], inplace=True)
    pe_df.drop_duplicates(subset=['timestamp'], inplace=True)

    m = pd.merge(spot_df, ce_df, on='timestamp', how='inner')
    m = pd.merge(m, pe_df, on='timestamp', how='inner')

    m['dt'] = pd.to_datetime(m['timestamp'], format='ISO8601')
    m.set_index('dt', inplace=True)
    m.sort_index(inplace=True)

    m['ist'] = m.index + pd.Timedelta(hours=5, minutes=30)
    m['date'] = m['ist'].dt.date
    m['time_str'] = m['ist'].dt.strftime('%H:%M')
    m['year'] = m['ist'].dt.year

    m = m[(m['time_str'] >= '09:15') & (m['time_str'] <= '15:30')].copy()

    # Session Straddle Price: ATM CE Close + ATM PE Close
    m['straddle_close'] = m['ce_close'] + m['pe_close']
    m['straddle_open'] = m['ce_open'] + m['pe_open']

    # Spot Pivots
    daily = m.groupby('date').agg(day_h=('spot_high', 'max'), day_l=('spot_low', 'min'), day_c=('spot_close', 'last'))
    daily_prev = daily.shift(1)
    p = (daily_prev['day_h'] + daily_prev['day_l'] + daily_prev['day_c']) / 3.0
    r1 = (2.0 * p) - daily_prev['day_l']
    s1 = (2.0 * p) - daily_prev['day_h']

    pivots_df = pd.DataFrame({'pivot': p, 'r1': r1, 's1': s1}, index=daily.index)
    m = m.join(pivots_df, on='date')
    return m.dropna()


def simulate_real_straddle_decay(m: pd.DataFrame):
    """
    Intraday ATM Straddle Selling on Real Option Premiums:
    Sell ATM CE + Sell ATM PE at 09:30 IST.
    Stop loss: Total straddle loss of 25% (or 35 pts).
    Take profit: Total straddle gain of 25% (or 35 pts).
    Mandatory exit at 15:15 IST.
    """
    days = m['date'].unique()
    trades = []

    for d in days:
        day_df = m[m['date'] == d]
        if len(day_df) < 10:
            continue

        bar_0930 = day_df[day_df['time_str'] >= '09:30'].iloc[0]
        entry_ce = bar_0930['ce_open']
        entry_pe = bar_0930['pe_open']
        entry_straddle = entry_ce + entry_pe

        if entry_straddle < 30.0:
            continue

        sl_straddle = entry_straddle * 1.25  # Max loss = 25% expansion
        tp_straddle = entry_straddle * 0.75  # Target = 25% decay into profit

        # Loop through rest of day
        rest = day_df.loc[bar_0930.name:]
        exit_straddle = None
        reason = None

        for idx, row in rest.iterrows():
            curr_straddle_high = row['ce_high'] + row['pe_high']
            curr_straddle_low = row['ce_low'] + row['pe_low']
            curr_straddle_close = row['ce_close'] + row['pe_close']
            t = row['time_str']

            if curr_straddle_high >= sl_straddle:
                exit_straddle = sl_straddle
                reason = "STOP_LOSS"
                break
            elif curr_straddle_low <= tp_straddle:
                exit_straddle = tp_straddle
                reason = "TAKE_PROFIT"
                break
            elif t >= '15:15':
                exit_straddle = curr_straddle_close
                reason = "EOD_EXIT"
                break

        if exit_straddle is not None:
            # We are SELLER: profit = entry - exit
            pnl_premium = entry_straddle - exit_straddle
            pnl_premium -= 2.0  # Slippage
            trades.append({
                "date": d,
                "year": bar_0930['year'],
                "entry_premium": entry_straddle,
                "exit_premium": exit_straddle,
                "pnl": pnl_premium,
                "reason": reason,
            })

    tdf = pd.DataFrame(trades)
    return tdf


def main():
    m = load_merged_data()
    print(f"Loaded {len(m):,} aligned 15-minute bars with real Option Premiums across {m['date'].nunique()} trading days.")

    tdf = simulate_real_straddle_decay(m)
    wins = tdf[tdf['pnl'] > 0]
    losses = tdf[tdf['pnl'] <= 0]
    wr = len(wins) / len(tdf) * 100.0
    tot_p = wins['pnl'].sum() if len(wins) > 0 else 0.0
    tot_l = abs(losses['pnl'].sum()) if len(losses) > 0 else 1.0
    pf = tot_p / max(1.0, tot_l)
    net_pts = tdf['pnl'].sum()

    print("\n" + "=" * 75)
    print("   REAL OPTION CONTRACT STRADDLE SELLING RESULTS (100% REAL LTP / OHLC)   ")
    print("=" * 75)
    print(f"Total Trading Days Tested : {len(tdf)}")
    print(f"Win Rate (Theta Profit)   : {wr:.1f}%")
    print(f"Profit Factor             : {pf:.2f}")
    print(f"Net Premium Captured      : {net_pts:+,.1f} pts per share")
    print(f"Est. P&L (1 Lot = 25 Qty) : +INR {net_pts * 25:+,.0f}")
    print(f"Est. P&L (2 Lots = 50 Qty): +INR {net_pts * 50:+,.0f}")
    print(f"Average P&L per Day       : +INR {tdf['pnl'].mean() * 25:+,.0f} / lot")

    print("\n  Yearly Performance on Real Option Premiums:")
    yearly = tdf.groupby('year')['pnl'].agg(trades='count', wr=lambda x: (x > 0).mean() * 100, net='sum')
    for yr, r in yearly.iterrows():
        print(f"    Year {yr}: {int(r['trades']):3d} days | Win Rate: {r['wr']:5.1f}% | Net Premium: {r['net']:+8.1f} pts (+INR {r['net']*25:+,.0f})")
    print("=" * 75)


if __name__ == "__main__":
    main()
