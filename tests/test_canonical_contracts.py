"""
Tests for Canonical Observation Contracts (Package 3 / 3.1 Hardening).

Covers:
- ObservationSource consistent identification
- ObservationStatus enums (never fake values)
- ObservationEvidence traceability
- CandleObservation (UTC storage, IST property, complete vs forming segregation)
- TradingViewObservation (evidence linking, neutral visual context)
- SensibullObservation & OptionChainObservation (normalized strikes, null preservation)
- SourceStatus telemetry (latency, completeness, data age)
- CrossSourceValidation (MATCH, MINOR_DIFFERENCE, SIGNIFICANT_DIFFERENCE, UNCOMPARABLE)
- ManualInstructionContext preservation
- UnifiedObservationBuilder assembly and UnifiedMarketObservation verification
"""

from datetime import datetime, timezone
import pytest

from nifty_trader.browser.models import BrowserObservation, SourceType
from nifty_trader.contracts.builder import UnifiedObservationBuilder
from nifty_trader.contracts.models import (
    CandleObservation,
    CanonicalObservationStatus,
    CrossSourceValidation,
    CrossSourceValidationStatus,
    EvidenceType,
    ManualInstructionContext,
    NumericalObservation,
    ObservationEvidence,
    ObservationSource,
    ObservationWarning,
    OptionChainObservation,
    OptionLegObservation,
    OptionStrikeObservation,
    SensibullObservation as CanonicalSensibullObservation,
    SourceChannelType,
    SourceStatus,
    TradingViewObservation,
    UnifiedMarketObservation,
    VisualObservation,
    WarningSeverity,
)
from nifty_trader.instruction.models import AgentInstruction, InstructionPriority
from nifty_trader.market_data.models import Candle, MarketSessionStatus, Timeframe
from nifty_trader.observation.models import (
    OptionChainStrike,
    SensibullObservation as RawSensibullObservation,
    SensibullStatus,
)


def test_observation_source_contract():
    src = ObservationSource(
        source_id="sensibull",
        source_type=SourceChannelType.BROWSER,
        provider="Sensibull Technologies",
        version="1.0.0",
        capabilities=["option_chain", "pcr", "max_pain"],
    )
    assert src.schema_version == "1.0"
    assert src.source_id == "sensibull"
    assert src.source_type == SourceChannelType.BROWSER
    assert "pcr" in src.capabilities


def test_observation_evidence_traceability():
    ev = ObservationEvidence(
        source_id="sensibull",
        evidence_type=EvidenceType.SCREENSHOT,
        reference="/path/to/sensi_screenshot.png",
        excerpt="PCR: 0.95 at 24500",
        metadata={"resolution": "1920x1080"},
    )
    assert ev.schema_version == "1.0"
    assert ev.evidence_id.startswith("ev_")
    assert ev.evidence_type == EvidenceType.SCREENSHOT
    assert ev.reference == "/path/to/sensi_screenshot.png"


def test_candle_observation_utc_and_ist():
    now_utc = datetime(2026, 9, 26, 10, 0, 0, tzinfo=timezone.utc)
    c = CandleObservation(
        instrument="NIFTY",
        timeframe="15M",
        timestamp=now_utc,
        open=24500.0,
        high=24520.0,
        low=24490.0,
        close=24510.0,
        volume=150000.0,
        is_complete=True,
        source="yahoo_finance",
    )
    assert c.schema_version == "1.0"
    assert c.timestamp == now_utc
    # 10:00 UTC == 15:30 IST
    assert c.timestamp_ist.hour == 15
    assert c.timestamp_ist.minute == 30
    assert c.is_complete is True


def test_option_chain_contract_null_preservation():
    """Missing metrics must remain None, never coerced to fake 0.0."""
    strike = OptionStrikeObservation(
        strike=24500.0,
        call=OptionLegObservation(ltp=120.5, oi=50000.0, oi_change=None, iv=13.5),
        put=OptionLegObservation(ltp=95.0, oi=65000.0, oi_change=None, iv=None),
    )
    chain = OptionChainObservation(
        underlying="NIFTY",
        expiry="2026-11-28",
        observed_at=datetime.now(timezone.utc),
        spot=24510.0,
        strikes=[strike],
        source="sensibull",
    )
    assert chain.strikes[0].call.oi_change is None
    assert chain.strikes[0].put.iv is None
    assert chain.strikes[0].call.ltp == 120.5


def test_cross_source_validation_status():
    csv = CrossSourceValidation(
        field="spot_price",
        source_a="sensibull",
        value_a=24510.0,
        source_b="numerical_feed",
        value_b=24500.0,
        absolute_difference=10.0,
        relative_difference=0.041,
        tolerance=0.5,
        status=CrossSourceValidationStatus.MATCH,
    )
    assert csv.schema_version == "1.0"
    assert csv.status == CrossSourceValidationStatus.MATCH
    assert csv.relative_difference == 0.041


