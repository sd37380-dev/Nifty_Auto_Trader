"""
Unit tests for Dhan Futures Service.
Verifies symbol resolution, fallback modeling, volume profile calculation, and credential handling.
"""

import pytest
from nifty_trader.market_data.dhan_futures_service import DhanFuturesService, get_dhan_futures_service


def test_dhan_futures_service_singleton():
    svc1 = get_dhan_futures_service()
    svc2 = get_dhan_futures_service()
    assert svc1 is svc2


def test_symbol_resolution():
    svc = get_dhan_futures_service()
    assert svc.resolve_future_symbol("NIFTY FUT") == ("NIFTY_FUT", "NIFTY")
    assert svc.resolve_future_symbol("nifty_fut") == ("NIFTY_FUT", "NIFTY")
    assert svc.resolve_future_symbol("BANKNIFTY FUT") == ("BANKNIFTY_FUT", "BANKNIFTY")
    assert svc.resolve_future_symbol("FINNIFTY FUT") == ("FINNIFTY_FUT", "FINNIFTY")
    assert svc.resolve_future_symbol("RELIANCE") is None


def test_volume_profile_calculation():
    svc = get_dhan_futures_service()
    candles = [
        {"time": 100, "open": 25000, "high": 25050, "low": 24980, "close": 25020, "volume": 1000},
        {"time": 200, "open": 25020, "high": 25080, "low": 25010, "close": 25070, "volume": 5000},
        {"time": 300, "open": 25070, "high": 25100, "low": 25060, "close": 25090, "volume": 2000},
    ]
    vp = svc.calculate_volume_profile(candles)
    assert vp["total_volume"] == 8000
    assert 24980 <= vp["poc"] <= 25100
    assert vp["val"] <= vp["poc"] <= vp["vah"]


def test_modeled_candles_without_credentials():
    svc = get_dhan_futures_service()
    spot_candles = [
        {"time": 1700000000, "open": 25600.0, "high": 25620.0, "low": 25590.0, "close": 25615.0, "volume": 10000},
    ]
    res = svc.get_futures_candles("NIFTY FUT", interval="5m", range_str="5d", spot_candles=spot_candles)
    assert res["status"] == "ok"
    assert res["symbol"] == "NIFTY_FUT"
    assert len(res["candles"]) == 1
    # Futures close should include basis offset (> spot close)
    assert res["candles"][0]["close"] > spot_candles[0]["close"]
    assert res["basis"]["status"] == "PREMIUM (CONTANGO)"
    assert res["volume_profile"]["total_volume"] > 0
