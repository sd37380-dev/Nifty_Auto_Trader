"""
Package 5: Autonomous Observation Planner.

Translates Package 4 ObservationRequests into concrete, scheduled observation
plans. Applies deduplication, cooldown validation, expiration filtering, and
priority sorting to determine which sources must be interrogated in upcoming cycles.
"""

from datetime import datetime, timezone
import logging
from typing import Dict, List, Optional, Set, Tuple
import uuid

from nifty_trader.autonomous.contracts import (
    AutonomousLimits,
    ObservationPriority,
    ScheduledObservationPlan,
)
from nifty_trader.autonomous.deduplication import RequestDeduplicator
from nifty_trader.brain.contracts import ObservationRequest

logger = logging.getLogger(__name__)


class AutonomousObservationPlanner:
    """
    Coordinates scheduling, deduplication, and execution planning for observation requests.
    """

    def __init__(
        self,
        deduplicator: Optional[RequestDeduplicator] = None,
        limits: Optional[AutonomousLimits] = None,
    ):
        self.limits = limits or AutonomousLimits()
        self.deduplicator = deduplicator or RequestDeduplicator(self.limits)
        self._active_plans: Dict[str, ScheduledObservationPlan] = {}

    def plan_requests(
        self,
        requests: List[ObservationRequest],
        current_time: Optional[datetime] = None,
    ) -> List[ScheduledObservationPlan]:
        """
        Processes incoming observation requests from Package 4, filtering out
        expired or duplicate requests and creating ScheduledObservationPlans.
        """
        now = current_time or datetime.now(timezone.utc)
        plans: List[ScheduledObservationPlan] = []

        # Sort incoming requests by priority (CRITICAL > HIGH > NORMAL > LOW)
        prio_order = {"CRITICAL": 0, "HIGH": 1, "NORMAL": 2, "LOW": 3}
        sorted_requests = sorted(requests, key=lambda r: prio_order.get(r.priority, 2))

        # Enforce max observation requests limit
        if len(self._active_plans) >= self.limits.max_observation_requests:
            logger.warning(
                "Max observation requests limit (%d) reached. Dropping new observation requests.",
                self.limits.max_observation_requests,
            )
            return []

        for req in sorted_requests:
            # 1. Check expiration
            if req.expires_at and now > req.expires_at:
                logger.info("Observation request '%s' for '%s' is expired. Skipping.", req.request_id, req.source)
                continue

            # 2. Check deduplication & cooldown
            is_dup, dup_reason = self.deduplicator.is_suppressed_or_duplicate(req, current_time=now)
            fp = self.deduplicator.compute_fingerprint(req.source, req.requested_information)

            if is_dup:
                logger.info("Observation request '%s' suppressed: %s", req.request_id, dup_reason)
                continue

            # 3. Create ScheduledObservationPlan
            plan = ScheduledObservationPlan(
                plan_id=f"plan_{uuid.uuid4().hex[:8]}",
                source=req.source.lower(),
                requested_information=req.requested_information,
                priority=ObservationPriority(req.priority),
                scheduled_at=now,
                expires_at=req.expires_at,
                request_fingerprint=fp,
                reason=req.reason,
                status="PENDING",
            )

            self.deduplicator.register_pending(fp)
            self._active_plans[plan.plan_id] = plan
            plans.append(plan)

        return plans

    def determine_sources_for_cycle(
        self,
        base_sources: Optional[List[str]] = None,
        include_sensibull_override: bool = False,
    ) -> List[str]:
        """
        Determines the list of source channels to query for the next observation cycle.
        Merges base sources (e.g. numerical) with sources demanded by active plans.
        """
        sources: Set[str] = set(base_sources or ["numerical"])

        if include_sensibull_override:
            sources.add("sensibull")

        for plan in self._active_plans.values():
            if plan.status == "PENDING" and not plan.is_expired:
                sources.add(plan.source)

        return sorted(list(sources))

    def mark_plan_executed(self, plan_id: str, timestamp: Optional[datetime] = None) -> None:
        """Marks a plan as successfully executed."""
        plan = self._active_plans.get(plan_id)
        if plan:
            plan.status = "EXECUTED"
            self.deduplicator.mark_executed(plan.request_fingerprint, timestamp=timestamp)
            del self._active_plans[plan_id]

    def mark_source_executed(self, source: str, timestamp: Optional[datetime] = None) -> None:
        """Marks all pending plans for a given source as executed."""
        now = timestamp or datetime.now(timezone.utc)
        to_remove = []
        for pid, plan in self._active_plans.items():
            if plan.source.lower() == source.lower():
                plan.status = "EXECUTED"
                self.deduplicator.mark_executed(plan.request_fingerprint, timestamp=now)
                to_remove.append(pid)

        for pid in to_remove:
            del self._active_plans[pid]

    def get_pending_plans(self) -> List[ScheduledObservationPlan]:
        """Returns all currently pending observation plans."""
        return [p for p in self._active_plans.values() if p.status == "PENDING" and not p.is_expired]

    def clear(self) -> None:
        """Clears all active plans."""
        self._active_plans.clear()
        self.deduplicator.clear()
