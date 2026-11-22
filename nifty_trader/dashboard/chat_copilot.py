"""
AI Copilot Web Chat Service for NIFTY Autonomous Trader.
Provides real-time conversational assistance directly inside the Render Web Dashboard.
Seamlessly bridges to local Antigravity when the user is logged in,
uses Google Gemini / OpenAI with live market and historical database context injection,
and transparently displays genuine error messages when AI keys are missing or failing.
"""

from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
from typing import Any, Dict, List, Optional, Tuple
import urllib.error
import urllib.request

# Automatically load environment variables from .env
try:
    from dotenv import load_dotenv
    load_dotenv()
    # Also attempt loading from project root
    _root = Path(__file__).resolve().parent.parent.parent
    if (_root / ".env").exists():
        load_dotenv(_root / ".env")
except Exception:
    pass

logger = logging.getLogger(__name__)


def find_historical_ohlc(user_msg: str, root_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """
    Parses dates or relative time expressions from the user's message and retrieves
    exact historical OHLC session data from SQLite (data/market/nse_spot_data.db)
    or Supabase Cloud PostgreSQL.
    """
    if not user_msg:
        return None

    msg = user_msg.lower()
    target_date_str: Optional[str] = None
    display_title: Optional[str] = None

    month_map = {
        "jan": "01", "january": "01",
        "feb": "02", "february": "02",
        "mar": "03", "march": "03",
        "apr": "04", "april": "04",
        "may": "05",
        "jun": "06", "june": "06",
        "jul": "07", "july": "07",
        "aug": "08", "august": "08",
        "sep": "09", "september": "09",
        "oct": "10", "october": "10",
        "nov": "11", "november": "11",
        "dec": "12", "december": "12",
    }

    # 1. Pattern: "19th nov 2026", "19 nov 2026", "19th november 2026"
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3,9})\s+(\d{4})\b", msg)
    if m:
        day, mon_name, year = m.groups()
        mon = month_map.get(mon_name[:3])
        if mon:
            target_date_str = f"{year}-{mon}-{int(day):02d}"
            display_title = f"{int(day)} {mon_name.title()} {year}"

    # 2. Pattern: "november 19 2026", "nov 19th, 2026"
    if not target_date_str:
        m = re.search(r"\b([a-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", msg)
        if m:
            mon_name, day, year = m.groups()
            mon = month_map.get(mon_name[:3])
            if mon:
                target_date_str = f"{year}-{mon}-{int(day):02d}"
                display_title = f"{int(day)} {mon_name.title()} {year}"

    # 3. Pattern: "2026-11-19" or "2026/11/19"
    if not target_date_str:
        m = re.search(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b", msg)
        if m:
            year, mon, day = m.groups()
            target_date_str = f"{year}-{int(mon):02d}-{int(day):02d}"
            display_title = target_date_str

    # 4. Pattern: "19-11-2026" or "19/11/2026"
    if not target_date_str:
        m = re.search(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b", msg)
        if m:
            day, mon, year = m.groups()
            target_date_str = f"{year}-{int(mon):02d}-{int(day):02d}"
            display_title = target_date_str

    # 5. Pattern without year: "19th nov", "nov 19" (assume 2026)
    if not target_date_str:
        m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3,9})\b", msg)
        if m and m.group(2)[:3] in month_map:
            day, mon_name = m.groups()
            mon = month_map.get(mon_name[:3])
            target_date_str = f"2026-{mon}-{int(day):02d}"
            display_title = f"{int(day)} {mon_name.title()} 2026"

    # 6. Relative: "yesterday"
    if not target_date_str and "yesterday" in msg:
        yest = datetime.now(timezone.utc) - timedelta(days=1)
        target_date_str = yest.strftime("%Y-%m-%d")
        display_title = f"Yesterday ({target_date_str})"

    if not target_date_str:
        return None

    if root_dir is None:
        root_dir = Path(__file__).resolve().parent.parent.parent
    db_path = root_dir / "data" / "market" / "nse_spot_data.db"

    by_symbol: Dict[str, Dict[str, Any]] = {}
    rows = []

    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                """
                SELECT date, time, symbol, spot_price, open_price, high_price, low_price,
                       close_price, previous_close, change_pts, change_pct
                FROM nse_spot_records
                WHERE date LIKE ?
                ORDER BY id DESC
                """,
                (f"%{target_date_str}%",),
            )
            rows = cur.fetchall()
            conn.close()
        except Exception as ex:
            logger.warning("Local SQLite historical query error: %s", ex)

    if rows:
        for r in rows:
            sym = r["symbol"]
            if sym not in by_symbol:
                by_symbol[sym] = {
                    "date": r["date"],
                    "time": r["time"],
                    "symbol": sym,
                    "spot_price": r["spot_price"],
                    "open_price": r["open_price"],
                    "high_price": r["high_price"],
                    "low_price": r["low_price"],
                    "close_price": r["close_price"],
                    "previous_close": r["previous_close"],
                    "change_pts": r["change_pts"],
                    "change_pct": r["change_pct"],
                }
    else:
        # Fall back to Supabase Cloud Database (PostgreSQL)
        try:
            from nifty_trader.core.supabase_adapter import get_supabase_adapter
            supa = get_supabase_adapter(root_dir)
            cloud_records = supa.fetch_spot_records_from_cloud(target_date_str)
            if cloud_records:
                for cr in cloud_records:
                    sym = cr.get("symbol")
                    if sym and sym not in by_symbol:
                        by_symbol[sym] = {
                            "date": target_date_str,
                            "time": cr.get("timestamp_ist", "").split(" ")[1] if " " in cr.get("timestamp_ist", "") else "",
                            "symbol": sym,
                            "spot_price": cr.get("spot_price"),
                            "open_price": cr.get("day_open"),
                            "high_price": cr.get("day_high"),
                            "low_price": cr.get("day_low"),
                            "close_price": cr.get("day_close") or cr.get("spot_price"),
                            "previous_close": cr.get("previous_close"),
                            "change_pts": cr.get("change_pts"),
                            "change_pct": cr.get("change_pct"),
                        }
        except Exception as ex:
            logger.debug("Supabase cloud historical spot error: %s", ex)

    if not by_symbol:
        return None

    # Build clean markdown
    md_lines = [
        f"### 📅 Historical Market Session ({display_title or target_date_str})",
    ]

    for sym in ["NIFTY 50", "BANKNIFTY", "GIFT NIFTY"]:
        if sym in by_symbol:
            data = by_symbol[sym]
            chg = data["change_pts"] or 0.0
            chg_pct = data["change_pct"] or 0.0
            sign = "+" if chg >= 0 else ""
            md_lines.append(f"\n**{sym}:**")
            md_lines.append(f"• **Open Spot Price**: **₹{data['open_price']:,.2f}**")
            md_lines.append(f"• **Session High**: ₹{data['high_price']:,.2f}")
            md_lines.append(f"• **Session Low**: ₹{data['low_price']:,.2f}")
            md_lines.append(f"• **Closing / Last Spot**: ₹{data['close_price']:,.2f}")
            if data["previous_close"]:
                md_lines.append(f"• **Previous Close**: ₹{data['previous_close']:,.2f}")
            md_lines.append(f"• **Net Move**: **{sign}{chg:,.2f} pts ({sign}{chg_pct:.2f}%)**")

    return {
        "target_date": target_date_str,
        "display_title": display_title,
        "symbols": by_symbol,
        "formatted_markdown": "\n".join(md_lines),
    }


