"""
Automated Backtesting Engine for NIFTY & BANKNIFTY.

Supports multi-year historical backtesting over 5M, 15M, 1H and Daily bars with:
- Zero look-ahead bias (signals generated on candle close, entered on next candle open)
- Realistic execution: slippage, exchange charges, brokerage & STT
- Stop loss, target (fixed or risk-reward), and optional trailing stop loss
- Intraday cutoff exits (15:15 IST) or positional swings
- Multiple battle-tested quantitative strategies (EMA Crossover, Supertrend, Breakout S/R, VWAP Reversion, Gap Fill, Custom Rule Builder)
- Formats outputs for direct visual rendering in Lightweight Charts (candlesticks, visual markers, indicator overlays, equity curves, trade logs)
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Default Database Paths
DEFAULT_MARKET_DB = Path(__file__).resolve().parent.parent.parent / "data" / "hermes_research" / "market_data.db"
CSV_RESEARCH_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "hermes_research" / "banknifty_research"


class AutomatedBacktester:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DEFAULT_MARKET_DB

    @staticmethod
    def get_custom_strategies_dir() -> Path:
        p = Path(__file__).resolve().parent / "custom_strategies"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def list_custom_strategies(self) -> List[Dict[str, Any]]:
        cdir = self.get_custom_strategies_dir()
        files = []
        for f in cdir.glob("*.py"):
            if f.name == "__init__.py":
                continue
            files.append({
                "filename": f.name,
                "name": f.stem.replace("_", " ").title(),
                "path": str(f),
                "modified": datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).strftime("%Y-%m-%d %H:%M"),
                "size_bytes": f.stat().st_size,
            })
        return sorted(files, key=lambda x: x["filename"])

    def read_custom_strategy(self, filename: str) -> str:
        cdir = self.get_custom_strategies_dir()
        safe_name = Path(filename).name
        target = cdir / safe_name
        if not target.exists():
            raise FileNotFoundError(f"Strategy file '{safe_name}' not found.")
        return target.read_text(encoding="utf-8")

    def save_custom_strategy(self, filename: str, code: str) -> Dict[str, Any]:
        cdir = self.get_custom_strategies_dir()
        safe_name = Path(filename).name
        if not safe_name.endswith(".py"):
            safe_name += ".py"
        target = cdir / safe_name
        target.write_text(code, encoding="utf-8")
        return {"status": "ok", "filename": safe_name, "path": str(target)}

    def get_available_datasets(self) -> Dict[str, Any]:
        """Returns metadata about available symbols, timeframes, and date spans."""
        if not self.db_path.exists():
            return {"status": "error", "message": f"Database not found at {self.db_path}"}

        try:
            conn = sqlite3.connect(f"file:{self.db_path.resolve()}?mode=ro", uri=True, timeout=5.0)
            cur = conn.cursor()
            cur.execute("""
                SELECT symbol, timeframe, COUNT(*), MIN(timestamp), MAX(timestamp)
                FROM normalized_bars
                WHERE symbol IN ('NIFTY', 'BANKNIFTY')
                GROUP BY symbol, timeframe
                ORDER BY symbol, timeframe
            """)
            rows = cur.fetchall()
            conn.close()

            datasets = []
            for r in rows:
                datasets.append({
                    "symbol": r[0],
                    "timeframe": r[1],
                    "count": r[2],
                    "start_time": r[3],
                    "end_time": r[4],
                })
            return {"status": "ok", "datasets": datasets}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def load_ohlcv(
        self,
        symbol: str = "NIFTY",
        timeframe: str = "5M",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """Loads historical bars from SQLite or CSV and normalizes columns."""
        symbol = symbol.upper().strip()
        timeframe = timeframe.upper().strip()

        # If CSV files requested for 1H or Daily
        if timeframe in ("1H", "DAILY", "1D"):
            csv_name = f"{symbol}_{'1H_2Y' if timeframe == '1H' else 'DAILY_5Y'}.csv"
            csv_path = CSV_RESEARCH_DIR / csv_name
            if csv_path.exists():
                df = pd.read_csv(csv_path)
                # Map standard columns
                time_col = None
                for c in ["timestamp", "datetime", "date", "Date", "Datetime"]:
                    if c in df.columns:
                        time_col = c
                        break
                if time_col:
                    df["timestamp"] = pd.to_datetime(df[time_col], utc=True, format="ISO8601")
                    df.rename(columns={
                        "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"
                    }, inplace=True)
                    df.sort_values("timestamp", inplace=True)
                    df.reset_index(drop=True, inplace=True)
                    return self._filter_date_range(df, start_date, end_date)

        # Fallback to SQLite normalized_bars
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database {self.db_path} does not exist.")

        conn = sqlite3.connect(f"file:{self.db_path.resolve()}?mode=ro", uri=True, timeout=10.0)
        # Check if the requested timeframe is directly in DB
        db_tf = "5M" if timeframe in ("5M", "5m") else ("15M" if timeframe in ("15M", "15m") else "5M")
        
        query = "SELECT timestamp, open, high, low, close, volume FROM normalized_bars WHERE symbol = ? AND timeframe = ?"
        params = [symbol, db_tf]

        if start_date:
            query += " AND timestamp >= ?"
            params.append(start_date)
        if end_date:
            query += " AND timestamp <= ?"
            params.append(end_date)

        query += " ORDER BY timestamp ASC"

        df = pd.read_sql_query(query, conn, params=params)
        conn.close()

        if df.empty:
            return df

        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601")
        df.sort_values("timestamp", inplace=True)
        df.reset_index(drop=True, inplace=True)

        # Resample if higher timeframe requested (e.g. 15M, 30M, 1H from 5M)
        if timeframe in ("15M", "30M", "1H") and db_tf == "5M":
            rule_map = {"15M": "15min", "30M": "30min", "1H": "1h"}
            rule = rule_map.get(timeframe)
            if rule:
                df.set_index("timestamp", inplace=True)
                resampled = df.resample(rule, label="left", closed="left").agg({
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }).dropna().reset_index()
                return self._filter_date_range(resampled, start_date, end_date)

        return self._filter_date_range(df, start_date, end_date)

    def _filter_date_range(self, df: pd.DataFrame, start_date: Optional[str], end_date: Optional[str]) -> pd.DataFrame:
        if df.empty:
            return df
        if start_date:
            s_dt = pd.to_datetime(start_date, utc=True, format="ISO8601")
            df = df[df["timestamp"] >= s_dt]
        if end_date:
            e_dt = pd.to_datetime(end_date, utc=True, format="ISO8601")
            df = df[df["timestamp"] <= e_dt]
        df.reset_index(drop=True, inplace=True)
        return df

    # =========================================================================
    # Strategy Indicator Computation
    # =========================================================================
    def compute_indicators(self, df: pd.DataFrame, strategy: str, params: Dict[str, Any]) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """Calculates indicators and sets 'long_condition' and 'short_condition' boolean series."""
        df = df.copy()
        df["long_condition"] = False
        df["short_condition"] = False
        overlay_lines = {}

        close = df["close"]
        high = df["high"]
        low = df["low"]

        # Basic True Range / ATR
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr_period = int(params.get("atr_period", 14))
        df["atr"] = tr.rolling(atr_period, min_periods=1).mean()

        # Strategy 1: EMA Crossover
        if strategy == "ema_crossover":
            fast = int(params.get("fast_ema", 9))
            slow = int(params.get("slow_ema", 21))
            df["fast_ema"] = close.ewm(span=fast, adjust=False).mean()
            df["slow_ema"] = close.ewm(span=slow, adjust=False).mean()

            overlay_lines[f"EMA {fast}"] = {"color": "#38bdf8", "col": "fast_ema"}
            overlay_lines[f"EMA {slow}"] = {"color": "#f59e0b", "col": "slow_ema"}

            # Crossover logic
            fast_above = df["fast_ema"] > df["slow_ema"]
            fast_above_prev = fast_above.shift(1).fillna(False).astype(bool)

            bull_cross = fast_above & (~fast_above_prev)
            bear_cross = (~fast_above) & fast_above_prev

            if params.get("use_rsi", False):
                rsi_period = int(params.get("rsi_period", 14))
                df["rsi"] = self._calculate_rsi(close, rsi_period)
                rsi_long_thresh = float(params.get("rsi_long", 50))
                rsi_short_thresh = float(params.get("rsi_short", 50))
                bull_cross = bull_cross & (df["rsi"] >= rsi_long_thresh)
                bear_cross = bear_cross & (df["rsi"] <= rsi_short_thresh)

            direction = params.get("direction", "BOTH").upper()
            if direction in ("BOTH", "LONG_ONLY"):
                df["long_condition"] = bull_cross
            if direction in ("BOTH", "SHORT_ONLY"):
                df["short_condition"] = bear_cross

        # Strategy 2: Supertrend
        elif strategy == "supertrend":
            period = int(params.get("supertrend_period", 10))
            multiplier = float(params.get("supertrend_mult", 3.0))

            hl2 = (high + low) / 2.0
            st_atr = tr.rolling(period, min_periods=1).mean()
            upper_band = hl2 + (multiplier * st_atr)
            lower_band = hl2 - (multiplier * st_atr)

            st = np.zeros(len(df))
            st_dir = np.zeros(len(df))  # 1 for bullish, -1 for bearish

            for i in range(1, len(df)):
                c = close.iloc[i]
                prev_c = close.iloc[i - 1]
                prev_ub = upper_band.iloc[i - 1]
                prev_lb = lower_band.iloc[i - 1]

                # Lower band adjustment
                curr_lb = lower_band.iloc[i]
                if curr_lb > prev_lb or prev_c < prev_lb:
                    pass
                else:
                    curr_lb = prev_lb
                lower_band.iloc[i] = curr_lb

                # Upper band adjustment
                curr_ub = upper_band.iloc[i]
                if curr_ub < prev_ub or prev_c > prev_ub:
                    pass
                else:
                    curr_ub = prev_ub
                upper_band.iloc[i] = curr_ub

                # Direction flip
                prev_dir = st_dir[i - 1]
                if prev_dir == 1:
                    if c < curr_lb:
                        st_dir[i] = -1
                        st[i] = curr_ub
                    else:
                        st_dir[i] = 1
                        st[i] = curr_lb
                else:
                    if c > curr_ub:
                        st_dir[i] = 1
                        st[i] = curr_lb
                    else:
                        st_dir[i] = -1
                        st[i] = curr_ub

            df["supertrend"] = st
            df["st_dir"] = st_dir
            df["st_dir_prev"] = df["st_dir"].shift(1).fillna(0)

            overlay_lines["Supertrend"] = {"color": "#10b981", "col": "supertrend"}

            direction = params.get("direction", "BOTH").upper()
            if direction in ("BOTH", "LONG_ONLY"):
                df["long_condition"] = (df["st_dir"] == 1) & (df["st_dir_prev"] == -1)
            if direction in ("BOTH", "SHORT_ONLY"):
                df["short_condition"] = (df["st_dir"] == -1) & (df["st_dir_prev"] == 1)

        # Strategy 3: Breakout S/R (Donchian Channel)
        elif strategy == "breakout_sr":
            lookback = int(params.get("breakout_lookback", 20))
            df["highest_high"] = high.shift(1).rolling(lookback).max()
            df["lowest_low"] = low.shift(1).rolling(lookback).min()

            overlay_lines[f"Resist {lookback}"] = {"color": "#ef4444", "col": "highest_high"}
            overlay_lines[f"Support {lookback}"] = {"color": "#10b981", "col": "lowest_low"}

            direction = params.get("direction", "BOTH").upper()
            if direction in ("BOTH", "LONG_ONLY"):
                df["long_condition"] = (close > df["highest_high"]) & (close.shift(1) <= df["highest_high"])
            if direction in ("BOTH", "SHORT_ONLY"):
                df["short_condition"] = (close < df["lowest_low"]) & (close.shift(1) >= df["lowest_low"])

        # Strategy 4: VWAP Mean Reversion
        elif strategy == "vwap_reversion":
            # Compute daily cumulative volume-weighted typical price
            df["date"] = df["timestamp"].dt.date
            typical = (high + low + close) / 3.0
            vol = df["volume"].replace(0, 1)

            df["cum_vol"] = vol.groupby(df["date"]).cumsum()
            df["cum_vp"] = (typical * vol).groupby(df["date"]).cumsum()
            df["vwap"] = df["cum_vp"] / df["cum_vol"]
            overlay_lines["VWAP"] = {"color": "#c084fc", "col": "vwap"}

            dev_mult = float(params.get("vwap_dev_mult", 1.5))
            df["vwap_dev"] = df["atr"] * dev_mult

            df["vwap_upper"] = df["vwap"] + df["vwap_dev"]
            df["vwap_lower"] = df["vwap"] - df["vwap_dev"]

            df["rsi"] = self._calculate_rsi(close, 14)

            direction = params.get("direction", "BOTH").upper()
            if direction in ("BOTH", "LONG_ONLY"):
                # Oversold dip below lower VWAP band bouncing back
                df["long_condition"] = (low <= df["vwap_lower"]) & (close > df["vwap_lower"]) & (df["rsi"] < 40)
            if direction in ("BOTH", "SHORT_ONLY"):
                # Overbought spike above upper VWAP band rejecting
                df["short_condition"] = (high >= df["vwap_upper"]) & (close < df["vwap_upper"]) & (df["rsi"] > 60)

        # Strategy 5: Opening Gap Fill Strategy
        elif strategy == "gap_strategy":
            gap_pts = float(params.get("gap_threshold", 30.0))
            strategy_type = params.get("gap_type", "GAP_FILL").upper()

            df["date"] = df["timestamp"].dt.date
            df["time_ist"] = df["timestamp"].dt.tz_convert("Asia/Kolkata").dt.time
            is_first_bar = df["date"] != df["date"].shift(1)
            prev_day_close = close.shift(1).where(is_first_bar).ffill()

            gap = close - prev_day_close

            if strategy_type == "GAP_FILL":
                # If gap up, fade gap (Short towards prev close); if gap down, fade (Long towards prev close)
                df["long_condition"] = is_first_bar & (gap <= -gap_pts)
                df["short_condition"] = is_first_bar & (gap >= gap_pts)
            else:
                # GAP_MOMENTUM
                df["long_condition"] = is_first_bar & (gap >= gap_pts)
                df["short_condition"] = is_first_bar & (gap <= -gap_pts)

        # Strategy 6: Custom Rule Builder
        elif strategy == "custom_rules":
            ind_type = params.get("indicator_type", "EMA").upper()
            fast = int(params.get("fast_period", 9))
            slow = int(params.get("slow_period", 21))

            if ind_type == "SMA":
                df["fast_ma"] = close.rolling(fast).mean()
                df["slow_ma"] = close.rolling(slow).mean()
            else:
                df["fast_ma"] = close.ewm(span=fast, adjust=False).mean()
                df["slow_ma"] = close.ewm(span=slow, adjust=False).mean()

            overlay_lines[f"MA {fast}"] = {"color": "#38bdf8", "col": "fast_ma"}
            overlay_lines[f"MA {slow}"] = {"color": "#f59e0b", "col": "slow_ma"}

            cross_long = (df["fast_ma"] > df["slow_ma"]) & (df["fast_ma"].shift(1) <= df["slow_ma"].shift(1))
            cross_short = (df["fast_ma"] < df["slow_ma"]) & (df["fast_ma"].shift(1) >= df["slow_ma"].shift(1))

            if params.get("use_rsi", True):
                df["rsi"] = self._calculate_rsi(close, int(params.get("rsi_period", 14)))
                rsi_buy = float(params.get("rsi_buy", 45))
                rsi_sell = float(params.get("rsi_sell", 55))
                cross_long = cross_long & (df["rsi"] >= rsi_buy)
                cross_short = cross_short & (df["rsi"] <= rsi_sell)

            direction = params.get("direction", "BOTH").upper()
            if direction in ("BOTH", "LONG_ONLY"):
                df["long_condition"] = cross_long
            if direction in ("BOTH", "SHORT_ONLY"):
                df["short_condition"] = cross_short

        # Strategy 7: Custom Python Strategy (.py file or dynamic code)
        elif strategy in ("custom_py", "custom_file", "custom_strategy"):
            custom_file = params.get("custom_file") or params.get("strategy_file")
            custom_code = params.get("custom_code")

            mod_scope = {
                "np": np,
                "pd": pd,
                "__name__": "__custom_strategy__",
            }
            if custom_code and custom_code.strip():
                exec(custom_code, mod_scope)
            elif custom_file:
                file_path = Path(custom_file)
                if not file_path.is_absolute():
                    custom_dir = Path(__file__).resolve().parent / "custom_strategies"
                    candidate = custom_dir / file_path.name
                    if candidate.exists():
                        file_path = candidate
                    else:
                        file_path = Path(__file__).resolve().parent.parent.parent / custom_file
                if not file_path.exists():
                    raise FileNotFoundError(f"Custom strategy file not found: {custom_file}")
                with open(file_path, "r", encoding="utf-8") as f:
                    code = f.read()
                exec(code, mod_scope)
            else:
                default_path = Path(__file__).resolve().parent / "custom_strategies" / "multi_factor_strategy.py"
                if default_path.exists():
                    with open(default_path, "r", encoding="utf-8") as f:
                        code = f.read()
                    exec(code, mod_scope)
                else:
                    raise ValueError("No custom strategy file (.py) or code provided.")

            entry_fn = mod_scope.get("generate_signals") or mod_scope.get("apply_strategy") or mod_scope.get("calculate_signals")
            if not entry_fn:
                raise AttributeError("Custom strategy file must define a function named 'generate_signals(df, params)'.")

            res = entry_fn(df, params)
            if isinstance(res, tuple):
                df_res, custom_overlays = res
            else:
                df_res = res
                custom_overlays = {}

            if "long_condition" not in df_res.columns or "short_condition" not in df_res.columns:
                raise ValueError("Custom strategy must return df with 'long_condition' and 'short_condition' boolean columns.")

            direction = params.get("direction", "BOTH").upper()
            if direction in ("BOTH", "LONG_ONLY"):
                df["long_condition"] = df_res["long_condition"].fillna(False).astype(bool)
            if direction in ("BOTH", "SHORT_ONLY"):
                df["short_condition"] = df_res["short_condition"].fillna(False).astype(bool)

            palette = ["#38bdf8", "#f59e0b", "#10b981", "#ef4444", "#c084fc", "#ec4899", "#14b8a6"]
            if isinstance(custom_overlays, dict):
                for idx, (name, ov_info) in enumerate(custom_overlays.items()):
                    color = palette[idx % len(palette)]
                    if isinstance(ov_info, dict) and "series" in ov_info:
                        col_name = f"_ov_{abs(hash(name)) % 100000}_{idx}"
                        df[col_name] = ov_info["series"]
                        overlay_lines[name] = {
                            "color": ov_info.get("color", color),
                            "col": col_name,
                        }
                    elif isinstance(ov_info, (pd.Series, np.ndarray, list)):
                        col_name = f"_ov_{abs(hash(name)) % 100000}_{idx}"
                        df[col_name] = ov_info
                        overlay_lines[name] = {
                            "color": color,
                            "col": col_name,
                        }
            elif isinstance(custom_overlays, (list, tuple)):
                for idx, item in enumerate(custom_overlays):
                    color = palette[idx % len(palette)]
                    if isinstance(item, dict):
                        name = item.get("name", f"Overlay {idx+1}")
                        c = item.get("color", color)
                        if "series" in item:
                            col_name = f"_ov_{abs(hash(name)) % 100000}_{idx}"
                            df[col_name] = item["series"]
                            overlay_lines[name] = {"color": c, "col": col_name}
                        elif "col" in item and item["col"] in df.columns:
                            overlay_lines[name] = {"color": c, "col": item["col"]}

        return df, overlay_lines

    def _calculate_rsi(self, series: pd.Series, period: int = 14) -> pd.Series:
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
        avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
        rs = avg_gain / (avg_loss + 1e-9)
        rsi = 100 - (100 / (1 + rs))
        return rsi

    # =========================================================================
    # Backtest Execution Simulator
    # =========================================================================
    def execute_simulation(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        overlay_lines: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Simulates bar-by-bar execution with zero look-ahead bias."""
        if df.empty or len(df) < 5:
            return {"status": "error", "message": "Insufficient bars to simulate."}

        initial_capital = float(params.get("initial_capital", 500000.0))
        capital = initial_capital
        equity_curve = []

        symbol = str(params.get("symbol", "NIFTY")).upper()
        # Lots & lot sizing: NIFTY=65, BANKNIFTY=30
        is_bank = "BANK" in symbol
        lot_size = 30 if is_bank else 65
        lots = int(params.get("lots", 1))
        total_qty = lots * lot_size

        # Options delta approximation or Futures
        exec_instrument = params.get("instrument_mode", "OPTIONS_ATM_DELTA").upper()
        delta = 0.50 if exec_instrument == "OPTIONS_ATM_DELTA" else 1.0

        # SL and Target configuration
        sl_points = float(params.get("sl_points", 40.0))
        target_points = float(params.get("target_points", 80.0))
        trailing_sl = bool(params.get("trailing_sl", False))
        trail_step = float(params.get("trail_step", 20.0))

        # Intraday cutoff
        intraday_exit = bool(params.get("intraday_exit", True))
        cutoff_hour = int(params.get("cutoff_hour", 15))
        cutoff_min = int(params.get("cutoff_min", 15))

        # Costs (NSE standard rates)
        brokerage_per_order = float(params.get("brokerage", 20.0))
        slippage_points = float(params.get("slippage_pts", 0.5))

        trades: List[Dict[str, Any]] = []
        markers: List[Dict[str, Any]] = []

        in_pos = False
        pos_type = None  # "LONG" or "SHORT"
        entry_price = 0.0
        entry_time = None
        entry_bar_idx = 0
        current_sl = 0.0
        current_target = 0.0

        n = len(df)
        times = df["timestamp"].tolist()
        opens = df["open"].to_numpy()
        highs = df["high"].to_numpy()
        lows = df["low"].to_numpy()
        closes = df["close"].to_numpy()
        long_conds = df["long_condition"].to_numpy()
        short_conds = df["short_condition"].to_numpy()

        peak_equity = initial_capital
        max_drawdown_val = 0.0
        max_drawdown_pct = 0.0

        for i in range(n):
            t = times[i]
            o = opens[i]
            h = highs[i]
            l = lows[i]
            c = closes[i]

            t_sec = int(t.timestamp())
            t_ist = t.tz_convert("Asia/Kolkata")
            is_eod = (t_ist.hour > cutoff_hour) or (t_ist.hour == cutoff_hour and t_ist.minute >= cutoff_min)

            # -------------------------------------------------------------
            # 1. Manage Active Position
            # -------------------------------------------------------------
            if in_pos:
                exit_price = None
                exit_reason = None

                if pos_type == "LONG":
                    # Check Stop Loss hit first (conservative fill at SL)
                    if l <= current_sl:
                        exit_price = min(o, current_sl) - slippage_points
                        exit_reason = "STOP_LOSS"
                    # Check Target hit
                    elif h >= current_target:
                        exit_price = max(o, current_target) - slippage_points
                        exit_reason = "TARGET"
                    # Trailing Stop Loss adjustment
                    elif trailing_sl and (c - entry_price) >= trail_step:
                        new_sl = entry_price + ((c - entry_price) - trail_step * 0.5)
                        if new_sl > current_sl:
                            current_sl = new_sl

                elif pos_type == "SHORT":
                    if h >= current_sl:
                        exit_price = max(o, current_sl) + slippage_points
                        exit_reason = "STOP_LOSS"
                    elif l <= current_target:
                        exit_price = min(o, current_target) + slippage_points
                        exit_reason = "TARGET"
                    elif trailing_sl and (entry_price - c) >= trail_step:
                        new_sl = entry_price - ((entry_price - c) - trail_step * 0.5)
                        if new_sl < current_sl:
                            current_sl = new_sl

                # Check Intraday EOD cutoff
                if exit_price is None and intraday_exit and is_eod:
                    exit_price = c - (slippage_points if pos_type == "LONG" else -slippage_points)
                    exit_reason = "EOD_EXIT"

                # Check End of Dataset
                if exit_price is None and i == n - 1:
                    exit_price = c
                    exit_reason = "DATA_END"

                # Process Exit
                if exit_price is not None:
                    if pos_type == "LONG":
                        pts = exit_price - entry_price
                    else:
                        pts = entry_price - exit_price

                    gross_pnl = pts * delta * total_qty
                    # Turnover costs + STT + ₹40 brokerage
                    turnover = (entry_price + exit_price) * total_qty
                    stt = turnover * 0.0002 if exec_instrument != "OPTIONS_ATM_DELTA" else turnover * 0.000625
                    ex_charges = turnover * 0.000019
                    brokerage = brokerage_per_order * 2
                    gst = (brokerage + ex_charges) * 0.18
                    net_cost = brokerage + stt + ex_charges + gst
                    net_pnl = round(gross_pnl - net_cost, 2)

                    capital += net_pnl
                    if capital > peak_equity:
                        peak_equity = capital
                    dd_val = peak_equity - capital
                    dd_pct = (dd_val / peak_equity) * 100 if peak_equity > 0 else 0
                    if dd_val > max_drawdown_val:
                        max_drawdown_val = dd_val
                    if dd_pct > max_drawdown_pct:
                        max_drawdown_pct = dd_pct

                    trade_info = {
                        "id": len(trades) + 1,
                        "type": pos_type,
                        "entry_time": entry_time.strftime("%Y-%m-%d %H:%M"),
                        "entry_time_iso": entry_time.isoformat(),
                        "exit_time": t.strftime("%Y-%m-%d %H:%M"),
                        "exit_time_iso": t.isoformat(),
                        "entry_price": round(entry_price, 2),
                        "exit_price": round(exit_price, 2),
                        "points": round(pts, 2),
                        "gross_pnl": round(gross_pnl, 2),
                        "net_pnl": net_pnl,
                        "exit_reason": exit_reason,
                        "bars_held": i - entry_bar_idx,
                        "running_capital": round(capital, 2),
                    }
                    trades.append(trade_info)

                    # Add Exit Visual Marker
                    is_win = net_pnl >= 0
                    markers.append({
                        "time": t_sec,
                        "position": "aboveBar" if pos_type == "LONG" else "belowBar",
                        "color": "#10b981" if is_win else "#ef4444",
                        "shape": "circle" if exit_reason == "TARGET" else ("square" if exit_reason == "STOP_LOSS" else "arrowDown"),
                        "text": f"{exit_reason} {'+' if pts>=0 else ''}{round(pts, 1)}pts (₹{net_pnl:+,.0f})",
                    })

                    in_pos = False
                    pos_type = None

            # -------------------------------------------------------------
            # 2. Check New Entry (Zero Look-Ahead: signal at bar i-1 -> enter at bar i open)
            # -------------------------------------------------------------
            if not in_pos and i > 0 and (not intraday_exit or not is_eod):
                # Signals were computed at close of previous candle (i - 1)
                sig_long = long_conds[i - 1]
                sig_short = short_conds[i - 1]

                if sig_long:
                    in_pos = True
                    pos_type = "LONG"
                    entry_price = o + slippage_points
                    entry_time = t
                    entry_bar_idx = i
                    current_sl = entry_price - sl_points
                    current_target = entry_price + target_points

                    markers.append({
                        "time": t_sec,
                        "position": "belowBar",
                        "color": "#10b981",
                        "shape": "arrowUp",
                        "text": f"BUY LONG @ ₹{round(entry_price, 1)}",
                    })

                elif sig_short:
                    in_pos = True
                    pos_type = "SHORT"
                    entry_price = o - slippage_points
                    entry_time = t
                    entry_bar_idx = i
                    current_sl = entry_price + sl_points
                    current_target = entry_price - target_points

                    markers.append({
                        "time": t_sec,
                        "position": "aboveBar",
                        "color": "#ef4444",
                        "shape": "arrowDown",
                        "text": f"SELL SHORT @ ₹{round(entry_price, 1)}",
                    })

            # Sample equity curve (every bar or every 10 bars to keep payload concise)
            if i % max(1, n // 1000) == 0 or i == n - 1:
                cur_unrealized = 0.0
                if in_pos:
                    if pos_type == "LONG":
                        cur_unrealized = (c - entry_price) * delta * total_qty
                    else:
                        cur_unrealized = (entry_price - c) * delta * total_qty

                curr_eq = capital + cur_unrealized
                equity_curve.append({
                    "time": t_sec,
                    "value": round(curr_eq, 2),
                })

        # -----------------------------------------------------------------
        # Performance Statistics
        # -----------------------------------------------------------------
        total_trades = int(len(trades))
        winning_trades = [tr for tr in trades if tr["net_pnl"] > 0]
        losing_trades = [tr for tr in trades if tr["net_pnl"] <= 0]
        win_count = int(len(winning_trades))
        loss_count = int(len(losing_trades))
        win_rate = round(float(win_count / total_trades * 100), 2) if total_trades > 0 else 0.0

        total_net_pnl = round(float(capital - initial_capital), 2)
        total_return_pct = round(float(total_net_pnl / initial_capital * 100), 2)

        gross_profit = float(sum(tr["net_pnl"] for tr in winning_trades))
        gross_loss = float(abs(sum(tr["net_pnl"] for tr in losing_trades)))
        profit_factor = round(float(gross_profit / (gross_loss + 1e-9)), 2) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)

        avg_win = round(float(gross_profit / win_count), 2) if win_count > 0 else 0.0
        avg_loss = round(float(gross_loss / loss_count), 2) if loss_count > 0 else 0.0
        realized_rr = round(float(avg_win / (avg_loss + 1e-9)), 2) if avg_loss > 0 else 0.0
        expectancy = round(float(total_net_pnl / total_trades), 2) if total_trades > 0 else 0.0

        # Consecutive streaks
        max_consec_wins = 0
        max_consec_losses = 0
        cur_w = 0
        cur_l = 0
        for tr in trades:
            if tr["net_pnl"] > 0:
                cur_w += 1
                cur_l = 0
                max_consec_wins = max(max_consec_wins, cur_w)
            else:
                cur_l += 1
                cur_w = 0
                max_consec_losses = max(max_consec_losses, cur_l)

        # Build formatted candle series for Lightweight Charts
        # If bars > 5000, we send the most recent 5,000 candles for smooth rendering
        chart_bars_limit = 5000
        candle_slice = df.tail(chart_bars_limit) if len(df) > chart_bars_limit else df

        chart_candles = []
        for _, row in candle_slice.iterrows():
            chart_candles.append({
                "time": int(row["timestamp"].timestamp()),
                "open": round(float(row["open"]), 2),
                "high": round(float(row["high"]), 2),
                "low": round(float(row["low"]), 2),
                "close": round(float(row["close"]), 2),
                "volume": int(row["volume"]) if "volume" in row and not pd.isna(row["volume"]) else 0,
            })

        # Build indicator line series for Lightweight Charts
        formatted_overlays = []
        for name, info in overlay_lines.items():
            col = info["col"]
            if col in candle_slice.columns:
                series_data = []
                for _, row in candle_slice.iterrows():
                    val = row[col]
                    if not pd.isna(val):
                        series_data.append({
                            "time": int(row["timestamp"].timestamp()),
                            "value": round(float(val), 2),
                        })
                formatted_overlays.append({
                    "name": name,
                    "color": info["color"],
                    "data": series_data,
                })

        # Filter markers to match the rendered chart window
        min_chart_time = chart_candles[0]["time"] if chart_candles else 0
        filtered_markers = [m for m in markers if m["time"] >= min_chart_time]

        return {
            "status": "ok",
            "summary": {
                "symbol": symbol,
                "timeframe": params.get("timeframe", "5M"),
                "bars_tested": int(len(df)),
                "start_date": df["timestamp"].iloc[0].strftime("%Y-%m-%d"),
                "end_date": df["timestamp"].iloc[-1].strftime("%Y-%m-%d"),
                "initial_capital": float(initial_capital),
                "final_capital": round(float(capital), 2),
                "net_pnl": float(total_net_pnl),
                "return_pct": float(total_return_pct),
                "total_trades": int(total_trades),
                "winning_trades": int(win_count),
                "losing_trades": int(loss_count),
                "win_rate": float(win_rate),
                "profit_factor": float(profit_factor),
                "avg_win": float(avg_win),
                "avg_loss": float(avg_loss),
                "realized_rr": float(realized_rr),
                "expectancy": float(expectancy),
                "max_drawdown_val": round(float(max_drawdown_val), 2),
                "max_drawdown_pct": round(float(max_drawdown_pct), 2),
                "max_consecutive_wins": int(max_consec_wins),
                "max_consecutive_losses": int(max_consec_losses),
            },
            "equity_curve": equity_curve,
            "candles": chart_candles,
            "markers": filtered_markers,
            "overlays": formatted_overlays,
            "trades": trades,
        }

    # =========================================================================
    # High-Level Run API
    # =========================================================================
    def run(
        self,
        strategy: str = "ema_crossover",
        symbol: str = "NIFTY",
        timeframe: str = "5M",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Main entry point to execute an automated backtest."""
        params = params or {}
        params["symbol"] = symbol
        params["timeframe"] = timeframe

        try:
            df = self.load_ohlcv(symbol, timeframe, start_date, end_date)
            if df.empty:
                return {
                    "status": "error",
                    "message": f"No data found for {symbol} ({timeframe}) in range {start_date or 'ALL'} to {end_date or 'ALL'}",
                }

            df_with_indicators, overlay_lines = self.compute_indicators(df, strategy, params)
            result = self.execute_simulation(df_with_indicators, params, overlay_lines)
            return result
        except Exception as ex:
            logger.exception("Backtest execution failed")
            return {"status": "error", "message": str(ex)}
