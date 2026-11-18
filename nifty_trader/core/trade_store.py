"""
Dedicated SQLite Audit Store for TradeRecords, TradeEvents, and Position Collisions.

Implements Sections 11, 12, 14, 15, 23, and 26 of Dual Autonomous Hermes Modes:
- Mandatory trade attribution: `decision_source` (EXISTING_SYSTEM vs HERMES_RESEARCH).
- Research ID tracking for research trades.
- Event logging for full lifecycle traceability.
- Position collision handling across modes without silent merging or state corruption.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, Generator, List, Optional, Tuple

from nifty_trader.core.modes import (
    TradeEvent,
    TradeIntent,
    TradeLifecycleEventType,
    TradeRecord,
    TradingMode,
)
from nifty_trader.paper.contracts import PaperPosition

logger = logging.getLogger(__name__)


class TradeAuditStore:
    """
    Thread-safe persistent store for canonical TradeRecords and TradeEvents.
    Provides mode-specific views and prevents cross-contamination.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or Path("data/trading/trades_audit.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trade_records (
                    trade_id TEXT PRIMARY KEY,
                    decision_source TEXT NOT NULL,
                    trade_intent_id TEXT NOT NULL,
                    assessment_id TEXT NOT NULL,
                    research_id TEXT,
                    timestamp TEXT NOT NULL,
                    instrument TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    strike REAL,
                    option_type TEXT,
                    entry REAL,
                    stop_loss REAL,
                    target REAL,
                    score REAL NOT NULL,
                    confidence REAL NOT NULL,
                    thesis TEXT NOT NULL,
                    safety_decision TEXT NOT NULL,
                    safety_block_reason TEXT,
                    execution_status TEXT NOT NULL,
                    entry_time TEXT,
                    exit_time TEXT,
                    exit_price REAL,
                    pnl REAL NOT NULL,
                    outcome TEXT NOT NULL,
                    metadata_json TEXT
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trade_events (
                    event_id TEXT PRIMARY KEY,
                    trade_id TEXT,
                    mode TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    assessment_id TEXT,
                    research_id TEXT,
                    trade_intent_id TEXT,
                    details_json TEXT
                )
            """)

            # Indices for rapid mode queries
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trade_source ON trade_records (decision_source)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trade_intent ON trade_records (trade_intent_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_event_mode ON trade_events (mode)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_event_trade ON trade_events (trade_id)")

    def save_trade(self, trade: TradeRecord) -> None:
        """Saves or updates a TradeRecord."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO trade_records (
                    trade_id, decision_source, trade_intent_id, assessment_id, research_id,
                    timestamp, instrument, direction, strike, option_type,
                    entry, stop_loss, target, score, confidence, thesis,
                    safety_decision, safety_block_reason, execution_status,
                    entry_time, exit_time, exit_price, pnl, outcome, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade.trade_id,
                trade.decision_source.value if isinstance(trade.decision_source, TradingMode) else str(trade.decision_source),
                trade.trade_intent_id,
                trade.assessment_id,
                trade.research_id,
                trade.timestamp.isoformat(),
                trade.instrument,
                trade.direction,
                trade.strike,
                trade.option_type,
                trade.entry,
                trade.stop_loss,
                trade.target,
                trade.score,
                trade.confidence,
                trade.thesis,
                trade.safety_decision,
                trade.safety_block_reason,
                trade.execution_status,
                trade.entry_time.isoformat() if trade.entry_time else None,
                trade.exit_time.isoformat() if trade.exit_time else None,
                trade.exit_price,
                trade.pnl,
                trade.outcome,
                json.dumps(trade.metadata or {}),
            ))

    def get_trade(self, trade_id: str) -> Optional[TradeRecord]:
        """Retrieves a TradeRecord by trade_id."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM trade_records WHERE trade_id = ?", (trade_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_trade(row)

    def list_trades(
        self,
        mode: Optional[TradingMode] = None,
        limit: int = 100,
    ) -> List[TradeRecord]:
        """Lists trade records, optionally filtered by TradingMode."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if mode:
                mode_val = mode.value if isinstance(mode, TradingMode) else str(mode)
                cursor.execute(
                    "SELECT * FROM trade_records WHERE decision_source = ? ORDER BY timestamp DESC LIMIT ?",
                    (mode_val, limit),
                )
            else:
                cursor.execute(
                    "SELECT * FROM trade_records ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                )
            return [self._row_to_trade(r) for r in cursor.fetchall()]

    def get_trades_by_mode(self, mode: TradingMode, limit: int = 100) -> List[TradeRecord]:
        """Convenience method returning trades for a specific TradingMode."""
        return self.list_trades(mode=mode, limit=limit)

    def get_all_trades(self, limit: int = 100) -> List[TradeRecord]:
        """Convenience method returning all trades across modes."""
        return self.list_trades(mode=None, limit=limit)

    def log_event(self, event: TradeEvent) -> None:
        """Appends an auditable lifecycle event with strict mode attribution."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO trade_events (
                    event_id, trade_id, mode, timestamp, event_type,
                    assessment_id, research_id, trade_intent_id, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event.event_id,
                event.trade_id,
                event.mode.value if isinstance(event.mode, TradingMode) else str(event.mode),
                event.timestamp.isoformat(),
                event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type),
                event.assessment_id,
                event.research_id,
                event.trade_intent_id,
                json.dumps(event.details or {}),
            ))

    def list_events(
        self,
        trade_id: Optional[str] = None,
        mode: Optional[TradingMode] = None,
        limit: int = 100,
    ) -> List[TradeEvent]:
        """Retrieves audit trail events."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if trade_id:
                cursor.execute("SELECT * FROM trade_events WHERE trade_id = ? ORDER BY timestamp ASC LIMIT ?", (trade_id, limit))
            elif mode:
                mode_val = mode.value if isinstance(mode, TradingMode) else str(mode)
                cursor.execute("SELECT * FROM trade_events WHERE mode = ? ORDER BY timestamp DESC LIMIT ?", (mode_val, limit))
            else:
                cursor.execute("SELECT * FROM trade_events ORDER BY timestamp DESC LIMIT ?", (limit,))
            return [self._row_to_event(r) for r in cursor.fetchall()]

    def handle_position_collision(
        self,
        incoming_intent: TradeIntent,
        active_positions: List[PaperPosition],
    ) -> Tuple[bool, Optional[str]]:
        """
        Explicitly handles cases where both modes generate trades close together.
        Ensures NO silent merging, NO state overwrite, and explicit collision logging.
        Returns:
            (can_proceed: bool, reason: Optional[str])
        """
        symbol = incoming_intent.instrument.upper()
        mode_str = incoming_intent.mode.value

        # Check existing positions on the same instrument
        conflicting = [p for p in active_positions if p.symbol.upper() == symbol]
        if not conflicting:
            return True, None

        # Check if there is already a position opened by the other mode
        other_mode_positions = [
            p for p in conflicting
            if getattr(p, "mode", "EXISTING_SYSTEM") != mode_str
        ]

        if other_mode_positions:
            other_p = other_mode_positions[0]
            other_mode = getattr(other_p, "mode", "OTHER_MODE")
            other_action = getattr(other_p, "action", "BUY")
            this_action = incoming_intent.direction

            # Log collision event
            collision_details = {
                "incoming_mode": mode_str,
                "incoming_trade_intent_id": incoming_intent.trade_intent_id,
                "incoming_direction": this_action,
                "existing_mode": other_mode,
                "existing_position_id": other_p.position_id,
                "existing_direction": str(other_action),
                "instrument": symbol,
            }

            self.log_event(TradeEvent(
                mode=incoming_intent.mode,
                event_type=TradeLifecycleEventType.POSITION_COLLISION_DETECTED,
                trade_intent_id=incoming_intent.trade_intent_id,
                assessment_id=incoming_intent.assessment_id,
                research_id=incoming_intent.research_id,
                details=collision_details,
            ))

            logger.warning(
                "[POSITION COLLISION] Mode %s proposed %s %s while %s holds active position %s (%s). Preserving separate attribution.",
                mode_str, this_action, symbol, other_mode, other_p.position_id, other_action
            )

            # In single Sensibull paper trading portfolio, opposite directional positions on the same strike
            # cancel each other out remotely. We detect and record this limitation cleanly.
            if str(this_action).upper() != str(other_action).upper() and incoming_intent.strike == other_p.strike:
                reason = (
                    f"Position Collision Limitation: {other_mode} holds active {other_action} on {symbol} strike {other_p.strike}. "
                    f"Sensibull cannot cleanly isolate opposing virtual positions simultaneously. Separate attribution preserved; order rejected."
                )
                return False, reason

        return True, None

    def _row_to_trade(self, row: sqlite3.Row) -> TradeRecord:
        source = TradingMode(row["decision_source"]) if row["decision_source"] in [m.value for m in TradingMode] else TradingMode.EXISTING_SYSTEM
        meta = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
        return TradeRecord(
            trade_id=row["trade_id"],
            decision_source=source,
            trade_intent_id=row["trade_intent_id"],
            assessment_id=row["assessment_id"],
            research_id=row["research_id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            instrument=row["instrument"],
            direction=row["direction"],
            strike=row["strike"],
            option_type=row["option_type"],
            entry=row["entry"],
            stop_loss=row["stop_loss"],
            target=row["target"],
            score=row["score"],
            confidence=row["confidence"],
            thesis=row["thesis"],
            safety_decision=row["safety_decision"],
            safety_block_reason=row["safety_block_reason"],
            execution_status=row["execution_status"],
            entry_time=datetime.fromisoformat(row["entry_time"]) if row["entry_time"] else None,
            exit_time=datetime.fromisoformat(row["exit_time"]) if row["exit_time"] else None,
            exit_price=row["exit_price"],
            pnl=row["pnl"],
            outcome=row["outcome"],
            metadata=meta,
        )

    def _row_to_event(self, row: sqlite3.Row) -> TradeEvent:
        mode = TradingMode(row["mode"]) if row["mode"] in [m.value for m in TradingMode] else TradingMode.EXISTING_SYSTEM
        evt_type = TradeLifecycleEventType(row["event_type"]) if row["event_type"] in [e.value for e in TradeLifecycleEventType] else TradeLifecycleEventType.ASSESSMENT_CREATED
        details = json.loads(row["details_json"]) if row["details_json"] else {}
        return TradeEvent(
            event_id=row["event_id"],
            trade_id=row["trade_id"],
            mode=mode,
            timestamp=datetime.fromisoformat(row["timestamp"]),
            event_type=evt_type,
            assessment_id=row["assessment_id"],
            research_id=row["research_id"],
            trade_intent_id=row["trade_intent_id"],
            details=details,
        )
