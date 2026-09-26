"""
Tests for Observation Planner (Package 3.1).

Covers:
- Configuration-based source planning
- Manual operator steering directives (e.g. "Check Sensibull")
- Command-line source overrides
- Strict safety boundary enforcement when instructions contain trading directives
"""

import pytest

from nifty_trader.instruction.models import AgentInstruction, InstructionPriority
from nifty_trader.observation.planner import ObservationPlan, ObservationPlanner


def test_planner_default_all_enabled():
    planner = ObservationPlanner(
        tradingview_enabled=True,
        sensibull_enabled=True,
        numerical_enabled=True,
    )
    plan = planner.plan_observation()
    assert plan.is_numerical_requested is True
    assert plan.is_tradingview_requested is True
    assert plan.is_sensibull_requested is True
    assert set(plan.required_sources) == {"numerical", "tradingview", "sensibull"}


def test_planner_sensibull_disabled():
    planner = ObservationPlanner(
        tradingview_enabled=True,
        sensibull_enabled=False,
        numerical_enabled=True,
    )
    plan = planner.plan_observation()
    assert plan.is_sensibull_requested is False
    assert "sensibull" not in plan.required_sources


def test_planner_manual_instruction_triggers_sensibull():
    """Even if Sensibull is disabled by default, an operator directive schedules it."""
    planner = ObservationPlanner(
        tradingview_enabled=True,
        sensibull_enabled=False,
        numerical_enabled=True,
    )
    instruction = AgentInstruction(
        text="Please inspect Sensibull option chain and PCR for this cycle.",
        priority=InstructionPriority.HIGH,
    )
    plan = planner.plan_observation(instructions=[instruction])
    assert plan.is_sensibull_requested is True
    assert "sensibull" in plan.required_sources
    assert any("INSTRUCTION" in t for t in plan.triggers)


def test_planner_cli_overrides():
    planner = ObservationPlanner(
        tradingview_enabled=True,
        sensibull_enabled=True,
        numerical_enabled=True,
    )
    plan = planner.plan_observation(source_overrides=["sensibull", "numerical"])
    assert plan.is_sensibull_requested is True
    assert plan.is_numerical_requested is True
    assert plan.is_tradingview_requested is False
    assert set(plan.required_sources) == {"sensibull", "numerical"}


def test_planner_trading_directive_neutralized():
    """An instruction saying 'Buy NIFTY because PCR is bullish' must generate a safety note and remain observation-only."""
    planner = ObservationPlanner()
    instruction = AgentInstruction(
        text="Buy NIFTY 24500 CE because PCR is 1.4 bullish.",
        priority=InstructionPriority.NORMAL,
    )
    plan = planner.plan_observation(instructions=[instruction])
    # The planner must record a safety notice that trading directives are ignored
    assert len(plan.safety_notes) > 0
    assert "Safety Boundary Notice" in plan.safety_notes[0]
    # Sensibull is triggered as an observation, NOT a trade
    assert plan.is_sensibull_requested is True
