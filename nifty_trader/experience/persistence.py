"""
SQLite Persistence Store for Experience Memory & Post-Trade Analysis.

Database: data/experience/experience.db
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional

from nifty_trader.experience.contracts import (
    EvidenceQuality,
    ExecutionAnalysis,
    ExperienceRecord,
    Lesson,
    MemoryStatus,
    OutcomeAnalysis,
    ReasoningAnalysis,
    TradeTimeline,
)

logger = logging.getLogger(__name__)


class ExperienceStore:
    """
    Thread-safe SQLite store for Experience Records, Lessons, and Event logs.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or Path("data/experience/experience.db")
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
                CREATE TABLE IF NOT EXISTS experience_records (
                    experience_id TEXT PRIMARY KEY,
                    trade_id TEXT NOT NULL,
                    position_id TEXT,
                    symbol TEXT NOT NULL,
                    strike REAL NOT NULL,
                    option_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    market_context TEXT,
                    original_thesis TEXT,
                    timeline_json TEXT NOT NULL,
                    reasoning_analysis_json TEXT NOT NULL,
                    execution_analysis_json TEXT NOT NULL,
                    outcome_analysis_json TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    evidence_quality TEXT NOT NULL,
                    memory_status TEXT NOT NULL,
                    similar_experience_count INTEGER NOT NULL,
                    summary TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS lessons (
                    lesson_id TEXT PRIMARY KEY,
                    experience_id TEXT NOT NULL,
                    lesson_type TEXT NOT NULL,
                    statement TEXT NOT NULL,
                    epistemic_status TEXT NOT NULL,
                    evidence_refs TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    is_validated INTEGER NOT NULL,
                    FOREIGN KEY(experience_id) REFERENCES experience_records(experience_id)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS experience_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    experience_id TEXT,
                    trade_id TEXT,
                    details TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_exp_trade ON experience_records(trade_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_exp_status ON experience_records(memory_status)")
            conn.commit()

    def save_experience(self, record: ExperienceRecord) -> None:
        """Saves or updates an ExperienceRecord along with its extracted lessons."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO experience_records (
                    experience_id, trade_id, position_id, symbol, strike, option_type,
                    created_at, schema_version, market_context, original_thesis,
                    timeline_json, reasoning_analysis_json, execution_analysis_json,
                    outcome_analysis_json, tags, evidence_quality, memory_status,
                    similar_experience_count, summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.experience_id,
                record.trade_id,
                record.position_id,
                record.symbol,
                record.strike,
                record.option_type,
                record.created_at.isoformat(),
                record.schema_version,
                record.market_context,
                record.original_thesis,
                record.timeline.model_dump_json(),
                record.reasoning_analysis.model_dump_json(),
                record.execution_analysis.model_dump_json(),
                record.outcome_analysis.model_dump_json(),
                json.dumps(record.tags),
                record.evidence_quality.value,
                record.memory_status.value,
                record.similar_experience_count,
                record.summary,
            ))

            # Replace lessons
            cursor.execute("DELETE FROM lessons WHERE experience_id = ?", (record.experience_id,))
            for lesson in record.lessons:
                cursor.execute("""
                    INSERT INTO lessons (
                        lesson_id, experience_id, lesson_type, statement,
                        epistemic_status, evidence_refs, confidence, is_validated
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    lesson.lesson_id,
                    record.experience_id,
                    lesson.lesson_type.value,
                    lesson.statement,
                    lesson.epistemic_status.value,
                    json.dumps(lesson.evidence_refs),
                    lesson.confidence,
                    1 if lesson.is_validated else 0,
                ))

            conn.commit()

    def get_experience(self, experience_id: str) -> Optional[ExperienceRecord]:
        """Retrieves an ExperienceRecord by experience_id."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM experience_records WHERE experience_id = ?", (experience_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_record(cursor, row)

    def get_experience_by_trade(self, trade_id: str) -> Optional[ExperienceRecord]:
        """Retrieves an ExperienceRecord by trade_id."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM experience_records WHERE trade_id = ? ORDER BY created_at DESC LIMIT 1", (trade_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_record(cursor, row)

    def list_experiences(
        self,
        limit: int = 50,
        tag: Optional[str] = None,
        status: Optional[MemoryStatus] = None,
    ) -> List[ExperienceRecord]:
        """Lists recent experiences with optional filtering."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM experience_records"
            params: List[Any] = []
            clauses = []

            if status:
                clauses.append("memory_status = ?")
                params.append(status.value)
            if tag:
                clauses.append("tags LIKE ?")
                params.append(f"%{tag}%")

            if clauses:
                query += " WHERE " + " AND ".join(clauses)

            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [self._row_to_record(cursor, r) for r in rows]

    def save_event(
        self,
        event_type: str,
        experience_id: Optional[str],
        trade_id: Optional[str],
        details: Dict[str, Any],
    ) -> None:
        """Logs an auditable experience memory lifecycle event."""
        import uuid
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO experience_events (event_id, event_type, experience_id, trade_id, details, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                f"xevt_{uuid.uuid4().hex[:8]}",
                event_type,
                experience_id,
                trade_id,
                json.dumps(details),
                datetime.now(timezone.utc).isoformat(),
            ))
            conn.commit()

    def list_events(
        self,
        limit: int = 50,
        experience_id: Optional[str] = None,
        trade_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Lists recent experience lifecycle events."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM experience_events"
            params: List[Any] = []
            clauses = []
            if experience_id:
                clauses.append("experience_id = ?")
                params.append(experience_id)
            if trade_id:
                clauses.append("trade_id = ?")
                params.append(trade_id)
            if clauses:
                query += " WHERE " + " AND ".join(clauses)
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            results = []
            for r in cursor.fetchall():
                results.append({
                    "event_id": r["event_id"],
                    "event_type": r["event_type"],
                    "experience_id": r["experience_id"],
                    "trade_id": r["trade_id"],
                    "details": json.loads(r["details"]) if r["details"] else {},
                    "timestamp": datetime.fromisoformat(r["timestamp"]),
                })
            return results

    def _row_to_record(self, cursor: sqlite3.Cursor, row: sqlite3.Row) -> ExperienceRecord:
        exp_id = row["experience_id"]
        cursor.execute("SELECT * FROM lessons WHERE experience_id = ?", (exp_id,))
        lesson_rows = cursor.fetchall()
        lessons = [
            Lesson(
                lesson_id=lr["lesson_id"],
                lesson_type=lr["lesson_type"],
                statement=lr["statement"],
                epistemic_status=lr["epistemic_status"],
                evidence_refs=json.loads(lr["evidence_refs"]) if lr["evidence_refs"] else [],
                confidence=lr["confidence"],
                is_validated=bool(lr["is_validated"]),
            )
            for lr in lesson_rows
        ]

        return ExperienceRecord(
            experience_id=row["experience_id"],
            trade_id=row["trade_id"],
            position_id=row["position_id"],
            symbol=row["symbol"],
            strike=row["strike"],
            option_type=row["option_type"],
            created_at=datetime.fromisoformat(row["created_at"]),
            schema_version=row["schema_version"],
            market_context=row["market_context"] or "",
            original_thesis=row["original_thesis"] or "",
            timeline=TradeTimeline.model_validate_json(row["timeline_json"]),
            reasoning_analysis=ReasoningAnalysis.model_validate_json(row["reasoning_analysis_json"]),
            execution_analysis=ExecutionAnalysis.model_validate_json(row["execution_analysis_json"]),
            outcome_analysis=OutcomeAnalysis.model_validate_json(row["outcome_analysis_json"]),
            lessons=lessons,
            tags=json.loads(row["tags"]) if row["tags"] else [],
            evidence_quality=EvidenceQuality(row["evidence_quality"]),
            memory_status=MemoryStatus(row["memory_status"]),
            similar_experience_count=row["similar_experience_count"],
            summary=row["summary"],
        )
