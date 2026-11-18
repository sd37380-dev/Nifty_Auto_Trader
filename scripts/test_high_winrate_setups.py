"""
Testing High-Win-Rate Edge Models on 5 Years of NIFTY 15M Data:
1. Gap Reversal / Gap Fade (Exhaustion Gap back to Yesterday Close)
2. Range-Bound Credit Spread Proxy (Expiring OTM between Put & Call Walls)
3. Trend Expansion with Dynamic Target
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
    return df


def test_gap_fade_strategy(df: pd.DataFrame):
    """
    Overnight Gap Exhaustion (Gap Fade):
    If NIFTY gaps UP > 0.35% and first 15M bar closes RED (Open > Close):
      -> Sell / Short at 09:30 IST. Target: Previous Day Close (or +40 pts). SL: 25 pts above Day High.
    If NIFTY gaps DOWN > 0.35% and first 15M bar closes GREEN (Close > Open):
      -> Buy / Long at 09:30 IST. Target: Previous Day Close (or +40 pts). SL: 25 pts below Day Low.
    """
    days = df['date'].unique()
    daily = df.groupby('date').agg(pdc=('close', 'last'), pdh=('high', 'max'), pdl=('low', 'min'))
    daily_prev = daily.shift(1)

    trades = []

    for d in days:
        if d not in daily_prev.index:
            continue
        prev_close = daily_prev.loc[d, 'pdc']
        if pd.isna(prev_close):
            continue

        day_df = df[df['date'] == d]
        if len(day_df) < 5:
            continue

        first_bar = day_df.iloc[0]
        f_open = first_bar['open']
        f_close = first_bar['close']
        f_high = first_bar['high']
        f_low = first_bar['low']

        gap_pct = (f_open - prev_close) / prev_close * 100.0

        in_trade = False
        direction = None
        entry_price = 0.0
        sl_price = 0.0
        tp_price = 0.0

        # Gap UP exhaustion: Gapped up > 0.3% but first 15M bar is red
        if gap_pct >= 0.30 and f_close < f_open:
            in_trade = True
            direction = "SHORT"
            entry_price = f_close
            sl_price = f_high + 10.0
            tp_price = max(prev_close, entry_price - 45.0) # Target gap fill or 45 pts
            # Ensure risk is capped at 30 pts
            sl_price = min(sl_price, entry_price + 30.0)

        # Gap DOWN exhaustion: Gapped down > 0.3% but first 15M bar is green
        elif gap_pct <= -0.30 and f_close > f_open:
            in_trade = True
            direction = "LONG"
            entry_price = f_close
            sl_price = f_low - 10.0
            tp_price = min(prev_close, entry_price + 45.0)
            sl_price = max(sl_price, entry_price - 30.0)

        if in_trade:
            # Simulate through rest of the day
            rest_bars = day_df.iloc[1:]
            exit_price = None
            reason = None

            for _, row in rest_bars.iterrows():
                h = row['high']
                l = row['low']
                c = row['close']
                t = row['time_str']

                if direction == "LONG":
                    if l <= sl_price:
                        exit_price = sl_price
                        reason = "SL"
                        break
                    elif h >= tp_price:
                        exit_price = tp_price
                        reason = "TP"
                        break
                    elif t >= '15:15':
                        exit_price = c
                        reason = "EOD"
                        break
                else:
                    if h >= sl_price:
                        exit_price = sl_price
                        reason = "SL"
                        break
                    elif l <= tp_price:
                        exit_price = tp_price
                        reason = "TP"
                        break
                    elif t >= '15:15':
                        exit_price = c
                        reason = "EOD"
                        break

            if exit_price is not None:
                pnl = (exit_price - entry_price) if direction == "LONG" else (entry_price - exit_price)
                pnl -= 3.0
                trades.append({
                    "date": d,
                    "year": first_bar['year'],
                    "direction": direction,
                    "entry": entry_price,
                    "exit": exit_price,
                    "pnl": pnl,
                    "reason": reason,
                })

    tdf = pd.DataFrame(trades)
    return tdf


def test_credit_spread_theta_strategy(df: pd.DataFrame):
    """
    Simulates Defined-Risk Iron Condor / Credit Spread:
    On Sideways/Normal Days (which is 75% of days):
    Sell Put 150 pts below day open, Sell Call 150 pts above day open.
    Win if market expires between Put Strike and Call Strike.
    Loss if market breaches either strike by 30 pts.
    """
    days = df['date'].unique()
    trades = []

    for d in days:
        day_df = df[df['date'] == d]
        if len(day_df) < 15:
            continue

        d_open = day_df.iloc[0]['open']
        d_high = day_df['high'].max()
        d_low = day_df['low'].min()
        d_close = day_df.iloc[-1]['close']

        # Short Strangle / Iron Condor strikes (150 pts OTM)
        put_strike = d_open - 150.0
        call_strike = d_open + 150.0

        # Max loss threshold (breach by 30 pts)
        breached_high = d_high >= (call_strike + 30.0)
        breached_low = d_low <= (put_strike - 30.0)

        year = day_df.iloc[0]['year']

        if not breached_high and not breached_low:
            # Full theta capture: Earn 35 points net premium
            trades.append({"date": d, "year": year, "pnl": 32.0, "result": "WIN"})
        else:
            # Stopped out at max loss: Lose 60 points
            trades.append({"date": d, "year": year, "pnl": -60.0, "result": "LOSS"})

    return pd.DataFrame(trades)


def main():
    df = load_data()

    print("=" * 75)
    print("      HIGH WIN RATE STRATEGY TOURNAMENT (5-YEAR DATA)      ")
    print("=" * 75)

    # Strategy 1: Gap Reversal Exhaustion
    tdf_gap = test_gap_fade_strategy(df)
    if len(tdf_gap) > 0:
        wins = tdf_gap[tdf_gap['pnl'] > 0]
        wr = len(wins) / len(tdf_gap) * 100.0
        net = tdf_gap['pnl'].sum()
        pf = wins['pnl'].sum() / max(1.0, abs(tdf_gap[tdf_gap['pnl'] <= 0]['pnl'].sum()))
        print(f"\n1. Gap Reversal / Gap Fill Strategy:")
        print(f"   Total Trades       : {len(tdf_gap)}")
        print(f"   Win Rate           : {wr:.1f}%")
        print(f"   Profit Factor      : {pf:.2f}")
        print(f"   Net Points Captured: {net:+,.1f} pts")
        yearly = tdf_gap.groupby('year')['pnl'].agg(trades='count', wr=lambda x: (x > 0).mean() * 100, net='sum')
        for yr, r in yearly.iterrows():
            print(f"     Year {yr}: {int(r['trades']):2d} trades | Win Rate: {r['wr']:5.1f}% | Net: {r['net']:+7.1f} pts")

    # Strategy 2: OTM Defined-Risk Theta Spread (Option Selling)
    tdf_spread = test_credit_spread_theta_strategy(df)
    if len(tdf_spread) > 0:
        wins_sp = tdf_spread[tdf_spread['pnl'] > 0]
        wr_sp = len(wins_sp) / len(tdf_spread) * 100.0
        net_sp = tdf_spread['pnl'].sum()
        pf_sp = wins_sp['pnl'].sum() / max(1.0, abs(tdf_spread[tdf_spread['pnl'] <= 0]['pnl'].sum()))
        print(f"\n2. Defined-Risk Theta Option Spread (150 pt OTM):")
        print(f"   Total Sessions     : {len(tdf_spread)}")
        print(f"   Win Rate           : {wr_sp:.1f}%")
        print(f"   Profit Factor      : {pf_sp:.2f}")
        print(f"   Net Points Captured: {net_sp:+,.1f} pts")
        yearly_sp = tdf_spread.groupby('year')['pnl'].agg(trades='count', wr=lambda x: (x > 0).mean() * 100, net='sum')
        for yr, r in yearly_sp.iterrows():
            print(f"     Year {yr}: {int(r['trades']):3d} trades | Win Rate: {r['wr']:5.1f}% | Net: {r['net']:+7.1f} pts")
    print("=" * 75)


if __name__ == "__main__":
    main()
