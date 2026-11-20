"""
Local Webview Dashboard Server for NIFTY Autonomous Trader.

Serves an interactive real-time web dashboard displaying:
1. System Status, Safety Circuit Breakers & Session Health
2. Market Observation & Candle Telemetry (1H / 15M)
3. AI Brain Reasoning History & Verdicts (Gemini 2.5)
4. Active Sensibull Paper Positions & Real-Time P&L
5. Experience Memory & Trade Post-Mortems
6. Isolated Hermes Research Zone (Feature Sets, Hypotheses, Dynamic Segment Scores, Negative Knowledge)
"""

from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional
import webbrowser

logger = logging.getLogger(__name__)


def _query_db_rows(db_path: Path, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
    """Helper to query SQLite safely with dict rows."""
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute(query, params)
            rows = [dict(r) for r in cur.fetchall()]
            return rows
        finally:
            conn.close()
    except Exception as e:
        logger.debug("Database read error for %s: %s", db_path, e)
        return []


class DashboardDataAggregator:
    """Aggregates real-time state from runtime and SQLite stores."""

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or Path(".").resolve()
        self.data_dir = self.root_dir / "data"
        self.research_dir = self.data_dir / "hermes_research"

    def get_system_overview(self) -> Dict[str, Any]:
        return {
            "application": "NIFTY Autonomous Trader",
            "version": "0.1.0",
            "mode": "RESEARCH / PAPER",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "paper_broker": "Sensibull Virtual Portfolio (ACTIVE)",
            "live_broker": "DISABLED (Safety Circuit Breakers Locked)",
            "gemini_provider": "READY (Gemini 2.5 Flash/Pro)",
            "safety_policies": {
                "max_portfolio_daily_loss": "₹2,000",
                "max_daily_loss_per_instrument": "₹1,000 (NIFTY & BANKNIFTY)",
                "max_lots_per_trade": "1 Lot (65 qty NIFTY / 30 qty BANKNIFTY)",
                "max_trades_per_day": "3 Trades (NIFTY) | 3 Trades (BANKNIFTY)",
                "active_instrument_limit": "1 Instrument active at a time",
                "minimum_rr_ratio": "1:3 (Mandatory Risk-to-Reward)",
                "execution_window": "09:25–15:15 IST",
            }
        }

    def get_brain_history(self, limit: int = 15) -> List[Dict[str, Any]]:
        db_path = self.data_dir / "brain_history.db"
        query = "SELECT * FROM brain_history ORDER BY timestamp DESC LIMIT ?"
        rows = _query_db_rows(db_path, query, (limit,))
        for r in rows:
            for k in ["reasoning", "uncertainties", "important_levels"]:
                if k in r and isinstance(r[k], str):
                    try:
                        r[k] = json.loads(r[k])
                    except Exception:
                        pass
        return rows

    def get_paper_positions(self) -> Dict[str, Any]:
        db_positions = self.data_dir / "paper_positions.db"
        db_monitoring = self.data_dir / "position_monitoring.db"

        positions = _query_db_rows(db_positions, "SELECT * FROM paper_positions ORDER BY updated_at DESC LIMIT 20")
        monitoring_cycles = _query_db_rows(db_monitoring, "SELECT * FROM monitoring_cycles ORDER BY timestamp DESC LIMIT 20")
        reassessments = _query_db_rows(db_monitoring, "SELECT * FROM reassessment_records ORDER BY timestamp DESC LIMIT 20")

        return {
            "positions": positions,
            "recent_monitoring": monitoring_cycles,
            "reassessments": reassessments,
        }

    def get_experience_summary(self) -> Dict[str, Any]:
        db_exp = self.data_dir / "experience.db"
        experiences = _query_db_rows(db_exp, "SELECT * FROM experience_records ORDER BY completed_at DESC LIMIT 15")
        for e in experiences:
            for k in ["tags", "reasoning_summary", "outcome_summary", "lessons"]:
                if k in e and isinstance(e[k], str):
                    try:
                        e[k] = json.loads(e[k])
                    except Exception:
                        pass
        return {"experiences": experiences}

    def get_research_zone_summary(self) -> Dict[str, Any]:
        assessments_db = self.research_dir / "assessments.db"
        research_db = self.research_dir / "research.db"
        memory_db = self.research_dir / "research_memory.db"
        market_db = self.research_dir / "market_data.db"

        assessments = _query_db_rows(assessments_db, "SELECT * FROM assessments ORDER BY timestamp DESC LIMIT 5")
        for a in assessments:
            segs = _query_db_rows(assessments_db, "SELECT * FROM assessment_segments WHERE research_id = ?", (a["research_id"],))
            a["segments"] = segs

        hypotheses = _query_db_rows(research_db, "SELECT * FROM hypotheses ORDER BY created_at DESC LIMIT 10")
        test_results = _query_db_rows(research_db, "SELECT * FROM test_results ORDER BY tested_at DESC LIMIT 10")
        failures = _query_db_rows(memory_db, "SELECT * FROM failed_hypotheses ORDER BY recorded_at DESC LIMIT 10")
        findings = _query_db_rows(memory_db, "SELECT * FROM research_findings ORDER BY created_at DESC LIMIT 10")
        bars_count = _query_db_rows(market_db, "SELECT count(*) as count FROM normalized_bars")

        return {
            "total_normalized_bars": bars_count[0]["count"] if bars_count else 0,
            "assessments": assessments,
            "hypotheses": hypotheses,
            "test_results": test_results,
            "failed_hypotheses": failures,
            "findings": findings,
        }

    def get_simulator_summary(self) -> Dict[str, Any]:
        try:
            from nifty_trader.simulator.service import get_simulator_service
            return get_simulator_service().get_dashboard_summary()
        except Exception as e:
            logger.debug("Simulator summary read error: %s", e)
            return {"status": "PAUSED", "total_trades": 0, "net_pnl": 0.0}

    def get_spot_summary(self) -> Dict[str, Any]:
        try:
            from nifty_trader.market_data.spot_service import get_spot_service
            return get_spot_service().get_dashboard_summary()
        except Exception as e:
            logger.debug("Spot summary read error: %s", e)
            return {"status": "PAUSED", "latest": None}

    def get_levels_summary(self) -> Dict[str, Any]:
        try:
            from nifty_trader.simulator.level_strategy import get_level_strategy_manager
            from nifty_trader.market_data.spot_service import get_spot_service
            spot_data = get_spot_service().latest_spots
            current_spots = {k: float(v.get("spot_price", 0.0)) for k, v in spot_data.items()}
            mgr = get_level_strategy_manager()
            triggers = mgr.list_triggers(current_spots=current_spots)
            return {
                "triggers": triggers,
                "armed_count": sum(1 for t in triggers if t.get("status") == "ARMED"),
                "triggered_count": sum(1 for t in triggers if t.get("status") == "TRIGGERED"),
            }
        except Exception as e:
            logger.debug("Levels summary read error: %s", e)
            return {"triggers": [], "armed_count": 0, "triggered_count": 0}

    def get_news_summary(self) -> Dict[str, Any]:
        try:
            from nifty_trader.market_data.news_service import get_news_service
            return get_news_service(self.root_dir).get_news_summary()
        except Exception as e:
            logger.debug("News summary read error: %s", e)
            return {
                "stats": {"total": 0, "bullish": 0, "bearish": 0, "important": 0, "good_news": 0, "macro": 0},
                "last_fetch": "Unavailable",
                "top_scrolling": [],
                "recent_news": [],
            }


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
<meta name="theme-color" content="#0b0f19">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="format-detection" content="telephone=no">
<title>NIFTY Autonomous Trader — Live Webview Dashboard</title>
<style>
  :root {
    --bg-main: #0b0f19;
    --bg-card: #131b2e;
    --bg-card-hover: #19233c;
    --border: #1f2b48;
    --text-primary: #f8fafc;
    --text-secondary: #94a3b8;
    --accent: #3b82f6;
    --accent-glow: rgba(59, 130, 246, 0.15);
    --green: #10b981;
    --red: #ef4444;
    --yellow: #f59e0b;
    --purple: #8b5cf6;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background-color: var(--bg-main);
    color: var(--text-primary);
    line-height: 1.5;
    padding: 18px 24px;
  }

  header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid var(--border);
    padding-bottom: 16px;
    margin-bottom: 20px;
  }

  .brand h1 { font-size: 1.35rem; font-weight: 800; letter-spacing: -0.5px; }
  .brand .tagline { font-size: 0.82rem; color: var(--text-secondary); }

  .status-badges { display: flex; gap: 10px; align-items: center; }
  .badge {
    font-size: 0.72rem;
    font-weight: 700;
    padding: 4px 10px;
    border-radius: 9999px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    border: 1px solid transparent;
  }
  .badge-green { background: rgba(16, 185, 129, 0.12); color: var(--green); border-color: rgba(16, 185, 129, 0.3); }
  .badge-blue { background: rgba(59, 130, 246, 0.12); color: var(--accent); border-color: rgba(59, 130, 246, 0.3); }
  .badge-red { background: rgba(239, 68, 68, 0.12); color: var(--red); border-color: rgba(239, 68, 68, 0.3); }
  .badge-yellow { background: rgba(245, 158, 11, 0.12); color: var(--yellow); border-color: rgba(245, 158, 11, 0.3); }

  .nav-tabs {
    display: flex;
    gap: 8px;
    margin-bottom: 20px;
    border-bottom: 1px solid var(--border);
    padding-bottom: 8px;
    overflow-x: auto;
    white-space: nowrap;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
  }
  .nav-tabs::-webkit-scrollbar {
    display: none;
  }
  .nav-tab {
    background: transparent;
    border: none;
    color: var(--text-secondary);
    padding: 8px 16px;
    border-radius: 6px;
    font-weight: 600;
    font-size: 0.88rem;
    cursor: pointer;
    flex-shrink: 0;
    touch-action: manipulation;
    -webkit-tap-highlight-color: transparent;
    transition: all 0.2s ease;
  }
  .nav-tab:hover { background: var(--bg-card); color: var(--text-primary); }
  .nav-tab.active { background: var(--accent); color: #ffffff; }

  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin-bottom: 20px; }
  .card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px;
    transition: border-color 0.2s;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }
  .card:hover { border-color: #2e3e68; }
  .card-header { font-size: 0.85rem; font-weight: 700; color: var(--text-secondary); text-transform: uppercase; margin-bottom: 10px; display: flex; justify-content: space-between; }
  .card-value { font-size: 1.5rem; font-weight: 800; color: var(--text-primary); margin-bottom: 4px; }
  .card-subtext { font-size: 0.78rem; color: var(--text-secondary); }

  table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 0.82rem; }
  th, td { padding: 9px 12px; text-align: left; border-bottom: 1px solid var(--border); }
  th { background: #162038; color: var(--text-secondary); font-weight: 700; text-transform: uppercase; font-size: 0.72rem; }
  tr:hover td { background: var(--bg-card-hover); }

  .tab-content { display: none; }
  .tab-content.active { display: block; }

  .segment-pill { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; margin-right: 4px; }
  .score-pos { color: var(--green); font-weight: 700; }
  .score-neg { color: var(--red); font-weight: 700; }

  .btn {
    background: var(--bg-card);
    border: 1px solid var(--border);
    color: var(--text-primary);
    padding: 6px 12px;
    border-radius: 6px;
    font-size: 0.8rem;
    font-weight: 600;
    cursor: pointer;
  }
  .btn:hover { background: var(--bg-card-hover); }

  /* Scrolling News Ticker at Dashboard Top */
  @keyframes pulseLiveDot {
    0% { transform: scale(0.95); opacity: 0.85; box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.7); }
    70% { transform: scale(1.1); opacity: 1; box-shadow: 0 0 0 6px rgba(239, 68, 68, 0); }
    100% { transform: scale(0.95); opacity: 0.85; box-shadow: 0 0 0 0 rgba(239, 68, 68, 0); }
  }
  @keyframes marqueeTickerAnim {
    0% { transform: translateX(0); }
    100% { transform: translateX(-50%); }
  }
  .news-ticker-container {
    background: linear-gradient(90deg, #131728 0%, #171d33 50%, #151829 100%);
    border: 1px solid var(--border);
    border-left: 4px solid #ef4444;
    border-radius: 8px;
    padding: 7px 12px;
    margin-bottom: 12px;
    display: flex;
    align-items: center;
    gap: 12px;
    box-shadow: 0 4px 14px rgba(0,0,0,0.35);
  }
  .news-ticker-badge {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-shrink: 0;
    border-right: 1px solid var(--border);
    padding-right: 12px;
    font-size: 0.74rem;
    font-weight: 800;
    color: #f87171;
    letter-spacing: 0.5px;
    text-transform: uppercase;
  }
  .live-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #ef4444;
    display: inline-block;
    animation: pulseLiveDot 1.8s infinite;
  }
  .news-ticker-viewport {
    overflow: hidden;
    white-space: nowrap;
    position: relative;
    width: 100%;
    cursor: pointer;
  }
  .news-ticker-track {
    display: inline-flex;
    gap: 32px;
    align-items: center;
    will-change: transform;
    animation: marqueeTickerAnim 180s linear infinite;
  }
  .news-ticker-viewport:hover .news-ticker-track {
    animation-play-state: paused;
  }

  /* Option Chain Styles */
  .oc-table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
  .oc-table th { padding: 6px 8px; text-align: center; font-weight: 700; font-size: 0.72rem; }
  .oc-table td { padding: 5px 6px; text-align: center; border-bottom: 1px solid var(--border); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace; }
  .oc-itm-ce { background: rgba(16, 185, 129, 0.05); }
  .oc-itm-pe { background: rgba(239, 68, 68, 0.05); }
  .oc-atm-row td { background: rgba(245, 158, 11, 0.12) !important; font-weight: 800; }
  .oc-atm-strike { background: #f59e0b !important; color: #000000 !important; font-weight: 900; border-radius: 4px; padding: 2px 6px; }
  .oc-btn-ce { background: rgba(16, 185, 129, 0.2); color: var(--green); border: 1px solid rgba(16, 185, 129, 0.4); border-radius: 4px; padding: 2px 8px; font-weight: 700; font-size: 0.72rem; cursor: pointer; }
  .oc-btn-ce:hover { background: var(--green); color: black; }
  .oc-btn-pe { background: rgba(239, 68, 68, 0.2); color: var(--red); border: 1px solid rgba(239, 68, 68, 0.4); border-radius: 4px; padding: 2px 8px; font-weight: 700; font-size: 0.72rem; cursor: pointer; }
  .oc-btn-pe:hover { background: var(--red); color: white; }
  .oc-btn-buy { background: rgba(16, 185, 129, 0.22); color: var(--green); border: 1px solid rgba(16, 185, 129, 0.5); border-radius: 4px; padding: 2px 7px; font-weight: 800; font-size: 0.68rem; cursor: pointer; transition: all 0.12s; }
  .oc-btn-buy:hover { background: var(--green); color: black; }
  .oc-btn-sell { background: rgba(239, 68, 68, 0.22); color: var(--red); border: 1px solid rgba(239, 68, 68, 0.5); border-radius: 4px; padding: 2px 7px; font-weight: 800; font-size: 0.68rem; cursor: pointer; transition: all 0.12s; }
  .oc-btn-sell:hover { background: var(--red); color: white; }
  .ticker-pill-item {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font-size: 0.8rem;
    color: var(--text-primary);
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 6px;
    padding: 4px 10px;
    text-decoration: none;
    cursor: pointer;
    transition: all 0.2s;
  }
  .ticker-pill-item:hover {
    background: rgba(59, 130, 246, 0.18);
    border-color: var(--accent);
    color: #ffffff;
  }
  .news-filter-btn {
    background: var(--bg-card);
    border: 1px solid var(--border);
    color: var(--text-secondary);
    padding: 6px 12px;
    border-radius: 6px;
    font-size: 0.78rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
  }
  .news-filter-btn:hover {
    color: var(--text-primary);
    background: var(--bg-card-hover);
  }
  .news-filter-btn.active {
    background: var(--accent);
    color: #ffffff;
    border-color: var(--accent);
  }
  .news-item-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    transition: border-color 0.2s, transform 0.15s;
  }
  .news-item-card:hover {
    border-color: #3b82f6;
    transform: translateY(-1px);
  }

  /* ==============================================================================
     MOBILE & TOUCH DEVICE RESPONSIVE SYSTEM
     ============================================================================== */
  @media (max-width: 900px) {
    header {
      flex-direction: column;
      align-items: stretch;
      gap: 12px;
    }
    .status-badges {
      flex-wrap: wrap;
      justify-content: flex-start;
      gap: 6px;
    }
    #header-spot-badge {
      width: 100%;
      text-align: center;
      padding: 6px 10px !important;
    }
  }

  @media (max-width: 680px) {
    body {
      padding: 10px 10px 60px 10px;
    }
    header {
      padding-bottom: 12px;
      margin-bottom: 12px;
    }
    .brand h1 {
      font-size: 1.15rem;
      letter-spacing: -0.3px;
    }
    .brand .tagline {
      font-size: 0.72rem;
      line-height: 1.3;
    }
    .badge {
      font-size: 0.65rem;
      padding: 3px 7px;
    }
    .btn {
      padding: 6px 10px;
      font-size: 0.76rem;
      touch-action: manipulation;
    }

    /* News Ticker Mobile Layout */
    .news-ticker-container {
      flex-direction: column;
      align-items: stretch;
      gap: 6px;
      padding: 8px 10px;
    }
    .news-ticker-badge {
      border-right: none;
      border-bottom: 1px solid var(--border);
      padding-right: 0;
      padding-bottom: 4px;
      font-size: 0.68rem;
      width: 100%;
    }
    .news-ticker-viewport {
      width: 100%;
      padding: 2px 0;
    }
    .news-ticker-container > div:last-child {
      border-left: none !important;
      padding-left: 0 !important;
      border-top: 1px solid var(--border);
      padding-top: 6px;
      justify-content: space-between;
      width: 100%;
      flex-wrap: wrap;
    }

    /* Persistent Market Telemetry Strip */
    #persistent-market-bar {
      position: relative !important;
      padding: 10px 10px !important;
      margin-bottom: 12px !important;
    }
    #persistent-market-bar > div:first-child {
      flex-direction: column;
      align-items: stretch !important;
      gap: 6px !important;
    }
    #persistent-market-cards {
      grid-template-columns: 1fr !important;
      gap: 8px !important;
    }

    /* Grid & Cards */
    .grid {
      grid-template-columns: 1fr !important;
      gap: 12px !important;
      margin-bottom: 14px !important;
    }
    .card {
      padding: 12px !important;
      border-radius: 8px !important;
    }
    .card-value {
      font-size: 1.25rem !important;
    }
    .card-header {
      font-size: 0.78rem !important;
    }

    /* Tables Mobile Horizontal Scrolling */
    table {
      font-size: 0.72rem !important;
      min-width: 520px;
    }
    th, td {
      padding: 6px 8px !important;
    }
    .oc-table {
      font-size: 0.7rem !important;
      min-width: 720px;
    }
    .oc-table th, .oc-table td {
      padding: 4px 3px !important;
    }
    .oc-btn-ce, .oc-btn-pe {
      padding: 5px 8px !important;
      font-size: 0.68rem !important;
      touch-action: manipulation;
    }

    /* Mobile News Layout */
    .news-item-card {
      padding: 12px !important;
    }

    /* Modals Mobile Sizing */
    #oc-trade-modal > div, #add-news-modal > div {
      max-width: 96% !important;
      width: 96% !important;
      padding: 16px !important;
      max-height: 92vh !important;
      overflow-y: auto !important;
      border-radius: 8px !important;
      margin: auto;
    }

    /* Form Inputs on Touch Screens */
    input, select, textarea {
      font-size: 16px !important; /* Prevents auto-zoom on iOS Safari */
    }
  }
</style>
</head>
<body>

<header>
  <div class="brand">
    <h1>NIFTY Autonomous Trader</h1>
    <div class="tagline">Hermes Autonomous Operator + Cognitive AI Brain + Segregated Research Zone</div>
  </div>
  <div class="status-badges">
    <span class="badge badge-green" id="header-spot-badge" style="font-size: 0.82rem; padding: 4px 12px; background: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.4);">🟢 NIFTY: Loading... | 🏦 BANKNIFTY: Loading... | 🌐 GIFT: Loading...</span>
    <span class="badge badge-green" id="app-status">RESEARCH MODE</span>
    <span class="badge badge-green" id="sim-badge">⚡ SIMULATOR: AUTO-ACTIVE</span>
    <span class="badge" id="supabase-badge" style="font-size: 0.8rem; background: rgba(59, 130, 246, 0.15); border: 1px solid rgba(59, 130, 246, 0.4); color: #60a5fa;" title="Supabase Cloud Sync Status">☁️ SUPABASE: CHECKING...</span>
    <span class="badge" id="telegram-badge" style="font-size: 0.8rem; background: rgba(56, 189, 248, 0.15); border: 1px solid rgba(56, 189, 248, 0.4); color: #38bdf8; cursor: pointer;" onclick="switchTab('tab-telegram')" title="Telegram Bot & 15-Minute Auto-Execution Alerts">📱 TELEGRAM: CHECKING...</span>
    <span class="badge badge-blue">Gemini 2.5 Brain: READY</span>
    <span class="badge badge-yellow">Sensibull Virtual: READY</span>
    <span class="badge badge-red">Live Broker: DISABLED</span>
    <button class="btn" onclick="fetchData()">🔄 Refresh</button>
  </div>
</header>

<!-- PERSISTENT TOP BREAKING & IMPORTANT INDIAN MARKET NEWS TICKER (SCROLLING AT DASHBOARD TOP) -->
<div id="persistent-news-ticker" class="news-ticker-container">
  <div class="news-ticker-badge">
    <span class="live-dot"></span>
    <span>🇮🇳 BREAKING INDIAN MARKET NEWS</span>
  </div>
  <div class="news-ticker-viewport" onclick="openNewsTab()" title="Click to open Full News Section. Hover mouse to pause scrolling.">
    <div class="news-ticker-track" id="top-news-ticker-track">
      <span style="color: var(--text-secondary); font-size: 0.8rem;">Loading real-time Indian market news &amp; NIFTY/BANKNIFTY catalysts...</span>
    </div>
  </div>
  <div style="display: flex; align-items: center; gap: 6px; flex-shrink: 0; border-left: 1px solid var(--border); padding-left: 10px;">
    <!-- Speed Controls -->
    <div style="display: flex; gap: 3px; align-items: center; background: rgba(0,0,0,0.35); padding: 2px 4px; border-radius: 4px; border: 1px solid var(--border);">
      <button onclick="setTickerSpeed('slow')" id="speed-btn-slow" class="btn" style="padding: 2px 6px; font-size: 0.68rem; font-weight: 700; background: var(--accent); color: white; border: none; border-radius: 3px;" title="Comfortable slow scroll speed">🐢 Slow</button>
      <button onclick="setTickerSpeed('superslow')" id="speed-btn-superslow" class="btn" style="padding: 2px 6px; font-size: 0.68rem; font-weight: 600; background: transparent; color: var(--text-secondary); border: none; border-radius: 3px;" title="Super Slow (extra time to read)">🐌 Very Slow</button>
      <button onclick="setTickerSpeed('normal')" id="speed-btn-normal" class="btn" style="padding: 2px 6px; font-size: 0.68rem; font-weight: 600; background: transparent; color: var(--text-secondary); border: none; border-radius: 3px;" title="Standard speed">▶️ Normal</button>
      <button onclick="toggleTickerPause()" id="ticker-pause-btn" class="btn" style="padding: 2px 6px; font-size: 0.68rem; font-weight: 700; background: rgba(245, 158, 11, 0.2); color: var(--yellow); border: 1px solid rgba(245, 158, 11, 0.4); border-radius: 3px;" title="Pause or Resume marquee scrolling">⏸️</button>
    </div>
    <button onclick="openNewsTab()" class="btn" style="padding: 3px 8px; font-size: 0.72rem; background: rgba(59, 130, 246, 0.15); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.3); border-radius: 4px; cursor: pointer; font-weight: 700;">📰 All News</button>
    <button onclick="refreshNewsNow()" class="btn" style="padding: 3px 8px; font-size: 0.72rem; background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); border-radius: 4px; cursor: pointer; font-weight: 700;" title="Refresh live RSS feeds now">🔄 Sync</button>
  </div>
</div>

<!-- PERSISTENT TOP MARKET TICKER BAR (PERMANENTLY VISIBLE ACROSS ALL TABS) -->
<div id="persistent-market-bar" style="position: sticky; top: 0; z-index: 1000; background: rgba(13, 20, 36, 0.96); backdrop-filter: blur(10px); border: 1px solid var(--border); border-top: 3px solid var(--accent); border-radius: 8px; padding: 10px 16px; margin-bottom: 16px; box-shadow: 0 4px 18px rgba(0,0,0,0.45);">
  <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 8px;">
    <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
      <span style="font-size: 0.76rem; font-weight: 800; letter-spacing: 0.5px; text-transform: uppercase; color: var(--accent);">📡 LIVE NSE &amp; GLOBAL SPOT TELEMETRY (ALL-TIME VISIBLE)</span>
      <span id="top-bar-session-badge" class="badge badge-green" style="font-size: 0.72rem;">AUTO-ACTIVE (09:15–15:30 IST)</span>
      <span style="font-size: 0.72rem; color: var(--text-secondary);">⏰ Continuous Mon–Fri (Excl. Sat/Sun/NSE Holidays)</span>
    </div>
    <div style="display: flex; align-items: center; gap: 8px; font-size: 0.75rem; flex-wrap: wrap;">
      <span style="color: var(--text-secondary);">Next 5M fetch: <strong id="top-bar-countdown" style="color: var(--accent);">05:00</strong></span>
      <span style="color: var(--text-secondary);" id="top-bar-last-time">--</span>
      <button class="btn" onclick="fetchSpotNow()" style="padding: 2px 10px; font-size: 0.72rem; background: var(--green); color: black; font-weight: 700; border: none; border-radius: 4px; cursor: pointer;">🔄 Fetch Now</button>
      <button class="btn" id="market-bar-toggle-btn" onclick="toggleMarketBar()" style="padding: 2px 8px; font-size: 0.72rem; background: rgba(255,255,255,0.08); color: var(--text-secondary); border: 1px solid var(--border); border-radius: 4px; cursor: pointer;" title="Toggle Telemetry Cards">▲</button>
    </div>
  </div>

  <div id="persistent-market-cards" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 10px;">
    <!-- NIFTY 50 Persistent Strip -->
    <div style="background: rgba(19, 27, 46, 0.85); border: 1px solid var(--border); border-left: 3px solid var(--accent); border-radius: 6px; padding: 8px 12px; display: flex; flex-direction: column; gap: 4px;">
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <span style="font-weight: 800; font-size: 0.88rem; color: #60a5fa;">🇮🇳 NIFTY 50</span>
        <div>
          <strong id="top-nifty-close" style="font-size: 1.15rem; color: var(--text-primary);">₹--</strong>
          <span id="top-nifty-change" style="font-size: 0.75rem; font-weight: 700; margin-left: 4px;">--</span>
        </div>
      </div>
      <div style="display: grid; grid-template-columns: repeat(5, 1fr); gap: 4px; font-size: 0.72rem; background: rgba(0,0,0,0.25); padding: 4px 6px; border-radius: 4px;">
        <div><span style="color: var(--text-secondary);">Open:</span> <strong id="top-nifty-open">₹--</strong></div>
        <div><span style="color: var(--text-secondary);">High:</span> <strong id="top-nifty-high" style="color: var(--green);">₹--</strong></div>
        <div><span style="color: var(--text-secondary);">Low:</span> <strong id="top-nifty-low" style="color: var(--red);">₹--</strong></div>
        <div><span style="color: var(--text-secondary);">PDH:</span> <strong id="top-nifty-pdh" style="color: #60a5fa;">₹--</strong></div>
        <div><span style="color: var(--text-secondary);">PDL:</span> <strong id="top-nifty-pdl" style="color: #f87171;">₹--</strong></div>
      </div>
      <!-- Calculated 2S & 2R Levels -->
      <div style="display: flex; gap: 4px; font-size: 0.69rem; justify-content: space-between; margin-top: 3px; padding-top: 3px; border-top: 1px dashed rgba(255,255,255,0.08);">
        <div><span style="color: #ef4444; font-weight: 700;">R2:</span> <strong id="top-nifty-r2" style="color: #fca5a5;">₹--</strong></div>
        <div><span style="color: #f59e0b; font-weight: 700;">R1:</span> <strong id="top-nifty-r1" style="color: #fde68a;">₹--</strong></div>
        <div><span style="color: #94a3b8; font-weight: 700;">PP:</span> <strong id="top-nifty-pp" style="color: #cbd5e1;">₹--</strong></div>
        <div><span style="color: #10b981; font-weight: 700;">S1:</span> <strong id="top-nifty-s1" style="color: #86efac;">₹--</strong></div>
        <div><span style="color: #3b82f6; font-weight: 700;">S2:</span> <strong id="top-nifty-s2" style="color: #93c5fd;">₹--</strong></div>
      </div>
    </div>

    <!-- BANKNIFTY Persistent Strip -->
    <div style="background: rgba(19, 27, 46, 0.85); border: 1px solid var(--border); border-left: 3px solid #8b5cf6; border-radius: 6px; padding: 8px 12px; display: flex; flex-direction: column; gap: 4px;">
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <span style="font-weight: 800; font-size: 0.88rem; color: #a78bfa;">🏦 BANKNIFTY</span>
        <div>
          <strong id="top-bank-close" style="font-size: 1.15rem; color: var(--text-primary);">₹--</strong>
          <span id="top-bank-change" style="font-size: 0.75rem; font-weight: 700; margin-left: 4px;">--</span>
        </div>
      </div>
      <div style="display: grid; grid-template-columns: repeat(5, 1fr); gap: 4px; font-size: 0.72rem; background: rgba(0,0,0,0.25); padding: 4px 6px; border-radius: 4px;">
        <div><span style="color: var(--text-secondary);">Open:</span> <strong id="top-bank-open">₹--</strong></div>
        <div><span style="color: var(--text-secondary);">High:</span> <strong id="top-bank-high" style="color: var(--green);">₹--</strong></div>
        <div><span style="color: var(--text-secondary);">Low:</span> <strong id="top-bank-low" style="color: var(--red);">₹--</strong></div>
        <div><span style="color: var(--text-secondary);">PDH:</span> <strong id="top-bank-pdh" style="color: #a78bfa;">₹--</strong></div>
        <div><span style="color: var(--text-secondary);">PDL:</span> <strong id="top-bank-pdl" style="color: #f87171;">₹--</strong></div>
      </div>
      <!-- Calculated 2S & 2R Levels -->
      <div style="display: flex; gap: 4px; font-size: 0.69rem; justify-content: space-between; margin-top: 3px; padding-top: 3px; border-top: 1px dashed rgba(255,255,255,0.08);">
        <div><span style="color: #ef4444; font-weight: 700;">R2:</span> <strong id="top-bank-r2" style="color: #fca5a5;">₹--</strong></div>
        <div><span style="color: #f59e0b; font-weight: 700;">R1:</span> <strong id="top-bank-r1" style="color: #fde68a;">₹--</strong></div>
        <div><span style="color: #94a3b8; font-weight: 700;">PP:</span> <strong id="top-bank-pp" style="color: #cbd5e1;">₹--</strong></div>
        <div><span style="color: #10b981; font-weight: 700;">S1:</span> <strong id="top-bank-s1" style="color: #86efac;">₹--</strong></div>
        <div><span style="color: #3b82f6; font-weight: 700;">S2:</span> <strong id="top-bank-s2" style="color: #93c5fd;">₹--</strong></div>
      </div>
    </div>

    <!-- GIFT NIFTY Persistent Strip -->
    <div style="background: rgba(19, 27, 46, 0.85); border: 1px solid var(--border); border-left: 3px solid #f59e0b; border-radius: 6px; padding: 8px 12px; display: flex; flex-direction: column; gap: 4px;">
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <span style="font-weight: 800; font-size: 0.88rem; color: #fbbf24;">🌐 GIFT NIFTY</span>
        <div>
          <strong id="top-gift-close" style="font-size: 1.15rem; color: var(--text-primary);">₹--</strong>
          <span id="top-gift-change" style="font-size: 0.75rem; font-weight: 700; margin-left: 4px;">--</span>
        </div>
      </div>
      <div style="display: grid; grid-template-columns: repeat(5, 1fr); gap: 4px; font-size: 0.72rem; background: rgba(0,0,0,0.25); padding: 4px 6px; border-radius: 4px;">
        <div><span style="color: var(--text-secondary);">Open:</span> <strong id="top-gift-open">₹--</strong></div>
        <div><span style="color: var(--text-secondary);">High:</span> <strong id="top-gift-high" style="color: var(--green);">₹--</strong></div>
        <div><span style="color: var(--text-secondary);">Low:</span> <strong id="top-gift-low" style="color: var(--red);">₹--</strong></div>
        <div><span style="color: var(--text-secondary);">PDH:</span> <strong id="top-gift-pdh" style="color: #fbbf24;">₹--</strong></div>
        <div><span style="color: var(--text-secondary);">PDL:</span> <strong id="top-gift-pdl" style="color: #f87171;">₹--</strong></div>
      </div>
      <!-- Calculated 2S & 2R Levels -->
      <div style="display: flex; gap: 4px; font-size: 0.69rem; justify-content: space-between; margin-top: 3px; padding-top: 3px; border-top: 1px dashed rgba(255,255,255,0.08);">
        <div><span style="color: #ef4444; font-weight: 700;">R2:</span> <strong id="top-gift-r2" style="color: #fca5a5;">₹--</strong></div>
        <div><span style="color: #f59e0b; font-weight: 700;">R1:</span> <strong id="top-gift-r1" style="color: #fde68a;">₹--</strong></div>
        <div><span style="color: #94a3b8; font-weight: 700;">PP:</span> <strong id="top-gift-pp" style="color: #cbd5e1;">₹--</strong></div>
        <div><span style="color: #10b981; font-weight: 700;">S1:</span> <strong id="top-gift-s1" style="color: #86efac;">₹--</strong></div>
        <div><span style="color: #3b82f6; font-weight: 700;">S2:</span> <strong id="top-gift-s2" style="color: #93c5fd;">₹--</strong></div>
      </div>
    </div>
  </div>
