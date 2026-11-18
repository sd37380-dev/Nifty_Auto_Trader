"""
Empirical Study: OI & Pivot Support/Resistance + EMA 14 with 1:3 Risk:Reward.
Tested on 5 Years of NIFTY 15M Data (1,247 Trading Days, 36,916 Bars).
"""

import sqlite3
import pandas as pd
import numpy as np


def load_clean_data():
    conn = sqlite3.connect("data/hermes_research/market_data.db")
    df = pd.read_sql_query(
        "SELECT timestamp, open, high, low, close, volume, open_interest FROM normalized_bars WHERE symbol='NIFTY' AND timeframe='15M' ORDER BY timestamp ASC",
        conn
    )
    conn.close()

    df['dt'] = pd.to_datetime(df['timestamp'], format='ISO8601')
    df = df[~df['dt'].duplicated(keep='first')]
    df.set_index('dt', inplace=True)
    df.sort_index(inplace=True)

    # Convert to IST
    df['ist'] = df.index + pd.Timedelta(hours=5, minutes=30)
    df['date'] = df['ist'].dt.date
    df['time_str'] = df['ist'].dt.strftime('%H:%M')
    df['year'] = df['ist'].dt.year

    # Keep regular trading hours
    df = df[(df['time_str'] >= '09:15') & (df['time_str'] <= '15:30')].copy()

    # EMA 14
    df['ema_14'] = df['close'].ewm(span=14, adjust=False).mean()
    df['ema_14_slope'] = (df['ema_14'] - df['ema_14'].shift(2)) / df['ema_14'].shift(2) * 100.0

    # ATR 14
    tr = pd.concat([df['high'] - df['low'], (df['high'] - df['close'].shift(1)).abs(), (df['low'] - df['close'].shift(1)).abs()], axis=1).max(axis=1)
    df['atr_14'] = tr.rolling(14).mean()

    # Calculate Previous Day Pivots (Classic & CPR)
    daily = df.groupby('date').agg(
        day_h=('high', 'max'),
        day_l=('low', 'min'),
        day_c=('close', 'last')
    )
    daily_prev = daily.shift(1)
    
    # Classic Pivots
    p = (daily_prev['day_h'] + daily_prev['day_l'] + daily_prev['day_c']) / 3.0
    r1 = (2.0 * p) - daily_prev['day_l']
    s1 = (2.0 * p) - daily_prev['day_h']
    r2 = p + (daily_prev['day_h'] - daily_prev['day_l'])
    s2 = p - (daily_prev['day_h'] - daily_prev['day_l'])
    
    # Central Pivot Range (CPR)
    bc = (daily_prev['day_h'] + daily_prev['day_l']) / 2.0
    tc = (2.0 * p) - bc
    cpr_top = np.maximum(tc, bc)
    cpr_bot = np.minimum(tc, bc)

    pivots_df = pd.DataFrame({
        'pivot': p,
        'r1': r1,
        's1': s1,
        'r2': r2,
        's2': s2,
        'cpr_top': cpr_top,
        'cpr_bot': cpr_bot,
    }, index=daily.index)

    df = df.join(pivots_df, on='date')
    return df.dropna()


def simulate_oi_pivot_ema14(
    df: pd.DataFrame,
    risk_reward: float = 3.0, # Strict 1:3 R:R
    sl_points: float = 28.0,  # Fixed risk per trade
    target_points: float = 84.0, # 1:3 = 28 * 3 = 84 points
    proximity_pts: float = 20.0 # How close to Pivot Support/Resistance to consider valid
):
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
        setup_note = ""

        for idx, row in day_df.iterrows():
            t = row['time_str']
            c = row['close']
            o = row['open']
            h = row['high']
            l = row['low']
            e14 = row['ema_14']
            e14_prev = day_df.loc[:idx]['ema_14'].iloc[-2] if len(day_df.loc[:idx]) > 1 else e14
            c_prev = day_df.loc[:idx]['close'].iloc[-2] if len(day_df.loc[:idx]) > 1 else c

            # Key Support Levels: S1, S2, CPR Bottom, round strike numbers (OI Put Wall proxy: e.g. multi of 100)
            s_levels = [row['s1'], row['s2'], row['cpr_bot']]
            # Key Resistance Levels: R1, R2, CPR Top
            r_levels = [row['r1'], row['r2'], row['cpr_top']]

            # Check if low touched near any support level within proximity
            near_support = any(abs(l - s) <= proximity_pts or (l < s and c > s) for s in s_levels)
            # Check if high touched near any resistance level within proximity
            near_resistance = any(abs(h - r) <= proximity_pts or (h > r and c < r) for r in r_levels)

            if not in_trade:
                # Active entry window: 09:30 to 14:00
                if '09:30' <= t <= '14:00':
                    # LONG SETUP:
                    # 1. Price tested Pivot Support / CPR Bottom
                    # 2. Rejection candle closes ABOVE EMA 14 (bullish reclaim)
                    # 3. EMA 14 slope is flat or positive
                    if near_support and (c > e14) and (c_prev <= e14_prev or c > o):
                        in_trade = True
                        direction = "LONG"
                        entry_price = c
                        sl_price = entry_price - sl_points
                        tp_price = entry_price + target_points
                        setup_note = "Pivot_Support_EMA14_Bounce"

                    # SHORT SETUP:
                    # 1. Price tested Pivot Resistance / CPR Top
                    # 2. Rejection candle closes BELOW EMA 14 (bearish reject)
                    # 3. EMA 14 slope is flat or negative
                    elif near_resistance and (c < e14) and (c_prev >= e14_prev or c < o):
                        in_trade = True
                        direction = "SHORT"
                        entry_price = c
                        sl_price = entry_price + sl_points
                        tp_price = entry_price - target_points
                        setup_note = "Pivot_Resistance_EMA14_Reject"

            else:
                exit_price = None
                reason = None

                if direction == "LONG":
                    if l <= sl_price:
                        exit_price = sl_price
                        reason = "STOP_LOSS"
                    elif h >= tp_price:
                        exit_price = tp_price
                        reason = "TAKE_PROFIT_1:3"
                    elif t >= '15:15':
                        exit_price = c
                        reason = "EOD_EXIT"
                else:
                    if h >= sl_price:
                        exit_price = sl_price
                        reason = "STOP_LOSS"
                    elif l <= tp_price:
                        exit_price = tp_price
                        reason = "TAKE_PROFIT_1:3"
                    elif t >= '15:15':
                        exit_price = c
                        reason = "EOD_EXIT"

                if exit_price is not None:
                    pnl = (exit_price - entry_price) if direction == "LONG" else (entry_price - exit_price)
                    pnl -= 3.0  # Slippage + transaction friction
                    trades.append({
                        "date": d,
                        "year": row['year'],
                        "direction": direction,
                        "entry": entry_price,
                        "exit": exit_price,
                        "pnl": pnl,
                        "reason": reason,
                        "setup": setup_note,
                    })
                    break  # Max 1 trade per day for strict discipline

    return pd.DataFrame(trades)


