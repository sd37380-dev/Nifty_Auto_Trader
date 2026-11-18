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
        with urllib.request.urlopen(req_oc, timeout=5.0) as res:
            assert res.status == 200
            oc_data = json.loads(res.read().decode("utf-8"))
            assert oc_data["status"] == "ok"
            assert "chain" in oc_data
            assert "spot_price" in oc_data["chain"]
            assert "strikes" in oc_data["chain"]
    finally:
        server.shutdown()
        server.server_close()
