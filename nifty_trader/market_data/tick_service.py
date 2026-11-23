"""
High-Resolution Market Tick Data Service and Dedicated Database Store.

Features:
1. Maintains a dedicated local SQLite database for tick data:
   - Path: data/market/market_ticks.db
   - WAL (Write-Ahead Logging) enabled for microsecond writes and concurrent reads.
   - Completely separate database file isolated from spot bars, option chains, and paper trades.
2. Captures granular tick events:
   - Symbol (NIFTY 50, BANKNIFTY, GIFT NIFTY, INDIA VIX, custom options)
   - Price / LTP, Day Open, High, Low, Close, Volume, Change Pts, Change Pct, Bid, Ask
   - High-precision timestamps (IST and UTC)
3. Non-blocking Dual-Persistence to Supabase Cloud:
   - Streams ticks asynchronously to Supabase PostgreSQL table `public.market_ticks`.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import sqlite3
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Indian Standard Time (UTC + 5:30)
IST = timezone(timedelta(hours=5, minutes=30))


class TickDataService:
    """
    Dedicated Service for high-frequency tick data management.
    Stores ticks in a dedicated SQLite database (data/market/market_ticks.db)
    and non-blockingly synchronizes with Supabase Cloud table `market_ticks`.
    """

    _instance: Optional["TickDataService"] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, root_dir: Optional[Path] = None) -> "TickDataService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(root_dir=root_dir)
        return cls._instance

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent.parent
        self.data_dir = self.root_dir / "data" / "market"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "market_ticks.db"

        self._db_lock = threading.Lock()
        self._init_db()

    @contextmanager
    def _get_connection(self):
        """Yields SQLite connection with WAL enabled and ensures clean closure."""
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Initializes dedicated tick database schema and indexes."""
        with self._db_lock:
            try:
                with self._get_connection() as conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS market_ticks (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            timestamp_ist TEXT NOT NULL,
                            timestamp_utc TEXT NOT NULL,
                            symbol TEXT NOT NULL,
                            price REAL NOT NULL,
                            open REAL,
                            high REAL,
                            low REAL,
                            close REAL,
                            volume INTEGER DEFAULT 0,
                            change_pts REAL DEFAULT 0.0,
                            change_pct REAL DEFAULT 0.0,
                            bid REAL DEFAULT 0.0,
                            ask REAL DEFAULT 0.0,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                    """)
                    conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_market_ticks_sym_time 
                        ON market_ticks (symbol, timestamp_ist DESC);
                    """)
                    conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_market_ticks_created 
                        ON market_ticks (created_at DESC);
                    """)
                    conn.commit()
            except Exception as e:
                logger.error("Failed to initialize market_ticks.db: %s", e)

    def record_tick(
        self,
        symbol: str,
        price: float,
        open_price: Optional[float] = None,
        high_price: Optional[float] = None,
        low_price: Optional[float] = None,
        close_price: Optional[float] = None,
        volume: int = 0,
        change_pts: float = 0.0,
        change_pct: float = 0.0,
        bid: float = 0.0,
        ask: float = 0.0,
        timestamp_ist: Optional[str] = None,
    ) -> Optional[int]:
        """
        Records a tick event into the dedicated tick database,
        and streams it to Supabase in a non-blocking background task.
        """
        now_utc = datetime.now(timezone.utc)
        now_ist = datetime.now(IST)

        ts_ist = timestamp_ist or now_ist.strftime("%Y-%m-%d %H:%M:%S")
        ts_utc = now_utc.strftime("%Y-%m-%d %H:%M:%S")

        tick_id = None
        with self._db_lock:
            try:
                with self._get_connection() as conn:
                    cur = conn.execute(
                        """
                        INSERT INTO market_ticks (
                            timestamp_ist, timestamp_utc, symbol, price,
                            open, high, low, close, volume,
                            change_pts, change_pct, bid, ask
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            ts_ist,
                            ts_utc,
                            symbol.strip().upper(),
                            float(price),
                            float(open_price) if open_price is not None else float(price),
                            float(high_price) if high_price is not None else float(price),
                            float(low_price) if low_price is not None else float(price),
                            float(close_price) if close_price is not None else float(price),
                            int(volume),
                            float(change_pts),
                            float(change_pct),
                            float(bid),
                            float(ask),
                        ),
                    )
                    conn.commit()
                    tick_id = cur.lastrowid
            except Exception as e:
                logger.debug("Failed writing tick to market_ticks.db: %s", e)

        # Dual-persistence: Non-blocking sync to Supabase
        try:
            from nifty_trader.core.supabase_adapter import get_supabase_adapter
            supa = get_supabase_adapter(self.root_dir)
            if supa.is_enabled:
                supa.sync_tick_data({
                    "timestamp_ist": ts_ist,
                    "timestamp_utc": ts_utc,
                    "symbol": symbol.strip().upper(),
                    "price": float(price),
                    "open": float(open_price) if open_price is not None else float(price),
                    "high": float(high_price) if high_price is not None else float(price),
                    "low": float(low_price) if low_price is not None else float(price),
                    "close": float(close_price) if close_price is not None else float(price),
                    "volume": int(volume),
                    "change_pts": float(change_pts),
                    "change_pct": float(change_pct),
                    "bid": float(bid),
                    "ask": float(ask),
                })
        except Exception as supa_err:
            logger.debug("Supabase tick sync skipped: %s", supa_err)

        return tick_id

    def get_recent_ticks(self, symbol: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieves recent ticks for a symbol ordered from latest to oldest."""
        with self._db_lock:
            try:
                with self._get_connection() as conn:
                    rows = conn.execute(
                        """
                        SELECT id, timestamp_ist, timestamp_utc, symbol, price,
                               open, high, low, close, volume, change_pts, change_pct,
                               bid, ask, created_at
                        FROM market_ticks
                        WHERE symbol = ?
                        ORDER BY id DESC
                        LIMIT ?
                        """,
                        (symbol.strip().upper(), limit),
                    ).fetchall()
                    return [dict(r) for r in rows]
            except Exception as e:
                logger.error("Error querying market_ticks.db: %s", e)
                return []

    def get_tick_count(self, symbol: Optional[str] = None) -> int:
        """Returns total count of ticks in the dedicated database."""
        with self._db_lock:
            try:
                with self._get_connection() as conn:
                    if symbol:
                        res = conn.execute(
                            "SELECT COUNT(*) FROM market_ticks WHERE symbol = ?",
                            (symbol.strip().upper(),),
                        ).fetchone()
                    else:
                        res = conn.execute("SELECT COUNT(*) FROM market_ticks").fetchone()
                    return res[0] if res else 0
            except Exception as e:
                logger.debug("Error getting tick count: %s", e)
                return 0


def get_tick_service(root_dir: Optional[Path] = None) -> TickDataService:
    """Convenience accessor for singleton TickDataService."""
    return TickDataService.get_instance(root_dir=root_dir)
