"""
NSE Spot Data Auto-Fetcher and Database Store.

Features:
1. Automatically fetches Spot/Futures data every 5 minutes for:
   - NIFTY 50
   - BANKNIFTY
   - GIFT NIFTY (NSE IX)
2. Strict Market Trading Hours Schedule:
   - Auto-update starts at 09:15 AM IST (09:15:00)
   - Auto-update stops at 03:30 PM IST (15:30:00)
   - Pauses/Standby on Saturdays and Sundays (Weekends)
   - Pauses/Standby on official NSE Declared Trading Holidays
3. Persists Day Open, Day High, Day Low, Day Close/LTP, Previous Close, Change, Volume,
   and Date/Time stamps (IST & UTC) to SQLite database (data/market/nse_spot_data.db).
4. Maintains audit log in data/market/nse_spot_log.txt.
5. Provides multi-instrument telemetry for web dashboard display & historical analysis.
"""

from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional
import httpx

from nifty_trader.market_data.session import MarketSessionManager

logger = logging.getLogger(__name__)

# Indian Standard Time (UTC + 5:30)
IST = timezone(timedelta(hours=5, minutes=30))

# Target Instruments Mapping
INSTRUMENTS_CONFIG = [
    {
        "symbol_key": "NIFTY 50",
        "display_name": "NIFTY 50",
        "tv_ticker": "NSE:NIFTY",
        "yahoo_ticker": "^NSEI",
        "exchange": "NSE",
    },
    {
        "symbol_key": "BANKNIFTY",
        "display_name": "BANKNIFTY",
        "tv_ticker": "NSE:BANKNIFTY",
        "yahoo_ticker": "^NSEBANK",
        "exchange": "NSE",
    },
    {
        "symbol_key": "GIFT NIFTY",
        "display_name": "GIFT NIFTY",
        "tv_ticker": "NSEIX:NIFTY1!",
        "yahoo_ticker": None,
        "exchange": "NSE IX",
    },
]


