"""
Antigravity Live Local Agent Bridge Worker.
Runs on the user's local computer while Antigravity is active.
Bridges between the web dashboard chat box (on Render or Localhost) and Antigravity,
allowing Antigravity to answer questions on behalf of the web copilot in real time.

Usage:
  python scripts/antigravity_bridge.py
  python scripts/antigravity_bridge.py --url https://<your-render-app>.onrender.com
"""

import argparse
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, Optional
import urllib.error
import urllib.parse
import urllib.request

# Add root directory to sys.path so we can import nifty_trader modules
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Load .env file automatically
try:
    from dotenv import load_dotenv
    load_dotenv()
    if (ROOT_DIR / ".env").exists():
        load_dotenv(ROOT_DIR / ".env")
except Exception:
    pass

from nifty_trader.dashboard.chat_copilot import (
    call_gemini_api,
    call_openai_api,
    find_historical_ohlc,
    format_context_for_prompt,
    get_market_statistics_context,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("AntigravityBridge")


def generate_antigravity_response(
    user_msg: str,
    history: list,
    ctx: Dict[str, Any],
) -> str:
    """
    Generates an expert response from Antigravity with full local codebase and database access.
    """
    # 1. Check historical database if date or past prices are mentioned
    hist = find_historical_ohlc(user_msg, ROOT_DIR)
    if hist:
        ctx["historical"] = hist

    # 2. Add statistical extremes (monthly low/high, all-time ranges)
    ctx["market_stats_text"] = get_market_statistics_context(ROOT_DIR, user_msg)

    # 3. Check for Gemini API key
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    system_prompt = (
        "You are Antigravity, the elite autonomous AI trading engineer and quantitative researcher for NIFTY Autonomous Trader. "
        "You are communicating with the user directly through the Live Web Chat Bridge from your local execution environment.\n\n"
        "Guidelines:\n"
        "1. Always answer the specific question asked by the user.\n"
        "2. If the user asks for historical prices or past dates, cite the exact numbers from the HISTORICAL DATA block.\n"
        "3. If the user asks for the lowest price, highest price, or monthly range, cite the exact numbers from the COMPREHENSIVE MARKET RANGE & EXTREMES block.\n"
        "4. Explain trading setups using Volume Profile (POC, VAH, VAL), 9/20 EMA slope, Supertrend, and strict 1:3 risk management.\n"
        "5. Format your output cleanly with bullet points and bold highlights.\n\n"
        f"{format_context_for_prompt(ctx)}"
    )

    if gemini_key:
        reply, meta, err = call_gemini_api(gemini_key, system_prompt, user_msg, history)
        if reply:
            engine_str = meta.get("engine", "Google Gemini 2.5 Flash") if meta else "Google Gemini 2.5 Flash"
            prompt_t = meta.get("prompt_tokens", 0) if meta else 0
            cand_t = meta.get("candidate_tokens", 0) if meta else 0
            lat = meta.get("latency_sec", 0.0) if meta else 0.0
            proof_badge = (
                f"\n\n---\n"
                f"*⚡ Verified AI Origin: Antigravity Bridge via **{engine_str}** "
                f"({prompt_t} in / {cand_t} out • {lat}s latency)*"
            )
            return f"{reply}{proof_badge}"
        else:
            return f"⚠️ **Antigravity AI Request Error**: {err}\n\nPlease check your `GEMINI_API_KEY` configuration."

    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if openai_key:
        reply, meta, err = call_openai_api(openai_key, system_prompt, user_msg, history)
        if reply:
            engine_str = meta.get("engine", "OpenAI gpt-4o-mini") if meta else "OpenAI gpt-4o-mini"
            prompt_t = meta.get("prompt_tokens", 0) if meta else 0
            cand_t = meta.get("candidate_tokens", 0) if meta else 0
            lat = meta.get("latency_sec", 0.0) if meta else 0.0
            proof_badge = (
                f"\n\n---\n"
                f"*⚡ Verified AI Origin: Antigravity Bridge via **{engine_str}** "
                f"({prompt_t} in / {cand_t} out • {lat}s latency)*"
            )
            return f"{reply}{proof_badge}"
        else:
            return f"⚠️ **Antigravity OpenAI Error**: {err}\n\nPlease check your `OPENAI_API_KEY` configuration."

    return (
        "⚠️ **Antigravity AI Key Error**:\n\n"
        "No `GEMINI_API_KEY` was found in your `.env` file on this computer.\n"
        "Please add `GEMINI_API_KEY=your_key` to `.env` so Antigravity can answer your questions with live reasoning."
    )


def run_bridge_worker(
    server_url: str,
    token: str,
    once: bool = False,
    poll_interval: float = 1.0,
) -> None:
    """Main polling loop for the Antigravity Bridge."""
    server_url = server_url.rstrip("/")
    logger.info("=" * 60)
    logger.info("🚀 ANTIGRAVITY LIVE WEB CHAT BRIDGE ACTIVE")
    logger.info("   Target Server : %s", server_url)
    logger.info("   Local Root    : %s", ROOT_DIR)
    logger.info("   AI Key Status : %s", "Configured (Gemini)" if os.environ.get("GEMINI_API_KEY") else "Missing GEMINI_API_KEY")
    logger.info("   Token Status  : Authenticated")
    logger.info("=" * 60)
    logger.info("Listening for incoming chat questions from the Web Copilot...")

    consecutive_errors = 0

    while True:
        try:
            # Poll for pending chat job
            poll_url = f"{server_url}/api/bridge/poll?token={urllib.parse.quote(token)}"
            req = urllib.request.Request(
                poll_url,
                headers={"User-Agent": "AntigravityBridgeWorker/1.0"},
                method="GET",
            )

            try:
                with urllib.request.urlopen(req, timeout=18.0) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    consecutive_errors = 0
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    logger.error("Bridge authorization failed: invalid token.")
                    time.sleep(5.0)
                    continue
                raise
            except (urllib.error.URLError, TimeoutError):
                # Normal long-poll timeout, loop again
                time.sleep(poll_interval)
                continue

            job = data.get("job")
            if not job:
                time.sleep(poll_interval)
                continue

            job_id = job.get("job_id")
            user_msg = job.get("message", "")
            history = job.get("history", [])
            ctx = job.get("context", {})

            logger.info("📩 Received message [Job: %s]: %r", job_id, user_msg)

            # Generate Antigravity's response
            start_t = time.time()
            reply = generate_antigravity_response(user_msg, history, ctx)
            elapsed = time.time() - start_t

            logger.info("💡 Generated reply in %.2fs. Sending back to Web Chat...", elapsed)

            # Submit reply back to web server
            reply_url = f"{server_url}/api/bridge/reply"
            payload = {
                "token": token,
                "job_id": job_id,
                "reply": reply,
                "model": "antigravity_bridge",
            }
            reply_req = urllib.request.Request(
                reply_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(reply_req, timeout=10.0) as resp:
                ack = json.loads(resp.read().decode("utf-8"))
                logger.info("✅ Reply delivered to Web Chat! Server ack: %s", ack.get("delivered"))

            if once:
                break

        except KeyboardInterrupt:
            logger.info("Bridge stopped by user.")
            break
        except Exception as ex:
            consecutive_errors += 1
            logger.warning("Bridge loop error (%d/5): %s", consecutive_errors, ex)
            time.sleep(min(2.0 * consecutive_errors, 10.0))


def main() -> None:
    parser = argparse.ArgumentParser(description="Antigravity Live Web Chat Bridge")
    parser.add_argument(
        "--url",
        default=os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("BRIDGE_SERVER_URL") or "http://localhost:8080",
        help="Target server URL (default: http://localhost:8080 or RENDER_EXTERNAL_URL)",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("AGY_BRIDGE_SECRET") or "nifty-antigravity-secure-bridge-2026",
        help="Shared secret token for bridge authentication",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process one message and exit",
    )
    args = parser.parse_args()

    run_bridge_worker(server_url=args.url, token=args.token, once=args.once)


if __name__ == "__main__":
    main()