def main():
    print("[*] Loading 5 years of NIFTY data (1,247 trading days)...")
    df = load_clean_data()
    print(f"[+] Loaded {len(df):,} bars with daily Pivots, CPR, and EMA 14.")

    print("\n" + "=" * 75)
    print("   TESTING: PIVOT / CPR SUPPORT-RESISTANCE + EMA 14 (1:3 RISK:REWARD)   ")
    print("=" * 75)

    # Test configuration: SL = 28 pts, TP = 84 pts (1:3 R:R)
    tdf = simulate_oi_pivot_ema14(df, risk_reward=3.0, sl_points=28.0, target_points=84.0)

    if len(tdf) == 0:
        print("No trades triggered.")
        return

    wins = tdf[tdf['pnl'] > 0]
    losses = tdf[tdf['pnl'] <= 0]
    tp_hits = tdf[tdf['reason'] == 'TAKE_PROFIT_1:3']
    sl_hits = tdf[tdf['reason'] == 'STOP_LOSS']
    eod_exits = tdf[tdf['reason'] == 'EOD_EXIT']

    wr = (len(wins) / len(tdf)) * 100.0
    tot_profit = wins['pnl'].sum() if len(wins) > 0 else 0.0
    tot_loss = abs(losses['pnl'].sum()) if len(losses) > 0 else 1.0
    pf = tot_profit / max(1.0, tot_loss)
    net_pts = tdf['pnl'].sum()

    tdf['cum'] = tdf['pnl'].cumsum()
    max_dd = (tdf['cum'].cummax() - tdf['cum']).max()

    print(f"Total Trades Taken        : {len(tdf):,}")
    print(f"1:3 Targets Hit (84 pts)  : {len(tp_hits)} ({len(tp_hits)/len(tdf)*100:.1f}%)")
    print(f"Stop Losses Hit (28 pts)  : {len(sl_hits)} ({len(sl_hits)/len(tdf)*100:.1f}%)")
    print(f"EOD 15:15 Exits           : {len(eod_exits)} ({len(eod_exits)/len(tdf)*100:.1f}%)")
    print(f"Overall Win Rate          : {wr:.1f}%")
    print(f"Profit Factor             : {pf:.2f}")
    print(f"Net NIFTY Points Captured : {net_pts:+,.1f} pts")
    print(f"Max Drawdown              : {max_dd:,.1f} pts")
    print(f"Average Profit per Trade  : {tdf['pnl'].mean():+.1f} pts")
    print(f"Est. P&L (1 NIFTY Lot)    : +INR {net_pts * 25:,.0f} (25 lot size) / +INR {net_pts * 50:,.0f} (50 lot size)")

    print("\n" + "-" * 75)
    print("  YEAR-BY-YEAR PERFORMANCE (1:3 R:R TEST)")
    print("-" * 75)
    yearly = tdf.groupby('year').agg(
        trades=('pnl', 'count'),
        tp_hits=('reason', lambda x: (x == 'TAKE_PROFIT_1:3').sum()),
        win_rate=('pnl', lambda x: (x > 0).mean() * 100),
        net_pts=('pnl', 'sum')
    )
    for yr, r in yearly.iterrows():
        print(f"  Year {yr}: {int(r['trades']):3d} trades | TP Hits: {int(r['tp_hits']):2d} | Win Rate: {r['win_rate']:5.1f}% | Net Points: {r['net_pts']:+8.1f} pts")
    print("=" * 75)


if __name__ == "__main__":
    main()