def get_market_statistics_context(root_dir: Optional[Path] = None, user_msg: str = "") -> str:
    """
    Computes statistical extremes (monthly highs, lows, all-time ranges) from the database
    so the AI model can answer queries like 'what is nifty lowest price this month'.
    """
    if root_dir is None:
        root_dir = Path(__file__).resolve().parent.parent.parent
    db_path = root_dir / "data" / "market" / "nse_spot_data.db"

    lines = ["### COMPREHENSIVE MARKET RANGE & EXTREMES STATS:"]

    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            # 1. Current Month (November 2026) Extremes
            cur.execute(
                """
                SELECT symbol, MIN(low_price) as min_low, MAX(high_price) as max_high,
                       MIN(open_price) as min_open, MAX(close_price) as max_close
                FROM nse_spot_records
                WHERE date LIKE '2026-11%'
                GROUP BY symbol
                """
            )
            rows = cur.fetchall()
            if rows:
                lines.append("\n**Current Month (November 2026) Ranges:**")
                for r in rows:
                    sym = r["symbol"]
                    min_low = r["min_low"]
                    max_high = r["max_high"]

                    # Find date of min_low
                    cur.execute(
                        "SELECT date FROM nse_spot_records WHERE symbol = ? AND date LIKE '2026-11%' AND low_price = ? LIMIT 1",
                        (sym, min_low),
                    )
                    low_match = cur.fetchone()
                    low_date = low_match["date"] if low_match else "Nov 2026"

                    # Find date of max_high
                    cur.execute(
                        "SELECT date FROM nse_spot_records WHERE symbol = ? AND date LIKE '2026-11%' AND high_price = ? LIMIT 1",
                        (sym, max_high),
                    )
                    high_match = cur.fetchone()
                    high_date = high_match["date"] if high_match else "Nov 2026"

                    lines.append(
                        f"- **{sym}**: Lowest = ₹{min_low:,.2f} (on {low_date}) | Highest = ₹{max_high:,.2f} (on {high_date}) | Month Open = ₹{r['min_open']:,.2f}"
                    )

            # 2. Database All-Time / 52-Week Range in SQLite
            cur.execute(
                """
                SELECT symbol, MIN(low_price) as min_low, MAX(high_price) as max_high
                FROM nse_spot_records
                GROUP BY symbol
                """
            )
            all_time_rows = cur.fetchall()
            if all_time_rows:
                lines.append("\n**All-Time / Database Recorded Extremes:**")
                for r in all_time_rows:
                    lines.append(f"- **{r['symbol']}**: Lowest Ever Recorded = ₹{r['min_low']:,.2f} | Highest Ever = ₹{r['max_high']:,.2f}")

            conn.close()
        except Exception as ex:
            logger.debug("Market stats extraction error: %s", ex)

    return "\n".join(lines)