def test_unified_observation_builder_full_cycle():
    builder = UnifiedObservationBuilder()
    now = datetime.now(timezone.utc)

    # 1. Numerical candles
    c1h = Candle(
        timestamp=now,
        symbol="NIFTY",
        timeframe=Timeframe.H1,
        open=24400.0,
        high=24550.0,
        low=24380.0,
        close=24500.0,
        is_closed=True,
    )
    c15m = Candle(
        timestamp=now,
        symbol="NIFTY",
        timeframe=Timeframe.M15,
        open=24480.0,
        high=24520.0,
        low=24470.0,
        close=24500.0,
        is_closed=True,
    )

    # 2. TradingView visual
    tv_obs = BrowserObservation(
        url="https://in.tradingview.com/symbols/NSE-NIFTY/",
        page_title="NIFTY 50 Chart",
        source_type=SourceType.CHART,
        visible_text="NIFTY 50 24,502.00 INR Index",
        screenshot_path="/data/screenshots/tv_test.png",
    )

    # 3. Sensibull raw observation
    raw_sensi = RawSensibullObservation(
        status=SensibullStatus.OBSERVED,
        spot_reference=24505.0,
        pcr=1.05,
        max_pain_information=24500.0,
        strike_information=[OptionChainStrike(strike=24500.0, call_ltp=110.0, put_ltp=90.0)],
        screenshot_reference="/data/screenshots/sensi_test.png",
        visible_text="Sensibull NIFTY Option Chain",
    )

    # 4. Operator instruction
    instruction = AgentInstruction(
        text="Observe 24500 strike open interest concentration.",
        priority=InstructionPriority.HIGH,
    )

    unified: UnifiedMarketObservation = builder.build(
        symbol="NIFTY",
        session_status=MarketSessionStatus.OPEN,
        h1_candles=[c1h],
        m15_candles=[c15m],
        tradingview_obs=tv_obs,
        sensibull_obs=raw_sensi,
        instructions=[instruction],
    )

    # Assert canonical invariants
    assert unified.schema_version == "1.0"
    assert unified.observation_id.startswith("umo_")
    assert unified.instrument == "NIFTY"
    assert unified.session == "OPEN"

    # Numerical verification
    assert len(unified.numerical.candles_1h) == 1
    assert len(unified.numerical.candles_15m) == 1
    assert unified.numerical.latest_15m.close == 24500.0

    # Visual verification
    assert unified.visual.tradingview is not None
    assert unified.visual.tradingview.visible_price == 24502.0
    assert len(unified.visual.tradingview.evidence_ids) > 0

    assert unified.visual.sensibull is not None
    assert unified.visual.sensibull.status == CanonicalObservationStatus.SUCCESS
    assert unified.visual.sensibull.pcr == 1.05
    assert unified.visual.sensibull.max_pain == 24500.0
    assert len(unified.visual.sensibull.evidence_ids) > 0

    # Cross-source validation
    assert len(unified.cross_source_validation) >= 2
    for csv in unified.cross_source_validation:
        assert csv.status == CrossSourceValidationStatus.MATCH

    # Operator instruction context
    assert len(unified.manual_instruction_context) == 1
    assert unified.manual_instruction_context[0].text == "Observe 24500 strike open interest concentration."

    # Evidence traceability
    assert len(unified.evidence) >= 4
    types = {ev.evidence_type for ev in unified.evidence}
    assert EvidenceType.NUMERICAL_DATA in types
    assert EvidenceType.SCREENSHOT in types
    assert EvidenceType.VISIBLE_TEXT in types
    assert EvidenceType.USER_INSTRUCTION in types

    # Not partial
    assert unified.is_partial is False
    assert "PCR=1.05" in unified.summary_text


def test_unified_observation_partial_auth_required():
    builder = UnifiedObservationBuilder()
    now = datetime.now(timezone.utc)

    c15m = Candle(
        timestamp=now,
        symbol="NIFTY",
        timeframe=Timeframe.M15,
        open=24480.0,
        high=24520.0,
        low=24470.0,
        close=24500.0,
        is_closed=True,
    )

    raw_sensi = RawSensibullObservation(
        status=SensibullStatus.AUTHENTICATION_REQUIRED,
        warnings=["Sensibull page requires user broker login."],
        screenshot_reference="/data/screenshots/auth_page.png",
    )

    unified: UnifiedMarketObservation = builder.build(
        symbol="NIFTY",
        session_status=MarketSessionStatus.OPEN,
        m15_candles=[c15m],
        sensibull_obs=raw_sensi,
    )

    assert unified.visual.sensibull.status == CanonicalObservationStatus.AUTHENTICATION_REQUIRED
    assert unified.is_partial is True
    assert any(w.code == "AUTH_REQUIRED" for w in unified.warnings)
    assert unified.numerical.latest_15m.close == 24500.0
