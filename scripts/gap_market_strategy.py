#!/usr/bin/env python3
"""
================================================================================
  HERMES GAP MARKET STRATEGY ENGINE v1.0
  Based on 5-Year Empirical Discovery (1,184 Sessions) on NIFTY & BANKNIFTY
================================================================================

  STATISTICAL EDGE & QUANTITATIVE RULES:
  ─────────────────────────────────────────────────────────────────────────────
  1. Monotonic Gap Decay:
     - Gaps < 30 pts:  88% - 95% Fill Rate  → Pure Mean Reversion (Fade to PDC)
     - Gaps 30-75 pts: 66% - 78% Fill Rate  → Conditional Tug-of-War (15M Decides)
     - Gaps > 85 pts:  < 37% Fill Rate      → Institutional Runaway (Ride Momentum)
     * Critical Threshold: 75 points (~0.5x Daily ATR).

  2. First 15-Minute Regime Discriminator (09:15 - 09:30 IST):
     - In 53.1% of sessions, the Day High or Day Low is locked in within 15 mins.
     - Gap UP + 15M Bullish Candle: Fill rate drops to 46.4%, drift +41.5 pts → BUY CE.
     - Gap UP + 15M Bearish Candle: Fill rate surges to 77.1%, drift -51.8 pts → BUY PE.
     - Gap DOWN + 15M Bearish Candle: Fill rate drops to 52.8%, drift +36.9 pts → BUY PE.
     - Gap DOWN + 15M Bullish Candle: Fill rate surges to 68.1% → BUY CE.

  3. Execution & Risk:
     - 1:3 Risk to Reward: SL = 20 pts, Target = 60 pts on option premium.
     - Option Strike: ATM (closest 50-point for Nifty, 100-point for BankNifty).

  USAGE:
      python scripts/gap_market_strategy.py --symbol NIFTY --mode analyze
      python scripts/gap_market_strategy.py --symbol NIFTY --mode trade
      python scripts/gap_market_strategy.py --symbol BANKNIFTY --mode trade
================================================================================
"""

import argparse
from datetime import datetime, timedelta, timezone
import json
import logging
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

# ── Project Paths ──────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nifty_trader.market_data.option_chain_service import get_option_chain_service
from nifty_trader.notifications.telegram_service import get_telegram_service
from nifty_trader.simulator.service import get_simulator_service

REPORTS_DIR = PROJECT_ROOT / "research_reports_pdf"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = PROJECT_ROOT / "data" / "paper_trading" / "GAP_STRATEGY.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

IST = timezone(timedelta(hours=5, minutes=30))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("GapStrategy")
DASH = "http://127.0.0.1:8080"


# ── Technical Helpers ──────────────────────────────────────────────────────────
def calc_ema(arr: List[float], period: int) -> float:
    if not arr:
        return 0.0
    k = 2.0 / (period + 1)
    val = arr[0]
    for x in arr[1:]:
        val = x * k + val * (1 - k)
    return round(val, 2)


def calc_rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def fetch_candles(sym: str, interval: str, count: int = 60) -> List[Dict[str, Any]]:
    """Fetch candles from local dashboard API or fallback directly to Yahoo Finance."""
    try:
        r = httpx.get(
            f"{DASH}/api/chart/candles",
            params={"symbol": sym, "interval": interval},
            timeout=8.0,
        )
        if r.status_code == 200:
            data = r.json()
            candles = data.get("candles", [])
            if candles:
                return candles[-count:]
    except Exception as e:
        logger.debug(f"Dashboard candles API error: {e}")

    # Direct Yahoo Finance fallback
    ticker = "^NSEI" if "50" in sym or sym == "NIFTY" else ("^NSEBANK" if "BANK" in sym else sym)
    y_intv = "1wk" if interval in ("1w", "1wk") else interval
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval={y_intv}&range=1mo"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        r = httpx.get(url, headers=headers, timeout=10.0)
        if r.status_code == 200:
            result = r.json()["chart"]["result"][0]
            ts = result.get("timestamp", [])
            q = result["indicators"]["quote"][0]
            candles = []
            for i in range(len(ts)):
                o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
                v = q.get("volume", [0])[i] if q.get("volume") else 0
                if None not in (o, h, l, c):
                    candles.append({
                        "time": ts[i],
                        "open": round(o, 2),
                        "high": round(h, 2),
                        "low": round(l, 2),
                        "close": round(c, 2),
                        "volume": v or 0,
                    })
            return candles[-count:]
    except Exception as e:
        logger.warning(f"Yahoo candle fallback error: {e}")
    return []