class NSESpotService:
    """
    Background service for fetching and storing spot & index data
    for NIFTY 50, BANKNIFTY, and GIFT NIFTY at 5-minute intervals.
    Auto-update runs strictly from 09:15 AM to 03:30 PM IST on NSE trading days.
    """

    _instance: Optional["NSESpotService"] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, root_dir: Optional[Path] = None) -> "NSESpotService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(root_dir=root_dir)
        return cls._instance

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent.parent
        self.data_dir = self.root_dir / "data" / "market"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "nse_spot_data.db"
        self.log_path = self.data_dir / "nse_spot_log.txt"

        self.interval_seconds: int = 300  # 5 minutes
        self.is_running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Telemetry State per instrument
        self.latest_spots: Dict[str, Dict[str, Any]] = {}
        self.latest_spot: Optional[Dict[str, Any]] = None  # NIFTY 50 for backward compatibility
        self.last_fetch_time: Optional[str] = None
        self.last_fetch_status: str = "INITIALIZING"
        self.total_fetches: int = 0
        self.next_fetch_time: float = 0.0
        self._daily_levels_cache: Dict[str, Dict[str, float]] = {}
        self._daily_levels_cache_ts: float = 0.0

        self._init_db()
        self._load_latest_from_db()

    def _init_db(self):
        """Initializes SQLite tables and indices for multi-instrument spot records."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS nse_spot_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp_utc TEXT NOT NULL,
                        timestamp_ist TEXT NOT NULL,
                        date TEXT NOT NULL,
                        time TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        spot_price REAL NOT NULL,
                        open_price REAL,
                        high_price REAL,
                        low_price REAL,
                        close_price REAL,
                        previous_close REAL,
                        pdh REAL,
                        pdl REAL,
                        change_pts REAL,
                        change_pct REAL,
                        volume INTEGER,
                        source TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)
                # Migrations if table already existed
                try:
                    conn.execute("ALTER TABLE nse_spot_records ADD COLUMN pdh REAL")
                except Exception:
                    pass
                try:
                    conn.execute("ALTER TABLE nse_spot_records ADD COLUMN pdl REAL")
                except Exception:
                    pass

                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_spot_utc ON nse_spot_records(timestamp_utc)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_spot_sym_utc ON nse_spot_records(symbol, timestamp_utc)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_spot_sym_date ON nse_spot_records(symbol, date)
                """)
        finally:
            conn.close()

    def _fetch_previous_day_levels(self) -> Dict[str, Dict[str, float]]:
        """
        Fetches official Previous Day High (PDH), Previous Day Low (PDL), and Previous Day Close (PDC)
        from daily historical bars. Cached for 1 hour to prevent redundant network queries.
        """
        now_ts = time.time()
        if self._daily_levels_cache and (now_ts - self._daily_levels_cache_ts < 3600):
            return self._daily_levels_cache

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        levels: Dict[str, Dict[str, float]] = {
            "NIFTY 50": {"pdh": 0.0, "pdl": 0.0, "pdc": 0.0},
            "BANKNIFTY": {"pdh": 0.0, "pdl": 0.0, "pdc": 0.0},
            "GIFT NIFTY": {"pdh": 0.0, "pdl": 0.0, "pdc": 0.0},
        }

        for y_sym, sym_name in [("^NSEI", "NIFTY 50"), ("^NSEBANK", "BANKNIFTY")]:
            try:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{y_sym}?interval=1d&range=5d"
                r = httpx.get(url, headers=headers, timeout=6.0)
                if r.status_code == 200:
                    data = r.json()
                    res = data.get("chart", {}).get("result", [{}])[0]
                    quotes = res.get("indicators", {}).get("quote", [{}])[0]
                    highs = quotes.get("high", [])
                    lows = quotes.get("low", [])
                    closes = quotes.get("close", [])
                    valid = [(h, l, c) for h, l, c in zip(highs, lows, closes) if h is not None and c is not None]
                    if len(valid) >= 2:
                        prev = valid[-2]
                        levels[sym_name] = {
                            "pdh": round(float(prev[0]), 2),
                            "pdl": round(float(prev[1]), 2),
                            "pdc": round(float(prev[2]), 2),
                        }
            except Exception as e:
                logger.debug("Failed fetching daily levels for %s: %s", y_sym, e)

        # GIFT NIFTY tracks NIFTY 50 benchmark
        if levels["NIFTY 50"]["pdh"] > 0:
            levels["GIFT NIFTY"] = dict(levels["NIFTY 50"])

        self._daily_levels_cache = levels
        self._daily_levels_cache_ts = now_ts
        return levels

    def _load_latest_from_db(self):
        """Loads most recent spot records for each instrument from SQLite into memory."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            for cfg in INSTRUMENTS_CONFIG:
                sym = cfg["display_name"]
                cur.execute("""
                    SELECT * FROM nse_spot_records WHERE symbol = ? ORDER BY id DESC LIMIT 1
                """, (sym,))
                row = cur.fetchone()
                if row:
                    rec = dict(row)
                    self.latest_spots[sym] = rec
                    if sym == "NIFTY 50":
                        self.latest_spot = rec
                        self.last_fetch_time = rec.get("timestamp_ist")

            if self.latest_spots:
                win_status = MarketSessionManager.get_auto_update_window_status()
                self.last_fetch_status = win_status["badge_status"] if not win_status["active"] else "READY (Loaded from DB)"
        except Exception as e:
            logger.debug("Failed loading latest spot records from db: %s", e)
        finally:
            conn.close()

    def fetch_spot_now(self, is_automated: bool = False) -> Dict[str, Any]:
        """
        Executes query to fetch Day Open, High, Low, Close/Spot for:
        1. NIFTY 50
        2. BANKNIFTY
        3. GIFT NIFTY
        Saves all to SQLite and logs to audit file.
        """
        records: Dict[str, Dict[str, Any]] = {}
        error_msg: Optional[str] = None

        # 1. Primary: TradingView Scanner API (Fetches NIFTY 50, BANKNIFTY, GIFT NIFTY in 1 call)
        try:
            records = self._fetch_from_tradingview()
        except Exception as tv_err:
            logger.warning("TradingView scanner fetch error: %s. Falling back to Yahoo Finance...", tv_err)
            error_msg = str(tv_err)

        # 2. Fallback for NIFTY & BANKNIFTY if TradingView failed
        if not records or "NIFTY 50" not in records or "BANKNIFTY" not in records:
            try:
                yahoo_records = self._fetch_from_yahoo()
                for k, v in yahoo_records.items():
                    if k not in records:
                        records[k] = v
            except Exception as yf_err:
                logger.warning("Yahoo Finance fallback error: %s", yf_err)
                if not error_msg:
                    error_msg = str(yf_err)

        if not records:
            self.last_fetch_status = f"ERROR: {error_msg or 'All fetch providers failed'}"
            if self.latest_spot:
                return {
                    "status": "fallback",
                    "instruments": self.latest_spots,
                    "latest": self.latest_spot,
                }
            raise RuntimeError(f"Could not fetch spot data: {error_msg}")

        # Fetch / attach official Previous Day High (PDH), Low (PDL), and Close (PDC)
        pd_levels = self._fetch_previous_day_levels()

        # Save all records to DB and log
        dt_utc = datetime.now(timezone.utc)
        dt_ist = dt_utc.astimezone(IST)
        now_created = dt_utc.isoformat()

        conn = sqlite3.connect(str(self.db_path))
        try:
            with conn:
                for sym_name, rec in records.items():
                    sym_pd = pd_levels.get(sym_name, {})
                    rec["pdh"] = sym_pd.get("pdh", rec.get("previous_close", 0.0))
                    rec["pdl"] = sym_pd.get("pdl", rec.get("previous_close", 0.0))

                    rec["timestamp_utc"] = rec.get("timestamp_utc") or dt_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
                    rec["timestamp_ist"] = rec.get("timestamp_ist") or dt_ist.strftime("%Y-%m-%d %H:%M:%S IST")
                    rec["date"] = rec.get("date") or dt_ist.strftime("%Y-%m-%d")
                    rec["time"] = rec.get("time") or dt_ist.strftime("%H:%M:%S")
                    rec["created_at"] = now_created

                    conn.execute("""
                        INSERT INTO nse_spot_records (
                            timestamp_utc, timestamp_ist, date, time, symbol,
                            spot_price, open_price, high_price, low_price, close_price,
                            previous_close, pdh, pdl, change_pts, change_pct, volume, source, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        rec["timestamp_utc"],
                        rec["timestamp_ist"],
                        rec["date"],
                        rec["time"],
                        rec["symbol"],
                        rec["spot_price"],
                        rec["open_price"],
                        rec["high_price"],
                        rec["low_price"],
                        rec["close_price"],
                        rec["previous_close"],
                        rec["pdh"],
                        rec["pdl"],
                        rec["change_pts"],
                        rec["change_pct"],
                        rec.get("volume", 0),
                        rec["source"],
                        rec["created_at"],
                    ))
                    self.latest_spots[sym_name] = rec

                    # Dual persistence: sync spot tick to Supabase
                    try:
                        from nifty_trader.core.supabase_adapter import get_supabase_adapter
                        get_supabase_adapter(self.root_dir).sync_spot_record({
                            "timestamp_ist": rec.get("timestamp_ist", ""),
                            "timestamp_utc": rec.get("timestamp_utc", ""),
                            "symbol": rec.get("symbol", ""),
                            "spot_price": rec.get("spot_price", 0.0),
                            "day_open": rec.get("open_price", 0.0),
                            "day_high": rec.get("high_price", 0.0),
                            "day_low": rec.get("low_price", 0.0),
                            "day_close": rec.get("close_price", 0.0),
                            "previous_close": rec.get("previous_close", 0.0),
                            "change_pts": rec.get("change_pts", 0.0),
                            "change_pct": rec.get("change_pct", 0.0),
                            "volume": rec.get("volume", 0),
                            "pdh": rec.get("pdh", 0.0),
                            "pdl": rec.get("pdl", 0.0),
                            "r1": rec.get("r1", 0.0),
                            "r2": rec.get("r2", 0.0),
                            "s1": rec.get("s1", 0.0),
                            "s2": rec.get("s2", 0.0),
                            "pivot": rec.get("pivot", 0.0),
                        })
                    except Exception:
                        pass
        finally:
            conn.close()

        # Update NIFTY 50 backward-compatible field
        if "NIFTY 50" in self.latest_spots:
            self.latest_spot = self.latest_spots["NIFTY 50"]

        self.last_fetch_time = dt_ist.strftime("%Y-%m-%d %H:%M:%S IST")
        self.last_fetch_status = "SUCCESS"
        self.total_fetches += 1
        self.next_fetch_time = time.time() + self.interval_seconds

        # Append to audit text log with PDH & PDL
        tag = "AUTO-UPDATE (09:15-15:30 IST)" if is_automated else "MANUAL FETCH"
        with open(self.log_path, "a", encoding="utf-8") as f:
            for sym, rec in records.items():
                s = "+" if rec["change_pts"] >= 0 else ""
                log_line = (
                    f"[{rec['timestamp_ist']}] 📊 [{tag}] {rec['symbol']}: Close/LTP: ₹{rec['spot_price']:,.2f} "
                    f"({s}{rec['change_pts']:,.2f} / {s}{rec['change_pct']:.2f}%) | "
                    f"Open: ₹{rec['open_price']:,.2f} | High: ₹{rec['high_price']:,.2f} | "
                    f"Low: ₹{rec['low_price']:,.2f} | PDH: ₹{rec.get('pdh', 0):,.2f} | "
                    f"PDL: ₹{rec.get('pdl', 0):,.2f} | PrevClose: ₹{rec['previous_close']:,.2f} | "
                    f"Vol: {rec.get('volume', 0):,} | Src: {rec['source']}\n"
                )
                f.write(log_line)

        # Evaluate Custom Level-Based Strategy triggers on spot update
        try:
            from nifty_trader.simulator.level_strategy import get_level_strategy_manager
            lvl_mgr = get_level_strategy_manager()
            for sym, rec in records.items():
                lvl_mgr.evaluate_spot_update(
                    symbol=sym,
                    spot_price=rec["spot_price"],
                    day_high=rec.get("high_price"),
                    day_low=rec.get("low_price"),
                    day_open=rec.get("open_price"),
                )
        except Exception as lvl_err:
            logger.debug("Level trigger evaluation notice: %s", lvl_err)

        logger.info(
            "Multi-instrument spot fetched (%s): NIFTY=₹%.2f, BANKNIFTY=₹%.2f, GIFT=₹%.2f",
            tag,
            self.latest_spots.get("NIFTY 50", {}).get("spot_price", 0.0),
            self.latest_spots.get("BANKNIFTY", {}).get("spot_price", 0.0),
            self.latest_spots.get("GIFT NIFTY", {}).get("spot_price", 0.0),
        )

        return {
            "status": "ok",
            "trigger": tag,
            "instruments": self.latest_spots,
            "latest": self.latest_spot,
            "timestamp_ist": self.last_fetch_time,
        }

    def _fetch_from_tradingview(self) -> Dict[str, Dict[str, Any]]:
        """
        Fetches live OHLCV for NIFTY 50, BANKNIFTY, and GIFT NIFTY
        via TradingView Scanner API.
        """
        url = "https://scanner.tradingview.com/global/scan"
        cols = ["name", "description", "close", "open", "high", "low", "change", "change_abs", "volume"]
        payload = {
            "symbols": {
                "tickers": ["NSE:NIFTY", "NSE:BANKNIFTY", "NSEIX:NIFTY1!"]
            },
            "columns": cols
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Content-Type": "application/json"
        }

        resp = httpx.post(url, json=payload, headers=headers, timeout=7.0)
        resp.raise_for_status()
        data = resp.json()

        ticker_map = {
            "NSE:NIFTY": "NIFTY 50",
            "NSE:BANKNIFTY": "BANKNIFTY",
            "NSEIX:NIFTY1!": "GIFT NIFTY",
        }

        results: Dict[str, Dict[str, Any]] = {}
        for item in data.get("data", []):
            ticker = item.get("s")
            sym_name = ticker_map.get(ticker)
            if not sym_name:
                continue

            vals = dict(zip(cols, item.get("d", [])))
            close_val = float(vals.get("close") or 0.0)
            open_val = float(vals.get("open") or close_val)
            high_val = float(vals.get("high") or max(close_val, open_val))
            low_val = float(vals.get("low") or min(close_val, open_val))
            chg_abs = float(vals.get("change_abs") or 0.0)
            chg_pct = float(vals.get("change") or 0.0)
            prev_close = round(close_val - chg_abs, 2)
            vol = int(vals.get("volume") or 0)

            results[sym_name] = {
                "symbol": sym_name,
                "spot_price": round(close_val, 2),
                "open_price": round(open_val, 2),
                "high_price": round(high_val, 2),
                "low_price": round(low_val, 2),
                "close_price": round(close_val, 2),
                "previous_close": round(prev_close, 2),
                "change_pts": round(chg_abs, 2),
                "change_pct": round(chg_pct, 2),
                "volume": vol,
                "source": "TRADINGVIEW_SCANNER",
            }

        return results

    def _fetch_from_yahoo(self) -> Dict[str, Dict[str, Any]]:
        """Fallback fetching NIFTY 50 and BANKNIFTY from Yahoo Finance."""
        results: Dict[str, Dict[str, Any]] = {}
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        targets = [
            ("^NSEI", "NIFTY 50"),
            ("^NSEBANK", "BANKNIFTY"),
        ]

        for y_sym, sym_name in targets:
            try:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{y_sym}?interval=5m&range=1d"
                resp = httpx.get(url, headers=headers, timeout=6.0)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                res = data.get("chart", {}).get("result", [{}])[0]
                meta = res.get("meta", {})
                quote = res.get("indicators", {}).get("quote", [{}])[0]

                spot_price = float(meta.get("regularMarketPrice") or 0.0)
                closes = [c for c in quote.get("close", []) if c is not None]
                if spot_price <= 0 and closes:
                    spot_price = float(closes[-1])

                prev_close = float(meta.get("chartPreviousClose") or meta.get("previousClose") or spot_price)
                change_pts = round(spot_price - prev_close, 2)
                change_pct = round((change_pts / prev_close) * 100.0, 2) if prev_close else 0.0

                high_price = float(meta.get("regularMarketDayHigh") or (max(closes) if closes else spot_price))
                low_price = float(meta.get("regularMarketDayLow") or (min(closes) if closes else spot_price))

                opens = [o for o in quote.get("open", []) if o is not None]
                open_price = float(opens[0]) if opens else spot_price
                volume = int(meta.get("regularMarketVolume") or 0)

                results[sym_name] = {
                    "symbol": sym_name,
                    "spot_price": round(spot_price, 2),
                    "open_price": round(open_price, 2),
                    "high_price": round(high_price, 2),
                    "low_price": round(low_price, 2),
                    "close_price": round(spot_price, 2),
                    "previous_close": round(prev_close, 2),
                    "change_pts": change_pts,
                    "change_pct": change_pct,
                    "volume": volume,
                    "source": "YAHOO_FINANCE",
                }
            except Exception as e:
                logger.debug("Yahoo fetch failed for %s: %s", y_sym, e)

        return results

    def get_history(self, limit: int = 50, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieves stored 5-minute spot records from SQLite with optional symbol filter."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            if symbol and symbol.upper() != "ALL":
                cur.execute(
                    "SELECT * FROM nse_spot_records WHERE symbol LIKE ? ORDER BY id DESC LIMIT ?",
                    (f"%{symbol}%", limit),
                )
            else:
                cur.execute(
                    "SELECT * FROM nse_spot_records ORDER BY id DESC LIMIT ?",
                    (limit,),
                )
            rows = [dict(r) for r in cur.fetchall()]
            return rows
        except Exception as e:
            logger.debug("Failed reading spot history: %s", e)
            return []
        finally:
            conn.close()

    def start_auto_fetch(self, interval_seconds: int = 300):
        """Starts automated 5-minute background loop thread with 09:15-15:30 IST schedule."""
        if self.is_running and self._thread and self._thread.is_alive():
            return

        self.interval_seconds = interval_seconds
        self.is_running = True
        self._stop_event.clear()

        # Check market window on startup
        win_status = MarketSessionManager.get_auto_update_window_status()
        if win_status["active"] or not self.latest_spots:
            try:
                self.fetch_spot_now(is_automated=win_status["active"])
            except Exception as ex:
                logger.debug("Startup spot fetch notice: %s", ex)
        else:
            self.last_fetch_status = win_status["badge_status"]

        self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="NSESpotAutoFetch")
        self._thread.start()
        logger.info(
            "⚡ Spot auto-fetch daemon started (09:15–15:30 IST Mon–Fri, excluding weekends & holidays)."
        )

    def stop_auto_fetch(self):
        """Stops the automated fetch loop."""
        self.is_running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("Multi-instrument spot auto-fetch stopped.")

    def _worker_loop(self):
        """
        Background worker strictly respecting Indian market trading hours:
        - Starts auto-update at 09:15 AM IST
        - Stops auto-update at 03:30 PM IST (15:30 IST)
        - Standby on Saturdays, Sundays, and official NSE holidays
        """
        self.next_fetch_time = time.time()
        while not self._stop_event.is_set():
            win_status = MarketSessionManager.get_auto_update_window_status()
            is_active = win_status["active"]

            if not is_active:
                # Outside active market session: Standby mode
                self.last_fetch_status = win_status["badge_status"]
                # Sleep in short slices (10 seconds) so stop events are respected promptly
                if self._stop_event.wait(timeout=10.0):
                    break
                continue

            # Inside active continuous market hours (09:15 to 15:30 IST Mon-Fri)
            sleep_duration = max(0.5, self.next_fetch_time - time.time())
            if self._stop_event.wait(timeout=min(5.0, sleep_duration)):
                break

            if time.time() >= self.next_fetch_time:
                try:
                    self.fetch_spot_now(is_automated=True)
                except Exception as err:
                    logger.debug("Auto-fetch cycle error: %s", err)
                self.next_fetch_time = time.time() + self.interval_seconds

    def calculate_sr_levels(self) -> Dict[str, Dict[str, Any]]:
        """
        Calculates 2 Support (S1, S2) and 2 Resistance (R1, R2) levels
        along with the central Pivot (PP) from the stored historical OHLC database.
        Standard Classic Floor Pivot Equations:
          PP = (High + Low + Close) / 3
          R1 = 2 * PP - Low
          R2 = PP + (High - Low)
          S1 = 2 * PP - High
          S2 = PP - (High - Low)
        """
        levels_map = {}
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            for cfg in INSTRUMENTS_CONFIG:
                sym = cfg["display_name"]
                cur.execute("""
                    SELECT date, spot_price, high_price, low_price, close_price, open_price
                    FROM nse_spot_records
                    WHERE symbol = ? AND high_price > 0 AND low_price > 0
                    ORDER BY id DESC LIMIT 1
                """, (sym,))
                row = cur.fetchone()
                if row:
                    h = float(row["high_price"])
                    l = float(row["low_price"])
                    c = float(row["close_price"] or row["spot_price"])
                    spot = float(row["spot_price"] or c)
                    d = row["date"]

                    pp = round((h + l + c) / 3.0, 2)
                    r1 = round(2.0 * pp - l, 2)
                    r2 = round(pp + (h - l), 2)
                    s1 = round(2.0 * pp - h, 2)
                    s2 = round(pp - (h - l), 2)

                    levels_map[sym] = {
                        "symbol": sym,
                        "date": d,
                        "spot": spot,
                        "high": h,
                        "low": l,
                        "close": c,
                        "pivot": pp,
                        "r1": r1,
                        "r2": r2,
                        "s1": s1,
                        "s2": s2,
                        "r2_dist": round(r2 - spot, 2),
                        "r1_dist": round(r1 - spot, 2),
                        "s1_dist": round(spot - s1, 2),
                        "s2_dist": round(spot - s2, 2),
                    }
        except Exception as e:
            logger.debug("Failed calculating S/R levels: %s", e)
        finally:
            conn.close()
        return levels_map

    def get_dashboard_summary(self) -> Dict[str, Any]:
        """Provides rich multi-instrument telemetry with market window status for web dashboard display."""
        win_status = MarketSessionManager.get_auto_update_window_status()
        is_market_active = win_status["active"]

        seconds_remaining = max(0, int(self.next_fetch_time - time.time())) if (self.is_running and is_market_active) else 0
        mins, secs = divmod(seconds_remaining, 60)
        countdown_str = f"{mins:02d}:{secs:02d}" if is_market_active else "STANDBY"

        display_status = "🟢 AUTO-ACTIVE (09:15–15:30 IST)" if (self.is_running and is_market_active) else win_status["badge_status"]

        sr_levels = self.calculate_sr_levels()
        for sym, rec in self.latest_spots.items():
            if sym in sr_levels:
                rec["sr"] = sr_levels[sym]

        return {
            "status": display_status,
            "is_market_active": is_market_active,
            "market_window": win_status,
            "schedule": "09:15 AM – 03:30 PM IST (Mon–Fri, Excl. Saturdays, Sundays & NSE Holidays)",
            "symbols": [c["display_name"] for c in INSTRUMENTS_CONFIG],
            "instruments": self.latest_spots,
            "latest": self.latest_spot,
            "sr_levels": sr_levels,
            "last_fetch_time": self.last_fetch_time or "Awaiting fetch",
            "last_fetch_status": self.last_fetch_status,
            "total_fetches": self.total_fetches,
            "interval_seconds": self.interval_seconds,
            "countdown_str": countdown_str,
            "seconds_remaining": seconds_remaining,
            "db_path": str(self.db_path),
            "history": self.get_history(limit=18),
        }


def get_spot_service(root_dir: Optional[Path] = None) -> NSESpotService:
    return NSESpotService.get_instance(root_dir=root_dir)
