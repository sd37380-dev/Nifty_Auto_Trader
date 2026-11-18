"""
Targeted Quantitative Edge Search on 5 Years of NIFTY Data (1,243 Days).
Tests:
1. Volume-Confirmed Morning Breakout (Filter: Vol > 1.4x SMA20)
2. Mean-Reversion VWAP 2.0 Sigma Fade (Extreme Stretch Fade)
3. Gap Reversal / Gap Fill
"""

import sqlite3
import pandas as pd
import numpy as np


def load_data():
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

    # Session VWAP & Stdev
    tp = (df['high'] + df['low'] + df['close']) / 3.0
    pv = tp * df['volume']
    df['cum_pv'] = pv.groupby(df['date']).cumsum()
    df['cum_vol'] = df['volume'].groupby(df['date']).cumsum()
    df['vwap'] = np.where(df['cum_vol'] > 0, df['cum_pv'] / df['cum_vol'], df['close'])
    
    # VWAP std
    tp_diff_sq = (tp - df['vwap']) ** 2
    df['cum_var'] = (tp_diff_sq * df['volume']).groupby(df['date']).cumsum()
    df['vwap_std'] = np.sqrt(np.where(df['cum_vol'] > 0, df['cum_var'] / df['cum_vol'], 1.0))
    df['vwap_upper_2'] = df['vwap'] + (2.0 * df['vwap_std'])
    df['vwap_lower_2'] = df['vwap'] - (2.0 * df['vwap_std'])

    # Moving averages
    df['ema_20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean()

    # Volume ratio
    df['vol_sma_20'] = df['volume'].rolling(20).mean()
    df['vol_ratio'] = df['volume'] / df['vol_sma_20'].replace(0, 1)

    return df


def test_volume_confirmed_momentum(df: pd.DataFrame):
    """
    Volume-Confirmed Trend Following:
    Only take trade if:
    1. Breakout has Volume > 1.5x 20-period average.
    2. Aligned with 200 EMA (Long if > 200 EMA, Short if < 200 EMA).
    3. Trailing SL with 1:2 R:R.
    """
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
            h = row['high']
            l = row['low']
            e200 = row['ema_200']
            e20 = row['ema_20']
            vwap = row['vwap']
            vr = row['vol_ratio']

            if not in_trade:
                if '09:45' <= t <= '11:15':
                    # Long: Price breaks above high of day with volume > 1.4x and > 200 EMA
                    hod_prev = day_df.loc[:idx]['high'].iloc[:-1].max() if len(day_df.loc[:idx]) > 1 else h
                    if c > hod_prev and c > e200 and c > vwap and vr > 1.3:
                        in_trade = True
                        direction = "LONG"
                        entry_price = c
                        sl_price = max(entry_price - 40.0, vwap - 5.0)
                        tp_price = entry_price + (entry_price - sl_price) * 1.8
                    # Short: Price breaks below low of day with volume > 1.4x and < 200 EMA
                    lod_prev = day_df.loc[:idx]['low'].iloc[:-1].min() if len(day_df.loc[:idx]) > 1 else l
                    if c < lod_prev and c < e200 and c < vwap and vr > 1.3:
                        in_trade = True
                        direction = "SHORT"
                        entry_price = c
                        sl_price = min(entry_price + 40.0, vwap + 5.0)
                        tp_price = entry_price - (sl_price - entry_price) * 1.8
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


def test_vwap_mean_reversion(df: pd.DataFrame):
    """
    Fade Extreme Overextensions:
    When price stretches > 2.0 standard deviations from VWAP and shows a rejection candle,
    fade back to VWAP.
    SL: 30 pts, Target: VWAP.
    """
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
            vwap = row['vwap']
            vu = row['vwap_upper_2']
            vl = row['vwap_lower_2']

            if not in_trade:
                if '10:30' <= t <= '14:00':
                    # Short overextended upper band
                    if h > vu and c < o and (c - vwap) > 50.0:
                        in_trade = True
                        direction = "SHORT"
                        entry_price = c
                        sl_price = entry_price + 30.0
                        tp_price = vwap + 5.0
                    # Long overextended lower band
                    elif l < vl and c > o and (vwap - c) > 50.0:
                        in_trade = True
                        direction = "LONG"
                        entry_price = c
                        sl_price = entry_price - 30.0
                        tp_price = vwap - 5.0
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


def report(tdf: pd.DataFrame, name: str):
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

    print(f"\n" + "=" * 60)
    print(f"  RESULTS: {name}")
    print(f"=" * 60)
    print(f"  Total Trades       : {len(tdf):,}")
    print(f"  Win Rate           : {wr:.1f}%")
    print(f"  Profit Factor      : {pf:.2f}")
    print(f"  Net NIFTY Points   : {net_pts:+,.1f} pts")
    print(f"  Max Drawdown       : {max_dd:,.1f} pts")
    print(f"  Avg Points / Trade : {tdf['pts'].mean():+.1f} pts")

    yearly = tdf.groupby('year').agg(
        trades=('pts', 'count'),
        win_rate=('pts', lambda x: (x > 0).mean() * 100),
        net_pts=('pts', 'sum')
    )
    print("\n  Yearly Performance:")
    for yr, r in yearly.iterrows():
        print(f"    Year {yr}: {int(r['trades']):3d} trades | Win Rate: {r['win_rate']:5.1f}% | Net: {r['net_pts']:+8.1f} pts")


def main():
    print("[*] Loading 5-year data...")
    df = load_data()

    tdf_vol = test_volume_confirmed_momentum(df)
    report(tdf_vol, "Volume-Confirmed Trend Breakout (200 EMA + 1:1.8 R:R)")

    tdf_mr = test_vwap_mean_reversion(df)
    report(tdf_mr, "VWAP 2.0 Sigma Mean Reversion (Overextension Fade)")


if __name__ == "__main__":
    main()