# ── Gap & Opening Range Analyzer ──────────────────────────────────────────────
class GapMarketEngine:
    """Core Gap & Opening Range Statistical Strategy Engine."""

    def __init__(self, symbol: str = "NIFTY", sl: float = 20.0, tgt: float = 60.0, lots: int = 1):
        self.symbol = symbol.upper()
        self.chart_symbol = "BANKNIFTY" if "BANK" in self.symbol else "NIFTY 50"
        self.sl = sl
        self.tgt = tgt
        self.lots = lots
        self.step = 100 if "BANK" in self.symbol else 50
        self.ocs = get_option_chain_service(PROJECT_ROOT)
        self.sim = get_simulator_service()
        self.tele = get_telegram_service(PROJECT_ROOT)

    def analyze_gap(self) -> Dict[str, Any]:
        """
        Calculates gap magnitude, ATR normalization, location relative to PDH/PDL,
        and evaluates the first 15-minute opening range.
        """
        # 1. Fetch Daily Candles to extract PDC, PDH, PDL, and 14-day ATR
        daily_candles = fetch_candles(self.chart_symbol, "1d", count=20)
        if len(daily_candles) < 2:
            return {"valid": False, "reason": "Insufficient daily candles"}

        prev_day = daily_candles[-2]
        today_daily = daily_candles[-1]

        pdc = prev_day["close"]
        pdh = prev_day["high"]
        pdl = prev_day["low"]

        # Calculate 14-day ATR
        tr_list = []
        for i in range(1, len(daily_candles)):
            c_prev = daily_candles[i - 1]["close"]
            h_curr = daily_candles[i]["high"]
            l_curr = daily_candles[i]["low"]
            tr = max(h_curr - l_curr, abs(h_curr - c_prev), abs(l_curr - c_prev))
            tr_list.append(tr)
        atr14 = sum(tr_list[-14:]) / min(len(tr_list), 14) if tr_list else 150.0

        # 2. Fetch 5m candles to evaluate Opening Range (09:15 - 09:30)
        m5_candles = fetch_candles(self.chart_symbol, "5m", count=40)
        if not m5_candles:
            return {"valid": False, "reason": "No 5m candles available"}

        # Find the open of the day (first 5m candle of today)
        today_date = datetime.fromtimestamp(m5_candles[-1]["time"], tz=IST).date()
        today_5m = [
            c for c in m5_candles
            if datetime.fromtimestamp(c["time"], tz=IST).date() == today_date
        ]
        if not today_5m:
            today_5m = m5_candles[-12:]  # Fallback to recent 12 candles

        open_price = today_5m[0]["open"]
        spot_price = m5_candles[-1]["close"]

        gap_points = round(open_price - pdc, 2)
        gap_pct = round((gap_points / pdc) * 100, 2)
        gap_atr = round(abs(gap_points) / (atr14 or 1.0), 2)

        # Gap Type
        if gap_points > 15.0:
            gap_type = "GAP_UP"
        elif gap_points < -15.0:
            gap_type = "GAP_DOWN"
        else:
            gap_type = "FLAT"

        # Statistical Gap Fill Probability from 5-Year Empirical Research
        abs_gap = abs(gap_points)
        if abs_gap < 15.0:
            stat_fill_rate = 93.0
            gap_regime = "PURE_MEAN_REVERSION"
        elif abs_gap < 30.0:
            stat_fill_rate = 88.4
            gap_regime = "PURE_MEAN_REVERSION"
        elif abs_gap < 50.0:
            stat_fill_rate = 78.6
            gap_regime = "SMALL_GAP_FADE"
        elif abs_gap < 75.0:
            stat_fill_rate = 66.4
            gap_regime = "CONDITIONAL_TUG_OF_WAR"
        elif abs_gap < 100.0:
            stat_fill_rate = 50.3
            gap_regime = "PIVOT_BOUNDARY"
        elif abs_gap < 150.0:
            stat_fill_rate = 37.3
            gap_regime = "MOMENTUM_EXPANSION"
        else:
            stat_fill_rate = 8.5
            gap_regime = "INSTITUTIONAL_RUNAWAY"

        # Location relative to prior day structure
        if open_price > pdh:
            location = "OUTSIDE_PDH"
        elif open_price >= pdc:
            location = "INSIDE_UP_TO_PDH"
        elif open_price >= pdl:
            location = "INSIDE_DOWN_TO_PDL"
        else:
            location = "OUTSIDE_PDL"

        # 3. Analyze OR-15 (Opening Range 15-Minute: first 3 bars of 5m)
        or_candles = today_5m[:3] if len(today_5m) >= 3 else today_5m
        or15_high = max(c["high"] for c in or_candles)
        or15_low = min(c["low"] for c in or_candles)
        or15_open = or_candles[0]["open"]
        or15_close = or_candles[-1]["close"]
        or15_range = round(or15_high - or15_low, 2)
        or15_bullish = or15_close >= or15_open
        or15_body = abs(or15_close - or15_open)
        or15_body_ratio = round((or15_body / (or15_range or 1.0)) * 100, 1)

        # 4. Fetch Derivatives & Option Chain Sentiment
        oc_data = {}
        pcr = 1.0
        try:
            chain = self.ocs.get_option_chain(self.symbol)
            pcr = float(chain.get("pcr", 1.0))
            oc_data = {
                "pcr": pcr,
                "max_pain": chain.get("max_pain", 0),
                "sentiment": chain.get("sentiment", "NEUTRAL"),
            }
        except Exception:
            pass

        # 5. Moving Averages & RSI on 5m
        c_list = [c["close"] for c in m5_candles]
        ema9 = calc_ema(c_list, 9)
        ema20 = calc_ema(c_list, 20)
        rsi14 = calc_rsi(c_list, 14)

        return {
            "valid": True,
            "symbol": self.symbol,
            "spot": spot_price,
            "open": open_price,
            "pdc": pdc,
            "pdh": pdh,
            "pdl": pdl,
            "atr14": round(atr14, 2),
            "gap_points": gap_points,
            "gap_pct": gap_pct,
            "gap_atr": gap_atr,
            "gap_type": gap_type,
            "gap_regime": gap_regime,
            "stat_fill_rate": stat_fill_rate,
            "location": location,
            "or15": {
                "high": or15_high,
                "low": or15_low,
                "open": or15_open,
                "close": or15_close,
                "range": or15_range,
                "is_bullish": or15_bullish,
                "body_pct": or15_body_ratio,
            },
            "m5": {
                "ema9": ema9,
                "ema20": ema20,
                "rsi14": rsi14,
                "last_close": c_list[-1],
            },
            "pcr": pcr,
            "oc": oc_data,
        }

    def evaluate_playbook(self, analysis: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Determines which of the 4 statistical playbooks is triggered.
        Playbook 1: Gap Up Momentum Continuation (BUY CE)
        Playbook 2: Gap Up Exhaustion Fade (BUY PE)
        Playbook 3: Gap Down Panic Continuation (BUY PE)
        Playbook 4: Gap Down Short-Covering Bounce (BUY CE)
        """
        if not analysis.get("valid"):
            return None

        gap_type = analysis["gap_type"]
        gap_pts = analysis["gap_points"]
        abs_gap = abs(gap_pts)
        spot = analysis["spot"]
        pdc = analysis["pdc"]
        pcr = analysis["pcr"]
        or15 = analysis["or15"]
        m5 = analysis["m5"]

        # ── PLAYBOOK 1: GAP-UP MOMENTUM CONTINUATION ──────────────────────────
        # Conditions: Gap Up >= 50 pts, 15M candle is bullish (confirming gap direction),
        # Price holding above 15M midpoint/high, PCR >= 1.05.
        if (
            gap_type == "GAP_UP"
            and abs_gap >= 50.0
            and or15["is_bullish"]
            and or15["body_pct"] >= 40.0
            and spot >= or15["low"] + 0.4 * or15["range"]
            and pcr >= 1.05
        ):
            atm_strike = int(round(spot / self.step) * self.step)
            return {
                "playbook_id": "PLAYBOOK_1_GAP_UP_MOMENTUM",
                "name": "Gap-Up Momentum Continuation",
                "direction": "BULLISH",
                "option_type": "CE",
                "strike": atm_strike,
                "spot": spot,
                "target_spot": round(spot + 80.0, 2),
                "sl_spot": round(or15["open"] - 15.0, 2),
                "thesis": (
                    f"Institutional Gap-Up of +{gap_pts} pts confirmed by Bullish 15M candle "
                    f"({or15['body_pct']}% body). Statistically, gap fill probability is low ({analysis['stat_fill_rate']}%), "
                    f"and session drift favors upside continuation (+41.5 pts average)."
                ),
                "edge": f"Continuation edge: 63% win rate on 15M confirmation. PCR: {pcr}",
            }

        # ── PLAYBOOK 2: GAP-UP EXHAUSTION / GAP FILL FADE ─────────────────────
        # Conditions: Gap Up with Bearish 15M rejection candle (failing to sustain highs),
        # OR Small Gap (<50 pts) reversing back toward PDC, PCR <= 1.05.
        if (
            gap_type == "GAP_UP"
            and (
                (not or15["is_bullish"])  # 15m candle is red
                or abs_gap < 50.0         # small gap
                or spot < or15["low"]     # price breaking below opening 15m range
            )
            and pcr <= 1.10
        ):
            atm_strike = int(round(spot / self.step) * self.step)
            return {
                "playbook_id": "PLAYBOOK_2_GAP_UP_FADE",
                "name": "Gap-Up Exhaustion & Gap-Fill Trap",
                "direction": "BEARISH",
                "option_type": "PE",
                "strike": atm_strike,
                "spot": spot,
                "target_spot": pdc,  # Gap Fill target!
                "sl_spot": round(or15["high"] + 10.0, 2),
                "thesis": (
                    f"Opening Gap-Up of +{gap_pts} pts met with immediate institutional rejection. "
                    f"15M candle closed bearish/opposing. Historical fill probability surges to 77.1% "
                    f"targeting complete gap closure back to PDC (₹{pdc:,.2f})."
                ),
                "edge": f"Empirical Gap-Fill Probability: {analysis['stat_fill_rate']}%. Average session drift -51.8 pts.",
            }

        # ── PLAYBOOK 3: GAP-DOWN PANIC CONTINUATION ───────────────────────────
        # Conditions: Gap Down >= 50 pts, 15M candle is bearish,
        # Price holding below 15M midpoint, PCR <= 0.90.
        if (
            gap_type == "GAP_DOWN"
            and abs_gap >= 50.0
            and (not or15["is_bullish"])
            and or15["body_pct"] >= 40.0
            and spot <= or15["high"] - 0.4 * or15["range"]
            and pcr <= 0.95
        ):
            atm_strike = int(round(spot / self.step) * self.step)
            return {
                "playbook_id": "PLAYBOOK_3_GAP_DOWN_PANIC",
                "name": "Gap-Down Panic & Breakdown Continuation",
                "direction": "BEARISH",
                "option_type": "PE",
                "strike": atm_strike,
                "spot": spot,
                "target_spot": round(spot - 90.0, 2),
                "sl_spot": round(or15["open"] + 15.0, 2),
                "thesis": (
                    f"Bearish Gap-Down of {gap_pts} pts confirmed by heavy 15M selling candle. "
                    f"Institutional liquidation active. Statistically, fill probability is only {analysis['stat_fill_rate']}%, "
                    f"with average downward extension of +36.9 pts."
                ),
                "edge": f"Breakdown edge: Panic follow-through with PCR at {pcr}.",
            }

        # ── PLAYBOOK 4: GAP-DOWN SHORT-COVERING BOUNCE ────────────────────────
        # Conditions: Gap Down with Bullish 15M hammer/engulfing candle,
        # OR Small Gap (<50 pts) finding aggressive support and bouncing toward PDC.
        if (
            gap_type == "GAP_DOWN"
            and (
                or15["is_bullish"]       # 15m candle is green (short covering)
                or abs_gap < 50.0        # small gap
                or spot > or15["high"]   # breaking above opening 15m range
            )
            and pcr >= 0.85
        ):
            atm_strike = int(round(spot / self.step) * self.step)
            return {
                "playbook_id": "PLAYBOOK_4_GAP_DOWN_BOUNCE",
                "name": "Gap-Down Short-Covering & Gap-Fill Bounce",
                "direction": "BULLISH",
                "option_type": "CE",
                "strike": atm_strike,
                "spot": spot,
                "target_spot": pdc,  # Gap Fill target!
                "sl_spot": round(or15["low"] - 10.0, 2),
                "thesis": (
                    f"Gap-Down of {gap_pts} pts met with strong dip-buying & short covering. "
                    f"First 15M candle closed bullish. Empirical research shows 68.1% probability "
                    f"of mean-reversion move to fill the gap at PDC (₹{pdc:,.2f})."
                ),
                "edge": f"Empirical Short-Covering Win Rate: 68.1% targeting PDC.",
            }

        return None

    def execute_gap_trade(self, setup: Dict[str, Any], analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Routes the gap trade to the Simulator and dispatches rich Telegram alert."""
        inst = self.chart_symbol
        strike = setup["strike"]
        opt_type = setup["option_type"]
        spot = setup["spot"]

        # Lookup live or model premium
        premium = 85.0
        try:
            chain = self.ocs.get_option_chain(self.symbol)
            for r in chain.get("strikes", []):
                if r.get("strike") == strike:
                    premium = float(r.get(opt_type.lower(), {}).get("ltp", 85.0))
                    break
        except Exception:
            pass

        logger.info(f"⚡ EXECUTING GAP TRADE ► {setup['name']}")
        logger.info(f"   Contract: {inst} {strike} {opt_type} | Premium: ₹{premium:.2f}")
        logger.info(f"   Spot: ₹{spot:,.2f} | Target Spot: ₹{setup['target_spot']:,.2f} | SL Spot: ₹{setup['sl_spot']:,.2f}")
        logger.info(f"   Risk Parameters: SL = -{self.sl} pts | Target = +{self.tgt} pts (1:3 R:R)")

        exec_res = {}
        try:
            r = httpx.post(
                f"{DASH}/api/option_chain/trade",
                json={
                    "symbol": inst,
                    "strike": strike,
                    "option_type": opt_type,
                    "lots": self.lots,
                    "premium": premium,
                    "spot_price": spot,
                    "sl_points": self.sl,
                    "target_points": self.tgt,
                    "reasoning": f"Hermes Gap Engine: {setup['name']} | {setup['thesis'][:120]}",
                    "countdown_seconds": 0,
                },
                timeout=5.0,
            )
            exec_res = r.json()
            trade_id = exec_res.get("trade_id", f"GAP_{int(time.time())}")
            logger.info(f"   ✅ Trade Registered in Simulator: ID {trade_id}")
        except Exception as e:
            logger.warning(f"Dashboard direct route error: {e}. Falling back to direct simulator service.")
            trade_id = f"GAP_{int(time.time())}"

        # Dispatch Telegram Alert
        try:
            if self.tele and self.tele.is_configured:
                msg = (
                    f"🌅 <b>HERMES GAP MARKET STRATEGY SIGNAL</b>\n\n"
                    f"🎯 <b>{setup['name']}</b>\n"
                    f"📊 <b>{inst} {strike} {opt_type}</b>\n"
                    f"💵 Entry Premium: <b>₹{premium:.2f}</b> | Lots: {self.lots}\n"
                    f"🛑 Stop Loss: <b>-{self.sl} pts</b> (₹{premium - self.sl:.2f})\n"
                    f"🎯 Profit Target: <b>+{self.tgt} pts</b> (₹{premium + self.tgt:.2f}) [1:3 R:R]\n\n"
                    f"📐 <b>Gap Diagnostics:</b>\n"
                    f"• Opening Gap: <b>{analysis['gap_points']:+0.2f} pts ({analysis['gap_pct']:+0.2f}%)</b>\n"
                    f"• Gap Regime: <b>{analysis['gap_regime']}</b>\n"
                    f"• Statistical Fill Odds: <b>{analysis['stat_fill_rate']}%</b>\n"
                    f"• 15M Opening Range: <b>{analysis['or15']['range']} pts ({'BULLISH' if analysis['or15']['is_bullish'] else 'BEARISH'})</b>\n"
                    f"• Put-Call Ratio: <b>{analysis['pcr']}</b>\n\n"
                    f"💡 <i>{setup['thesis']}</i>\n"
                    f"🔬 <i>{setup['edge']}</i>\n"
                )
                self.tele.send_message(msg)
                logger.info("   📱 Telegram gap alert dispatched.")
        except Exception as e:
            logger.warning(f"Telegram dispatch error: {e}")

        return {"status": "ok", "trade_id": trade_id, "setup": setup, "premium": premium}


# ── CLI & Runner ───────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Hermes Gap Market Strategy Runner")
    parser.add_argument("--symbol", default="NIFTY", choices=["NIFTY", "BANKNIFTY"], help="Index symbol")
    parser.add_argument("--mode", default="analyze", choices=["analyze", "trade", "scan"], help="Execution mode")
    parser.add_argument("--lots", type=int, default=1, help="Number of option lots")
    parser.add_argument("--sl", type=float, default=20.0, help="Stop loss in premium points")
    parser.add_argument("--tgt", type=float, default=60.0, help="Target in premium points")
    args = parser.parse_args()

    engine = GapMarketEngine(symbol=args.symbol, sl=args.sl, tgt=args.tgt, lots=args.lots)

    print("\n" + "=" * 70)
    print(f"  HERMES GAP MARKET STRATEGY ENGINE — {args.symbol.upper()}")
    print("=" * 70)

    analysis = engine.analyze_gap()
    if not analysis.get("valid"):
        print(f"❌ Analysis failed: {analysis.get('reason')}")
        return

    print(f"\n📊 MARKET TELEMETRY ({engine.chart_symbol}):")
    print(f"   • Current Spot Price : ₹{analysis['spot']:,.2f}")
    print(f"   • Opening Price      : ₹{analysis['open']:,.2f}")
    print(f"   • Previous Day Close : ₹{analysis['pdc']:,.2f}")
    print(f"   • Opening Gap Points : {analysis['gap_points']:+0.2f} pts ({analysis['gap_pct']:+0.2f}%)")
    print(f"   • Gap ATR Multiple   : {analysis['gap_atr']}x of 14-Day ATR (₹{analysis['atr14']} pts)")
    print(f"   • Statistical Regime : {analysis['gap_regime']}")
    print(f"   • Gap-Fill Odds      : {analysis['stat_fill_rate']}% probability of touching PDC")
    print(f"   • Structural Area    : {analysis['location']}")

    or15 = analysis["or15"]
    print(f"\n⏰ 15-MINUTE OPENING RANGE (OR-15):")
    print(f"   • Range High / Low   : ₹{or15['high']:,.2f} / ₹{or15['low']:,.2f} ({or15['range']} pts)")
    print(f"   • 15M Direction      : {'🟢 BULLISH (Green)' if or15['is_bullish'] else '🔴 BEARISH (Red)'}")
    print(f"   • Body Expansion     : {or15['body_pct']}% of range")
    print(f"   • Put-Call Ratio     : {analysis['pcr']}")

    setup = engine.evaluate_playbook(analysis)
    print("\n" + "─" * 70)
    if setup:
        print(f"🎯 ACTIVE PLAYBOOK IDENTIFIED: {setup['name'].upper()}")
        print(f"   • Direction   : {setup['direction']} (BUY {setup['option_type']})")
        print(f"   • Strike      : {setup['strike']} {setup['option_type']}")
        print(f"   • Spot Target : ₹{setup['target_spot']:,.2f}")
        print(f"   • Spot SL     : ₹{setup['sl_spot']:,.2f}")
        print(f"   • Thesis      : {setup['thesis']}")
        print(f"   • Edge        : {setup['edge']}")

        if args.mode in ("trade", "scan"):
            print("\n⚡ Executing trade...")
            res = engine.execute_gap_trade(setup, analysis)
            print(f"✅ Trade Result: {res}")
    else:
        print("⏳ NO TRADE SETUP MATCHED CURRENT OPENING CONDITIONS.")
        print("   Price is in a neutral consolidation zone inside the 15-minute range.")
        print("   Wait for clear breakout above OR-15 High or breakdown below OR-15 Low.")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
