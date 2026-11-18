"""
Study: Pivot/OI Support-Resistance + Dynamic 14 EMA Trailing Stop (1:3 Target).
Instead of early breakeven choking, we trail behind the EMA 14 candle close!
"""

import sqlite3
import pandas as pd
import numpy as np


def load_clean_data():
    conn = sqlite3.connect("data/hermes_research/market_data.db")
    df = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, volume FROM normalized_bars WHERE symbol='NIFTY' AND timeframe='15M' ORDER BY timestamp ASC",
        conn
    )
    conn.close()

    df['dt'] = pd.to_datetime(df['timestamp'], format='ISO8601')
    df = df[~df['dt'].duplicated(keep='first')]
    df.set_index('dt', inplace=True)
    df.sort_index(inplace=True)

    df['ist'] = df.index + pd.Timedelta(hours=5, minutes=30)
    df['date'] = df['ist'].dt.date
    df['time_str'] = df['ist'].dt.strftime('%H:%M')
    df['year'] = df['ist'].dt.year

    df = df[(df['time_str'] >= '09:15') & (df['time_str'] <= '15:30')].copy()

    df['ema_14'] = df['close'].ewm(span=14, adjust=False).mean()

    # Pivots
    daily = df.groupby('date').agg(day_h=('high', 'max'), day_l=('low', 'min'), day_c=('close', 'last'))
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
        'pivot': p, 'r1': r1, 's1': s1, 'r2': r2, 's2': s2,
        'cpr_top': cpr_top, 'cpr_bot': cpr_bot,
    }, index=daily.index)

    df = df.join(pivots_df, on='date')
    return df.dropna()


def simulate_ema14_trail(df: pd.DataFrame, sl_pts: float = 30.0, target_pts: float = 90.0): # 1:3 R:R
    days = df['date'].unique()
    trades = []

    for d in days:
        day_df = df[df['date'] == d]
        if len(day_df) < 10:
            continue

        in_trade = False
        direction = None
        entry_price = 0.0
        sl_price = 0.0
        tp_price = 0.0

        for idx, row in day_df.iterrows():
            t = row['time_str']
            c = row['close']
            o = row['open']
            h = row['high']
            l = row['low']
            e14 = row['ema_14']

            s_levels = [row['s1'], row['s2'], row['cpr_bot'], row['pivot']]
            r_levels = [row['r1'], row['r2'], row['cpr_top'], row['pivot']]

            near_s = any(abs(l - s) <= 20.0 or (l < s and c > s) for s in s_levels)
            near_r = any(abs(h - r) <= 20.0 or (h > r and c < r) for r in r_levels)

            if not in_trade:
                if '09:30' <= t <= '13:30':
                    # Long
                    if near_s and c > e14 and c > o:
                        in_trade = True
                        direction = "LONG"
                        entry_price = c
                        sl_price = entry_price - sl_pts
                        tp_price = entry_price + target_pts
                    # Short
                    elif near_r and c < e14 and c < o:
                        in_trade = True
                        direction = "SHORT"
                        entry_price = c
                        sl_price = entry_price + sl_pts
                        tp_price = entry_price - target_pts
            else:
                exit_price = None
                reason = None

                if direction == "LONG":
                    # Hard SL
                    if l <= sl_price:
                        exit_price = sl_price
                        reason = "HARD_SL"
                    # Target 1:3
                    elif h >= tp_price:
                        exit_price = tp_price
                        reason = "TARGET_1:3"
                    # Dynamic Exit: If price was in profit > +30 pts and now closes below 14 EMA
                    elif (h - entry_price >= 30.0) and c < e14:
                        exit_price = c
                        reason = "EMA14_TRAIL_EXIT"
                    elif t >= '15:15':
                        exit_price = c
                        reason = "EOD"
                else:
                    if h >= sl_price:
                        exit_price = sl_price
                        reason = "HARD_SL"
                    elif l <= tp_price:
                        exit_price = tp_price
                        reason = "TARGET_1:3"
                    elif (entry_price - l >= 30.0) and c > e14:
                        exit_price = c
                        reason = "EMA14_TRAIL_EXIT"
                    elif t >= '15:15':
                        exit_price = c
                        reason = "EOD"

                if exit_price is not None:
                    pnl = (exit_price - entry_price) if direction == "LONG" else (entry_price - exit_price)
                    pnl -= 3.0
                    trades.append({
                        "date": d,
                        "year": row['year'],
                        "direction": direction,
                        "entry": entry_price,
                        "exit": exit_price,
                        "pnl": pnl,
                        "reason": reason,
                    })
                    break

    return pd.DataFrame(trades)


def main():
    df = load_clean_data()
    tdf = simulate_ema14_trail(df, sl_pts=30.0, target_pts=90.0)

    wins = tdf[tdf['pnl'] > 0]
    losses = tdf[tdf['pnl'] <= 0]
    tp_hits = tdf[tdf['reason'] == 'TARGET_1:3']
    trail_exits = tdf[tdf['reason'] == 'EMA14_TRAIL_EXIT']
    sl_hits = tdf[tdf['reason'] == 'HARD_SL']

    wr = (len(wins) / len(tdf)) * 100.0
    tot_p = wins['pnl'].sum() if len(wins) > 0 else 0.0
    tot_l = abs(losses['pnl'].sum()) if len(losses) > 0 else 1.0
    pf = tot_p / max(1.0, tot_l)
    net_pts = tdf['pnl'].sum()

    tdf['cum'] = tdf['pnl'].cumsum()
    max_dd = (tdf['cum'].cummax() - tdf['cum']).max()

    print("=" * 75)
    print("   STUDY: PIVOT/OI SUPPORT-RESISTANCE + EMA 14 DYNAMIC TRAIL (1:3 R:R)   ")
    print("=" * 75)
    print(f"Total Trades Taken        : {len(tdf):,}")
    print(f"1:3 Targets Hit (90 pts)  : {len(tp_hits)} ({len(tp_hits)/len(tdf)*100:.1f}%)")
    print(f"EMA 14 Trailing Profit    : {len(trail_exits)} ({len(trail_exits)/len(tdf)*100:.1f}%)")
    print(f"Hard Stop Losses Hit      : {len(sl_hits)} ({len(sl_hits)/len(tdf)*100:.1f}%)")
    print(f"Overall Win Rate          : {wr:.1f}%")
    print(f"Profit Factor             : {pf:.2f}")
    print(f"Net NIFTY Points Captured : {net_pts:+,.1f} pts")
    print(f"Max Drawdown              : {max_dd:,.1f} pts")
    print(f"Average Profit per Trade  : {tdf['pnl'].mean():+.1f} pts")
    print(f"Est. P&L (1 NIFTY Lot)    : +INR {net_pts * 25:,.0f} (25 lot) / +INR {net_pts * 50:,.0f} (50 lot)")

    print("\n" + "-" * 75)
    print("  YEAR-BY-YEAR PERFORMANCE (5 YEARS)")
    print("-" * 75)
    yearly = tdf.groupby('year').agg(
        trades=('pnl', 'count'),
        tp_hits=('reason', lambda x: (x == 'TARGET_1:3').sum()),
        win_rate=('pnl', lambda x: (x > 0).mean() * 100),
        net_pts=('pnl', 'sum')
    )
    for yr, r in yearly.iterrows():
        print(f"  Year {yr}: {int(r['trades']):3d} trades | 1:3 Hits: {int(r['tp_hits']):2d} | Win Rate: {r['win_rate']:5.1f}% | Net Points: {r['net_pts']:+8.1f} pts")
    print("=" * 75)


if __name__ == "__main__":
    main()
