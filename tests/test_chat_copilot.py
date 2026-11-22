import threading
import time
import pytest
from nifty_trader.dashboard.chat_copilot import (
    build_live_market_context,
    format_context_for_prompt,
    handle_ai_chat_request,
    find_historical_ohlc,
    get_market_statistics_context,
)
from nifty_trader.dashboard.antigravity_bridge import get_bridge_manager

def test_build_live_market_context():
    ctx = build_live_market_context()
    assert isinstance(ctx, dict)
    assert "timestamp_ist" in ctx
    assert "spots" in ctx
    assert "simulator" in ctx
    assert "news" in ctx
    assert "market_stats_text" in ctx

def test_format_context_for_prompt():
    ctx = {
        "timestamp_ist": "2026-11-22 15:00:00 UTC",
        "spots": {"NIFTY": {"spot_price": 25250.0, "change": "+0.5%"}},
        "simulator": {"status": "ACTIVE", "net_pnl": 1500.0, "active_positions": []},
        "news": [{"title": "RBI keeps repo rate unchanged", "impact_type": "HIGH"}],
        "news_sentiment": "BULLISH",
        "market_stats_text": "NIFTY Lowest = 23,207.05",
    }
    formatted = format_context_for_prompt(ctx)
    assert "NIFTY" in formatted
    assert "25250" in formatted
    assert "1,500.00" in formatted
    assert "23,207.05" in formatted

def test_get_market_statistics_context():
    stats = get_market_statistics_context()
    assert "COMPREHENSIVE MARKET RANGE" in stats
    assert "23,207.05" in stats
    assert "NIFTY 50" in stats

def test_find_historical_ohlc():
    # Test lookup for 19th nov 2026
    res = find_historical_ohlc("what is open spot price in 19th nov 2026")
    assert res is not None
    assert "2026-11-19" in res["target_date"]
    assert "NIFTY 50" in res["symbols"]
    assert res["symbols"]["NIFTY 50"]["open_price"] == 25186.8
    assert "25,186.80" in res["formatted_markdown"]

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
    # Test empty message handling
    err_res = handle_ai_chat_request({"message": "   "})
    assert err_res["status"] == "error"

    # Test real AI query with Gemini API
    res = handle_ai_chat_request({"message": "what is nifty lowest price this month"})
    assert "reply" in res
    assert "23,207" in res["reply"] or "23207" in res["reply"]
