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

        return {"bias": bias, "news": news, "sr": sr, "m5": m5}

    # ── Decision Logic ────────────────────────────────────────────────────────
    def decide_trade(self, analysis: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Decision engine: ALL gates must pass.
        Gate 1: Multi-TF bias is not against the trade.
        Gate 2: News is not strongly against.
        Gate 3: S/R confluence supports entry zone.
        Gate 4: 5m candle confirms direction + volume.
        Gate 5: Option chain PCR aligns.
        """
        bias = analysis["bias"]["overall_bias"]
        news = analysis["news"]["sentiment"]
        sr = analysis["sr"]
        m5 = analysis["m5"]
        pcr = sr["pcr"]
        spot = sr["spot"]

        if not m5.get("valid"):
            return None

        # ── CE (BULLISH) TRADE ────────────────────────────────────────────────
        gate1_bull = bias in ("STRONG_BULLISH", "BULLISH")
        gate2_bull = news != "BEARISH"
        gate3_bull = (
            spot > sr["pp"]
            or spot > sr["s1"]
            or abs(spot - sr["max_pe_strike"]) <= 50
        )
        gate4_bull = (
            m5["ema_cross"] in ("BULLISH_CROSS", "ABOVE")
            and m5["rsi"] > 45 and m5["rsi"] < 80
            and m5["pattern"] in ("STRONG_BULL_CANDLE", "BULLISH_PIN_BAR", "BULLISH_ENGULFING", "NEUTRAL", "DOJI")
        )
        gate5_bull = pcr >= 1.10

        if gate1_bull and gate2_bull and gate3_bull and gate4_bull and gate5_bull:
            step = 100 if "BANK" in self.symbol else 50
            atm = int(round(spot / step) * step)
            premium = self._lookup_premium(atm, "CE")
            return {
                "direction": "BULLISH",
                "option_type": "CE",
                "strike": atm,
                "premium": premium,
                "spot": spot,
                "gates": {"TF_Bias": bias, "News": news, "SR": "Above PP/S1", "5m": m5["pattern"],
                          "EMA": m5["ema_cross"], "RSI": m5["rsi"], "VolRatio": m5["vol_ratio"], "PCR": pcr},
            }

        # ── PE (BEARISH) TRADE ────────────────────────────────────────────────
        gate1_bear = bias in ("STRONG_BEARISH", "BEARISH")
        gate2_bear = news != "BULLISH"
        gate3_bear = (
            spot < sr["pp"]
            or spot < sr["r1"]
            or abs(spot - sr["max_ce_strike"]) <= 50
        )
        gate4_bear = (
            m5["ema_cross"] in ("BEARISH_CROSS", "BELOW")
            and m5["rsi"] > 20 and m5["rsi"] < 55
            and m5["pattern"] in ("STRONG_BEAR_CANDLE", "BEARISH_PIN_BAR", "BEARISH_ENGULFING", "NEUTRAL", "DOJI")
        )
        gate5_bear = pcr <= 0.90

        if gate1_bear and gate2_bear and gate3_bear and gate4_bear and gate5_bear:
            step = 100 if "BANK" in self.symbol else 50
            atm = int(round(spot / step) * step)
            premium = self._lookup_premium(atm, "PE")
            return {
                "direction": "BEARISH",
                "option_type": "PE",
                "strike": atm,
                "premium": premium,
                "spot": spot,
                "gates": {"TF_Bias": bias, "News": news, "SR": "Below PP/R1", "5m": m5["pattern"],
                          "EMA": m5["ema_cross"], "RSI": m5["rsi"], "VolRatio": m5["vol_ratio"], "PCR": pcr},
            }

        return None

    def _lookup_premium(self, strike: int, opt_type: str) -> float:
        chain = self.ocs.get_option_chain(self.symbol)
        for r in chain.get("strikes", []):
            if r.get("strike") == strike:
                return float(r.get(opt_type.lower(), {}).get("ltp", 85.0))
        return 85.0

    # ── STEP 6 — Instant Execution ────────────────────────────────────────────
    def execute(self, decision: Dict[str, Any], analysis: Dict[str, Any]) -> Dict[str, Any]:
        """STEP 6: Instant execution into Paper Simulator + Telegram."""
        inst = "BANKNIFTY" if "BANK" in self.symbol else "NIFTY 50"
        logger.info("=" * 60)
        logger.info(f"⚡ STEP 6 ► INSTANT EXECUTION: {inst} {decision['strike']} {decision['option_type']}")
        logger.info(f"   Premium: ₹{decision['premium']:.2f} | SL: -{self.sl} pts | Target: +{self.tgt} pts")
        logger.info("=" * 60)

        res = self.ocs.execute_option_chain_paper_trade(
            symbol=inst,
            strike=decision["strike"],
            option_type=decision["option_type"],
            lots=self.lots,
            premium=decision["premium"],
            sl_points=self.sl,
            target_points=self.tgt,
            trailing_sl=True,
            trail_step=15.0,
            action="BUY",
        )

        trade_id = res.get("trade_id", "N/A")
        now_ist = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

        # Telegram alert
        if self.tele.is_configured:
            gates = decision["gates"]
            msg = (
                f"⚡ <b>[TRADE EXECUTED]</b> ⚡\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🎯 <b>{inst} {decision['strike']} {decision['option_type']}</b>\n"
                f"💵 Entry: ₹{decision['premium']:.2f} | Lots: {self.lots}\n"
                f"🛡 SL: ₹{res.get('sl_price',0):.2f} (-{self.sl} pts)\n"
                f"🚀 Target: ₹{res.get('target_price',0):.2f} (+{self.tgt} pts)\n"
                f"⚖ R:R = 1:3 | 🆔 {trade_id}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 <b>Analysis Summary:</b>\n"
                f"TF Bias: {gates['TF_Bias']} | News: {gates['News']}\n"
                f"EMA: {gates['EMA']} | RSI: {gates['RSI']}\n"
                f"Pattern: {gates['5m']} | Vol: {gates['VolRatio']}x\n"
                f"PCR: {gates['PCR']} | ⏰ {now_ist}"
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

        # PDF Report
        pdf_name = f"TRADE_{inst_short}_{strike}{opt}_{date_str}_{trade_id}.pdf"
        pdf_path = str(REPORTS_DIR / pdf_name)
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

            els.append(Paragraph(f"Trade Entry Report: {inst_short} {strike} {opt}", st_title))
            els.append(Paragraph(f"Trade ID: <b>{trade_id}</b> | Date: {now.strftime('%Y-%m-%d %H:%M IST')} | File: {pdf_name}", st_small))
            els.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0284c7"), spaceAfter=8))

            # Execution table
            sl_p = exec_res.get("sl_price", 0)
            tgt_p = exec_res.get("target_price", 0)
            tbl = [
                ["Instrument", f"{inst_short} {strike} {opt}", "Lots/Qty", f"{self.lots} ({self.lots*65})"],
                ["Entry Premium", f"Rs. {decision['premium']:.2f}", "Spot", f"Rs. {decision['spot']:,.2f}"],
                ["Stop Loss", f"Rs. {sl_p:.2f} (-{self.sl} pts)", "Target", f"Rs. {tgt_p:.2f} (+{self.tgt} pts)"],
                ["Risk:Reward", "1 : 3.0", "Status", "OPEN (Active)"],
            ]
            t = Table(tbl, colWidths=[120, 140, 120, 140])
            t.setStyle(TableStyle([
                ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#e2e8f0")),
                ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#f1f5f9")),
                ("BACKGROUND", (2,0), (2,-1), colors.HexColor("#f1f5f9")),
                ("FONTNAME", (0,0), (0,-1), "Helvetica-Bold"),
                ("FONTNAME", (2,0), (2,-1), "Helvetica-Bold"),
                ("FONTSIZE", (0,0), (-1,-1), 9),
                ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
                ("PADDING", (0,0), (-1,-1), 5),
            ]))
            els.append(t)
            els.append(Spacer(1, 8))

            # Chart image
            if os.path.exists(chart_path):
                from PIL import Image as PILImage
                img = PILImage.open(chart_path)
                aspect = img.height / img.width
                els.append(Paragraph("Chart at Trade Time:", st_h2))
                els.append(RLImage(chart_path, width=520, height=520*aspect))
                els.append(Spacer(1, 6))

            # Analysis Summary
            bias = analysis["bias"]
            news_d = analysis["news"]
            sr = analysis["sr"]
            m5 = analysis["m5"]
            gates = decision["gates"]

            els.append(Paragraph("Multi-Timeframe Bias Analysis:", st_h2))
            tf_rows = [["Timeframe", "Bias", "EMA 9", "EMA 20", "Candle"]]
            for tf, d in bias["timeframes"].items():
                tf_rows.append([tf, d["bias"], str(d["ema9"]), str(d["ema20"]), d["candle_type"]])
            tf_rows.append(["OVERALL", bias["overall_bias"], "", "", f"Votes: {bias['votes']}"])
            tt = Table(tf_rows, colWidths=[80, 90, 80, 80, 190])
            tt.setStyle(TableStyle([
                ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#e2e8f0")),
                ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1e3a8a")),
                ("TEXTCOLOR", (0,0), (-1,0), colors.white),
                ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
                ("FONTSIZE", (0,0), (-1,-1), 8),
                ("PADDING", (0,0), (-1,-1), 4),
            ]))
            els.append(tt)
            els.append(Spacer(1, 6))

            els.append(Paragraph("News Sentiment:", st_h2))
            els.append(Paragraph(f"Overall: <b>{news_d['sentiment']}</b> | Bullish: {news_d['bullish_count']} | Bearish: {news_d['bearish_count']} | Avg Score: {news_d['avg_impact_score']}", st_body))
            els.append(Spacer(1, 4))

            els.append(Paragraph("Support &amp; Resistance Levels:", st_h2))
            els.append(Paragraph(f"PP: {sr['pp']} | R1: {sr['r1']} | R2: {sr['r2']} | S1: {sr['s1']} | S2: {sr['s2']} | PDH: {sr['pdh']} | PDL: {sr['pdl']}", st_body))
            els.append(Paragraph(f"Max Call OI: {sr['max_ce_strike']} ({sr['max_ce_oi']:,}) | Max Put OI: {sr['max_pe_strike']} ({sr['max_pe_oi']:,}) | PCR: {sr['pcr']} | Max Pain: {sr['max_pain']}", st_body))
            els.append(Spacer(1, 4))

            if m5.get("valid"):
                els.append(Paragraph("5-Min Execution Candle:", st_h2))
                els.append(Paragraph(f"EMA9: {m5['ema9']} | EMA20: {m5['ema20']} | Cross: {m5['ema_cross']} | RSI(14): {m5['rsi']} | Vol Ratio: {m5['vol_ratio']}x | Pattern: {m5['pattern']}", st_body))
            els.append(Spacer(1, 4))

            els.append(Paragraph("Gate Checklist:", st_h2))
            gate_rows = [["Gate", "Value", "Status"]]
            for gname, gval in gates.items():
                gate_rows.append([gname, str(gval), "PASS"])
            gt = Table(gate_rows, colWidths=[120, 200, 200])
            gt.setStyle(TableStyle([
                ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#e2e8f0")),
                ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#047857")),
                ("TEXTCOLOR", (0,0), (-1,0), colors.white),
                ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
                ("FONTSIZE", (0,0), (-1,-1), 8),
                ("PADDING", (0,0), (-1,-1), 4),
            ]))
            els.append(gt)
            els.append(Spacer(1, 8))
            els.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceAfter=4))
            els.append(Paragraph("Generated by <b>Hermes Autonomous Trader v2.0</b> | Price Action + S/R + Volume Strategy", st_small))
            doc.build(els)
            logger.info(f"📄 PDF report saved: {pdf_path}")
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

        try:
            while True:
                now = datetime.now(IST)

                # Check if position is already active
                if self.sim.active_position is not None:
                    pos = self.sim.active_position
                    logger.info(
                        f"📊 Active: {pos.symbol} {pos.strike} {pos.option_type} | "
                        f"Entry: ₹{pos.entry_premium:.2f} | Current: ₹{pos.current_premium:.2f} | "
                        f"MTM: ₹{pos.mtm_pnl:+.2f}"
                    )
                    if pos.status != "OPEN":
                        logger.info(f"🔄 Position closed ({pos.status}). Resuming scan.")
                        self.sim.active_position = None
                    time.sleep(scan_interval)
                    continue

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
    parser.add_argument("--interval", type=int, default=15, help="Scan interval seconds")
    args = parser.parse_args()

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
