"""
Experience Memory Validation Pipeline & Anti-Rule Guard.

STRICT INVARIANTS:
1. Every lesson must be backed by evidence references (unsupported lessons rejected).
2. Prohibits imperative strategy rules ("ALWAYS", "NEVER TRADE", etc.).
3. Prohibits sensitive credentials, passwords, or tokens in memory records.
4. Distinguishes RAW, VALIDATED, ACTIVE, and REJECTED states.
"""

import logging
import re
from typing import List, Tuple

from nifty_trader.experience.contracts import (
    EvidenceQuality,
    ExperienceRecord,
    Lesson,
    MemoryStatus,
    TradeOutcome,
)
from nifty_trader.experience.lesson_extractor import PROHIBITED_RULE_PATTERNS

logger = logging.getLogger(__name__)

# Patterns that detect sensitive credentials/tokens
SENSITIVE_PATTERNS = [
    r"password",
    r"otp",
    r"bearer\s+[a-zA-Z0-9_\-\.]{20,}",
    r"session_id",
    r"jwt",
    r"api[_-]?secret",
]


class ExperienceValidator:
    """
    Validates ExperienceRecord integrity, epistemic evidence linkage, and security.
    """

    def validate(self, record: ExperienceRecord) -> Tuple[bool, ExperienceRecord, List[str]]:
        """
        Validates an ExperienceRecord and sets its MemoryStatus.
        Returns: (is_valid, updated_record, error_list)
        """
        errors: List[str] = []
        validated_lessons: List[Lesson] = []

        # 1. Security & Privacy Inspection
        full_text = f"{record.market_context} {record.original_thesis} {record.summary} " + " ".join(
            l.statement for l in record.lessons
        )
        for pat in SENSITIVE_PATTERNS:
            if re.search(pat, full_text, re.IGNORECASE):
                errors.append(f"Security violation: Sensitive credential/token pattern '{pat}' detected in record.")

        # 2. Invariant: Lessons must have supporting evidence
        for lesson in record.lessons:
            if not lesson.evidence_refs:
                errors.append(f"Lesson '{lesson.lesson_id}' rejected: missing supporting evidence references.")
                lesson.is_validated = False
                continue

            # Anti-rule check
            is_rule = False
            for pat in PROHIBITED_RULE_PATTERNS:
                if re.search(pat, lesson.statement, re.IGNORECASE):
                    errors.append(f"Lesson '{lesson.lesson_id}' rejected: contains prohibited imperative rule pattern '{pat}'.")
                    is_rule = True
                    break

            if not is_rule:
                lesson.is_validated = True
                validated_lessons.append(lesson)

        record.lessons = validated_lessons

        # 3. Completeness & Trade Status Verification
        if record.outcome_analysis.outcome == TradeOutcome.UNKNOWN or not record.outcome_analysis.is_verified_pnl:
            record.evidence_quality = EvidenceQuality.PARTIAL
            record.memory_status = MemoryStatus.RAW
        elif errors:
            record.memory_status = MemoryStatus.REJECTED
        else:
            record.memory_status = MemoryStatus.ACTIVE

        is_valid = len(errors) == 0 and record.memory_status in [MemoryStatus.ACTIVE, MemoryStatus.VALIDATED, MemoryStatus.RAW]
        return is_valid, record, errors
