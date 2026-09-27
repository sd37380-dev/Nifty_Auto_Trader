"""
Package 5: Observation Deduplication & Cooldown Manager.

Prevents duplicate or runaway observation requests from executing within
configured cooldown windows or within the same cognitive cycle.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import logging
from typing import Dict, List, Optional, Set, Tuple

from nifty_trader.autonomous.contracts import AutonomousLimits
from nifty_trader.brain.contracts import ObservationRequest

logger = logging.getLogger(__name__)


class RequestDeduplicator:
    """
    Manages deterministic request fingerprints, execution history, and cooldown enforcement.
    """

    def __init__(self, limits: Optional[AutonomousLimits] = None):
        self.limits = limits or AutonomousLimits()
        # fingerprint -> last_executed_timestamp
        self._execution_history: Dict[str, datetime] = {}
        # active/pending fingerprints
        self._pending_fingerprints: Set[str] = set()

    @staticmethod
    def compute_fingerprint(source: str, requested_information: List[str]) -> str:
        """
        Computes a deterministic hash fingerprint for an observation request.
        """
        src_clean = source.strip().lower()
        items_clean = sorted(item.strip().lower() for item in requested_information)
        payload = f"{src_clean}::{'|'.join(items_clean)}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def get_source_cooldown(self, source: str) -> float:
        """Returns the configured cooldown seconds for the given source channel."""
        s = source.lower()
        if "sensibull" in s:
            return self.limits.sensibull_cooldown_seconds
        elif "tradingview" in s:
            return self.limits.tradingview_cooldown_seconds
        return self.limits.default_cooldown_seconds

    def is_suppressed_or_duplicate(
        self,
        request: ObservationRequest,
        current_time: Optional[datetime] = None,
    ) -> Tuple[bool, str]:
        """
        Checks if the request is an in-flight duplicate or inside cooldown.
        Returns: (is_duplicate_or_suppressed: bool, reason: str)
        """
        now = current_time or datetime.now(timezone.utc)
        fp = self.compute_fingerprint(request.source, request.requested_information)

        # 1. Active pending check
        if fp in self._pending_fingerprints:
            return True, f"Identical request '{fp}' is already pending in the observation queue."

        # 2. Cooldown check
        last_exec = self._execution_history.get(fp)
        if last_exec:
            cooldown = self.get_source_cooldown(request.source)
            elapsed = (now - last_exec).total_seconds()
            if elapsed < cooldown:
                remaining = cooldown - elapsed
                return True, (
                    f"Request '{fp}' for source '{request.source}' is inside cooldown "
                    f"({elapsed:.1f}s elapsed < {cooldown:.1f}s cooldown, {remaining:.1f}s remaining)."
                )

        return False, "Request is unique and outside cooldown."

    def register_pending(self, fingerprint: str) -> None:
        """Marks a request fingerprint as in-flight pending."""
        self._pending_fingerprints.add(fingerprint)

    def mark_executed(self, fingerprint: str, timestamp: Optional[datetime] = None) -> None:
        """Marks a request as executed and records its execution timestamp for cooldown."""
        now = timestamp or datetime.now(timezone.utc)
        self._pending_fingerprints.discard(fingerprint)
        self._execution_history[fingerprint] = now

    def discard_pending(self, fingerprint: str) -> None:
        """Discards a pending request (e.g. if cancelled or failed)."""
        self._pending_fingerprints.discard(fingerprint)

    def clear(self) -> None:
        """Resets all tracking history."""
        self._execution_history.clear()
        self._pending_fingerprints.clear()