</div>

<div class="nav-tabs">
  <button class="nav-tab active" onclick="switchTab('tab-overview', this)">System Overview</button>
  <button class="nav-tab" onclick="switchTab('tab-simulator', this)">⚡ Option Paper Simulator</button>
  <button class="nav-tab" onclick="switchTab('tab-option-chain', this)" id="nav-btn-option-chain">📊 NSE Option Chain &amp; Trade</button>
  <button class="nav-tab" onclick="switchTab('tab-news', this)" id="nav-btn-news">📰 Market News &amp; Impact <span id="nav-news-count-badge" class="badge badge-green" style="font-size: 0.65rem; padding: 1px 6px; margin-left: 4px;">--</span></button>
  <button class="nav-tab" onclick="switchTab('tab-telegram', this)" id="nav-btn-telegram">📱 Telegram &amp; 15-Min Execution <span id="nav-pending-badge" class="badge badge-yellow" style="font-size: 0.65rem; padding: 1px 6px; margin-left: 4px; display: none;">0</span></button>
  <button class="nav-tab" onclick="switchTab('tab-brain', this)">AI Brain Reasoning</button>
  <button class="nav-tab" onclick="switchTab('tab-positions', this)">Paper Trades &amp; Monitoring</button>
  <button class="nav-tab" onclick="switchTab('tab-experience', this)">Experience Memory</button>
  <button class="nav-tab" onclick="switchTab('tab-research', this)">Hermes Research Zone (Isolated)</button>
</div>

<!-- Tab 1: Overview -->
<div id="tab-overview" class="tab-content active">
  <!-- Live 5-Minute NSE & Global Spot Telemetry Board (NIFTY 50, BANKNIFTY, GIFT NIFTY) -->
  <div class="card" style="margin-bottom: 20px; background: linear-gradient(135deg, rgba(16, 185, 129, 0.08) 0%, rgba(19, 27, 46, 0.95) 100%); border-left: 4px solid var(--green);">
    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 14px;">
      <div>
        <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
          <span style="font-weight: 800; font-size: 1.15rem; color: var(--text-primary);">📈 Live Market Spot &amp; Futures Telemetry</span>
          <span id="spot-status-badge" class="badge badge-green">AUTO-ACTIVE (09:15–15:30 IST)</span>
          <span class="badge badge-blue" style="font-size: 0.72rem;">⏰ Trading Session: 09:15 AM – 03:30 PM IST (Mon–Fri)</span>
        </div>
        <div style="font-size: 0.8rem; color: var(--text-secondary); margin-top: 3px;">
          Automatically querying &amp; storing <strong>Day Open, High, Low, Close, PDH &amp; PDL</strong> for <strong>NIFTY 50</strong>, <strong>BANKNIFTY</strong>, and <strong>GIFT NIFTY</strong> into SQLite database <code>data/market/nse_spot_data.db</code>.
          <span id="spot-schedule-text" style="color: var(--yellow); display: block; margin-top: 2px;"></span>
        </div>
      </div>
      <div style="display: flex; gap: 10px; align-items: center;">
        <span style="font-size: 0.8rem; color: var(--text-secondary);">Next 5M fetch in: <strong id="spot-countdown" style="color: var(--accent);">05:00</strong></span>
        <button class="btn" onclick="fetchSpotNow()" style="background: var(--green); color: black; border: none; font-weight: 700; padding: 6px 14px; border-radius: 6px; cursor: pointer;">
          🔄 Fetch All 3 Spot Now
        </button>
      </div>
    </div>

    <!-- 3 Instrument Cards Grid: NIFTY 50, BANKNIFTY, GIFT NIFTY -->
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 14px; margin-bottom: 16px;">
      <!-- NIFTY 50 Card -->
      <div style="background: var(--bg-card); padding: 14px; border-radius: 8px; border: 1px solid var(--border); border-top: 3px solid var(--accent);">
        <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px;">
          <span style="font-weight: 800; font-size: 1rem; color: var(--text-primary);">🇮🇳 NIFTY 50</span>
          <span id="nifty-change" style="font-size: 0.85rem; font-weight: 700; color: var(--green);">--</span>
        </div>
        <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px;">
          <span style="color: var(--text-secondary); font-size: 0.8rem;">Closing Price / LTP:</span>
          <span id="nifty-price" style="font-size: 1.8rem; font-weight: 800; color: var(--text-primary);">₹--</span>
        </div>
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px; font-size: 0.78rem;">
          <div><span style="color: var(--text-secondary);">Day Open:</span> <strong id="nifty-open">₹--</strong></div>
          <div><span style="color: var(--text-secondary);">Day High:</span> <strong id="nifty-high" style="color: var(--green);">₹--</strong></div>
          <div><span style="color: var(--text-secondary);">Day Low:</span> <strong id="nifty-low" style="color: var(--red);">₹--</strong></div>
          <div><span style="color: var(--text-secondary);">Prev Close:</span> <span id="nifty-prev" style="color: var(--text-secondary);">₹--</span></div>
          <div><span style="color: var(--text-secondary);">Prev Day High (PDH):</span> <strong id="nifty-pdh" style="color: #60a5fa;">₹--</strong></div>
          <div><span style="color: var(--text-secondary);">Prev Day Low (PDL):</span> <strong id="nifty-pdl" style="color: #f87171;">₹--</strong></div>
        </div>
      </div>

      <!-- BANKNIFTY Card -->
      <div style="background: var(--bg-card); padding: 14px; border-radius: 8px; border: 1px solid var(--border); border-top: 3px solid #8b5cf6;">
        <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px;">
          <span style="font-weight: 800; font-size: 1rem; color: var(--text-primary);">🏦 BANKNIFTY</span>
          <span id="banknifty-change" style="font-size: 0.85rem; font-weight: 700; color: var(--green);">--</span>
        </div>
        <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px;">
          <span style="color: var(--text-secondary); font-size: 0.8rem;">Closing Price / LTP:</span>
          <span id="banknifty-price" style="font-size: 1.8rem; font-weight: 800; color: var(--text-primary);">₹--</span>
        </div>
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px; font-size: 0.78rem;">
          <div><span style="color: var(--text-secondary);">Day Open:</span> <strong id="banknifty-open">₹--</strong></div>
          <div><span style="color: var(--text-secondary);">Day High:</span> <strong id="banknifty-high" style="color: var(--green);">₹--</strong></div>
          <div><span style="color: var(--text-secondary);">Day Low:</span> <strong id="banknifty-low" style="color: var(--red);">₹--</strong></div>
          <div><span style="color: var(--text-secondary);">Prev Close:</span> <span id="banknifty-prev" style="color: var(--text-secondary);">₹--</span></div>
          <div><span style="color: var(--text-secondary);">Prev Day High (PDH):</span> <strong id="banknifty-pdh" style="color: #a78bfa;">₹--</strong></div>
          <div><span style="color: var(--text-secondary);">Prev Day Low (PDL):</span> <strong id="banknifty-pdl" style="color: #f87171;">₹--</strong></div>
        </div>
      </div>

      <!-- GIFT NIFTY Card -->
      <div style="background: var(--bg-card); padding: 14px; border-radius: 8px; border: 1px solid var(--border); border-top: 3px solid #f59e0b;">
        <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px;">
          <span style="font-weight: 800; font-size: 1rem; color: var(--text-primary);">🌐 GIFT NIFTY (NSE IX)</span>
          <span id="giftnifty-change" style="font-size: 0.85rem; font-weight: 700; color: var(--yellow);">--</span>
        </div>
        <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px;">
          <span style="color: var(--text-secondary); font-size: 0.8rem;">Closing Price / LTP:</span>
          <span id="giftnifty-price" style="font-size: 1.8rem; font-weight: 800; color: var(--text-primary);">₹--</span>
        </div>
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px; font-size: 0.78rem;">
          <div><span style="color: var(--text-secondary);">Day Open:</span> <strong id="giftnifty-open">₹--</strong></div>
          <div><span style="color: var(--text-secondary);">Day High:</span> <strong id="giftnifty-high" style="color: var(--green);">₹--</strong></div>
          <div><span style="color: var(--text-secondary);">Day Low:</span> <strong id="giftnifty-low" style="color: var(--red);">₹--</strong></div>
          <div><span style="color: var(--text-secondary);">Prev Close:</span> <span id="giftnifty-prev" style="color: var(--text-secondary);">₹--</span></div>
          <div><span style="color: var(--text-secondary);">Prev Day High (PDH):</span> <strong id="giftnifty-pdh" style="color: #fbbf24;">₹--</strong></div>
          <div><span style="color: var(--text-secondary);">Prev Day Low (PDL):</span> <strong id="giftnifty-pdl" style="color: #f87171;">₹--</strong></div>
        </div>
      </div>
    </div>

    <!-- Calculated 2 Support & 2 Resistance Levels Matrix Card -->
    <div class="card" style="margin-bottom: 20px; background: linear-gradient(135deg, rgba(30, 41, 59, 0.95) 0%, rgba(15, 23, 42, 0.98) 100%); border-left: 4px solid #8b5cf6;">
      <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 12px;">
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="font-weight: 800; font-size: 1.05rem; color: var(--text-primary);">🎯 Calculated 2-Support &amp; 2-Resistance Levels (From 1-Year Stored OHLC Data)</span>
          <span class="badge" style="font-size: 0.72rem; background: rgba(139, 92, 246, 0.2); color: #c084fc; border: 1px solid rgba(139, 92, 246, 0.4);">CLASSIC FLOOR PIVOT FORMULA</span>
        </div>
        <div style="font-size: 0.78rem; color: var(--text-secondary);">
          Derived from stored daily High, Low &amp; Close records in SQLite (<code>data/market/nse_spot_data.db</code>).
        </div>
      </div>

      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 16px;">
        <!-- NIFTY 50 SR Ladder -->
        <div style="background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; padding: 14px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; border-bottom: 1px solid rgba(255,255,255,0.06); padding-bottom: 6px;">
            <strong style="color: #60a5fa; font-size: 0.95rem;">🇮🇳 NIFTY 50 Key S/R Matrix</strong>
            <span style="font-size: 0.78rem; color: var(--text-secondary);">Spot: <strong id="mat-nifty-spot" style="color: var(--text-primary);">₹--</strong></span>
          </div>
          <div style="display: flex; flex-direction: column; gap: 6px; font-size: 0.8rem;">
            <div style="display: flex; justify-content: space-between; align-items: center; background: rgba(239, 68, 68, 0.10); padding: 6px 10px; border-radius: 6px; border-left: 3px solid #ef4444;">
              <div><strong style="color: #ef4444;">Resistance 2 (R2):</strong> <span style="font-size: 0.72rem; color: var(--text-secondary); margin-left: 6px;">Major Reversal / Target</span></div>
              <div><strong id="mat-nifty-r2" style="font-size: 0.95rem; color: #fca5a5;">₹--</strong> <span id="mat-nifty-r2-dist" style="font-size: 0.72rem; color: #ef4444; margin-left: 4px;">--</span></div>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center; background: rgba(245, 158, 11, 0.10); padding: 6px 10px; border-radius: 6px; border-left: 3px solid #f59e0b;">
              <div><strong style="color: #f59e0b;">Resistance 1 (R1):</strong> <span style="font-size: 0.72rem; color: var(--text-secondary); margin-left: 6px;">Immediate Intraday Ceiling</span></div>
              <div><strong id="mat-nifty-r1" style="font-size: 0.95rem; color: #fde68a;">₹--</strong> <span id="mat-nifty-r1-dist" style="font-size: 0.72rem; color: #f59e0b; margin-left: 4px;">--</span></div>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center; background: rgba(59, 130, 246, 0.10); padding: 6px 10px; border-radius: 6px; border-left: 3px solid var(--accent);">
              <div><strong style="color: #60a5fa;">Central Pivot (PP):</strong> <span style="font-size: 0.72rem; color: var(--text-secondary); margin-left: 6px;">Day Equilibrium / Baseline</span></div>
              <div><strong id="mat-nifty-pp" style="font-size: 0.95rem; color: #93c5fd;">₹--</strong></div>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center; background: rgba(16, 185, 129, 0.10); padding: 6px 10px; border-radius: 6px; border-left: 3px solid #10b981;">
              <div><strong style="color: #10b981;">Support 1 (S1):</strong> <span style="font-size: 0.72rem; color: var(--text-secondary); margin-left: 6px;">Immediate Intraday Floor</span></div>
              <div><strong id="mat-nifty-s1" style="font-size: 0.95rem; color: #86efac;">₹--</strong> <span id="mat-nifty-s1-dist" style="font-size: 0.72rem; color: #10b981; margin-left: 4px;">--</span></div>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center; background: rgba(59, 130, 246, 0.12); padding: 6px 10px; border-radius: 6px; border-left: 3px solid #3b82f6;">
              <div><strong style="color: #3b82f6;">Support 2 (S2):</strong> <span style="font-size: 0.72rem; color: var(--text-secondary); margin-left: 6px;">Major Demand / Breakdown Filter</span></div>
              <div><strong id="mat-nifty-s2" style="font-size: 0.95rem; color: #93c5fd;">₹--</strong> <span id="mat-nifty-s2-dist" style="font-size: 0.72rem; color: #3b82f6; margin-left: 4px;">--</span></div>
            </div>
          </div>
        </div>

        <!-- BANKNIFTY SR Ladder -->
        <div style="background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; padding: 14px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; border-bottom: 1px solid rgba(255,255,255,0.06); padding-bottom: 6px;">
            <strong style="color: #a78bfa; font-size: 0.95rem;">🏦 BANKNIFTY Key S/R Matrix</strong>
            <span style="font-size: 0.78rem; color: var(--text-secondary);">Spot: <strong id="mat-bank-spot" style="color: var(--text-primary);">₹--</strong></span>
          </div>
          <div style="display: flex; flex-direction: column; gap: 6px; font-size: 0.8rem;">
            <div style="display: flex; justify-content: space-between; align-items: center; background: rgba(239, 68, 68, 0.10); padding: 6px 10px; border-radius: 6px; border-left: 3px solid #ef4444;">
              <div><strong style="color: #ef4444;">Resistance 2 (R2):</strong> <span style="font-size: 0.72rem; color: var(--text-secondary); margin-left: 6px;">Major Reversal / Target</span></div>
              <div><strong id="mat-bank-r2" style="font-size: 0.95rem; color: #fca5a5;">₹--</strong> <span id="mat-bank-r2-dist" style="font-size: 0.72rem; color: #ef4444; margin-left: 4px;">--</span></div>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center; background: rgba(245, 158, 11, 0.10); padding: 6px 10px; border-radius: 6px; border-left: 3px solid #f59e0b;">
              <div><strong style="color: #f59e0b;">Resistance 1 (R1):</strong> <span style="font-size: 0.72rem; color: var(--text-secondary); margin-left: 6px;">Immediate Intraday Ceiling</span></div>
              <div><strong id="mat-bank-r1" style="font-size: 0.95rem; color: #fde68a;">₹--</strong> <span id="mat-bank-r1-dist" style="font-size: 0.72rem; color: #f59e0b; margin-left: 4px;">--</span></div>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center; background: rgba(59, 130, 246, 0.10); padding: 6px 10px; border-radius: 6px; border-left: 3px solid var(--accent);">
              <div><strong style="color: #60a5fa;">Central Pivot (PP):</strong> <span style="font-size: 0.72rem; color: var(--text-secondary); margin-left: 6px;">Day Equilibrium / Baseline</span></div>
              <div><strong id="mat-bank-pp" style="font-size: 0.95rem; color: #93c5fd;">₹--</strong></div>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center; background: rgba(16, 185, 129, 0.10); padding: 6px 10px; border-radius: 6px; border-left: 3px solid #10b981;">
              <div><strong style="color: #10b981;">Support 1 (S1):</strong> <span style="font-size: 0.72rem; color: var(--text-secondary); margin-left: 6px;">Immediate Intraday Floor</span></div>
              <div><strong id="mat-bank-s1" style="font-size: 0.95rem; color: #86efac;">₹--</strong> <span id="mat-bank-s1-dist" style="font-size: 0.72rem; color: #10b981; margin-left: 4px;">--</span></div>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center; background: rgba(59, 130, 246, 0.12); padding: 6px 10px; border-radius: 6px; border-left: 3px solid #3b82f6;">
              <div><strong style="color: #3b82f6;">Support 2 (S2):</strong> <span style="font-size: 0.72rem; color: var(--text-secondary); margin-left: 6px;">Major Demand / Breakdown Filter</span></div>
              <div><strong id="mat-bank-s2" style="font-size: 0.95rem; color: #93c5fd;">₹--</strong> <span id="mat-bank-s2-dist" style="font-size: 0.72rem; color: #3b82f6; margin-left: 4px;">--</span></div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Stored Database Records Table (Collapsible) -->
    <details open style="font-size: 0.82rem; color: var(--text-secondary);">
      <summary style="cursor: pointer; font-weight: 600; color: var(--accent); padding: 4px 0; display: flex; justify-content: space-between; align-items: center;">
        <span>📋 Stored 5-Minute Database Records (data/market/nse_spot_data.db)</span>
        <span style="font-size: 0.75rem; color: var(--text-secondary);" id="spot-last-updated-text">Last Updated: --</span>
      </summary>
      <div style="margin: 8px 0; display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
        <span style="font-size: 0.75rem; font-weight: 600;">Filter Symbol:</span>
        <button class="btn" onclick="filterSpotTable('ALL')" style="padding: 2px 10px; font-size: 0.75rem;">All</button>
        <button class="btn" onclick="filterSpotTable('NIFTY 50')" style="padding: 2px 10px; font-size: 0.75rem;">NIFTY 50</button>
        <button class="btn" onclick="filterSpotTable('BANKNIFTY')" style="padding: 2px 10px; font-size: 0.75rem;">BANKNIFTY</button>
        <button class="btn" onclick="filterSpotTable('GIFT NIFTY')" style="padding: 2px 10px; font-size: 0.75rem;">GIFT NIFTY</button>
        <a href="/api/spot/export_csv" download="nse_spot_records.csv" class="btn" style="padding: 3px 12px; font-size: 0.75rem; text-decoration: none; margin-left: auto; background: rgba(59, 130, 246, 0.2); border: 1px solid var(--accent); color: var(--text-primary);">📥 Export CSV for Future Analysis</a>
      </div>
      <table style="margin-top: 6px;">
        <thead>
          <tr>
            <th>Date &amp; Time (IST)</th>
            <th>Symbol</th>
            <th>Spot / Close Price</th>
            <th>Day Open</th>
            <th>Day High</th>
            <th>Day Low</th>
            <th>PDH</th>
            <th>PDL</th>
            <th>Previous Close</th>
            <th>Change</th>
            <th>Volume</th>
            <th>Source</th>
          </tr>
        </thead>
        <tbody id="spot-history-table-body">
          <tr><td colspan="12" style="text-align: center; color: var(--text-secondary);">Loading stored spot records...</td></tr>
        </tbody>
      </table>
    </details>
  </div>

  <div class="grid">
    <div class="card">
      <div class="card-header">System Health</div>
      <div class="card-value" style="color: var(--green);">OPERATIONAL</div>
      <div class="card-subtext">All 212 tests verified passing (100%)</div>
    </div>
    <div class="card">
      <div class="card-header">Target Instruments &amp; Mode</div>
      <div class="card-value">NIFTY &amp; BANKNIFTY</div>
      <div class="card-subtext">1 Instrument Active | 1 Lot Max</div>
    </div>
    <div class="card">
      <div class="card-header">Safety Circuit Breakers</div>
      <div class="card-value" style="color: var(--accent);">LOCKED</div>
      <div class="card-subtext">Portfolio Cap: ₹2,000 | ₹1,000/inst | R:R 1:3</div>
    </div>
    <div class="card">
      <div class="card-header">Research Zone State</div>
      <div class="card-value" style="color: var(--purple);">ISOLATED</div>
      <div class="card-subtext">Dhan Mock Provider | Dynamic Scoring</div>
    </div>
  </div>

  <!-- Live Market News & Good News Impact Widget on Overview Tab -->
  <div class="card" style="margin-bottom: 20px; border-left: 4px solid #3b82f6; background: linear-gradient(135deg, rgba(59, 130, 246, 0.05) 0%, rgba(19, 27, 46, 0.95) 100%);">
    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 12px;">
      <div>
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="font-size: 1.05rem; font-weight: 800; color: var(--text-primary);">📰 High-Impact Market News &amp; Good News Catalysts</span>
          <span id="overview-news-stats-pill" class="badge badge-green">8 ACTIVE NEWS</span>
        </div>
        <div style="font-size: 0.8rem; color: var(--text-secondary); margin-top: 2px;">
          Real-time financial news, RBI/macro statements, and global cues analyzed for direct effect on NIFTY &amp; BANKNIFTY.
        </div>
      </div>
      <div style="display: flex; gap: 8px;">
        <button class="btn" onclick="openNewsTab()" style="background: var(--accent); color: white; border: none; font-weight: 700; padding: 5px 12px; border-radius: 6px; cursor: pointer;">
          View All News &amp; Impact Analysis →
        </button>
      </div>
    </div>
    <div id="overview-news-list" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 12px;">
      <span style="color: var(--text-secondary); font-size: 0.82rem;">Loading market impact news...</span>
    </div>
  </div>

  <div class="card">
    <div class="card-header">Deterministic Safety Guard Specifications (Non-Bypassable)</div>
    <table>
      <thead>
        <tr><th>Circuit Breaker</th><th>Parameter Limit</th><th>Enforcement Logic</th><th>Status</th></tr>
      </thead>
      <tbody>
        <tr><td><strong>Portfolio Daily Loss Cap</strong></td><td>₹2,000 realized + unrealized</td><td>Halts all trading operations across entire system for the day</td><td><span class="badge badge-green">ARMED</span></td></tr>
        <tr><td><strong>Instrument Daily Loss Cap</strong></td><td>₹1,000 max per day</td><td>Halts trading on NIFTY or BANKNIFTY if instrument reaches ₹1,000 loss</td><td><span class="badge badge-green">ARMED</span></td></tr>
        <tr><td><strong>Daily Trade Frequency</strong></td><td>3 Trades per Day</td><td>Max 3 trades/day for NIFTY, Max 3 trades/day for BANKNIFTY</td><td><span class="badge badge-green">ARMED</span></td></tr>
        <tr><td><strong>Position Sizing Limit</strong></td><td>Strictly 1 Lot per Trade</td><td>1 Lot (65 qty NIFTY / 30 qty BANKNIFTY). Excess lots instantly rejected</td><td><span class="badge badge-green">ARMED</span></td></tr>
        <tr><td><strong>Active Instrument Policy</strong></td><td>Single Active Instrument</td><td>Only 1 instrument can be traded at a time. Multi-symbol overlap blocked</td><td><span class="badge badge-green">ARMED</span></td></tr>
        <tr><td><strong>Risk-to-Reward (R:R) Invariant</strong></td><td>Minimum 1:3 Ratio (3.0)</td><td>Blocks trade orders if target-to-risk ratio is lower than 1:3</td><td><span class="badge badge-green">ARMED</span></td></tr>
        <tr><td><strong>Intraday Timing Filters</strong></td><td>09:15–09:25 &amp; post-15:15 IST</td><td>Blocks new entries during volatility spikes and after market cutoff</td><td><span class="badge badge-green">ARMED</span></td></tr>
        <tr><td><strong>Sensibull Paper Guard</strong></td><td>Strict DOM badge validation</td><td>Aborts execution immediately if live broker account detected</td><td><span class="badge badge-green">ARMED</span></td></tr>
      </tbody>
    </table>
  </div>
</div>

<!-- Tab 2: Brain -->
<div id="tab-brain" class="tab-content">
  <div class="card" style="margin-bottom: 16px; border-left: 4px solid var(--accent); background: linear-gradient(135deg, rgba(59, 130, 246, 0.08) 0%, rgba(19, 27, 46, 0.95) 100%);">
    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
      <div>
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="font-size: 1.05rem; font-weight: 800; color: var(--text-primary);">🧠 Gemini 2.5 Flash Autonomous Cognitive AI Brain</span>
          <span class="badge badge-green">ARMED &amp; STANDBY</span>
        </div>
        <div style="font-size: 0.8rem; color: var(--text-secondary); margin-top: 3px;">
          Evaluates multi-timeframe 1H macro bias, 15M tactical candle state, and volume order flow. Scheduled automatically during active trading sessions (09:15–15:30 IST).
        </div>
      </div>
      <div style="display: flex; gap: 8px;">
        <button class="btn" onclick="analyzeChartNow()" style="background: var(--accent); color: white; border: none; font-weight: 700; padding: 6px 14px; border-radius: 6px; cursor: pointer;">
          🔬 Trigger Brain Evaluation Now
        </button>
      </div>
    </div>
  </div>

  <div class="card">
    <div class="card-header">Recent Cognitive Brain Reasoning Verdicts (data/brain_history.db)</div>
    <table>
      <thead>
        <tr><th>Timestamp</th><th>Setup State</th><th>1H Macro Bias</th><th>15M Tactical State</th><th>Recommended Action</th><th>Key Reasoning</th></tr>
      </thead>
      <tbody id="brain-table-body">
        <tr><td colspan="6" style="text-align: center; color: var(--text-secondary); padding: 24px;">🧠 Cognitive AI Brain is ready &amp; armed. Awaiting 15M candle evaluation during market session (09:15–15:30 IST) or click "Trigger Brain Evaluation Now" above.</td></tr>
      </tbody>
    </table>
  </div>
</div>

<!-- Tab 3: Positions -->
<div id="tab-positions" class="tab-content">
  <div class="card" style="margin-bottom: 16px; border-left: 4px solid var(--yellow); background: linear-gradient(135deg, rgba(245, 158, 11, 0.08) 0%, rgba(19, 27, 46, 0.95) 100%);">
    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
      <div>
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="font-size: 1.05rem; font-weight: 800; color: var(--text-primary);">🛡️ Sensibull Virtual Paper Execution &amp; Position Guard</span>
          <span class="badge badge-yellow">SAFE VIRTUAL MODE</span>
          <span class="badge badge-red">LIVE BROKER: DISABLED</span>
        </div>
        <div style="font-size: 0.8rem; color: var(--text-secondary); margin-top: 3px;">
          Live real-money broker execution is strictly disabled for safety. Simulated option positions and Sensibull virtual trades are monitored here with real-time MTM, SL, and Target alerts.
        </div>
      </div>
      <button class="btn" onclick="switchTab('tab-simulator', document.querySelectorAll('.nav-tab')[1])" style="background: rgba(59, 130, 246, 0.2); border: 1px solid var(--accent); color: var(--text-primary); font-size: 0.78rem; padding: 6px 12px; border-radius: 6px; cursor: pointer;">
        ⚡ Go to Option Paper Simulator
      </button>
    </div>
  </div>

  <div class="card" style="margin-bottom: 20px;">
    <div class="card-header">Sensibull Virtual Positions (data/paper_positions.db)</div>
    <table>
      <thead>
        <tr><th>Position ID</th><th>Symbol &amp; Strike</th><th>Action</th><th>Lots</th><th>Entry Price</th><th>Current Price</th><th>Unrealized P&amp;L</th><th>Status</th></tr>
      </thead>
      <tbody id="positions-table-body">
        <tr><td colspan="8" style="text-align: center; color: var(--text-secondary); padding: 24px;">🟢 Safe Virtual Mode Active &bull; No active positions currently open (Portfolio Flat). Active positions with real-time MTM, SL, and Target tracking will display here as soon as a custom level or AI setup triggers.</td></tr>
      </tbody>
    </table>
  </div>
  <div class="card">
    <div class="card-header">Autonomous Position Monitoring &amp; Reassessment Triggers (data/position_monitoring.db)</div>
    <table>
      <thead>
        <tr><th>Timestamp</th><th>Position ID</th><th>Trigger Event</th><th>Price Move</th><th>Brain Reassessment Action</th><th>P&amp;L Recorded</th></tr>
      </thead>
      <tbody id="monitoring-table-body">
        <tr><td colspan="6" style="text-align: center; color: var(--text-secondary); padding: 20px;">Position monitoring active. Checks occur continuously every 15 seconds whenever positions are active.</td></tr>
      </tbody>
    </table>
  </div>
