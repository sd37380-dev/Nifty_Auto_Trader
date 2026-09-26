"""
Unit tests for MarketCrossChecker (Browser vs Numerical Data Validation).
"""

from datetime import datetime, timezone
import pytest

from nifty_trader.browser.models import BrowserObservation, SourceType
from nifty_trader.market_data.cross_check import MarketCrossChecker
from nifty_trader.market_data.models import Candle, Timeframe


def test_cross_check_perfect_match():
    checker = MarketCrossChecker(tolerance_pct=0.5)

    obs = BrowserObservation(
        url="https://in.tradingview.com/chart/?symbol=NSE%3ANIFTY",
        page_title="NIFTY 50 Index Chart - 23,140.50 INR",
        source_type=SourceType.CHART,
        visible_text="NIFTY 50 23,140.50 +45.20 (+0.20%)",
    )

    candle = Candle(
        symbol="NIFTY",
        timeframe=Timeframe.M15,
        timestamp=datetime.now(timezone.utc),
        open=23120.0,
        high=23150.0,
        low=23100.0,
        close=23140.50,
        is_closed=True,
    )

    result = checker.cross_check(obs, candle)
    assert result.is_aligned is True
    assert result.status == "MATCH"
    assert result.browser_price == 23140.50
    assert result.numerical_price == 23140.50
    assert result.discrepancy_points == 0.0
    assert result.discrepancy_pct == 0.0


def test_cross_check_within_tolerance():
    checker = MarketCrossChecker(tolerance_pct=0.5)

    obs = BrowserObservation(
        url="https://in.tradingview.com/chart/?symbol=NSE%3ANIFTY",
        page_title="NIFTY 50 23,150.00",
        source_type=SourceType.CHART,
        visible_text="Price 23,150.00",
    )

    # 23,140 vs 23,150 -> 10 pts difference out of 23140 is ~0.043% (well within 0.5%)
    candle = Candle(
        symbol="NIFTY",
        timeframe=Timeframe.M15,
        timestamp=datetime.now(timezone.utc),
        open=23120.0,
        high=23160.0,
        low=23100.0,
        close=23140.00,
        is_closed=True,
    )

    result = checker.cross_check(obs, candle)
    assert result.is_aligned is True
    assert result.status == "MATCH"
    assert result.discrepancy_pct < 0.1


def test_cross_check_mismatch_detected():
    checker = MarketCrossChecker(tolerance_pct=0.5)

    # Browser shows 23,500 while numerical feed shows 23,140 (> 1.5% difference)
    obs = BrowserObservation(
        url="https://in.tradingview.com/chart/?symbol=NSE%3ANIFTY",
        page_title="NIFTY 50 23,500.00",
        source_type=SourceType.CHART,
        visible_text="NIFTY 50 23,500.00",
    )

    candle = Candle(
        symbol="NIFTY",
        timeframe=Timeframe.M15,
        timestamp=datetime.now(timezone.utc),
        open=23100.0,
        high=23150.0,
        low=23080.0,
        close=23140.00,
        is_closed=True,
    )

    result = checker.cross_check(obs, candle)
    assert result.is_aligned is False
    assert result.status == "MISMATCH"
    assert result.discrepancy_pct > 1.0


def test_cross_check_insufficient_data():
    checker = MarketCrossChecker()

    obs_no_price = BrowserObservation(
        url="https://example.com",
        page_title="Example Domain",
        source_type=SourceType.GENERAL_WEB,
        visible_text="No price data here",
    )

    candle = Candle(
        symbol="NIFTY",
        timeframe=Timeframe.M15,
        timestamp=datetime.now(timezone.utc),
        open=23100.0,
        high=23150.0,
        low=23080.0,
        close=23140.00,
        is_closed=True,
    )

    result = checker.cross_check(obs_no_price, candle)
    assert result.status == "INSUFFICIENT_DATA"
    assert result.browser_price is None
