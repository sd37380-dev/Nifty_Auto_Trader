"""
Find Robust, High-Win-Rate Strategy across 5 Years of NIFTY 15M Data.
Strict fixed-risk mechanics (SL: 35 pts, TP: 70 pts = 1:2 R:R).
Guaranteed realistic slippage, no lookahead bias.
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

    # Keep regular NSE market hours
    df = df[(df['time_str'] >= '09:15') & (df['time_str'] <= '15:30')].copy()

    # Technicals
    c = df['close']
    h = df['high']
    l = df['low']

    df['ema_9'] = c.ewm(span=9, adjust=False).mean()
    df['ema_21'] = c.ewm(span=21, adjust=False).mean()
    df['ema_50'] = c.ewm(span=50, adjust=False).mean()
    df['ema_200'] = c.ewm(span=200, adjust=False).mean()

    # SuperTrend (10, 3)
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.rolling(10).mean()
    hl2 = (h + l) / 2.0
    upper_band = hl2 + (3.0 * atr)
    lower_band = hl2 - (3.0 * atr)

    supertrend = [True] * len(df) # True = Bullish, False = Bearish
    for i in range(1, len(df)):
        if c.iloc[i] > upper_band.iloc[i-1]:
            supertrend[i] = True
        elif c.iloc[i] < lower_band.iloc[i-1]:
            supertrend[i] = False
        else:
            supertrend[i] = supertrend[i-1]
    df['supertrend'] = supertrend

    return df


def backtest_fixed_rr(df: pd.DataFrame, long_signal: pd.Series, short_signal: pd.Series, name: str, sl_pts: float = 35.0, tp_pts: float = 70.0):
    trades = []
    days = df['date'].unique()

    for d in days:
        day_df = df[df['date'] == d]
        if len(day_df) < 8:
            continue

        in_trade = False
        direction = None
        entry_p = 0.0
        sl_p = 0.0
        tp_p = 0.0

        for idx, row in day_df.iterrows():
            t = row['time_str']
            c = row['close']
            h = row['high']
            l = row['low']

            if not in_trade:
                if '09:30' <= t <= '13:30': # Active entry hours
                    if long_signal.loc[idx]:
                        in_trade = True
                        direction = "LONG"
                        entry_p = c
                        sl_p = entry_p - sl_pts
                        tp_p = entry_p + tp_pts
                    elif short_signal.loc[idx]:
                        in_trade = True
                        direction = "SHORT"
                        entry_p = c
                        sl_p = entry_p + sl_pts
                        tp_p = entry_p - tp_pts
            else:
                exit_p = None
                reason = None
                if direction == "LONG":
                    if l <= sl_p:
                        exit_p = sl_p
                        reason = "SL"
                    elif h >= tp_p:
                        exit_p = tp_p
                        reason = "TP"
                    elif t >= '15:15':
                        exit_p = c
                        reason = "EOD"
                else:
                    if h >= sl_p:
                        exit_p = sl_p
                        reason = "SL"
                    elif l <= tp_p:
                        exit_p = tp_p
                        reason = "TP"
                    elif t >= '15:15':
                        exit_p = c
                        reason = "EOD"

                if exit_p is not None:
                    pnl = (exit_p - entry_p) if direction == "LONG" else (entry_p - exit_p)
                    pnl -= 3.0 # Slippage
                    trades.append({
                        "date": d,
                        "year": row['year'],
                        "direction": direction,
                        "entry": entry_p,
                        "exit": exit_p,
                        "pnl": pnl,
                        "reason": reason,
                    })
                    break # Max 1 trade per day for discipline

    if not trades:
        print(f"No trades for {name}")
        return None

    tdf = pd.DataFrame(trades)
    wins = tdf[tdf['pnl'] > 0]
    losses = tdf[tdf['pnl'] <= 0]
    wr = len(wins) / len(tdf) * 100.0
    tot_p = wins['pnl'].sum() if len(wins) > 0 else 0.0
    tot_l = abs(losses['pnl'].sum()) if len(losses) > 0 else 1.0
    pf = tot_p / max(1.0, tot_l)
    net_pts = tdf['pnl'].sum()

    tdf['cum'] = tdf['pnl'].cumsum()
    max_dd = (tdf['cum'].cummax() - tdf['cum']).max()

    print(f"\n==================================================================")
    print(f"  STRATEGY: {name}")
    print(f"==================================================================")
    print(f"  Total Trades       : {len(tdf):,}")
    print(f"  Win Rate           : {wr:.1f}%")
    print(f"  Profit Factor      : {pf:.2f}")
    print(f"  Net NIFTY Points   : {net_pts:+,.1f} pts")
    print(f"  Max Drawdown       : {max_dd:,.1f} pts")
    print(f"  Avg Points / Trade : {tdf['pnl'].mean():+.1f} pts")
    print("\n  Yearly Breakdown:")
    yearly = tdf.groupby('year').agg(
        trades=('pnl', 'count'),
        win_rate=('pnl', lambda x: (x > 0).mean() * 100),
        net_pts=('pnl', 'sum')
    )
    for yr, r in yearly.iterrows():
        print(f"    Year {yr}: {int(r['trades']):3d} trades | Win Rate: {r['win_rate']:5.1f}% | Net: {r['net_pts']:+8.1f} pts")

    return tdf


def main():
    print("[*] Loading 5 years of clean NIFTY bars...")
    df = load_clean_data()

    # 1. SuperTrend Reversal in direction of 200 EMA
    # Long: SuperTrend turns Bullish AND Close > 200 EMA
    st_flip_bull = df['supertrend'] & (~df['supertrend'].shift(1).fillna(False)) & (df['close'] > df['ema_200'])
    st_flip_bear = (~df['supertrend']) & (df['supertrend'].shift(1).fillna(True)) & (df['close'] < df['ema_200'])
    backtest_fixed_rr(df, st_flip_bull, st_flip_bear, "1. SuperTrend (10, 3) + 200 EMA Filter (1:2 R:R)", sl_pts=35.0, tp_pts=70.0)

    # 2. EMA 9/21 Golden Cross in direction of 200 EMA
    ema_cross_bull = (df['ema_9'] > df['ema_21']) & (df['ema_9'].shift(1) <= df['ema_21'].shift(1)) & (df['close'] > df['ema_200'])
    ema_cross_bear = (df['ema_9'] < df['ema_21']) & (df['ema_9'].shift(1) >= df['ema_21'].shift(1)) & (df['close'] < df['ema_200'])
    backtest_fixed_rr(df, ema_cross_bull, ema_cross_bear, "2. EMA 9/21 Trend Cross + 200 EMA Filter (1:2 R:R)", sl_pts=35.0, tp_pts=70.0)

    # 3. Previous Day High / Low Breakout (PDH / PDL)
    # Group by date to find PDH and PDL
    daily = df.groupby('date').agg(pdh=('high', 'max'), pdl=('low', 'min'))
    daily_shifted = daily.shift(1)
    df = df.join(daily_shifted, on='date')
    pdh_break = (df['close'] > df['pdh']) & (df['close'].shift(1) <= df['pdh']) & (df['close'] > df['ema_200'])
    pdl_break = (df['close'] < df['pdl']) & (df['close'].shift(1) >= df['pdl']) & (df['close'] < df['ema_200'])
    backtest_fixed_rr(df, pdh_break, pdl_break, "3. Previous Day High/Low Breakout + 200 EMA (1:2 R:R)", sl_pts=35.0, tp_pts=70.0)


if __name__ == "__main__":
    main()
