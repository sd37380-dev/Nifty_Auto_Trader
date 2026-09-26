"""
Instruction Manager and Safety Boundary Enforcement.

Validates human operator instructions against non-negotiable safety policies,
manages instruction lifecycle, and formats instructions for agent observation.
"""

from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import re
from typing import List, Optional, Tuple, Union

from nifty_trader.instruction.models import (
    AgentInstruction,
    InstructionPriority,
    InstructionStatus,
)
from nifty_trader.instruction.storage import InstructionStore

logger = logging.getLogger(__name__)


class InstructionSafetyViolation(Exception):
    """Raised when an instruction attempts to compromise safety constraints."""
    pass


class InstructionManager:
    """
    Manages operator steering instructions with deterministic safety validation.
    """

    # Prohibited patterns that attempt to circumvent core safety or risk policies
    FORBIDDEN_DIRECTIVES = [
        re.compile(r"ignore\s+(all\s+)?(risk|safety|loss)\s+limits?", re.IGNORECASE),
        re.compile(r"bypass\s+(risk|safety|policy|guardrails?)", re.IGNORECASE),
        re.compile(r"trade\s+(with\s+)?(maximum|unlimited|huge)\s+(size|leverage|risk)", re.IGNORECASE),
        re.compile(r"execute\s+live\s+(order|trade|now)", re.IGNORECASE),
        re.compile(r"override\s+(stop\s*loss|daily\s+loss)", re.IGNORECASE),
        re.compile(r"reveal\s+(api[_\s-]?key|secret|password)", re.IGNORECASE),
        re.compile(r"delete\s+(database|journal|history)", re.IGNORECASE),
    ]

    def __init__(self, store: Optional[InstructionStore] = None, db_path: Optional[Path] = None):
        if store is not None:
            self.store = store
        elif db_path is not None:
            self.store = InstructionStore(db_path=db_path)
        else:
            self.store = InstructionStore()

    def validate_safety(self, text: str) -> Tuple[bool, str]:
        """
        Validates that the instruction does not attempt to breach safety invariants.
        Returns (is_safe, reason).
        """
        if not text or not text.strip():
            return False, "Instruction text cannot be empty."

        for pattern in self.FORBIDDEN_DIRECTIVES:
            if pattern.search(text):
                return False, f"Instruction rejected: Matches prohibited safety-violating pattern '{pattern.pattern}'."

        return True, "Instruction validated successfully."

    def submit_instruction(
        self,
        text: str,
        priority: InstructionPriority = InstructionPriority.NORMAL,
        expires_in_hours: Optional[float] = None,
        created_by: str = "operator",
    ) -> AgentInstruction:
        """
        Validates, stores, and activates a human operator steering instruction.
        """
        is_safe, reason = self.validate_safety(text)
        now_utc = datetime.now(timezone.utc)
        expires_at = (now_utc + timedelta(hours=expires_in_hours)) if expires_in_hours else None

        initial_status = InstructionStatus.PENDING if is_safe else InstructionStatus.REJECTED
        agent_response = None if is_safe else f"SAFETY_POLICY_REJECTION: {reason}"

        instruction = AgentInstruction(
            text=text.strip(),
            source="HUMAN",
            priority=priority,
            status=initial_status,
            created_by=created_by,
            expires_at=expires_at,
            agent_response=agent_response,
        )

        self.store.add_instruction(instruction)

        if not is_safe:
            logger.warning("[SAFETY REJECTION] Rejected manual instruction '%s': %s", instruction.instruction_id, reason)
        else:
            logger.info("[INSTRUCTION ACCEPTED] Registered instruction %s (Priority: %s)", instruction.instruction_id, priority.value)

        return instruction

    def get_active_instructions(self) -> List[AgentInstruction]:
        """
        Returns all non-expired, pending or active instructions sorted by priority and recency.
        """
        self.store.expire_outdated_instructions()
        pending = self.store.list_instructions(status=InstructionStatus.PENDING, limit=20)
        active = self.store.list_instructions(status=InstructionStatus.ACTIVE, limit=20)

        all_inst = pending + active

        priority_weight = {
            InstructionPriority.URGENT: 3,
            InstructionPriority.HIGH: 2,
            InstructionPriority.NORMAL: 1,
        }

        # Sort highest priority first, then most recent
        return sorted(all_inst, key=lambda x: (priority_weight.get(x.priority, 1), x.timestamp), reverse=True)

    def mark_completed(self, instruction_id: str, agent_response: str, observation_id: Optional[str] = None) -> bool:
        """Marks an instruction as completed with the agent's response."""
        return self.store.update_status(
            instruction_id=instruction_id,
            status=InstructionStatus.COMPLETED,
            response=agent_response,
            observation_id=observation_id,
        )

    def list_instructions(self, status: Optional[InstructionStatus] = None, limit: int = 100) -> List[AgentInstruction]:
        """Lists stored instructions, optionally filtered by status."""
        self.store.expire_outdated_instructions()
        return self.store.list_instructions(status=status, limit=limit)

    def format_instructions_for_prompt(self) -> str:
        """Formats active instructions into a clean context block for reasoning models."""
        active = self.get_active_instructions()
        if not active:
            return "No active human operator instructions."

        lines = ["Active Operator Instructions (Guiding Observation/Context Only):"]
        for idx, inst in enumerate(active, 1):
            exp_str = f" [Expires: {inst.expires_at.strftime('%H:%M UTC')}]" if inst.expires_at else ""
            lines.append(f"  {idx}. [{inst.priority.value}] \"{inst.text}\"{exp_str} (ID: {inst.instruction_id})")
        return "\n".join(lines)
