"""
Dedicated Option Chain Database Store and Supabase Dual-Persistence Manager.

Features:
1. Maintains a dedicated local SQLite database for option chain snapshots:
   - Path: data/market/option_chain.db
   - Completely separate database file isolated from tick data, spot bars, and paper trades.
   - WAL (Write-Ahead Logging) enabled for non-blocking concurrent reads and fast writes.
2. Persists comprehensive derivatives snapshots:
   - Symbol (NIFTY, BANKNIFTY) & Expiry date
   - Underlying Spot Price & Calculated ATM Strike
   - PCR (Put-Call Ratio), Max Pain strike
   - Total CE OI, Total PE OI
   - Full strike ladder (JSON) including CE/PE LTP, OI, Change in OI, OI Velocity, Buildup, IV
3. Dual-Persistence to Supabase Cloud:
   - Streams snapshots asynchronously to Supabase PostgreSQL table `public.option_chain_snapshots`.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import sqlite3
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Indian Standard Time (UTC + 5:30)
IST = timezone(timedelta(hours=5, minutes=30))


class OptionChainStore:
    """
    Dedicated database manager for option chain snapshots.
    Operates on `data/market/option_chain.db` and synchronizes with Supabase.
    """

    _instance: Optional["OptionChainStore"] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, root_dir: Optional[Path] = None) -> "OptionChainStore":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(root_dir=root_dir)
        return cls._instance

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent.parent
        self.data_dir = self.root_dir / "data" / "market"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "option_chain.db"

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
        """Initializes dedicated option_chain.db tables and indexes."""
        with self._db_lock:
            try:
                with self._get_connection() as conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS option_chain_snapshots (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            snapshot_id TEXT UNIQUE NOT NULL,
                            timestamp_ist TEXT NOT NULL,
                            timestamp_utc TEXT NOT NULL,
                            symbol TEXT NOT NULL,
                            expiry TEXT NOT NULL,
                            spot_price REAL NOT NULL,
                            atm_strike REAL NOT NULL,
                            pcr REAL NOT NULL,
                            max_pain REAL,
                            total_ce_oi INTEGER DEFAULT 0,
                            total_pe_oi INTEGER DEFAULT 0,
                            strikes_data TEXT NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                    """)
                    conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_oc_snapshots_sym_exp
                        ON option_chain_snapshots (symbol, expiry, timestamp_ist DESC);
                    """)
                    conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_oc_snapshots_time
                        ON option_chain_snapshots (timestamp_ist DESC);
                    """)
                    conn.commit()
            except Exception as e:
                logger.error("Failed to initialize option_chain.db: %s", e)

    def save_snapshot(
        self,
        symbol: str,
        expiry: str,
        spot_price: float,
        atm_strike: float,
        pcr: float,
        max_pain: Optional[float] = None,
        total_ce_oi: int = 0,
        total_pe_oi: int = 0,
        strikes: Optional[List[Dict[str, Any]]] = None,
        timestamp_ist: Optional[str] = None,
    ) -> str:
        """
        Saves an option chain snapshot into the dedicated option_chain.db database,
        and streams it to Supabase in a non-blocking background task.
        """
        now_utc = datetime.now(timezone.utc)
        now_ist = datetime.now(IST)

        ts_ist = timestamp_ist or now_ist.strftime("%Y-%m-%d %H:%M:%S")
        ts_utc = now_utc.strftime("%Y-%m-%d %H:%M:%S")
        clean_sym = symbol.strip().upper()
        clean_exp = expiry.strip()

        # Unique snapshot ID
        time_slug = ts_ist.replace(" ", "_").replace(":", "-")
        snapshot_id = f"oc_{clean_sym.lower()}_{clean_exp}_{time_slug}"

        strikes_json = json.dumps(strikes or [])

        with self._db_lock:
            try:
                with self._get_connection() as conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO option_chain_snapshots (
                            snapshot_id, timestamp_ist, timestamp_utc, symbol, expiry,
                            spot_price, atm_strike, pcr, max_pain,
                            total_ce_oi, total_pe_oi, strikes_data
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            snapshot_id,
                            ts_ist,
                            ts_utc,
                            clean_sym,
                            clean_exp,
                            float(spot_price),
                            float(atm_strike),
                            float(pcr),
                            float(max_pain) if max_pain is not None else None,
                            int(total_ce_oi),
                            int(total_pe_oi),
                            strikes_json,
                        ),
                    )
                    conn.commit()
            except Exception as e:
                logger.debug("Failed writing snapshot to option_chain.db: %s", e)

        # Dual-persistence: Non-blocking sync to Supabase
        try:
            from nifty_trader.core.supabase_adapter import get_supabase_adapter
            supa = get_supabase_adapter(self.root_dir)
            if supa.is_enabled:
                supa.sync_option_chain_snapshot({
                    "snapshot_id": snapshot_id,
                    "timestamp_ist": ts_ist,
                    "timestamp_utc": ts_utc,
                    "symbol": clean_sym,
                    "expiry": clean_exp,
                    "spot_price": float(spot_price),
                    "atm_strike": float(atm_strike),
                    "pcr": float(pcr),
                    "max_pain": float(max_pain) if max_pain is not None else None,
                    "total_ce_oi": int(total_ce_oi),
                    "total_pe_oi": int(total_pe_oi),
                    "strikes_data": strikes or [],
                })
        except Exception as supa_err:
            logger.debug("Supabase option chain sync skipped: %s", supa_err)

        return snapshot_id

    def get_latest_snapshot(self, symbol: str, expiry: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Retrieves the most recent option chain snapshot from option_chain.db."""
        with self._db_lock:
            try:
                with self._get_connection() as conn:
                    clean_sym = symbol.strip().upper()
                    if expiry:
                        row = conn.execute(
                            """
                            SELECT snapshot_id, timestamp_ist, timestamp_utc, symbol, expiry,
                                   spot_price, atm_strike, pcr, max_pain, total_ce_oi, total_pe_oi,
                                   strikes_data, created_at
                            FROM option_chain_snapshots
                            WHERE symbol = ? AND expiry = ?
                            ORDER BY id DESC
                            LIMIT 1
                            """,
                            (clean_sym, expiry.strip()),
                        ).fetchone()
                    else:
                        row = conn.execute(
                            """
                            SELECT snapshot_id, timestamp_ist, timestamp_utc, symbol, expiry,
                                   spot_price, atm_strike, pcr, max_pain, total_ce_oi, total_pe_oi,
                                   strikes_data, created_at
                            FROM option_chain_snapshots
                            WHERE symbol = ?
                            ORDER BY id DESC
                            LIMIT 1
                            """,
                            (clean_sym,),
                        ).fetchone()

                    if row:
                        res = dict(row)
                        try:
                            res["strikes"] = json.loads(res.pop("strikes_data"))
                        except Exception:
                            res["strikes"] = []
                        return res
            except Exception as e:
                logger.error("Error fetching latest snapshot from option_chain.db: %s", e)
        return None

    def get_historical_snapshots(
        self, symbol: str, expiry: Optional[str] = None, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Retrieves historical snapshots summaries (excluding heavy strike data for performance)."""
        with self._db_lock:
            try:
                with self._get_connection() as conn:
                    clean_sym = symbol.strip().upper()
                    if expiry:
                        rows = conn.execute(
                            """
                            SELECT snapshot_id, timestamp_ist, timestamp_utc, symbol, expiry,
                                   spot_price, atm_strike, pcr, max_pain, total_ce_oi, total_pe_oi,
                                   created_at
                            FROM option_chain_snapshots
                            WHERE symbol = ? AND expiry = ?
                            ORDER BY id DESC
                            LIMIT ?
                            """,
                            (clean_sym, expiry.strip(), limit),
                        ).fetchall()
                    else:
                        rows = conn.execute(
                            """
                            SELECT snapshot_id, timestamp_ist, timestamp_utc, symbol, expiry,
                                   spot_price, atm_strike, pcr, max_pain, total_ce_oi, total_pe_oi,
                                   created_at
                            FROM option_chain_snapshots
                            WHERE symbol = ?
                            ORDER BY id DESC
                            LIMIT ?
                            """,
                            (clean_sym, limit),
                        ).fetchall()
                    return [dict(r) for r in rows]
            except Exception as e:
                logger.error("Error querying historical snapshots from option_chain.db: %s", e)
                return []

    def get_snapshot_count(self, symbol: Optional[str] = None) -> int:
        """Returns total count of snapshots in option_chain.db."""
        with self._db_lock:
            try:
                with self._get_connection() as conn:
                    if symbol:
                        res = conn.execute(
                            "SELECT COUNT(*) FROM option_chain_snapshots WHERE symbol = ?",
                            (symbol.strip().upper(),),
                        ).fetchone()
                    else:
                        res = conn.execute("SELECT COUNT(*) FROM option_chain_snapshots").fetchone()
                    return res[0] if res else 0
            except Exception as e:
                logger.debug("Error getting snapshot count: %s", e)
                return 0


def get_option_chain_store(root_dir: Optional[Path] = None) -> OptionChainStore:
    """Convenience accessor for singleton OptionChainStore."""
    return OptionChainStore.get_instance(root_dir=root_dir)
