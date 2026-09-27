"""
Stage 6: Hermes Collaboration Domain Contracts & Auditing Models.

Defines the collaboration cycle, interaction turns, source attribution, and
telemetry tracking between Hermes Orchestrator and the Trading Brain.

STRICT INVARIANT:
Package 4 contracts (BrainInput, BrainOutput, BrainResult, BrainState, TradeCandidate)
remain canonical and authoritative. These contracts encapsulate the operational
collaboration flow without duplicating or bypassing Package 4.
"""

from datetime import datetime, timezone
from enum import Enum
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, Field

from nifty_trader.brain.contracts import (
    BrainFailure,
    BrainInput,
    BrainOutput,
    BrainResult,
    BrainState,
    ObservationRequest,
    ReasoningState,
    TradeCandidate,
)

logger = logging.getLogger(__name__)


class ContextSource(str, Enum):
    """Identifies the operational source of contextual evidence."""
    NUMERICAL_DATA = "NUMERICAL_DATA"
    TRADINGVIEW = "TRADINGVIEW"
    SENSIBULL = "SENSIBULL"
    OPERATOR_INSTRUCTION = "OPERATOR_INSTRUCTION"
    MEMORY = "MEMORY"
    PREVIOUS_BRAIN_STATE = "PREVIOUS_BRAIN_STATE"
    EXTERNAL_RESEARCH = "EXTERNAL_RESEARCH"


class ContextItem(BaseModel):
    """
    Source-attributed context item provided to the Brain.
    """
    item_id: str = Field(default_factory=lambda: f"citem_{uuid.uuid4().hex[:8]}")
    source: ContextSource
    source_id: str
    source_type: str = Field(description="e.g. CANDLE_HISTORY, DERIVATIVES_CHAIN, VISUAL_SUMMARY")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    freshness: str = "FRESH"
    status: str = "VALID"
    content: str
    observation_reference: Optional[str] = None
    relevance: float = 1.0


class CollaborationTurn(BaseModel):
    """
    Represents one single turn (reasoning evaluation or tool fulfillment) within a cycle.
    """
    turn_index: int
    brain_request_id: str
    action_taken: str = Field(description="e.g. INITIAL_ANALYSIS, OBSERVATION_FULFILLMENT, RE_EVALUATION")
    requested_items: List[str] = Field(default_factory=list)
    tools_invoked: List[str] = Field(default_factory=list)
    reasoning_state: Optional[ReasoningState] = None
    duration_ms: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CollaborationCycle(BaseModel):
    """
    Complete auditable history of a collaborative trading reasoning cycle.
    """
    cycle_id: str = Field(default_factory=lambda: f"collab_{uuid.uuid4().hex[:10]}")
    session_id: str
    instrument: str = "NIFTY"
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    turns: List[CollaborationTurn] = Field(default_factory=list)
    final_reasoning_state: Optional[ReasoningState] = None
    candidate: Optional[TradeCandidate] = None
    observation_requests_issued: List[ObservationRequest] = Field(default_factory=list)
    wait_decision: Optional[Dict[str, Any]] = None
    model_used: str = "gemini"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CollaborationAuditStore:
    """
    Persists collaboration cycles to disk in JSON Lines format for auditing.
    """

    def __init__(self, storage_dir: Optional[Path] = None):
        self.storage_dir = storage_dir or Path("data/collaboration")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.storage_dir / "collaboration_cycles.jsonl"

    def record_cycle(self, cycle: CollaborationCycle) -> None:
        """Appends a collaboration cycle to the audit file."""
        try:
            line = cycle.model_dump_json() + "\n"
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(line)
            logger.info("Recorded collaboration cycle %s [Final State: %s]", cycle.cycle_id, cycle.final_reasoning_state)
        except Exception as e:
            logger.error("Failed to record collaboration cycle %s: %s", cycle.cycle_id, e)

    def load_recent_cycles(self, limit: int = 20) -> List[CollaborationCycle]:
        """Loads most recent collaboration cycles."""
        if not self.log_file.exists():
            return []
        cycles = []
        try:
            with open(self.log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            for line in lines[-limit:]:
                if line.strip():
                    cycles.append(CollaborationCycle.model_validate_json(line))
        except Exception as e:
            logger.error("Failed to read collaboration cycles log: %s", e)
        return cycles
