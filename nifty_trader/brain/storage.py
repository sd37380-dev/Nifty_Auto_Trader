"""
Persistent Storage Engine for Brain Reasoning History (Package 4).

Stores normalized BrainRecord rows and full BrainOutput JSON documents
in SQLite for auditability, post-mortem analysis, and operator inspection.
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional
import uuid

from nifty_trader.brain.contracts import (
    DEFAULT_PROMPT_VERSION,
    PACKAGE4_SCHEMA_VERSION,
    BrainOutput,
    BrainRecord,
    BrainState,
    Confidence,
    ReasoningState,
)

logger = logging.getLogger(__name__)


class BrainStorage:
    """
    SQLite persistence layer for BrainRecord and BrainOutput history.
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
                    record_id TEXT PRIMARY KEY,
                    schema_version TEXT NOT NULL,
                    brain_request_id TEXT NOT NULL,
                    observation_id TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    model_provider TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    task TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    brain_schema_version TEXT NOT NULL,
                    reasoning_state TEXT NOT NULL,
                    confidence_value REAL NOT NULL,
                    candidate_direction TEXT,
                    output_json TEXT NOT NULL,
                    summary_text TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_brain_obs
                ON brain_reasoning_history(observation_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_brain_state_ts
                ON brain_reasoning_history(reasoning_state, timestamp DESC)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_brain_ts
                ON brain_reasoning_history(timestamp DESC)
            """)
            conn.commit()

    def save_output(
        self,
        output: BrainOutput,
        model_provider: str = "gemini",
        model_name: str = "gemini-2.5-flash",
        task: str = "MARKET_ANALYSIS",
        prompt_version: str = DEFAULT_PROMPT_VERSION,
    ) -> BrainRecord:
        """Stores a completed BrainOutput and returns its persisted BrainRecord."""
        record_id = f"brec_{uuid.uuid4().hex[:10]}"
        direction = output.candidate.direction.value if output.candidate else None
        output_json = output.model_dump_json()
        summary_text = output.reasoning_summary.interpretation

        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO brain_reasoning_history (
                    record_id, schema_version, brain_request_id, observation_id,
                    timestamp, model_provider, model_name, task, prompt_version,
                    brain_schema_version, reasoning_state, confidence_value,
                    candidate_direction, output_json, summary_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record_id,
                output.schema_version,
                output.brain_request_id,
                output.observation_id,
                float(output.generated_at.timestamp()),
                model_provider,
                model_name,
                task,
                prompt_version,
                output.schema_version,
                output.reasoning_state.value,
                output.confidence.value,
                direction,
                output_json,
                summary_text,
            ))
            conn.commit()

        return BrainRecord(
            record_id=record_id,
            schema_version=output.schema_version,
            brain_request_id=output.brain_request_id,
            observation_id=output.observation_id,
            model_provider=model_provider,
            model_name=model_name,
            task=task,
            prompt_version=prompt_version,
            brain_schema_version=output.schema_version,
            reasoning_state=output.reasoning_state,
            confidence=output.confidence,
            created_at=output.generated_at,
        )

    def get_output(self, brain_request_id: str) -> Optional[BrainOutput]:
        """Retrieves a BrainOutput by request ID."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT output_json FROM brain_reasoning_history WHERE brain_request_id = ?", (brain_request_id,))
            row = cur.fetchone()
            if row:
                try:
                    return BrainOutput.model_validate_json(row["output_json"])
                except Exception as e:
                    logger.warning("Failed to deserialize output for %s: %s", brain_request_id, e)
        return None

    def get_latest_output(self) -> Optional[BrainOutput]:
        """Retrieves the most recent BrainOutput."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT output_json FROM brain_reasoning_history ORDER BY timestamp DESC, rowid DESC LIMIT 10")
            rows = cur.fetchall()
            for r in rows:
                try:
                    return BrainOutput.model_validate_json(r["output_json"])
                except Exception:
                    continue
        return None

    def get_by_observation_id(self, observation_id: str) -> List[BrainOutput]:
        """Retrieves all BrainOutputs associated with a given observation."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT output_json FROM brain_reasoning_history WHERE observation_id = ? ORDER BY timestamp DESC, rowid DESC",
                (observation_id,),
            )
            rows = cur.fetchall()
            valid_outputs = []
            for r in rows:
                try:
                    valid_outputs.append(BrainOutput.model_validate_json(r["output_json"]))
                except Exception:
                    pass
            return valid_outputs

    def list_outputs(
        self,
        limit: int = 20,
        state: Optional[ReasoningState] = None,
    ) -> List[BrainOutput]:
        """Lists recent BrainOutputs, optionally filtered by ReasoningState."""
        query = "SELECT output_json FROM brain_reasoning_history"
        params: List[Any] = []
        if state:
            query += " WHERE reasoning_state = ?"
            params.append(state.value)
        query += " ORDER BY timestamp DESC, rowid DESC LIMIT ?"
        params.append(limit * 2)

        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            rows = cur.fetchall()
            valid_outputs = []
            for r in rows:
                try:
                    valid_outputs.append(BrainOutput.model_validate_json(r["output_json"]))
                    if len(valid_outputs) >= limit:
                        break
                except Exception:
                    pass
            return valid_outputs

    def get_latest_state(self) -> Optional[BrainState]:
        """Reconstructs the latest BrainState from the most recent BrainOutput."""
        latest_output = self.get_latest_output()
        if not latest_output:
            return None
        return BrainState(
            schema_version=latest_output.schema_version,
            state_id=f"bstate_{latest_output.brain_request_id}",
            reasoning_state=latest_output.reasoning_state,
            market_context=latest_output.market_context,
            timeframe_assessments=latest_output.timeframe_assessments,
            scenarios=latest_output.scenarios,
            hypotheses=latest_output.hypotheses,
            active_candidate=latest_output.candidate,
            observation_requests=latest_output.observation_requests,
            uncertainties=latest_output.uncertainties,
            confidence=latest_output.confidence,
            reasoning_summary=latest_output.reasoning_summary,
            created_at=latest_output.generated_at,
            updated_at=latest_output.generated_at,
            source_observation_id=latest_output.observation_id,
        )
