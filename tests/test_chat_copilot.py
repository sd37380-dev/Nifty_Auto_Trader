import threading
import time
import pytest
from nifty_trader.dashboard.chat_copilot import (
    build_live_market_context,
    format_context_for_prompt,
    autonomous_copilot_rule_engine,
    handle_ai_chat_request,
    find_historical_ohlc,
)
from nifty_trader.dashboard.antigravity_bridge import get_bridge_manager

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

def test_find_historical_ohlc():
    # Test lookup for 19th nov 2026
    res = find_historical_ohlc("what is open spot price in 19th nov 2026")
    assert res is not None
    assert "2026-11-19" in res["target_date"]
    assert "NIFTY 50" in res["symbols"]
    assert res["symbols"]["NIFTY 50"]["open_price"] == 25186.8
    assert "25,186.80" in res["formatted_markdown"]

    # Test direct handling through handle_ai_chat_request
    chat_res = handle_ai_chat_request({"message": "what is open spot price in 19th nov 2026"})
    assert chat_res["status"] == "ok"
    assert "25,186.80" in chat_res["reply"]
    assert "NIFTY 50" in chat_res["reply"]

def test_antigravity_bridge_flow():
    bridge = get_bridge_manager()
    bridge.register_heartbeat()
    assert bridge.is_online() is True

    # Simulate worker answering in background thread
    def bridge_worker():
        job = bridge.poll_job(timeout=3.0)
        if job:
            bridge.submit_reply(
                job_id=job["job_id"],
                reply="Simulated response from Antigravity Bridge for: " + job["message"],
                model="antigravity_bridge",
            )

    worker_thread = threading.Thread(target=bridge_worker)
    worker_thread.start()

    res = bridge.enqueue_message(
        message="Hello from test",
        timeout=4.0,
    )
    worker_thread.join()

    assert res is not None
    assert "Simulated response from Antigravity" in res["reply"]
    assert res["model"] == "antigravity_bridge"

def test_handle_ai_chat_request():
    # Test normal request
    res = handle_ai_chat_request({"message": "What is the NIFTY trend and POC?"})
    assert res["status"] == "ok"
    assert "reply" in res
    assert len(res["reply"]) > 20
    assert "model" in res

    # Empty message handling
    err_res = handle_ai_chat_request({"message": "   "})
    assert err_res["status"] == "error"
