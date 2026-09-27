"""
Unit tests for Package 5 MeaningfulChangeDetector and SourceFreshnessChecker.
"""

from datetime import datetime, timedelta, timezone
import pytest

from nifty_trader.autonomous.change_detector import MeaningfulChangeDetector
from nifty_trader.autonomous.contracts import SourceFreshnessStatus
from nifty_trader.autonomous.freshness import SourceFreshnessChecker
from nifty_trader.contracts.models import (
    CandleObservation,
    CanonicalObservationStatus,
    NumericalObservation,
    SensibullObservation,
    SourceStatus,
    UnifiedMarketObservation,
    VisualObservation,
)


def _make_obs(price: float, candle_time: datetime, pcr: float = 1.0) -> UnifiedMarketObservation:
    c15 = CandleObservation(
        timeframe="15M",
        timestamp=candle_time,
        open=price,
        high=price + 5,
        low=price - 5,
        close=price,
    )
    sensi = SensibullObservation(
        status=CanonicalObservationStatus.SUCCESS,
        observed_at=candle_time,
        pcr=pcr,
        max_pain=25000.0,
    )
    return UnifiedMarketObservation(
        observed_at=candle_time,
        numerical=NumericalObservation(candles_15m=[c15]),
        visual=VisualObservation(sensibull=sensi),
        source_status={
            "numerical": SourceStatus(source_id="numerical", status=CanonicalObservationStatus.SUCCESS),
        },
    )


def test_change_detector_initial_obs():
    detector = MeaningfulChangeDetector()
    t = datetime(2026, 9, 27, 10, 0, 0, tzinfo=timezone.utc)
    obs = _make_obs(price=25000.0, candle_time=t)

    is_meaningful, reasons = detector.detect_changes(current_obs=obs, previous_obs=None)
    assert is_meaningful is True
    assert "INITIAL_OBSERVATION" in reasons[0]


def test_change_detector_suppresses_redundant_obs():
    detector = MeaningfulChangeDetector()
    t = datetime(2026, 9, 27, 10, 0, 0, tzinfo=timezone.utc)
    obs1 = _make_obs(price=25000.0, candle_time=t, pcr=1.0)
    # Identical prices, timestamps, and PCR
    obs2 = _make_obs(price=25000.0, candle_time=t, pcr=1.0)

    is_meaningful, reasons = detector.detect_changes(current_obs=obs2, previous_obs=obs1)
    assert is_meaningful is False
    assert len(reasons) == 0


def test_change_detector_candle_completion():
    detector = MeaningfulChangeDetector()
    t1 = datetime(2026, 9, 27, 10, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 27, 10, 15, 0, tzinfo=timezone.utc)

    obs1 = _make_obs(price=25000.0, candle_time=t1)
    obs2 = _make_obs(price=25000.0, candle_time=t2)  # New candle completed

    is_meaningful, reasons = detector.detect_changes(current_obs=obs2, previous_obs=obs1)
    assert is_meaningful is True
    assert any("NEW_CANDLE" in r for r in reasons)


def test_change_detector_price_movement():
    detector = MeaningfulChangeDetector()
    t = datetime(2026, 9, 27, 10, 0, 0, tzinfo=timezone.utc)

    obs1 = _make_obs(price=25000.0, candle_time=t)
    # 25035 is +0.14% > 0.10% threshold
    obs2 = _make_obs(price=25035.0, candle_time=t)

    is_meaningful, reasons = detector.detect_changes(current_obs=obs2, previous_obs=obs1)
    assert is_meaningful is True
    assert any("PRICE_MOVEMENT" in r for r in reasons)


def test_change_detector_pcr_shift():
    detector = MeaningfulChangeDetector()
    t = datetime(2026, 9, 27, 10, 0, 0, tzinfo=timezone.utc)

    obs1 = _make_obs(price=25000.0, candle_time=t, pcr=1.00)
    # PCR shifted by 0.08 >= 0.05 threshold
    obs2 = _make_obs(price=25000.0, candle_time=t, pcr=1.08)

    is_meaningful, reasons = detector.detect_changes(current_obs=obs2, previous_obs=obs1)
    assert is_meaningful is True
    assert any("SOURCE_REFRESH" in r for r in reasons)


def test_source_freshness_checker_tiers():
    checker = SourceFreshnessChecker(ttls={"sensibull": 180.0})
    now = datetime(2026, 9, 27, 10, 0, 0, tzinfo=timezone.utc)

    # 1. Fresh (age 30s < 90s)
    f1 = checker.evaluate_source("sensibull", now - timedelta(seconds=30), CanonicalObservationStatus.SUCCESS, now)
    assert f1 == SourceFreshnessStatus.FRESH

    # 2. Aging (age 120s: 90s <= age < 180s)
    f2 = checker.evaluate_source("sensibull", now - timedelta(seconds=120), CanonicalObservationStatus.SUCCESS, now)
    assert f2 == SourceFreshnessStatus.AGING

    # 3. Stale (age 240s: 180s <= age < 360s)
    f3 = checker.evaluate_source("sensibull", now - timedelta(seconds=240), CanonicalObservationStatus.SUCCESS, now)
    assert f3 == SourceFreshnessStatus.STALE

    # 4. Expired (age 400s >= 360s)
    f4 = checker.evaluate_source("sensibull", now - timedelta(seconds=400), CanonicalObservationStatus.SUCCESS, now)
    assert f4 == SourceFreshnessStatus.EXPIRED

    # 5. Failed status
    f5 = checker.evaluate_source("sensibull", now - timedelta(seconds=10), CanonicalObservationStatus.SOURCE_ERROR, now)
    assert f5 == SourceFreshnessStatus.FAILED
