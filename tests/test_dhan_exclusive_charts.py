import pytest
from unittest.mock import patch, PropertyMock
from nifty_trader.market_data.dhan_futures_service import DhanFuturesService, DHAN_SECURITY_MAP


def test_dhan_security_id_mapping():
    assert "NIFTY" in DHAN_SECURITY_MAP
    assert DHAN_SECURITY_MAP["NIFTY"][0] == "13"
    assert DHAN_SECURITY_MAP["BANKNIFTY"][0] == "25"
    assert DHAN_SECURITY_MAP["HDFCBANK"][0] == "1333"
    assert DHAN_SECURITY_MAP["RELIANCE"][0] == "2885"
    assert DHAN_SECURITY_MAP["NIFTY_FUT"][0] == "49557"


def test_dhan_futures_symbol_resolver():
    dfs = DhanFuturesService.get_instance()
    res = dfs.resolve_future_symbol("NIFTY FUT")
    assert res == ("NIFTY_FUT", "NIFTY")

    res_bn = dfs.resolve_future_symbol("BANKNIFTY1!")
    assert res_bn == ("BANKNIFTY_FUT", "BANKNIFTY")


def test_fetch_dhan_candles_unconfigured():
    dfs = DhanFuturesService()
    with patch.object(DhanFuturesService, "is_configured", new_callable=PropertyMock, return_value=False):
        res = dfs.fetch_dhan_candles("NIFTY", interval="5m", range_str="5d")
        assert res is None
