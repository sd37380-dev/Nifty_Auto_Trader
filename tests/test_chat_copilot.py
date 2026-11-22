import pytest
from nifty_trader.dashboard.chat_copilot import (
    build_live_market_context,
    format_context_for_prompt,
    autonomous_copilot_rule_engine,
    handle_ai_chat_request,
)

def test_build_live_market_context():
    ctx = build_live_market_context()
    assert isinstance(ctx, dict)
    assert "timestamp_ist" in ctx
    assert "spots" in ctx
    assert "simulator" in ctx
    assert "news" in ctx

def test_format_context_for_prompt():
    ctx = {
        "timestamp_ist": "2026-11-22 15:00:00 UTC",
        "spots": {"NIFTY": {"spot_price": 25250.0, "change": "+0.5%"}},
        "simulator": {"status": "ACTIVE", "net_pnl": 1500.0, "active_positions": []},
        "news": [{"title": "RBI keeps repo rate unchanged", "impact_type": "HIGH"}],
        "news_sentiment": "BULLISH",
    }
    formatted = format_context_for_prompt(ctx)
    assert "NIFTY" in formatted
    assert "25250" in formatted
    assert "1,500.00" in formatted
    assert "RBI" in formatted

def test_autonomous_copilot_rule_engine():
    ctx = {
        "spots": {"NIFTY": {"spot_price": 25300.0}},
        "simulator": {"status": "ACTIVE", "net_pnl": 500.0, "active_positions": []},
        "news": [],
        "levels": {},
    }
    poc_resp = autonomous_copilot_rule_engine("Where is today's POC and value area?", ctx)
    assert "Volume Profile" in poc_resp
    assert "POC" in poc_resp

    pnl_resp = autonomous_copilot_rule_engine("What is my current profit and positions?", ctx)
    assert "Paper Trading" in pnl_resp
    assert "500.00" in pnl_resp

    news_resp = autonomous_copilot_rule_engine("Give me latest news", ctx)
    assert "News" in news_resp

def test_handle_ai_chat_request():
    res = handle_ai_chat_request({"message": "What is the NIFTY trend and POC?"})
    assert res["status"] == "ok"
    assert "reply" in res
    assert len(res["reply"]) > 20
    assert "model" in res

    # Empty message handling
    err_res = handle_ai_chat_request({"message": "   "})
    assert err_res["status"] == "error"