def build_live_market_context(root_dir: Optional[Path] = None, user_msg: str = "") -> Dict[str, Any]:
    """Compiles a structured real-time market snapshot from SQLite and runtime services."""
    ctx: Dict[str, Any] = {
        "timestamp_ist": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "spots": {},
        "simulator": {},
        "news": [],
        "levels": {},
    }

    try:
        from nifty_trader.dashboard.server import DashboardDataAggregator
        agg = DashboardDataAggregator(root_dir)

        # 1. Spot Data
        try:
            spot_info = agg.get_spot_summary()
            if spot_info and "latest" in spot_info and spot_info["latest"]:
                ctx["spots"] = spot_info["latest"]
        except Exception as e:
            logger.debug("Chat context spot error: %s", e)

        # 2. Paper Simulator Positions & P&L
        try:
            sim_info = agg.get_simulator_summary()
            if sim_info:
                ctx["simulator"] = {
                    "status": sim_info.get("status", "STANDBY"),
                    "total_trades": sim_info.get("total_trades", 0),
                    "net_pnl": sim_info.get("net_pnl", 0.0),
                    "win_rate": sim_info.get("win_rate", "0%"),
                    "active_positions_count": sim_info.get("active_positions_count", 0),
                    "active_positions": sim_info.get("active_positions", []),
                }
        except Exception as e:
            logger.debug("Chat context simulator error: %s", e)

        # 3. Market News
        try:
            news_info = agg.get_news_summary()
            if news_info and "recent_news" in news_info:
                items = news_info["recent_news"][:5]
                ctx["news"] = [
                    {
                        "title": n.get("title"),
                        "category": n.get("category"),
                        "impact_type": n.get("impact_type"),
                        "impact_score": n.get("impact_score"),
                    }
                    for n in items
                ]
                ctx["news_sentiment"] = news_info.get("overall_sentiment", "NEUTRAL")
        except Exception as e:
            logger.debug("Chat context news error: %s", e)

        # 4. Level Triggers
        try:
            levels_info = agg.get_levels_summary()
            if levels_info:
                ctx["levels"] = {
                    "armed_count": levels_info.get("armed_count", 0),
                    "triggered_count": levels_info.get("triggered_count", 0),
                    "triggers": levels_info.get("triggers", [])[:5],
                }
        except Exception as e:
            logger.debug("Chat context levels error: %s", e)

    except Exception as ex:
        logger.warning("Could not compile complete market context: %s", ex)

    # 5. Historical OHLC lookup if date or relative date present
    if user_msg:
        hist = find_historical_ohlc(user_msg, root_dir)
        if hist:
            ctx["historical"] = hist

    # 6. Monthly & Range Statistics
    ctx["market_stats_text"] = get_market_statistics_context(root_dir, user_msg)

    return ctx


