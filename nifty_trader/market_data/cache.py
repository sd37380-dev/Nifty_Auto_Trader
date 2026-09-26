"""
Local SQLite Market Data Cache and Incremental Synchronizer.

Stores historical and live OHLCV candles, manages incremental delta synchronization,
and prevents redundant network requests.
"""

from datetime import datetime, timezone
import logging
from pathlib import Path
import sqlite3
from typing import Dict, List, Optional

from nifty_trader.market_data.models import Candle, Timeframe

logger = logging.getLogger(__name__)


class MarketDataCache:
    """
    Persistent SQLite storage engine for OHLCV candles.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or Path("data/market/market_cache.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS candles (
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL,
                    is_closed INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    PRIMARY KEY (symbol, timeframe, timestamp)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_candles_lookup 
                ON candles(symbol, timeframe, timestamp DESC)
            """)
            conn.commit()

    def store_candles(self, candles: List[Candle]) -> int:
        """
        Inserts or replaces candles in the cache.
        Returns the number of records inserted/updated.
        """
        if not candles:
            return 0

        now_epoch = int(datetime.now(timezone.utc).timestamp())
        records = [
            (
                c.symbol,
                c.timeframe.value,
                int(c.timestamp.timestamp()),
                c.open,
                c.high,
                c.low,
                c.close,
                c.volume,
                1 if c.is_closed else 0,
                c.source,
                now_epoch,
            )
            for c in candles
        ]

        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.executemany("""
                INSERT INTO candles (
                    symbol, timeframe, timestamp, open, high, low, close, volume, is_closed, source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, timeframe, timestamp) DO UPDATE SET
                    open=excluded.open,
                    high=excluded.high,
                    low=excluded.low,
                    close=excluded.close,
                    volume=excluded.volume,
                    is_closed=excluded.is_closed,
                    source=excluded.source
            """, records)
            conn.commit()
            return cur.rowcount

    def get_latest_timestamp(self, symbol: str, timeframe: Timeframe) -> Optional[datetime]:
        """Returns the most recent candle timestamp stored in the cache."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT MAX(timestamp) as max_ts FROM candles
                WHERE symbol = ? AND timeframe = ? AND is_closed = 1
            """, (symbol, timeframe.value))
            row = cur.fetchone()
            if row and row["max_ts"] is not None:
                return datetime.fromtimestamp(row["max_ts"], tz=timezone.utc)
        return None

    def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        limit: int = 100,
        only_closed: bool = True,
    ) -> List[Candle]:
        """Retrieves cached candles sorted chronologically."""
        query = """
            SELECT symbol, timeframe, timestamp, open, high, low, close, volume, is_closed, source
            FROM candles
            WHERE symbol = ? AND timeframe = ?
        """
        params = [symbol, timeframe.value]
        if only_closed:
            query += " AND is_closed = 1"

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            rows = cur.fetchall()

        candles = []
        for r in rows:
            candles.append(Candle(
                symbol=r["symbol"],
                timeframe=Timeframe(r["timeframe"]),
                timestamp=datetime.fromtimestamp(r["timestamp"], tz=timezone.utc),
                open=r["open"],
                high=r["high"],
                low=r["low"],
                close=r["close"],
                volume=r["volume"],
                is_closed=bool(r["is_closed"]),
                source=r["source"],
            ))

        # Return in ascending chronological order
        return list(reversed(candles))

    def get_candle_count(self, symbol: str, timeframe: Timeframe) -> int:
        """Returns count of stored candles for given symbol and timeframe."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT COUNT(*) as cnt FROM candles
                WHERE symbol = ? AND timeframe = ?
            """, (symbol, timeframe.value))
            row = cur.fetchone()
            return row["cnt"] if row else 0

    def get_stats(self, symbol: str = "NIFTY") -> Dict[Timeframe, int]:
        """Returns candle counts per timeframe for the given symbol."""
        from typing import Dict
        return {
            Timeframe.H1: self.get_candle_count(symbol, Timeframe.H1),
            Timeframe.M15: self.get_candle_count(symbol, Timeframe.M15),
        }
