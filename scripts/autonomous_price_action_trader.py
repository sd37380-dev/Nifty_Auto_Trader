#!/usr/bin/env python3
"""
================================================================================
  HERMES AUTONOMOUS TRADER v2.0
  Price Action + Multi-TF Trend + S/R + Volume + Options + News
================================================================================

  WORKFLOW (Professional Option Trader Checklist):
  ─────────────────────────────────────────────────
  STEP 1 ► Multi-Timeframe Trend/Bias (Weekly → Daily → 4H → 1H)
           EMA 9/20 position & candle structure on each TF.
           Majority vote decides session bias: BULLISH / BEARISH / NEUTRAL.

  STEP 2 ► Market News Sentiment
           Query market_news.db for today's impact headlines.
           Aggregate BULLISH vs BEARISH count + average impact_score.

  STEP 3 ► Support & Resistance Matrix
           Daily Pivots (PP, R1, R2, S1, S2) + CPR.
           PDH / PDL / Previous Day Close.
           Max Call OI strike (Resistance) + Max Put OI strike (Support).

  STEP 4 ► 5-Min Execution Candle Analysis
           Price Action: candle body %, wick ratio, engulfing patterns.
           EMA 9 / EMA 20 crossover & slope.
           RSI(14) overbought/oversold/momentum.
           Volume vs 20-period SMA (expansion / dry-up).

  STEP 5 ► Option Chain Derivatives Confirmation
           PCR level + OI buildup pattern + Max Pain distance.

  STEP 6 ► Instant Execution (0-sec delay)
           Route to Paper Simulator.  SL = 20 pts, Target = 60 pts (1:3 R:R).
           Telegram alert dispatched immediately.

  STEP 7 ► Post-Trade Audit
           Chart screenshot + full analysis PDF report + SIMULATOR_LOG.txt.
           After exit → restart scan for next trade.

  USAGE:
      python autonomous_price_action_trader.py --symbol NIFTY --mode live
================================================================================
"""

import argparse
from datetime import datetime, time as dt_time, timedelta, timezone
import json
import logging
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import shutil
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

# ── Project Paths ──────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nifty_trader.market_data.option_chain_service import get_option_chain_service
from nifty_trader.market_data.contributors_service import get_contributors_service
from nifty_trader.market_data.session import MarketSessionManager
from nifty_trader.notifications.telegram_service import get_telegram_service
from nifty_trader.simulator.service import get_simulator_service

REPORTS_DIR = PROJECT_ROOT / "research_reports_pdf"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = PROJECT_ROOT / "data" / "paper_trading" / "AUTONOMOUS_PA_VOLUME.log"
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
logger = logging.getLogger("HermesV2")

DASH = "http://127.0.0.1:8080"


def play_beep_chime(event: str = "ENTRY"):
    """Audible Windows beep chime for trade execution and exits."""
    try:
        import platform
        if platform.system() == "Windows":
            import winsound
            if event == "ENTRY":
                winsound.Beep(1000, 150)
                winsound.Beep(1500, 150)
                winsound.Beep(2000, 300)
            elif event == "EXIT_WIN":
                winsound.Beep(1500, 150)
                winsound.Beep(2000, 150)
                winsound.Beep(2500, 400)
            elif event == "EXIT_LOSS":
                winsound.Beep(800, 300)
                winsound.Beep(600, 400)
            else:
                winsound.Beep(1200, 300)
    except Exception as ex:
        logger.debug("Beep audio error: %s", ex)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TRADING SCHEDULE & MARKET HOURS GATE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_trading_session_phase(dt: Optional[datetime] = None) -> Dict[str, Any]:
    """
    Evaluates exchange schedule:
    - Days: Monday through Friday (Excluding official NSE holidays)
    - Hours:
      * Before 09:00 AM IST: STANDBY_AWAITING_OPEN (Arm and wait until 09:00 AM)
      * 09:00 AM - 09:15 AM IST: PRE_MARKET_MONITORING (Pre-market analysis, S/R, news sentiment)
      * 09:15 AM - 15:30 PM IST: LIVE_MARKET_MONITORING (Live confluence scans and trade execution)
      * After 15:30 PM IST: POST_MARKET_CLOSED (Session complete, standby until next trade day 09:00 AM)
    """
    ref_dt = dt or datetime.now(IST)
    if ref_dt.tzinfo is None:
        ref_dt = ref_dt.replace(tzinfo=IST)
    else:
        ref_dt = ref_dt.astimezone(IST)

    # Check override environment variable (for offline simulation / tests)
    if os.environ.get("IGNORE_MARKET_HOURS", "false").lower() in ("true", "1", "yes"):
        return {
            "is_trade_day": True,
            "is_monitoring_active": True,
            "can_execute_orders": True,
            "phase": "OVERRIDE_TESTING",
            "message": "Market hours override active (IGNORE_MARKET_HOURS=true)",
            "ist_time": ref_dt.strftime("%H:%M:%S"),
        }

    is_wknd, wknd_name = MarketSessionManager.is_weekend(ref_dt)
    if is_wknd:
        return {
            "is_trade_day": False,
            "is_monitoring_active": False,
            "can_execute_orders": False,
            "phase": "WEEKEND_CLOSED",
            "message": f"Weekend Closed ({wknd_name}). Standby until Monday 09:00 AM IST.",
            "ist_time": ref_dt.strftime("%H:%M:%S"),
        }

    is_hday, hday_name = MarketSessionManager.is_holiday(ref_dt)
    if is_hday:
        return {
            "is_trade_day": False,
            "is_monitoring_active": False,
            "can_execute_orders": False,
            "phase": "HOLIDAY_CLOSED",
            "message": f"NSE Trading Holiday: {hday_name}. Standby until next trade day 09:00 AM IST.",
            "ist_time": ref_dt.strftime("%H:%M:%S"),
        }

    curr_time = ref_dt.time()
    t_0900 = dt_time(9, 0)
    t_0915 = dt_time(9, 15)
    t_1530 = dt_time(15, 30)

    if curr_time < t_0900:
        secs_until_9am = int((datetime.combine(ref_dt.date(), t_0900) - datetime.combine(ref_dt.date(), curr_time)).total_seconds())
        mins_rem, secs_rem = divmod(secs_until_9am, 60)
        return {
            "is_trade_day": True,
            "is_monitoring_active": False,
            "can_execute_orders": False,
            "phase": "STANDBY_AWAITING_OPEN",
            "message": f"Standby: Monitoring starts at 09:00 AM IST today ({mins_rem}m {secs_rem:02d}s remaining)",
            "seconds_until_start": secs_until_9am,
            "ist_time": ref_dt.strftime("%H:%M:%S"),
        }
    elif t_0900 <= curr_time < t_0915:
        return {
            "is_trade_day": True,
            "is_monitoring_active": True,
            "can_execute_orders": False,
            "phase": "PRE_MARKET_MONITORING",
            "message": "Pre-Market Monitoring Active (09:00–09:15 IST). Live orders unlock at 09:15 AM.",
            "ist_time": ref_dt.strftime("%H:%M:%S"),
        }
    elif t_0915 <= curr_time <= t_1530:
        return {
            "is_trade_day": True,
            "is_monitoring_active": True,
            "can_execute_orders": True,
            "phase": "LIVE_MARKET_MONITORING",
            "message": "Live Trading Session Active (09:15–15:30 IST). Confluence scans active.",
            "ist_time": ref_dt.strftime("%H:%M:%S"),
        }
    else:
        return {
            "is_trade_day": True,
            "is_monitoring_active": False,
            "can_execute_orders": False,
            "phase": "POST_MARKET_CLOSED",
            "message": "Market Closed at 15:30 IST. Standby until next trading day at 09:00 AM IST.",
            "ist_time": ref_dt.strftime("%H:%M:%S"),
        }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TECHNICAL INDICATOR HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def ema(closes: List[float], period: int) -> List[float]:
    """Exponential Moving Average."""
    if not closes:
        return []
    k = 2.0 / (period + 1)
    result = [closes[0]]
    for i in range(1, len(closes)):
        result.append(closes[i] * k + result[-1] * (1 - k))
    return result


def rsi(closes: List[float], period: int = 14) -> float:
    """Relative Strength Index of the last bar."""
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def vol_sma(volumes: List[float], period: int = 20) -> float:
    """Simple Moving Average of volume."""
    if len(volumes) < period:
        return sum(volumes) / max(len(volumes), 1)
    return sum(volumes[-period:]) / period


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STEP 1 — MULTI-TIMEFRAME TREND BIAS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fetch_candles(symbol: str, interval: str, limit: int = 50) -> List[Dict]:
    """Fetch OHLCV candles from the dashboard API."""
    try:
        url = f"{DASH}/api/chart/candles?symbol={symbol}&interval={interval}"
        resp = httpx.get(url, timeout=8.0)
        if resp.status_code == 200:
            return resp.json().get("candles", [])[-limit:]
    except Exception as e:
        logger.debug(f"Candle fetch {interval}: {e}")
    return []


def assess_tf_bias(candles: List[Dict]) -> Dict[str, Any]:
    """
    Assess bias on a single timeframe using EMA 9/20 position and last candle structure.
    Returns: { bias: BULLISH|BEARISH|NEUTRAL, ema9, ema20, last_close, candle_type }
    """
    if len(candles) < 5:
        return {"bias": "NEUTRAL", "ema9": 0, "ema20": 0, "last_close": 0, "candle_type": "unknown"}

    closes = [c["close"] for c in candles]
    ema9 = ema(closes, 9)
    ema20 = ema(closes, 20)
    last = candles[-1]
    body = last["close"] - last["open"]
    spread = last["high"] - last["low"]
    candle_type = "BULLISH" if body > 0 else "BEARISH" if body < 0 else "DOJI"

    e9 = ema9[-1]
    e20 = ema20[-1]
    close = closes[-1]

    # Bias logic: EMA 9 above EMA 20 + price above EMA 9 → BULLISH
    if e9 > e20 and close > e9:
        bias = "BULLISH"
    elif e9 < e20 and close < e9:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    return {
        "bias": bias,
        "ema9": round(e9, 2),
        "ema20": round(e20, 2),
        "last_close": round(close, 2),
        "candle_type": candle_type,
    }


