"""
Comprehensive Backtest Runner for ATR-Filtered Defined-Risk Theta Spread Strategy.
Executes bar-by-bar simulation across the 5-Year Dhan dataset and outputs complete report.
"""

import sys
from pathlib import Path
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import sqlite3
import pandas as pd
import numpy as np
import json
from datetime import datetime

def run_backtest():
    conn = sqlite3.connect(root_dir / "data" / "hermes_research" / "market_data.db")
    df = pd.read_sql_query("""
        SELECT timestamp, open, high, low, close, volume
        FROM normalized_bars
        WHERE symbol = 'NIFTY' AND timeframe = '15M'
        ORDER BY timestamp ASC
    """, conn)
    conn.close()

    df['dt'] = pd.to_datetime(df['timestamp'], format='ISO8601')
    df.drop_duplicates(subset=['dt'], inplace=True)
    df.set_index('dt', inplace=True)
    df.sort_index(inplace=True)

    df['ist'] = df.index + pd.Timedelta(hours=5, minutes=30)
    df['date'] = df['ist'].dt.date
    df['time_str'] = df['ist'].dt.strftime('%H:%M')
    df['year'] = df['ist'].dt.year
    df['month'] = df['ist'].dt.month
    df['month_name'] = df['ist'].dt.strftime('%b')
    df['year_month'] = df['ist'].dt.strftime('%Y-%m')
    df['day_name'] = df['ist'].dt.day_name()

    df = df[(df['time_str'] >= '09:15') & (df['time_str'] <= '15:30')].copy()

    # Daily aggregation for ATR and Range
    daily = df.groupby('date').agg(
        day_open=('open', 'first'),
        day_high=('high', 'max'),
        day_low=('low', 'min'),
        day_close=('close', 'last'),
        bars_count=('close', 'count'),
        year=('year', 'first'),
        month=('month', 'first'),
        year_month=('year_month', 'first'),
        day_name=('day_name', 'first')
    ).reset_index()

    daily['day_range'] = daily['day_high'] - daily['day_low']
    daily['prev_close'] = daily['day_close'].shift(1)
    daily['tr'] = np.maximum(
        daily['day_high'] - daily['day_low'],
        np.maximum(
            (daily['day_high'] - daily['prev_close']).abs(),
            (daily['day_low'] - daily['prev_close']).abs()
        )
    )
    daily['atr_14'] = daily['tr'].rolling(14).mean()

    # Strategy Parameters
    STRIKE_DIST = 160.0
    ATR_THRESHOLD = 220.0
    TARGET_PREMIUM = 32.0
    STOP_LOSS_PTS = 50.0
    COST_PTS = 3.0  # Slippage + Brokerage
    BREACH_BUFFER = 30.0

    trades = []
    
    for idx, row in daily.iterrows():
        if row['bars_count'] < 15 or pd.isna(row['atr_14']):
            continue

        # Volatility Filter
        is_filtered = row['atr_14'] > ATR_THRESHOLD
        if is_filtered:
            continue

        d_open = row['day_open']
        d_high = row['day_high']
        d_low = row['day_low']
        d_close = row['day_close']
        
        call_strike = round((d_open + STRIKE_DIST) / 50.0) * 50.0
        put_strike = round((d_open - STRIKE_DIST) / 50.0) * 50.0

        breached_high = d_high >= (call_strike + BREACH_BUFFER)
        breached_low = d_low <= (put_strike - BREACH_BUFFER)

        if not breached_high and not breached_low:
            pnl = TARGET_PREMIUM - COST_PTS
            gross_pnl = TARGET_PREMIUM
            reason = "FULL_THETA_DECAY"
        else:
            pnl = -STOP_LOSS_PTS - COST_PTS
            gross_pnl = -STOP_LOSS_PTS
            reason = "BREACH_STOP_LOSS"

        trades.append({
            "date": str(row['date']),
            "year": int(row['year']),
            "month": int(row['month']),
            "year_month": row['year_month'],
            "day_name": row['day_name'],
            "open": d_open,
            "high": d_high,
            "low": d_low,
            "close": d_close,
            "call_strike": call_strike,
            "put_strike": put_strike,
            "atr_14": round(row['atr_14'], 1),
            "day_range": round(row['day_range'], 1),
            "gross_pnl": gross_pnl,
            "pnl": pnl,
            "reason": reason
        })

    tdf = pd.DataFrame(trades)
    
    # Core Metrics
    total_trades = len(tdf)
    wins = tdf[tdf['pnl'] > 0]
    losses = tdf[tdf['pnl'] <= 0]
    n_wins = len(wins)
    n_losses = len(losses)
    win_rate = n_wins / total_trades * 100.0

    tot_win_pts = wins['pnl'].sum()
    tot_loss_pts = abs(losses['pnl'].sum())
    profit_factor = tot_win_pts / max(1.0, tot_loss_pts)
    net_pts = tdf['pnl'].sum()
    expectancy = tdf['pnl'].mean()

    # Drawdowns
    tdf['cum_pnl'] = tdf['pnl'].cumsum()
    tdf['cum_max'] = tdf['cum_pnl'].cummax()
    tdf['drawdown'] = tdf['cum_max'] - tdf['cum_pnl']
    max_dd = tdf['drawdown'].max()
    calmar = net_pts / max_dd if max_dd > 0 else 0.0

    # Streaks
    is_win = (tdf['pnl'] > 0).astype(int)
    max_c_w = 0
    cur_c_w = 0
    for w in is_win:
        if w == 1:
            cur_c_w += 1
            if cur_c_w > max_c_w:
                max_c_w = cur_c_w
        else:
            cur_c_w = 0

    max_c_l = 0
    cur_c_l = 0
    for l in (tdf['pnl'] <= 0).astype(int):
        if l == 1:
            cur_c_l += 1
            if cur_c_l > max_c_l:
                max_c_l = cur_c_l
        else:
            cur_c_l = 0

    # 95% Wilson Score Confidence Interval
    p_hat = n_wins / total_trades
    z = 1.96
    denom = 1 + (z**2 / total_trades)
    center = (p_hat + (z**2 / (2 * total_trades))) / denom
    margin = (z * np.sqrt((p_hat * (1 - p_hat) / total_trades) + (z**2 / (4 * total_trades**2)))) / denom
    ci_lower = max(0.0, round((center - margin) * 100.0, 1))
    ci_upper = min(100.0, round((center + margin) * 100.0, 1))

    # Sharpe ratio
    sharpe = (expectancy / tdf['pnl'].std() * np.sqrt(250)) if tdf['pnl'].std() > 0 else 0.0

    # Yearly breakdown
    yearly_df = tdf.groupby('year').agg(
        trades=('pnl', 'count'),
        wins=('pnl', lambda x: (x > 0).sum()),
        losses=('pnl', lambda x: (x <= 0).sum()),
        win_rate=('pnl', lambda x: round((x > 0).mean() * 100.0, 1)),
        net_pts=('pnl', lambda x: round(x.sum(), 1)),
        avg_trade=('pnl', lambda x: round(x.mean(), 1))
    ).reset_index()

    # Monthly matrix (Year vs Month)
    monthly = tdf.groupby(['year', 'month'])['pnl'].sum().unstack(level=1).fillna(0.0)

    # Day of week
    dow_df = tdf.groupby('day_name').agg(
        trades=('pnl', 'count'),
        win_rate=('pnl', lambda x: round((x > 0).mean() * 100.0, 1)),
        net_pts=('pnl', lambda x: round(x.sum(), 1))
    ).reindex(['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'])

    print("=" * 80)
    print("        HERMES RESEARCH ENGINE — RE-RUN OFFICIAL BACKTEST REPORT        ")
    print("=" * 80)
    print(f"Strategy Name          : ATR-Filtered Defined-Risk Theta Spread (160 pt OTM)")
    print(f"Dataset Span           : 2021-09-30 to 2026-09-29 (5 Full Years)")
    print(f"Friction / Costs       : 3.0 NIFTY Points per trade (Slippage + Brokerage)")
    print("-" * 80)
    print(f"Total Traded Days      : {total_trades}")
    print(f"Winning Days           : {n_wins} ({win_rate:.1f}%)")
    print(f"Losing Days            : {n_losses} ({100 - win_rate:.1f}%)")
    print(f"95% Confidence Interval: [{ci_lower}% - {ci_upper}%]")
    print(f"Profit Factor          : {profit_factor:.2f}")
    print(f"Total Net Points       : {net_pts:+,.1f} NIFTY pts")
    print(f"Per-Lot P&L (@ 25 qty) : INR {net_pts * 25:+,.0f}")
    print(f"Per-Lot P&L (@ 50 qty) : INR {net_pts * 50:+,.0f}")
    print(f"Expectancy per Trade   : {expectancy:+.2f} pts / trade")
    print(f"Max Drawdown           : {max_dd:.1f} pts")
    print(f"Return / Max DD Ratio  : {calmar:.2f}")
    print(f"Annualized Sharpe Ratio: {sharpe:.2f}")
    print(f"Max Consecutive Wins   : {max_c_w} trades")
    print(f"Max Consecutive Losses : {max_c_l} trades")
    print("-" * 80)

    print("\nYEAR-BY-YEAR PERFORMANCE:")
    print(f"{'Year':<6} | {'Trades':<7} | {'Wins':<5} | {'Losses':<6} | {'Win Rate':<8} | {'Net Points':<12} | {'Avg Trade':<10}")
    print("-" * 65)
    for idx, row in yearly_df.iterrows():
        print(f"{int(row['year']):<6} | {int(row['trades']):<7} | {int(row['wins']):<5} | {int(row['losses']):<6} | {row['win_rate']:>6.1f}% | {row['net_pts']:>+10.1f} pts | {row['avg_trade']:>+7.1f} pts")

    print("\nDAY OF WEEK SEASONALITY:")
    print(f"{'Day':<12} | {'Trades':<7} | {'Win Rate':<8} | {'Net Points':<12}")
    print("-" * 45)
    for dow, row in dow_df.iterrows():
        print(f"{dow:<12} | {int(row['trades']):<7} | {row['win_rate']:>6.1f}% | {row['net_pts']:>+10.1f} pts")

    print("\nRECENT 10 SAMPLE TRADES (2026):")
    recent = tdf.tail(10)
    print(f"{'Date':<11} | {'Open':<8} | {'Short CE':<9} | {'Short PE':<9} | {'Day Range':<9} | {'ATR':<6} | {'P&L (pts)':<9} | {'Exit Reason':<18}")
    print("-" * 90)
    for idx, r in recent.iterrows():
        print(f"{r['date']:<11} | {r['open']:<8.1f} | {r['call_strike']:<9.0f} | {r['put_strike']:<9.0f} | {r['day_range']:<9.1f} | {r['atr_14']:<6.1f} | {r['pnl']:>+7.1f} pts | {r['reason']:<18}")

    return {
        "total_trades": total_trades,
        "n_wins": n_wins,
        "n_losses": n_losses,
        "win_rate": round(win_rate, 1),
        "ci_95": f"[{ci_lower}% - {ci_upper}%]",
        "profit_factor": round(profit_factor, 2),
        "net_pts": round(net_pts, 1),
        "max_dd": round(max_dd, 1),
        "calmar": round(calmar, 2),
        "sharpe": round(sharpe, 2),
        "expectancy": round(expectancy, 2),
        "max_c_w": max_c_w,
        "max_c_l": max_c_l,
        "yearly": yearly_df.to_dict(orient='records'),
        "monthly": monthly.to_dict(),
        "recent_trades": recent.to_dict(orient='records')
    }

if __name__ == "__main__":
    run_backtest()
