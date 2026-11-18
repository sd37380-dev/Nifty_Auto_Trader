"""
Backtest Directly on Real Option Contract Premiums (OHLC, Volume, OI).
Merges Underlying NIFTY Index Spot Data with Real ATM Call & Put Option Contracts.
Simulates entries, stops, and targets directly on actual traded option premiums.
"""

import sqlite3
import pandas as pd
import numpy as np


def load_merged_data():
    conn = sqlite3.connect("data/hermes_research/market_data.db")

    # Load Spot
    spot_df = pd.read_sql_query(
        "SELECT timestamp, open as spot_open, high as spot_high, low as spot_low, close as spot_close, volume as spot_vol FROM normalized_bars WHERE symbol='NIFTY' AND timeframe='15M' ORDER BY timestamp ASC",
        conn
    )
    # Load CE
    ce_df = pd.read_sql_query(
        "SELECT timestamp, open as ce_open, high as ce_high, low as ce_low, close as ce_close, volume as ce_vol, open_interest as ce_oi FROM normalized_bars WHERE symbol='NIFTY_ATM_CE' ORDER BY timestamp ASC",
        conn
    )
    # Load PE
    pe_df = pd.read_sql_query(
        "SELECT timestamp, open as pe_open, high as pe_high, low as pe_low, close as pe_close, volume as pe_vol, open_interest as pe_oi FROM normalized_bars WHERE symbol='NIFTY_ATM_PE' ORDER BY timestamp ASC",
        conn
    )
    conn.close()

    # Deduplicate
    spot_df.drop_duplicates(subset=['timestamp'], inplace=True)
    ce_df.drop_duplicates(subset=['timestamp'], inplace=True)
    pe_df.drop_duplicates(subset=['timestamp'], inplace=True)

    # Merge on timestamp
    m = pd.merge(spot_df, ce_df, on='timestamp', how='inner')
    m = pd.merge(m, pe_df, on='timestamp', how='inner')

    m['dt'] = pd.to_datetime(m['timestamp'], format='ISO8601')
    m.set_index('dt', inplace=True)
    m.sort_index(inplace=True)

    # IST
    m['ist'] = m.index + pd.Timedelta(hours=5, minutes=30)
    m['date'] = m['ist'].dt.date
    m['time_str'] = m['ist'].dt.strftime('%H:%M')
    m['year'] = m['ist'].dt.year

    m = m[(m['time_str'] >= '09:15') & (m['time_str'] <= '15:30')].copy()

    # Spot EMA 14
    m['ema_14'] = m['spot_close'].ewm(span=14, adjust=False).mean()

    # Daily Pivots from Spot
    daily = m.groupby('date').agg(day_h=('spot_high', 'max'), day_l=('spot_low', 'min'), day_c=('spot_close', 'last'))
    daily_prev = daily.shift(1)
    p = (daily_prev['day_h'] + daily_prev['day_l'] + daily_prev['day_c']) / 3.0
    r1 = (2.0 * p) - daily_prev['day_l']
    s1 = (2.0 * p) - daily_prev['day_h']
    bc = (daily_prev['day_h'] + daily_prev['day_l']) / 2.0
    tc = (2.0 * p) - bc
    cpr_top = np.maximum(tc, bc)
    cpr_bot = np.minimum(tc, bc)

    pivots_df = pd.DataFrame({
        'pivot': p, 'r1': r1, 's1': s1, 'cpr_top': cpr_top, 'cpr_bot': cpr_bot,
    }, index=daily.index)

    m = m.join(pivots_df, on='date')
    return m.dropna()