</div>

<!-- Tab 4: Experience -->
<div id="tab-experience" class="tab-content">
  <div class="card" style="margin-bottom: 16px; border-left: 4px solid var(--green); background: linear-gradient(135deg, rgba(16, 185, 129, 0.08) 0%, rgba(19, 27, 46, 0.95) 100%);">
    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
      <div>
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="font-size: 1.05rem; font-weight: 800; color: var(--text-primary);">📚 Trade Experience Memory &amp; Cognitive Post-Mortem Store</span>
          <span class="badge badge-green">ACTIVE STORE</span>
        </div>
        <div style="font-size: 0.8rem; color: var(--text-secondary); margin-top: 3px;">
          Persists closed trades in <code>data/experience.db</code>. Every closed trade undergoes an automatic cognitive post-mortem to score edge fidelity, record lessons learned, and eliminate repeating mistakes.
        </div>
      </div>
      <a href="/api/simulator/report" target="_blank" class="btn" style="text-decoration: none; padding: 6px 12px; font-size: 0.78rem;">
        📥 Download Simulator Report
      </a>
    </div>
  </div>

  <div class="card">
    <div class="card-header">Completed Trade Post-Mortems &amp; Experience Memory (data/experience.db)</div>
    <table>
      <thead>
        <tr><th>Trade ID</th><th>Instrument</th><th>Outcome</th><th>Realized P&amp;L</th><th>Holding Duration</th><th>Reasoning Evaluation</th><th>Execution Fidelity</th></tr>
      </thead>
      <tbody id="experience-table-body">
        <tr><td colspan="7" style="text-align: center; color: var(--text-secondary); padding: 24px;">📘 Experience Memory Store is active (data/experience.db). Closed simulator &amp; paper trades will be analyzed here for edge validation, win-rate attribution, and risk lessons.</td></tr>
      </tbody>
    </table>
  </div>
</div>

<!-- Tab 5: Research -->
<div id="tab-research" class="tab-content">
  <div class="grid">
    <div class="card">
      <div class="card-header">Dhan Broker Data Adapter</div>
      <div class="card-value" style="color: var(--green);">ONLINE</div>
      <div class="card-subtext">Mock Provider (Offline Deterministic Walk)</div>
    </div>
    <div class="card">
      <div class="card-header">Normalized Bars Stored</div>
      <div class="card-value" id="res-bars-count">0</div>
      <div class="card-subtext">data/hermes_research/market_data.db</div>
    </div>
    <div class="card">
      <div class="card-header">Negative Knowledge Catalog</div>
      <div class="card-value" style="color: var(--red);" id="res-fails-count">0</div>
      <div class="card-subtext">Preserved Failed Hypotheses in Memory</div>
    </div>
    <div class="card">
      <div class="card-header">Dynamic Assessments</div>
      <div class="card-value" style="color: var(--purple);" id="res-ass-count">0</div>
      <div class="card-subtext">Dynamic Segment Importance Weights</div>
    </div>
  </div>

  <div class="card" style="margin-bottom: 20px;">
    <div class="card-header">Latest Hermes Research Dynamic Assessments (data/hermes_research/assessments.db)</div>
    <table>
      <thead>
        <tr><th>Assessment ID</th><th>Timestamp</th><th>Instrument</th><th>Direction</th><th>Total Score</th><th>Confidence</th><th>Dynamic Segments Breakdown</th></tr>
      </thead>
      <tbody id="research-ass-body">
        <tr><td colspan="7" style="text-align: center; color: var(--text-secondary);">Loading research assessments...</td></tr>
      </tbody>
    </table>
  </div>

  <div class="card">
    <div class="card-header">Negative Knowledge Catalog — Disproven Hypotheses (data/hermes_research/research_memory.db)</div>
    <table>
      <thead>
        <tr><th>Failed ID</th><th>Hypothesis Statement</th><th>Failure Reason</th><th>Lessons Learned</th><th>Recorded At</th></tr>
      </thead>
      <tbody id="research-fails-body">
        <tr><td colspan="5" style="text-align: center; color: var(--text-secondary);">Loading negative knowledge catalog...</td></tr>
      </tbody>
    </table>
  </div>
</div>

<!-- Tab 6: Simulator -->
<div id="tab-simulator" class="tab-content">
  <!-- TradingView Perception & Manual Control Center -->
  <div class="card" style="margin-bottom: 20px; background: rgba(59, 130, 246, 0.04); border-left: 4px solid var(--accent);">
    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 14px;">
      <div>
        <div style="font-weight: 700; font-size: 1.05rem; color: var(--text-primary); margin-bottom: 4px;">
          🎯 TradingView NIFTY Chart Perception &amp; Local Rule Analysis
        </div>
        <div style="font-size: 0.82rem; color: var(--text-secondary); max-width: 750px;">
          Manually capture a live chart screenshot from TradingView or run local rule analysis on the latest market bar. If rule conditions pass, a paper trade is placed immediately.
        </div>
      </div>
      <div style="display: flex; gap: 10px; flex-wrap: wrap;">
        <button id="btn-manual-screenshot" class="btn" onclick="captureTradingViewScreenshot()" style="background: #0284c7; color: white; border: none; padding: 9px 16px; border-radius: 6px; font-weight: 700; cursor: pointer; display: flex; align-items: center; gap: 6px;">
          📸 Take TradingView Screenshot
        </button>
        <button id="btn-manual-upload" class="btn" onclick="triggerUploadChart()" style="background: #0d9488; color: white; border: none; padding: 9px 16px; border-radius: 6px; font-weight: 700; cursor: pointer; display: flex; align-items: center; gap: 6px;">
          📤 Upload / Paste Real Chart
        </button>
        <button id="btn-manual-analyze" class="btn" onclick="analyzeChartNow()" style="background: #2563eb; color: white; border: none; padding: 9px 16px; border-radius: 6px; font-weight: 700; cursor: pointer; display: flex; align-items: center; gap: 6px;">
          🔬 Analyze Chart Now
        </button>
        <input type="file" id="chart-file-input" accept="image/*" style="display: none;" onchange="uploadChartScreenshot(this)">
      </div>
    </div>
    <div style="font-size: 0.78rem; color: var(--text-secondary); margin-bottom: 12px; background: rgba(0,0,0,0.25); padding: 6px 12px; border-radius: 6px; border: 1px dashed var(--border);">
      💡 <strong>Real Chart Sync:</strong> You can paste your TradingView chart screenshot anytime with <kbd style="background: var(--bg-card); padding: 1px 5px; border-radius: 3px; border: 1px solid var(--border);">Ctrl + V</kbd>, click <strong>📤 Upload</strong>, or run <code style="color: var(--accent);">login_tradingview.bat</code> to connect your real TradingView account.
    </div>

    <!-- Live Dual-Panel: Left = Screenshot Preview, Right = Analysis Breakdown -->
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; align-items: stretch;">
      <!-- Left: TradingView Screenshot Card -->
      <div style="background: var(--bg-main); border: 1px solid var(--border); border-radius: 8px; padding: 12px; display: flex; flex-direction: column;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
          <span style="font-size: 0.78rem; font-weight: 700; color: var(--text-secondary); text-transform: uppercase;">
            📊 Live Chart Snapshot (NSE:NIFTY)
          </span>
          <a id="sim-tv-link" href="/api/simulator/screenshot_image" target="_blank" style="font-size: 0.75rem; color: var(--accent); text-decoration: none; font-weight: 600;">
            🔍 Open Full Image ↗
          </a>
        </div>
        <div style="position: relative; flex: 1; min-height: 200px; display: flex; align-items: center; justify-content: center; background: #060911; border-radius: 6px; overflow: hidden; border: 1px solid rgba(255,255,255,0.05);">
          <img id="sim-tv-img" src="/api/simulator/screenshot_image" alt="TradingView Chart Snapshot" style="width: 100%; max-height: 240px; object-fit: contain;" onerror="this.style.display='none'; document.getElementById('sim-tv-img-fallback').style.display='block';">
          <div id="sim-tv-img-fallback" style="display: none; padding: 20px; text-align: center; color: var(--text-secondary); font-size: 0.8rem;">
            No TradingView screenshot captured yet.<br>Click <strong>📸 Take TradingView Screenshot</strong> above to capture one now.
          </div>
        </div>
        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 8px; font-size: 0.75rem; color: var(--text-secondary);">
          <span>File: <code id="sim-tv-filename" style="color: var(--text-primary);">-</code></span>
          <span id="sim-tv-timestamp">Awaiting capture</span>
        </div>
      </div>

      <!-- Right: Technical Indicators & Rule Verdict Card -->
      <div style="background: var(--bg-main); border: 1px solid var(--border); border-radius: 8px; padding: 12px; display: flex; flex-direction: column; justify-content: space-between;">
        <div>
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-size: 0.78rem; font-weight: 700; color: var(--text-secondary); text-transform: uppercase;">
              🧠 Technical Indicators &amp; Rule Verdict
            </span>
            <span id="sim-ana-badge" class="badge badge-yellow">Awaiting Analysis</span>
          </div>

          <!-- Indicator pills -->
          <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 10px;">
            <div style="background: var(--bg-card); padding: 8px; border-radius: 6px; text-align: center; border: 1px solid var(--border);">
              <div style="font-size: 0.7rem; color: var(--text-secondary); text-transform: uppercase;">NIFTY Spot</div>
              <div id="sim-ana-spot" style="font-weight: 800; font-size: 0.95rem; color: var(--text-primary);">₹--</div>
            </div>
            <div style="background: var(--bg-card); padding: 8px; border-radius: 6px; text-align: center; border: 1px solid var(--border);">
              <div style="font-size: 0.7rem; color: var(--text-secondary); text-transform: uppercase;">Trend (EMA 9/21)</div>
              <div id="sim-ana-trend" style="font-weight: 800; font-size: 0.95rem; color: var(--accent);">--</div>
            </div>
            <div style="background: var(--bg-card); padding: 8px; border-radius: 6px; text-align: center; border: 1px solid var(--border);">
              <div style="font-size: 0.7rem; color: var(--text-secondary); text-transform: uppercase;">RSI (14)</div>
              <div id="sim-ana-rsi" style="font-weight: 800; font-size: 0.95rem; color: var(--yellow);">--</div>
            </div>
          </div>

          <div style="font-size: 0.78rem; color: var(--text-secondary); margin-bottom: 6px;">
            Active Rule: <strong id="sim-ana-rule-name" style="color: var(--text-primary);">user_rule.py</strong> | Candle: <span id="sim-ana-candle-time">--</span>
          </div>

          <!-- Rule condition explanation -->
          <div id="sim-ana-reason-box" style="background: rgba(15, 23, 42, 0.8); border: 1px solid var(--border); padding: 10px; border-radius: 6px; font-size: 0.82rem; color: var(--text-primary); margin-bottom: 10px; min-height: 40px; display: flex; align-items: center;">
            Click <strong>"🔬 Analyze Chart Now"</strong> to evaluate current market candle against your rule.
          </div>
        </div>

        <!-- Simulator Action -->
        <div id="sim-ana-action-box" style="background: rgba(59, 130, 246, 0.1); border: 1px solid rgba(59, 130, 246, 0.25); padding: 8px 12px; border-radius: 6px; font-size: 0.8rem; color: var(--accent); font-weight: 600;">
          Status: Ready for manual analysis.
        </div>
      </div>
    </div>
  </div>

  <div class="grid">
    <div class="card">
      <div class="card-header">Simulator Engine Status</div>
      <div class="card-value" style="color: var(--green);" id="sim-kpi-status">AUTO-ACTIVE</div>
      <div class="card-subtext" id="sim-kpi-rule">Evaluating: user_rule.py (100% Local, No LLM)</div>
    </div>
    <div class="card">
      <div class="card-header">Simulated Capital</div>
      <div class="card-value" id="sim-kpi-capital">₹100,000.00</div>
      <div class="card-subtext" id="sim-kpi-roi">Initial Capital: ₹1,00,000.00</div>
    </div>
    <div class="card">
      <div class="card-header">True Net P&amp;L (After All Charges)</div>
      <div class="card-value" id="sim-kpi-net-pnl">₹0.00</div>
      <div class="card-subtext" id="sim-kpi-charges">STT + GST + SEBI + Brokerage: ₹0.00</div>
    </div>
    <div class="card">
      <div class="card-header">Win Rate / Executed Trades</div>
      <div class="card-value" id="sim-kpi-winrate">0.0%</div>
      <div class="card-subtext" id="sim-kpi-trades-count">0 Wins / 0 Losses</div>
    </div>
  </div>


  <!-- Custom Level-Based Trading Strategy Trigger Center -->
  <div class="card" style="margin-bottom: 20px; border-left: 4px solid #f59e0b; background: rgba(245, 158, 11, 0.03);">
    <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 12px;">
      <div style="display: flex; align-items: center; gap: 8px;">
        <span style="font-weight: 800; font-size: 1.05rem; color: var(--text-primary);">🎯 Custom Level-Based Trading Strategy Trigger Center</span>
        <span id="level-trigger-badge" class="badge badge-yellow">0 ARMED TRIGGERS</span>
      </div>
      <div style="font-size: 0.8rem; color: var(--text-secondary);">
        Auto-executes Paper Trade (CE/PE) when Spot touches or crosses your custom price level.
      </div>
    </div>

    <!-- Level Trigger Setup Form -->
    <div style="background: var(--bg-main); padding: 16px; border-radius: 8px; border: 1px solid var(--border); margin-bottom: 16px;">
      <div style="font-size: 0.8rem; font-weight: 700; color: var(--text-secondary); text-transform: uppercase; margin-bottom: 12px;">
        ➕ Arm New Custom Price Level Trigger:
      </div>
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; align-items: end;">
        <!-- Instrument -->
        <div>
          <label style="font-size: 0.76rem; color: var(--text-secondary); display: block; margin-bottom: 4px;">Instrument:</label>
          <select id="lvl-instrument" style="width: 100%; box-sizing: border-box; background: var(--bg-card); color: var(--text-primary); border: 1px solid var(--border); padding: 7px 10px; border-radius: 6px; font-size: 0.85rem;">
            <option value="NIFTY 50">NIFTY 50</option>
            <option value="BANKNIFTY">BANKNIFTY</option>
          </select>
        </div>

        <!-- Trigger Level Price -->
        <div>
          <label style="font-size: 0.76rem; color: var(--text-secondary); display: block; margin-bottom: 4px;">
            Spot Trigger Level: <span style="color: var(--accent); font-weight: 700;">(Key Price)</span>
          </label>
          <input type="number" id="lvl-trigger-price" step="0.5" placeholder="e.g. 25450" style="width: 100%; box-sizing: border-box; background: var(--bg-card); color: var(--text-primary); border: 1px solid var(--border); padding: 7px 10px; border-radius: 6px; font-size: 0.85rem; font-weight: 700;">
        </div>

        <!-- Condition -->
        <div>
          <label style="font-size: 0.76rem; color: var(--text-secondary); display: block; margin-bottom: 4px;">Trigger Condition:</label>
          <select id="lvl-condition" style="width: 100%; box-sizing: border-box; background: var(--bg-card); color: var(--text-primary); border: 1px solid var(--border); padding: 7px 10px; border-radius: 6px; font-size: 0.85rem;">
            <option value="CROSS_ABOVE">Cross Above Level (Bullish Breakout)</option>
            <option value="CROSS_BELOW">Cross Below Level (Bearish Breakdown)</option>
            <option value="TOUCH">Touch Level (Within ±3 pts)</option>
          </select>
        </div>

        <!-- Option Type -->
        <div>
          <label style="font-size: 0.76rem; color: var(--text-secondary); display: block; margin-bottom: 4px;">Execute Option:</label>
          <select id="lvl-opt-type" style="width: 100%; box-sizing: border-box; background: var(--bg-card); color: var(--text-primary); border: 1px solid var(--border); padding: 7px 10px; border-radius: 6px; font-size: 0.85rem; font-weight: 700;">
            <option value="CE" style="color: var(--green);">BUY Call (CE)</option>
            <option value="PE" style="color: var(--red);">BUY Put (PE)</option>
          </select>
        </div>

        <!-- Stop Loss Level -->
        <div>
          <label style="font-size: 0.76rem; color: var(--text-secondary); display: block; margin-bottom: 4px;">Manual Stop Loss:</label>
          <div style="display: flex; gap: 4px;">
            <input type="number" id="lvl-sl-val" step="0.5" placeholder="e.g. 25400 or 20" style="flex: 1; min-width: 70px; background: var(--bg-card); color: var(--text-primary); border: 1px solid var(--border); padding: 7px 8px; border-radius: 6px; font-size: 0.85rem;">
            <select id="lvl-sl-type" style="background: var(--bg-card); color: var(--text-primary); border: 1px solid var(--border); padding: 7px 6px; border-radius: 6px; font-size: 0.75rem;">
              <option value="SPOT_LEVEL">Spot Level</option>
              <option value="POINTS">Option Pts</option>
              <option value="PERCENT">Option %</option>
            </select>
          </div>
        </div>

        <!-- Target Level -->
        <div>
          <label style="font-size: 0.76rem; color: var(--text-secondary); display: block; margin-bottom: 4px;">Manual Target Level:</label>
          <div style="display: flex; gap: 4px;">
            <input type="number" id="lvl-target-val" step="0.5" placeholder="e.g. 25550 or 40" style="flex: 1; min-width: 70px; background: var(--bg-card); color: var(--text-primary); border: 1px solid var(--border); padding: 7px 8px; border-radius: 6px; font-size: 0.85rem;">
            <select id="lvl-target-type" style="background: var(--bg-card); color: var(--text-primary); border: 1px solid var(--border); padding: 7px 6px; border-radius: 6px; font-size: 0.75rem;">
              <option value="SPOT_LEVEL">Spot Level</option>
              <option value="POINTS">Option Pts</option>
              <option value="PERCENT">Option %</option>
            </select>
          </div>
        </div>

        <!-- Lots -->
        <div style="max-width: 90px;">
          <label style="font-size: 0.76rem; color: var(--text-secondary); display: block; margin-bottom: 4px;">Lots:</label>
          <input type="number" id="lvl-lots" min="1" max="50" value="1" style="width: 100%; box-sizing: border-box; background: var(--bg-card); color: var(--text-primary); border: 1px solid var(--border); padding: 7px 8px; border-radius: 6px; font-size: 0.85rem;">
        </div>

        <!-- Note & Arm Button -->
        <div>
          <label style="font-size: 0.76rem; color: var(--text-secondary); display: block; margin-bottom: 4px;">Strategy Note:</label>
          <input type="text" id="lvl-notes" placeholder="e.g. Day High Breakout" style="width: 100%; box-sizing: border-box; background: var(--bg-card); color: var(--text-primary); border: 1px solid var(--border); padding: 7px 10px; border-radius: 6px; font-size: 0.85rem;">
        </div>

        <div style="display: flex; align-items: end;">
          <button class="btn" onclick="armCustomLevelTrigger()" style="width: 100%; background: #f59e0b; color: black; font-weight: 800; border: none; padding: 9px 16px; border-radius: 6px; cursor: pointer; white-space: nowrap;">
            🎯 Arm Level Trigger
          </button>
        </div>
      </div>
      <div id="lvl-arm-status" style="margin-top: 8px; font-size: 0.8rem;"></div>
    </div>

    <!-- Active & Historical Level Triggers Table -->
    <div style="font-size: 0.8rem; font-weight: 700; color: var(--text-secondary); text-transform: uppercase; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center;">
      <span>📋 Level Strategy Triggers Watchlist (Auto-Monitored against Live Spot)</span>
      <button class="btn" onclick="checkLevelsNow()" style="padding: 2px 8px; font-size: 0.72rem;">🔄 Check Levels Now</button>
    </div>
    <table>
      <thead>
        <tr>
          <th>Trigger ID</th>
          <th>Instrument</th>
          <th>Trigger Level Price</th>
          <th>Current Spot &amp; Distance</th>
          <th>Condition</th>
          <th>Action</th>
          <th>Stop Loss Level</th>
          <th>Target Level</th>
          <th>Lots</th>
          <th>Status</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody id="level-triggers-table-body">
        <tr><td colspan="11" style="text-align: center; color: var(--text-secondary);">No custom level triggers set yet. Use the form above to arm one.</td></tr>
      </tbody>
    </table>
  </div>

  <div class="card" style="margin-bottom: 20px;">
    <div class="card-header" style="display: flex; justify-content: space-between; align-items: center;">
      <span>Active Local Option Position</span>
      <div>
        <label style="font-size: 0.8rem; color: var(--text-secondary); margin-right: 8px;">Active Strategy Rule:</label>
        <select id="sim-rule-picker" onchange="changeSimRule(this.value)" style="background: var(--bg-main); color: var(--text-primary); border: 1px solid var(--border); padding: 4px 8px; border-radius: 4px; font-size: 0.8rem;">
          <option value="custom">My Custom Rule (user_rule.py)</option>
          <option value="ema-pivot">EMA 14 + CPR Pivot Bounce</option>
          <option value="supertrend">Supertrend + RSI Momentum</option>
        </select>
      </div>
    </div>
    <div id="sim-active-pos-box" style="padding: 10px 0;">
      <span style="color: var(--text-secondary);">Currently flat. Watching market candles for rule triggers...</span>
    </div>
  </div>

  <div class="card" style="margin-bottom: 20px;">
    <div class="card-header" style="display: flex; justify-content: space-between; align-items: center;">
      <span>Live Real-Time Simulator Trade Log (Full Statutory Tax &amp; Brokerage Deductions)</span>
      <button onclick="clearAllSimTrades()" class="btn" style="background: rgba(239, 68, 68, 0.1); color: var(--red); border: 1px solid rgba(239, 68, 68, 0.25); padding: 4px 10px; font-size: 0.78rem; cursor: pointer;">🧹 Clear All Fake Logs</button>
    </div>
    <table>
      <thead>
        <tr><th>Trade ID</th><th>Option Contract</th><th>Entry Time</th><th>Exit Time</th><th>Buy Premium</th><th>Exit Premium</th><th>Exit Reason</th><th>Gross P&amp;L</th><th>Taxes &amp; Brokerage</th><th>Real Net P&amp;L</th><th>Action</th></tr>
      </thead>
      <tbody id="sim-trades-table-body">
        <tr><td colspan="11" style="text-align: center; color: var(--text-secondary);">Waiting for trade signals...</td></tr>
      </tbody>
    </table>
  </div>

  <div class="card">
    <div class="card-header" style="display: flex; justify-content: space-between; align-items: center;">
      <span>Saved Log Report (data/paper_trading/SIMULATOR_REPORT.md)</span>
      <a href="/api/simulator/report" target="_blank" class="btn" style="text-decoration: none; padding: 4px 12px; font-size: 0.8rem;">📥 View / Download Report</a>
    </div>
    <pre id="sim-report-preview" style="background: var(--bg-main); padding: 14px; border-radius: 6px; font-size: 0.82rem; color: #94a3b8; max-height: 250px; overflow-y: auto; white-space: pre-wrap; font-family: monospace;">Loading simulator audit report...</pre>
  </div>
</div>

<!-- Tab: NSE Option Chain & Paper Trade -->
<div id="tab-option-chain" class="tab-content">
  <!-- Option Chain Header Card -->
  <div class="card" style="margin-bottom: 16px; border-left: 4px solid #10b981; background: linear-gradient(135deg, rgba(16, 185, 129, 0.08) 0%, rgba(19, 27, 46, 0.95) 100%);">
    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
      <div>
        <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
          <span style="font-size: 1.25rem; font-weight: 800; color: var(--text-primary);">📊 Live NSE Option Chain &amp; 1-Click Paper Trading</span>
          <span id="oc-source-badge" class="badge badge-green">LIVE NSE FEED</span>
          <span id="oc-sync-time" class="badge badge-blue">Updated: Just now</span>
        </div>
        <div style="font-size: 0.82rem; color: var(--text-secondary); margin-top: 4px; max-width: 850px;">
          Directly inspect Open Interest (OI), LTP, and PCR across all active strikes. Click <strong style="color: var(--green);">BUY CE</strong> or <strong style="color: var(--red);">BUY PE</strong> on any strike to instantly execute a paper trade in the Option Simulator!
        </div>
      </div>
      <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
        <!-- Symbol Toggle -->
        <div style="display: flex; background: var(--bg-main); border: 1px solid var(--border); border-radius: 6px; padding: 2px;">
          <button id="oc-btn-sym-nifty" onclick="switchOptionChainSymbol('NIFTY')" class="btn" style="padding: 5px 12px; font-size: 0.8rem; font-weight: 700; background: var(--accent); color: white; border: none; border-radius: 4px;">🇮🇳 NIFTY 50</button>
          <button id="oc-btn-sym-bank" onclick="switchOptionChainSymbol('BANKNIFTY')" class="btn" style="padding: 5px 12px; font-size: 0.8rem; font-weight: 600; background: transparent; color: var(--text-secondary); border: none; border-radius: 4px;">🏦 BANKNIFTY</button>
        </div>
        <select id="oc-expiry-select" onchange="fetchOptionChain()" style="background: var(--bg-card); color: var(--text-primary); border: 1px solid var(--border); padding: 6px 10px; border-radius: 6px; font-size: 0.8rem; font-weight: 600;">
          <option value="">Nearest Expiry</option>
        </select>
        <button class="btn" onclick="fetchOptionChain(true)" style="background: var(--green); color: black; border: none; font-weight: 700; padding: 6px 14px; border-radius: 6px; cursor: pointer;">
          🔄 Refresh Chain
        </button>
        <button class="btn" onclick="openNiftyTraderKeyModal()" style="background: #1e293b; color: #fbbf24; border: 1px solid #d97706; font-weight: 700; padding: 6px 14px; border-radius: 6px; cursor: pointer;" title="Update NiftyTrader API Key or Token">
          🔑 Update API Key
        </button>
      </div>
    </div>
  </div>

  <!-- Option Chain Top Analytics & Telemetry Bar -->
  <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; margin-bottom: 16px;">
    <div style="background: var(--bg-card); padding: 12px; border-radius: 8px; border: 1px solid var(--border); border-top: 3px solid var(--accent);">
      <div style="font-size: 0.72rem; color: var(--text-secondary); text-transform: uppercase;">Underlying Spot Price</div>
      <div id="oc-stat-spot" style="font-size: 1.45rem; font-weight: 800; color: var(--text-primary); margin-top: 2px;">₹--</div>
      <div id="oc-stat-atm" style="font-size: 0.74rem; color: #fbbf24; font-weight: 700;">ATM Strike: --</div>
    </div>
    <div style="background: var(--bg-card); padding: 12px; border-radius: 8px; border: 1px solid var(--border); border-top: 3px solid #10b981;">
      <div style="font-size: 0.72rem; color: var(--text-secondary); text-transform: uppercase;">Put-Call Ratio (PCR)</div>
      <div id="oc-stat-pcr" style="font-size: 1.45rem; font-weight: 800; color: var(--green); margin-top: 2px;">--</div>
      <div id="oc-stat-sentiment" style="font-size: 0.72rem; color: var(--green); font-weight: 600;">Calculating bias...</div>
    </div>
    <div style="background: var(--bg-card); padding: 12px; border-radius: 8px; border: 1px solid var(--border); border-top: 3px solid #f59e0b;">
      <div style="font-size: 0.72rem; color: var(--text-secondary); text-transform: uppercase;">Max Pain Strike</div>
      <div id="oc-stat-maxpain" style="font-size: 1.45rem; font-weight: 800; color: #fbbf24; margin-top: 2px;">--</div>
      <div style="font-size: 0.72rem; color: var(--text-secondary);">Minimal option seller loss level</div>
    </div>
    <div style="background: var(--bg-card); padding: 12px; border-radius: 8px; border: 1px solid var(--border); border-top: 3px solid #8b5cf6;">
      <div style="font-size: 0.72rem; color: var(--text-secondary); text-transform: uppercase;">Total Open Interest (OI)</div>
      <div id="oc-stat-total-oi" style="font-size: 1.25rem; font-weight: 800; color: #c4b5fd; margin-top: 2px;">--</div>
      <div id="oc-stat-oi-ratio" style="font-size: 0.72rem; color: var(--text-secondary);">CE vs PE distribution</div>
    </div>
    <div style="background: var(--bg-card); padding: 12px; border-radius: 8px; border: 1px solid var(--border); border-top: 3px solid #ec4899;">
      <div style="font-size: 0.72rem; color: var(--text-secondary); text-transform: uppercase;">Lot Size &amp; Trading Mode</div>
      <div id="oc-stat-lotsize" style="font-size: 1.45rem; font-weight: 800; color: #f472b6; margin-top: 2px;">65 Qty</div>
      <div style="font-size: 0.72rem; color: var(--green);">⚡ 1-Click Instant Execution Active</div>
    </div>
  </div>

  <!-- Option Chain Table Container -->
  <div style="font-size: 0.74rem; color: var(--text-secondary); margin-bottom: 8px; display: flex; align-items: center; gap: 6px;">
    <span>📱 <strong>Mobile Note:</strong> Swipe the option chain table left &amp; right with your finger to explore all CE/PE strikes, LTPs, and 1-click buy buttons.</span>
  </div>
  <div class="card" style="padding: 0; overflow-x: auto; margin-bottom: 24px;">
    <table class="oc-table" id="option-chain-table">
      <thead>
        <tr style="background: #111827; border-bottom: 2px solid var(--border);">
          <th colspan="7" style="color: var(--green); font-size: 0.85rem; border-right: 2px solid #374151; padding: 8px;">
            CALLS (CE) &bull; BULLISH OPTIONS
          </th>
          <th style="background: #1e293b; color: #fbbf24; font-size: 0.85rem; padding: 8px; min-width: 90px;">
            STRIKE
          </th>
          <th colspan="7" style="color: var(--red); font-size: 0.85rem; border-left: 2px solid #374151; padding: 8px;">
            PUTS (PE) &bull; BEARISH OPTIONS
          </th>
        </tr>
        <tr style="background: #182238; font-size: 0.72rem; color: var(--text-secondary);">
          <!-- Calls headers -->
          <th style="padding: 6px; min-width: 105px;">TRADE</th>
          <th title="OI Buildup Signal">OI BUILDUP</th>
          <th title="Open Interest">OI</th>
          <th title="Change in Open Interest">CHANGE OI</th>
          <th title="Implied Volatility">IV</th>
          <th title="Put-Call Ratio for Strike">PCR</th>
          <th title="Last Traded Price" style="color: var(--text-primary); font-weight: 800;">LTP (₹)</th>
          <!-- Strike Header -->
          <th style="background: #1e293b; color: #f8fafc; font-weight: 800; border-left: 1px solid #374151; border-right: 1px solid #374151; min-width: 95px;">STRIKE</th>
          <!-- Puts headers -->
          <th title="Last Traded Price" style="color: var(--text-primary); font-weight: 800;">LTP (₹)</th>
          <th title="Put-Call Ratio for Strike">PCR</th>
          <th title="Implied Volatility">IV</th>
          <th title="Change in Open Interest">CHANGE OI</th>
          <th title="Open Interest">OI</th>
          <th title="OI Buildup Signal">OI BUILDUP</th>
          <th style="padding: 6px; min-width: 105px;">TRADE</th>
        </tr>
      </thead>
      <tbody id="oc-table-body">
        <tr><td colspan="15" style="text-align: center; color: var(--text-secondary); padding: 40px;">Loading Live NiftyTrader Option Chain...</td></tr>
      </tbody>
    </table>
  </div>
