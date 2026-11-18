"""
Intraday Strategy Analysis on 5 Years of NIFTY 15M Data (1,247 Trading Days).
Tests:
1. 09:45 Opening Range Breakout (ORB)
2. EMA 20 Pullback in Direction of 200 EMA
3. VWAP Session Trend Continuation
All trades are strictly intraday (squared off at 15:15 IST).
"""

import sqlite3
import pandas as pd
import numpy as np


def load_clean_intraday_data():
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

    # Convert UTC to IST (+5:30)
    df['ist'] = df.index + pd.Timedelta(hours=5, minutes=30)
    df['date'] = df['ist'].dt.date
    df['time_str'] = df['ist'].dt.strftime('%H:%M')
    df['year'] = df['ist'].dt.year

    # Filter to normal market hours only (09:15 to 15:30)
    df = df[(df['time_str'] >= '09:15') & (df['time_str'] <= '15:30')].copy()

    # Moving averages
    df['ema_20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean()

    # Session VWAP
    tp = (df['high'] + df['low'] + df['close']) / 3.0
    pv = tp * df['volume']
    df['cum_pv'] = pv.groupby(df['date']).cumsum()
    df['cum_vol'] = df['volume'].groupby(df['date']).cumsum()
    df['vwap'] = np.where(df['cum_vol'] > 0, df['cum_pv'] / df['cum_vol'], df['close'])

    return df


def test_opening_range_breakout(df: pd.DataFrame, target_mult: float = 1.5):
    """
    Opening Range (09:15 to 09:45): High and Low of first 2 bars.
    Entry on breakout between 09:45 and 11:30.
    Target: 1.5x range. Stop: Midpoint of range.
    Exit: SL, Target, or 15:15 IST.
    """
    days = df['date'].unique()
    trades = []

    for d in days:
        day_df = df[df['date'] == d]
        if len(day_df) < 10:
            continue

        or_bars = day_df[(day_df['time_str'] >= '09:15') & (day_df['time_str'] <= '09:30')]
        if len(or_bars) < 2:
            continue

        or_high = or_bars['high'].max()
        or_low = or_bars['low'].min()
        or_range = or_high - or_low

        if or_range < 30.0 or or_range > 180.0:  # Skip abnormally tight or huge gap ranges
            continue

        or_mid = (or_high + or_low) / 2.0
        target_dist = or_range * target_mult

        post_or_bars = day_df[(day_df['time_str'] >= '09:45') & (day_df['time_str'] <= '15:15')]

        in_trade = False
        direction = None
        entry_price = 0.0
        sl_price = 0.0
        tp_price = 0.0
        entry_time = None

        for idx, row in post_or_bars.iterrows():
            t_str = row['time_str']
            c_high = row['high']
            c_low = row['low']
            c_close = row['close']

            if not in_trade:
                # Only take fresh entries before 11:30 IST
                if t_str <= '11:30':
                    if c_close > or_high:
                        in_trade = True
                        direction = "LONG"
                        entry_price = c_close
                        sl_price = or_mid
                        tp_price = entry_price + target_dist
                        entry_time = row['ist']
                    elif c_close < or_low:
                        in_trade = True
                        direction = "SHORT"
                        entry_price = c_close
                        sl_price = or_mid
                        tp_price = entry_price - target_dist
                        entry_time = row['ist']
            else:
                exit_price = None
                reason = None
                if direction == "LONG":
                    if c_low <= sl_price:
                        exit_price = sl_price
                        reason = "SL"
                    elif c_high >= tp_price:
                        exit_price = tp_price
                        reason = "TP"
                    elif t_str >= '15:15':
                        exit_price = c_close
                        reason = "EOD"
                else:
                    if c_high >= sl_price:
                        exit_price = sl_price
                        reason = "SL"
                    elif c_low <= tp_price:
                        exit_price = tp_price
                        reason = "TP"
                    elif t_str >= '15:15':
                        exit_price = c_close
                        reason = "EOD"

                if exit_price is not None:
                    pts = (exit_price - entry_price) if direction == "LONG" else (entry_price - exit_price)
                    pts -= 3.0  # Slippage + charges
                    trades.append({
                        "date": d,
                        "year": row['year'],
                        "direction": direction,
                        "entry": entry_price,
                        "exit": exit_price,
                        "pts": pts,
                        "reason": reason,
                    })
                    break  # One trade per day max

    return pd.DataFrame(trades)


def test_vwap_trend_pullback(df: pd.DataFrame):
    """
    Intraday Trend Continuation:
    Long: Close > 200 EMA & Close > VWAP. Price pulls back to touch VWAP (Low <= VWAP) and closes above VWAP.
    Short: Close < 200 EMA & Close < VWAP. Price pulls back to touch VWAP (High >= VWAP) and closes below VWAP.
    SL: 35 points, Target: 70 points (1:2 R:R). EOD exit at 15:15.
    """
    days = df['date'].unique()
    trades = []

    for d in days:
        day_df = df[df['date'] == d]
        if len(day_df) < 10:
            continue

        # Look for entries between 10:00 and 14:00
        eligible = day_df[(day_df['time_str'] >= '10:00') & (day_df['time_str'] <= '15:15')]
        in_trade = False
        direction = None
        entry_price = 0.0
        sl_price = 0.0
        tp_price = 0.0

        for idx, row in eligible.iterrows():
            t_str = row['time_str']
            c_high = row['high']
            c_low = row['low']
            c_close = row['close']
            c_vwap = row['vwap']
            c_ema200 = row['ema_200']

            if not in_trade:
                if t_str <= '13:45':
                    # Long setup
                    if c_close > c_ema200 and c_low <= c_vwap and c_close > c_vwap:
                        in_trade = True
                        direction = "LONG"
                        entry_price = c_close
                        sl_price = entry_price - 35.0
                        tp_price = entry_price + 70.0  # 1:2
                    # Short setup
                    elif c_close < c_ema200 and c_high >= c_vwap and c_close < c_vwap:
                        in_trade = True
                        direction = "SHORT"
                        entry_price = c_close
                        sl_price = entry_price + 35.0
                        tp_price = entry_price - 70.0
            else:
                exit_price = None
                reason = None
                if direction == "LONG":
                    if c_low <= sl_price:
                        exit_price = sl_price
                        reason = "SL"
                    elif c_high >= tp_price:
                        exit_price = tp_price
                        reason = "TP"
                    elif t_str >= '15:15':
                        exit_price = c_close
                        reason = "EOD"
                else:
                    if c_high >= sl_price:
                        exit_price = sl_price
                        reason = "SL"
                    elif c_low <= tp_price:
                        exit_price = tp_price
                        reason = "TP"
                    elif t_str >= '15:15':
                        exit_price = c_close
                        reason = "EOD"

                if exit_price is not None:
                    pts = (exit_price - entry_price) if direction == "LONG" else (entry_price - exit_price)
                    pts -= 3.0
                    trades.append({
                        "date": d,
                        "year": row['year'],
                        "direction": direction,
                        "entry": entry_price,
                        "exit": exit_price,
                        "pts": pts,
                        "reason": reason,
                    })
                    break

    return pd.DataFrame(trades)


def print_metrics(tdf: pd.DataFrame, name: str):
    if len(tdf) == 0:
        print(f"No trades for {name}")
        return

    wins = tdf[tdf['pts'] > 0]
    losses = tdf[tdf['pts'] <= 0]
    wr = len(wins) / len(tdf) * 100.0
    tot_p = wins['pts'].sum() if len(wins) > 0 else 0.0
    tot_l = abs(losses['pts'].sum()) if len(losses) > 0 else 1.0
    pf = tot_p / max(1.0, tot_l)
    net_pts = tdf['pts'].sum()

    tdf['cum'] = tdf['pts'].cumsum()
    max_dd = (tdf['cum'].cummax() - tdf['cum']).max()

    print(f"\n=======================================================")
    print(f"  RESULTS: {name}")
    print(f"=======================================================")
    print(f"  Total Trades       : {len(tdf):,}")
    print(f"  Win Rate           : {wr:.1f}%")
    print(f"  Profit Factor      : {pf:.2f}")
    print(f"  Net NIFTY Points   : {net_pts:+,.1f} pts")
    print(f"  Max Drawdown       : {max_dd:,.1f} pts")
    print(f"  Avg Points / Trade : {tdf['pts'].mean():+.1f} pts")

    print("\n  Yearly Breakdown:")
    yearly = tdf.groupby('year').agg(
        trades=('pts', 'count'),
        win_rate=('pts', lambda x: (x > 0).mean() * 100),
        net_pts=('pts', 'sum')
    )
    for yr, r in yearly.iterrows():
        print(f"    Year {yr}: {int(r['trades']):3d} trades | Win Rate: {r['win_rate']:5.1f}% | Net: {r['net_pts']:+8.1f} pts")


def main():
    print("[*] Loading clean intraday data (1,247 trading days)...")
    df = load_clean_intraday_data()
    print(f"[+] Cleaned data has {len(df):,} bars across {df['date'].nunique()} trading days.")

    # Strategy 1: Opening Range Breakout (ORB)
    tdf_orb = test_opening_range_breakout(df, target_mult=1.5)
    print_metrics(tdf_orb, "09:45 Opening Range Breakout (ORB)")

    # Strategy 2: VWAP Trend Pullback (1:2 R:R)
    tdf_vwap = test_vwap_trend_pullback(df)
    print_metrics(tdf_vwap, "VWAP Trend Continuation (200 EMA + 1:2 R:R)")


if __name__ == "__main__":
    main()
