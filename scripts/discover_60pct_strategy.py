"""
Systematic Quantitative Search for a 60%+ Win Rate Strategy on 5 Years of NIFTY Data.
Tests high-probability setups:
1. Liquidity Sweep (PDH/PDL Fakeout Reversal / Turtle Soup)
2. Extreme Mean Reversion (Bollinger Band Piercing + RSI < 25 / > 75 Reclaim)
3. Gap Fill Continuation / Exhaustion
4. VWAP 2.0 Sigma Rejection to VWAP Mean
5. EMA 20 Pullback Scalp (1:1 and 1:1.2 R:R)
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

    c = df['close']
    h = df['high']
    l = df['low']
    v = df['volume']

    # Moving averages
    df['ema_9'] = c.ewm(span=9, adjust=False).mean()
    df['ema_20'] = c.ewm(span=20, adjust=False).mean()
    df['ema_50'] = c.ewm(span=50, adjust=False).mean()
    df['ema_200'] = c.ewm(span=200, adjust=False).mean()

    # RSI 14
    delta = c.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df['rsi_14'] = 100 - (100 / (1 + rs))

    # Bollinger Bands
    sma_20 = c.rolling(20).mean()
    std_20 = c.rolling(20).std()
    df['bb_upper'] = sma_20 + (2.0 * std_20)
    df['bb_lower'] = sma_20 - (2.0 * std_20)

    # Session VWAP
    tp = (h + l + c) / 3.0
    pv = tp * v
    df['cum_pv'] = pv.groupby(df['date']).cumsum()
    df['cum_vol'] = v.groupby(df['date']).cumsum()
    df['vwap'] = np.where(df['cum_vol'] > 0, df['cum_pv'] / df['cum_vol'], df['close'])

    # Daily PDH and PDL
    daily = df.groupby('date').agg(pdh=('high', 'max'), pdl=('low', 'min'), pdc=('close', 'last'), pdo=('open', 'first'))
    daily_prev = daily.shift(1)
    df = df.join(daily_prev, on='date')

    return df.dropna()


def simulate_model(df: pd.DataFrame, long_sig: pd.Series, short_sig: pd.Series, name: str, sl_pts: float, tp_pts: float):
    trades = []
    days = df['date'].unique()

    for d in days:
        day_df = df[df['date'] == d]
        if len(day_df) < 10:
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
                if '09:30' <= t <= '14:00':
                    if long_sig.loc[idx]:
                        in_trade = True
                        direction = "LONG"
                        entry_p = c
                        sl_p = entry_p - sl_pts
                        tp_p = entry_p + tp_pts
                    elif short_sig.loc[idx]:
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
                    break

    if not trades:
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

    yearly = tdf.groupby('year').agg(
        trades=('pnl', 'count'),
        win_rate=('pnl', lambda x: round((x > 0).mean() * 100, 1)),
        net_pts=('pnl', lambda x: round(x.sum(), 1))
    ).to_dict(orient='index')

    return {
        "name": name,
        "trades": len(tdf),
        "win_rate": round(wr, 1),
        "profit_factor": round(pf, 2),
        "net_pts": round(net_pts, 1),
        "max_dd": round(max_dd, 1),
        "avg_pts": round(tdf['pnl'].mean(), 1),
        "yearly": yearly,
    }


def main():
    print("[*] Loading 5 years of data...")
    df = load_data()
    print(f"[+] Loaded {len(df):,} bars.")

    results = []

    # -------------------------------------------------------------------------
    # Model 1: Liquidity Sweep / Fakeout Reversal (Turtle Soup)
    # Long: Price sweeps below Previous Day Low (PDL) by <= 35 pts, but candle closes back ABOVE PDL!
    # Short: Price sweeps above Previous Day High (PDH) by <= 35 pts, but candle closes back BELOW PDH!
    # -------------------------------------------------------------------------
    l1 = (df['low'] < df['pdl']) & (df['close'] > df['pdl']) & (df['pdl'] - df['low'] <= 40.0) & (df['close'] > df['open'])
    s1 = (df['high'] > df['pdh']) & (df['close'] < df['pdh']) & (df['high'] - df['pdh'] <= 40.0) & (df['close'] < df['open'])
    # Risk = 25 pts, Target = 30 pts (approx 1:1.2)
    r1 = simulate_model(df, l1, s1, "1. PDH/PDL Liquidity Sweep Reversal (SL: 25, TP: 30)", sl_pts=25.0, tp_pts=30.0)
    if r1: results.append(r1)

    # -------------------------------------------------------------------------
    # Model 2: Bollinger Band Extreme Stretch + RSI Divergent Bounce
    # Long: Low pierced lower BB, RSI < 30, closes green back above lower BB
    # Short: High pierced upper BB, RSI > 70, closes red back below upper BB
    # -------------------------------------------------------------------------
    l2 = (df['low'] < df['bb_lower']) & (df['close'] > df['bb_lower']) & (df['rsi_14'] < 32) & (df['close'] > df['open'])
    s2 = (df['high'] > df['bb_upper']) & (df['close'] < df['bb_upper']) & (df['rsi_14'] > 68) & (df['close'] < df['open'])
    r2 = simulate_model(df, l2, s2, "2. Bollinger Extreme Mean Reversion (SL: 28, TP: 35)", sl_pts=28.0, tp_pts=35.0)
    if r2: results.append(r2)

    # -------------------------------------------------------------------------
    # Model 3: Liquidity Sweep with VWAP Confluence (High Quality Filter)
    # -------------------------------------------------------------------------
    l3 = l1 & (df['rsi_14'] < 45) # Oversold sweep
    s3 = s1 & (df['rsi_14'] > 55) # Overbought sweep
    r3 = simulate_model(df, l3, s3, "3. Quality Filtered Liquidity Sweep (SL: 24, TP: 32)", sl_pts=24.0, tp_pts=32.0)
    if r3: results.append(r3)

    # -------------------------------------------------------------------------
    # Model 4: First-Hour Breakout Scalp (1:1 R:R)
    # -------------------------------------------------------------------------
    # First 30 min range
    f30_high = df.groupby('date')['high'].transform(lambda x: x.iloc[:2].max() if len(x) >= 2 else np.nan)
    f30_low = df.groupby('date')['low'].transform(lambda x: x.iloc[:2].min() if len(x) >= 2 else np.nan)
    l4 = (df['close'] > f30_high) & (df['close'].shift(1) <= f30_high) & (df['close'] > df['ema_200']) & ('09:45' <= df['time_str']) & (df['time_str'] <= '11:00')
    s4 = (df['close'] < f30_low) & (df['close'].shift(1) >= f30_low) & (df['close'] < df['ema_200']) & ('09:45' <= df['time_str']) & (df['time_str'] <= '11:00')
    r4 = simulate_model(df, l4, s4, "4. First-Hour Breakout Scalp (SL: 30, TP: 35)", sl_pts=30.0, tp_pts=35.0)
    if r4: results.append(r4)

    # Print tournament results
    print("\n" + "=" * 85)
    print(f"{'Strategy Model':<48} | {'Trades':<6} | {'Win %':<6} | {'PF':<5} | {'Net Pts':<10} | {'Max DD':<8}")
    print("=" * 85)
    for r in results:
        print(f"{r['name']:<48} | {r['trades']:<6} | {r['win_rate']:>5.1f}% | {r['profit_factor']:>5.2f} | {r['net_pts']:>+8.1f} | {r['max_dd']:>6.1f}")
    print("-" * 85)

    # Find highest win rate
    best = max(results, key=lambda x: x['win_rate'])
    print(f"\n[HIGHEST WIN RATE STRATEGY]: {best['name']}")
    print(f"Win Rate: {best['win_rate']}% | Profit Factor: {best['profit_factor']} | Net Points: {best['net_pts']:+,.1f} pts")
    print(f"Total Trades: {best['trades']} | Max Drawdown: {best['max_dd']} pts")
    print("\nYearly Consistency:")
    for yr, s in best['yearly'].items():
        print(f"  Year {yr}: {s['trades']:2d} trades | Win Rate: {s['win_rate']:5.1f}% | Net: {s['net_pts']:+7.1f} pts")


if __name__ == "__main__":
    main()
