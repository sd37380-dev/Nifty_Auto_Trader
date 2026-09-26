"""
Manual Agent Instruction Models.

Strict data models for human operator steering instructions, priorities,
and lifecycle states.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
import uuid
from pydantic import BaseModel, Field


class InstructionPriority(str, Enum):
    """Priority level for human operator instructions."""
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"


class InstructionStatus(str, Enum):
    """Lifecycle state of an operator instruction."""
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class AgentInstruction(BaseModel):
    """
    Structured model representing human operator steering input to the agent.
    """
    instruction_id: str = Field(default_factory=lambda: f"inst_{uuid.uuid4().hex[:8]}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    text: str
    source: str = "HUMAN"
    priority: InstructionPriority = InstructionPriority.NORMAL
    status: InstructionStatus = InstructionStatus.PENDING
    created_by: str = "operator"
    expires_at: Optional[datetime] = None
    agent_response: Optional[str] = None
    related_observation_id: Optional[str] = None

    @property
    def is_expired(self) -> bool:
        """Determines if the instruction has expired relative to current UTC time."""
        if not self.expires_at:
            return False
        now_utc = datetime.now(timezone.utc)
        return now_utc >= self.expires_at