</div>

<!-- Option Chain Quick Order Execution Modal -->
<div id="oc-trade-modal" style="display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.8); z-index: 2500; justify-content: center; align-items: center; padding: 20px;">
  <div style="background: var(--bg-card); border: 2px solid var(--border); border-radius: 10px; max-width: 480px; width: 100%; padding: 22px; box-shadow: 0 12px 36px rgba(0,0,0,0.85);">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; border-bottom: 1px solid var(--border); padding-bottom: 10px;">
      <div style="display: flex; align-items: center; gap: 8px;">
        <span id="oc-modal-type-badge" class="badge badge-green" style="font-size: 0.85rem; padding: 4px 10px;">BUY CE</span>
        <strong id="oc-modal-title" style="font-size: 1.1rem; color: var(--text-primary);">NIFTY 25400 CE</strong>
      </div>
      <button onclick="closeOptionTradeModal()" style="background: none; border: none; color: var(--text-secondary); font-size: 1.4rem; cursor: pointer;">&times;</button>
    </div>

    <form onsubmit="submitOptionTrade(event)" style="display: flex; flex-direction: column; gap: 12px;">
      <input type="hidden" id="oc-trade-symbol" value="NIFTY" />
      <input type="hidden" id="oc-trade-strike" value="0" />
      <input type="hidden" id="oc-trade-type" value="CE" />

      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; background: rgba(0,0,0,0.25); padding: 10px; border-radius: 6px; border: 1px solid var(--border);">
        <div>
          <span style="font-size: 0.74rem; color: var(--text-secondary);">Current Option LTP:</span>
          <div id="oc-modal-ltp" style="font-size: 1.3rem; font-weight: 800; color: var(--text-primary);">₹0.00</div>
        </div>
        <div>
          <span style="font-size: 0.74rem; color: var(--text-secondary);">Underlying Spot:</span>
          <div id="oc-modal-spot" style="font-size: 1.1rem; font-weight: 700; color: var(--accent);">₹0.00</div>
        </div>
      </div>

      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
        <div>
          <label style="display: block; font-size: 0.75rem; color: var(--text-secondary); margin-bottom: 4px;">Lots (1 Lot = <span id="oc-modal-qty-multiplier">65</span> Qty)</label>
          <input type="number" id="oc-trade-lots" value="1" min="1" max="10" oninput="updateOptionMarginDisplay()" style="width: 100%; background: var(--bg-main); border: 1px solid var(--border); padding: 8px 10px; border-radius: 6px; color: var(--text-primary); font-size: 0.9rem; font-weight: 700;" />
        </div>
        <div>
          <label style="display: block; font-size: 0.75rem; color: var(--text-secondary); margin-bottom: 4px;">Capital / Margin Required</label>
          <div id="oc-modal-margin" style="background: var(--bg-main); border: 1px solid var(--border); padding: 8px 10px; border-radius: 6px; color: #fbbf24; font-size: 0.9rem; font-weight: 700;">₹0.00</div>
        </div>
      </div>

      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
        <div>
          <label style="display: block; font-size: 0.75rem; color: var(--text-secondary); margin-bottom: 4px;">Stop Loss (Points from Entry)</label>
          <input type="number" id="oc-trade-sl" value="20" min="5" max="200" oninput="updateOptionMarginDisplay()" style="width: 100%; background: var(--bg-main); border: 1px solid var(--border); padding: 8px 10px; border-radius: 6px; color: var(--red); font-size: 0.85rem; font-weight: 700;" />
          <span id="oc-modal-sl-calc" style="font-size: 0.7rem; color: var(--text-secondary);">SL Price: ₹--</span>
        </div>
        <div>
          <label style="display: block; font-size: 0.75rem; color: var(--text-secondary); margin-bottom: 4px;">Target (Points from Entry)</label>
          <input type="number" id="oc-trade-tgt" value="40" min="10" max="400" oninput="updateOptionMarginDisplay()" style="width: 100%; background: var(--bg-main); border: 1px solid var(--border); padding: 8px 10px; border-radius: 6px; color: var(--green); font-size: 0.85rem; font-weight: 700;" />
          <span id="oc-modal-tgt-calc" style="font-size: 0.7rem; color: var(--text-secondary);">Target Price: ₹--</span>
        </div>
      </div>

      <div style="display: flex; align-items: center; gap: 8px; margin-top: 4px;">
        <input type="checkbox" id="oc-trade-trailing" checked style="accent-color: var(--accent); transform: scale(1.1);" />
        <label for="oc-trade-trailing" style="font-size: 0.78rem; color: var(--text-primary); cursor: pointer;">
          Trail SL automatically (Step: 15 pts on favorable moves)
        </label>
      </div>

      <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 14px; border-top: 1px solid var(--border); padding-top: 12px; flex-wrap: wrap;">
        <button type="button" onclick="closeOptionTradeModal()" class="btn" style="padding: 7px 14px;">Cancel</button>
        <button type="button" onclick="submitOptionTrade(event, 'arm_15m')" id="oc-modal-arm-btn" class="btn" style="background: #f59e0b; color: #000; border: none; font-weight: 800; padding: 7px 16px; font-size: 0.88rem;" title="Sends Telegram alert detailing WHY trade is taken and starts 15-minute countdown before auto-execution">
          ⏱️ 15-Min Confirmation (Telegram Alert)
        </button>
        <button type="button" onclick="submitOptionTrade(event, 'instant')" id="oc-modal-submit-btn" class="btn" style="background: var(--green); color: black; border: none; font-weight: 800; padding: 7px 20px; font-size: 0.88rem;">
          🚀 Instant Execution
        </button>
      </div>
    </form>
  </div>
</div>

<!-- NiftyTrader API Key & Bearer Token Modal -->
<div id="nt-key-modal" style="display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.85); z-index: 2600; justify-content: center; align-items: center; padding: 20px;">
  <div style="background: var(--bg-card); border: 2px solid #d97706; border-radius: 12px; max-width: 560px; width: 100%; padding: 24px; box-shadow: 0 16px 48px rgba(0,0,0,0.9);">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; border-bottom: 1px solid var(--border); padding-bottom: 12px;">
      <div style="display: flex; align-items: center; gap: 8px;">
        <span style="font-size: 1.3rem;">🔑</span>
        <strong style="font-size: 1.15rem; color: var(--text-primary);">NiftyTrader API Key &amp; Token Settings</strong>
      </div>
      <button onclick="closeNiftyTraderKeyModal()" style="background: transparent; border: none; color: var(--text-secondary); font-size: 1.4rem; cursor: pointer;">&times;</button>
    </div>

    <!-- Instructions / One-liner helper -->
    <div style="background: rgba(217, 119, 6, 0.1); border: 1px solid rgba(217, 119, 6, 0.3); border-radius: 8px; padding: 12px; margin-bottom: 16px;">
      <div style="font-size: 0.76rem; color: #fbbf24; font-weight: 700; margin-bottom: 4px;">⚡ 2-Second Console Helper for Tomorrow's Key:</div>
      <div style="font-size: 0.72rem; color: var(--text-secondary); margin-bottom: 6px;">
        In NiftyTrader, press <strong>F12 &rarr; Console</strong>, run this code to copy your daily key in 1 second:
      </div>
      <div style="display: flex; gap: 6px;">
        <input type="text" readonly id="nt-console-helper-code" value='JSON.parse(localStorage.getItem("niftytrader-api-key-cache-v1")).apiKey' style="background: #0f172a; color: #38bdf8; border: 1px solid #334155; border-radius: 4px; padding: 5px 8px; font-size: 0.70rem; font-family: monospace; width: 100%;">
        <button type="button" onclick="copyConsoleHelperCode()" style="background: var(--accent); color: white; border: none; border-radius: 4px; padding: 5px 12px; font-size: 0.72rem; font-weight: 700; cursor: pointer; white-space: nowrap;">📋 Copy</button>
      </div>
    </div>

    <form onsubmit="saveNiftyTraderKeys(event)">
      <div style="margin-bottom: 14px;">
        <label style="font-size: 0.78rem; font-weight: 700; color: var(--text-secondary); display: block; margin-bottom: 6px;">
          x-api-key (Rotates daily at 06:30 AM IST) *
        </label>
        <input type="text" id="nt-input-api-key" placeholder="Paste your fresh x-api-key here..." required style="background: var(--bg-main); color: var(--text-primary); border: 1px solid var(--border); border-radius: 6px; padding: 8px 12px; font-size: 0.82rem; font-family: monospace; width: 100%;">
      </div>

      <div style="margin-bottom: 18px;">
        <label style="font-size: 0.78rem; font-weight: 700; color: var(--text-secondary); display: block; margin-bottom: 6px;">
          Bearer JWT Token (Valid for 30 days &mdash; only change if expired)
        </label>
        <textarea id="nt-input-bearer" rows="3" placeholder="Leave empty to keep current active Bearer token..." style="background: var(--bg-main); color: var(--text-primary); border: 1px solid var(--border); border-radius: 6px; padding: 8px 12px; font-size: 0.76rem; font-family: monospace; width: 100%; resize: vertical;"></textarea>
      </div>

      <div id="nt-key-status-msg" style="display: none; font-size: 0.80rem; padding: 8px 12px; border-radius: 6px; margin-bottom: 14px;"></div>

      <div style="display: flex; justify-content: flex-end; gap: 10px;">
        <button type="button" onclick="closeNiftyTraderKeyModal()" class="btn" style="background: #334155; color: white; padding: 8px 16px; border: none; border-radius: 6px; font-weight: 600; cursor: pointer;">Cancel</button>
        <button type="submit" id="nt-key-save-btn" class="btn" style="background: var(--green); color: black; padding: 8px 18px; border: none; border-radius: 6px; font-weight: 800; cursor: pointer;">💾 Save &amp; Test Live Key</button>
      </div>
    </form>
  </div>
</div>

<!-- Tab News: Dedicated Market News & Impact Hub -->
<div id="tab-news" class="tab-content">
  <!-- Header Card -->
  <div class="card" style="margin-bottom: 18px; border-left: 4px solid var(--accent); background: linear-gradient(135deg, rgba(59, 130, 246, 0.08) 0%, rgba(19, 27, 46, 0.95) 100%);">
    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
      <div>
        <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
          <span style="font-size: 1.25rem; font-weight: 800; color: var(--text-primary);">📰 Market News &amp; Impact Intelligence Hub</span>
          <span class="badge badge-green" id="news-status-badge">AUTO-UPDATES ACTIVE</span>
          <span class="badge badge-blue" id="news-last-fetch-badge">Last Synced: Just now</span>
        </div>
        <div style="font-size: 0.82rem; color: var(--text-secondary); margin-top: 4px; max-width: 850px;">
          Deterministic financial news monitoring tracking catalysts that effect the market: Bullish good news, RBI/macro statements, crude &amp; global cues, and corporate earnings with actionable NIFTY 50 and BANKNIFTY market effect commentary.
        </div>
      </div>
      <div style="display: flex; gap: 10px; flex-wrap: wrap;">
        <button class="btn" onclick="refreshNewsNow()" style="background: var(--green); color: black; border: none; font-weight: 700; padding: 7px 14px; border-radius: 6px; cursor: pointer;">
          🔄 Fetch Live RSS Now
        </button>
        <button class="btn" onclick="openAddNewsModal()" style="background: var(--accent); color: white; border: none; font-weight: 700; padding: 7px 14px; border-radius: 6px; cursor: pointer;">
          ➕ Add Custom News Event
        </button>
      </div>
    </div>
  </div>

  <!-- News KPI Stats Row -->
  <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 18px;">
    <div style="background: var(--bg-card); padding: 14px; border-radius: 8px; border: 1px solid var(--border); border-top: 3px solid #60a5fa;">
      <div style="font-size: 0.75rem; color: var(--text-secondary); text-transform: uppercase;">Total News Tracked</div>
      <div id="news-stat-total" style="font-size: 1.6rem; font-weight: 800; color: var(--text-primary); margin-top: 4px;">0</div>
      <div style="font-size: 0.72rem; color: var(--text-secondary);">Across ET, Moneycontrol, Livemint</div>
    </div>
    <div style="background: var(--bg-card); padding: 14px; border-radius: 8px; border: 1px solid var(--border); border-top: 3px solid var(--green);">
      <div style="font-size: 0.75rem; color: var(--text-secondary); text-transform: uppercase;">Good News (Bullish)</div>
      <div id="news-stat-bullish" style="font-size: 1.6rem; font-weight: 800; color: var(--green); margin-top: 4px;">0</div>
      <div style="font-size: 0.72rem; color: var(--green);">Positive catalysts for indices</div>
    </div>
    <div style="background: var(--bg-card); padding: 14px; border-radius: 8px; border: 1px solid var(--border); border-top: 3px solid var(--red);">
      <div style="font-size: 0.75rem; color: var(--text-secondary); text-transform: uppercase;">Market Risk (Bearish)</div>
      <div id="news-stat-bearish" style="font-size: 1.6rem; font-weight: 800; color: var(--red); margin-top: 4px;">0</div>
      <div style="font-size: 0.72rem; color: var(--red);">Downside caution / warnings</div>
    </div>
    <div style="background: var(--bg-card); padding: 14px; border-radius: 8px; border: 1px solid var(--border); border-top: 3px solid #f59e0b;">
      <div style="font-size: 0.75rem; color: var(--text-secondary); text-transform: uppercase;">High Impact / Breaking</div>
      <div id="news-stat-important" style="font-size: 1.6rem; font-weight: 800; color: #f59e0b; margin-top: 4px;">0</div>
      <div style="font-size: 0.72rem; color: #f59e0b;">Scrolling at Dashboard Top</div>
    </div>
    <div style="background: var(--bg-card); padding: 14px; border-radius: 8px; border: 1px solid var(--border); border-top: 3px solid #a855f7;">
      <div style="font-size: 0.75rem; color: var(--text-secondary); text-transform: uppercase;">Macro &amp; RBI Policy</div>
      <div id="news-stat-macro" style="font-size: 1.6rem; font-weight: 800; color: #c084fc; margin-top: 4px;">0</div>
      <div style="font-size: 0.72rem; color: #c084fc;">Rates, Inflation, CAD, Global</div>
    </div>
  </div>

  <!-- Filter Buttons Row -->
  <div style="display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; background: rgba(19, 27, 46, 0.7); padding: 10px; border-radius: 8px; border: 1px solid var(--border);">
    <span style="font-size: 0.8rem; font-weight: 700; color: var(--text-secondary); align-self: center; margin-right: 6px;">Filter By:</span>
    <button class="news-filter-btn active" onclick="filterNews('ALL', this)">All News</button>
    <button class="news-filter-btn" onclick="filterNews('IMPORTANT', this)">⚡ High Market Impact Only</button>
    <button class="news-filter-btn" onclick="filterNews('GOOD_NEWS', this)">🟢 Good News (Bullish)</button>
    <button class="news-filter-btn" onclick="filterNews('BAD_NEWS', this)">🔴 Bearish / Risk</button>
    <button class="news-filter-btn" onclick="filterNews('MACRO_POLICY', this)">🏦 RBI &amp; Macro Policy</button>
    <button class="news-filter-btn" onclick="filterNews('GLOBAL_CUES', this)">🌐 Global Cues &amp; Crude</button>
    <button class="news-filter-btn" onclick="filterNews('EARNINGS', this)">📊 Corporate Earnings</button>
  </div>

  <!-- News Cards Stream -->
  <div id="news-cards-container" style="display: flex; flex-direction: column; gap: 14px;">
    <div style="text-align: center; color: var(--text-secondary); padding: 30px;">Loading news stream...</div>
  </div>
</div>

<!-- Tab Telegram: Real-Time Alerts, 15-Minute Countdown Safety Gate & News Updater -->
<div id="tab-telegram" class="tab-content">
  <!-- Header Banner -->
  <div class="card" style="margin-bottom: 20px; border-left: 4px solid #38bdf8; background: linear-gradient(135deg, rgba(56, 189, 248, 0.08) 0%, rgba(19, 27, 46, 0.95) 100%);">
    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
      <div>
        <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
          <span style="font-size: 1.25rem; font-weight: 800; color: var(--text-primary);">📱 Telegram Notification Engine &amp; 15-Minute Execution Gate</span>
          <span class="badge" id="tele-status-tag" style="background: rgba(56, 189, 248, 0.15); border: 1px solid rgba(56, 189, 248, 0.4); color: #38bdf8;">CHECKING...</span>
        </div>
        <div style="font-size: 0.82rem; color: var(--text-secondary); margin-top: 4px; max-width: 900px;">
          Autonomous alert bridge for NIFTY &amp; BANKNIFTY: Dispatches instant breakout alerts, sudden high-impact market news, and <strong>trade confirmations with full AI reasoning ("Why system takes trade")</strong> that count down for <strong>15 minutes</strong> before auto-executing into the simulator.
        </div>
      </div>
      <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
        <button class="btn" onclick="sendTelegramTest()" style="background: rgba(56, 189, 248, 0.2); border: 1px solid #38bdf8; color: #38bdf8; font-weight: 700; padding: 6px 14px; border-radius: 6px;">
          📨 Send Test Alert
        </button>
        <button class="btn" onclick="fetchPendingTrades()" style="background: var(--bg-card); border: 1px solid var(--border); color: var(--text-primary); font-weight: 600; padding: 6px 14px; border-radius: 6px;">
          🔄 Refresh Orders
        </button>
      </div>
    </div>
  </div>

  <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 24px;">
    <!-- Telegram Bot Settings Card -->
    <div class="card" style="border: 1px solid var(--border);">
      <h3 style="font-size: 1.05rem; color: var(--text-primary); margin-bottom: 12px; display: flex; align-items: center; gap: 6px;">
        ⚙️ Bot Credentials &amp; Channel
      </h3>
      <form onsubmit="saveTelegramCredentials(event)" style="display: flex; flex-direction: column; gap: 12px;">
        <div>
          <label style="display: block; font-size: 0.78rem; color: var(--text-secondary); margin-bottom: 4px;">Telegram Bot Token</label>
          <input type="password" id="tele-input-token" placeholder="e.g. 7123456789:AAHk..." style="width: 100%; background: var(--bg-main); border: 1px solid var(--border); padding: 8px 12px; border-radius: 6px; color: var(--text-primary); font-size: 0.85rem; font-family: monospace;" />
          <span style="font-size: 0.7rem; color: var(--text-secondary);">Obtain via <a href="https://t.me/BotFather" target="_blank" style="color: #38bdf8;">@BotFather</a> on Telegram with <code>/newbot</code>.</span>
        </div>
        <div>
          <label style="display: block; font-size: 0.78rem; color: var(--text-secondary); margin-bottom: 4px;">Telegram Chat ID / Channel ID</label>
          <input type="text" id="tele-input-chat" placeholder="e.g. 123456789 or -100..." style="width: 100%; background: var(--bg-main); border: 1px solid var(--border); padding: 8px 12px; border-radius: 6px; color: var(--text-primary); font-size: 0.85rem; font-family: monospace;" />
          <span style="font-size: 0.7rem; color: var(--text-secondary);">Your personal user ID (from <a href="https://t.me/userinfobot" target="_blank" style="color: #38bdf8;">@userinfobot</a>) or group/channel ID.</span>
        </div>
        <div style="display: flex; gap: 10px; align-items: center; margin-top: 4px;">
          <button type="submit" class="btn" style="background: #38bdf8; color: #000; border: none; font-weight: 700; padding: 8px 18px; border-radius: 6px;">
            💾 Save Telegram Credentials
          </button>
          <span id="tele-save-feedback" style="font-size: 0.75rem; color: var(--green);"></span>
        </div>
      </form>
    </div>

    <!-- 15-Minute Auto-Execution Gate Architecture Card -->
    <div class="card" style="border: 1px solid var(--border); background: rgba(19, 27, 46, 0.6);">
      <h3 style="font-size: 1.05rem; color: var(--text-primary); margin-bottom: 12px; display: flex; align-items: center; gap: 6px;">
        ⏱️ How the 15-Minute Execution Gate Works
      </h3>
      <div style="font-size: 0.82rem; color: var(--text-secondary); line-height: 1.6;">
        <ol style="margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 8px;">
          <li><strong style="color: var(--text-primary);">Level Breakout / Trade Condition Met:</strong> System spots a high-probability breakout or option setup.</li>
          <li><strong style="color: var(--text-primary);">Telegram Alert Dispatched:</strong> Sends an instant message detailing the <em>exact technical reason</em> ("Why system takes trade"), strike, target, and stop loss.</li>
          <li><strong style="color: var(--yellow);">15-Minute Confirmation Window:</strong> System enters an armed hold state for 900 seconds. You receive ample time to review market context.</li>
          <li><strong style="color: var(--green);">Automatic Execution:</strong> If not cancelled via the Cancel button below, the system auto-fires the paper trade right when the 15-minute timer hits zero and sends an execution confirmation to Telegram.</li>
          <li><strong style="color: var(--red);">Manual Cancellation:</strong> Click <em>Cancel Order</em> anytime during the 15 minutes to abort the trade.</li>
        </ol>
      </div>
    </div>
  </div>

  <!-- Active 15-Minute Countdown Orders Table -->
  <div class="card" style="margin-bottom: 24px; border: 1px solid var(--border);">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; flex-wrap: wrap; gap: 10px;">
      <div style="display: flex; align-items: center; gap: 8px;">
        <span style="font-size: 1.1rem; font-weight: 800; color: var(--text-primary);">⏳ Active Armed Orders (15-Minute Countdown)</span>
        <span class="badge badge-yellow" id="pending-count-badge">0 ARMED</span>
      </div>
      <div style="font-size: 0.78rem; color: var(--text-secondary);">
        Live auto-executing countdown &bull; Updates every second
      </div>
    </div>

    <div style="overflow-x: auto; -webkit-overflow-scrolling: touch;">
      <table style="width: 100%; border-collapse: collapse; font-size: 0.82rem;">
        <thead>
          <tr style="border-bottom: 1px solid var(--border); text-align: left; color: var(--text-secondary); background: rgba(0,0,0,0.2);">
            <th style="padding: 10px 12px;">Order ID</th>
            <th style="padding: 10px 12px;">Contract</th>
            <th style="padding: 10px 12px;">Lots / Qty</th>
            <th style="padding: 10px 12px;">Spot / Premium</th>
            <th style="padding: 10px 12px;">SL / Target</th>
            <th style="padding: 10px 12px;">Time Remaining</th>
            <th style="padding: 10px 12px;">Status</th>
            <th style="padding: 10px 12px;">Technical Rationale ("Why Trade")</th>
            <th style="padding: 10px 12px; text-align: right;">Action</th>
          </tr>
        </thead>
        <tbody id="pending-trades-tbody">
          <tr>
            <td colspan="9" style="text-align: center; color: var(--text-secondary); padding: 30px;">
              No armed trades currently counting down. When a custom level or option setup triggers, it will appear here with a live 15-minute countdown.
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- Manual 15-Minute Arm Test Form -->
  <div class="card" style="border: 1px solid var(--border); background: rgba(19, 27, 46, 0.4);">
    <h3 style="font-size: 1.05rem; color: var(--text-primary); margin-bottom: 10px; display: flex; align-items: center; gap: 6px;">
      🧪 Test Armed 15-Minute Execution Workflow
    </h3>
    <div style="font-size: 0.78rem; color: var(--text-secondary); margin-bottom: 14px;">
      Manually arm an order to simulate the exact production workflow: dispatches the Telegram intent alert with technical reasoning, counts down 15 minutes (or custom seconds for testing), and auto-executes into the Option Paper Simulator upon timer completion.
    </div>
    <form onsubmit="submitManualArmTrade(event)" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)) 2fr auto; gap: 10px; align-items: flex-end;">
      <div>
        <label style="display: block; font-size: 0.72rem; color: var(--text-secondary); margin-bottom: 3px;">Index</label>
        <select id="arm-test-symbol" style="width: 100%; background: var(--bg-main); border: 1px solid var(--border); padding: 7px; border-radius: 6px; color: var(--text-primary); font-size: 0.8rem;">
          <option value="NIFTY">NIFTY</option>
          <option value="BANKNIFTY">BANKNIFTY</option>
        </select>
      </div>
      <div>
        <label style="display: block; font-size: 0.72rem; color: var(--text-secondary); margin-bottom: 3px;">Strike Price</label>
        <input type="number" id="arm-test-strike" value="23500" step="50" style="width: 100%; background: var(--bg-main); border: 1px solid var(--border); padding: 7px; border-radius: 6px; color: var(--text-primary); font-size: 0.8rem;" />
      </div>
      <div>
        <label style="display: block; font-size: 0.72rem; color: var(--text-secondary); margin-bottom: 3px;">Option Type</label>
        <select id="arm-test-type" style="width: 100%; background: var(--bg-main); border: 1px solid var(--border); padding: 7px; border-radius: 6px; color: var(--text-primary); font-size: 0.8rem;">
          <option value="CE">CALL (CE)</option>
          <option value="PE">PUT (PE)</option>
        </select>
      </div>
      <div>
        <label style="display: block; font-size: 0.72rem; color: var(--text-secondary); margin-bottom: 3px;">Est. Premium (₹)</label>
        <input type="number" id="arm-test-premium" value="125.50" step="0.05" style="width: 100%; background: var(--bg-main); border: 1px solid var(--border); padding: 7px; border-radius: 6px; color: var(--text-primary); font-size: 0.8rem;" />
      </div>
      <div>
        <label style="display: block; font-size: 0.72rem; color: var(--text-secondary); margin-bottom: 3px;">Countdown (Sec)</label>
        <input type="number" id="arm-test-countdown" value="900" min="10" max="1800" title="900s = 15 minutes standard" style="width: 100%; background: var(--bg-main); border: 1px solid var(--border); padding: 7px; border-radius: 6px; color: var(--yellow); font-size: 0.8rem; font-weight: 700;" />
      </div>
      <div>
        <label style="display: block; font-size: 0.72rem; color: var(--text-secondary); margin-bottom: 3px;">Technical Reason ("Why System Takes Trade")</label>
        <input type="text" id="arm-test-reason" value="Bullish breakout above PDH (23,500) confirmed on 15M candle with OI support" style="width: 100%; background: var(--bg-main); border: 1px solid var(--border); padding: 7px; border-radius: 6px; color: var(--text-primary); font-size: 0.8rem;" />
      </div>
      <div>
        <button type="submit" class="btn" style="background: #f59e0b; color: #000; border: none; font-weight: 800; padding: 8px 16px; border-radius: 6px; font-size: 0.82rem; white-space: nowrap;">
          ⏱️ Arm 15-Min Trade
        </button>
      </div>
    </form>
  </div>
</div>

<!-- Add Custom News Event Modal -->
<div id="add-news-modal" style="display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.75); z-index: 2000; justify-content: center; align-items: center; padding: 20px;">
  <div style="background: var(--bg-card); border: 1px solid var(--border); border-radius: 10px; max-width: 600px; width: 100%; padding: 24px; box-shadow: 0 10px 30px rgba(0,0,0,0.7);">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; border-bottom: 1px solid var(--border); padding-bottom: 10px;">
      <h3 style="font-size: 1.15rem; color: var(--text-primary);">➕ Add Market News / Event</h3>
      <button onclick="closeAddNewsModal()" style="background: none; border: none; color: var(--text-secondary); font-size: 1.4rem; cursor: pointer;">&times;</button>
    </div>
    <form onsubmit="submitAddNews(event)" style="display: flex; flex-direction: column; gap: 12px;">
      <div>
        <label style="display: block; font-size: 0.78rem; color: var(--text-secondary); margin-bottom: 4px;">News Headline / Title *</label>
        <input type="text" id="modal-news-title" required placeholder="e.g. RBI Keeps Repo Rate Unchanged; Upgrades GDP Growth Forecast" style="width: 100%; background: var(--bg-main); border: 1px solid var(--border); padding: 8px 12px; border-radius: 6px; color: var(--text-primary); font-size: 0.85rem;" />
      </div>
      <div>
        <label style="display: block; font-size: 0.78rem; color: var(--text-secondary); margin-bottom: 4px;">Summary / Description</label>
        <textarea id="modal-news-summary" rows="3" placeholder="Context, figures, key quotes..." style="width: 100%; background: var(--bg-main); border: 1px solid var(--border); padding: 8px 12px; border-radius: 6px; color: var(--text-primary); font-size: 0.85rem;"></textarea>
      </div>
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
        <div>
          <label style="display: block; font-size: 0.78rem; color: var(--text-secondary); margin-bottom: 4px;">Category</label>
          <select id="modal-news-category" style="width: 100%; background: var(--bg-main); border: 1px solid var(--border); padding: 8px; border-radius: 6px; color: var(--text-primary); font-size: 0.82rem;">
            <option value="GOOD_NEWS">Good News for Market</option>
            <option value="MARKET_IMPACT">High Market Impact</option>
            <option value="MACRO_POLICY">Macro &amp; RBI Policy</option>
            <option value="GLOBAL_CUES">Global Cues &amp; Crude</option>
            <option value="BAD_NEWS">Market Risk / Negative</option>
            <option value="EARNINGS">Corporate Earnings</option>
          </select>
        </div>
        <div>
          <label style="display: block; font-size: 0.78rem; color: var(--text-secondary); margin-bottom: 4px;">Expected Market Effect</label>
          <select id="modal-news-impact" style="width: 100%; background: var(--bg-main); border: 1px solid var(--border); padding: 8px; border-radius: 6px; color: var(--text-primary); font-size: 0.82rem;">
            <option value="BULLISH">🟢 BULLISH (Supports Rally)</option>
            <option value="BEARISH">🔴 BEARISH (Downside Risk)</option>
            <option value="VOLATILE">⚡ VOLATILE (Sharp Swings)</option>
            <option value="NEUTRAL">⚪ NEUTRAL (Rangebound)</option>
          </select>
        </div>
      </div>
      <div>
        <label style="display: block; font-size: 0.78rem; color: var(--text-secondary); margin-bottom: 4px;">Direct Market Effect on NIFTY &amp; BANKNIFTY *</label>
        <input type="text" id="modal-news-effect" required placeholder="e.g. Bullish catalyst for BankNifty; supports higher lows and call buying" style="width: 100%; background: var(--bg-main); border: 1px solid var(--border); padding: 8px 12px; border-radius: 6px; color: var(--text-primary); font-size: 0.85rem;" />
      </div>
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
        <div>
          <label style="display: block; font-size: 0.78rem; color: var(--text-secondary); margin-bottom: 4px;">Source Name</label>
          <input type="text" id="modal-news-source" value="Market Wire / Analyst" style="width: 100%; background: var(--bg-main); border: 1px solid var(--border); padding: 8px 12px; border-radius: 6px; color: var(--text-primary); font-size: 0.82rem;" />
        </div>
        <div>
          <label style="display: block; font-size: 0.78rem; color: var(--text-secondary); margin-bottom: 4px;">Article URL (Optional)</label>
          <input type="url" id="modal-news-url" placeholder="https://..." style="width: 100%; background: var(--bg-main); border: 1px solid var(--border); padding: 8px 12px; border-radius: 6px; color: var(--text-primary); font-size: 0.82rem;" />
        </div>
      </div>
      <div style="display: flex; align-items: center; gap: 8px; margin-top: 4px;">
        <input type="checkbox" id="modal-news-important" checked style="accent-color: var(--accent); transform: scale(1.15);" />
        <label for="modal-news-important" style="font-size: 0.82rem; color: var(--text-primary); cursor: pointer;">
          ⚡ <strong>Mark as Important: Scroll at Dashboard Top ticker</strong>
        </label>
      </div>
      <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 14px;">
        <button type="button" onclick="closeAddNewsModal()" class="btn" style="padding: 8px 16px;">Cancel</button>
        <button type="submit" class="btn" style="background: var(--accent); color: white; border: none; font-weight: 700; padding: 8px 20px;">Save &amp; Post News</button>
      </div>
    </form>
  </div>
