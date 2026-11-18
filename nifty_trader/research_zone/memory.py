"""
Research Memory Layer: Empirical Findings, Negative Knowledge, and Research History.

STRICT INVARIANT:
Failed hypotheses are first-class empirical findings ("Negative Knowledge").
Storing disproven theories prevents Hermes from repeating fruitless research cycles.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
import uuid

from nifty_trader.research_zone.contracts import (
    FailedHypothesis,
    ResearchFinding,
    ResearchHistoryEntry,
)
from nifty_trader.research_zone.storage import ResearchMemoryStore

logger = logging.getLogger(__name__)


class ResearchMemory:
    """
    Manages cumulative research memory, tracking confirmed patterns,
    negative knowledge (failed hypotheses), and audit trails.
    """

    def __init__(self, store: ResearchMemoryStore):
        self.store = store

    def record_finding(
        self,
        pattern_name: str,
        statistical_edge: str,
        confidence: float,
        evidence_refs: Optional[List[str]] = None,
    ) -> ResearchFinding:
        """Stores a confirmed empirical finding into long-term research memory."""
        finding = ResearchFinding(
            finding_id=f"fnd_{uuid.uuid4().hex[:8]}",
            pattern_name=pattern_name,
            statistical_edge=statistical_edge,
            confidence=confidence,
            evidence_refs=evidence_refs or [],
            created_at=datetime.now(timezone.utc),
        )
        self.store.save_finding(finding)
        logger.info("Recorded research finding: %s (edge: %s)", pattern_name, statistical_edge)
        return finding

    def record_failed_hypothesis(
        self,
        hypothesis_id: str,
        statement: str,
        failure_reason: str,
        counter_evidence: Optional[List[str]] = None,
        lessons_learned: str = "",
    ) -> FailedHypothesis:
        """
        Stores negative knowledge: an empirical failure that must NOT be repeated blindly.
        """
        failed = FailedHypothesis(
            failed_id=f"fhyp_{uuid.uuid4().hex[:8]}",
            hypothesis_id=hypothesis_id,
            statement=statement,
            failure_reason=failure_reason,
            counter_evidence=counter_evidence or [],
            lessons_learned=lessons_learned or "Pattern failed statistical significance test.",
            recorded_at=datetime.now(timezone.utc),
        )
        self.store.save_failed_hypothesis(failed)
        logger.info("Recorded failed hypothesis: %s (reason: %s)", statement, failure_reason)
        return failed

    def has_prior_failure(self, search_text: str) -> Optional[FailedHypothesis]:
        """
        Checks if a given pattern or thesis previously failed empirical backtesting.
        """
        failures = self.store.get_failed_hypotheses(limit=100)
        search_lower = search_text.lower()
        for f in failures:
            if search_lower in f.statement.lower() or search_lower in f.failure_reason.lower():
                return f
        return None

    def log_stage_progression(
        self,
        research_id: str,
        stage: str,
        summary: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> ResearchHistoryEntry:
        """Records an auditable stage event in the research lifecycle."""
        entry = ResearchHistoryEntry(
            entry_id=f"rhist_{uuid.uuid4().hex[:8]}",
            research_id=research_id,
            stage=stage,
            summary=summary,
            details=details or {},
            timestamp=datetime.now(timezone.utc),
        )
        self.store.record_history_entry(entry)
        return entry

    def get_all_findings(self, limit: int = 50) -> List[ResearchFinding]:
        return self.store.get_findings(limit=limit)

    def get_all_failed_hypotheses(self, limit: int = 50) -> List[FailedHypothesis]:
        return self.store.get_failed_hypotheses(limit=limit)

    def get_research_history(self, research_id: Optional[str] = None, limit: int = 100) -> List[ResearchHistoryEntry]:
        return self.store.get_history(research_id=research_id, limit=limit)
