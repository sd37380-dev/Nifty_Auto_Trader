"""
Advanced Quantitative Strategy Discovery across 5 Years of NIFTY 15M Data.
Tests institutional regime-filtered setups:
1. Morning / Afternoon Momentum Window (avoiding midday chop)
2. Multi-Timeframe Trend Alignment (200 EMA + 20 EMA slope)
3. Volatility Squeeze Expansion (NR4 / Bollinger squeeze with Volume Surge)
4. Intraday VWAP Break & Retest with ATR Trailing Stop
"""

import sys
from pathlib import Path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import sqlite3
import pandas as pd
import numpy as np


def load_and_prepare_data():
    conn = sqlite3.connect("data/hermes_research/market_data.db")
    query = """
        SELECT timestamp, open, high, low, close, volume
        FROM normalized_bars
        WHERE symbol = 'NIFTY' AND timeframe = '15M'
        ORDER BY timestamp ASC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    df['timestamp'] = pd.to_datetime(df['timestamp'], format='ISO8601')
    df.set_index('timestamp', inplace=True)
    df = df[~df.index.duplicated(keep='first')]

    c = df['close']
    h = df['high']
    l = df['low']
    v = df['volume']

    # Moving Averages
    df['ema_20'] = c.ewm(span=20, adjust=False).mean()
    df['ema_50'] = c.ewm(span=50, adjust=False).mean()
    df['ema_200'] = c.ewm(span=200, adjust=False).mean()
    df['ema_20_slope'] = (df['ema_20'] - df['ema_20'].shift(3)) / df['ema_20'].shift(3) * 100.0

    # ATR 14
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    df['atr_14'] = tr.rolling(14).mean()
    df['atr_sma_20'] = df['atr_14'].rolling(20).mean()

    # Session VWAP
    df['date'] = df.index.date
    df['hour'] = df.index.hour
    df['minute'] = df.index.minute
    tp = (h + l + c) / 3.0
    pv = tp * v
    df['cum_pv'] = pv.groupby(df['date']).cumsum()
    df['cum_vol'] = v.groupby(df['date']).cumsum()
    df['vwap'] = np.where(df['cum_vol'] > 0, df['cum_pv'] / df['cum_vol'], df['ema_20'])

    # Volume ratio
    df['vol_sma_20'] = v.rolling(20).mean()
    df['vol_ratio'] = df['volume'] / df['vol_sma_20'].replace(0, 1)

    # 4-bar candle range compression (NR4 pattern)
    bar_range = h - l
    df['is_nr4'] = (bar_range < bar_range.shift(1)) & (bar_range < bar_range.shift(2)) & (bar_range < bar_range.shift(3))

    # Time filters (IST is UTC + 5:30)
    # 09:30 to 11:15 IST corresponds to 04:00 to 05:45 UTC
    # 13:30 to 15:00 IST corresponds to 08:00 to 09:30 UTC
    # Midday chop zone: 11:30 to 13:15 IST (06:00 to 07:45 UTC)
    df['is_morning_window'] = (df['hour'] == 4) | ((df['hour'] == 5) & (df['minute'] <= 45))
    df['is_afternoon_window'] = (df['hour'] == 8) | ((df['hour'] == 9) & (df['minute'] <= 15))
    df['is_active_window'] = df['is_morning_window'] | df['is_afternoon_window']

    return df.dropna()


def simulate_advanced_strategy(
    df: pd.DataFrame,
    long_condition: pd.Series,
    short_condition: pd.Series,
    name: str,
    rr: float = 2.0,
    sl_atr: float = 1.0,
    breakeven_trigger: float = 1.0, # Move SL to entry after 1:1 gain
):
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    atr = df['atr_14'].values
    dates = df.index
    long_sig = long_condition.values
    short_sig = short_condition.values

    trades = []
    in_trade = False
    direction = None
    entry_p = 0.0
    sl_p = 0.0
    tp_p = 0.0
    initial_risk = 0.0
    entry_i = 0
    moved_be = False

    for i in range(len(df) - 16):
        if not in_trade:
            if long_sig[i]:
                in_trade = True
                direction = "LONG"
                entry_i = i
                entry_p = close[i]
                risk = max(20.0, atr[i] * sl_atr)
                initial_risk = risk
                sl_p = entry_p - risk
                tp_p = entry_p + (risk * rr)
                moved_be = False
            elif short_sig[i]:
                in_trade = True
                direction = "SHORT"
                entry_i = i
                entry_p = close[i]
                risk = max(20.0, atr[i] * sl_atr)
                initial_risk = risk
                sl_p = entry_p + risk
                tp_p = entry_p - (risk * rr)
                moved_be = False
        else:
            bars_held = i - entry_i
            c_high = high[i]
            c_low = low[i]
            exit_p = None
            exit_reason = None

            if direction == "LONG":
                # Check breakeven trailing
                if not moved_be and c_high >= (entry_p + initial_risk * breakeven_trigger):
                    sl_p = entry_p + 2.0 # Breakeven + small buffer
                    moved_be = True

                if c_low <= sl_p:
                    exit_p = sl_p
                    exit_reason = "STOP_LOSS"
                elif c_high >= tp_p:
                    exit_p = tp_p
                    exit_reason = "TAKE_PROFIT"
                elif bars_held >= 16:
                    exit_p = close[i]
                    exit_reason = "TIME_EXIT"
            else:
                # Check breakeven trailing
                if not moved_be and c_low <= (entry_p - initial_risk * breakeven_trigger):
                    sl_p = entry_p - 2.0
                    moved_be = True

                if c_high >= sl_p:
                    exit_p = sl_p
                    exit_reason = "STOP_LOSS"
                elif c_low <= tp_p:
                    exit_p = tp_p
                    exit_reason = "TAKE_PROFIT"
                elif bars_held >= 16:
                    exit_p = close[i]
                    exit_reason = "TIME_EXIT"

            if exit_p is not None:
                pnl = (exit_p - entry_p) if direction == "LONG" else (entry_p - exit_p)
                pnl -= 3.0 # Slippage + brokerage
                trades.append({
                    "entry_time": dates[entry_i],
                    "direction": direction,
                    "entry": entry_p,
                    "exit": exit_p,
                    "pnl": pnl,
                    "reason": exit_reason,
                    "year": dates[entry_i].year,
                })
                in_trade = False

    tdf = pd.DataFrame(trades)
    if len(tdf) == 0:
        return None

    wins = tdf[tdf['pnl'] > 0]
    losses = tdf[tdf['pnl'] <= 0]
    wr = len(wins) / len(tdf) * 100.0
    tot_p = wins['pnl'].sum() if len(wins) > 0 else 0.0
    tot_l = abs(losses['pnl'].sum()) if len(losses) > 0 else 1.0
    pf = tot_p / max(1.0, tot_l)
    net_pts = tdf['pnl'].sum()

    tdf['cum'] = tdf['pnl'].cumsum()
    max_dd = (tdf['cum'].cummax() - tdf['cum']).max()

    annual = tdf.groupby('year')['pnl'].agg(trades='count', net_pts='sum', wr=lambda x: (x > 0).mean() * 100).to_dict(orient='index')

    return {
        "name": name,
        "trades": len(tdf),
        "win_rate": round(wr, 1),
        "profit_factor": round(pf, 2),
        "net_pts": round(net_pts, 1),
        "max_dd": round(max_dd, 1),
        "avg_trade": round(tdf['pnl'].mean(), 1),
        "annual": annual,
    }


def main():
    print("[*] Loading and calculating multi-timeframe indicators...")
    df = load_and_prepare_data()

    print("\n" + "=" * 80)
    print("     TESTING INSTITUTIONAL REGIME-CONDITIONED STRATEGIES (5 YEARS)     ")
    print("=" * 80)

    results = []

    # Model A: Institutional VWAP + 200 EMA Trend Expansion (Active Window Only)
    l1 = (
        df['is_active_window'] &
        (df['close'] > df['ema_200']) &
        (df['close'] > df['vwap']) &
        (df['close'].shift(1) <= df['vwap'].shift(1)) & # Fresh VWAP crossover
        (df['ema_20_slope'] > 0.02) & # Positive momentum slope
        (df['vol_ratio'] > 1.2) # Institutional volume confirmation
    )
    s1 = (
        df['is_active_window'] &
        (df['close'] < df['ema_200']) &
        (df['close'] < df['vwap']) &
        (df['close'].shift(1) >= df['vwap'].shift(1)) & # Fresh VWAP crossover down
        (df['ema_20_slope'] < -0.02) &
        (df['vol_ratio'] > 1.2)
    )
    r1 = simulate_advanced_strategy(df, l1, s1, "1. Institutional VWAP Cross + 200 EMA + Volume Expansion", rr=2.0, sl_atr=1.0)
    if r1: results.append(r1)

    # Model B: NR4 Volatility Compression Breakout (Inside Window Only)
    l2 = (
        df['is_active_window'] &
        df['is_nr4'].shift(1) &
        (df['close'] > df['high'].shift(1)) &
        (df['close'] > df['ema_50']) &
        (df['close'] > df['vwap']) &
        (df['vol_ratio'] > 1.3)
    )
    s2 = (
        df['is_active_window'] &
        df['is_nr4'].shift(1) &
        (df['close'] < df['low'].shift(1)) &
        (df['close'] < df['ema_50']) &
        (df['close'] < df['vwap']) &
        (df['vol_ratio'] > 1.3)
    )
    r2 = simulate_advanced_strategy(df, l2, s2, "2. NR4 Compression Breakout + Volume Surge", rr=2.2, sl_atr=0.9)
    if r2: results.append(r2)

    # Model C: 200 EMA Trend Continuation with 20 EMA Pullback + Trailing Stop
    l3 = (
        df['is_active_window'] &
        (df['close'] > df['ema_200']) &
        (df['ema_50'] > df['ema_200']) &
        (df['low'] <= df['ema_20']) &
        (df['close'] > df['ema_20']) &
        (df['close'] > df['open']) & # Bullish rejection candle
        (df['close'] > df['vwap'])
    )
    s3 = (
        df['is_active_window'] &
        (df['close'] < df['ema_200']) &
        (df['ema_50'] < df['ema_200']) &
        (df['high'] >= df['ema_20']) &
        (df['close'] < df['ema_20']) &
        (df['close'] < df['open']) & # Bearish rejection candle
        (df['close'] < df['vwap'])
    )
    r3 = simulate_advanced_strategy(df, l3, s3, "3. Trend Continuation 20 EMA Pullback + Breakeven Trail", rr=2.0, sl_atr=1.1)
    if r3: results.append(r3)

    # Print results
    print(f"{'Strategy':<55} | {'Trades':<6} | {'Win %':<6} | {'PF':<5} | {'Net Pts':<11} | {'Max DD':<9}")
    print("-" * 100)
    for r in results:
        print(f"{r['name']:<55} | {r['trades']:<6} | {r['win_rate']:>5.1f}% | {r['profit_factor']:>5.2f} | {r['net_pts']:>+9.1f} | {r['max_dd']:>7.1f}")

    print("\n" + "=" * 80)
    best = max(results, key=lambda x: x['net_pts'])
    print(f"[BEST QUANTITATIVE STRATEGY]: {best['name']}")
    print(f"Total Trades: {best['trades']} | Win Rate: {best['win_rate']}% | Profit Factor: {best['profit_factor']}")
    print(f"Net Points Captured: {best['net_pts']:+,} pts | Max Drawdown: {best['max_dd']} pts")
    print(f"Average Profit per Trade: {best['avg_trade']:+,} pts")
    print("-" * 80)
    print("Year-by-Year Robustness Test:")
    for yr, stats in best['annual'].items():
        print(f"  Year {yr}: {stats['trades']} trades | Win Rate: {stats['wr']:.1f}% | Net Points: {stats['net_pts']:+,.1f} pts")


if __name__ == "__main__":
    main()