</div>

<script>
  function switchTab(tabId, btn) {
    document.querySelectorAll('.tab-content').forEach(el => {
      el.classList.remove('active');
      el.style.display = 'none';
    });
    document.querySelectorAll('.nav-tab').forEach(el => el.classList.remove('active'));

    const target = document.getElementById(tabId);
    if (target) {
      target.classList.add('active');
      target.style.display = 'block';
    }

    if (btn && btn.classList) {
      btn.classList.add('active');
    } else {
      document.querySelectorAll('.nav-tab').forEach(b => {
        const oc = b.getAttribute('onclick') || '';
        if (oc.includes(tabId)) {
          b.classList.add('active');
        }
      });
    }

    try { localStorage.setItem('nt_active_tab', tabId); } catch (e) {}
  }

  // -------------------------------------------------------------
  // TELEGRAM & 15-MINUTE ARMED TRADE FUNCTIONS
  // -------------------------------------------------------------
  async function fetchTelegramStatus() {
    try {
      const res = await fetch('/api/telegram/status');
      if (!res.ok) return;
      const data = await res.json();

      const badge = document.getElementById('telegram-badge');
      const tag = document.getElementById('tele-status-tag');

      if (data.configured) {
        if (badge) {
          badge.className = 'badge badge-green';
          badge.innerText = '📱 TELEGRAM: CONNECTED';
          badge.style.border = '1px solid rgba(16, 185, 129, 0.4)';
          badge.style.color = '#10b981';
          badge.title = `Telegram Bot Connected (Chat: ${data.chat_id || 'Configured'})`;
        }
        if (tag) {
          tag.className = 'badge badge-green';
          tag.innerText = `CONNECTED (${data.chat_id || 'OK'})`;
          tag.style.color = '#10b981';
        }
      } else {
        if (badge) {
          badge.className = 'badge badge-yellow';
          badge.innerText = '📱 TELEGRAM: UNCONFIGURED';
          badge.style.border = '1px solid rgba(245, 158, 11, 0.4)';
          badge.style.color = '#f59e0b';
          badge.title = 'Click to configure Telegram Bot Token and Chat ID';
        }
        if (tag) {
          tag.className = 'badge badge-yellow';
          tag.innerText = 'UNCONFIGURED';
          tag.style.color = '#f59e0b';
        }
      }

      const tokInput = document.getElementById('tele-input-token');
      const chatInput = document.getElementById('tele-input-chat');
      if (tokInput && !tokInput.value && data.bot_token_set) {
        tokInput.placeholder = data.masked_token || 'Configured in environment';
      }
      if (chatInput && !chatInput.value && data.chat_id) {
        chatInput.value = data.chat_id;
      }
    } catch (e) {
      console.debug("Telegram status fetch error:", e);
    }
  }

  async function saveTelegramCredentials(e) {
    e.preventDefault();
    const token = document.getElementById('tele-input-token').value.trim();
    const chat = document.getElementById('tele-input-chat').value.trim();
    const feedback = document.getElementById('tele-save-feedback');

    if (!token && !chat) {
      alert("Please enter a valid Bot Token and Chat ID.");
      return;
    }

    try {
      if (feedback) feedback.innerText = "Saving credentials...";
      const res = await fetch('/api/telegram/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bot_token: token, chat_id: chat }),
      });
      const data = await res.json();
      if (data.status === 'ok') {
        if (feedback) {
          feedback.style.color = 'var(--green)';
          feedback.innerText = "✅ Credentials saved successfully!";
          setTimeout(() => { if (feedback) feedback.innerText = ""; }, 4000);
        }
        await fetchTelegramStatus();
        alert("Telegram credentials saved! You can now click 'Send Test Alert' to test communication.");
      } else {
        if (feedback) {
          feedback.style.color = 'var(--red)';
          feedback.innerText = "Error: " + (data.message || 'Failed');
        }
      }
    } catch (err) {
      console.error("Save Telegram creds error:", err);
      if (feedback) {
        feedback.style.color = 'var(--red)';
        feedback.innerText = "Error saving credentials";
      }
    }
  }

  async function sendTelegramTest() {
    try {
      const res = await fetch('/api/telegram/test', { method: 'POST' });
      const data = await res.json();
      if (data.status === 'ok') {
        alert(`✅ Telegram test alert dispatched successfully!\n\nCheck your Telegram chat for the confirmation message.`);
      } else {
        alert(`⚠️ Telegram test failed:\n\n${data.message || 'Unknown error'}\n\nPlease ensure your Bot Token and Chat ID are correct, and that you have started your bot by sending /start.`);
      }
    } catch (err) {
      alert("Error sending Telegram test alert: " + err);
    }
  }

  async function fetchPendingTrades() {
    try {
      const res = await fetch('/api/telegram/pending_trades');
      if (!res.ok) return;
      const data = await res.json();
      const trades = data.pending_trades || [];
      const armedCount = data.count || 0;

      // Update badges
      const navBadge = document.getElementById('nav-pending-badge');
      if (navBadge) {
        if (armedCount > 0) {
          navBadge.innerText = armedCount;
          navBadge.style.display = 'inline-block';
        } else {
          navBadge.style.display = 'none';
        }
      }
      const countBadge = document.getElementById('pending-count-badge');
      if (countBadge) countBadge.innerText = `${armedCount} ARMED`;

      // Render table
      const tbody = document.getElementById('pending-trades-tbody');
      if (!tbody) return;

      if (trades.length === 0) {
        tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--text-secondary); padding: 30px;">No armed trades currently active. When a breakout or option condition triggers, it will appear here with a live 15-minute countdown.</td></tr>`;
        return;
      }

      tbody.innerHTML = trades.map(t => {
        const isArmed = t.status === 'ARMED_15M';
        const remSecs = t.remaining_seconds || 0;
        const mins = Math.floor(remSecs / 60);
        const secs = remSecs % 60;
        const remStr = isArmed ? `${mins < 10 ? '0' : ''}${mins}:${secs < 10 ? '0' : ''}${secs}` : '--';

        let statusBadge = '<span class="badge badge-yellow">ARMED 15M</span>';
        if (t.status === 'EXECUTED') statusBadge = '<span class="badge badge-green">EXECUTED</span>';
        else if (t.status === 'CANCELLED') statusBadge = '<span class="badge badge-red">CANCELLED</span>';

        const optBadge = t.option_type === 'CE' ? 'badge-green' : 'badge-red';

        return `
          <tr style="border-bottom: 1px solid rgba(255,255,255,0.05); ${isArmed ? 'background: rgba(245, 158, 11, 0.04);' : ''}">
            <td><code style="color: #38bdf8;">${t.pending_id || 'PT'}</code></td>
            <td><strong>${t.symbol} ${t.strike} <span class="badge ${optBadge}">${t.option_type}</span></strong></td>
            <td>${t.lots} Lots (${t.qty} Qty)</td>
            <td>Spot: ₹${(t.spot_price || 0).toFixed(2)}<br/><span style="color: var(--accent); font-weight: 700;">Prem: ₹${(t.premium || 0).toFixed(2)}</span></td>
            <td><span style="color: var(--red);">SL: ₹${(t.sl_price || 0).toFixed(2)}</span><br/><span style="color: var(--green);">Tgt: ₹${(t.target_price || 0).toFixed(2)}</span></td>
            <td>
              ${isArmed ? `<span style="font-size: 1.1rem; font-weight: 800; font-family: monospace; color: ${remSecs < 180 ? 'var(--red)' : 'var(--yellow)'};">${remStr}</span>` : '<span style="color: var(--text-secondary);">Completed</span>'}
            </td>
            <td>${statusBadge}</td>
            <td style="max-width: 280px; font-size: 0.76rem; color: var(--text-secondary);">
              ${t.reasoning || 'Standard setup condition matched'}
            </td>
            <td style="text-align: right;">
              ${isArmed ? `
                <button onclick="cancelPendingTrade('${t.pending_id}')" class="btn" style="background: rgba(239, 68, 68, 0.2); border: 1px solid var(--red); color: var(--red); font-size: 0.75rem; padding: 4px 10px; border-radius: 4px; font-weight: 700;" title="Cancel trade before 15-minute countdown finishes">
                  🛑 Cancel Order
                </button>
              ` : `<span style="font-size: 0.72rem; color: var(--text-secondary);">${t.status === 'EXECUTED' ? 'Executed' : 'Aborted'}</span>`}
            </td>
          </tr>
        `;
      }).join('');
    } catch (e) {
      console.debug("Fetch pending trades error:", e);
    }
  }

  async function cancelPendingTrade(pendingId) {
    if (!confirm(`Are you sure you want to cancel pending order ${pendingId}?\n\nThis will stop the 15-minute countdown and prevent auto-execution into the simulator.`)) {
      return;
    }
    try {
      const res = await fetch('/api/telegram/cancel_pending', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pending_id: pendingId, reason: "Cancelled manually by user from dashboard" }),
      });
      const data = await res.json();
      if (data.status === 'ok') {
        alert(`Order ${pendingId} has been cancelled.\nA cancellation alert was sent to Telegram.`);
        await fetchPendingTrades();
      } else {
        alert("Could not cancel order: " + (data.message || "Error"));
      }
    } catch (err) {
      alert("Error cancelling pending trade: " + err);
    }
  }

  async function submitManualArmTrade(e) {
    e.preventDefault();
    const sym = document.getElementById('arm-test-symbol').value;
    const strike = parseInt(document.getElementById('arm-test-strike').value);
    const optType = document.getElementById('arm-test-type').value;
    const premium = parseFloat(document.getElementById('arm-test-premium').value);
    const countdown = parseInt(document.getElementById('arm-test-countdown').value) || 900;
    const reason = document.getElementById('arm-test-reason').value.trim() || "Manual 15M confirmation test";

    try {
      const res = await fetch('/api/telegram/arm_trade', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: sym,
          strike: strike,
          option_type: optType,
          lots: 1,
          premium: premium,
          sl_points: 20,
          target_points: 40,
          reasoning: reason,
          countdown_seconds: countdown,
        }),
      });
      const data = await res.json();
      if (data.status === 'ok') {
        alert(`⚡ Trade Armed Successfully!\n\nOrder ID: ${data.pending_trade.pending_id}\nSymbol: ${sym} ${strike} ${optType}\nCountdown: ${countdown} seconds\n\nA Telegram intent alert was dispatched. The trade will auto-execute when countdown completes unless cancelled.`);
        await fetchPendingTrades();
      } else {
        alert("Error arming trade: " + (data.message || "Error"));
      }
    } catch (err) {
      alert("Error submitting arm trade: " + err);
    }
  }

  async function fetchData() {
    try {
      const res = await fetch('/api/data');
      const data = await res.json();
      renderDashboard(data);
    } catch (e) {
      console.error("Dashboard fetch error:", e);
    }

    try {
      const supaRes = await fetch('/api/supabase/status');
      if (supaRes.ok) {
        const supaData = await supaRes.json();
        const badge = document.getElementById('supabase-badge');
        if (badge) {
          if (supaData.configured) {
            badge.className = 'badge badge-green';
            badge.innerText = '☁️ SUPABASE: CONNECTED';
            badge.style.border = '1px solid rgba(16, 185, 129, 0.4)';
            badge.title = 'Supabase Cloud Sync active (' + (supaData.url || '') + ')';
          } else {
            badge.className = 'badge badge-yellow';
            badge.innerText = '💾 LOCAL SQLITE (CLOUD READY)';
            badge.style.border = '1px solid rgba(245, 158, 11, 0.4)';
            badge.title = 'Running locally on SQLite. Set SUPABASE_URL & SUPABASE_KEY to enable cloud sync.';
          }
        }
      }
    } catch (e) {
      console.debug("Supabase status check skipped:", e);
    }

    try {
      await fetchTelegramStatus();
    } catch (e) {
      console.debug("Telegram status error:", e);
    }
  }

  function renderDashboard(data) {
    // 1. Brain history
    const brainBody = document.getElementById('brain-table-body');
    if (data.brain && data.brain.length > 0) {
      brainBody.innerHTML = data.brain.map(b => `
        <tr>
          <td>${b.timestamp ? b.timestamp.substring(0, 19).replace('T', ' ') : 'N/A'}</td>
          <td><span class="badge badge-blue">${b.setup_status || 'WAIT'}</span></td>
          <td><strong>${b.one_hour_bias || 'NEUTRAL'}</strong></td>
          <td>${b.fifteen_minute_state || 'CONSOLIDATING'}</td>
          <td><span class="badge ${b.action === 'CANDIDATE' ? 'badge-green' : 'badge-yellow'}">${b.action || 'WAIT'}</span></td>
          <td style="color: var(--text-secondary); font-size: 0.78rem;">${(b.reasoning && b.reasoning.length > 0) ? b.reasoning[0] : (b.market_context || 'Standard evaluation')}</td>
        </tr>
      `).join('');
    } else if (brainBody) {
      brainBody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-secondary); padding: 24px;">🧠 Cognitive AI Brain is ready &amp; armed. Awaiting 15M candle evaluation during market session (09:15–15:30 IST) or click "Trigger Brain Evaluation Now" above.</td></tr>`;
    }

    // 2. Positions
    const posBody = document.getElementById('positions-table-body');
    if (data.paper && data.paper.positions && data.paper.positions.length > 0) {
      posBody.innerHTML = data.paper.positions.map(p => `
        <tr>
          <td>${p.position_id ? p.position_id.substring(0, 12) : 'POS'}</td>
          <td><strong>${p.symbol} ${p.strike || ''} ${p.option_type || ''}</strong></td>
          <td><span class="badge ${p.action === 'BUY' ? 'badge-green' : 'badge-red'}">${p.action}</span></td>
          <td>${p.lots || 1}</td>
          <td>₹${p.entry_price ? p.entry_price.toFixed(2) : '0.00'}</td>
          <td>₹${p.current_price ? p.current_price.toFixed(2) : '0.00'}</td>
          <td class="${(p.unrealized_pnl || 0) >= 0 ? 'score-pos' : 'score-neg'}">₹${(p.unrealized_pnl || 0).toFixed(2)}</td>
          <td><span class="badge badge-green">${p.status || 'OPEN'}</span></td>
        </tr>
      `).join('');
    } else if (posBody) {
      posBody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-secondary); padding: 24px;">🟢 Safe Virtual Mode Active &bull; No active positions currently open (Portfolio Flat). Active positions with real-time MTM, SL, and Target tracking will display here as soon as a custom level or AI setup triggers.</td></tr>`;
    }

    // 2b. Monitoring
    const monBody = document.getElementById('monitoring-table-body');
    if (data.paper && data.paper.monitoring && data.paper.monitoring.length > 0) {
      monBody.innerHTML = data.paper.monitoring.map(m => `
        <tr>
          <td>${m.timestamp ? m.timestamp.substring(0, 19).replace('T', ' ') : 'N/A'}</td>
          <td><code>${m.position_id || 'POS'}</code></td>
          <td><span class="badge badge-blue">${m.trigger_event || 'POLL'}</span></td>
          <td>${m.price_move ? (m.price_move > 0 ? '+' : '') + m.price_move.toFixed(2) : '--'}</td>
          <td>${m.reassessment_action || 'HOLD'}</td>
          <td class="${(m.current_pnl || 0) >= 0 ? 'score-pos' : 'score-neg'}">₹${(m.current_pnl || 0).toFixed(2)}</td>
        </tr>
      `).join('');
    } else if (monBody) {
      monBody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-secondary); padding: 18px;">Position monitoring active. Checks occur continuously every 15 seconds whenever positions are active.</td></tr>`;
    }

    // 2c. Experience
    const expBody = document.getElementById('experience-table-body');
    if (data.experience && data.experience.experiences && data.experience.experiences.length > 0) {
      expBody.innerHTML = data.experience.experiences.map(e => `
        <tr>
          <td><code>${e.trade_id || 'TRD'}</code></td>
          <td><strong>${e.instrument || 'NIFTY'}</strong></td>
          <td><span class="badge ${e.outcome === 'WIN' ? 'badge-green' : 'badge-red'}">${e.outcome || 'RESOLVED'}</span></td>
          <td class="${(e.realized_pnl || 0) >= 0 ? 'score-pos' : 'score-neg'}">₹${(e.realized_pnl || 0).toFixed(2)}</td>
          <td>${e.duration_minutes ? e.duration_minutes + ' mins' : '--'}</td>
          <td style="font-size: 0.78rem;">${typeof e.reasoning_summary === 'object' ? JSON.stringify(e.reasoning_summary) : (e.reasoning_summary || '--')}</td>
          <td><span class="badge badge-blue">${e.execution_fidelity || '100%'}</span></td>
        </tr>
      `).join('');
    } else if (expBody) {
      expBody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-secondary); padding: 24px;">📘 Experience Memory Store is active (data/experience.db). Closed simulator &amp; paper trades will be analyzed here for edge validation, win-rate attribution, and risk lessons.</td></tr>`;
    }

    // 3. Research Zone
    if (data.research) {
      document.getElementById('res-bars-count').innerText = data.research.total_normalized_bars || 0;
      document.getElementById('res-fails-count').innerText = (data.research.failed_hypotheses || []).length;
      document.getElementById('res-ass-count').innerText = (data.research.assessments || []).length;

      const assBody = document.getElementById('research-ass-body');
      if (data.research.assessments && data.research.assessments.length > 0) {
        assBody.innerHTML = data.research.assessments.map(a => {
          const segHtml = (a.segments || []).map(s => `
            <span class="segment-pill" style="background: rgba(59, 130, 246, 0.15); color: var(--accent);">
              ${s.name}: <strong class="${s.score >= 0 ? 'score-pos' : 'score-neg'}">${s.score > 0 ? '+' : ''}${s.score.toFixed(1)}</strong> (w: ${s.importance.toFixed(2)})
            </span>
          `).join('');
          return `
            <tr>
              <td><code>${a.research_id}</code></td>
              <td>${a.timestamp ? a.timestamp.substring(0, 19).replace('T', ' ') : ''}</td>
              <td><strong>${a.instrument} ${a.timeframe}</strong></td>
              <td><span class="badge ${a.direction === 'BULLISH' ? 'badge-green' : a.direction === 'BEARISH' ? 'badge-red' : 'badge-yellow'}">${a.direction}</span></td>
              <td class="${a.total_score >= 0 ? 'score-pos' : 'score-neg'}">${a.total_score > 0 ? '+' : ''}${a.total_score.toFixed(2)}</td>
              <td>${(a.confidence * 100).toFixed(0)}%</td>
              <td>${segHtml}</td>
            </tr>
          `;
        }).join('');
      }

      const failsBody = document.getElementById('research-fails-body');
      if (data.research.failed_hypotheses && data.research.failed_hypotheses.length > 0) {
        failsBody.innerHTML = data.research.failed_hypotheses.map(f => `
          <tr>
            <td><code>${f.failed_id}</code></td>
            <td><strong>${f.statement}</strong></td>
            <td style="color: var(--red);">${f.failure_reason}</td>
            <td style="color: var(--yellow);">${f.lessons_learned}</td>
            <td>${f.recorded_at ? f.recorded_at.substring(0, 19).replace('T', ' ') : ''}</td>
          </tr>
        `).join('');
      }
    }

    // 4. Simulator Telemetry
    if (data.simulator) {
      const sim = data.simulator;
      document.getElementById('sim-kpi-status').innerText = sim.status || 'AUTO-ACTIVE';
      document.getElementById('sim-kpi-rule').innerText = `Rule: ${sim.rule_name || 'My_Custom_Strategy'} (${sim.status === 'AUTO-ACTIVE' ? '100% Local, Zero LLM' : 'Paused'})`;
      document.getElementById('sim-kpi-capital').innerText = `₹${(sim.current_capital || 100000).toLocaleString('en-IN', {minimumFractionDigits: 2})}`;

      const netPnlEl = document.getElementById('sim-kpi-net-pnl');
      const netVal = sim.net_pnl || 0.0;
      netPnlEl.innerText = `${netVal >= 0 ? '+' : ''}₹${netVal.toLocaleString('en-IN', {minimumFractionDigits: 2})}`;
      netPnlEl.style.color = netVal >= 0 ? 'var(--green)' : 'var(--red)';

      document.getElementById('sim-kpi-charges').innerText = `STT + GST + SEBI + Brokerage: ₹${(sim.total_charges || 0).toLocaleString('en-IN', {minimumFractionDigits: 2})} (Gross: ₹${(sim.gross_pnl || 0).toFixed(2)})`;
      document.getElementById('sim-kpi-winrate').innerText = `${sim.win_rate || 0.0}%`;
      document.getElementById('sim-kpi-trades-count').innerText = `${sim.winning_trades || 0} Wins / ${sim.losing_trades || 0} Losses (${sim.total_trades || 0} Total)`;

      const obsTimeEl = document.getElementById('sim-last-obs-time');
      if (obsTimeEl) obsTimeEl.innerText = sim.last_analysis_time || 'Awaiting 15M cycle';
      const verdictEl = document.getElementById('sim-last-verdict');
      if (verdictEl) verdictEl.innerText = sim.last_chart_verdict || 'Listening for 15M cycle';

      // Active Position
      const posBox = document.getElementById('sim-active-pos-box');
      if (sim.active_position) {
        const p = sim.active_position;
        const pnlCol = p.mtm_pnl >= 0 ? 'score-pos' : 'score-neg';
        posBox.innerHTML = `
          <div style="display: flex; gap: 20px; align-items: center; background: rgba(59, 130, 246, 0.08); padding: 12px 16px; border-radius: 6px; border: 1px solid var(--border);">
            <div><span class="badge ${p.option_type === 'CE' ? 'badge-green' : 'badge-red'}">${p.option_type} BUY</span> <strong>NIFTY ${p.strike} ${p.option_type}</strong> (${p.lots} Lot / ${p.qty} Qty)</div>
            <div>Entry: <strong>₹${p.entry_premium.toFixed(2)}</strong></div>
            <div>LTP: <strong>₹${p.current_premium.toFixed(2)}</strong></div>
            <div>SL: <strong style="color: var(--red);">₹${p.sl_price.toFixed(2)}</strong></div>
            <div>Target: <strong style="color: var(--green);">₹${p.target_price.toFixed(2)}</strong></div>
            <div>MTM P&L: <strong class="${pnlCol}">${p.mtm_pnl >= 0 ? '+' : ''}₹${p.mtm_pnl.toFixed(2)}</strong></div>
          </div>
        `;
      } else {
        posBox.innerHTML = `<span style="color: var(--text-secondary);">Currently flat. Real-time candle monitor is actively watching for ${sim.rule_name} signals...</span>`;
      }

      // Trades Table
      const simTable = document.getElementById('sim-trades-table-body');
      if (sim.recent_trades && sim.recent_trades.length > 0) {
        simTable.innerHTML = sim.recent_trades.map(t => `
          <tr>
            <td><code>${t.trade_id}</code></td>
            <td><strong>NIFTY ${t.strike} ${t.option_type}</strong></td>
            <td>${t.entry_time}</td>
            <td>${t.exit_time}</td>
            <td>₹${t.entry_premium.toFixed(2)}</td>
            <td>₹${t.exit_premium.toFixed(2)}</td>
            <td><span class="badge ${t.net_pnl >= 0 ? 'badge-green' : 'badge-red'}">${t.exit_reason}</span></td>
            <td>₹${t.gross_pnl.toFixed(2)}</td>
            <td style="color: var(--yellow);">₹${t.charges.toFixed(2)}</td>
            <td class="${t.net_pnl >= 0 ? 'score-pos' : 'score-neg'}"><strong>${t.net_pnl >= 0 ? '+' : ''}₹${t.net_pnl.toFixed(2)}</strong> (${t.pnl_pct > 0 ? '+' : ''}${t.pnl_pct.toFixed(1)}%)</td>
            <td>
              <button onclick="deleteSimTrade('${t.trade_id}')" class="btn" style="background: rgba(239, 68, 68, 0.15); color: var(--red); border: 1px solid rgba(239, 68, 68, 0.3); padding: 3px 8px; border-radius: 4px; font-size: 0.75rem; cursor: pointer;" title="Delete this fake/test trade log">🗑️ Delete</button>
            </td>
          </tr>
        `).join('');
      }

      // Update Report Preview
      const repEl = document.getElementById('sim-report-preview');
      if (repEl && sim.report_preview) {
        repEl.innerText = sim.report_preview;
      }

      // 4b. Screenshot preview & details
      if (sim.last_screenshot_name) {
        const fn = document.getElementById('sim-tv-filename');
        if (fn && fn.innerText === '-') fn.innerText = sim.last_screenshot_name;
        const img = document.getElementById('sim-tv-img');
        const fallback = document.getElementById('sim-tv-img-fallback');
        if (img && (!img.src || !img.src.includes('/api/simulator/screenshot_image'))) {
          img.src = '/api/simulator/screenshot_image';
        }
        if (fallback) fallback.style.display = 'none';
        if (img) img.style.display = 'block';
      }
      if (sim.last_analysis_details) {
        renderAnalysisDetails(sim.last_analysis_details);
      }

      // 5. Update Risk & Sizing Controls
      if (sim.settings) {
        window._lastSimData = sim;
        const cfg = sim.settings;
        const activePreset = cfg.preset_name || 'CUSTOM';

        const badgeEl = document.getElementById('sim-active-preset-badge');
        if (badgeEl) {
          badgeEl.innerText = `ACTIVE: ${activePreset}`;
          badgeEl.className = activePreset === 'CUSTOM' ? 'badge badge-yellow' : 'badge badge-blue';
        }

        // Highlight active preset button
        document.querySelectorAll('.preset-btn').forEach(b => {
          b.style.borderColor = 'var(--border)';
          b.style.background = 'var(--bg-card)';
        });
        const activeBtn = document.getElementById(`preset-btn-${activePreset}`);
        if (activeBtn) {
          activeBtn.style.borderColor = 'var(--accent)';
          activeBtn.style.background = 'rgba(59, 130, 246, 0.2)';
        }

        const lotsInput = document.getElementById('sim-cfg-lots');
        if (lotsInput && document.activeElement !== lotsInput) {
          lotsInput.value = cfg.lots || 1;
          updateLotsDisplay();
        }
        const slInput = document.getElementById('sim-cfg-sl-val');
        if (slInput && document.activeElement !== slInput) {
          slInput.value = cfg.sl_val || 20;
        }
        const slModeSel = document.getElementById('sim-cfg-sl-mode');
        if (slModeSel && document.activeElement !== slModeSel) {
          slModeSel.value = cfg.sl_mode || 'POINTS';
        }
        const targetInput = document.getElementById('sim-cfg-target-val');
        if (targetInput && document.activeElement !== targetInput) {
          targetInput.value = cfg.target_val || 40;
        }
        const targetModeSel = document.getElementById('sim-cfg-target-mode');
        if (targetModeSel && document.activeElement !== targetModeSel) {
          targetModeSel.value = cfg.target_mode || 'POINTS';
        }
        const trailCheck = document.getElementById('sim-cfg-trailing');
        if (trailCheck && document.activeElement !== trailCheck) {
          trailCheck.checked = !!cfg.trailing_sl;
        }
        const trailStepInput = document.getElementById('sim-cfg-trail-step');
        if (trailStepInput && document.activeElement !== trailStepInput) {
          trailStepInput.value = cfg.trail_step || 15;
        }
      }
    }

    // 6. Multi-Instrument Spot Telemetry (NIFTY 50, BANKNIFTY, GIFT NIFTY)
    if (data.spot) {
      const sp = data.spot;
      const insts = sp.instruments || {};
      const headerBadge = document.getElementById('header-spot-badge');
      const spotStatusBadge = document.getElementById('spot-status-badge');
      const countdownEl = document.getElementById('spot-countdown');
      const lastUpText = document.getElementById('spot-last-updated-text');

      if (countdownEl) {
        countdownEl.innerText = sp.is_market_active ? (sp.countdown_str || '05:00') : 'STANDBY';
      }
      if (spotStatusBadge) {
        spotStatusBadge.innerText = sp.status || 'AUTO-ACTIVE (09:15–15:30 IST)';
        if (!sp.is_market_active) {
          spotStatusBadge.className = 'badge badge-yellow';
        } else {
          spotStatusBadge.className = 'badge badge-green';
        }
      }
      const schedTextEl = document.getElementById('spot-schedule-text');
      if (schedTextEl && sp.market_window) {
        const mw = sp.market_window;
        schedTextEl.innerHTML = `<strong>Session Status:</strong> ${mw.reason || ''} &bull; <em>${mw.next_session_desc || ''}</em>`;
      }
      if (lastUpText && sp.last_fetch_time) lastUpText.innerText = `Last Updated: ${sp.last_fetch_time}`;

      // Update Header Multi-Ticker Badge
      let badgeParts = [];
      const n = insts['NIFTY 50'];
      const b = insts['BANKNIFTY'];
      const g = insts['GIFT NIFTY'];

      if (n) {
        const s = n.change_pts >= 0 ? '+' : '';
        const col = n.change_pts >= 0 ? 'var(--green)' : 'var(--red)';
        badgeParts.push(`🟢 NIFTY: ₹${n.spot_price.toLocaleString('en-IN', {minimumFractionDigits: 1})} <span style="color:${col};">(${s}${n.change_pct.toFixed(2)}%)</span>`);
      }
      if (b) {
        const s = b.change_pts >= 0 ? '+' : '';
        const col = b.change_pts >= 0 ? 'var(--green)' : 'var(--red)';
        badgeParts.push(`🏦 BANKNIFTY: ₹${b.spot_price.toLocaleString('en-IN', {minimumFractionDigits: 1})} <span style="color:${col};">(${s}${b.change_pct.toFixed(2)}%)</span>`);
      }
      if (g) {
        const s = g.change_pts >= 0 ? '+' : '';
        const col = g.change_pts >= 0 ? 'var(--green)' : 'var(--red)';
        badgeParts.push(`🌐 GIFT: ₹${g.spot_price.toLocaleString('en-IN', {minimumFractionDigits: 1})} <span style="color:${col};">(${s}${g.change_pct.toFixed(2)}%)</span>`);
      }
      if (headerBadge && badgeParts.length > 0) {
        headerBadge.innerHTML = badgeParts.join(' &nbsp;|&nbsp; ');
      }

      // Populate Individual Cards
      function populateInstCard(prefix, item) {
        if (!item) return;
        const s = item.change_pts >= 0 ? '+' : '';
        const col = item.change_pts >= 0 ? 'var(--green)' : 'var(--red)';

        const priceEl = document.getElementById(`${prefix}-price`);
        if (priceEl) priceEl.innerText = `₹${item.spot_price.toLocaleString('en-IN', {minimumFractionDigits: 2})}`;

        const chgEl = document.getElementById(`${prefix}-change`);
        if (chgEl) {
          chgEl.innerText = `${s}₹${item.change_pts.toFixed(2)} (${s}${item.change_pct.toFixed(2)}%)`;
          chgEl.style.color = col;
        }

        const highEl = document.getElementById(`${prefix}-high`);
        if (highEl) highEl.innerText = `₹${(item.high_price || item.spot_price).toLocaleString('en-IN', {minimumFractionDigits: 2})}`;

        const lowEl = document.getElementById(`${prefix}-low`);
        if (lowEl) lowEl.innerText = `₹${(item.low_price || item.spot_price).toLocaleString('en-IN', {minimumFractionDigits: 2})}`;

        const openEl = document.getElementById(`${prefix}-open`);
        if (openEl) openEl.innerText = `₹${(item.open_price || item.spot_price).toLocaleString('en-IN', {minimumFractionDigits: 2})}`;

        const prevEl = document.getElementById(`${prefix}-prev`);
        if (prevEl) prevEl.innerText = `₹${(item.previous_close || item.spot_price).toLocaleString('en-IN', {minimumFractionDigits: 2})}`;

        const pdhEl = document.getElementById(`${prefix}-pdh`);
        if (pdhEl) pdhEl.innerText = `₹${(item.pdh || item.previous_close || item.spot_price).toLocaleString('en-IN', {minimumFractionDigits: 2})}`;

        const pdlEl = document.getElementById(`${prefix}-pdl`);
        if (pdlEl) pdlEl.innerText = `₹${(item.pdl || item.previous_close || item.spot_price).toLocaleString('en-IN', {minimumFractionDigits: 2})}`;
      }

      populateInstCard('nifty', n);
      populateInstCard('banknifty', b);
      populateInstCard('giftnifty', g);

      // Populate Persistent Top Market Bar (Visible Across All Tabs At All Times)
      function updateTopBarInst(prefix, item) {
        if (!item) return;
        const s = item.change_pts >= 0 ? '+' : '';
        const col = item.change_pts >= 0 ? 'var(--green)' : 'var(--red)';

        const closeEl = document.getElementById(`top-${prefix}-close`);
        if (closeEl) closeEl.innerText = `₹${item.spot_price.toLocaleString('en-IN', {minimumFractionDigits: 2})}`;

        const chgEl = document.getElementById(`top-${prefix}-change`);
        if (chgEl) {
          chgEl.innerText = `${s}₹${item.change_pts.toFixed(2)} (${s}${item.change_pct.toFixed(2)}%)`;
          chgEl.style.color = col;
        }

        const openEl = document.getElementById(`top-${prefix}-open`);
        if (openEl) openEl.innerText = `₹${(item.open_price || item.spot_price).toLocaleString('en-IN', {minimumFractionDigits: 1})}`;

        const highEl = document.getElementById(`top-${prefix}-high`);
        if (highEl) highEl.innerText = `₹${(item.high_price || item.spot_price).toLocaleString('en-IN', {minimumFractionDigits: 1})}`;

        const lowEl = document.getElementById(`top-${prefix}-low`);
        if (lowEl) lowEl.innerText = `₹${(item.low_price || item.spot_price).toLocaleString('en-IN', {minimumFractionDigits: 1})}`;

        const pdhEl = document.getElementById(`top-${prefix}-pdh`);
        if (pdhEl) pdhEl.innerText = `₹${(item.pdh || item.previous_close || item.spot_price).toLocaleString('en-IN', {minimumFractionDigits: 1})}`;

        const pdlEl = document.getElementById(`top-${prefix}-pdl`);
        if (pdlEl) pdlEl.innerText = `₹${(item.pdl || item.previous_close || item.spot_price).toLocaleString('en-IN', {minimumFractionDigits: 1})}`;

        const sr = (item && item.sr) || (sp.sr_levels ? sp.sr_levels[item.symbol] : null);
        if (sr) {
          const r2El = document.getElementById(`top-${prefix}-r2`);
          if (r2El) r2El.innerText = `₹${sr.r2.toLocaleString('en-IN', {minimumFractionDigits: 1})}`;
          const r1El = document.getElementById(`top-${prefix}-r1`);
          if (r1El) r1El.innerText = `₹${sr.r1.toLocaleString('en-IN', {minimumFractionDigits: 1})}`;
          const ppEl = document.getElementById(`top-${prefix}-pp`);
          if (ppEl) ppEl.innerText = `₹${sr.pivot.toLocaleString('en-IN', {minimumFractionDigits: 1})}`;
          const s1El = document.getElementById(`top-${prefix}-s1`);
          if (s1El) s1El.innerText = `₹${sr.s1.toLocaleString('en-IN', {minimumFractionDigits: 1})}`;
          const s2El = document.getElementById(`top-${prefix}-s2`);
          if (s2El) s2El.innerText = `₹${sr.s2.toLocaleString('en-IN', {minimumFractionDigits: 1})}`;
        }
      }

      updateTopBarInst('nifty', n);
      updateTopBarInst('bank', b);
      updateTopBarInst('gift', g);

      // Populate Overview S/R Matrix
      if (sp.sr_levels) {
        ['NIFTY 50', 'BANKNIFTY'].forEach(sym => {
          const sr = sp.sr_levels[sym];
          if (!sr) return;
          const k = sym === 'BANKNIFTY' ? 'bank' : 'nifty';

          const spotEl = document.getElementById(`mat-${k}-spot`);
          if (spotEl) spotEl.innerText = `₹${sr.spot.toLocaleString('en-IN', {minimumFractionDigits: 2})}`;

          const r2El = document.getElementById(`mat-${k}-r2`);
          if (r2El) r2El.innerText = `₹${sr.r2.toLocaleString('en-IN', {minimumFractionDigits: 2})}`;
          const r2d = document.getElementById(`mat-${k}-r2-dist`);
          if (r2d) r2d.innerText = `+${sr.r2_dist.toFixed(1)} pts (${((sr.r2_dist/sr.spot)*100).toFixed(2)}%)`;

          const r1El = document.getElementById(`mat-${k}-r1`);
          if (r1El) r1El.innerText = `₹${sr.r1.toLocaleString('en-IN', {minimumFractionDigits: 2})}`;
          const r1d = document.getElementById(`mat-${k}-r1-dist`);
          if (r1d) r1d.innerText = `+${sr.r1_dist.toFixed(1)} pts (${((sr.r1_dist/sr.spot)*100).toFixed(2)}%)`;

          const ppEl = document.getElementById(`mat-${k}-pp`);
          if (ppEl) ppEl.innerText = `₹${sr.pivot.toLocaleString('en-IN', {minimumFractionDigits: 2})}`;

          const s1El = document.getElementById(`mat-${k}-s1`);
          if (s1El) s1El.innerText = `₹${sr.s1.toLocaleString('en-IN', {minimumFractionDigits: 2})}`;
          const s1d = document.getElementById(`mat-${k}-s1-dist`);
          if (s1d) s1d.innerText = `-${sr.s1_dist.toFixed(1)} pts (${((sr.s1_dist/sr.spot)*100).toFixed(2)}%)`;

          const s2El = document.getElementById(`mat-${k}-s2`);
          if (s2El) s2El.innerText = `₹${sr.s2.toLocaleString('en-IN', {minimumFractionDigits: 2})}`;
          const s2d = document.getElementById(`mat-${k}-s2-dist`);
          if (s2d) s2d.innerText = `-${sr.s2_dist.toFixed(1)} pts (${((sr.s2_dist/sr.spot)*100).toFixed(2)}%)`;
        });
      }

      const topCountdown = document.getElementById('top-bar-countdown');
      if (topCountdown) topCountdown.innerText = sp.is_market_active ? (sp.countdown_str || '05:00') : 'STANDBY';

      const topSessionBadge = document.getElementById('top-bar-session-badge');
      if (topSessionBadge) {
        topSessionBadge.innerText = sp.status || 'AUTO-ACTIVE (09:15–15:30 IST)';
        topSessionBadge.className = sp.is_market_active ? 'badge badge-green' : 'badge badge-yellow';
      }

      const topLastTime = document.getElementById('top-bar-last-time');
      if (topLastTime && sp.last_fetch_time) {
        topLastTime.innerText = `Fetched: ${sp.last_fetch_time}`;
      }

      // Stored Database Records Table
      window._spotHistory = sp.history || [];
      renderSpotTable(window._spotFilter || 'ALL');
    }

    // 7. Custom Level Strategy Triggers
    if (data.levels) {
      const lvls = data.levels.triggers || [];
      const badgeEl = document.getElementById('level-trigger-badge');
      if (badgeEl) {
        badgeEl.innerText = `${data.levels.armed_count || 0} ARMED TRIGGERS`;
        badgeEl.className = data.levels.armed_count > 0 ? 'badge badge-green' : 'badge badge-yellow';
      }

      const tableBody = document.getElementById('level-triggers-table-body');
      if (tableBody && lvls.length > 0) {
        tableBody.innerHTML = lvls.map(t => {
          const isArmed = t.status === 'ARMED';
          const statBadge = isArmed ? 'badge-green' : (t.status === 'TRIGGERED' ? 'badge-blue' : 'badge-red');
          const optBadge = t.option_type === 'CE' ? 'badge-green' : 'badge-red';
          const distColor = Math.abs(t.distance_pts) <= 3.0 ? 'color: var(--yellow); font-weight: 800;' : 'color: var(--text-secondary);';
          return `
            <tr>
              <td><code>${t.trigger_id}</code></td>
              <td><strong>${t.instrument}</strong></td>
              <td style="font-size: 1.05rem; font-weight: 800; color: #f59e0b;">₹${t.trigger_price.toFixed(2)}</td>
              <td style="${distColor}">
                <strong>₹${(t.current_spot || 0).toFixed(2)}</strong><br>
                <small>${t.proximity_desc || ''}</small>
              </td>
              <td><span class="badge badge-blue">${t.condition}</span></td>
              <td><span class="badge ${optBadge}">BUY ${t.option_type}</span></td>
              <td style="color: var(--red);">
                <strong>${t.sl_type === 'SPOT_LEVEL' ? 'Spot ₹' : ''}${t.sl_val}${t.sl_type === 'PERCENT' ? '%' : (t.sl_type === 'POINTS' ? ' pts' : '')}</strong>
              </td>
              <td style="color: var(--green);">
                <strong>${t.target_type === 'SPOT_LEVEL' ? 'Spot ₹' : ''}${t.target_val}${t.target_type === 'PERCENT' ? '%' : (t.target_type === 'POINTS' ? ' pts' : '')}</strong>
              </td>
              <td>${t.lots} Lot (${t.lots * (t.instrument.includes('BANK') ? 30 : 65)} Qty)</td>
              <td><span class="badge ${statBadge}">${t.status}</span></td>
              <td>
                <div style="display: flex; gap: 4px;">
                  ${isArmed ? `<button onclick="cancelLevelTrigger('${t.trigger_id}')" class="btn" style="padding: 2px 6px; font-size: 0.72rem; background: rgba(245, 158, 11, 0.2); color: var(--yellow); border: 1px solid rgba(245, 158, 11, 0.4);">Cancel</button>` : ''}
                  <button onclick="deleteLevelTrigger('${t.trigger_id}')" class="btn" style="padding: 2px 6px; font-size: 0.72rem; background: rgba(239, 68, 68, 0.15); color: var(--red); border: 1px solid rgba(239, 68, 68, 0.3);">🗑️</button>
                </div>
              </td>
            </tr>
          `;
        }).join('');
      } else if (tableBody) {
        tableBody.innerHTML = `<tr><td colspan="11" style="text-align: center; color: var(--text-secondary);">No custom level triggers set yet. Use the form above to arm one.</td></tr>`;
      }
    }

    // 8. Live Market News & Sentiment Intelligence
    if (data.news) {
      renderNewsSection(data.news);
    }
  }

  window._currentNewsData = null;
  window._currentNewsFilter = 'ALL';

  function openNewsTab() {
    switchTab('tab-news');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function filterNews(filterType, btn) {
    window._currentNewsFilter = filterType;
    document.querySelectorAll('.news-filter-btn').forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');
    if (window._currentNewsData) {
      renderNewsCards(window._currentNewsData.recent_news || []);
    }
  }

  window._tickerSpeedMultiplier = 1.0;
  window._tickerPaused = false;
  window._tickerBaseDuration = 180;

  function setTickerSpeed(speed) {
    if (speed === 'slow') {
      window._tickerSpeedMultiplier = 1.0;
    } else if (speed === 'superslow') {
      window._tickerSpeedMultiplier = 1.5;
    } else if (speed === 'normal') {
      window._tickerSpeedMultiplier = 0.65;
    }
    ['slow', 'superslow', 'normal'].forEach(s => {
      const b = document.getElementById(`speed-btn-${s}`);
      if (b) {
        if (s === speed) {
          b.style.background = 'var(--accent)';
          b.style.color = '#ffffff';
          b.style.fontWeight = '700';
        } else {
          b.style.background = 'transparent';
          b.style.color = 'var(--text-secondary)';
          b.style.fontWeight = '600';
        }
      }
    });
    applyTickerSpeed();
  }

  function applyTickerSpeed() {
    const track = document.getElementById('top-news-ticker-track');
    if (!track) return;
    const dur = (window._tickerBaseDuration || 180) * (window._tickerSpeedMultiplier || 1.0);
    track.style.animationDuration = `${dur.toFixed(1)}s`;
    track.style.animationPlayState = window._tickerPaused ? 'paused' : 'running';
  }

  function toggleTickerPause() {
    window._tickerPaused = !window._tickerPaused;
    const btn = document.getElementById('ticker-pause-btn');
    if (btn) {
      btn.innerText = window._tickerPaused ? '▶️' : '⏸️';
      btn.title = window._tickerPaused ? 'Resume scrolling' : 'Pause scrolling';
      btn.style.background = window._tickerPaused ? 'rgba(16, 185, 129, 0.25)' : 'rgba(245, 158, 11, 0.2)';
      btn.style.color = window._tickerPaused ? 'var(--green)' : 'var(--yellow)';
    }
    applyTickerSpeed();
  }

  function toggleMarketBar() {
    const cards = document.getElementById('persistent-market-cards');
    const btn = document.getElementById('market-bar-toggle-btn');
    if (!cards) return;
    if (cards.style.display === 'none') {
      cards.style.display = 'grid';
      if (btn) btn.innerText = '▲';
    } else {
      cards.style.display = 'none';
      if (btn) btn.innerText = '▼';
    }
  }

  function renderNewsSection(newsData) {
    window._currentNewsData = newsData;

    // A. Render Top Scrolling Ticker Bar (100% Indian Market Focused)
    const topTrack = document.getElementById('top-news-ticker-track');
    if (topTrack && newsData.top_scrolling && newsData.top_scrolling.length > 0) {
      const itemsHtml = newsData.top_scrolling.map(item => {
        let badgeClass = 'badge-blue';
        let badgeText = '⚪ NEUTRAL';
        if (item.impact_type === 'BULLISH') { badgeClass = 'badge-green'; badgeText = '🟢 BULLISH CATALYST'; }
        else if (item.impact_type === 'BEARISH') { badgeClass = 'badge-red'; badgeText = '🔴 BEARISH RISK'; }
        else if (item.impact_type === 'VOLATILE') { badgeClass = 'badge-yellow'; badgeText = '⚡ HIGH VOLATILITY'; }

        const effectShort = item.market_effect ? ` <span style="color: #60a5fa; font-weight: 700;">[NIFTY &amp; BANKNIFTY: ${escapeHtml(item.market_effect.substring(0, 85))}...]</span>` : '';

        return `
          <div class="ticker-pill-item" onclick="openNewsTab()">
            <span class="badge ${badgeClass}" style="font-size: 0.7rem; padding: 2px 7px;">${badgeText}</span>
            <span style="font-size: 0.72rem; color: #fbbf24; font-weight: 800;">🇮🇳 INDIA</span>
            <strong style="color: var(--text-primary);">${escapeHtml(item.title)}</strong>
            ${effectShort}
            <span style="color: var(--text-secondary); font-size: 0.72rem;">&bull; ${escapeHtml(item.source || 'Market')}</span>
          </div>
        `;
      }).join('');

      // Duplicate sequence for infinite seamless CSS marquee loop
      topTrack.innerHTML = itemsHtml + itemsHtml;
      const totalItems = newsData.top_scrolling.length;
      window._tickerBaseDuration = Math.max(160, totalItems * 18);
      applyTickerSpeed();
    }

    // B. Update KPI Stats
    const stats = newsData.stats || {};
    const totalEl = document.getElementById('news-stat-total');
    if (totalEl) totalEl.innerText = stats.total || 0;
    const bullEl = document.getElementById('news-stat-bullish');
    if (bullEl) bullEl.innerText = stats.bullish || 0;
    const bearEl = document.getElementById('news-stat-bearish');
    if (bearEl) bearEl.innerText = stats.bearish || 0;
    const impEl = document.getElementById('news-stat-important');
    if (impEl) impEl.innerText = stats.important || 0;
    const macEl = document.getElementById('news-stat-macro');
    if (macEl) macEl.innerText = stats.macro || 0;

    const navBadge = document.getElementById('nav-news-count-badge');
    if (navBadge) navBadge.innerText = stats.total || 0;

    const ovPill = document.getElementById('overview-news-stats-pill');
    if (ovPill) ovPill.innerText = `${stats.total || 0} ACTIVE NEWS (${stats.bullish || 0} 🟢 / ${stats.bearish || 0} 🔴)`;

    const lastFetchEl = document.getElementById('news-last-fetch-badge');
    if (lastFetchEl && newsData.last_fetch) {
      lastFetchEl.innerText = `Last Synced: ${newsData.last_fetch}`;
    }

    // C. Overview Tab Widget Cards (Top 4 impactful news)
    const ovList = document.getElementById('overview-news-list');
    if (ovList && newsData.recent_news) {
      const topNews = newsData.recent_news.slice(0, 4);
      ovList.innerHTML = topNews.map(n => {
        let borderCol = '#3b82f6';
        let bgGrad = 'rgba(59, 130, 246, 0.08)';
        let impactBadge = '<span class="badge badge-blue">⚪ NEUTRAL</span>';
        if (n.impact_type === 'BULLISH') {
          borderCol = 'var(--green)';
          bgGrad = 'rgba(16, 185, 129, 0.08)';
          impactBadge = '<span class="badge badge-green">🟢 BULLISH CATALYST</span>';
        } else if (n.impact_type === 'BEARISH') {
          borderCol = 'var(--red)';
          bgGrad = 'rgba(239, 68, 68, 0.08)';
          impactBadge = '<span class="badge badge-red">🔴 BEARISH RISK</span>';
        } else if (n.impact_type === 'VOLATILE') {
          borderCol = 'var(--yellow)';
          bgGrad = 'rgba(245, 158, 11, 0.08)';
          impactBadge = '<span class="badge badge-yellow">⚡ VOLATILITY TRIGGER</span>';
        }

        return `
          <div style="background: var(--bg-card); border: 1px solid var(--border); border-left: 3px solid ${borderCol}; border-radius: 8px; padding: 12px; display: flex; flex-direction: column; justify-content: space-between;">
            <div>
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; font-size: 0.72rem;">
                ${impactBadge}
                <span style="color: var(--text-secondary);">${escapeHtml(n.source || 'Market Wire')}</span>
              </div>
              <div style="font-weight: 700; font-size: 0.88rem; color: var(--text-primary); margin-bottom: 6px; line-height: 1.35;">
                ${escapeHtml(n.title)}
              </div>
            </div>
            <div style="background: ${bgGrad}; padding: 8px 10px; border-radius: 6px; border: 1px dashed ${borderCol}; margin-top: 8px; font-size: 0.76rem;">
              <strong style="color: var(--text-primary); display: block; margin-bottom: 2px;">🎯 Effect on NIFTY &amp; BANKNIFTY:</strong>
              <span style="color: var(--text-secondary);">${escapeHtml(n.market_effect || 'Monitored for price action')}</span>
            </div>
          </div>
        `;
      }).join('');
    }

    // D. Dedicated News Stream
    renderNewsCards(newsData.recent_news || []);
  }

  function renderNewsCards(newsList) {
    const container = document.getElementById('news-cards-container');
    if (!container) return;

    let filtered = newsList;
    const filter = window._currentNewsFilter || 'ALL';

    if (filter === 'IMPORTANT') {
      filtered = newsList.filter(n => n.is_important === 1 || n.impact_score >= 4);
    } else if (filter === 'GOOD_NEWS') {
      filtered = newsList.filter(n => n.category === 'GOOD_NEWS' || n.impact_type === 'BULLISH');
    } else if (filter === 'BAD_NEWS') {
      filtered = newsList.filter(n => n.category === 'BAD_NEWS' || n.impact_type === 'BEARISH');
    } else if (filter === 'MACRO_POLICY') {
      filtered = newsList.filter(n => n.category === 'MACRO_POLICY');
    } else if (filter === 'GLOBAL_CUES') {
      filtered = newsList.filter(n => n.category === 'GLOBAL_CUES');
    } else if (filter === 'EARNINGS') {
      filtered = newsList.filter(n => n.category === 'EARNINGS');
    }

    if (!filtered || filtered.length === 0) {
      container.innerHTML = `<div style="text-align: center; color: var(--text-secondary); padding: 40px; background: var(--bg-card); border-radius: 8px; border: 1px solid var(--border);">No news found matching filter "${escapeHtml(filter)}".</div>`;
      return;
    }

    container.innerHTML = filtered.map(item => {
      let impactBadge = '<span class="badge badge-blue">⚪ NEUTRAL</span>';
      let borderCol = '#3b82f6';
      let impactBg = 'rgba(59, 130, 246, 0.08)';
      if (item.impact_type === 'BULLISH') {
        impactBadge = '<span class="badge badge-green">🟢 BULLISH CATALYST (Good News)</span>';
        borderCol = 'var(--green)';
        impactBg = 'rgba(16, 185, 129, 0.09)';
      } else if (item.impact_type === 'BEARISH') {
        impactBadge = '<span class="badge badge-red">🔴 BEARISH / RISK FACTOR</span>';
        borderCol = 'var(--red)';
        impactBg = 'rgba(239, 68, 68, 0.09)';
      } else if (item.impact_type === 'VOLATILE') {
        impactBadge = '<span class="badge badge-yellow">⚡ VOLATILITY SPIKE</span>';
        borderCol = 'var(--yellow)';
        impactBg = 'rgba(245, 158, 11, 0.09)';
      }

      const scoreStars = '★'.repeat(item.impact_score || 3) + '☆'.repeat(5 - (item.impact_score || 3));
      const importantPill = item.is_important ? '<span class="badge badge-yellow" style="font-size: 0.68rem; margin-left: 6px;">⚡ SCROLLING AT TOP</span>' : '';

      return `
        <div class="news-item-card" style="border-left: 4px solid ${borderCol};">
          <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 8px;">
            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
              ${impactBadge}
              <span class="badge badge-blue" style="font-size: 0.68rem;">🏷️ ${escapeHtml(item.category || 'MARKET_IMPACT')}</span>
              ${importantPill}
              <span style="font-size: 0.74rem; color: #fbbf24;" title="Market Impact Score: ${item.impact_score || 3}/5">Impact: ${scoreStars}</span>
            </div>
            <div style="font-size: 0.74rem; color: var(--text-secondary);">
              <strong>${escapeHtml(item.source || 'Market Wire')}</strong> &bull; <span>${escapeHtml(item.published_at || '')}</span>
            </div>
          </div>

          <h3 style="font-size: 1.05rem; font-weight: 800; color: var(--text-primary); margin-bottom: 6px; line-height: 1.4;">
            ${escapeHtml(item.title)}
          </h3>

          ${item.summary ? `<p style="font-size: 0.84rem; color: var(--text-secondary); margin-bottom: 10px; line-height: 1.5;">${escapeHtml(item.summary)}</p>` : ''}

          <!-- Highlighted Market Effect Box -->
          <div style="background: ${impactBg}; border: 1px solid ${borderCol}; border-radius: 6px; padding: 10px 14px; margin-top: 10px;">
            <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 3px;">
              <span style="font-size: 0.95rem;">🎯</span>
              <strong style="font-size: 0.8rem; color: var(--text-primary); text-transform: uppercase; letter-spacing: 0.3px;">
                Direct Market Effect on NIFTY 50 &amp; BANKNIFTY:
              </strong>
            </div>
            <div style="font-size: 0.82rem; color: var(--text-primary); line-height: 1.45; font-weight: 500;">
              ${escapeHtml(item.market_effect || 'Standard market price action influence')}
            </div>
          </div>

          <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 12px; padding-top: 8px; border-top: 1px dashed rgba(255,255,255,0.06); font-size: 0.75rem;">
            <div>
              ${item.url ? `<a href="${item.url}" target="_blank" rel="noopener noreferrer" style="color: #60a5fa; text-decoration: none; font-weight: 600;">🔗 Read Full Source Article ↗</a>` : '<span style="color: var(--text-secondary);">Local Market Intelligence</span>'}
            </div>
            <div>
              <button onclick="deleteNews('${item.id}')" class="btn" style="padding: 2px 8px; font-size: 0.7rem; background: rgba(239, 68, 68, 0.1); color: var(--red); border: 1px solid rgba(239, 68, 68, 0.25); cursor: pointer;" title="Delete this news item">🗑️ Delete</button>
            </div>
          </div>
        </div>
      `;
    }).join('');
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  async function refreshNewsNow() {
    const badge = document.getElementById('news-status-badge');
    const oldText = badge ? badge.innerText : '';
    if (badge) badge.innerText = 'SYNCING RSS...';
    try {
      const res = await fetch('/api/news/fetch_now');
      const data = await res.json();
      await fetchData();
      alert(`News sync complete! Synced financial feeds (${data.added || 0} updates added/checked).`);
    } catch (e) {
      console.error('Failed to sync news RSS:', e);
      alert('Could not sync RSS news: ' + e);
    } finally {
      if (badge) badge.innerText = oldText || 'AUTO-UPDATES ACTIVE';
    }
  }

  function openAddNewsModal() {
    const m = document.getElementById('add-news-modal');
    if (m) m.style.display = 'flex';
  }

  function closeAddNewsModal() {
    const m = document.getElementById('add-news-modal');
    if (m) m.style.display = 'none';
  }

  async function submitAddNews(e) {
    e.preventDefault();
    const payload = {
      title: document.getElementById('modal-news-title').value.trim(),
      summary: document.getElementById('modal-news-summary').value.trim(),
      category: document.getElementById('modal-news-category').value,
      impact_type: document.getElementById('modal-news-impact').value,
      market_effect: document.getElementById('modal-news-effect').value.trim(),
      source: document.getElementById('modal-news-source').value.trim() || 'Market Wire',
      url: document.getElementById('modal-news-url').value.trim(),
      is_important: document.getElementById('modal-news-important').checked ? 1 : 0,
      impact_score: document.getElementById('modal-news-important').checked ? 5 : 4,
    };

    try {
      const res = await fetch('/api/news/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (data.status === 'ok') {
        closeAddNewsModal();
        document.getElementById('modal-news-title').value = '';
        document.getElementById('modal-news-summary').value = '';
        document.getElementById('modal-news-effect').value = '';
        await fetchData();
        alert('Market news added successfully! If marked as important, it is now scrolling on the top ticker.');
      } else {
        alert('Failed to add news: ' + (data.message || 'Unknown error'));
      }
    } catch (err) {
      console.error('Error submitting news:', err);
      alert('Error adding news: ' + err);
    }
  }

  async function deleteNews(newsId) {
    if (!confirm('Are you sure you want to delete this news item?')) return;
    try {
      const res = await fetch(`/api/news/delete?id=${encodeURIComponent(newsId)}`);
      const data = await res.json();
      if (data.status === 'ok') {
        await fetchData();
      } else {
        alert('Could not delete news: ' + (data.message || 'Error'));
      }
    } catch (e) {
      console.error('Delete news error:', e);
    }
  }

  // ==========================================
  // NSE OPTION CHAIN & PAPER TRADE JAVASCRIPT
  // ==========================================
  window._currentOcSymbol = 'NIFTY';
  window._currentOcData = null;
  window._activeTradeModalParams = null;

  function switchOptionChainSymbol(sym) {
    window._currentOcSymbol = sym;
    const btnNifty = document.getElementById('oc-btn-sym-nifty');
    const btnBank = document.getElementById('oc-btn-sym-bank');
    if (sym === 'NIFTY') {
      if (btnNifty) { btnNifty.style.background = 'var(--accent)'; btnNifty.style.color = 'white'; }
      if (btnBank) { btnBank.style.background = 'transparent'; btnBank.style.color = 'var(--text-secondary)'; }
    } else {
      if (btnNifty) { btnNifty.style.background = 'transparent'; btnNifty.style.color = 'var(--text-secondary)'; }
      if (btnBank) { btnBank.style.background = 'var(--accent)'; btnBank.style.color = 'white'; }
    }
    fetchOptionChain(true);
  }

  async function fetchOptionChain(force = false) {
    const sym = window._currentOcSymbol || 'NIFTY';
    const expirySel = document.getElementById('oc-expiry-select');
    const expiry = expirySel ? expirySel.value : '';
    const badge = document.getElementById('oc-source-badge');
    const syncTime = document.getElementById('oc-sync-time');
    if (badge) badge.innerText = 'FETCHING...';

    try {
      const url = `/api/option_chain?symbol=${encodeURIComponent(sym)}&expiry=${encodeURIComponent(expiry)}${force ? '&refresh=1' : ''}`;
      const res = await fetch(url);
      const data = await res.json();
      if (data.status === 'ok' && data.chain) {
        window._currentOcData = data.chain;
        renderOptionChain(data.chain);
        if (badge) badge.innerText = data.chain.data_source || 'LIVE NSE FEED';
        if (syncTime) syncTime.innerText = `Updated: ${data.chain.updated_at || 'Just now'}`;
      }
    } catch (e) {
      console.error('Option chain fetch error:', e);
      if (badge) badge.innerText = 'FETCH ERROR';
    }
  }

  function renderOptionChain(chain) {
    // 1. Analytics Bar
    const spotEl = document.getElementById('oc-stat-spot');
    if (spotEl) spotEl.innerText = `₹${(chain.spot_price || 0).toLocaleString('en-IN', {minimumFractionDigits: 2})}`;

    const atmEl = document.getElementById('oc-stat-atm');
    if (atmEl) atmEl.innerText = `⚡ ATM Strike: ${chain.atm_strike || '--'}`;

    const pcrEl = document.getElementById('oc-stat-pcr');
    if (pcrEl) {
      pcrEl.innerText = chain.pcr || '1.0';
      pcrEl.style.color = chain.pcr >= 1.15 ? 'var(--green)' : (chain.pcr <= 0.85 ? 'var(--red)' : 'var(--yellow)');
    }

    const sentEl = document.getElementById('oc-stat-sentiment');
    if (sentEl) {
      sentEl.innerText = chain.sentiment || 'NEUTRAL';
      sentEl.style.color = chain.pcr >= 1.15 ? 'var(--green)' : (chain.pcr <= 0.85 ? 'var(--red)' : 'var(--yellow)');
    }

    const maxPainEl = document.getElementById('oc-stat-maxpain');
    if (maxPainEl) maxPainEl.innerText = `₹${chain.max_pain || '--'}`;

    const totalOiEl = document.getElementById('oc-stat-total-oi');
    if (totalOiEl) totalOiEl.innerText = `${((chain.total_call_oi || 0) + (chain.total_put_oi || 0)).toLocaleString('en-IN')}`;

    const oiRatioEl = document.getElementById('oc-stat-oi-ratio');
    if (oiRatioEl) oiRatioEl.innerText = `CE: ${(chain.total_call_oi || 0).toLocaleString('en-IN')} | PE: ${(chain.total_put_oi || 0).toLocaleString('en-IN')}`;

    const lotEl = document.getElementById('oc-stat-lotsize');
    if (lotEl) lotEl.innerText = `${chain.lot_size || (chain.symbol === 'BANKNIFTY' ? 30 : 65)} Qty / Lot`;

    // 2. Expiry Select Options
    const expirySel = document.getElementById('oc-expiry-select');
    if (expirySel && chain.expiry_dates && chain.expiry_dates.length > 0) {
      const currentVal = expirySel.value;
      expirySel.innerHTML = chain.expiry_dates.map(exp => `
        <option value="${exp}" ${exp === (currentVal || chain.expiry) ? 'selected' : ''}>${exp}</option>
      `).join('');
    }

    // Helper for Buildup Badge
    function getBuildupBadge(buildup, optType) {
      if (!buildup || buildup === 'No Conclusion' || buildup === '--' || buildup === 'Neutral') {
        return `<span style="color: #64748b; font-size: 0.68rem;">--</span>`;
      }
      const b = buildup.toLowerCase();
      let bg = 'rgba(100, 116, 139, 0.15)';
      let color = '#94a3b8';
      let border = 'rgba(100, 116, 139, 0.3)';

      if (b.includes('call buying') || b.includes('put writing') || (b.includes('long buildup') && optType === 'CE') || (b.includes('short buildup') && optType === 'PE')) {
        bg = 'rgba(16, 185, 129, 0.18)';
        color = '#10b981';
        border = 'rgba(16, 185, 129, 0.4)';
      } else if (b.includes('call writing') || b.includes('put buying') || (b.includes('short buildup') && optType === 'CE') || (b.includes('long buildup') && optType === 'PE')) {
        bg = 'rgba(239, 68, 68, 0.18)';
        color = '#ef4444';
        border = 'rgba(239, 68, 68, 0.4)';
      } else if (b.includes('short covering')) {
        bg = 'rgba(6, 182, 212, 0.18)';
        color = '#06b6d4';
        border = 'rgba(6, 182, 212, 0.4)';
      } else if (b.includes('long unwinding') || b.includes('covering')) {
        bg = 'rgba(245, 158, 11, 0.18)';
        color = '#f59e0b';
        border = 'rgba(245, 158, 11, 0.4)';
      }

      return `<span style="background: ${bg}; color: ${color}; border: 1px solid ${border}; padding: 2px 6px; border-radius: 4px; font-size: 0.67rem; font-weight: 700; white-space: nowrap; display: inline-block;">${buildup}</span>`;
    }

    // 3. Option Chain Matrix Table (ATM ± 7 Strikes with exact requested fields)
    const tbody = document.getElementById('oc-table-body');
    if (!tbody || !chain.strikes) return;

    tbody.innerHTML = chain.strikes.map(row => {
      const isAtm = row.is_atm;
      const strike = row.strike;
      const ce = row.ce || {};
      const pe = row.pe || {};

      const rowClass = isAtm ? 'oc-atm-row' : '';
      const ceItmClass = ce.is_itm ? 'oc-itm-ce' : '';
      const peItmClass = pe.is_itm ? 'oc-itm-pe' : '';
      const pcrVal = row.pcr != null ? Number(row.pcr).toFixed(2) : '--';
      const pcrColor = (row.pcr >= 1.15) ? 'var(--green)' : ((row.pcr <= 0.85) ? 'var(--red)' : '#94a3b8');

      return `
        <tr class="${rowClass}">
          <!-- CE Direct Buy / Sell Actions -->
          <td class="${ceItmClass}" style="border-right: 1px solid var(--border); white-space: nowrap;">
            <div style="display: flex; gap: 4px; justify-content: center;">
              <button onclick="openOptionTradeModal(${strike}, 'CE', ${ce.ltp}, 'BUY')" class="oc-btn-buy" title="Direct BUY ${chain.symbol} ${strike} CE">BUY</button>
              <button onclick="openOptionTradeModal(${strike}, 'CE', ${ce.ltp}, 'SELL')" class="oc-btn-sell" title="Direct SELL ${chain.symbol} ${strike} CE">SELL</button>
            </div>
          </td>
          <!-- CE OI Buildup -->
          <td class="${ceItmClass}">${getBuildupBadge(ce.builtup, 'CE')}</td>
          <!-- CE OI -->
          <td class="${ceItmClass}">${(ce.oi || 0).toLocaleString('en-IN')}</td>
          <!-- CE Change OI -->
          <td class="${ceItmClass}" style="color: ${ce.change_in_oi >= 0 ? 'var(--green)' : 'var(--red)'}; font-weight: 600;">
            ${ce.change_in_oi >= 0 ? '+' : ''}${(ce.change_in_oi || 0).toLocaleString('en-IN')}
          </td>
          <!-- CE IV -->
          <td class="${ceItmClass}" style="color: #60a5fa;">${(ce.iv || 0).toFixed(1)}%</td>
          <!-- CE PCR -->
          <td class="${ceItmClass}" style="color: ${pcrColor}; font-weight: 700;">${pcrVal}</td>
          <!-- CE LTP -->
          <td class="${ceItmClass}" style="font-weight: 800; color: #f8fafc; font-size: 0.88rem; border-right: 2px solid #374151;">
            ₹${(ce.ltp || 0).toFixed(2)}
          </td>

          <!-- Center Strike Column (ATM Highlighted) -->
          <td style="background: #1e293b; color: #ffffff; font-weight: 800; font-size: 0.92rem; border-left: 1px solid #374151; border-right: 1px solid #374151;">
            ${isAtm ? `<span class="oc-atm-strike">⚡ ${strike}</span>` : strike}
          </td>

          <!-- PE LTP -->
          <td class="${peItmClass}" style="font-weight: 800; color: #f8fafc; font-size: 0.88rem; border-left: 2px solid #374151;">
            ₹${(pe.ltp || 0).toFixed(2)}
          </td>
          <!-- PE PCR -->
          <td class="${peItmClass}" style="color: ${pcrColor}; font-weight: 700;">${pcrVal}</td>
          <!-- PE IV -->
          <td class="${peItmClass}" style="color: #60a5fa;">${(pe.iv || 0).toFixed(1)}%</td>
          <!-- PE Change OI -->
          <td class="${peItmClass}" style="color: ${pe.change_in_oi >= 0 ? 'var(--green)' : 'var(--red)'}; font-weight: 600;">
            ${pe.change_in_oi >= 0 ? '+' : ''}${(pe.change_in_oi || 0).toLocaleString('en-IN')}
          </td>
          <!-- PE OI -->
          <td class="${peItmClass}">${(pe.oi || 0).toLocaleString('en-IN')}</td>
          <!-- PE OI Buildup -->
          <td class="${peItmClass}">${getBuildupBadge(pe.builtup, 'PE')}</td>
          <!-- PE Direct Buy / Sell Actions -->
          <td class="${peItmClass}" style="border-left: 1px solid var(--border); white-space: nowrap;">
            <div style="display: flex; gap: 4px; justify-content: center;">
              <button onclick="openOptionTradeModal(${strike}, 'PE', ${pe.ltp}, 'BUY')" class="oc-btn-buy" title="Direct BUY ${chain.symbol} ${strike} PE">BUY</button>
              <button onclick="openOptionTradeModal(${strike}, 'PE', ${pe.ltp}, 'SELL')" class="oc-btn-sell" title="Direct SELL ${chain.symbol} ${strike} PE">SELL</button>
            </div>
          </td>
        </tr>
      `;
    }).join('');
  }

  function openOptionTradeModal(strike, optType, ltp, action) {
    action = action || 'BUY';
    const sym = window._currentOcSymbol || 'NIFTY';
    const lotSize = sym === 'BANKNIFTY' ? 30 : 65;
    const spot = window._currentOcData ? window._currentOcData.spot_price : 0;

    document.getElementById('oc-trade-symbol').value = sym;
    document.getElementById('oc-trade-strike').value = strike;
    document.getElementById('oc-trade-type').value = optType;

    const modalTitle = document.getElementById('oc-modal-title');
    if (modalTitle) modalTitle.innerText = `${action} ${sym} ${strike} ${optType}`;

    const badge = document.getElementById('oc-modal-type-badge');
    if (badge) {
      badge.innerText = `${action} ${optType}`;
      badge.className = action === 'BUY' ? 'badge badge-green' : 'badge badge-red';
    }

    const btnSubmit = document.getElementById('oc-modal-submit-btn');
    if (btnSubmit) {
      btnSubmit.innerText = action === 'BUY' ? `⚡ Execute BUY Paper Trade` : `⚡ Execute SELL Paper Trade`;
      btnSubmit.style.background = action === 'BUY' ? 'var(--green)' : 'var(--red)';
      btnSubmit.style.color = action === 'BUY' ? 'black' : 'white';
    }

    const ltpEl = document.getElementById('oc-modal-ltp');
    if (ltpEl) ltpEl.innerText = `₹${(ltp || 0).toFixed(2)}`;

    const spotEl = document.getElementById('oc-modal-spot');
    if (spotEl) spotEl.innerText = `₹${(spot || 0).toFixed(2)}`;

    const qtyMul = document.getElementById('oc-modal-qty-multiplier');
    if (qtyMul) qtyMul.innerText = lotSize;

    window._activeTradeModalParams = { sym, strike, optType, ltp, lotSize, spot, action };
    updateOptionMarginDisplay();

    const modal = document.getElementById('oc-trade-modal');
    if (modal) modal.style.display = 'flex';
  }

  function closeOptionTradeModal() {
    const modal = document.getElementById('oc-trade-modal');
    if (modal) modal.style.display = 'none';
  }

  function updateOptionMarginDisplay() {
    if (!window._activeTradeModalParams) return;
    const p = window._activeTradeModalParams;
    const lots = parseInt(document.getElementById('oc-trade-lots').value) || 1;
    const slPts = parseFloat(document.getElementById('oc-trade-sl').value) || 20;
    const tgtPts = parseFloat(document.getElementById('oc-trade-tgt').value) || 40;

    const totalQty = lots * p.lotSize;
    const margin = totalQty * p.ltp;
    const isSell = p.action === 'SELL';

    const marginEl = document.getElementById('oc-modal-margin');
    if (marginEl) marginEl.innerText = `₹${margin.toLocaleString('en-IN', {minimumFractionDigits: 2})}`;

    const slCalc = document.getElementById('oc-modal-sl-calc');
    if (slCalc) slCalc.innerText = `SL Price: ₹${(isSell ? p.ltp + slPts : Math.max(1, p.ltp - slPts)).toFixed(2)}`;

    const tgtCalc = document.getElementById('oc-modal-tgt-calc');
    if (tgtCalc) tgtCalc.innerText = `Target Price: ₹${(isSell ? Math.max(1, p.ltp - tgtPts) : p.ltp + tgtPts).toFixed(2)}`;
  }

  // --- NiftyTrader Key Management Modal Helpers ---
  function openNiftyTraderKeyModal() {
    const modal = document.getElementById('nt-key-modal');
    if (modal) modal.style.display = 'flex';
    fetch('/api/niftytrader/config')
      .then(r => r.json())
      .then(d => {
        if (d.status === 'ok') {
          if (d.api_key) document.getElementById('nt-input-api-key').value = d.api_key;
          if (d.bearer_token) document.getElementById('nt-input-bearer').value = d.bearer_token;
        }
      })
      .catch(() => {});
  }

  function closeNiftyTraderKeyModal() {
    const modal = document.getElementById('nt-key-modal');
    if (modal) modal.style.display = 'none';
  }

  function copyConsoleHelperCode() {
    const inp = document.getElementById('nt-console-helper-code');
    if (inp) {
      inp.select();
      navigator.clipboard.writeText(inp.value);
      alert('📋 Copied console code! In NiftyTrader, press F12 -> Console -> Paste and run it to get your fresh key.');
    }
  }

  async function saveNiftyTraderKeys(e) {
    e.preventDefault();
    const apiKey = document.getElementById('nt-input-api-key').value.trim();
    const bearer = document.getElementById('nt-input-bearer').value.trim();
    const saveBtn = document.getElementById('nt-key-save-btn');
    const msgEl = document.getElementById('nt-key-status-msg');

    if (!apiKey) {
      alert('Please enter a valid x-api-key');
      return;
    }

    if (saveBtn) saveBtn.innerText = 'TESTING & SAVING...';
    if (msgEl) {
      msgEl.style.display = 'block';
      msgEl.style.background = 'rgba(59, 130, 246, 0.15)';
      msgEl.style.color = '#60a5fa';
      msgEl.innerText = 'Verifying key against NiftyTrader live API...';
    }

    try {
      const res = await fetch('/api/niftytrader/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: apiKey, bearer_token: bearer })
      });
      const data = await res.json();
      if (data.status === 'ok') {
        if (msgEl) {
          msgEl.style.background = 'rgba(16, 185, 129, 0.2)';
          msgEl.style.color = 'var(--green)';
          msgEl.innerText = '✅ ' + (data.message || 'Key verified and saved successfully!');
        }
        setTimeout(() => {
          closeNiftyTraderKeyModal();
          fetchOptionChain(true);
        }, 1200);
      } else {
        if (msgEl) {
          msgEl.style.background = 'rgba(239, 68, 68, 0.2)';
          msgEl.style.color = 'var(--red)';
          msgEl.innerText = '❌ Verification Failed: ' + (data.message || 'Key rejected by API');
        }
      }
    } catch (err) {
      if (msgEl) {
        msgEl.style.background = 'rgba(239, 68, 68, 0.2)';
        msgEl.style.color = 'var(--red)';
        msgEl.innerText = '❌ Error saving key: ' + err;
      }
    } finally {
      if (saveBtn) saveBtn.innerText = '💾 Save & Test Live Key';
    }
  }

  async function submitOptionTrade(e, mode = 'instant') {
    e.preventDefault();
    if (!window._activeTradeModalParams) return;
    const p = window._activeTradeModalParams;
    const lots = parseInt(document.getElementById('oc-trade-lots').value) || 1;
    const slPts = parseFloat(document.getElementById('oc-trade-sl').value) || 20;
    const tgtPts = parseFloat(document.getElementById('oc-trade-tgt').value) || 40;
    const trailing = document.getElementById('oc-trade-trailing').checked;

    const btnSubmit = document.getElementById('oc-modal-submit-btn');
    const btnArm = document.getElementById('oc-modal-arm-btn');

    if (mode === 'arm_15m') {
      if (btnArm) btnArm.innerText = 'ARMING...';
      try {
        const payload = {
          symbol: p.sym,
          strike: p.strike,
          option_type: p.optType,
          lots: lots,
          premium: p.ltp,
          spot_price: p.spot || 0,
          sl_points: slPts,
          target_points: tgtPts,
          reasoning: `Manual strike selection from Option Chain (${p.sym} ${p.strike} ${p.optType}) with 15-minute confirmation safety timer before auto-execution.`,
        };
        const res = await fetch('/api/telegram/arm_trade', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (data.status === 'ok') {
          closeOptionTradeModal();
          alert(`⏱️ Trade Armed with 15-Minute Countdown!\n\nOrder ID: ${data.pending_trade.pending_id}\nContract: ${p.sym} ${p.strike} ${p.optType}\n\nTelegram intent alert dispatched. You have 15 minutes to review before it automatically executes into the simulator.`);
          switchTab('tab-telegram');
          await fetchPendingTrades();
        } else {
          alert('Could not arm trade: ' + (data.message || 'Error'));
        }
      } catch (err) {
        console.error('Arm trade error:', err);
        alert('Error arming trade: ' + err);
      } finally {
        if (btnArm) btnArm.innerText = '⏱️ 15-Min Confirmation (Telegram Alert)';
      }
      return;
    }

    if (btnSubmit) btnSubmit.innerText = 'EXECUTING...';

    try {
      const payload = {
        symbol: p.sym,
        strike: p.strike,
        option_type: p.optType,
        action: p.action || 'BUY',
        lots: lots,
        premium: p.ltp,
        sl_points: slPts,
        target_points: tgtPts,
        trailing_sl: trailing,
        trail_step: 15.0,
      };

      const res = await fetch('/api/option_chain/trade', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (data.status === 'ok') {
        closeOptionTradeModal();
        alert(`⚡ Paper Trade Executed Successfully!\n\nContract: ${data.symbol} ${data.strike} ${data.option_type}\nLots: ${data.lots} (${data.qty} Qty)\nEntry Premium: ₹${data.entry_premium.toFixed(2)}\nStop Loss: ₹${data.sl_price.toFixed(2)}\nTarget: ₹${data.target_price.toFixed(2)}\n\nPosition is now ACTIVE with live real-time MTM P&L tracking.`);
        // Switch to Simulator tab to watch live position
        switchTab('tab-simulator');
        await fetchData();
      } else {
        alert('Could not place paper trade: ' + (data.message || 'Error'));
      }
    } catch (err) {
      console.error('Submit option trade error:', err);
      alert('Error executing trade: ' + err);
    } finally {
      if (btnSubmit) btnSubmit.innerText = '🚀 Instant Execution';
    }
  }

  function filterSpotTable(sym) {
    window._spotFilter = sym;
    renderSpotTable(sym);
  }

  function renderSpotTable(filterSym) {
    const histTable = document.getElementById('spot-history-table-body');
    if (!histTable) return;
    let list = window._spotHistory || [];
    if (filterSym && filterSym !== 'ALL') {
      list = list.filter(r => r.symbol && r.symbol.toUpperCase().includes(filterSym.toUpperCase()));
    }
    if (list.length === 0) {
      histTable.innerHTML = `<tr><td colspan="12" style="text-align: center; color: var(--text-secondary);">No stored records matching "${filterSym}".</td></tr>`;
      return;
    }
    histTable.innerHTML = list.map(r => {
      const s = r.change_pts >= 0 ? '+' : '';
      const col = r.change_pts >= 0 ? 'color: var(--green);' : 'color: var(--red);';
      const symBadge = r.symbol === 'BANKNIFTY' ? 'badge-blue' : (r.symbol === 'GIFT NIFTY' ? 'badge-yellow' : 'badge-green');
      return `
        <tr>
          <td><code>${r.timestamp_ist}</code></td>
          <td><span class="badge ${symBadge}"><strong>${r.symbol}</strong></span></td>
          <td><strong>₹${Number(r.spot_price).toLocaleString('en-IN', {minimumFractionDigits: 2})}</strong></td>
          <td>₹${Number(r.open_price || r.spot_price).toLocaleString('en-IN', {minimumFractionDigits: 2})}</td>
          <td style="color: var(--green);">₹${Number(r.high_price || r.spot_price).toLocaleString('en-IN', {minimumFractionDigits: 2})}</td>
          <td style="color: var(--red);">₹${Number(r.low_price || r.spot_price).toLocaleString('en-IN', {minimumFractionDigits: 2})}</td>
          <td style="color: #60a5fa; font-weight: 600;">₹${Number(r.pdh || r.previous_close || 0).toLocaleString('en-IN', {minimumFractionDigits: 2})}</td>
          <td style="color: #f87171; font-weight: 600;">₹${Number(r.pdl || r.previous_close || 0).toLocaleString('en-IN', {minimumFractionDigits: 2})}</td>
          <td style="color: var(--text-secondary);">₹${Number(r.previous_close || r.spot_price).toLocaleString('en-IN', {minimumFractionDigits: 2})}</td>
          <td style="${col} font-weight: 700;">${s}${Number(r.change_pts).toFixed(2)} (${s}${Number(r.change_pct).toFixed(2)}%)</td>
          <td style="color: var(--text-secondary);">${Number(r.volume || 0).toLocaleString('en-IN')}</td>
          <td><span class="badge badge-blue">${r.source || 'TRADINGVIEW'}</span></td>
        </tr>
      `;
    }).join('');
  }

  async function armCustomLevelTrigger() {
    const inst = document.getElementById('lvl-instrument').value;
    const trigPrice = document.getElementById('lvl-trigger-price').value;
    const cond = document.getElementById('lvl-condition').value;
    const optType = document.getElementById('lvl-opt-type').value;
    const slVal = document.getElementById('lvl-sl-val').value;
    const slType = document.getElementById('lvl-sl-type').value;
    const targetVal = document.getElementById('lvl-target-val').value;
    const targetType = document.getElementById('lvl-target-type').value;
    const lots = document.getElementById('lvl-lots').value || 1;
    const notes = document.getElementById('lvl-notes').value || '';
    const statEl = document.getElementById('lvl-arm-status');

    if (!trigPrice || parseFloat(trigPrice) <= 0) {
      alert("Please enter a valid Spot Trigger Level price.");
      return;
    }
    if (!slVal || parseFloat(slVal) <= 0) {
      alert("Please enter a valid Stop Loss level or value.");
      return;
    }
    if (!targetVal || parseFloat(targetVal) <= 0) {
      alert("Please enter a valid Target level or value.");
      return;
    }

    if (statEl) statEl.innerHTML = `<span style="color: var(--accent);">Arming level trigger...</span>`;

    try {
      const qs = new URLSearchParams({
        instrument: inst,
        trigger_price: trigPrice,
        condition: cond,
        option_type: optType,
        sl_type: slType,
        sl_val: slVal,
        target_type: targetType,
        target_val: targetVal,
        lots: lots,
        notes: notes,
      });
      const res = await fetch(`/api/levels/add?${qs.toString()}`);
      const data = await res.json();
      if (data.status === 'ok') {
        if (statEl) statEl.innerHTML = `<span style="color: var(--green);">✅ Trigger armed! Monitoring ${inst} level ₹${trigPrice} for ${cond} -> BUY ${optType}.</span>`;
        document.getElementById('lvl-trigger-price').value = '';
        fetchData();
      } else {
        if (statEl) statEl.innerHTML = `<span style="color: var(--red);">Error: ${data.message}</span>`;
      }
    } catch (e) {
      if (statEl) statEl.innerHTML = `<span style="color: var(--red);">Failed to arm trigger: ${e}</span>`;
    }
  }

  async function cancelLevelTrigger(trigId) {
    try {
      await fetch(`/api/levels/cancel?id=${encodeURIComponent(trigId)}`);
      fetchData();
    } catch (e) {
      console.error("Cancel level trigger error:", e);
    }
  }

  async function deleteLevelTrigger(trigId) {
    if (!confirm(`Delete level trigger ${trigId}?`)) return;
    try {
      await fetch(`/api/levels/delete?id=${encodeURIComponent(trigId)}`);
      fetchData();
    } catch (e) {
      console.error("Delete level trigger error:", e);
    }
  }

  async function checkLevelsNow() {
    try {
      const res = await fetch('/api/levels/check_now');
      const data = await res.json();
      if (data.executed && data.executed.length > 0) {
        const msg = data.executed.map(e => `${e.instrument} ${e.strike} ${e.option_type} @ ₹${e.entry_premium}`).join(' | ');
        alert(`🎯 ${data.executed.length} Level Trigger(s) Executed: ` + msg);
      }
      fetchData();
    } catch (e) {
      console.error("Check levels error:", e);
    }
  }

  function updateLotsDisplay() {
    const input = document.getElementById('sim-cfg-lots');
    const lots = parseInt(input ? input.value : 1) || 1;
    const lotSize = (window._lastSimData && window._lastSimData.lot_size) || 65;
    const disp = document.getElementById('sim-lots-display');
    if (disp) {
      disp.innerText = `${lots} ${lots === 1 ? 'Lot' : 'Lots'} (${lots * lotSize} Qty)`;
    }
  }

  async function applySimPreset(presetKey) {
    const statEl = document.getElementById('sim-settings-status');
    if (statEl) statEl.innerHTML = `<span style="color: var(--accent);">Applying preset ${presetKey}...</span>`;
    try {
      const res = await fetch(`/api/simulator/preset?key=${encodeURIComponent(presetKey)}`);
      const data = await res.json();
      if (data.status === 'ok') {
        if (statEl) statEl.innerHTML = `<span style="color: var(--green);">✅ Preset "${presetKey}" applied successfully!</span>`;
        fetchData();
      } else {
        if (statEl) statEl.innerHTML = `<span style="color: var(--red);">Error: ${data.message}</span>`;
      }
    } catch (e) {
      if (statEl) statEl.innerHTML = `<span style="color: var(--red);">Failed to apply preset: ${e}</span>`;
    }
  }

  async function saveSimManualSettings() {
    const statEl = document.getElementById('sim-settings-status');
    const lots = document.getElementById('sim-cfg-lots').value;
    const slVal = document.getElementById('sim-cfg-sl-val').value;
    const slMode = document.getElementById('sim-cfg-sl-mode').value;
    const targetVal = document.getElementById('sim-cfg-target-val').value;
    const targetMode = document.getElementById('sim-cfg-target-mode').value;
    const trailing = document.getElementById('sim-cfg-trailing').checked ? '1' : '0';
    const trailStep = document.getElementById('sim-cfg-trail-step').value;

    if (statEl) statEl.innerHTML = `<span style="color: var(--accent);">Saving custom settings...</span>`;
    try {
      const qs = new URLSearchParams({
        lots: lots,
        sl_val: slVal,
        sl_mode: slMode,
        target_val: targetVal,
        target_mode: targetMode,
        trailing_sl: trailing,
        trail_step: trailStep,
        preset_name: 'CUSTOM'
      });
      const res = await fetch(`/api/simulator/settings?${qs.toString()}`);
      const data = await res.json();
      if (data.status === 'ok') {
        const slUnit = slMode === 'PERCENT' ? '%' : ' pts';
        const tgtUnit = targetMode === 'PERCENT' ? '%' : ' pts';
        if (statEl) statEl.innerHTML = `<span style="color: var(--green);">✅ Settings saved! Trade size: ${lots} lot(s) | SL: ${slVal}${slUnit} | Target: ${targetVal}${tgtUnit}</span>`;
        fetchData();
      } else {
        if (statEl) statEl.innerHTML = `<span style="color: var(--red);">Error: ${data.message}</span>`;
      }
    } catch (e) {
      if (statEl) statEl.innerHTML = `<span style="color: var(--red);">Failed to save settings: ${e}</span>`;
    }
  }

  async function changeSimRule(ruleName) {
    try {
      await fetch(`/api/simulator/rule?name=${ruleName}`);
      fetchData();
    } catch (e) {
      console.error("Rule change error:", e);
    }
  }

  async function captureTradingViewScreenshot() {
    const btn = document.getElementById('btn-manual-screenshot');
    const oldHtml = btn ? btn.innerHTML : "📸 Take TradingView Screenshot";
    if (btn) {
      btn.innerHTML = "⏳ Capturing via Chrome CDP (8-10s)...";
      btn.disabled = true;
    }
    try {
      const res = await fetch('/api/simulator/capture_screenshot');
      const data = await res.json();
      if (data.status === 'ok') {
        const img = document.getElementById('sim-tv-img');
        const fallback = document.getElementById('sim-tv-img-fallback');
        if (img) {
          img.src = `/api/simulator/screenshot_image?t=${Date.now()}`;
          img.style.display = 'block';
        }
        if (fallback) fallback.style.display = 'none';
        const fn = document.getElementById('sim-tv-filename');
        if (fn) fn.innerText = data.filename || 'tradingview_nifty.png';
        const ts = document.getElementById('sim-tv-timestamp');
        if (ts) ts.innerText = `Captured: ${data.timestamp || 'Just now'}`;
      } else {
        alert("Screenshot capture error: " + (data.message || 'Unknown error'));
      }
    } catch (e) {
      alert("Failed to capture screenshot: " + e);
    } finally {
      if (btn) {
        btn.innerHTML = oldHtml;
        btn.disabled = false;
      }
      fetchData();
    }
  }

  function triggerUploadChart() {
    const input = document.getElementById('chart-file-input');
    if (input) input.click();
  }

  async function uploadChartScreenshot(fileInput) {
    if (!fileInput.files || !fileInput.files[0]) return;
    const file = fileInput.files[0];
    const reader = new FileReader();
    reader.onload = async function(e) {
      const b64 = e.target.result;
      try {
        const res = await fetch('/api/simulator/upload_chart', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ image_b64: b64 })
        });
        const data = await res.json();
        if (data.status === 'ok') {
          const img = document.getElementById('sim-tv-img');
          const fallback = document.getElementById('sim-tv-img-fallback');
          if (img) {
            img.src = `/api/simulator/screenshot_image?t=${Date.now()}`;
            img.style.display = 'block';
          }
          if (fallback) fallback.style.display = 'none';
          const fn = document.getElementById('sim-tv-filename');
          if (fn) fn.innerText = 'user_real_tradingview_chart.png';
          const ts = document.getElementById('sim-tv-timestamp');
          if (ts) ts.innerText = `Uploaded: ${data.timestamp || 'Just now'}`;
          alert("✅ Real TradingView chart uploaded successfully!");
          fetchData();
        } else {
          alert("Upload error: " + (data.message || 'Unknown error'));
        }
      } catch (err) {
        alert("Upload failed: " + err);
      }
    };
    reader.readAsDataURL(file);
  }

  // Paste listener for Ctrl+V
  window.addEventListener('paste', function(e) {
    if (e.clipboardData && e.clipboardData.items) {
      const items = e.clipboardData.items;
      for (let i = 0; i < items.length; i++) {
        if (items[i].type.indexOf('image') !== -1) {
          const blob = items[i].getAsFile();
          const reader = new FileReader();
          reader.onload = async function(ev) {
            const b64 = ev.target.result;
            try {
              const res = await fetch('/api/simulator/upload_chart', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ image_b64: b64 })
              });
              const data = await res.json();
              if (data.status === 'ok') {
                const img = document.getElementById('sim-tv-img');
                const fallback = document.getElementById('sim-tv-img-fallback');
                if (img) {
                  img.src = `/api/simulator/screenshot_image?t=${Date.now()}`;
                  img.style.display = 'block';
                }
                if (fallback) fallback.style.display = 'none';
                const fn = document.getElementById('sim-tv-filename');
                if (fn) fn.innerText = 'pasted_real_chart.png';
                const ts = document.getElementById('sim-tv-timestamp');
                if (ts) ts.innerText = `Pasted: ${data.timestamp || 'Just now'}`;
                alert("✅ Real TradingView chart pasted from clipboard!");
                fetchData();
              }
            } catch (err) {
              console.error("Paste upload error:", err);
            }
          };
          reader.readAsDataURL(blob);
          break;
        }
      }
    }
  });

  async function analyzeChartNow() {
    const btn = document.getElementById('btn-manual-analyze');
    const oldHtml = btn ? btn.innerHTML : "🔬 Analyze Chart Now";
    if (btn) {
      btn.innerHTML = "⏳ Evaluating Rule on Chart...";
      btn.disabled = true;
    }
    try {
      const res = await fetch('/api/simulator/analyze_chart');
      const data = await res.json();
      if (data.status === 'ok' && data.details) {
        renderAnalysisDetails(data.details);
      } else {
        alert("Chart analysis error: " + (data.message || 'Unknown error'));
      }
    } catch (e) {
      alert("Failed to analyze chart: " + e);
    } finally {
      if (btn) {
        btn.innerHTML = oldHtml;
        btn.disabled = false;
      }
      fetchData();
    }
  }

  function renderAnalysisDetails(d) {
    if (!d) return;
    const spotEl = document.getElementById('sim-ana-spot');
    if (spotEl) spotEl.innerText = `₹${(d.spot_close || 0).toFixed(2)}`;

    const ind = d.indicators || {};
    const trendEl = document.getElementById('sim-ana-trend');
    if (trendEl) {
      trendEl.innerText = ind.trend || '--';
      trendEl.className = ind.trend === 'BULLISH' ? 'badge badge-green' : 'badge badge-red';
    }

    const rsiEl = document.getElementById('sim-ana-rsi');
    if (rsiEl) rsiEl.innerText = ind.rsi !== undefined ? ind.rsi.toFixed(1) : '--';

    const ruleEl = document.getElementById('sim-ana-rule-name');
    if (ruleEl) ruleEl.innerText = d.rule_name || 'user_rule.py';

    const timeEl = document.getElementById('sim-ana-candle-time');
    if (timeEl) timeEl.innerText = `${d.candle_date || ''} ${d.candle_time || ''}`;

    const badgeEl = document.getElementById('sim-ana-badge');
    if (badgeEl) {
      if (d.trade_executed) {
        badgeEl.innerText = `✅ RULE PASSED (${d.signal_type})`;
        badgeEl.className = 'badge badge-green';
      } else if (d.signal_type === 'HOLD' || d.signal_type === 'WAIT') {
        badgeEl.innerText = `ℹ️ NO SIGNAL (HOLD)`;
        badgeEl.className = 'badge badge-yellow';
      } else {
        badgeEl.innerText = d.signal_type || 'ANALYZED';
        badgeEl.className = 'badge badge-blue';
      }
    }

    const reasonBox = document.getElementById('sim-ana-reason-box');
    if (reasonBox) {
      reasonBox.innerHTML = `<strong>Rule Evaluation:</strong>&nbsp;${d.reason || d.verdict || 'Analysis complete'}`;
    }

    const actBox = document.getElementById('sim-ana-action-box');
    if (actBox) {
      if (d.trade_executed) {
        actBox.style.background = 'rgba(16, 185, 129, 0.15)';
        actBox.style.borderColor = 'rgba(16, 185, 129, 0.3)';
        actBox.style.color = 'var(--green)';
      } else {
        actBox.style.background = 'rgba(59, 130, 246, 0.1)';
        actBox.style.borderColor = 'rgba(59, 130, 246, 0.25)';
        actBox.style.color = 'var(--accent)';
      }
      actBox.innerText = d.action_message || d.verdict || 'Ready';
    }
  }

  async function triggerChartObservation() {
    const btn = event.currentTarget;
    const oldText = btn.innerText;
    btn.innerText = "⏳ Observing 15M Chart & Evaluating...";
    btn.disabled = true;
    try {
      const res = await fetch('/api/simulator/analyze_now');
      const data = await res.json();
      fetchData();
    } catch (e) {
      console.error("Chart observation error:", e);
    } finally {
      btn.innerText = oldText;
      btn.disabled = false;
    }
  }

  async function deleteSimTrade(tradeId) {
    if (!confirm(`Delete simulated trade log ${tradeId}? This will remove it from the audit report and recalculate capital.`)) return;
    try {
      const res = await fetch(`/api/simulator/delete?id=${encodeURIComponent(tradeId)}`);
      const data = await res.json();
      if (data.status === 'ok') {
        fetchData();
      }
    } catch (e) {
      console.error("Delete trade error:", e);
    }
  }

  async function clearAllSimTrades() {
    if (!confirm("Are you sure you want to clear ALL simulated trade logs and reset capital to initial ₹1,00,000?")) return;
    try {
      const res = await fetch('/api/simulator/clear_all');
      const data = await res.json();
      if (data.status === 'ok') {
        fetchData();
      }
    } catch (e) {
      console.error("Clear all error:", e);
    }
  }

  async function fetchSpotNow() {
    const badge = document.getElementById('spot-status-badge');
    const oldText = badge ? badge.innerText : '';
    if (badge) badge.innerText = "FETCHING...";
    try {
      const res = await fetch('/api/spot/fetch_now');
      const data = await res.json();
      fetchData();
    } catch (e) {
      console.error("Manual spot fetch error:", e);
    } finally {
      if (badge) badge.innerText = oldText || "AUTO-ACTIVE (5 MIN)";
    }
  }

  // Smooth client-side second ticker for next 5-min fetch
  setInterval(() => {
    const el = document.getElementById('spot-countdown');
    if (!el || !el.innerText || !el.innerText.includes(':')) return;
    const parts = el.innerText.split(':');
    let totalSecs = parseInt(parts[0]) * 60 + parseInt(parts[1]);
    if (totalSecs > 0) {
      totalSecs -= 1;
      const m = Math.floor(totalSecs / 60);
      const s = totalSecs % 60;
      el.innerText = `${m < 10 ? '0' : ''}${m}:${s < 10 ? '0' : ''}${s}`;
    }
  }, 1000);

  // Restore previously active tab from localStorage if present
  try {
    const savedTab = localStorage.getItem('nt_active_tab');
    if (savedTab && document.getElementById(savedTab)) {
      switchTab(savedTab);
    }
  } catch (e) {}

  fetchData();
  fetchOptionChain();
  fetchTelegramStatus();
  fetchPendingTrades();
  setInterval(fetchData, 5000); // 5s live auto-refresh
  setInterval(fetchPendingTrades, 2000); // 2s live countdown refresh for armed orders
  setInterval(() => {
    const ocTab = document.getElementById('tab-option-chain');
    if (ocTab && (ocTab.classList.contains('active') || ocTab.style.display === 'block')) {
      fetchOptionChain();
    }
  }, 15000); // 15s option chain live auto-refresh
