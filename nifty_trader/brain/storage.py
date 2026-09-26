"""
Persistent Storage Engine for Brain Reasoning History (Package 4).

Stores reasoning runs, regimes, scenarios, hypotheses, and candidate trade theses
in SQLite for auditability, post-mortem analysis, and operator inspection.
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional

from nifty_trader.brain.contracts import BrainReasoningOutput, SetupState

logger = logging.getLogger(__name__)


class BrainStorage:
    """
    SQLite persistence layer for BrainReasoningOutput history.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or Path("data/brain/reasoning_history.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS brain_reasoning_history (
                    brain_run_id TEXT PRIMARY KEY,
                    observation_id TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    instrument TEXT NOT NULL,
                    current_state TEXT NOT NULL,
                    regime TEXT NOT NULL,
                    confidence_value REAL NOT NULL,
                    candidate_direction TEXT,
                    model_provider TEXT,
                    model_name TEXT,
                    output_json TEXT NOT NULL,
                    auditable_summary TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_brain_obs
                ON brain_reasoning_history(observation_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_brain_state_ts
                ON brain_reasoning_history(current_state, timestamp DESC)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_brain_ts
                ON brain_reasoning_history(timestamp DESC)
            """)
            conn.commit()

    def save_run(
        self,
        output: BrainReasoningOutput,
        model_provider: str = "",
        model_name: str = "",
    ) -> None:
        """Stores a completed reasoning run."""
        direction = output.candidate_thesis.direction.value if output.candidate_thesis else None
        output_json = output.model_dump_json()

        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO brain_reasoning_history (
                    brain_run_id, observation_id, timestamp, instrument,
                    current_state, regime, confidence_value, candidate_direction,
                    model_provider, model_name, output_json, auditable_summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                output.brain_run_id,
                output.observation_id,
                float(output.timestamp.timestamp()),
                output.instrument,
                output.current_state.value,
                output.regime.value,
                output.confidence.value,
                direction,
                model_provider,
                model_name,
                output_json,
                output.auditable_summary,
            ))
            conn.commit()

    def get_run(self, brain_run_id: str) -> Optional[BrainReasoningOutput]:
        """Retrieves a reasoning run by ID."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT output_json FROM brain_reasoning_history WHERE brain_run_id = ?", (brain_run_id,))
            row = cur.fetchone()
            if row:
                return BrainReasoningOutput.model_validate_json(row["output_json"])
        return None

    def get_latest(self) -> Optional[BrainReasoningOutput]:
        """Retrieves the most recent reasoning run."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT output_json FROM brain_reasoning_history ORDER BY timestamp DESC, rowid DESC LIMIT 1")
            row = cur.fetchone()
            if row:
                return BrainReasoningOutput.model_validate_json(row["output_json"])
        return None

    def get_by_observation_id(self, observation_id: str) -> List[BrainReasoningOutput]:
        """Retrieves all reasoning runs associated with a given observation."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT output_json FROM brain_reasoning_history WHERE observation_id = ? ORDER BY timestamp DESC, rowid DESC",
                (observation_id,),
            )
            rows = cur.fetchall()
            return [BrainReasoningOutput.model_validate_json(r["output_json"]) for r in rows]

    def list_runs(
        self,
        limit: int = 20,
        state: Optional[SetupState] = None,
    ) -> List[BrainReasoningOutput]:
        """Lists recent reasoning runs, optionally filtered by SetupState."""
        query = "SELECT output_json FROM brain_reasoning_history"
        params: List[Any] = []
        if state:
            query += " WHERE current_state = ?"
            params.append(state.value)
        query += " ORDER BY timestamp DESC, rowid DESC LIMIT ?"
        params.append(limit)

        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            rows = cur.fetchall()
            return [BrainReasoningOutput.model_validate_json(r["output_json"]) for r in rows]
