"""
Unit tests for Package 5 RequestDeduplicator and AutonomousObservationPlanner.
"""

from datetime import datetime, timedelta, timezone
import pytest

from nifty_trader.autonomous.contracts import (
    AutonomousLimits,
    ObservationPriority,
)
from nifty_trader.autonomous.deduplication import RequestDeduplicator
from nifty_trader.autonomous.observation_planner import AutonomousObservationPlanner
from nifty_trader.brain.contracts import ObservationRequest


def test_fingerprint_deterministic():
    fp1 = RequestDeduplicator.compute_fingerprint("sensibull", ["PCR", "OI", "MAX_PAIN"])
    # Different case and order should yield identical fingerprint
    fp2 = RequestDeduplicator.compute_fingerprint("SENSIBULL", ["max_pain", "pcr", "oi"])
    assert fp1 == fp2

    # Different source yields different fingerprint
    fp3 = RequestDeduplicator.compute_fingerprint("tradingview", ["pcr", "oi", "max_pain"])
    assert fp1 != fp3


def test_deduplicator_cooldown():
    limits = AutonomousLimits(sensibull_cooldown_seconds=60.0)
    dedup = RequestDeduplicator(limits)
    now = datetime(2026, 9, 27, 10, 0, 0, tzinfo=timezone.utc)

    req = ObservationRequest(
        source="sensibull",
        reason="Refresh PCR",
        requested_information=["pcr"],
    )

    # 1. First request is not duplicate
    is_dup, _ = dedup.is_suppressed_or_duplicate(req, current_time=now)
    assert is_dup is False

    # Mark executed at 10:00:00
    fp = dedup.compute_fingerprint(req.source, req.requested_information)
    dedup.mark_executed(fp, timestamp=now)

    # 2. Repeated request at 10:00:15 (inside 60s cooldown) is suppressed
    t15 = now + timedelta(seconds=15)
    is_dup2, reason2 = dedup.is_suppressed_or_duplicate(req, current_time=t15)
    assert is_dup2 is True
    assert "inside cooldown" in reason2

    # 3. Repeated request at 10:01:05 (outside 60s cooldown) is permitted
    t65 = now + timedelta(seconds=65)
    is_dup3, _ = dedup.is_suppressed_or_duplicate(req, current_time=t65)
    assert is_dup3 is False


def test_observation_planner_filters_expired_requests():
    planner = AutonomousObservationPlanner()
    now = datetime(2026, 9, 27, 10, 0, 0, tzinfo=timezone.utc)

    # Expired request
    expired_req = ObservationRequest(
        source="sensibull",
        reason="Old request",
        requested_information=["pcr"],
        expires_at=now - timedelta(minutes=5),
    )
    # Valid request
    valid_req = ObservationRequest(
        source="tradingview",
        reason="Valid chart check",
        requested_information=["levels"],
        expires_at=now + timedelta(minutes=15),
    )

    plans = planner.plan_requests([expired_req, valid_req], current_time=now)

    assert len(plans) == 1
    assert plans[0].source == "tradingview"


def test_observation_planner_priority_sorting():
    planner = AutonomousObservationPlanner()
    now = datetime(2026, 9, 27, 10, 0, 0, tzinfo=timezone.utc)

    req_low = ObservationRequest(source="source_low", reason="r", priority="LOW")
    req_crit = ObservationRequest(source="source_crit", reason="r", priority="CRITICAL")
    req_norm = ObservationRequest(source="source_norm", reason="r", priority="NORMAL")

    plans = planner.plan_requests([req_low, req_crit, req_norm], current_time=now)

    assert len(plans) == 3
    assert plans[0].source == "source_crit"
    assert plans[0].priority == ObservationPriority.CRITICAL
    assert plans[1].source == "source_norm"
    assert plans[2].source == "source_low"


def test_determine_sources_for_cycle():
    planner = AutonomousObservationPlanner()
    now = datetime(2026, 9, 27, 10, 0, 0, tzinfo=timezone.utc)

    # Initially only base numerical source
    sources = planner.determine_sources_for_cycle(base_sources=["numerical"])
    assert sources == ["numerical"]

    # Plan a sensibull request
    req = ObservationRequest(source="sensibull", reason="Need OI data")
    planner.plan_requests([req], current_time=now)

    sources_with_plan = planner.determine_sources_for_cycle(base_sources=["numerical"])
    assert set(sources_with_plan) == {"numerical", "sensibull"}

    # Mark executed
    planner.mark_source_executed("sensibull", timestamp=now)
    assert planner.determine_sources_for_cycle(base_sources=["numerical"]) == ["numerical"]