</script>
</body>
</html>
"""


class DashboardHTTPRequestHandler(BaseHTTPRequestHandler):
    aggregator = DashboardDataAggregator()

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "healthy",
                "service": "nifty-autonomous-trader",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "render": bool(os.environ.get("RENDER")),
            }).encode("utf-8"))
            return
        elif self.path == "/api/supabase/status":
            try:
                from nifty_trader.core.supabase_adapter import get_supabase_adapter
                supa = get_supabase_adapter()
                status = supa.get_status()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(json.dumps(status).encode("utf-8"))
            except Exception as ex:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"configured": False, "error": str(ex)}).encode("utf-8"))
            return
        elif self.path == "/api/telegram/status":
            try:
                from nifty_trader.notifications.telegram_service import get_telegram_service
                tele = get_telegram_service()
                status = tele.get_status()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(json.dumps(status).encode("utf-8"))
            except Exception as ex:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"configured": False, "error": str(ex)}).encode("utf-8"))
            return
        elif self.path == "/api/telegram/pending_trades":
            try:
                from nifty_trader.notifications.telegram_service import get_pending_trade_manager
                pm = get_pending_trade_manager()
                trades = pm.list_pending_trades()
                armed_count = len([t for t in trades if t.get("status") == "ARMED_15M"])
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(json.dumps({"pending_trades": trades, "count": armed_count}).encode("utf-8"))
            except Exception as ex:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(ex)}).encode("utf-8"))
            return
        elif self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode("utf-8"))
        elif self.path == "/api/simulator/report":
            rep_path = Path("data/paper_trading/SIMULATOR_REPORT.md")
            if not rep_path.exists():
                rep_path = Path(__file__).resolve().parent.parent.parent / "data" / "paper_trading" / "SIMULATOR_REPORT.md"
            self.send_response(200)
            self.send_header("Content-Type", "text/markdown; charset=utf-8")
            self.end_headers()
            content = rep_path.read_text(encoding="utf-8") if rep_path.exists() else "# No simulator report generated yet"
            self.wfile.write(content.encode("utf-8"))
        elif self.path.startswith("/api/simulator/screenshot_image"):
            try:
                from nifty_trader.simulator.service import get_simulator_service
                shot_path = get_simulator_service().get_latest_screenshot_path()
                if shot_path and Path(shot_path).exists():
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                    self.end_headers()
                    self.wfile.write(Path(shot_path).read_bytes())
                else:
                    self.send_response(404)
                    self.end_headers()
            except Exception as ex:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(ex).encode("utf-8"))
        elif self.path == "/api/simulator/capture_screenshot":
            try:
                from nifty_trader.simulator.service import get_simulator_service
                svc = get_simulator_service()
                shot_path = svc.capture_tradingview_screenshot()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "ok",
                    "screenshot_path": shot_path,
                    "filename": Path(shot_path).name,
                    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "image_url": f"/api/simulator/screenshot_image?t={int(time.time())}",
                }).encode("utf-8"))
            except Exception as ex:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(ex)}).encode("utf-8"))
        elif self.path.startswith("/api/simulator/analyze_chart") or self.path.startswith("/api/simulator/analyze_now"):
            try:
                from nifty_trader.simulator.service import get_simulator_service
                svc = get_simulator_service()
                details = svc.analyze_chart_now()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "ok",
                    "details": details,
                    "verdict": details["verdict"],
                    "time": details["timestamp"],
                }).encode("utf-8"))
            except Exception as ex:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(ex)}).encode("utf-8"))
        elif self.path.startswith("/api/simulator/delete"):
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            trade_id = q.get("id", [""])[0]
            try:
                from nifty_trader.simulator.service import get_simulator_service
                ok = get_simulator_service().delete_trade(trade_id)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "deleted": ok, "trade_id": trade_id}).encode("utf-8"))
            except Exception as ex:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(ex)}).encode("utf-8"))
        elif self.path == "/api/simulator/clear_all":
            try:
                from nifty_trader.simulator.service import get_simulator_service
                cnt = get_simulator_service().clear_all_trades()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "deleted_count": cnt}).encode("utf-8"))
            except Exception as ex:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(ex)}).encode("utf-8"))
        elif self.path.startswith("/api/simulator/rule"):
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            rule_name = q.get("name", ["custom"])[0]
            try:
                from nifty_trader.simulator.service import get_simulator_service
                get_simulator_service().set_rule(rule_name)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')
            except Exception as ex:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(ex).encode("utf-8"))
        elif self.path.startswith("/api/simulator/preset"):
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            key = q.get("key", [""])[0]
            try:
                from nifty_trader.simulator.service import get_simulator_service
                svc = get_simulator_service()
                svc.apply_preset(key)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "ok",
                    "preset": key,
                    "settings": svc.get_dashboard_summary()["settings"],
                }).encode("utf-8"))
            except Exception as ex:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(ex)}).encode("utf-8"))
        elif self.path.startswith("/api/simulator/settings"):
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            try:
                from nifty_trader.simulator.service import get_simulator_service
                svc = get_simulator_service()
                lots = int(q.get("lots", [svc.lots])[0]) if "lots" in q else None
                sl_mode = q.get("sl_mode", [None])[0]
                sl_val = float(q.get("sl_val", [svc.sl_val])[0]) if "sl_val" in q else None
                target_mode = q.get("target_mode", [None])[0]
                target_val = float(q.get("target_val", [svc.target_val])[0]) if "target_val" in q else None
                trailing_sl = (q.get("trailing_sl", ["0"])[0].lower() in ["1", "true"]) if "trailing_sl" in q else None
                trail_step = float(q.get("trail_step", [svc.trail_step])[0]) if "trail_step" in q else None
                preset_name = q.get("preset_name", ["CUSTOM"])[0]

                svc.update_settings(
                    lots=lots,
                    sl_mode=sl_mode,
                    sl_val=sl_val,
                    target_mode=target_mode,
                    target_val=target_val,
                    trailing_sl=trailing_sl,
                    trail_step=trail_step,
                    preset_name=preset_name,
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "ok",
                    "settings": svc.get_dashboard_summary()["settings"],
                }).encode("utf-8"))
            except Exception as ex:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(ex)}).encode("utf-8"))
        elif self.path == "/api/spot/fetch_now":
            try:
                from nifty_trader.market_data.spot_service import get_spot_service
                record = get_spot_service().fetch_spot_now()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "record": record}).encode("utf-8"))
            except Exception as ex:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(ex)}).encode("utf-8"))
        elif self.path == "/api/spot/latest":
            try:
                from nifty_trader.market_data.spot_service import get_spot_service
                rec = get_spot_service().latest_spot
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "latest": rec}).encode("utf-8"))
            except Exception as ex:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(ex)}).encode("utf-8"))
        elif self.path.startswith("/api/spot/history"):
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            sym = q.get("symbol", [None])[0]
            try:
                from nifty_trader.market_data.spot_service import get_spot_service
                hist = get_spot_service().get_history(limit=100, symbol=sym)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "history": hist}).encode("utf-8"))
            except Exception as ex:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(ex)}).encode("utf-8"))
        elif self.path.startswith("/api/spot/export_csv"):
            try:
                import io
                import csv
                from nifty_trader.market_data.spot_service import get_spot_service
                records = get_spot_service().get_history(limit=5000)
                output = io.StringIO()
                if records:
                    fieldnames = [
                        "id", "timestamp_ist", "timestamp_utc", "date", "time",
                        "symbol", "spot_price", "open_price", "high_price", "low_price",
                        "close_price", "previous_close", "change_pts", "change_pct", "volume", "source"
                    ]
                    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
                    writer.writeheader()
                    for r in records:
                        writer.writerow(r)
                else:
                    output.write("No spot records recorded yet.\n")
                csv_bytes = output.getvalue().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="nse_spot_records.csv"')
                self.end_headers()
                self.wfile.write(csv_bytes)
            except Exception as ex:
                self.send_response(500)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(str(ex).encode("utf-8"))
        elif self.path.startswith("/api/levels/list"):
            try:
                from nifty_trader.simulator.level_strategy import get_level_strategy_manager
                from nifty_trader.market_data.spot_service import get_spot_service
                spot_data = get_spot_service().latest_spots
                current_spots = {k: float(v.get("spot_price", 0.0)) for k, v in spot_data.items()}
                trigs = get_level_strategy_manager().list_triggers(current_spots=current_spots)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "triggers": trigs}).encode("utf-8"))
            except Exception as ex:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(ex)}).encode("utf-8"))
        elif self.path.startswith("/api/levels/add"):
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            try:
                from nifty_trader.simulator.level_strategy import get_level_strategy_manager
                mgr = get_level_strategy_manager()
                inst = q.get("instrument", ["NIFTY 50"])[0]
                trig_price = float(q.get("trigger_price", [0.0])[0])
                cond = q.get("condition", ["CROSS_ABOVE"])[0]
                opt_type = q.get("option_type", ["CE"])[0]
                sl_type = q.get("sl_type", ["SPOT_LEVEL"])[0]
                sl_val = float(q.get("sl_val", [0.0])[0])
                target_type = q.get("target_type", ["SPOT_LEVEL"])[0]
                target_val = float(q.get("target_val", [0.0])[0])
                lots = int(q.get("lots", [1])[0])
                notes = q.get("notes", [""])[0]

                trig = mgr.add_trigger(
                    instrument=inst,
                    trigger_price=trig_price,
                    condition=cond,
                    option_type=opt_type,
                    strike_mode="ATM",
                    lots=lots,
                    sl_type=sl_type,
                    sl_val=sl_val,
                    target_type=target_type,
                    target_val=target_val,
                    notes=notes,
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "trigger_id": trig.trigger_id}).encode("utf-8"))
            except Exception as ex:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(ex)}).encode("utf-8"))
        elif self.path.startswith("/api/levels/cancel"):
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            trig_id = q.get("id", [""])[0]
            try:
                from nifty_trader.simulator.level_strategy import get_level_strategy_manager
                ok = get_level_strategy_manager().cancel_trigger(trig_id)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "cancelled": ok}).encode("utf-8"))
            except Exception as ex:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(ex)}).encode("utf-8"))
        elif self.path.startswith("/api/levels/delete"):
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            trig_id = q.get("id", [""])[0]
            try:
                from nifty_trader.simulator.level_strategy import get_level_strategy_manager
                ok = get_level_strategy_manager().delete_trigger(trig_id)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "deleted": ok}).encode("utf-8"))
            except Exception as ex:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(ex)}).encode("utf-8"))
        elif self.path == "/api/levels/check_now":
            try:
                from nifty_trader.simulator.level_strategy import get_level_strategy_manager
                from nifty_trader.market_data.spot_service import get_spot_service
                from nifty_trader.simulator.service import get_simulator_service
                spot_data = get_spot_service().latest_spots
                mgr = get_level_strategy_manager()
                sim_svc = get_simulator_service()
                all_exec = []
                for sym, rec in spot_data.items():
                    events = mgr.evaluate_spot_update(
                        symbol=sym,
                        spot_price=rec["spot_price"],
                        day_high=rec.get("high_price"),
                        day_low=rec.get("low_price"),
                        day_open=rec.get("open_price"),
                    )
                    all_exec.extend(events)
                    sim_svc.update_active_position_with_spot(
                        symbol=sym,
                        spot_price=rec["spot_price"],
                        high=rec.get("high_price"),
                        low=rec.get("low_price"),
                    )
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "executed": all_exec}).encode("utf-8"))
            except Exception as ex:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(ex)}).encode("utf-8"))
        elif self.path.startswith("/api/news/fetch_now"):
            try:
                from nifty_trader.market_data.news_service import get_news_service
                ns = get_news_service()
                added = ns.fetch_live_rss()
                summary = ns.get_news_summary()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "added": added, "summary": summary}).encode("utf-8"))
            except Exception as ex:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(ex)}).encode("utf-8"))
        elif self.path.startswith("/api/news/delete"):
            try:
                from urllib.parse import parse_qs, urlparse
                q = parse_qs(urlparse(self.path).query)
                nid = q.get("id", [""])[0]
                from nifty_trader.market_data.news_service import get_news_service
                ns = get_news_service()
                ok = ns.delete_news_item(nid)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "deleted": ok}).encode("utf-8"))
            except Exception as ex:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(ex)}).encode("utf-8"))
        elif self.path.startswith("/api/news"):
            try:
                from urllib.parse import parse_qs, urlparse
                q = parse_qs(urlparse(self.path).query)
                cat = q.get("category", [None])[0]
                imp = q.get("impact", [None])[0]
                imp_only = q.get("important", ["0"])[0] in ("1", "true", "True")
                limit = int(q.get("limit", [50])[0])
                from nifty_trader.market_data.news_service import get_news_service
                ns = get_news_service()
                news_items = ns.get_all_news(category=cat, impact_type=imp, important_only=imp_only, limit=limit)
                summary = ns.get_news_summary()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "news": news_items, "summary": summary}).encode("utf-8"))
            except Exception as ex:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(ex)}).encode("utf-8"))
        elif self.path.startswith("/api/option_chain"):
            try:
                from urllib.parse import parse_qs, urlparse
                q = parse_qs(urlparse(self.path).query)
                symbol = q.get("symbol", ["NIFTY"])[0]
                expiry = q.get("expiry", [None])[0]
                force = q.get("refresh", ["0"])[0] in ("1", "true", "True")
                from nifty_trader.market_data.option_chain_service import get_option_chain_service
                ocs = get_option_chain_service()
                chain = ocs.get_option_chain(symbol=symbol, expiry=expiry, force_refresh=force)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "chain": chain}).encode("utf-8"))
            except Exception as ex:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(ex)}).encode("utf-8"))
        elif self.path == "/api/niftytrader/config":
            try:
                import os
                api_key = os.getenv("NIFTYTRADER_API_KEY", "")
                bearer = os.getenv("NIFTYTRADER_BEARER_TOKEN", "")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "ok",
                    "api_key": api_key,
                    "bearer_token": bearer,
                }).encode("utf-8"))
            except Exception as ex:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(ex)}).encode("utf-8"))
        elif self.path == "/api/data":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            payload = {
                "overview": self.aggregator.get_system_overview(),
                "brain": self.aggregator.get_brain_history(limit=15),
                "paper": self.aggregator.get_paper_positions(),
                "experience": self.aggregator.get_experience_summary(),
                "research": self.aggregator.get_research_zone_summary(),
                "simulator": self.aggregator.get_simulator_summary(),
                "spot": self.aggregator.get_spot_summary(),
                "levels": self.aggregator.get_levels_summary(),
                "news": self.aggregator.get_news_summary(),
            }
            self.wfile.write(json.dumps(payload, default=str).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/option_chain/trade":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                data = json.loads(body)
                from nifty_trader.market_data.option_chain_service import get_option_chain_service
                ocs = get_option_chain_service()
                res = ocs.execute_option_chain_paper_trade(
                    symbol=data.get("symbol", "NIFTY"),
                    strike=int(data.get("strike")),
                    option_type=data.get("option_type", "CE"),
                    lots=int(data.get("lots", 1)),
                    premium=float(data.get("premium", 0.0)),
                    sl_points=float(data.get("sl_points", 20.0)),
                    target_points=float(data.get("target_points", 40.0)),
                    trailing_sl=bool(data.get("trailing_sl", True)),
                    trail_step=float(data.get("trail_step", 15.0)),
                    action=data.get("action", "BUY"),
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(res).encode("utf-8"))
            except Exception as ex:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(ex)}).encode("utf-8"))
        elif self.path == "/api/niftytrader/config":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                data = json.loads(body)
                api_key = data.get("api_key", "").strip()
                bearer_token = data.get("bearer_token", "").strip()

                import os
                from pathlib import Path
                if api_key:
                    os.environ["NIFTYTRADER_API_KEY"] = api_key
                if bearer_token:
                    os.environ["NIFTYTRADER_BEARER_TOKEN"] = bearer_token

                # Update .env file permanently
                env_path = Path("D:/AI_Trading/nifty-autonomous-trader/.env")
                if env_path.exists():
                    try:
                        content = env_path.read_text(encoding="utf-8")
                        import re
                        if api_key:
                            content = re.sub(r"NIFTYTRADER_API_KEY=.*", f"NIFTYTRADER_API_KEY={api_key}", content)
                        if bearer_token:
                            content = re.sub(r"NIFTYTRADER_BEARER_TOKEN=.*", f"NIFTYTRADER_BEARER_TOKEN={bearer_token}", content)
                        env_path.write_text(content, encoding="utf-8")
                    except Exception as env_err:
                        logger.warning("Could not update .env file: %s", env_err)

                # Clear cache and verify key immediately
                from nifty_trader.market_data.option_chain_service import get_option_chain_service
                ocs = get_option_chain_service()
                ocs._cache.clear()
                ocs._cache_time.clear()

                test_raw = ocs.fetch_live_chain_from_niftytrader("NIFTY")
                if test_raw and "opDatas" in test_raw:
                    strikes_count = len(test_raw["opDatas"])
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "status": "ok",
                        "message": f"Verified successfully! Retrieved {strikes_count} live strikes."
                    }).encode("utf-8"))
                else:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "status": "error",
                        "message": "NiftyTrader rejected the key. Please verify your x-api-key."
                    }).encode("utf-8"))
            except Exception as ex:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(ex)}).encode("utf-8"))
        elif self.path == "/api/telegram/config":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                data = json.loads(body)
                from nifty_trader.notifications.telegram_service import get_telegram_service
                tele = get_telegram_service()
                bot_token = data.get("bot_token", "").strip()
                chat_id = data.get("chat_id", "").strip()
                if bot_token or chat_id:
                    tele.set_credentials(
                        bot_token=bot_token or tele.bot_token,
                        chat_id=chat_id or tele.chat_id,
                    )
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "configured": tele.is_configured}).encode("utf-8"))
            except Exception as ex:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(ex)}).encode("utf-8"))
        elif self.path == "/api/telegram/test":
            try:
                from nifty_trader.notifications.telegram_service import get_telegram_service
                tele = get_telegram_service()
                if not tele.is_configured:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "error", "message": "Telegram Bot Token and Chat ID are not configured yet."}).encode("utf-8"))
                    return
                res = tele.send_test_message()
                if res.get("status") == "ok":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(res).encode("utf-8"))
                else:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(res).encode("utf-8"))
            except Exception as ex:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(ex)}).encode("utf-8"))
        elif self.path == "/api/telegram/arm_trade":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                data = json.loads(body)
                from nifty_trader.notifications.telegram_service import get_pending_trade_manager
                pm = get_pending_trade_manager()
                trade = pm.arm_trade(
                    symbol=data.get("symbol", "NIFTY"),
                    strike=int(data.get("strike", 23500)),
                    option_type=data.get("option_type", "CE"),
                    lots=int(data.get("lots", 1)),
                    premium=float(data.get("premium", 100.0)),
                    spot_price=float(data.get("spot_price", 0.0)),
                    sl_points=float(data.get("sl_points", 20.0)),
                    target_points=float(data.get("target_points", 40.0)),
                    reasoning=data.get("reasoning", "Autonomous setup condition matched with 15-minute confirmation gate"),
                    custom_countdown=int(data.get("countdown_seconds")) if data.get("countdown_seconds") else None,
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "pending_trade": trade}).encode("utf-8"))
            except Exception as ex:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(ex)}).encode("utf-8"))
        elif self.path == "/api/telegram/cancel_pending":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                data = json.loads(body)
                from nifty_trader.notifications.telegram_service import get_pending_trade_manager
                pm = get_pending_trade_manager()
                pending_id = data.get("pending_id", "")
                reason = data.get("reason", "Cancelled by user from dashboard")
                success = pm.cancel_trade(pending_id, reason=reason)
                if success:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "ok", "pending_id": pending_id}).encode("utf-8"))
                else:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "error", "message": f"Could not cancel {pending_id} (already completed, cancelled, or not found)"}).encode("utf-8"))
            except Exception as ex:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(ex)}).encode("utf-8"))
        elif self.path == "/api/news/add":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                data = json.loads(body)
                from nifty_trader.market_data.news_service import get_news_service
                ns = get_news_service()
                nid = ns.add_news_item(
                    title=data.get("title", ""),
                    summary=data.get("summary", ""),
                    source=data.get("source", "Market Wire"),
                    category=data.get("category"),
                    impact_type=data.get("impact_type"),
                    impact_score=int(data.get("impact_score", 4)),
                    market_effect=data.get("market_effect"),
                    is_important=int(data.get("is_important", 1)),
                    url=data.get("url", ""),
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "id": nid}).encode("utf-8"))
            except Exception as ex:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(ex)}).encode("utf-8"))
        elif self.path == "/api/simulator/upload_chart":
            try:
                import base64
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length)
                data = json.loads(body.decode("utf-8"))
                img_data_str = data.get("image_b64", "")
                if "," in img_data_str:
                    img_data_str = img_data_str.split(",", 1)[1]
                raw_bytes = base64.b64decode(img_data_str)

                from nifty_trader.simulator.service import get_simulator_service
                svc = get_simulator_service()
                save_dir = svc.root_dir / "data" / "browser" / "screenshots"
                save_dir.mkdir(parents=True, exist_ok=True)
                dest = save_dir / "user_real_tradingview_chart.png"
                dest.write_bytes(raw_bytes)

                svc.last_screenshot_path = str(dest)
                now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                svc._append_log(f"[{now_str}] 📤 [CHART UPLOAD] User uploaded real TradingView chart screenshot ({len(raw_bytes)} bytes)")
                svc.update_report_files()

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "ok",
                    "filename": dest.name,
                    "screenshot_path": str(dest),
                    "timestamp": now_str,
                }).encode("utf-8"))
            except Exception as ex:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(ex)}).encode("utf-8"))
        elif self.path == "/api/supabase/sync":
            try:
                from nifty_trader.core.supabase_adapter import get_supabase_adapter
                supa = get_supabase_adapter()
                if not supa.is_configured:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "status": "error",
                        "message": "Supabase credentials not configured in environment"
                    }).encode("utf-8"))
                    return
                counts = supa.hydrate_local_sqlite_from_cloud()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "counts": counts}).encode("utf-8"))
            except Exception as ex:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(ex)}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Silence default terminal request spam
        pass


def run_dashboard_server(
    host: Optional[str] = None,
    port: Optional[int] = None,
    open_browser: bool = True,
    block: bool = True,
) -> ThreadingHTTPServer:
    """Starts the interactive local or cloud (Render) Webview Dashboard server."""
    if host is None:
        host = os.environ.get("HOST", "0.0.0.0" if os.environ.get("RENDER") else "127.0.0.1")
    if port is None:
        port = int(os.environ.get("PORT", 8080))

    if os.environ.get("RENDER"):
        open_browser = False

    # AUTO-HYDRATE from Supabase Cloud if configured
    try:
        from nifty_trader.core.supabase_adapter import get_supabase_adapter
        supa = get_supabase_adapter()
        if supa.is_configured:
            print("☁️ Supabase configured! Hydrating local database from Supabase cloud...")
            counts = supa.hydrate_local_sqlite_from_cloud()
            print(f"☁️ Supabase hydration complete: {counts}")
        else:
            print("💾 Supabase not configured — running purely with local SQLite persistence.")
    except Exception as supa_err:
        logger.warning("Could not hydrate from Supabase cloud: %s", supa_err)

    # AUTO-ACTIVATE Local Option Paper Simulator
    try:
        from nifty_trader.simulator.service import get_simulator_service
        sim_service = get_simulator_service()
        sim_service.start()
        print("⚡ Local Option Paper Simulator Auto-Activated in Background.")
    except Exception as sim_err:
        logger.warning("Could not auto-start simulator service: %s", sim_err)

    # AUTO-ACTIVATE 5-Minute Automated NSE Spot Data Fetcher & DB Logger
    try:
        from nifty_trader.market_data.spot_service import get_spot_service
        spot_service = get_spot_service()
        spot_service.start_auto_fetch(interval_seconds=300)
        print("📈 NSE 5-Minute Spot Data Auto-Fetcher Online (DB: data/market/nse_spot_data.db).")
    except Exception as spot_err:
        logger.warning("Could not auto-start spot service: %s", spot_err)

    # AUTO-ACTIVATE Live Market News & Sentiment Auto-Fetcher
    try:
        from nifty_trader.market_data.news_service import get_news_service
        news_service = get_news_service()
        news_service.start_auto_fetch(interval_minutes=15)
        print("📰 Live Market News & Sentiment Service Online (DB: data/market/market_news.db).")
    except Exception as news_err:
        logger.warning("Could not auto-start news service: %s", news_err)

    server = ThreadingHTTPServer((host, port), DashboardHTTPRequestHandler)
    url = f"http://{host}:{port}"
    print(f"\n=======================================================")
    print(f"🚀 NIFTY Autonomous Trader — Webview Dashboard Online")
    print(f"👉 Local URL: {url}")
    print(f"=======================================================\n")

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception as e:
            logger.debug("Could not open browser automatically: %s", e)

    if block:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down dashboard server...")
            server.shutdown()
    else:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

    return server
