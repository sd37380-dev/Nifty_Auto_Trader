"""
Unit tests for the Webview Dashboard server and data aggregator.
"""

import json
from pathlib import Path
import tempfile
import urllib.request
import pytest

from nifty_trader.dashboard.server import (
    DashboardDataAggregator,
    DashboardHTTPRequestHandler,
    run_dashboard_server,
)


def test_dashboard_data_aggregator():
    agg = DashboardDataAggregator()
    overview = agg.get_system_overview()
    assert overview["application"] == "NIFTY Autonomous Trader"
    assert "safety_policies" in overview

    research = agg.get_research_zone_summary()
    assert "assessments" in research
    assert "hypotheses" in research
    assert "failed_hypotheses" in research


def test_dashboard_server_endpoints():
    # Start server in background thread on non-standard port
    server = run_dashboard_server(host="127.0.0.1", port=8899, open_browser=False, block=False)
    try:
        # 1. Test HTML UI endpoint
        url_html = "http://127.0.0.1:8899/"
        req = urllib.request.Request(url_html)
        with urllib.request.urlopen(req, timeout=5.0) as res:
            assert res.status == 200
            content = res.read().decode("utf-8")
            assert "NIFTY Autonomous Trader" in content
            assert "AI Brain Reasoning" in content
            assert "Hermes Research Zone" in content

        # 2. Test JSON API endpoint
        url_api = "http://127.0.0.1:8899/api/data"
        req_api = urllib.request.Request(url_api)
        with urllib.request.urlopen(req_api, timeout=5.0) as res:
            assert res.status == 200
            data = json.loads(res.read().decode("utf-8"))
            assert "overview" in data
            assert "brain" in data
            assert "paper" in data
            assert "research" in data

        # 3. Test Render Health Check endpoint
        url_health = "http://127.0.0.1:8899/health"
        req_health = urllib.request.Request(url_health)
        with urllib.request.urlopen(req_health, timeout=5.0) as res:
            assert res.status == 200
            health_data = json.loads(res.read().decode("utf-8"))
            assert health_data["status"] == "healthy"
            assert health_data["service"] == "nifty-autonomous-trader"

        # 4. Test Supabase Status endpoint
        url_supa = "http://127.0.0.1:8899/api/supabase/status"
        req_supa = urllib.request.Request(url_supa)
        with urllib.request.urlopen(req_supa, timeout=5.0) as res:
            assert res.status == 200
            supa_data = json.loads(res.read().decode("utf-8"))
            assert "configured" in supa_data

        # 5. Test NSE Option Chain API endpoint
        url_oc = "http://127.0.0.1:8899/api/option_chain?symbol=NIFTY"
        req_oc = urllib.request.Request(url_oc)
        with urllib.request.urlopen(req_oc, timeout=12.0) as res:
            assert res.status == 200
            oc_data = json.loads(res.read().decode("utf-8"))
            assert oc_data["status"] == "ok"
            assert "chain" in oc_data
            assert "spot_price" in oc_data["chain"]
            assert "strikes" in oc_data["chain"]

        # 6. Test Telegram Status endpoint
        url_tele = "http://127.0.0.1:8899/api/telegram/status"
        req_tele = urllib.request.Request(url_tele)
        with urllib.request.urlopen(req_tele, timeout=5.0) as res:
            assert res.status == 200
            tele_data = json.loads(res.read().decode("utf-8"))
            assert "configured" in tele_data

        # 7. Test Pending Trades endpoint
        url_pending = "http://127.0.0.1:8899/api/telegram/pending_trades"
        req_pending = urllib.request.Request(url_pending)
        with urllib.request.urlopen(req_pending, timeout=5.0) as res:
            assert res.status == 200
            pending_data = json.loads(res.read().decode("utf-8"))
            assert "pending_trades" in pending_data
            assert "count" in pending_data

        # 8. Test Arm Trade POST endpoint
        url_arm = "http://127.0.0.1:8899/api/telegram/arm_trade"
        arm_body = json.dumps({
            "symbol": "NIFTY",
            "strike": 23500,
            "option_type": "CE",
            "lots": 1,
            "premium": 110.0,
            "spot_price": 23510.0,
            "sl_points": 20.0,
            "target_points": 40.0,
            "reasoning": "Breakout above PDH test",
            "countdown_seconds": 60,
        }).encode("utf-8")
        req_arm = urllib.request.Request(url_arm, data=arm_body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req_arm, timeout=5.0) as res:
            assert res.status == 200
            arm_data = json.loads(res.read().decode("utf-8"))
            assert arm_data["status"] == "ok"
            pid = arm_data["pending_trade"]["pending_id"]

        # 9. Test Cancel Pending POST endpoint
        url_cancel = "http://127.0.0.1:8899/api/telegram/cancel_pending"
        cancel_body = json.dumps({
            "pending_id": pid,
            "reason": "Test cancel",
        }).encode("utf-8")
        req_cancel = urllib.request.Request(url_cancel, data=cancel_body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req_cancel, timeout=5.0) as res:
            assert res.status == 200
            cancel_data = json.loads(res.read().decode("utf-8"))
            assert cancel_data["status"] == "ok"
            assert cancel_data["pending_id"] == pid

        # 10. Test Separate Tick Data Database endpoint
        url_ticks = "http://127.0.0.1:8899/api/ticks?symbol=NIFTY&limit=10"
        req_ticks = urllib.request.Request(url_ticks)
        with urllib.request.urlopen(req_ticks, timeout=5.0) as res:
            assert res.status == 200
            ticks_data = json.loads(res.read().decode("utf-8"))
            assert ticks_data["status"] == "ok"
            assert ticks_data["database"] == "data/market/market_ticks.db"
            assert "ticks" in ticks_data

        # 11. Test Separate Option Chain Database History endpoint
        url_oc_hist = "http://127.0.0.1:8899/api/option_chain/history?symbol=NIFTY&limit=5"
        req_oc_hist = urllib.request.Request(url_oc_hist)
        with urllib.request.urlopen(req_oc_hist, timeout=5.0) as res:
            assert res.status == 200
            oc_hist_data = json.loads(res.read().decode("utf-8"))
            assert oc_hist_data["status"] == "ok"
            assert oc_hist_data["database"] == "data/market/option_chain.db"
            assert "history" in oc_hist_data
    finally:
        server.shutdown()
        server.server_close()
