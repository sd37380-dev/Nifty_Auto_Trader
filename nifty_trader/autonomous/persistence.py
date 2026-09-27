"""
Package 5: Autonomous Storage & Persistence Layer.

Persists autonomous sessions, execution cycles, state transitions, wait decisions,
and observation plans into a dedicated SQLite database (data/autonomous/autonomous_engine.db)
with support for crash recovery and audit trails.

STRICT INVARIANT: No secrets or private chain-of-thought stored.
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional

from nifty_trader.autonomous.contracts import (
    AutonomousCycle,
    AutonomousSession,
    AutonomousState,
    ScheduledObservationPlan,
    WaitDecision,
    WaitReason,
)
from nifty_trader.autonomous.state_machine import StateTransitionRecord

logger = logging.getLogger(__name__)


class AutonomousStorage:
    """
    SQLite persistence provider for autonomous sessions, cycles, and decisions.
    """

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            default_dir = Path("data/autonomous")
            default_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = default_dir / "autonomous_engine.db"
        else:
            self.db_path = Path(db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            cur = conn.cursor()
            # 1. Sessions table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS autonomous_sessions (
                    session_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    status TEXT NOT NULL,
                    cycles_completed INTEGER DEFAULT 0,
                    model_calls INTEGER DEFAULT 0,
                    observation_requests_count INTEGER DEFAULT 0,
                    consecutive_failures INTEGER DEFAULT 0
                )
            """)

            # 2. Cycles table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS autonomous_cycles (
                    cycle_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    cycle_index INTEGER NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    observation_id TEXT,
                    brain_request_id TEXT,
                    previous_state TEXT NOT NULL,
                    resulting_state TEXT NOT NULL,
                    wake_reason TEXT,
                    wait_reason TEXT,
                    observation_count INTEGER DEFAULT 0,
                    model_call_count INTEGER DEFAULT 0,
                    errors_json TEXT,
                    FOREIGN KEY (session_id) REFERENCES autonomous_sessions (session_id)
                )
            """)

            # 3. Transitions table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS state_transitions (
                    transition_id TEXT PRIMARY KEY,
                    session_id TEXT,
                    cycle_id TEXT,
                    from_state TEXT NOT NULL,
                    to_state TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)

            # 4. Wait decisions table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS wait_decisions (
                    decision_id TEXT PRIMARY KEY,
                    cycle_id TEXT,
                    should_wait INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    earliest_wake_at TEXT NOT NULL,
                    latest_wake_at TEXT NOT NULL,
                    explanation TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)

            # 5. Observation plans table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS observation_plans (
                    plan_id TEXT PRIMARY KEY,
                    cycle_id TEXT,
                    source TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    request_fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT,
                    scheduled_at TEXT NOT NULL,
                    expires_at TEXT
                )
            """)

            conn.commit()

    # =========================================================================
    # Sessions
    # =========================================================================

    def save_session(self, session: AutonomousSession) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO autonomous_sessions (
                    session_id, symbol, started_at, ended_at, status,
                    cycles_completed, model_calls, observation_requests_count, consecutive_failures
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.session_id,
                    session.symbol,
                    session.started_at.isoformat(),
                    session.ended_at.isoformat() if session.ended_at else None,
                    session.status.value,
                    session.cycles_completed,
                    session.model_calls,
                    session.observation_requests_count,
                    session.consecutive_failures,
                ),
            )
            conn.commit()

    def get_latest_session(self) -> Optional[AutonomousSession]:
        with self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM autonomous_sessions ORDER BY started_at DESC LIMIT 1")
            row = cur.fetchone()
            if not row:
                return None
            return AutonomousSession(
                session_id=row["session_id"],
                symbol=row["symbol"],
                started_at=datetime.fromisoformat(row["started_at"]),
                ended_at=datetime.fromisoformat(row["ended_at"]) if row["ended_at"] else None,
                status=AutonomousState(row["status"]),
                cycles_completed=row["cycles_completed"],
                model_calls=row["model_calls"],
                observation_requests_count=row["observation_requests_count"],
                consecutive_failures=row["consecutive_failures"],
            )

    # =========================================================================
    # Cycles
    # =========================================================================

    def save_cycle(self, cycle: AutonomousCycle) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO autonomous_cycles (
                    cycle_id, session_id, cycle_index, started_at, completed_at,
                    observation_id, brain_request_id, previous_state, resulting_state,
                    wake_reason, wait_reason, observation_count, model_call_count, errors_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cycle.cycle_id,
                    cycle.session_id,
                    cycle.cycle_index,
                    cycle.started_at.isoformat(),
                    cycle.completed_at.isoformat() if cycle.completed_at else None,
                    cycle.observation_id,
                    cycle.brain_request_id,
                    cycle.previous_state.value,
                    cycle.resulting_state.value,
                    cycle.wake_reason,
                    cycle.wait_reason.value if cycle.wait_reason else None,
                    cycle.observation_count,
                    cycle.model_call_count,
                    json.dumps(cycle.errors),
                ),
            )
            conn.commit()

    def list_cycles(self, limit: int = 20) -> List[AutonomousCycle]:
        with self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM autonomous_cycles ORDER BY started_at DESC LIMIT ?", (limit,))
            rows = cur.fetchall()
            cycles = []
            for r in rows:
                cycles.append(
                    AutonomousCycle(
                        cycle_id=r["cycle_id"],
                        session_id=r["session_id"],
                        cycle_index=r["cycle_index"],
                        started_at=datetime.fromisoformat(r["started_at"]),
                        completed_at=datetime.fromisoformat(r["completed_at"]) if r["completed_at"] else None,
                        observation_id=r["observation_id"],
                        brain_request_id=r["brain_request_id"],
                        previous_state=AutonomousState(r["previous_state"]),
                        resulting_state=AutonomousState(r["resulting_state"]),
                        wake_reason=r["wake_reason"],
                        wait_reason=WaitReason(r["wait_reason"]) if r["wait_reason"] else None,
                        observation_count=r["observation_count"],
                        model_call_count=r["model_call_count"],
                        errors=json.loads(r["errors_json"]) if r["errors_json"] else [],
                    )
                )
            return cycles

    # =========================================================================
    # State Transitions & Wait Decisions
    # =========================================================================

    def save_transition(self, record: StateTransitionRecord) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO state_transitions (
                    transition_id, session_id, cycle_id, from_state, to_state, reason, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.transition_id,
                    record.session_id,
                    record.cycle_id,
                    record.from_state.value,
                    record.to_state.value,
                    record.reason,
                    record.timestamp.isoformat(),
                ),
            )
            conn.commit()

    def save_wait_decision(self, decision: WaitDecision, cycle_id: Optional[str] = None) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO wait_decisions (
                    decision_id, cycle_id, should_wait, reason, earliest_wake_at,
                    latest_wake_at, explanation, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.decision_id,
                    cycle_id,
                    1 if decision.should_wait else 0,
                    decision.reason.value,
                    decision.earliest_wake_at.isoformat(),
                    decision.latest_wake_at.isoformat(),
                    decision.explanation,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()

    def get_latest_wait_decision(self) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM wait_decisions ORDER BY created_at DESC LIMIT 1")
            row = cur.fetchone()
            if not row:
                return None
            return dict(row)
