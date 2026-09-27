"""
SQLite Persistence Store for Position Monitoring Lifecycle & Audit Trail.

Database: data/monitoring/position_monitoring.db
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional

from nifty_trader.brain.contracts import PositionManagementAction, ReasoningState
from nifty_trader.monitoring.contracts import (
    MonitoringState,
    PositionEvent,
    PositionMonitoringRecord,
)

logger = logging.getLogger(__name__)


class PositionMonitoringStore:
    """Thread-safe SQLite store for position monitoring records and events."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or Path("data/monitoring/position_monitoring.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS position_monitoring_records (
                    monitoring_id TEXT PRIMARY KEY,
                    position_id TEXT NOT NULL,
                    trade_id TEXT,
                    symbol TEXT NOT NULL,
                    strike REAL NOT NULL,
                    option_type TEXT NOT NULL,
                    lots INTEGER NOT NULL,
                    quantity INTEGER NOT NULL,
                    entry_price REAL NOT NULL,
                    current_price REAL NOT NULL,
                    unrealized_pnl REAL NOT NULL,
                    pnl_percentage REAL NOT NULL,
                    holding_duration_minutes REAL NOT NULL,
                    monitoring_state TEXT NOT NULL,
                    wake_reason TEXT,
                    market_observation_id TEXT,
                    sensibull_observation_id TEXT,
                    brain_request_id TEXT,
                    brain_reasoning_state TEXT,
                    brain_position_action TEXT,
                    brain_summary TEXT,
                    action_executed TEXT,
                    action_result TEXT,
                    discrepancy_detected TEXT,
                    error TEXT,
                    timestamp TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS position_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    position_id TEXT NOT NULL,
                    details TEXT,
                    timestamp TEXT NOT NULL
                )
            """)
            conn.commit()

    def save_record(self, record: PositionMonitoringRecord) -> None:
        """Saves a monitoring turn record."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO position_monitoring_records (
                    monitoring_id, position_id, trade_id, symbol, strike, option_type,
                    lots, quantity, entry_price, current_price, unrealized_pnl, pnl_percentage,
                    holding_duration_minutes, monitoring_state, wake_reason, market_observation_id,
                    sensibull_observation_id, brain_request_id, brain_reasoning_state,
                    brain_position_action, brain_summary, action_executed, action_result,
                    discrepancy_detected, error, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.monitoring_id,
                record.position_id,
                record.trade_id,
                record.symbol,
                record.strike,
                record.option_type,
                record.lots,
                record.quantity,
                record.entry_price,
                record.current_price,
                record.unrealized_pnl,
                record.pnl_percentage,
                record.holding_duration_minutes,
                record.monitoring_state.value,
                record.wake_reason,
                record.market_observation_id,
                record.sensibull_observation_id,
                record.brain_request_id,
                record.brain_reasoning_state.value if record.brain_reasoning_state else None,
                record.brain_position_action.value if record.brain_position_action else None,
                record.brain_summary,
                record.action_executed,
                record.action_result,
                record.discrepancy_detected,
                record.error,
                record.timestamp.isoformat(),
            ))
            conn.commit()

    def save_event(self, event: PositionEvent) -> None:
        """Logs an auditable position monitoring event."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO position_events (
                    event_id, event_type, position_id, details, timestamp
                ) VALUES (?, ?, ?, ?, ?)
            """, (
                event.event_id,
                event.event_type,
                event.position_id,
                json.dumps(event.details),
                event.timestamp.isoformat(),
            ))
            conn.commit()

    def get_records_for_position(self, position_id: str, limit: int = 50) -> List[PositionMonitoringRecord]:
        """Retrieves history for a specific position."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM position_monitoring_records
                WHERE position_id = ?
                ORDER BY timestamp DESC LIMIT ?
            """, (position_id, limit))
            return [self._row_to_record(r) for r in cursor.fetchall()]

    def get_recent_records(self, limit: int = 20) -> List[PositionMonitoringRecord]:
        """Retrieves most recent monitoring turns."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM position_monitoring_records
                ORDER BY timestamp DESC LIMIT ?
            """, (limit,))
            return [self._row_to_record(r) for r in cursor.fetchall()]

    def list_records(self, limit: int = 50, position_id: Optional[str] = None) -> List[PositionMonitoringRecord]:
        """Unified method to list records, optionally filtered by position_id."""
        if position_id:
            return self.get_records_for_position(position_id, limit=limit)
        return self.get_recent_records(limit=limit)

    def get_events_for_position(self, position_id: str, limit: int = 50) -> List[PositionEvent]:
        """Retrieves events for a position."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM position_events
                WHERE position_id = ?
                ORDER BY timestamp DESC LIMIT ?
            """, (position_id, limit))
            results = []
            for r in cursor.fetchall():
                results.append(PositionEvent(
                    event_id=r["event_id"],
                    event_type=r["event_type"],
                    position_id=r["position_id"],
                    details=json.loads(r["details"]) if r["details"] else {},
                    timestamp=datetime.fromisoformat(r["timestamp"]),
                ))
            return results

    def _row_to_record(self, row: sqlite3.Row) -> PositionMonitoringRecord:
        return PositionMonitoringRecord(
            monitoring_id=row["monitoring_id"],
            position_id=row["position_id"],
            trade_id=row["trade_id"],
            symbol=row["symbol"],
            strike=row["strike"],
            option_type=row["option_type"],
            lots=row["lots"],
            quantity=row["quantity"],
            entry_price=row["entry_price"],
            current_price=row["current_price"],
            unrealized_pnl=row["unrealized_pnl"],
            pnl_percentage=row["pnl_percentage"],
            holding_duration_minutes=row["holding_duration_minutes"],
            monitoring_state=MonitoringState(row["monitoring_state"]),
            wake_reason=row["wake_reason"],
            market_observation_id=row["market_observation_id"],
            sensibull_observation_id=row["sensibull_observation_id"],
            brain_request_id=row["brain_request_id"],
            brain_reasoning_state=ReasoningState(row["brain_reasoning_state"]) if row["brain_reasoning_state"] else None,
            brain_position_action=PositionManagementAction(row["brain_position_action"]) if row["brain_position_action"] else None,
            brain_summary=row["brain_summary"],
            action_executed=row["action_executed"],
            action_result=row["action_result"],
            discrepancy_detected=row["discrepancy_detected"],
            error=row["error"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
        )
