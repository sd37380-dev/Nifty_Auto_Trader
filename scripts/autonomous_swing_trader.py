#!/usr/bin/env python3
"""
================================================================================
  HERMES AUTONOMOUS SWING TRADER v1.0
  4-Tier Confluence Architecture (300-point Target | 50-point SL | 1:6.0 R:R)
================================================================================
"""

import argparse
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import sys
import time

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from nifty_trader.swing import (
    get_macro_radar_service,
    get_reaction_zone_service,
    get_swing_agent,
    get_swing_report_service,
)

IST = timezone(timedelta(hours=5, minutes=30))
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("HermesSwingTrader")


def print_swing_briefing():
    rz = get_reaction_zone_service(ROOT_DIR)
    macro = get_macro_radar_service(ROOT_DIR).get_macro_radar_telemetry()
    mtfa = rz.get_multi_timeframe_state("NIFTY")
    zones = rz.scan_reaction_zones("NIFTY")
    setups = rz.get_active_swing_setups("NIFTY")

    print("\n" + "=" * 75)
    print("  HERMES v1.0 — 300-POINT SWING TRADE RADAR (1:6.0 R:R)")
    print(f"  {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')}")
    print("=" * 75)

    print("\n── TIER 1: MACRO & GLOBAL RADAR ──")
    print(f"   Verdict: {macro['global_verdict']}")
    print(f"   FII Long %: {macro['fii_dii']['fii_futures_long_pct']}% ({macro['fii_dii']['fii_status']})")
    print(f"   Brent Crude: ${macro['crude_oil']['price']} ({macro['crude_oil']['status']})")
    print(f"   Gold (XAU): ${macro['gold']['price']} | DXY: {macro['dxy_dollar_index']['price']} | VIX: {macro['india_vix']['value']:.2f}")

    print("\n── TIER 2: MULTI-TIMEFRAME STRUCTURE (MTFA) ──")
    print(f"   W1 Compass : {mtfa['w1_compass']['stage']} | Permission: {mtfa['w1_compass']['permission']}")
    print(f"   D1 Roadmap : {mtfa['d1_roadmap']['phase']} | 20 EMA: ₹{mtfa['d1_roadmap']['20_day_ema']:,.0f}")
    print(f"   4H Battle  : POC: ₹{mtfa['four_h_battleground']['monthly_poc']:,.0f} | VAL: ₹{mtfa['four_h_battleground']['monthly_val']:,.0f}")

    print("\n── TIER 3: CONFLUENCE REACTION ZONES (30-POINT BOXES) ──")
    bf = zones["bullish_floor_zone"]
    bc = zones["bearish_ceiling_zone"]
    print(f"   Demand Floor  : {bf['range_box']} (Dist: {bf['distance_pts']:+.1f} pts) -> {bf['status']}")
    print(f"   Supply Ceiling: {bc['range_box']} (Dist: {bc['distance_pts']:+.1f} pts) -> {bc['status']}")

    print("\n── TIER 4: ACTIVE SWING SETUPS (300-PT TARGET | 50-PT SL) ──")
    for s in setups:
        print(f"   • {s['name']} [{s['status']}]")
        print(f"     Contract: {s['recommended_contract']}")
        print(f"     Levels  : Entry ₹{s['entry_level']:,.0f} | SL ₹{s['stop_loss_price']:,.0f} (-{s['stop_loss_pts']:.0f} pts) | Target ₹{s['target_price']:,.0f} (+{s['target_pts']:.0f} pts)")
        print(f"     Thesis  : {s['why_selected']}")

    print("=" * 75 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hermes Swing Trader v1.0")
    parser.add_argument("--mode", choices=["scan-once", "live"], default="scan-once")
    parser.add_argument("--report", choices=["daily", "weekly", "test-trade"], help="Generate specific swing report")
    parser.add_argument("--interval", type=int, default=60, help="Scan interval seconds")
    args = parser.parse_args()

    rep_svc = get_swing_report_service(ROOT_DIR)

    if args.report == "daily":
        res = rep_svc.generate_daily_swing_summary_pdf()
        print(f"✅ Daily Swing PDF generated: {res.get('pdf_path')}")
    elif args.report == "weekly":
        res = rep_svc.generate_weekly_swing_summary_pdf()
        print(f"✅ Weekly Swing PDF generated: {res.get('pdf_path')}")
    elif args.report == "test-trade":
        rz = get_reaction_zone_service(ROOT_DIR)
        setups = rz.get_active_swing_setups("NIFTY")
        agent = get_swing_agent(ROOT_DIR)
        trade = agent.execute_swing_paper_trade(setups[0])
        print(f"✅ Executed Trade PDF generated: {trade.get('pdf_report')}")
    elif args.mode == "scan-once":
        print_swing_briefing()
    elif args.mode == "live":
        agent = get_swing_agent(ROOT_DIR, scan_interval_seconds=args.interval)
        agent.start_background_monitoring()
        logger.info("Hermes Swing Agent running in live loop. Press Ctrl+C to terminate.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            agent.stop_background_monitoring()
            logger.info("Hermes Swing Agent stopped.")