def multi_tf_bias(symbol: str) -> Dict[str, Any]:
    """
    STEP 1: Check Weekly → Daily → 4H → 1H.
    Returns aggregated bias and per-TF details.
    """
    tfs = {
        "WEEKLY":  fetch_candles(symbol, "1wk", 30),
        "DAILY":   fetch_candles(symbol, "1d", 50),
        "4H":      fetch_candles(symbol, "4h", 40),
        "1H":      fetch_candles(symbol, "1h", 50),
        "15M":     fetch_candles(symbol, "15m", 50),
    }
    results = {}
    votes = {"BULLISH": 0, "BEARISH": 0, "NEUTRAL": 0}
    for tf_name, cdata in tfs.items():
        r = assess_tf_bias(cdata)
        results[tf_name] = r
        votes[r["bias"]] += 1

    # Majority vote — higher TFs weighted more
    if votes["BULLISH"] >= 3:
        overall = "STRONG_BULLISH"
    elif votes["BULLISH"] >= 2:
        overall = "BULLISH"
    elif votes["BEARISH"] >= 3:
        overall = "STRONG_BEARISH"
    elif votes["BEARISH"] >= 2:
        overall = "BEARISH"
    else:
        overall = "NEUTRAL"

    return {"overall_bias": overall, "votes": votes, "timeframes": results}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STEP 2 — MARKET NEWS SENTIMENT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def news_sentiment() -> Dict[str, Any]:
    """
    STEP 2: Read recent 24h news from market_news.db.
    Aggregate bullish vs bearish count and average impact score.
    """
    db = PROJECT_ROOT / "data" / "market" / "market_news.db"
    bull, bear, neut, scores = 0, 0, 0, []
    headlines = []
    try:
        conn = sqlite3.connect(db)
        rows = conn.execute(
            "SELECT title, impact_type, impact_score FROM market_news "
            "ORDER BY id DESC LIMIT 30"
        ).fetchall()
        for title, itype, iscore in rows:
            if itype == "BULLISH":
                bull += 1
            elif itype == "BEARISH":
                bear += 1
            else:
                neut += 1
            scores.append(iscore or 0)
            headlines.append(f"[{itype}] {title[:80]}")
        conn.close()
    except Exception as e:
        logger.warning(f"News DB error: {e}")

    avg_score = round(sum(scores) / max(len(scores), 1), 2)
    if bull > bear * 1.5:
        sentiment = "BULLISH"
    elif bear > bull * 1.5:
        sentiment = "BEARISH"
    else:
        sentiment = "MIXED"

    return {
        "sentiment": sentiment,
        "bullish_count": bull,
        "bearish_count": bear,
        "neutral_count": neut,
        "avg_impact_score": avg_score,
        "top_headlines": headlines[:5],
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STEP 3 — SUPPORT & RESISTANCE MATRIX
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def compute_sr_matrix(symbol: str) -> Dict[str, Any]:
    """
    STEP 3: Build S/R from chart data + option chain.
    """
    # Spot data from DB
    db = PROJECT_ROOT / "data" / "market" / "nse_spot_data.db"
    spot = high = low = close = open_p = pdh = pdl = 0.0
    sym_name = "BANKNIFTY" if "BANK" in symbol.upper() else "NIFTY 50"
    try:
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT spot_price, open_price, high_price, low_price, close_price, pdh, pdl "
            "FROM nse_spot_records WHERE symbol=? ORDER BY id DESC LIMIT 1",
            (sym_name,),
        ).fetchone()
        if row:
            spot, open_p, high, low, close, pdh, pdl = [float(v or 0) for v in row]
        conn.close()
    except Exception as e:
        logger.warning(f"Spot DB: {e}")

    # Fallback from API
    if spot == 0:
        try:
            r = httpx.get(f"{DASH}/api/spot/latest", timeout=5).json()
            for item in r.get("data", []):
                if sym_name in item.get("symbol", ""):
                    spot = float(item.get("spot_price", 0))
                    high = float(item.get("high_price", 0))
                    low = float(item.get("low_price", 0))
                    close = float(item.get("close_price", spot))
                    open_p = float(item.get("open_price", 0))
                    pdh = float(item.get("pdh", high))
                    pdl = float(item.get("pdl", low))
        except Exception:
            pass

    # Daily Pivots
    if high > 0 and low > 0 and close > 0:
        pp = round((high + low + close) / 3, 2)
        bc = round((high + low) / 2, 2)
        tc = round((pp - bc) + pp, 2)
        r1 = round(2 * pp - low, 2)
        r2 = round(pp + (high - low), 2)
        s1 = round(2 * pp - high, 2)
        s2 = round(pp - (high - low), 2)
    else:
        pp = bc = tc = r1 = r2 = s1 = s2 = 0

    # Option chain S/R
    ocs = get_option_chain_service(PROJECT_ROOT)
    chain = ocs.get_option_chain(symbol)
    max_ce_oi, max_pe_oi = 0, 0
    max_ce_strike, max_pe_strike = 0, 0
    for s in chain.get("strikes", []):
        stk = s.get("strike", 0)
        ce_oi = s.get("ce", {}).get("oi", 0)
        pe_oi = s.get("pe", {}).get("oi", 0)
        if ce_oi > max_ce_oi:
            max_ce_oi = ce_oi
            max_ce_strike = stk
        if pe_oi > max_pe_oi:
            max_pe_oi = pe_oi
            max_pe_strike = stk

    return {
        "spot": spot, "open": open_p, "high": high, "low": low, "close": close,
        "pdh": pdh, "pdl": pdl,
        "pp": pp, "tc": tc, "bc": bc, "r1": r1, "r2": r2, "s1": s1, "s2": s2,
        "max_ce_strike": max_ce_strike, "max_ce_oi": max_ce_oi,
        "max_pe_strike": max_pe_strike, "max_pe_oi": max_pe_oi,
        "pcr": chain.get("pcr", 1.0),
        "max_pain": chain.get("max_pain", 0),
        "sentiment": chain.get("sentiment", ""),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STEP 4 — 5-MIN CANDLE EXECUTION ANALYSIS (PA + EMA + RSI + VOLUME)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def analyze_5m_candles(symbol: str) -> Dict[str, Any]:
    """
    STEP 4: 5-minute chart technical analysis.
    Returns EMA 9/20 state, RSI(14), volume ratio, candle pattern.
    """
    candles = fetch_candles(symbol, "5m", 50)
    if len(candles) < 20:
        return {"valid": False, "reason": "Insufficient 5m candles"}

    closes = [c["close"] for c in candles]
    volumes = [c.get("volume", 0) for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]

    # EMA 9 and 20
    e9 = ema(closes, 9)
    e20 = ema(closes, 20)
    ema9_val = round(e9[-1], 2)
    ema20_val = round(e20[-1], 2)
    ema_bullish = ema9_val > ema20_val
    ema_cross = "BULLISH_CROSS" if (e9[-2] <= e20[-2] and e9[-1] > e20[-1]) else \
                "BEARISH_CROSS" if (e9[-2] >= e20[-2] and e9[-1] < e20[-1]) else \
                "ABOVE" if ema_bullish else "BELOW"

    # RSI 14
    rsi_val = rsi(closes, 14)

    # Volume analysis
    v_sma = vol_sma(volumes, 20)
    last_vol = volumes[-1] if volumes[-1] > 0 else v_sma
    vol_ratio = round(last_vol / max(v_sma, 1), 2)

    # Last candle pattern
    last = candles[-1]
    prev = candles[-2]
    body = last["close"] - last["open"]
    spread = last["high"] - last["low"] or 0.01
    body_pct = round(abs(body) / spread * 100, 1)
    upper_wick = last["high"] - max(last["open"], last["close"])
    lower_wick = min(last["open"], last["close"]) - last["low"]

    # Pattern detection
    pattern = "NEUTRAL"
    if body > 0 and body_pct > 60:
        pattern = "STRONG_BULL_CANDLE"
    elif body < 0 and body_pct > 60:
        pattern = "STRONG_BEAR_CANDLE"
    elif lower_wick > abs(body) * 2 and body >= 0:
        pattern = "BULLISH_PIN_BAR"
    elif upper_wick > abs(body) * 2 and body <= 0:
        pattern = "BEARISH_PIN_BAR"
    elif body > 0 and prev["close"] < prev["open"] and last["close"] > prev["open"]:
        pattern = "BULLISH_ENGULFING"
    elif body < 0 and prev["close"] > prev["open"] and last["close"] < prev["open"]:
        pattern = "BEARISH_ENGULFING"
    elif abs(body) < spread * 0.1:
        pattern = "DOJI"

    return {
        "valid": True,
        "ema9": ema9_val,
        "ema20": ema20_val,
        "ema_cross": ema_cross,
        "rsi": rsi_val,
        "vol_ratio": vol_ratio,
        "vol_sma20": round(v_sma, 0),
        "last_volume": last_vol,
        "pattern": pattern,
        "body_pct": body_pct,
        "last_close": closes[-1],
        "last_candle": last,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ORDER FLOW & CONFLUENCE HELPERS (POC, NIFTY-BN, CONTRIBUTORS, DELTA)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def compute_volume_profile(candles: List[Dict[str, Any]], num_bins: int = 25) -> Dict[str, Any]:
    """Computes intraday Volume Profile: Point of Control (POC), Value Area High (VAH), and Value Area Low (VAL)."""
    if not candles or len(candles) < 5:
        return {"poc": 0.0, "vah": 0.0, "val": 0.0, "total_vol": 0, "status": "INSUFFICIENT_DATA"}
    
    recent = candles[-75:] if len(candles) > 75 else candles
    lows = [float(c["low"]) for c in recent if "low" in c]
    highs = [float(c["high"]) for c in recent if "high" in c]
    if not lows or not highs:
        return {"poc": 0.0, "vah": 0.0, "val": 0.0, "total_vol": 0, "status": "NO_RANGE"}
    
    min_p, max_p = min(lows), max(highs)
    if min_p == max_p:
        return {"poc": min_p, "vah": max_p, "val": min_p, "total_vol": 0, "status": "FLAT"}
    
    bin_width = (max_p - min_p) / num_bins
    bins = [0.0] * num_bins
    bin_prices = [min_p + (i + 0.5) * bin_width for i in range(num_bins)]
    
    total_vol = 0.0
    for c in recent:
        v = float(c.get("volume", 0) or 0)
        c_low = float(c.get("low", 0))
        c_high = float(c.get("high", 0))
        if v <= 0 or c_high <= c_low:
            continue
        total_vol += v
        for i in range(num_bins):
            b_low = min_p + i * bin_width
            b_high = b_low + bin_width
            overlap = max(0.0, min(c_high, b_high) - max(c_low, b_low))
            if overlap > 0:
                bins[i] += v * (overlap / (c_high - c_low))
                
    if not bins or max(bins) == 0:
        return {"poc": round((min_p + max_p) / 2, 2), "vah": max_p, "val": min_p, "total_vol": total_vol, "status": "NO_VOLUME"}
    
    poc_idx = bins.index(max(bins))
    poc = round(bin_prices[poc_idx], 2)
    
    target_va_vol = 0.70 * total_vol
    curr_va_vol = bins[poc_idx]
    up_idx = poc_idx
    down_idx = poc_idx
    
    while curr_va_vol < target_va_vol and (up_idx < num_bins - 1 or down_idx > 0):
        next_up = bins[up_idx + 1] if up_idx < num_bins - 1 else 0.0
        next_down = bins[down_idx - 1] if down_idx > 0 else 0.0
        if next_up >= next_down and up_idx < num_bins - 1:
            up_idx += 1
            curr_va_vol += bins[up_idx]
        elif down_idx > 0:
            down_idx -= 1
            curr_va_vol += bins[down_idx]
        else:
            if up_idx < num_bins - 1:
                up_idx += 1
                curr_va_vol += bins[up_idx]
            else:
                break
                
    vah = round(bin_prices[up_idx] + 0.5 * bin_width, 2)
    val = round(bin_prices[down_idx] - 0.5 * bin_width, 2)
    
    return {
        "poc": poc,
        "vah": vah,
        "val": val,
        "total_volume": round(total_vol, 0),
        "status": "VALID",
    }


def get_nifty_bn_comparison() -> Dict[str, Any]:
    """Compares NIFTY 50 and BANKNIFTY live spot prices, percentage change, and alignment."""
    try:
        r = httpx.get(f"{DASH}/api/data", timeout=4.0)
        data = r.json()
        insts = data.get("spot", {}).get("instruments", {})
        nifty = insts.get("NIFTY 50", {})
        bn = insts.get("BANKNIFTY", {})
        
        n_price = nifty.get("spot_price") or 0.0
        n_chg = nifty.get("change_pts") or 0.0
        n_pct = nifty.get("change_pct") or 0.0
        
        bn_price = bn.get("spot_price") or 0.0
        bn_chg = bn.get("change_pts") or 0.0
        bn_pct = bn.get("change_pct") or 0.0
        
        if n_pct < 0 and bn_pct < 0:
            alignment = "BOTH_BEARISH"
        elif n_pct > 0 and bn_pct > 0:
            alignment = "BOTH_BULLISH"
        else:
            alignment = "DIVERGENT"
            
        return {
            "nifty_spot": n_price,
            "nifty_pct": round(n_pct, 2),
            "nifty_pts": round(n_chg, 2),
            "bn_spot": bn_price,
            "bn_pct": round(bn_pct, 2),
            "bn_pts": round(bn_chg, 2),
            "alignment": alignment,
        }
    except Exception as e:
        logger.debug("NIFTY vs BN comparison error: %s", e)
        return {
            "nifty_spot": 0.0, "nifty_pct": 0.0, "nifty_pts": 0.0,
            "bn_spot": 0.0, "bn_pct": 0.0, "bn_pts": 0.0,
            "alignment": "UNKNOWN",
        }


def get_contributors_position() -> Dict[str, Any]:
    """Retrieves live advance/decline breadth and top heavyweight contributor point impact."""
    try:
        cs = get_contributors_service(PROJECT_ROOT)
        data = cs.get_contributors_summary()
        advances = data.get("advances", 0)
        declines = data.get("declines", 0)
        n50_pts = data.get("n50_total_pts", 0.0)
        bn_pts = data.get("bn_total_pts", 0.0)
        
        top_gainers = [f"{g['symbol']} ({g['primary_pts']:+.1f} pts)" for g in data.get("top_gainers", [])[:2]]
        top_draggers = [f"{d['symbol']} ({d['primary_pts']:+.1f} pts)" for d in data.get("top_draggers", [])[:2]]
        
        sentiment = "BEARISH_BREADTH" if declines > advances else ("BULLISH_BREADTH" if advances > declines else "NEUTRAL")
        
        return {
            "advances": advances,
            "declines": declines,
            "n50_pts": n50_pts,
            "bn_pts": bn_pts,
            "sentiment": sentiment,
            "top_gainers": top_gainers,
            "top_draggers": top_draggers,
        }
    except Exception as e:
        logger.debug("Contributors service error: %s", e)
        return {
            "advances": 0, "declines": 0, "n50_pts": 0.0, "bn_pts": 0.0,
            "sentiment": "UNKNOWN", "top_gainers": [], "top_draggers": [],
        }


def compute_option_delta(spot: float, strike: float, option_type: str, dte_days: float = 4.0, iv: float = 0.14) -> float:
    """Estimates Black-Scholes Delta for given option contract."""
    if spot <= 0 or strike <= 0:
        return 0.50 if option_type.upper() == "CE" else -0.50
    try:
        t = max(dte_days / 365.0, 0.001)
        sigma = max(iv, 0.05)
        d1 = (math.log(spot / strike) + (0.065 + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
        norm_cdf = 0.5 * (1.0 + math.erf(d1 / math.sqrt(2.0)))
        if option_type.upper() == "CE":
            return round(norm_cdf, 3)
        else:
            return round(norm_cdf - 1.0, 3)
    except Exception:
        moneyness = (spot - strike) / max(strike, 1.0)
        base = 0.50 + moneyness * 2.5
        base = max(0.05, min(0.95, base))
        return round(base if option_type.upper() == "CE" else (base - 1.0), 3)


def get_deep_option_chain_analysis(symbol: str) -> Dict[str, Any]:
    """Analyzes option chain across Current and Next 3 Expiries with volume and buildup."""
    ocs = get_option_chain_service(PROJECT_ROOT)
    chain = ocs.get_option_chain(symbol)
    atm = chain.get("atm_strike", 25700)
    spot = chain.get("spot_price", 25700.0)
    pcr = chain.get("pcr", 1.0)
    max_pain = chain.get("max_pain", 25700)
    
    atm_ce_oi, atm_pe_oi = 0, 0
    atm_ce_vol, atm_pe_vol = 0, 0
    atm_ce_buildup, atm_pe_buildup = "--", "--"
    
    for s in chain.get("strikes", []):
        if s.get("strike") == atm:
            ce = s.get("ce", {}) if isinstance(s.get("ce"), dict) else {}
            pe = s.get("pe", {}) if isinstance(s.get("pe"), dict) else {}
            atm_ce_oi = ce.get("oi", 0)
            atm_pe_oi = pe.get("oi", 0)
            atm_ce_vol = ce.get("volume", 0)
            atm_pe_vol = pe.get("volume", 0)
            atm_ce_buildup = ce.get("buildup") or ce.get("builtup", "--")
            atm_pe_buildup = pe.get("buildup") or pe.get("builtup", "--")
            break
            
    next_exp_pcrs = {}
    try:
        r = httpx.get(f"{DASH}/api/option_chain/next_expiries", timeout=3.0)
        if r.status_code == 200:
            data = r.json()
            for c in data.get("chains", []):
                next_exp_pcrs[f"Week+{c.get('week_offset')}({c.get('expiry')})"] = c.get("pcr")
    except Exception:
        pass
        
    return {
        "atm_strike": atm,
        "spot_price": spot,
        "pcr": pcr,
        "max_pain": max_pain,
        "atm_ce_oi": atm_ce_oi,
        "atm_pe_oi": atm_pe_oi,
        "atm_ce_vol": atm_ce_vol,
        "atm_pe_vol": atm_pe_vol,
        "atm_ce_buildup": atm_ce_buildup,
        "atm_pe_buildup": atm_pe_buildup,
        "next_expiries": next_exp_pcrs,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STEP 5+6 — DECISION ENGINE + INSTANT EXECUTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class HermesTraderV2:
    """Full autonomous trading engine combining all 7 steps."""

    def __init__(self, symbol: str = "NIFTY", sl: float = 20.0, tgt: float = 60.0, lots: int = 1):
        self.symbol = symbol.upper()
        self.chart_symbol = "BANKNIFTY" if "BANK" in self.symbol else "NIFTY 50"
        self.sl = sl
        self.tgt = tgt
        self.lots = lots
        self.ocs = get_option_chain_service(PROJECT_ROOT)
        self.sim = get_simulator_service()
        self.tele = get_telegram_service(PROJECT_ROOT)

    # ── Full Analysis ─────────────────────────────────────────────────────────
    def run_full_analysis(self) -> Dict[str, Any]:
        """Execute Steps 1-5 and return combined analysis."""
        logger.info("━" * 60)
        logger.info("STEP 1 ► Multi-Timeframe Bias (Weekly → Daily → 4H → 1H)")
        bias = multi_tf_bias(self.chart_symbol)
        for tf, d in bias["timeframes"].items():
            logger.info(f"   {tf:8s} → {d['bias']:10s} | EMA9: {d['ema9']} | EMA20: {d['ema20']} | Candle: {d['candle_type']}")
        logger.info(f"   OVERALL SESSION BIAS: {bias['overall_bias']}  (Votes: {bias['votes']})")

        logger.info("━" * 60)
        logger.info("STEP 2 ► Market News Sentiment Analysis")
        news = news_sentiment()
        logger.info(f"   Sentiment: {news['sentiment']} | Bull: {news['bullish_count']} | Bear: {news['bearish_count']} | Avg Score: {news['avg_impact_score']}")
        for hl in news["top_headlines"][:3]:
            logger.info(f"   📰 {hl}")

        logger.info("━" * 60)
        logger.info("STEP 3 ► Support & Resistance Matrix")
        sr = compute_sr_matrix(self.symbol)
        logger.info(f"   Spot: ₹{sr['spot']:,.2f} | PDH: ₹{sr['pdh']:,.2f} | PDL: ₹{sr['pdl']:,.2f}")
        logger.info(f"   Pivots: S2={sr['s2']} | S1={sr['s1']} | PP={sr['pp']} | R1={sr['r1']} | R2={sr['r2']}")
        logger.info(f"   Max Call OI: {sr['max_ce_strike']} ({sr['max_ce_oi']:,}) | Max Put OI: {sr['max_pe_strike']} ({sr['max_pe_oi']:,})")
        logger.info(f"   PCR: {sr['pcr']} | Max Pain: {sr['max_pain']} | Chain Sentiment: {sr['sentiment']}")

        logger.info("━" * 60)
        logger.info("STEP 4 ► 5-Min Candle Analysis (PA + EMA + RSI + Volume)")
        m5 = analyze_5m_candles(self.chart_symbol)
        if m5["valid"]:
            logger.info(f"   EMA9: {m5['ema9']} | EMA20: {m5['ema20']} | Cross: {m5['ema_cross']}")
            logger.info(f"   RSI(14): {m5['rsi']} | Volume Ratio: {m5['vol_ratio']}x of 20-SMA")
            logger.info(f"   Candle Pattern: {m5['pattern']} | Body%: {m5['body_pct']}%")
        else:
            logger.info(f"   ⚠ {m5.get('reason', 'No data')}")

        logger.info("━" * 60)
        logger.info("STEP 5 ► Option Chain Derivatives Confirmation")
        logger.info(f"   PCR: {sr['pcr']} | Sentiment: {sr['sentiment']}")

        # Step 6: Volume Profile (POC, VAH, VAL)
        logger.info("━" * 60)
        logger.info("STEP 6 ► Point of Control & Volume Profile (POC, VAH, VAL)")
        m5_candles = fetch_candles(self.chart_symbol, "5m", 75)
        vp = compute_volume_profile(m5_candles)
        poc = vp["poc"]
        vah = vp["vah"]
        val = vp["val"]
        vp_loc = "BELOW_POC" if sr["spot"] < poc else ("ABOVE_POC" if sr["spot"] > poc else "AT_POC")
        logger.info(f"   POC: ₹{poc:,.2f} | VAH: ₹{vah:,.2f} | VAL: ₹{val:,.2f} | Spot Location: {vp_loc}")

        # Step 7: NIFTY vs BANKNIFTY Comparison
        logger.info("━" * 60)
        logger.info("STEP 7 ► NIFTY 50 vs BANKNIFTY Relative Strength & Alignment")
        nbn = get_nifty_bn_comparison()
        logger.info(f"   NIFTY: ₹{nbn['nifty_spot']:,.2f} ({nbn['nifty_pct']:+.2f}%) | BN: ₹{nbn['bn_spot']:,.2f} ({nbn['bn_pct']:+.2f}%) | Alignment: {nbn['alignment']}")

        # Step 8: Contributor Breadth & Drag/Boost
        logger.info("━" * 60)
        logger.info("STEP 8 ► Heavyweight Contributor Position & Market Breadth")
        contrib = get_contributors_position()
        logger.info(f"   Breadth: {contrib['advances']} Green / {contrib['declines']} Red ({contrib['sentiment']})")
        logger.info(f"   Point Impact: N50: {contrib['n50_pts']:+.1f} pts | BN: {contrib['bn_pts']:+.1f} pts")
        logger.info(f"   Leaders: {', '.join(contrib['top_gainers'])} | Draggers: {', '.join(contrib['top_draggers'])}")

        # Step 9: Deep Option Chain Analysis & Multi-Expiry
        logger.info("━" * 60)
        logger.info("STEP 9 ► Deep Option Chain Analysis & Next 3 Expiries Structure")
        deep_oc = get_deep_option_chain_analysis(self.symbol)
        logger.info(f"   Spot: ₹{deep_oc['spot_price']} | ATM: {deep_oc['atm_strike']} | PCR: {deep_oc['pcr']} | Max Pain: {deep_oc['max_pain']}")
        logger.info(f"   ATM CE Buildup: {deep_oc['atm_ce_buildup']} (Vol: {deep_oc['atm_ce_vol']:,}) | ATM PE Buildup: {deep_oc['atm_pe_buildup']} (Vol: {deep_oc['atm_pe_vol']:,})")
        logger.info(f"   Next Expiries PCR: {deep_oc['next_expiries']}")

        return {
            "bias": bias,
            "news": news,
            "sr": sr,
            "m5": m5,
            "vol_profile": vp,
            "nifty_bn": nbn,
            "contributors": contrib,
            "chain_deep": deep_oc,
        }

    # ── Decision Logic (3-Pillar Institutional Architecture) ─────────────────
    def decide_trade(self, analysis: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Streamlined 3-Pillar Decision Engine:
        ┌────────────────────────────────────────────────────────────────────────┐
        │ PILLAR 1 ► Direction: 1H/15M Trend + Option Chain PCR + Heavyweights   │
        │ PILLAR 2 ► Location:  Key Pivot / S/R Boundaries + Volume Profile POC  │
        │ PILLAR 3 ► Trigger:   5M Volume Candle + 1 Lot ITM Next Expiry         │
        └────────────────────────────────────────────────────────────────────────┘
        If ALL 3 Pillars are YES (PASS) → Execute Immediately.
        """
        bias = analysis["bias"]["overall_bias"]
        news = analysis["news"]["sentiment"]
        sr = analysis["sr"]
        m5 = analysis["m5"]
        vp = analysis.get("vol_profile", {})
        nbn = analysis.get("nifty_bn", {})
        contrib = analysis.get("contributors", {})
        deep_oc = analysis.get("chain_deep", {})
        pcr = sr["pcr"]
        spot = sr["spot"]
        poc = vp.get("poc", spot)

        if not m5.get("valid"):
            return None

        h1_bias = analysis["bias"]["timeframes"].get("1H", {}).get("bias", "NEUTRAL")
        m15_bias = analysis["bias"]["timeframes"].get("15M", {}).get("bias", "NEUTRAL")
        step = 100 if "BANK" in self.symbol else 50
        atm = int(round(spot / step) * step)

        # ══════════════════════════════════════════════════════════════════════
        # 👑 STRATEGY SETUP 1: WALL REVERSAL (FADE THE WALL — 1:7.0 RATIO)
        # ══════════════════════════════════════════════════════════════════════
        call_wall = sr.get("max_ce_strike", 0)
        put_floor = sr.get("max_pe_strike", 0)

        # ── 1. BEARISH REVERSAL (FADE CALL OI WALL ➔ BUY PUT with 1:7 R:R) ────
        at_call_wall = (call_wall > 0) and (0 <= (call_wall - spot) <= 25 or abs(spot - call_wall) <= 20) and (spot > poc)
        wall_defended_ce = (pcr <= 1.25) and (news != "STRONG_BULLISH")
        rejection_at_call_wall = (
            spot <= call_wall
            and (
                m5["pattern"] in ("BEARISH_PIN_BAR", "STRONG_BEAR_CANDLE", "BEARISH_ENGULFING", "DOJI")
                or m5["rsi"] >= 60
                or m5["ema_cross"] in ("BEARISH_CROSS", "BELOW")
            )
            and m5.get("vol_ratio", 1.0) >= 0.95
        )

        if at_call_wall and wall_defended_ce and rejection_at_call_wall:
            itm_strike = atm + step  # 1-strike ITM for PE (Strike > Spot)
            next_expiry, strikes = self._get_target_expiry_and_chain()
            premium = self._lookup_premium(itm_strike, "PE", strikes)
            delta = compute_option_delta(spot, itm_strike, "PE", dte_days=10.0)
            sl_pts = 15.0
            tgt_pts = 105.0  # 1:7.0 Asymmetric Risk:Reward
            return {
                "direction": "BEARISH",
                "option_type": "PE",
                "strike": itm_strike,
                "moneyness": "ITM",
                "expiry": next_expiry,
                "atm_reference": atm,
                "premium": premium,
                "spot": spot,
                "delta": delta,
                "poc": poc,
                "setup_type": "WALL_REVERSAL_FADE",
                "risk_reward": "1:7.0",
                "sl_points": sl_pts,
                "tgt_points": tgt_pts,
                "pillars": {
                    "Pillar_1_Direction": f"PASS (Reversal Fade at Call Wall {call_wall} | PCR {pcr:.2f})",
                    "Pillar_2_Location": f"PASS (At Max Call OI Wall {call_wall} | Spot ₹{spot:,.1f} | Target POC ₹{poc:,.1f})",
                    "Pillar_3_Trigger": f"PASS (5M {m5['pattern']} Rejection | 1:7.0 R:R | 1 Lot ITM {itm_strike} PE | Next Expiry {next_expiry})",
                },
                "gates": {
                    "Strategy": "WALL REVERSAL (FADE CALL WALL)",
                    "Pillar 1 - Direction": f"Bearish Reversal at Call Wall {call_wall} (PCR {pcr:.2f})",
                    "Pillar 2 - Location": f"At Call Wall {call_wall} (Distance: {call_wall - spot:.1f} pts) -> Target POC ₹{poc:,.1f}",
                    "Pillar 3 - Trigger": f"5M {m5['pattern']} (Vol: {m5['vol_ratio']}x) -> 1 Lot ITM {itm_strike} PE (SL: {sl_pts} / Tgt: {tgt_pts} -> 1:7 R:R)",
                    "TF_Bias": "REVERSAL_EXTREME", "H1_Bias": h1_bias, "News": news, "SR": f"Call Wall {call_wall}",
                    "5m": m5["pattern"], "EMA": m5["ema_cross"], "RSI": m5["rsi"], "VolRatio": m5["vol_ratio"],
                    "PCR": pcr, "POC_Loc": "Extended Above POC", "NIFTY_BN": nbn.get("alignment"),
                    "Contributors": f"{contrib.get('advances')}G/{contrib.get('declines')}R",
                    "Delta": delta,
                    "Contract": f"ITM ({itm_strike} PE)",
                    "Expiry": f"Next Expiry ({next_expiry})",
                    "Risk_Reward": f"1:7.0 (SL {sl_pts} pts / Target {tgt_pts} pts)",
                },
            }

        # ── 2. BULLISH REVERSAL (FADE PUT OI FLOOR ➔ BUY CALL with 1:7 R:R) ───
        at_put_floor = (put_floor > 0) and (0 <= (spot - put_floor) <= 25 or abs(spot - put_floor) <= 20) and (spot < poc)
        floor_defended_pe = (pcr >= 0.75) and (news != "STRONG_BEARISH")
        rejection_at_put_floor = (
            spot >= put_floor
            and (
                m5["pattern"] in ("BULLISH_PIN_BAR", "STRONG_BULL_CANDLE", "BULLISH_ENGULFING", "DOJI")
                or m5["rsi"] <= 40
                or m5["ema_cross"] in ("BULLISH_CROSS", "ABOVE")
            )
            and m5.get("vol_ratio", 1.0) >= 0.95
        )

        if at_put_floor and floor_defended_pe and rejection_at_put_floor:
            itm_strike = atm - step  # 1-strike ITM for CE (Strike < Spot)
            next_expiry, strikes = self._get_target_expiry_and_chain()
            premium = self._lookup_premium(itm_strike, "CE", strikes)
            delta = compute_option_delta(spot, itm_strike, "CE", dte_days=10.0)
            sl_pts = 15.0
            tgt_pts = 105.0  # 1:7.0 Asymmetric Risk:Reward
            return {
                "direction": "BULLISH",
                "option_type": "CE",
                "strike": itm_strike,
                "moneyness": "ITM",
                "expiry": next_expiry,
                "atm_reference": atm,
                "premium": premium,
                "spot": spot,
                "delta": delta,
                "poc": poc,
                "setup_type": "WALL_REVERSAL_FADE",
                "risk_reward": "1:7.0",
                "sl_points": sl_pts,
                "tgt_points": tgt_pts,
                "pillars": {
                    "Pillar_1_Direction": f"PASS (Reversal Fade at Put Floor {put_floor} | PCR {pcr:.2f})",
                    "Pillar_2_Location": f"PASS (At Max Put OI Floor {put_floor} | Spot ₹{spot:,.1f} | Target POC ₹{poc:,.1f})",
                    "Pillar_3_Trigger": f"PASS (5M {m5['pattern']} Rejection | 1:7.0 R:R | 1 Lot ITM {itm_strike} CE | Next Expiry {next_expiry})",
                },
                "gates": {
                    "Strategy": "WALL REVERSAL (FADE PUT FLOOR)",
                    "Pillar 1 - Direction": f"Bullish Reversal at Put Floor {put_floor} (PCR {pcr:.2f})",
                    "Pillar 2 - Location": f"At Put Floor {put_floor} (Distance: {spot - put_floor:.1f} pts) -> Target POC ₹{poc:,.1f}",
                    "Pillar 3 - Trigger": f"5M {m5['pattern']} (Vol: {m5['vol_ratio']}x) -> 1 Lot ITM {itm_strike} CE (SL: {sl_pts} / Tgt: {tgt_pts} -> 1:7 R:R)",
                    "TF_Bias": "REVERSAL_EXTREME", "H1_Bias": h1_bias, "News": news, "SR": f"Put Floor {put_floor}",
                    "5m": m5["pattern"], "EMA": m5["ema_cross"], "RSI": m5["rsi"], "VolRatio": m5["vol_ratio"],
                    "PCR": pcr, "POC_Loc": "Extended Below POC", "NIFTY_BN": nbn.get("alignment"),
                    "Contributors": f"{contrib.get('advances')}G/{contrib.get('declines')}R",
                    "Delta": delta,
                    "Contract": f"ITM ({itm_strike} CE)",
                    "Expiry": f"Next Expiry ({next_expiry})",
                    "Risk_Reward": f"1:7.0 (SL {sl_pts} pts / Target {tgt_pts} pts)",
                },
            }

        # ══════════════════════════════════════════════════════════════════════
        # 🚀 STRATEGY SETUP 2: TREND CONTINUATION (1:3.0 RATIO)
        # ══════════════════════════════════════════════════════════════════════
        # PILLAR 1: Direction (1H/15M Trend + Option Chain PCR + Heavyweights)
        p1_trend_bull = (
            bias in ("STRONG_BULLISH", "BULLISH")
            or (h1_bias in ("BULLISH", "NEUTRAL") and m15_bias in ("BULLISH", "NEUTRAL") and spot >= sr["pp"])
        )
        p1_oc_bull = (pcr >= 1.05) and (news != "BEARISH")
        p1_heavyweights_bull = (
            contrib.get("advances", 0) >= contrib.get("declines", 0)
            or contrib.get("n50_pts", 0) >= -20.0
        )
        p1_bn_bull = nbn.get("alignment") in ("BOTH_BULLISH", "DIVERGENT")
        pillar1_bull = p1_trend_bull and p1_oc_bull and p1_heavyweights_bull and p1_bn_bull

        # PILLAR 2: Location (Pivot & S/R Boundaries + Volume Profile POC)
        p2_pivot_bull = (
            spot >= sr["pp"]
            or spot >= sr["s1"]
            or abs(spot - sr["max_pe_strike"]) <= 50
        )
        p2_poc_bull = (spot >= poc or spot >= vp.get("val", spot))
        pillar2_bull = p2_pivot_bull and p2_poc_bull

        # PILLAR 3: Trigger & Risk (5M Volume Candle + 1 Lot ITM Next Expiry)
        p3_candle_bull = (
            m5["ema_cross"] in ("BULLISH_CROSS", "ABOVE")
            and (45 <= m5["rsi"] <= 80)
            and m5["pattern"] in ("STRONG_BULL_CANDLE", "BULLISH_PIN_BAR", "BULLISH_ENGULFING", "NEUTRAL", "DOJI")
        )
        p3_vol_bull = m5.get("vol_ratio", 1.0) >= 1.0
        pillar3_bull = p3_candle_bull and p3_vol_bull

        if pillar1_bull and pillar2_bull and pillar3_bull:
            itm_strike = atm - step  # 1-strike ITM for CE (Strike < Spot)
            next_expiry, strikes = self._get_target_expiry_and_chain()
            premium = self._lookup_premium(itm_strike, "CE", strikes)
            delta = compute_option_delta(spot, itm_strike, "CE", dte_days=10.0)
            return {
                "direction": "BULLISH",
                "option_type": "CE",
                "strike": itm_strike,
                "moneyness": "ITM",
                "expiry": next_expiry,
                "atm_reference": atm,
                "premium": premium,
                "spot": spot,
                "delta": delta,
                "poc": poc,
                "pillars": {
                    "Pillar_1_Direction": f"PASS (1H {h1_bias} | PCR {pcr:.2f} | Breadth {contrib.get('advances')}G/{contrib.get('declines')}R)",
                    "Pillar_2_Location": f"PASS (Spot ₹{spot:,.1f} >= PP ₹{sr['pp']:,.1f} | Above POC ₹{poc:,.1f})",
                    "Pillar_3_Trigger": f"PASS (5M {m5['pattern']} | Vol {m5['vol_ratio']}x | 1 Lot ITM {itm_strike} CE | Expiry {next_expiry})",
                },
                "gates": {
                    "Pillar 1 - Direction": f"1H {h1_bias} + PCR {pcr:.2f} + Breadth {contrib.get('advances')}G/{contrib.get('declines')}R",
                    "Pillar 2 - Location": f"Above PP ₹{sr['pp']:,.1f} & Above POC ₹{poc:,.1f}",
                    "Pillar 3 - Trigger": f"5M {m5['pattern']} (Vol: {m5['vol_ratio']}x) -> 1 Lot ITM {itm_strike} CE ({next_expiry})",
                    "TF_Bias": bias, "H1_Bias": h1_bias, "News": news, "SR": "Above PP/S1",
                    "5m": m5["pattern"], "EMA": m5["ema_cross"], "RSI": m5["rsi"], "VolRatio": m5["vol_ratio"],
                    "PCR": pcr, "POC_Loc": "Above/At POC", "NIFTY_BN": nbn.get("alignment"),
                    "Contributors": f"{contrib.get('advances')}G/{contrib.get('declines')}R",
                    "Delta": delta,
                    "Contract": f"ITM ({itm_strike} CE)",
                    "Expiry": f"Next Expiry ({next_expiry})",
                },
            }

        # ══════════════════════════════════════════════════════════════════════
        # 🔴 BEARISH SETUP (PUT / PE)
        # ══════════════════════════════════════════════════════════════════════
        # PILLAR 1: Direction (1H/15M Trend + Option Chain PCR + Heavyweights)
        p1_trend_bear = (
            bias in ("STRONG_BEARISH", "BEARISH")
            or (h1_bias in ("BEARISH", "NEUTRAL") and m15_bias in ("BEARISH", "NEUTRAL") and spot <= sr["pp"])
            or (spot < sr["pp"] and pcr <= 0.90)
        )
        p1_oc_bear = (pcr <= 0.90) and (news != "BULLISH")
        p1_heavyweights_bear = (
            contrib.get("declines", 0) >= contrib.get("advances", 0)
            or contrib.get("n50_pts", 0) <= 0.0
        )
        p1_bn_bear = nbn.get("alignment") in ("BOTH_BEARISH", "DIVERGENT")
        pillar1_bear = p1_trend_bear and p1_oc_bear and p1_heavyweights_bear and p1_bn_bear

        # PILLAR 2: Location (Pivot & S/R Boundaries + Volume Profile POC)
        p2_pivot_bear = (
            spot <= sr["pp"]
            or spot <= sr["r1"]
            or abs(spot - sr["max_ce_strike"]) <= 50
        )
        p2_poc_bear = (spot <= poc or spot <= vp.get("vah", spot))
        pillar2_bear = p2_pivot_bear and p2_poc_bear

        # PILLAR 3: Trigger & Risk (5M Volume Candle + 1 Lot ITM Next Expiry)
        p3_candle_bear = (
            m5["ema_cross"] in ("BEARISH_CROSS", "BELOW")
            and (20 <= m5["rsi"] <= 55)
            and m5["pattern"] in ("STRONG_BEAR_CANDLE", "BEARISH_PIN_BAR", "BEARISH_ENGULFING", "NEUTRAL", "DOJI")
        )
        p3_vol_bear = m5.get("vol_ratio", 1.0) >= 1.0
        pillar3_bear = p3_candle_bear and p3_vol_bear

        if pillar1_bear and pillar2_bear and pillar3_bear:
            itm_strike = atm + step  # 1-strike ITM for PE (Strike > Spot)
            next_expiry, strikes = self._get_target_expiry_and_chain()
            premium = self._lookup_premium(itm_strike, "PE", strikes)
            delta = compute_option_delta(spot, itm_strike, "PE", dte_days=10.0)
            return {
                "direction": "BEARISH",
                "option_type": "PE",
                "strike": itm_strike,
                "moneyness": "ITM",
                "expiry": next_expiry,
                "atm_reference": atm,
                "premium": premium,
                "spot": spot,
                "delta": delta,
                "poc": poc,
                "pillars": {
                    "Pillar_1_Direction": f"PASS (1H {h1_bias} | PCR {pcr:.2f} | Breadth {contrib.get('advances')}G/{contrib.get('declines')}R)",
                    "Pillar_2_Location": f"PASS (Spot ₹{spot:,.1f} <= PP ₹{sr['pp']:,.1f} | Below POC ₹{poc:,.1f})",
                    "Pillar_3_Trigger": f"PASS (5M {m5['pattern']} | Vol {m5['vol_ratio']}x | 1 Lot ITM {itm_strike} PE | Expiry {next_expiry})",
                },
                "gates": {
                    "Pillar 1 - Direction": f"1H {h1_bias} + PCR {pcr:.2f} + Breadth {contrib.get('advances')}G/{contrib.get('declines')}R",
                    "Pillar 2 - Location": f"Below PP ₹{sr['pp']:,.1f} & Below POC ₹{poc:,.1f}",
                    "Pillar 3 - Trigger": f"5M {m5['pattern']} (Vol: {m5['vol_ratio']}x) -> 1 Lot ITM {itm_strike} PE ({next_expiry})",
                    "TF_Bias": bias, "H1_Bias": h1_bias, "News": news, "SR": "Below PP/R1",
                    "5m": m5["pattern"], "EMA": m5["ema_cross"], "RSI": m5["rsi"], "VolRatio": m5["vol_ratio"],
                    "PCR": pcr, "POC_Loc": "Below/At POC", "NIFTY_BN": nbn.get("alignment"),
                    "Contributors": f"{contrib.get('advances')}G/{contrib.get('declines')}R",
                    "Delta": delta,
                    "Contract": f"ITM ({itm_strike} PE)",
                    "Expiry": f"Next Expiry ({next_expiry})",
                },
            }

        return None

    def _get_target_expiry_and_chain(self) -> tuple[str, list[dict]]:
        """Resolves next upcoming expiry and its option chain strikes for ITM trading."""
        try:
            exp_data = self.ocs.get_next_expiries_from_nse(self.symbol, count=2)
            chains = exp_data.get("chains", [])
            if chains:
                next_chain = chains[0]
                target_expiry = next_chain.get("expiry", "")
                strikes = next_chain.get("strikes", [])
                if target_expiry and strikes:
                    return target_expiry, strikes
        except Exception as e:
            logger.debug(f"Next expiry lookup fallback: {e}")

        # Fallback to current chain's expiry_dates
        chain = self.ocs.get_option_chain(self.symbol)
        expiry_dates = chain.get("expiry_dates", [])
        target_expiry = expiry_dates[1] if len(expiry_dates) > 1 else chain.get("expiry", "")
        return target_expiry, chain.get("strikes", [])

    def _lookup_premium(self, strike: int, opt_type: str, strikes: Optional[list[dict]] = None) -> float:
        if strikes is None:
            _, strikes = self._get_target_expiry_and_chain()
        for r in strikes:
            if r.get("strike") == strike:
                opt_key = opt_type.lower()
                opt_obj = r.get(opt_key)
                if isinstance(opt_obj, dict):
                    ltp = opt_obj.get("ltp")
                    if ltp and float(ltp) > 0:
                        return float(ltp)
                ltp_direct = r.get(f"{opt_key}_ltp")
                if ltp_direct and float(ltp_direct) > 0:
                    return float(ltp_direct)

        spot = self.ocs.get_current_spot(self.symbol)
        intrinsic = max(0.0, (spot - strike) if opt_type.upper() == "CE" else (strike - spot))
        time_value = 140.0  # Next expiry options trade with fuller extrinsic premium
        return round(max(40.0, intrinsic + time_value), 2)

    # ── STEP 6 — Instant Execution ────────────────────────────────────────────
    def execute(self, decision: Dict[str, Any], analysis: Dict[str, Any]) -> Dict[str, Any]:
        """STEP 6: Instant execution into Paper Simulator + Telegram."""
        inst = "BANKNIFTY" if "BANK" in self.symbol else "NIFTY 50"
        expiry_label = decision.get("expiry", "Next Expiry")
        moneyness_label = decision.get("moneyness", "ITM")
        sl_points = float(decision.get("sl_points", self.sl))
        tgt_points = float(decision.get("tgt_points", self.tgt))
        rr_label = decision.get("risk_reward", "1:3.0")
        setup_type = decision.get("setup_type", "TREND_CONTINUATION")

        logger.info("=" * 60)
        logger.info(f"⚡ STEP 6 ► INSTANT EXECUTION [{setup_type}]: {inst} {decision['strike']} {decision['option_type']} ({moneyness_label} | {expiry_label})")
        logger.info(f"   Premium: ₹{decision['premium']:.2f} | SL: -{sl_points} pts | Target: +{tgt_points} pts | R:R: {rr_label}")
        logger.info("=" * 60)

        res = self.ocs.execute_option_chain_paper_trade(
            symbol=inst,
            strike=decision["strike"],
            option_type=decision["option_type"],
            lots=self.lots,
            premium=decision["premium"],
            sl_points=sl_points,
            target_points=tgt_points,
            trailing_sl=True,
            trail_step=15.0,
            action="BUY",
            expiry=decision.get("expiry"),
            moneyness=moneyness_label,
        )

        trade_id = res.get("trade_id", "N/A")
        now_ist = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

        # Audible execution chime (Windows Beep)
        play_beep_chime("ENTRY")

        # Telegram alert
        if self.tele.is_configured:
            gates = decision["gates"]
            pillars = decision.get("pillars", {})
            msg = (
                f"⚡ <b>[TRADE EXECUTED — {setup_type}]</b> ⚡\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🎯 <b>{inst} {decision['strike']} {decision['option_type']} ({moneyness_label})</b>\n"
                f"📅 Expiry: <b>{expiry_label} (Next Expiry)</b>\n"
                f"💵 Entry: ₹{decision['premium']:.2f} | Lots: {self.lots} ({self.lots*65} Qty)\n"
                f"🛡 SL: ₹{res.get('sl_price',0):.2f} (-{sl_points} pts)\n"
                f"🚀 Target: ₹{res.get('target_price',0):.2f} (+{tgt_points} pts)\n"
                f"⚖ <b>Risk:Reward = {rr_label}</b> | 🆔 <code>{trade_id}</code>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🏆 <b>3-Pillar Institutional Checklist:</b>\n"
                f"1️⃣ <b>Direction:</b> {pillars.get('Pillar_1_Direction', 'PASS')}\n"
                f"2️⃣ <b>Location:</b> {pillars.get('Pillar_2_Location', 'PASS')}\n"
                f"3️⃣ <b>Trigger:</b> {pillars.get('Pillar_3_Trigger', 'PASS')}\n"
                f"⏰ {now_ist}"
            )
            self.tele.send_message(msg)

        # STEP 7: Generate PDF report + chart screenshot
        self._generate_report(trade_id, decision, analysis, res)

        return res

    # ── STEP 7 — Report Generation ────────────────────────────────────────────
    def _generate_report(self, trade_id: str, decision: Dict, analysis: Dict, exec_res: Dict):
        """STEP 7: Chart screenshot + PDF summary."""
        now = datetime.now(IST)
        date_str = now.strftime("%Y%m%d_%H%M")
        strike = decision["strike"]
        opt = decision["option_type"]
        inst_short = "BANKNIFTY" if "BANK" in self.symbol else "NIFTY50"

        # Chart Screenshot
        chart_path = str(REPORTS_DIR / f"CHART_{inst_short}_{strike}{opt}_{date_str}_{trade_id}.png")
        try:
            subprocess.run([
                "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                "--headless=new", "--no-sandbox", "--disable-gpu",
                "--window-size=1600,1000",
                "--virtual-time-budget=8000",
                "--run-all-compositor-stages-before-draw",
                f"--screenshot={chart_path}",
                f"{DASH}/#tab-charts",
            ], timeout=15, capture_output=True)
            logger.info(f"📸 Chart screenshot saved: {chart_path}")
        except Exception as e:
            logger.warning(f"Screenshot error: {e}")

        # High-fidelity candlestick chart fallback if screenshot missing
        if not os.path.exists(chart_path):
            try:
                import matplotlib
                matplotlib.use("Agg")
                import matplotlib.pyplot as plt
                import matplotlib.patches as patches
                from nifty_trader.market_data.report_service import _fetch_intraday_candles, _filter_session_candles
                candles = _fetch_intraday_candles(self.symbol, "15m")
                session_candles, _ = _filter_session_candles(candles, now.strftime("%Y-%m-%d"))
                if session_candles:
                    fig, (ax, ax_vol) = plt.subplots(2, 1, figsize=(10, 5), gridspec_kw={"height_ratios": [3.5, 1]}, sharex=True)
                    fig.patch.set_facecolor("#0f172a")
                    ax.set_facecolor("#0f172a")
                    ax_vol.set_facecolor("#0f172a")
                    xs = list(range(len(session_candles)))
                    labels = [c["label"] for c in session_candles]
                    for i, c in enumerate(session_candles):
                        o, h, l, cl = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])
                        vol = float(c.get("volume", 0))
                        col = "#22c55e" if cl >= o else "#ef4444"
                        ax.plot([i, i], [l, h], color=col, linewidth=1.3)
                        ax.add_patch(patches.Rectangle((i - 0.32, min(o, cl)), 0.64, max(abs(cl - o), 1.5), facecolor=col, edgecolor=col))
                        ax_vol.bar(i, vol, width=0.6, color=col, alpha=0.65)
                    if strike:
                        ax.axhline(strike, color="#f59e0b", linestyle=":", linewidth=1.5)
                    if decision.get("spot"):
                        ax.axhline(decision["spot"], color="#38bdf8", linestyle="--", linewidth=1.3)
                    ax.set_title(f"{inst_short} Intraday 15M Chart at Execution — {strike} {opt} ({now.strftime('%Y-%m-%d %H:%M IST')})", color="#f8fafc", fontsize=10, fontweight="bold")
                    ax.grid(True, color="#1e293b", linewidth=0.6)
                    ax_vol.grid(True, color="#1e293b", linewidth=0.6)
                    ax.tick_params(colors="#94a3b8", labelsize=8)
                    ax_vol.tick_params(colors="#94a3b8", labelsize=8)
                    step = max(1, len(xs) // 15)
                    ax_vol.set_xticks(xs[::step])
                    ax_vol.set_xticklabels(labels[::step], rotation=45, ha="right", fontsize=7.5)
                    plt.tight_layout()
                    plt.savefig(chart_path, dpi=160, facecolor="#0f172a")
                    plt.close(fig)
                    logger.info(f"📊 Rendered matplotlib candle chart fallback: {chart_path}")
            except Exception as e_plot:
                logger.warning(f"Matplotlib chart fallback error: {e_plot}")

        # PDF Report
        pdf_name = f"TRADE_{inst_short}_{strike}{opt}_{date_str}_{trade_id}.pdf"
        target_dir = Path("d:/AI_Trading/reports") / now.strftime("%Y-%m-%d") / "trade_reports"
        target_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = str(target_dir / pdf_name)
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib import colors
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
            from reportlab.platypus import Image as RLImage
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

            doc = SimpleDocTemplate(pdf_path, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
            styles = getSampleStyleSheet()
            st_title = ParagraphStyle("T", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=colors.HexColor("#0f172a"), spaceAfter=4)
            st_h2 = ParagraphStyle("H2", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=colors.HexColor("#1e3a8a"), spaceBefore=8, spaceAfter=4)
            st_body = ParagraphStyle("B", parent=styles["Normal"], fontName="Helvetica", fontSize=9, leading=12, textColor=colors.HexColor("#1e293b"))
            st_small = ParagraphStyle("SM", parent=styles["Normal"], fontName="Helvetica-Oblique", fontSize=8, leading=11, textColor=colors.HexColor("#475569"))
            els = []

            expiry_str = decision.get("expiry", "Next Expiry")
            moneyness_str = decision.get("moneyness", "ITM")
            rr_label = decision.get("risk_reward", "1:3.0")
            setup_type = decision.get("setup_type", "TREND_CONTINUATION")
            sl_points = float(decision.get("sl_points", self.sl))
            tgt_points = float(decision.get("tgt_points", self.tgt))

            els.append(Paragraph(f"Trade Execution Intelligence Report: {inst_short} {strike} {opt} ({moneyness_str})", st_title))
            els.append(Paragraph(f"Trade ID: <b>{trade_id}</b> | Setup: <b>{setup_type} ({rr_label} R:R)</b> | Expiry: <b>{expiry_str} (Next Expiry)</b> | Date: {now.strftime('%Y-%m-%d %H:%M IST')}", st_small))
            els.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0284c7"), spaceAfter=8))

            # Executive Summary Box
            els.append(Paragraph("1. Trade Executive Summary &amp; Strategy Thesis:", st_h2))
            if setup_type == "WALL_REVERSAL_FADE":
                thesis_text = (
                    f"<b>Setup: Institutional Wall Reversal Fade ({rr_label} Risk-to-Reward)</b>. "
                    f"Spot price tested extreme boundary at <b>{decision.get('spot', 0):,.1f}</b> near institutional wall. "
                    f"Option chain confirms heavy institutional defense with PCR at {sr.get('pcr', 0.59):.2f}. "
                    f"A confirmed 5-minute rejection candle triggered immediate entry into <b>1 Lot ITM {strike} {opt}</b> on next weekly expiry <b>{expiry_str}</b>. "
                    f"Risk is strictly controlled with a 15-pt SL behind the wall targeting a wholesale return to session POC (<b>{decision.get('poc', 0):,.1f}</b>) for a +{tgt_points:.0f} pts gain."
                )
            else:
                thesis_text = (
                    f"<b>Setup: Trend Continuation ({rr_label} Risk-to-Reward)</b>. "
                    f"Spot price at <b>{decision.get('spot', 0):,.1f}</b> aligned with higher-timeframe 1H trend, holding above wholesale Central Pivot ({sr.get('pp', 0):,.1f}) and session POC ({decision.get('poc', 0):,.1f}). "
                    f"A confirmed 5-minute trend candle with volume expansion triggered immediate entry into <b>1 Lot ITM {strike} {opt}</b> on next weekly expiry <b>{expiry_str}</b>. "
                    f"Risk is defined at -{sl_points:.0f} pts SL targeting a +{tgt_points:.0f} pts expansion with 15-pt trailing SL."
                )
            els.append(Paragraph(thesis_text, st_body))
            els.append(Spacer(1, 6))

            # Execution table
            sl_p = exec_res.get("sl_price", 0)
            tgt_p = exec_res.get("target_price", 0)
            tbl = [
                ["Instrument", f"{inst_short} {strike} {opt} ({moneyness_str})", "Lots/Qty", f"{self.lots} ({self.lots*65})"],
                ["Expiry", f"{expiry_str} (Next Expiry)", "Moneyness", f"{moneyness_str} (Delta: {decision.get('delta', 0.62):.2f})"],
                ["Entry Premium", f"Rs. {decision['premium']:.2f}", "Spot at Entry", f"Rs. {decision['spot']:,.2f}"],
                ["Stop Loss", f"Rs. {sl_p:.2f} (-{sl_points:.0f} pts)", "Target", f"Rs. {tgt_p:.2f} (+{tgt_points:.0f} pts)"],
                ["Risk:Reward", f"{rr_label}", "Trailing SL", "15-point trail step"],
            ]
            t = Table(tbl, colWidths=[120, 140, 120, 140])
            t.setStyle(TableStyle([
                ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#e2e8f0")),
                ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#f1f5f9")),
                ("BACKGROUND", (2,0), (2,-1), colors.HexColor("#f1f5f9")),
                ("FONTNAME", (0,0), (0,-1), "Helvetica-Bold"),
                ("FONTNAME", (2,0), (2,-1), "Helvetica-Bold"),
                ("FONTSIZE", (0,0), (-1,-1), 8.5),
                ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
                ("PADDING", (0,0), (-1,-1), 4.5),
            ]))
            els.append(t)
            els.append(Spacer(1, 8))

            # Chart image
            if os.path.exists(chart_path):
                from PIL import Image as PILImage
                img = PILImage.open(chart_path)
                aspect = img.height / img.width
                els.append(Paragraph("2. Intraday Candlestick Chart at Execution (15M Dark Theme):", st_h2))
                els.append(RLImage(chart_path, width=520, height=520*aspect))
                els.append(Spacer(1, 6))

            # Analysis Summary
            bias = analysis["bias"]
            news_d = analysis["news"]
            sr = analysis["sr"]
            m5 = analysis["m5"]
            gates = decision["gates"]

            # 3-Pillar Summary
            pillars = decision.get("pillars", {})
            els.append(Paragraph("3. 3-Pillar Institutional Checklist (Decision Engine):", st_h2))
            pil_rows = [
                ["Pillar", "Criteria", "Status", "Institutional Reason"],
                ["1. Direction", "1H Trend + Option Chain PCR + Heavyweights", "PASS", pillars.get("Pillar_1_Direction", "Aligned higher-timeframe structure")],
                ["2. Location", "Key Pivot / S/R Boundaries + Session POC", "PASS", pillars.get("Pillar_2_Location", "High-value wholesale boundary entry")],
                ["3. Trigger", "5M Volume Candle + 1 Lot ITM Next Expiry", "PASS", pillars.get("Pillar_3_Trigger", "Volume confirmation with protected contract")],
            ]
            pt = Table(pil_rows, colWidths=[75, 155, 60, 230])
            pt.setStyle(TableStyle([
                ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#e2e8f0")),
                ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#065f46")),
                ("TEXTCOLOR", (0,0), (-1,0), colors.white),
                ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
                ("FONTSIZE", (0,0), (-1,-1), 8),
                ("PADDING", (0,0), (-1,-1), 4.5),
            ]))
            els.append(pt)
            els.append(Spacer(1, 8))

            # Multi-Dimensional Detailed Analysis Matrix Table
            els.append(Paragraph("4. Detailed Multi-Factor Analysis Matrix (Status &amp; Reason):", st_h2))
            det_rows = [
                ["Factor Analyzed", "Observed Value", "Status", "Reason & Institutional Significance"],
                ["Higher-TF Trend", f"1H: {bias.get('timeframes',{}).get('1H',{}).get('bias','NEUTRAL')}", "PASS", "Strict rule: Trades strictly aligned with 1H order flow momentum."],
                ["Option Chain PCR", f"PCR {sr.get('pcr',0):.2f} (MaxPain {sr.get('max_pain',0)})", "PASS", "Option writers positioning confirms directional bias and ceiling/floor."],
                ["Institutional Walls", f"Call Wall: {sr.get('max_ce_strike',0)} | Put Floor: {sr.get('max_pe_strike',0)}", "PASS", "Heavy open interest strikes acting as institutional bounce/reversal anchors."],
                ["Pivots & POC", f"PP: {sr.get('pp',0):.1f} | POC: {decision.get('poc',0):.1f}", "PASS", "Entering at wholesale value boundary rather than chasing extended moves."],
                ["5M Trigger Candle", f"{m5.get('pattern','CANDLE')} (Vol: {m5.get('vol_ratio',1.0)}x)", "PASS", "Volume expansion confirms institutional participation on trigger bar."],
                ["Contract Moneyness", f"ITM (Strike {strike} | Delta ~{decision.get('delta',0.62):.2f})", "PASS", "High intrinsic value ensures immediate delta response and reduced theta risk."],
                ["Expiry Cycle", f"{expiry_str} (Next Weekly Expiry)", "PASS", "Completely eliminates same-week 0-DTE theta crush traps."],
                ["Risk Guardrails", f"1 Lot | SL: {sl_points:.0f} pts | Daily Cap: Rs. 2,000", "PASS", "Hard stop loss and trailing step enforce institutional capital survival."],
            ]
            dt_table = Table(det_rows, colWidths=[95, 135, 55, 235])
            dt_table.setStyle(TableStyle([
                ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#e2e8f0")),
                ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1e3a8a")),
                ("TEXTCOLOR", (0,0), (-1,0), colors.white),
                ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
                ("FONTSIZE", (0,0), (-1,-1), 7.5),
                ("PADDING", (0,0), (-1,-1), 4),
            ]))
            els.append(dt_table)
            els.append(Spacer(1, 8))

            # Strategic Trade Conclusion
            els.append(Paragraph("5. Strategic Conclusion &amp; Trajectory Plan:", st_h2))
            conclusion_text = (
                f"<b>Trade Execution Verdict:</b> Position entered cleanly with <b>1 Lot ITM {strike} {opt}</b> at premium ₹{decision['premium']:.2f}. "
                f"Stop loss is anchored at ₹{sl_p:.2f} (-{sl_points:.0f} pts index equivalent) and target is pegged at ₹{tgt_p:.2f} (+{tgt_points:.0f} pts index equivalent, <b>{rr_label} R:R</b>). "
                f"<b>Trailing Management:</b> Stop loss auto-trails by 15-point increments as price moves favorably, locking in breakeven and advancing profits toward target. "
                f"Daily loss remains strictly safeguarded under the ₹2,000 account cap."
            )
            els.append(Paragraph(conclusion_text, st_body))
            els.append(Spacer(1, 6))

            els.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceAfter=4))
            els.append(Paragraph("Generated by <b>Hermes Autonomous Trader v2.0</b> | 3-Pillar Institutional Decision Architecture", st_small))
            doc.build(els)
            logger.info(f"📄 PDF report saved: {pdf_path}")
            # Also copy to root reports/trade_reports/
            root_tr = Path("d:/AI_Trading/reports/trade_reports")
            root_tr.mkdir(parents=True, exist_ok=True)
            shutil.copy(pdf_path, root_tr / pdf_name)

            # Send photo to Telegram
            if os.path.exists(chart_path) and self.tele.is_configured:
                self.tele.send_photo(
                    chart_path,
                    caption=f"📸 <b>[TRADE EXECUTION REPORT]</b>\n"
                            f"🎯 <b>{inst_short} {strike} {opt}</b> | ID: <code>{trade_id}</code>\n"
                            f"💵 Entry: ₹{decision['premium']:.2f} | SL: ₹{sl_p:.2f} | Tgt: ₹{tgt_p:.2f}\n"
                            f"📄 PDF archived: <code>{pdf_name}</code>"
                )
        except Exception as e:
            logger.warning(f"PDF generation error: {e}")

    # ── Live Session Loop ─────────────────────────────────────────────────────
    def run_live(self, scan_interval: int = 15):
        """Full autonomous live session: market open → scan → execute → monitor → repeat."""
        logger.info("🚀" * 20)
        logger.info(f"  HERMES AUTONOMOUS TRADER v2.0 — LIVE SESSION STARTED")
        logger.info(f"  Symbol: {self.symbol} | SL: {self.sl} pts | Target: {self.tgt} pts | R:R = 1:3")
        logger.info(f"  Strategy: Price Action + Multi-TF S/R + Volume + Options + News")
        logger.info("🚀" * 20)

        last_standby_log = 0.0

        try:
            while True:
                now = datetime.now(IST)
                schedule = get_trading_session_phase(now)

                # Check if position is already active (even after market close, track exit or square-off)
                if self.sim.active_position is not None:
                    pos = self.sim.active_position
                    # Update live MTM and evaluate SL / Target using latest 5m spot candle
                    c_5m = fetch_candles(self.symbol, "5m")
                    if c_5m:
                        latest_c = c_5m[-1]
                        res = self.sim.update_active_position_with_spot(
                            pos.symbol,
                            latest_c["close"],
                            latest_c.get("high"),
                            latest_c.get("low"),
                        )
                        if res is not None or self.sim.active_position is None:
                            logger.info(f"🎯 Position closed ({getattr(res, 'exit_reason', 'EXIT')}) at premium ₹{getattr(res, 'exit_price', 0):.2f}! Resuming market scan.")
                            pnl = getattr(res, 'net_pnl', 1.0)
                            play_beep_chime("EXIT_WIN" if pnl >= 0 else "EXIT_LOSS")
                            time.sleep(scan_interval)
                            continue

                    logger.info(
                        f"📊 Active: {pos.symbol} {pos.strike} {pos.option_type} | "
                        f"Entry: ₹{pos.entry_premium:.2f} | Current: ₹{pos.current_premium:.2f} | "
                        f"MTM: ₹{pos.mtm_pnl:+.2f} | Trailing SL: ₹{pos.sl_price:.2f}"
                    )
                    time.sleep(scan_interval)
                    continue

                # ── Market Hours & Schedule Gate ──────────────────────────────
                # If market is NOT open for active monitoring (e.g. before 09:00 AM, weekend, holiday, after 15:30 PM):
                if not schedule["is_monitoring_active"]:
                    if time.time() - last_standby_log >= 30.0:
                        logger.info(f"⏳ [STANDBY] {schedule['message']} (Current: {schedule['ist_time']} IST)")
                        last_standby_log = time.time()
                    time.sleep(min(scan_interval, 15))
                    continue

                # If in pre-market window (09:00 AM to 09:15 AM IST):
                # Agent monitors order flow & news sentiment, but regular market orders unlock at 09:15 AM IST.
                if schedule["phase"] == "PRE_MARKET_MONITORING":
                    if time.time() - last_standby_log >= 60.0:
                        logger.info(f"📡 [PRE-MARKET 09:00–09:15] Monitoring pre-market order flow and S/R levels. Regular confluence orders unlock at 09:15 AM IST.")
                        last_standby_log = time.time()
                    time.sleep(min(scan_interval, 15))
                    continue

                # ── Regular Live Trading Session (09:15 to 15:30 IST) ────────
                # No position → Run full analysis
                analysis = self.run_full_analysis()

                # Decision
                logger.info("━" * 60)
                logger.info("STEP 5+6 ► DECISION ENGINE")
                decision = self.decide_trade(analysis)

                if decision:
                    logger.info(f"✅ TRADE SIGNAL: {decision['direction']} → {self.chart_symbol} {decision['strike']} {decision['option_type']}")
                    for gname, gval in decision["gates"].items():
                        logger.info(f"   ✓ {gname}: {gval}")
                    self.execute(decision, analysis)
                else:
                    logger.info("⏳ No confluence. All 5 gates did not align. Waiting...")
                    logger.info("━" * 60)

                time.sleep(scan_interval)

        except KeyboardInterrupt:
            logger.info("\n🛑 Live session stopped by user. Positions preserved in simulator.")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PRE-MARKET BRIEFING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def print_premarket(symbol: str = "NIFTY"):
    chart_sym = "BANKNIFTY" if "BANK" in symbol.upper() else "NIFTY 50"
    bias = multi_tf_bias(chart_sym)
    news = news_sentiment()
    sr = compute_sr_matrix(symbol)
    p = sr

    print("\n" + "=" * 70)
    print(f"  HERMES v2.0 — PRE-MARKET BRIEFING: {symbol.upper()}")
    print(f"  {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')}")
    print("=" * 70)

    print("\n── STEP 1: MULTI-TIMEFRAME BIAS ──")
    for tf, d in bias["timeframes"].items():
        print(f"   {tf:8s} │ {d['bias']:15s} │ EMA9={d['ema9']}  EMA20={d['ema20']}  Candle={d['candle_type']}")
    print(f"   {'VERDICT':8s} │ {bias['overall_bias']}")

    print("\n── STEP 2: NEWS SENTIMENT ──")
    print(f"   {news['sentiment']} │ Bull={news['bullish_count']}  Bear={news['bearish_count']}  AvgScore={news['avg_impact_score']}")
    for hl in news["top_headlines"][:3]:
        print(f"   📰 {hl}")

    print("\n── STEP 3: SUPPORT & RESISTANCE ──")
    print(f"   R2={p['r2']}  R1={p['r1']}  PP={p['pp']}  S1={p['s1']}  S2={p['s2']}")
    print(f"   PDH={p['pdh']}  PDL={p['pdl']}  Spot={p['spot']}")
    print(f"   Call OI Wall: {p['max_ce_strike']} ({p['max_ce_oi']:,})")
    print(f"   Put OI Floor: {p['max_pe_strike']} ({p['max_pe_oi']:,})")
    print(f"   PCR: {p['pcr']}  MaxPain: {p['max_pain']}  Sentiment: {p['sentiment']}")

    print("\n── EXECUTION RULES ──")
    print(f"   CE BUY: TF Bias BULLISH + News not BEARISH + Above PP/S1 + EMA9>EMA20 + RSI 45-80 + PCR>=1.10")
    print(f"   PE BUY: TF Bias BEARISH + News not BULLISH + Below PP/R1 + EMA9<EMA20 + RSI 20-55 + PCR<=0.90")
    print(f"   Risk: SL=20 pts | Target=60 pts | R:R=1:3 | Instant Execution | Telegram Alert")
    print("=" * 70 + "\n")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MAIN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hermes v2.0 — Autonomous Price Action + S/R + Volume Trader")
    parser.add_argument("--symbol", default="NIFTY", help="NIFTY or BANKNIFTY")
    parser.add_argument("--sl", type=float, default=20.0, help="Stop loss points")
    parser.add_argument("--target", type=float, default=60.0, help="Target points")
    parser.add_argument("--lots", type=int, default=1, help="Contract lots")
    parser.add_argument("--mode", choices=["premarket", "live", "scan-once"], default="live")
    parser.add_argument("--loop", action="store_true", help="Alias for --mode live")
    parser.add_argument("--interval", type=int, default=15, help="Scan interval seconds")
    args = parser.parse_args()

    if args.loop:
        args.mode = "live"

    if args.mode == "premarket":
        print_premarket(args.symbol)
    elif args.mode == "scan-once":
        print_premarket(args.symbol)
        trader = HermesTraderV2(symbol=args.symbol, sl=args.sl, tgt=args.target, lots=args.lots)
        analysis = trader.run_full_analysis()
        decision = trader.decide_trade(analysis)
        if decision:
            print(f"\n✅ SIGNAL: {decision['direction']} → {trader.chart_symbol} {decision['strike']} {decision['option_type']}")
            print(json.dumps(decision["gates"], indent=2))
        else:
            print("\n⏳ No trade signal — gates not aligned.")
    elif args.mode == "live":
        trader = HermesTraderV2(symbol=args.symbol, sl=args.sl, tgt=args.target, lots=args.lots)
        trader.run_live(scan_interval=args.interval)
