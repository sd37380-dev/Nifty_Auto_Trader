"""
Unit tests for the Market News Service and Dashboard News Section / Ticker.
"""

import json
from pathlib import Path
import urllib.request
import pytest

from nifty_trader.market_data.news_service import MarketNewsService, get_news_service
from nifty_trader.dashboard.server import DashboardDataAggregator, run_dashboard_server


def test_market_news_service_crud_and_analysis():
    news_svc = get_news_service()

    # 1. Verify initial seed
    summary = news_svc.get_news_summary()
    assert summary["stats"]["total"] >= 8
    assert summary["stats"]["bullish"] >= 1
    assert len(summary["top_scrolling"]) >= 5

    # 2. Test sentiment analysis for Good News (Bullish)
    good_analysis = news_svc.analyze_news_impact(
        title="NIFTY Hits Record High as FII Buying Surges",
        summary="Foreign investors bought heavily on strong GDP growth."
    )
    assert good_analysis["impact_type"] == "BULLISH"
    assert good_analysis["is_important"] == 1
    assert "NIFTY" in good_analysis["market_effect"]

    # 3. Test sentiment analysis for Bad News (Bearish)
    bad_analysis = news_svc.analyze_news_impact(
        title="Brent Crude Surges 6% on Conflict Escalation; Inflation Spikes",
        summary="Crude oil jumps raising deficit concerns."
    )
    assert bad_analysis["impact_type"] == "BEARISH"
    assert "Downside" in bad_analysis["market_effect"] or "caution" in bad_analysis["market_effect"]

    # 4. Add custom news item
    news_id = news_svc.add_news_item(
        title="RBI Governor Announces Special Liquidity Window for MSMEs",
        summary="Liquidity window opens to support commercial lending.",
        source="RBI Press Release",
        category="MACRO_POLICY",
        impact_type="BULLISH",
        impact_score=5,
        market_effect="Directly positive for BankNifty and financial credit growth.",
        is_important=1,
    )
    assert news_id != ""

    # Verify news retrieval with filter
    macro_news = news_svc.get_all_news(category="MACRO_POLICY")
    assert any(n["id"] == news_id for n in macro_news)

    # Verify top scrolling news includes this important item
    top_items = news_svc.get_top_scrolling_news(limit=20)
    assert any(n["id"] == news_id for n in top_items)

    # Clean up test item
    deleted = news_svc.delete_news_item(news_id)
    assert deleted is True


def test_dashboard_aggregator_has_news():
    agg = DashboardDataAggregator()
    news_sum = agg.get_news_summary()
    assert "stats" in news_sum
    assert "top_scrolling" in news_sum
    assert "recent_news" in news_sum


def test_dashboard_server_news_endpoints():
    server = run_dashboard_server(host="127.0.0.1", port=8989, open_browser=False, block=False)
    try:
        # 1. Verify HTML includes top news ticker, tab-news, tab-option-chain, and overview news card
        req_html = urllib.request.Request("http://127.0.0.1:8989/")
        with urllib.request.urlopen(req_html, timeout=5.0) as res:
            assert res.status == 200
            html = res.read().decode("utf-8")
            assert "persistent-news-ticker" in html
            assert "BREAKING INDIAN MARKET NEWS" in html
            assert "tab-news" in html
            assert "tab-option-chain" in html
            assert "overview-news-list" in html

        # 2. Verify /api/data includes news payload
        req_api = urllib.request.Request("http://127.0.0.1:8989/api/data")
        with urllib.request.urlopen(req_api, timeout=5.0) as res:
            assert res.status == 200
            data = json.loads(res.read().decode("utf-8"))
            assert "news" in data
            assert data["news"]["stats"]["total"] >= 8

        # 3. Test GET /api/option_chain
        req_oc = urllib.request.Request("http://127.0.0.1:8989/api/option_chain?symbol=NIFTY")
        with urllib.request.urlopen(req_oc, timeout=5.0) as res:
            assert res.status == 200
            oc_data = json.loads(res.read().decode("utf-8"))
            assert oc_data["status"] == "ok"
            assert "chain" in oc_data
            assert oc_data["chain"]["symbol"] == "NIFTY"
            assert len(oc_data["chain"]["strikes"]) > 0

        # 4. Test POST /api/option_chain/trade
        oc_trade_payload = json.dumps({
            "symbol": "NIFTY",
            "strike": 25400,
            "option_type": "CE",
            "lots": 1,
            "premium": 135.0,
            "sl_points": 20.0,
            "target_points": 40.0,
        }).encode("utf-8")
        req_oc_trade = urllib.request.Request(
            "http://127.0.0.1:8989/api/option_chain/trade",
            data=oc_trade_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_oc_trade, timeout=5.0) as res:
            assert res.status == 200
            trade_res = json.loads(res.read().decode("utf-8"))
            assert trade_res["status"] == "ok"
            assert trade_res["strike"] == 25400
            assert trade_res["option_type"] == "CE"

        # 5. Test POST /api/news/add
        payload = json.dumps({
            "title": "Fed Chairman Powell Hints at Rate Pause Ahead",
            "summary": "Inflation shows clear signs of sustained cooling toward target.",
            "category": "MACRO_POLICY",
            "impact_type": "BULLISH",
            "impact_score": 5,
            "market_effect": "Lifts global risk sentiment; positive gap-up cues for NIFTY.",
            "is_important": 1,
            "source": "Bloomberg Wire",
        }).encode("utf-8")
        req_post = urllib.request.Request(
            "http://127.0.0.1:8989/api/news/add",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_post, timeout=5.0) as res:
            assert res.status == 200
            res_data = json.loads(res.read().decode("utf-8"))
            assert res_data["status"] == "ok"
            test_id = res_data["id"]

        # 6. Test GET /api/news
        req_news = urllib.request.Request("http://127.0.0.1:8989/api/news")
        with urllib.request.urlopen(req_news, timeout=5.0) as res:
            assert res.status == 200
            news_json = json.loads(res.read().decode("utf-8"))
            assert any(n["id"] == test_id for n in news_json["news"])

        # 7. Test GET /api/news/delete
        req_del = urllib.request.Request(f"http://127.0.0.1:8989/api/news/delete?id={test_id}")
        with urllib.request.urlopen(req_del, timeout=5.0) as res:
            assert res.status == 200
            del_json = json.loads(res.read().decode("utf-8"))
            assert del_json["deleted"] is True
    finally:
        server.shutdown()
        server.server_close()
