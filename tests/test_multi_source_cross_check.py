"""
Tests for Multi-Source Cross-Check Engine (Package 3.1).

Covers:
- Discrepancy thresholds: MATCH, MINOR_DIFFERENCE, SIGNIFICANT_DIFFERENCE
- Missing source data: INSUFFICIENT_DATA
- Multi-source consistency logic
- Preservation of original prices across all sources
"""

from datetime import datetime, timezone
import pytest

from nifty_trader.browser.models import BrowserObservation, SourceType
from nifty_trader.market_data.models import Candle, Timeframe
from nifty_trader.observation.cross_check import MultiSourceCrossChecker
from nifty_trader.observation.models import SensibullObservation, SensibullStatus


@pytest.fixture
def base_candle():
    return Candle(
        timestamp=datetime.now(timezone.utc),
        symbol="NIFTY",
        timeframe=Timeframe.M15,
        open=24500.0,
        high=24550.0,
        low=24480.0,
        close=24500.0,
        is_closed=True,
    )


def test_cross_check_perfect_match(base_candle):
    checker = MultiSourceCrossChecker(match_tolerance_pct=0.5, minor_tolerance_pct=1.5)
    sensi_obs = SensibullObservation(
        status=SensibullStatus.OBSERVED,
        spot_reference=24510.0,  # ~0.04% diff
    )
    tv_obs = BrowserObservation(
        url="https://in.tradingview.com",
        page_title="NIFTY Chart",
        source_type=SourceType.CHART,
        visible_text="NIFTY 50 24,505.00 Index",
    )

    result = checker.compare_sources(
        numerical_candle=base_candle,
        sensibull_obs=sensi_obs,
        tradingview_obs=tv_obs,
    )

    assert result.sensibull_vs_numerical_status == "MATCH"
    assert result.tradingview_vs_numerical_status == "MATCH"
    assert result.is_consistent is True
    assert result.sensibull_spot == 24510.0
    assert result.numerical_close == 24500.0


def test_cross_check_minor_difference(base_candle):
    checker = MultiSourceCrossChecker(match_tolerance_pct=0.5, minor_tolerance_pct=1.5)
    sensi_obs = SensibullObservation(
        status=SensibullStatus.OBSERVED,
        spot_reference=24700.0,  # diff = 200 pts (0.816%) -> MINOR
    )

    result = checker.compare_sources(
        numerical_candle=base_candle,
        sensibull_obs=sensi_obs,
    )

    assert result.sensibull_vs_numerical_status == "MINOR_DIFFERENCE"
    assert result.is_consistent is True


def test_cross_check_significant_difference(base_candle):
    checker = MultiSourceCrossChecker(match_tolerance_pct=0.5, minor_tolerance_pct=1.5)
    sensi_obs = SensibullObservation(
        status=SensibullStatus.OBSERVED,
        spot_reference=25000.0,  # diff = 500 pts (2.04%) -> SIGNIFICANT
    )

    result = checker.compare_sources(
        numerical_candle=base_candle,
        sensibull_obs=sensi_obs,
    )

    assert result.sensibull_vs_numerical_status == "SIGNIFICANT_DIFFERENCE"
    assert result.is_consistent is False
    assert any("[DISCREPANCY]" in d for d in result.details)


def test_cross_check_insufficient_data(base_candle):
    checker = MultiSourceCrossChecker()
    # Sensibull with no spot reference (e.g. auth required)
    sensi_obs = SensibullObservation(
        status=SensibullStatus.AUTHENTICATION_REQUIRED,
        spot_reference=None,
    )

    result = checker.compare_sources(
        numerical_candle=base_candle,
        sensibull_obs=sensi_obs,
    )

    assert result.sensibull_vs_numerical_status == "INSUFFICIENT_DATA"
    assert result.sensibull_spot is None
