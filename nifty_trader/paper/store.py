"""
SQLite Persistence Store for Paper Trading Lifecycle & Audit Trail.

Persists paper trade orders, positions, and reconciliation events.
Database: data/paper_trading/paper_trades.db
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional
from nifty_trader.paper.contracts import (
    PaperAction,
    PaperOptionType,
    PaperOrderStatus,
    PaperPosition,
    PaperPositionStatus,
    PaperTradeOrder,
    ReconciliationDiscrepancy,
)

logger = logging.getLogger(__name__)


class PaperTradeStore:
    """Thread-safe SQLite store for paper trades, positions, and reconciliation logs."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or Path("data/paper_trading/paper_trades.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS paper_orders (
                    order_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    idempotency_key TEXT UNIQUE NOT NULL,
                    symbol TEXT NOT NULL,
                    expiry TEXT NOT NULL,
                    strike REAL NOT NULL,
                    option_type TEXT NOT NULL,
                    action TEXT NOT NULL,
                    lots INTEGER NOT NULL,
                    quantity INTEGER NOT NULL,
                    entry_price REAL,
                    status TEXT NOT NULL,
                    status_reason TEXT,
                    pre_execution_screenshot TEXT,
                    post_execution_screenshot TEXT,
                    submitted_at TEXT NOT NULL,
                    verified_at TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS paper_positions (
                    position_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    expiry TEXT NOT NULL,
                    strike REAL NOT NULL,
                    option_type TEXT NOT NULL,
                    action TEXT NOT NULL,
                    lots INTEGER NOT NULL,
                    quantity INTEGER NOT NULL,
                    avg_price REAL NOT NULL,
                    current_ltp REAL NOT NULL,
                    unrealized_pnl REAL NOT NULL,
                    pnl_percentage REAL NOT NULL,
                    realized_pnl REAL NOT NULL,
                    status TEXT NOT NULL,
                    first_detected_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    closed_at TEXT,
                    exit_price REAL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS paper_reconciliations (
                    discrepancy_id TEXT PRIMARY KEY,
                    discrepancy_type TEXT NOT NULL,
                    hermes_state TEXT,
                    sensibull_state TEXT,
                    resolution_action TEXT NOT NULL,
                    detected_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def save_order(self, order: PaperTradeOrder) -> None:
        """Saves or updates a paper trade order."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO paper_orders (
                    order_id, request_id, idempotency_key, symbol, expiry, strike,
                    option_type, action, lots, quantity, entry_price, status, status_reason,
                    pre_execution_screenshot, post_execution_screenshot, submitted_at, verified_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                order.order_id,
                order.request_id,
                order.idempotency_key,
                order.symbol,
                order.expiry,
                order.strike,
                order.option_type.value,
                order.action.value,
                order.lots,
                order.quantity,
                order.entry_price,
                order.status.value,
                order.status_reason,
                order.pre_execution_screenshot,
                order.post_execution_screenshot,
                order.submitted_at.isoformat(),
                order.verified_at.isoformat() if order.verified_at else None,
            ))
            conn.commit()

    def get_order_by_idempotency_key(self, idempotency_key: str) -> Optional[PaperTradeOrder]:
        """Checks if an order with this idempotency key already exists."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM paper_orders WHERE idempotency_key = ?", (idempotency_key,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_order(row)

    def save_position(self, pos: PaperPosition) -> None:
        """Saves or updates a paper position."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO paper_positions (
                    position_id, symbol, expiry, strike, option_type, action, lots, quantity,
                    avg_price, current_ltp, unrealized_pnl, pnl_percentage, realized_pnl,
                    status, first_detected_at, updated_at, closed_at, exit_price
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pos.position_id,
                pos.symbol,
                pos.expiry,
                pos.strike,
                pos.option_type.value,
                pos.action.value,
                pos.lots,
                pos.quantity,
                pos.avg_price,
                pos.current_ltp,
                pos.unrealized_pnl,
                pos.pnl_percentage,
                pos.realized_pnl,
                pos.status.value,
                pos.first_detected_at.isoformat(),
                pos.updated_at.isoformat(),
                pos.closed_at.isoformat() if pos.closed_at else None,
                pos.exit_price,
            ))
            conn.commit()

    def get_open_positions(self) -> List[PaperPosition]:
        """Retrieves all currently OPEN paper positions."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM paper_positions WHERE status = 'OPEN'")
            return [self._row_to_position(r) for r in cursor.fetchall()]

    def get_position(self, position_id: str) -> Optional[PaperPosition]:
        """Retrieves a position by position_id."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM paper_positions WHERE position_id = ?", (position_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_position(row)

    def get_all_positions(self, limit: int = 100) -> List[PaperPosition]:
        """Retrieves all paper positions ordered by first_detected_at desc."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM paper_positions ORDER BY first_detected_at DESC LIMIT ?", (limit,))
            return [self._row_to_position(r) for r in cursor.fetchall()]

    def get_order(self, order_id: str) -> Optional[PaperTradeOrder]:
        """Retrieves an order by order_id."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM paper_orders WHERE order_id = ?", (order_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_order(row)

    def save_reconciliation(self, disc: ReconciliationDiscrepancy) -> None:
        """Logs a reconciliation event."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO paper_reconciliations (
                    discrepancy_id, discrepancy_type, hermes_state, sensibull_state,
                    resolution_action, detected_at
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                disc.discrepancy_id,
                disc.discrepancy_type,
                json.dumps(disc.hermes_state) if disc.hermes_state else None,
                json.dumps(disc.sensibull_state) if disc.sensibull_state else None,
                disc.resolution_action,
                disc.detected_at.isoformat(),
            ))
            conn.commit()

    def get_recent_orders(self, limit: int = 10) -> List[PaperTradeOrder]:
        """Retrieves recent orders ordered by submitted_at desc."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM paper_orders ORDER BY submitted_at DESC LIMIT ?", (limit,))
            return [self._row_to_order(r) for r in cursor.fetchall()]

    def _row_to_order(self, row: sqlite3.Row) -> PaperTradeOrder:
        return PaperTradeOrder(
            order_id=row["order_id"],
            request_id=row["request_id"],
            idempotency_key=row["idempotency_key"],
            symbol=row["symbol"],
            expiry=row["expiry"],
            strike=row["strike"],
            option_type=PaperOptionType(row["option_type"]),
            action=PaperAction(row["action"]),
            lots=row["lots"],
            quantity=row["quantity"],
            entry_price=row["entry_price"],
            status=PaperOrderStatus(row["status"]),
            status_reason=row["status_reason"],
            pre_execution_screenshot=row["pre_execution_screenshot"],
            post_execution_screenshot=row["post_execution_screenshot"],
            submitted_at=datetime.fromisoformat(row["submitted_at"]),
            verified_at=datetime.fromisoformat(row["verified_at"]) if row["verified_at"] else None,
        )

    def _row_to_position(self, row: sqlite3.Row) -> PaperPosition:
        return PaperPosition(
            position_id=row["position_id"],
            symbol=row["symbol"],
            expiry=row["expiry"],
            strike=row["strike"],
            option_type=PaperOptionType(row["option_type"]),
            action=PaperAction(row["action"]),
            lots=row["lots"],
            quantity=row["quantity"],
            avg_price=row["avg_price"],
            current_ltp=row["current_ltp"],
            unrealized_pnl=row["unrealized_pnl"],
            pnl_percentage=row["pnl_percentage"],
            realized_pnl=row["realized_pnl"],
            status=PaperPositionStatus(row["status"]),
            first_detected_at=datetime.fromisoformat(row["first_detected_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            closed_at=datetime.fromisoformat(row["closed_at"]) if row["closed_at"] else None,
            exit_price=row["exit_price"],
        )
