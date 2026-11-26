"""
Per-Expiry Dedicated Option Chain SQLite Store.

Stores each future expiry's 300-second NSE option chain snapshots in its own
isolated SQLite database file named after the expiry date:
    data/market/option_chain_expiries/<EXPIRY_DATE>.db

Leaves `data/market/option_chain.db` (current-week NiftyTrader) completely untouched.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import re
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


class ExpiryOptionChainStore:
    """
    Manages one isolated SQLite database per expiry date under
    `data/market/option_chain_expiries/<expiry>.db`.
    """

    _instance: Optional["ExpiryOptionChainStore"] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, root_dir: Optional[Path] = None) -> "ExpiryOptionChainStore":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(root_dir=root_dir)
        return cls._instance

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent.parent
        self.base_dir = self.root_dir / "data" / "market" / "option_chain_expiries"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._db_lock = threading.Lock()
        self._initialized_dbs: set[str] = set()

    @staticmethod
    def _sanitize_expiry(expiry: str) -> str:
        """Converts an expiry string (e.g. '08-Dec-2026') into a safe DB filename stem."""
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(expiry or "UNKNOWN").strip())
        return cleaned.strip("-") or "UNKNOWN"

    def get_db_path(self, expiry: str) -> Path:
        """Returns the dedicated SQLite DB path for the given expiry date."""
        return self.base_dir / f"{self._sanitize_expiry(expiry)}.db"

    @contextmanager
    def _get_connection(self, db_path: Path):
        """Yields a WAL-enabled SQLite connection for a specific expiry DB."""
        conn = sqlite3.connect(str(db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            yield conn
        finally:
            conn.close()

    def _ensure_schema(self, db_path: Path) -> None:
        key = str(db_path)
        if key in self._initialized_dbs and db_path.exists():
            return
        with self._get_connection(db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    expiry TEXT NOT NULL,
                    spot_price REAL,
                    atm_strike INTEGER,
                    pcr REAL,
                    max_pain INTEGER,
                    top_ce_strike INTEGER,
                    top_ce_oi INTEGER,
                    top_pe_strike INTEGER,
                    top_pe_oi INTEGER,
                    total_call_oi INTEGER,
                    total_put_oi INTEGER,
                    sentiment TEXT,
                    data_source TEXT,
                    strikes_json TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    captured_epoch REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_snapshots_sym_epoch
                ON snapshots (symbol, captured_epoch DESC)
                """
            )
            conn.commit()
        self._initialized_dbs.add(key)

    def save_snapshot(self, chain_data: Dict[str, Any]) -> Optional[Path]:
        """Saves an expiry option chain snapshot into `<expiry>.db`."""
        expiry = str(chain_data.get("expiry") or "").strip()
        if not expiry:
            return None

        db_path = self.get_db_path(expiry)
        symbol = str(chain_data.get("symbol", "NIFTY")).upper()
        now_ist = chain_data.get("updated_at") or datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        now_epoch = time.time()

        with self._db_lock:
            try:
                self._ensure_schema(db_path)
                with self._get_connection(db_path) as conn:
                    conn.execute(
                        """
                        INSERT INTO snapshots (
                            symbol, expiry, spot_price, atm_strike, pcr, max_pain,
                            top_ce_strike, top_ce_oi, top_pe_strike, top_pe_oi,
                            total_call_oi, total_put_oi, sentiment, data_source,
                            strikes_json, captured_at, captured_epoch
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            symbol,
                            expiry,
                            float(chain_data.get("spot_price") or 0.0),
                            int(chain_data.get("atm_strike") or 0),
                            float(chain_data.get("pcr") or 0.0),
                            int(chain_data.get("max_pain") or 0),
                            chain_data.get("top_ce_strike"),
                            int(chain_data.get("top_ce_oi") or 0),
                            chain_data.get("top_pe_strike"),
                            int(chain_data.get("top_pe_oi") or 0),
                            int(chain_data.get("total_call_oi") or 0),
                            int(chain_data.get("total_put_oi") or 0),
                            str(chain_data.get("sentiment") or ""),
                            str(chain_data.get("data_source") or "NSE Live Option Chain v3 API"),
                            json.dumps(chain_data.get("strikes") or []),
                            now_ist,
                            now_epoch,
                        ),
                    )
                    conn.commit()
                return db_path
            except Exception as ex:
                logger.warning("Failed saving expiry snapshot to %s: %s", db_path, ex)
                return None

    def get_latest_snapshot(self, symbol: str, expiry: str) -> Optional[Dict[str, Any]]:
        """Loads the most recent snapshot for `(symbol, expiry)` from `<expiry>.db`."""
        db_path = self.get_db_path(expiry)
        if not db_path.exists():
            return None
        sym = symbol.upper()
        with self._db_lock:
            try:
                self._ensure_schema(db_path)
                with self._get_connection(db_path) as conn:
                    row = conn.execute(
                        """
                        SELECT * FROM snapshots
                        WHERE symbol = ?
                        ORDER BY captured_epoch DESC
                        LIMIT 1
                        """,
                        (sym,),
                    ).fetchone()
                    if not row:
                        return None
                    return {
                        "symbol": row["symbol"],
                        "expiry": row["expiry"],
                        "spot_price": row["spot_price"],
                        "atm_strike": row["atm_strike"],
                        "pcr": row["pcr"],
                        "max_pain": row["max_pain"],
                        "top_ce_strike": row["top_ce_strike"],
                        "top_ce_oi": row["top_ce_oi"],
                        "top_pe_strike": row["top_pe_strike"],
                        "top_pe_oi": row["top_pe_oi"],
                        "total_call_oi": row["total_call_oi"],
                        "total_put_oi": row["total_put_oi"],
                        "sentiment": row["sentiment"],
                        "data_source": row["data_source"],
                        "updated_at": row["captured_at"],
                        "strikes": json.loads(row["strikes_json"] or "[]"),
                        "db_file": str(db_path),
                    }
            except Exception as ex:
                logger.warning("Failed reading expiry snapshot from %s: %s", db_path, ex)
                return None

    def list_expiry_dbs(self) -> List[str]:
        """Returns sorted list of expiry DB filenames currently stored."""
        if not self.base_dir.exists():
            return []
        return sorted(p.name for p in self.base_dir.glob("*.db"))


def get_expiry_option_chain_store(root_dir: Optional[Path] = None) -> ExpiryOptionChainStore:
    return ExpiryOptionChainStore.get_instance(root_dir=root_dir)
