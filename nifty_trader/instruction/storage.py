"""
Persistent Storage Engine for Human Agent Instructions.

Stores instruction history in SQLite, tracks lifecycle states, and handles expiration.
"""

from datetime import datetime, timezone
import logging
from pathlib import Path
import sqlite3
from typing import List, Optional

from nifty_trader.instruction.models import (
    AgentInstruction,
    InstructionPriority,
    InstructionStatus,
)

logger = logging.getLogger(__name__)


class InstructionStore:
    """
    SQLite persistence layer for human operator instructions.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or Path("data/agent/instructions.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS instructions (
                    instruction_id TEXT PRIMARY KEY,
                    timestamp INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    source TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    expires_at INTEGER,
                    agent_response TEXT,
                    related_observation_id TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_instructions_status
                ON instructions(status, timestamp DESC)
            """)
            conn.commit()

    def add_instruction(self, inst: AgentInstruction) -> None:
        """Stores a new agent instruction."""
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO instructions (
                    instruction_id, timestamp, text, source, priority, status,
                    created_by, expires_at, agent_response, related_observation_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                inst.instruction_id,
                int(inst.timestamp.timestamp()),
                inst.text,
                inst.source,
                inst.priority.value,
                inst.status.value,
                inst.created_by,
                int(inst.expires_at.timestamp()) if inst.expires_at else None,
                inst.agent_response,
                inst.related_observation_id,
            ))
            conn.commit()

    def get_instruction(self, instruction_id: str) -> Optional[AgentInstruction]:
        """Retrieves a single instruction by ID."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM instructions WHERE instruction_id = ?", (instruction_id,))
            row = cur.fetchone()
            if row:
                return self._row_to_model(row)
        return None

    def list_instructions(
        self,
        status: Optional[InstructionStatus] = None,
        limit: int = 50,
    ) -> List[AgentInstruction]:
        """Lists stored instructions, optionally filtered by lifecycle status."""
        query = "SELECT * FROM instructions"
        params = []
        if status:
            query += " WHERE status = ?"
            params.append(status.value)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            rows = cur.fetchall()

        return [self._row_to_model(r) for r in rows]

    def update_status(
        self,
        instruction_id: str,
        status: InstructionStatus,
        response: Optional[str] = None,
        observation_id: Optional[str] = None,
    ) -> bool:
        """Updates the status and optional agent response of an instruction."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE instructions
                SET status = ?,
                    agent_response = COALESCE(?, agent_response),
                    related_observation_id = COALESCE(?, related_observation_id)
                WHERE instruction_id = ?
            """, (status.value, response, observation_id, instruction_id))
            conn.commit()
            return cur.rowcount > 0

    def expire_outdated_instructions(self) -> int:
        """Marks pending/active instructions whose expires_at timestamp has passed as EXPIRED."""
        now_epoch = int(datetime.now(timezone.utc).timestamp())
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE instructions
                SET status = ?
                WHERE status IN (?, ?)
                  AND expires_at IS NOT NULL
                  AND expires_at <= ?
            """, (
                InstructionStatus.EXPIRED.value,
                InstructionStatus.PENDING.value,
                InstructionStatus.ACTIVE.value,
                now_epoch,
            ))
            conn.commit()
            return cur.rowcount

    def _row_to_model(self, row: sqlite3.Row) -> AgentInstruction:
        return AgentInstruction(
            instruction_id=row["instruction_id"],
            timestamp=datetime.fromtimestamp(row["timestamp"], tz=timezone.utc),
            text=row["text"],
            source=row["source"],
            priority=InstructionPriority(row["priority"]),
            status=InstructionStatus(row["status"]),
            created_by=row["created_by"],
            expires_at=datetime.fromtimestamp(row["expires_at"], tz=timezone.utc) if row["expires_at"] else None,
            agent_response=row["agent_response"],
            related_observation_id=row["related_observation_id"],
        )