def format_context_for_prompt(ctx: Dict[str, Any]) -> str:
    """Formats market context dictionary into a concise markdown text block for LLMs."""
    lines = [
        f"### LIVE MARKET CONTEXT (Server Time: {ctx.get('timestamp_ist', 'Now')})",
    ]

    # Historical Session Data (if queried)
    if "historical" in ctx:
        hist = ctx["historical"]
        lines.append("\n" + hist["formatted_markdown"])
        lines.append("\n> [CRITICAL INSTRUCTION] Use these EXACT historical numbers above to answer the user's specific date query directly.")

    # Monthly & Range Statistics
    stats_text = ctx.get("market_stats_text")
    if stats_text:
        lines.append("\n" + stats_text)
        lines.append("> [CRITICAL INSTRUCTION] If the user asks for monthly low/high, lowest/highest price, or range extremes, answer directly with the exact numbers above.")

    # Spot Prices
    spots = ctx.get("spots", {})
    if spots:
        lines.append("\n**Current Live Spot Prices:**")
        if isinstance(spots, dict) and "symbol" in spots:
            sym = spots.get("symbol", "NIFTY")
            price = spots.get("spot_price") or spots.get("price") or "--"
            chg = spots.get("change") or spots.get("change_pct") or ""
            lines.append(f"- **{sym}**: ₹{price} {f'({chg})' if chg else ''}")
        elif isinstance(spots, dict):
            for sym, d in spots.items():
                if isinstance(d, dict):
                    price = d.get("spot_price") or d.get("price") or "--"
                    chg = d.get("change") or d.get("change_pct") or ""
                    lines.append(f"- **{sym}**: ₹{price} {f'({chg})' if chg else ''}")
    else:
        lines.append("- NIFTY 50 Spot: Active tracking on 5m candles (NSE Session 09:15–15:30 IST)")

    # Paper Positions & P&L
    sim = ctx.get("simulator", {})
    if sim:
        net_pnl = sim.get("net_pnl", 0.0)
        pnl_sign = "+" if net_pnl >= 0 else ""
        lines.append(f"\n**Paper Trading Status:** {sim.get('status', 'ACTIVE')}")
        lines.append(f"- Net Realized P&L: ₹{pnl_sign}{net_pnl:,.2f} | Win Rate: {sim.get('win_rate', '0%')}")
        active = sim.get("active_positions", [])
        if active:
            lines.append(f"- Active Open Positions ({len(active)}):")
            for pos in active:
                lines.append(f"  • {pos.get('symbol')} {pos.get('strike')} {pos.get('option_type')} | Qty: {pos.get('qty')} | Entry: ₹{pos.get('entry_price')} | Unrealized P&L: ₹{pos.get('unrealized_pnl', 0.0):,.2f}")
        else:
            lines.append("- Open Positions: None currently active")

    # News
    news = ctx.get("news", [])
    if news:
        lines.append(f"\n**Recent Market News (Sentiment: {ctx.get('news_sentiment', 'NEUTRAL')}):**")
        for n in news[:3]:
            lines.append(f"- [{n.get('impact_type', 'INFO')}] {n.get('title')}")

    # Armed levels
    levels = ctx.get("levels", {})
    if levels and levels.get("triggers"):
        lines.append(f"\n**Armed Breakout / Level Triggers ({levels.get('armed_count', 0)} active):**")
        for t in levels["triggers"][:3]:
            lines.append(f"- {t.get('symbol')} @ ₹{t.get('target_spot')} ({t.get('direction')} {t.get('option_type')})")

    return "\n".join(lines)


