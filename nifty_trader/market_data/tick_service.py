"""
High-Resolution Market Tick Data Service with Dedicated Per-Instrument Databases.

Features:
1. Physically separated local SQLite databases per instrument:
   - NIFTY 50: data/market/nifty_ticks.db
   - BANKNIFTY: data/market/banknifty_ticks.db
   - Global / Other (e.g. GIFT NIFTY): data/market/market_ticks.db
   - WAL (Write-Ahead Logging) enabled on all databases for zero-lock concurrency.
2. Captures granular tick events:
   - Symbol (NIFTY 50, BANKNIFTY, GIFT NIFTY, INDIA VIX, custom options)
   - Price / LTP, Day Open, High, Low, Close, Volume, Change Pts, Change Pct, Bid, Ask
   - High-precision timestamps (IST and UTC)
3. Non-blocking Dual-Persistence to Supabase Cloud:
   - NIFTY ticks stream asynchronously to Supabase PostgreSQL table `public.nifty_ticks`.
   - BANKNIFTY ticks stream asynchronously to Supabase PostgreSQL table `public.banknifty_ticks`.
   - Other ticks stream asynchronously to `public.market_ticks`.
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
    Dedicated Service for high-frequency tick data management with physical separation.
    Maintains independent databases for NIFTY (nifty_ticks.db) and BANKNIFTY (banknifty_ticks.db).
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

        self.nifty_db_path = self.data_dir / "nifty_ticks.db"
        self.banknifty_db_path = self.data_dir / "banknifty_ticks.db"
        self.general_db_path = self.data_dir / "market_ticks.db"

        self._db_lock = threading.Lock()
        self._init_all_dbs()

    def get_db_path(self, symbol: str) -> Path:
        """Resolves the isolated database file path based on instrument symbol."""
        sym = symbol.strip().upper()
        if "BANK" in sym:
            return self.banknifty_db_path
        elif "NIFTY" in sym and "GIFT" not in sym:
            return self.nifty_db_path
        return self.general_db_path

    @contextmanager
    def _get_connection(self, db_path: Path):
        """Yields SQLite connection with WAL enabled and ensures clean closure."""
        conn = sqlite3.connect(str(db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            yield conn
        finally:
            conn.close()

    def _init_db_file(self, db_path: Path) -> None:
        """Initializes schema and indexes on a specific database file."""
        try:
            with self._get_connection(db_path) as conn:
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
            logger.error("Failed to initialize database %s: %s", db_path.name, e)

    def _init_all_dbs(self) -> None:
        """Ensures all isolated tick databases are properly initialized."""
        with self._db_lock:
            for p in [self.nifty_db_path, self.banknifty_db_path, self.general_db_path]:
                self._init_db_file(p)

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
        Records a tick event into the instrument's dedicated database,
        and streams it to Supabase in a non-blocking background task.
        """
        now_utc = datetime.now(timezone.utc)
        now_ist = datetime.now(IST)

        ts_ist = timestamp_ist or now_ist.strftime("%Y-%m-%d %H:%M:%S")
        ts_utc = now_utc.strftime("%Y-%m-%d %H:%M:%S")

        clean_sym = symbol.strip().upper()
        target_db = self.get_db_path(clean_sym)

        tick_id = None
        with self._db_lock:
            try:
                with self._get_connection(target_db) as conn:
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
                            clean_sym,
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
                logger.debug("Failed writing tick to %s: %s", target_db.name, e)

        # Dual-persistence: Non-blocking sync to Supabase
        try:
            from nifty_trader.core.supabase_adapter import get_supabase_adapter
            supa = get_supabase_adapter(self.root_dir)
            if supa.is_enabled:
                supa.sync_tick_data({
                    "timestamp_ist": ts_ist,
                    "timestamp_utc": ts_utc,
                    "symbol": clean_sym,
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
        """Retrieves recent ticks for a symbol from its dedicated isolated database."""
        clean_sym = symbol.strip().upper()
        target_db = self.get_db_path(clean_sym)

        with self._db_lock:
            try:
                with self._get_connection(target_db) as conn:
                    rows = conn.execute(
                        """
                        SELECT id, timestamp_ist, timestamp_utc, symbol, price,
                               open, high, low, close, volume, change_pts, change_pct,
                               bid, ask, created_at
                        FROM market_ticks
                        WHERE symbol = ? OR symbol LIKE ?
                        ORDER BY id DESC
                        LIMIT ?
                        """,
                        (clean_sym, f"%{clean_sym}%", limit),
                    ).fetchall()
                    return [dict(r) for r in rows]
            except Exception as e:
                logger.error("Error querying %s: %s", target_db.name, e)
                return []

    def get_tick_count(self, symbol: str) -> int:
        """Returns total count of ticks in the symbol's dedicated database."""
        clean_sym = symbol.strip().upper()
        target_db = self.get_db_path(clean_sym)

        with self._db_lock:
            try:
                with self._get_connection(target_db) as conn:
                    res = conn.execute(
                        "SELECT COUNT(*) FROM market_ticks WHERE symbol = ? OR symbol LIKE ?",
                        (clean_sym, f"%{clean_sym}%"),
                    ).fetchone()
                    return res[0] if res else 0
            except Exception as e:
                logger.debug("Error getting tick count from %s: %s", target_db.name, e)
                return 0


def get_tick_service(root_dir: Optional[Path] = None) -> TickDataService:
    """Convenience accessor for singleton TickDataService."""
    return TickDataService.get_instance(root_dir=root_dir)
