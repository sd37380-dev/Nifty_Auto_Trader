"""
Tests for Brain Context Compiler and Prompt Architecture.
"""

from datetime import datetime, timezone
import pytest

from nifty_trader.brain.context import BrainContextCompiler
from nifty_trader.brain.prompts import SYSTEM_REASONING_POLICY, build_reasoning_prompt
from nifty_trader.contracts.models import (
    CandleObservation,
    CanonicalObservationStatus,
    CrossSourceValidation,
    CrossSourceValidationStatus,
    EvidenceType,
    ManualInstructionContext,
    NumericalObservation,
    ObservationEvidence,
    SensibullObservation,
    SourceStatus,
    TradingViewObservation,
    UnifiedMarketObservation,
    VisualObservation,
)


def test_brain_context_compiler_and_prompt_generation():
    now = datetime.now(timezone.utc)

    candles_1h = [
        CandleObservation(
            instrument="NIFTY",
            timeframe="1H",
            timestamp=now,
            open=25000.0,
            high=25100.0,
            low=24950.0,
            close=25080.0,
            volume=100000.0,
        ),
    ]
    candles_15m = [
        CandleObservation(
            instrument="NIFTY",
            timeframe="15M",
            timestamp=now,
            open=25050.0,
            high=25090.0,
            low=25040.0,
            close=25080.0,
            volume=25000.0,
        ),
    ]

    tv = TradingViewObservation(
        status=CanonicalObservationStatus.SUCCESS,
        visible_price=25082.0,
        visible_chart_context={"pattern": "Consolidation near high of session"},
        evidence_ids=["ev_tv_01"],
    )

    sensi = SensibullObservation(
        status=CanonicalObservationStatus.SUCCESS,
        spot_reference=25080.0,
        pcr=1.15,
        max_pain=25000.0,
        visible_strikes=[24900.0, 25000.0, 25100.0],
        evidence_ids=["ev_sensi_01"],
    )

    obs = UnifiedMarketObservation(
        observation_id="obs_unit_test_99",
        observed_at=now,
        instrument="NIFTY",
        session="OPEN",
        numerical=NumericalObservation(
            candles_1h=candles_1h,
            candles_15m=candles_15m,
        ),
        visual=VisualObservation(
            tradingview=tv,
            sensibull=sensi,
        ),
        source_status={
            "numerical": SourceStatus(source_id="numerical", status=CanonicalObservationStatus.SUCCESS, completeness=1.0),
            "tradingview": SourceStatus(source_id="tradingview", status=CanonicalObservationStatus.SUCCESS, completeness=1.0),
            "sensibull": SourceStatus(source_id="sensibull", status=CanonicalObservationStatus.SUCCESS, completeness=1.0),
        },
        cross_source_validation=[
            CrossSourceValidation(
                source_a="numerical",
                source_b="tradingview",
                field="close_price",
                status=CrossSourceValidationStatus.MATCH,
                absolute_difference=2.0,
                relative_difference=0.008,
            )
        ],
        manual_instruction_context=[
            ManualInstructionContext(
                instruction_id="inst_001",
                text="Pay attention to call unwinding above 25100",
                priority="HIGH",
                status="ACTIVE",
                created_at=now,
            )
        ],
        evidence=[
            ObservationEvidence(
                evidence_id="ev_tv_01",
                source_id="tradingview",
                evidence_type=EvidenceType.VISIBLE_TEXT,
                excerpt="NIFTY 50 25082.00",
            ),
            ObservationEvidence(
                evidence_id="ev_sensi_01",
                source_id="sensibull",
                evidence_type=EvidenceType.NUMERICAL_DATA,
                excerpt="PCR 1.15 Max Pain 25000",
            ),
        ],
    )

    compiler = BrainContextCompiler()
    context = compiler.compile(obs)

    assert context["observation_id"] == "obs_unit_test_99"
    assert "25080.00" in context["h1_context"]
    assert "25082.0" in context["tradingview_visual"]
    assert "1.15" in context["sensibull_derivatives"]
    assert "ev_tv_01" in context["evidence_catalog"]
    assert "Pay attention to call unwinding" in context["operator_instructions"]

    prompt = build_reasoning_prompt(context)
    assert "obs_unit_test_99" in prompt
    assert "1H STRUCTURAL CONTEXT" in prompt
    assert "TACTICAL 15M MARKET STATE" in prompt
    assert "DERIVATIVES SENTIMENT" in prompt
    assert "COGNITIVE REASONING TASK" in prompt
    assert "CRITICAL INVARIANTS" in SYSTEM_REASONING_POLICY