def call_gemini_api(
    api_key: str,
    system_prompt: str,
    user_prompt: str,
    history: Optional[List[Dict[str, str]]] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Invokes Google Gemini REST API (gemini-2.5-flash or gemini-1.5-flash).
    Returns (result_text, None) on success or (None, error_message) on failure.
    """
    models = ["gemini-2.5-flash", "gemini-1.5-flash"]
    last_error = None

    contents = []
    if history:
        for turn in history[-6:]:
            role = "user" if turn.get("role") == "user" else "model"
            content = turn.get("content", "").strip()
            if content:
                contents.append({"role": role, "parts": [{"text": content}]})

    contents.append({"role": "user", "parts": [{"text": user_prompt}]})

    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": contents,
            "generationConfig": {
                "temperature": 0.25,
                "maxOutputTokens": 800,
            },
        }

        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=req_data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=14.0) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                candidates = res.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts and "text" in parts[0]:
                        return (parts[0]["text"], None)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            last_error = f"HTTP {e.code}: {err_body[:200]}"
            logger.warning("Gemini %s API error: %s", model, last_error)
            if e.code in (404, 400):
                continue
            break
        except Exception as ex:
            last_error = str(ex)
            logger.warning("Gemini %s request failed: %s", model, ex)
            break

    return (None, last_error or "No response from Gemini models")


def call_openai_api(
    api_key: str,
    system_prompt: str,
    user_prompt: str,
    history: Optional[List[Dict[str, str]]] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Invokes OpenAI Chat Completions API as secondary fallback."""
    url = "https://api.openai.com/v1/chat/completions"
    messages = [{"role": "system", "content": system_prompt}]
    if history:
        for turn in history[-6:]:
            role = "user" if turn.get("role") == "user" else "assistant"
            content = turn.get("content", "").strip()
            if content:
                messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_prompt})

    payload = {
        "model": "gpt-4o-mini",
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 800,
    }

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=req_data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=12.0) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            choices = res.get("choices", [])
            if choices:
                return (choices[0].get("message", {}).get("content"), None)
    except Exception as ex:
        logger.warning("OpenAI API request failed: %s", ex)
        return (None, str(ex))
    return (None, "No choices returned by OpenAI")