def simulate_real_option_trades(m: pd.DataFrame, risk_reward: float = 3.0):
    days = m['date'].unique()
    trades = []

    for d in days:
        day_df = m[m['date'] == d]
        if len(day_df) < 8:
            continue

        in_trade = False
        opt_type = None
        entry_opt_price = 0.0
        sl_opt_price = 0.0
        tp_opt_price = 0.0
        spot_entry = 0.0

        for idx, row in day_df.iterrows():
            t = row['time_str']
            sc = row['spot_close']
            so = row['spot_open']
            sh = row['spot_high']
            sl = row['spot_low']
            e14 = row['ema_14']

            s_levels = [row['s1'], row['cpr_bot'], row['pivot']]
            r_levels = [row['r1'], row['cpr_top'], row['pivot']]

            near_s = any(abs(sl - s) <= 20.0 or (sl < s and sc > s) for s in s_levels)
            near_r = any(abs(sh - r) <= 20.0 or (sh > r and sc < r) for r in r_levels)

            if not in_trade:
                if '09:30' <= t <= '13:30':
                    # LONG Setup: Spot bounces off Support & crosses EMA 14 -> BUY REAL CALL (CE)
                    if near_s and sc > e14 and sc > so and row['ce_open'] > 5.0:
                        in_trade = True
                        opt_type = "CALL"
                        spot_entry = sc
                        entry_opt_price = row['ce_open'] # Buy at Call Option Open
                        # Risk: 25% of option premium or min Rs. 15
                        opt_risk = max(15.0, round(entry_opt_price * 0.25, 1))
                        sl_opt_price = max(1.0, entry_opt_price - opt_risk)
                        tp_opt_price = entry_opt_price + (opt_risk * risk_reward)

                    # SHORT Setup: Spot rejects Resistance & falls below EMA 14 -> BUY REAL PUT (PE)
                    elif near_r and sc < e14 and sc < so and row['pe_open'] > 5.0:
                        in_trade = True
                        opt_type = "PUT"
                        spot_entry = sc
                        entry_opt_price = row['pe_open'] # Buy at Put Option Open
                        opt_risk = max(15.0, round(entry_opt_price * 0.25, 1))
                        sl_opt_price = max(1.0, entry_opt_price - opt_risk)
                        tp_opt_price = entry_opt_price + (opt_risk * risk_reward)

            else:
                exit_price = None
                reason = None

                if opt_type == "CALL":
                    c_low = row['ce_low']
                    c_high = row['ce_high']
                    c_close = row['ce_close']

                    if c_low <= sl_opt_price:
                        exit_price = sl_opt_price
                        reason = "SL"
                    elif c_high >= tp_opt_price:
                        exit_price = tp_opt_price
                        reason = "TP_1:3"
                    elif t >= '15:15':
                        exit_price = c_close
                        reason = "EOD"

                else: # PUT
                    p_low = row['pe_low']
                    p_high = row['pe_high']
                    p_close = row['pe_close']

                    if p_low <= sl_opt_price:
                        exit_price = sl_opt_price
                        reason = "SL"
                    elif p_high >= tp_opt_price:
                        exit_price = tp_opt_price
                        reason = "TP_1:3"
                    elif t >= '15:15':
                        exit_price = p_close
                        reason = "EOD"

                if exit_price is not None:
                    pnl_rupees = exit_price - entry_opt_price
                    pnl_rupees -= 1.0 # Slippage on option premium
                    trades.append({
                        "date": d,
                        "year": row['year'],
                        "type": opt_type,
                        "spot_entry": spot_entry,
                        "entry_premium": entry_opt_price,
                        "exit_premium": exit_price,
                        "pnl_premium": pnl_rupees,
                        "reason": reason,
                    })
                    break

    return pd.DataFrame(trades)


def main():
    print("[*] Merging Underlying Spot with Real ATM Call & Put Option Contracts...")
    m = load_merged_data()
    print(f"[+] Loaded {len(m):,} aligned 15-minute bars with real Option OHLCV + OI across {m['date'].nunique()} trading days.")

    tdf = simulate_real_option_trades(m, risk_reward=3.0)

    if len(tdf) == 0:
        print("No trades triggered.")
        return

    wins = tdf[tdf['pnl_premium'] > 0]
    losses = tdf[tdf['pnl_premium'] <= 0]
    wr = len(wins) / len(tdf) * 100.0

    tot_gain = wins['pnl_premium'].sum() if len(wins) > 0 else 0.0
    tot_loss = abs(losses['pnl_premium'].sum()) if len(losses) > 0 else 1.0
    pf = tot_gain / max(1.0, tot_loss)
    net_pts = tdf['pnl_premium'].sum()

    tdf['cum'] = tdf['pnl_premium'].cumsum()
    max_dd = (tdf['cum'].cummax() - tdf['cum']).max()

    print("\n" + "=" * 75)
    print("      BACKTEST RESULTS ON REAL OPTION CONTRACTS (LTP / OHLC)       ")
    print("=" * 75)
    print(f"Total Option Trades       : {len(tdf):,}")
    print(f"Option Premium Win Rate   : {wr:.1f}%")
    print(f"Profit Factor             : {pf:.2f}")
    print(f"Net Premium Pts Captured  : {net_pts:+,.1f} pts (per lot)")
    print(f"Max Drawdown (Premium)    : {max_dd:,.1f} pts")
    print(f"Average P&L per Trade     : Rs. {tdf['pnl_premium'].mean():+.1f} / share")
    print(f"Total P&L (1 Lot = 25 Qty): +INR {net_pts * 25:,.0f}")
    print(f"Total P&L (2 Lots = 50 Qty): +INR {net_pts * 50:,.0f}")

    print("\n" + "-" * 75)
    print("  YEAR-BY-YEAR REAL OPTION PREMIUM PERFORMANCE")
    print("-" * 75)
    yearly = tdf.groupby('year').agg(
        trades=('pnl_premium', 'count'),
        tp_hits=('reason', lambda x: (x == 'TP_1:3').sum()),
        win_rate=('pnl_premium', lambda x: (x > 0).mean() * 100),
        net_pts=('pnl_premium', 'sum')
    )
    for yr, r in yearly.iterrows():
        print(f"  Year {yr}: {int(r['trades']):3d} trades | TP Hits: {int(r['tp_hits']):2d} | Win Rate: {r['win_rate']:5.1f}% | Net Premium: {r['net_pts']:+8.1f} pts (INR {r['net_pts']*25:+,.0f})")
    print("=" * 75)


if __name__ == "__main__":
    main()
