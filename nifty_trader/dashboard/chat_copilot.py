"""
AI Copilot Web Chat Service for NIFTY Autonomous Trader.
Provides real-time conversational assistance directly inside the Render Web Dashboard.
Seamlessly bridges to local Antigravity when the user is logged in,
uses Google Gemini / OpenAI with live market and historical context injection,
and includes an intelligent autonomous rule engine as a built-in zero-dependency fallback.
"""

from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


def find_historical_ohlc(user_msg: str, root_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """
    Parses dates or relative time expressions from the user's message and retrieves
    exact historical OHLC session data from SQLite (data/market/nse_spot_data.db).
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

    # Locate database
    if root_dir is None:
        root_dir = Path(__file__).resolve().parent.parent.parent
    db_path = root_dir / "data" / "market" / "nse_spot_data.db"

    if not db_path.exists():
        return None

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

        if not rows:
            return None

        by_symbol: Dict[str, Dict[str, Any]] = {}
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

    except Exception as ex:
        logger.warning("Historical OHLC query error: %s", ex)
        return None


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
        lines.append("\n> [CRITICAL INSTRUCTION] Use these EXACT historical numbers above to answer the user's date query directly.")

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


def call_gemini_api(api_key: str, system_prompt: str, user_prompt: str, history: List[Dict[str, str]] = None) -> Optional[str]:
    """Invokes Google Gemini REST API (gemini-2.5-flash or gemini-1.5-flash)."""
    models = ["gemini-2.5-flash", "gemini-1.5-flash"]

    contents = []
    if history:
        for turn in history[-6:]:  # Keep last 3 turns
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
            with urllib.request.urlopen(req, timeout=12.0) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                candidates = res.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts and "text" in parts[0]:
                        return parts[0]["text"]
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            logger.warning("Gemini %s API error (%s): %s", model, e.code, err_body)
            if e.code in (404, 400):
                continue  # Try next model
            break
        except Exception as ex:
            logger.warning("Gemini %s request failed: %s", model, ex)
            break

    return None


def call_openai_api(api_key: str, system_prompt: str, user_prompt: str, history: List[Dict[str, str]] = None) -> Optional[str]:
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
                return choices[0].get("message", {}).get("content")
    except Exception as ex:
        logger.warning("OpenAI API request failed: %s", ex)
    return None


def autonomous_copilot_rule_engine(user_msg: str, ctx: Dict[str, Any]) -> str:
    """
    Intelligent built-in algorithmic reasoning engine.
    Executes if no external LLM API key (GEMINI_API_KEY) is supplied yet on Render
    or if local Antigravity bridge is offline.
    Accurately parses market queries and provides actionable quantitative answers.
    """
    msg_low = user_msg.lower().strip()
    spots = ctx.get("spots", {})
    sim = ctx.get("simulator", {})
    news = ctx.get("news", [])
    levels = ctx.get("levels", {})

    # 0. Historical Session OHLC Lookup (e.g. "what is open spot price in 19th nov 2026")
    if "historical" in ctx:
        return ctx["historical"]["formatted_markdown"]

    nifty_spot = None
    if isinstance(spots, dict) and "symbol" in spots:
        nifty_spot = spots.get("spot_price") or spots.get("price")
    elif isinstance(spots, dict):
        for k, v in spots.items():
            if isinstance(v, dict) and "NIFTY" in k and "BANK" not in k:
                nifty_spot = v.get("spot_price") or v.get("price")
                break

    # 1. Volume Profile, POC, Fair Value, Zones
    if any(w in msg_low for w in ["poc", "fair value", "vah", "val", "zone", "value area", "profile"]):
        resp = [
            "### 📊 Volume Profile & Fair Value Engine Report",
            "- **Timeframe**: 5-Minute Intraday Session (Standard for NIFTY/BANKNIFTY).",
            "- **Point of Control (POC)**: Represents the high-density trading node where maximum volume exchanged.",
            "- **Value Area (70%)**: Bounded between **VAL (Value Area Low)** and **VAH (Value Area High)**.",
        ]
        if nifty_spot:
            resp.append(f"- **Current NIFTY Spot**: ₹{nifty_spot:,.2f}")
        resp.extend([
            "\n**Actionable Rules:**",
            "1. **Inside Value Area**: High probability of rotational / mean-reverting chop between VAL and VAH.",
            "2. **Above VAH**: Premium Zone — do not chase longs; wait for a pullback to VAH or POC retest.",
            "3. **Below VAL**: Discount Zone — do not short blindly; watch for institutional absorption.",
            "\n*Tip: Click the **[ 📊 Fair Value POC ]** toolbar button on the Charts tab to view live histogram bins.*",
        ])
        return "\n".join(resp)

    # 2. Positions, P&L, Trades
    if any(w in msg_low for w in ["position", "pnl", "p&l", "profit", "loss", "trade", "holding"]):
        net_pnl = sim.get("net_pnl", 0.0)
        pnl_sign = "+" if net_pnl >= 0 else ""
        active = sim.get("active_positions", [])
        resp = [
            "### ⚡ Paper Trading & Portfolio Status",
            f"- **Execution Engine**: {sim.get('status', 'ACTIVE')}",
            f"- **Net Realized P&L**: **₹{pnl_sign}{net_pnl:,.2f}**",
            f"- **Win Rate**: {sim.get('win_rate', '0%')} ({sim.get('total_trades', 0)} total closed trades)",
            f"- **Active Positions**: **{len(active)}**",
        ]
        if active:
            resp.append("\n**Open Contracts:**")
            for p in active:
                resp.append(f"- {p.get('symbol')} {p.get('strike')} {p.get('option_type')} | Qty: {p.get('qty')} | Entry: ₹{p.get('entry_price')} | Unrealized: ₹{p.get('unrealized_pnl', 0.0):,.2f}")
        else:
            resp.append("\n*No open positions currently. System is standing by for high-probability setups.*")
        return "\n".join(resp)

    # 3. Market News & Sentiment
    if any(w in msg_low for w in ["news", "sentiment", "headline", "macro", "event"]):
        sentiment = ctx.get("news_sentiment", "NEUTRAL")
        resp = [
            f"### 📰 Market News & Sentiment Analysis: **{sentiment}**",
        ]
        if news:
            for i, n in enumerate(news[:4], 1):
                resp.append(f"{i}. **[{n.get('impact_type', 'MARKET')}]** {n.get('title')}")
        else:
            resp.append("- Automated news scraper is monitoring Indian economic calendar and corporate releases.")
        resp.append("\n*Tip: Switch to the **Market News & Impact** tab for full historical sentiment breakdown.*")
        return "\n".join(resp)

    # 4. Spot Price, Trend, Direction
    if any(w in msg_low for w in ["price", "spot", "trend", "direction", "nifty", "market"]):
        resp = [
            "### 📈 Real-Time Spot & Market Structure",
        ]
        if spots:
            if isinstance(spots, dict) and "symbol" in spots:
                sym = spots.get("symbol", "NIFTY")
                p = spots.get("spot_price") or spots.get("price") or "--"
                chg = spots.get("change") or spots.get("change_pct") or ""
                resp.append(f"- **{sym}**: ₹{p} {f'({chg})' if chg else ''}")
            elif isinstance(spots, dict):
                for sym, d in spots.items():
                    if isinstance(d, dict):
                        p = d.get("spot_price") or d.get("price") or "--"
                        chg = d.get("change") or d.get("change_pct") or ""
                        resp.append(f"- **{sym}**: ₹{p} {f'({chg})' if chg else ''}")
        else:
            resp.append("- Real-time spot telemetry feed active (5-Minute automated interval).")
        resp.extend([
            "\n**Market Session Clock**: NSE trades **09:15 to 15:30 IST**.",
            "- Directional bias is filtered by 9 & 20 EMA slope and Supertrend alignment.",
            "- High-probability entries execute between **09:25 and 15:00 IST**.",
        ])
        return "\n".join(resp)

    # 5. Default Comprehensive Help
    resp = [
        "### 🤖 NIFTY Autonomous Trader Copilot",
        "Server is active on Render. Market telemetry & analysis engine ready.",
    ]
    if nifty_spot:
        resp.append(f"- **NIFTY 50 Spot**: ₹{nifty_spot:,.2f}")
    resp.extend([
        f"- **Paper Trading P&L**: ₹{sim.get('net_pnl', 0.0):,.2f} ({sim.get('active_positions_count', 0)} active positions)",
        f"- **Armed Level Triggers**: {levels.get('armed_count', 0)} triggers standing by",
        "\n**You can ask me:**",
        "• *'What is today's POC and are we in Premium or Discount zone?'*",
        "• *'What was open spot price in 19th nov 2026?'*",
        "• *'Show my active positions and current P&L'*",
        "• *'Summarize today's market news sentiment'*",
        "• *'Check NIFTY trend and key levels'*",
        "\n> [!TIP]\n> *Whenever you have Antigravity running on your computer, the chat automatically bridges directly to Antigravity for live interactive reasoning.*",
    ])
    return "\n".join(resp)


def handle_ai_chat_request(data: Dict[str, Any], root_dir: Optional[Path] = None) -> Dict[str, Any]:
    """
    Main orchestration handler for the web chat endpoint `/api/chat`.
    1. If Antigravity local bridge is online, routes directly to Antigravity.
    2. Otherwise, uses Gemini API / OpenAI API with live context & historical SQLite lookup.
    3. Seamlessly falls back to the autonomous algorithmic rule engine.
    """
    user_msg = (data.get("message") or "").strip()
    history = data.get("history") or []

    if not user_msg:
        return {"status": "error", "message": "Empty message provided"}

    # Compile real-time context + historical lookup
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
        "1. Always cite exact numbers, price levels, historical session data, and P&L from the provided context.\n"
        "2. If the user asks for historical prices or past dates, use the exact numbers from the HISTORICAL MARKET SESSION block.\n"
        "3. Explain technical setups clearly using Volume Profile (POC, VAH, VAL), Supertrend, and EMA structure.\n"
        "4. Emphasize strict risk management (1:3 Risk-to-Reward, hard stops, max daily drawdown ₹2,000).\n"
        "5. Format your responses with clean Markdown, bullet points, and bold price highlights.\n"
        "6. Keep responses concise, punchy, and actionable.\n\n"
        f"{context_text}"
    )

    reply = None
    model_name = "autonomous_rules_engine"

    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if gemini_key:
        reply = call_gemini_api(gemini_key, system_prompt, user_msg, history)
        if reply:
            model_name = "gemini-2.5-flash"

    if not reply:
        openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if openai_key:
            reply = call_openai_api(openai_key, system_prompt, user_msg, history)
            if reply:
                model_name = "gpt-4o-mini"

    # -------------------------------------------------------------
    # PRIORITY 2: Built-in Autonomous Rule Engine
    # -------------------------------------------------------------
    if not reply:
        reply = autonomous_copilot_rule_engine(user_msg, ctx)
        model_name = "autonomous_copilot"

    return {
        "status": "ok",
        "reply": reply,
        "model": model_name,
        "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
    }