def handle_ai_chat_request(data: Dict[str, Any], root_dir: Optional[Path] = None) -> Dict[str, Any]:
    """
    Main orchestration handler for the web chat endpoint `/api/chat`.
    1. If Antigravity local bridge is online, routes directly to Antigravity.
    2. Otherwise, uses Gemini API / OpenAI API with live context & historical SQLite lookup.
    3. If API keys are missing or fail, honestly displays the error to the user rather than fake text.
    """
    user_msg = (data.get("message") or "").strip()
    history = data.get("history") or []

    if not user_msg:
        return {"status": "error", "message": "Empty message provided"}

    # Compile real-time context + historical lookup + monthly stats
    ctx = build_live_market_context(root_dir, user_msg=user_msg)
    context_text = format_context_for_prompt(ctx)

    # -------------------------------------------------------------
    # PRIORITY 0: Antigravity Local Agent Bridge
    # -------------------------------------------------------------
    try:
        from nifty_trader.dashboard.antigravity_bridge import get_bridge_manager
        bridge = get_bridge_manager()
        if bridge.is_online():
            bridge_resp = bridge.enqueue_message(
                message=user_msg,
                history=history,
                context=ctx,
                timeout=6.0,
            )
            if bridge_resp and bridge_resp.get("reply"):
                return {
                    "status": "ok",
                    "reply": bridge_resp["reply"],
                    "model": "antigravity_bridge",
                    "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
                }
    except Exception as ex:
        logger.debug("Bridge routing bypass: %s", ex)

    # -------------------------------------------------------------
    # PRIORITY 1: Cloud Gemini / OpenAI API
    # -------------------------------------------------------------
    system_prompt = (
        "You are the NIFTY Autonomous Trader Copilot, an expert Indian markets quantitative options trader "
        "and algorithmic analyst. You assist the trader directly via the Render Web Dashboard.\n\n"
        "Guidelines:\n"
        "1. Always answer the specific question asked by the user.\n"
        "2. If the user asks for historical prices, open prices, or specific past dates, cite the exact numbers from the HISTORICAL DATA block.\n"
        "3. If the user asks for the lowest price, highest price, or monthly range, cite the exact numbers from the COMPREHENSIVE MARKET RANGE & EXTREMES block.\n"
        "4. Explain technical setups clearly using Volume Profile (POC, VAH, VAL), Supertrend, and EMA structure.\n"
        "5. Emphasize strict risk management (1:3 Risk-to-Reward, hard stops, max daily drawdown ₹2,000).\n"
        "6. Format your responses with clean Markdown, bullet points, and bold price highlights.\n"
        "7. Keep responses direct, concise, and actionable.\n\n"
        f"{context_text}"
    )

    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if gemini_key:
        reply, err = call_gemini_api(gemini_key, system_prompt, user_msg, history)
        if reply:
            return {
                "status": "ok",
                "reply": reply,
                "model": "gemini-2.5-flash",
                "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
            }
        else:
            return {
                "status": "error",
                "message": f"Gemini API request failed: {err}",
                "reply": f"⚠️ **Gemini AI Request Error**: {err}\n\nPlease check your `GEMINI_API_KEY` quota and configuration.",
                "model": "error",
                "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
            }

    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if openai_key:
        reply, err = call_openai_api(openai_key, system_prompt, user_msg, history)
        if reply:
            return {
                "status": "ok",
                "reply": reply,
                "model": "gpt-4o-mini",
                "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
            }
        else:
            return {
                "status": "error",
                "message": f"OpenAI API request failed: {err}",
                "reply": f"⚠️ **OpenAI Request Error**: {err}\n\nPlease check your `OPENAI_API_KEY` configuration.",
                "model": "error",
                "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
            }

    # -------------------------------------------------------------
    # NO API KEY CONFIGURED
    # -------------------------------------------------------------
    return {
        "status": "error",
        "message": "GEMINI_API_KEY is not configured",
        "reply": (
            "⚠️ **AI Assistant Not Configured**:\n\n"
            "I could not connect to Google Gemini because **`GEMINI_API_KEY`** is not set in your environment or `.env` file.\n\n"
            "To enable live conversational intelligence:\n"
            "1. Get a free API key at [Google AI Studio](https://aistudio.google.com/)\n"
            "2. Add `GEMINI_API_KEY=your_key_here` to your `.env` file or Render Environment Variables."
        ),
        "model": "unconfigured",
        "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
    }
