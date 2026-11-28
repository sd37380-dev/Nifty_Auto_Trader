import os
from unittest.mock import MagicMock, patch
from pathlib import Path
import pytest

from nifty_trader.market_data.option_chain_service import NSEOptionChainService


@pytest.fixture
def ocs():
    return NSEOptionChainService(root_dir=Path("."))


def test_dhan_expiry_normalization(ocs):
    # Tests YYYY-MM-DD and DD-MMM-YYYY conversions
    assert ocs._normalize_expiry_to_iso("03-Dec-2026") == "2026-12-03"
    assert ocs._normalize_expiry_to_iso("2026-12-03") == "2026-12-03"
    assert ocs._normalize_expiry_to_iso(None) is None


def test_dhan_exclusive_without_credentials(ocs):
    # When credentials are missing or empty, should return Dhan Exclusive structure without fallback
    with patch.object(ocs, "_get_credentials", return_value=("", "")):
        res = ocs.get_option_chain("NIFTY", force_refresh=True)
        assert res["data_source"] == "Dhan HQ API (Exclusive • Strictly Dhan)"
        assert "Dhan credentials not configured" in res["error"]
        assert res["strikes"] == []
        assert res["expiry_dates"] == []


def test_dhan_4_week_expiries_and_chain(ocs):
    # Mock Dhan Expiry List API and Option Chain API
    mock_expiries = ["2026-12-03", "2026-12-10", "2026-12-17", "2026-12-24", "2026-12-31"]
    mock_oc_data = {
        "data": {
            "last_price": 24200.0,
            "oc": {
                "24100": {
                    "ce": {"ltp": 150.0, "oi": 50000, "change_oi": 2000, "change_price": 10.0},
                    "pe": {"ltp": 50.0, "oi": 120000, "change_oi": 5000, "change_price": -5.0},
                },
                "24200": {
                    "ce": {"ltp": 80.0, "oi": 80000, "change_oi": 4000, "change_price": 5.0},
                    "pe": {"ltp": 80.0, "oi": 90000, "change_oi": 3000, "change_price": -3.0},
                },
                "24300": {
                    "ce": {"ltp": 30.0, "oi": 110000, "change_oi": 8000, "change_price": -2.0},
                    "pe": {"ltp": 130.0, "oi": 40000, "change_oi": 1000, "change_price": 4.0},
                },
            }
        }
    }

    with patch.dict(os.environ, {"DHAN_CLIENT_ID": "1234567890", "DHAN_ACCESS_TOKEN": "valid_mock_jwt_token_over_15_chars"}):
        with patch.object(ocs, "fetch_dhan_expiry_list", return_value=mock_expiries):
            with patch.object(ocs, "fetch_live_chain_from_dhan", return_value=mock_oc_data):
                # 1. Fetch nearest week
                chain = ocs.get_option_chain("NIFTY", force_refresh=True)
                assert chain["data_source"] == "Dhan HQ API (Live Authenticated • 4-Week Expiry)"
                assert len(chain["expiry_dates"]) == 4
                assert chain["expiry_dates"] == ["2026-12-03", "2026-12-10", "2026-12-17", "2026-12-24"]
                assert chain["expiry"] == "2026-12-03"
                assert len(chain["strikes"]) == 3
                assert chain["atm_strike"] == 24200

                # 2. Fetch specific week (Week 2: 2026-12-10)
                chain_w2 = ocs.get_option_chain("NIFTY", expiry="2026-12-10", force_refresh=True)
                assert chain_w2["expiry"] == "2026-12-10"
                assert chain_w2["expiry_dates"] == ["2026-12-03", "2026-12-10", "2026-12-17", "2026-12-24"]

                # 3. Test get_next_expiries and backward-compatibility alias
                next_exp = ocs.get_next_expiries("NIFTY", count=4, force_refresh=True)
                assert next_exp["status"] == "ok"
                assert next_exp["expiries"] == ["2026-12-03", "2026-12-10", "2026-12-17", "2026-12-24"]
                assert len(next_exp["chains"]) == 4

                # 4. Backward-compatible alias
                alias_exp = ocs.get_next_expiries_from_nse("NIFTY", count=2, force_refresh=True)
                assert alias_exp["status"] == "ok"
                assert len(alias_exp["chains"]) == 2
