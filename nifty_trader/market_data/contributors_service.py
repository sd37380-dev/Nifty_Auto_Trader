"""
NSE NIFTY 50 & BANK NIFTY Main Contributors Live Service.

Tracks and calculates real-time price status, percentage change, and index points contribution
for the top heavyweights and drivers of NIFTY 50 (~65% weight) and BANK NIFTY (~95% weight).
"""

from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import threading
import time
from typing import Any, Dict, List, Optional
import httpx

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

CONTRIBUTORS_CONFIG: List[Dict[str, Any]] = [
    # --- BANK NIFTY Main Drivers (~95% Cumulative BN Weight) ---
    {
        "symbol": "HDFCBANK",
        "name": "HDFC Bank Ltd",
        "tv_ticker": "NSE:HDFCBANK",
        "yahoo_ticker": "HDFCBANK.NS",
        "bn_weight": 28.5,
        "n50_weight": 11.5,
        "group": "bn",
        "icon": "🏛️",
        "sector": "Private Bank",
    },
    {
        "symbol": "ICICIBANK",
        "name": "ICICI Bank Ltd",
        "tv_ticker": "NSE:ICICIBANK",
        "yahoo_ticker": "ICICIBANK.NS",
        "bn_weight": 24.0,
        "n50_weight": 7.9,
        "group": "bn",
        "icon": "💳",
        "sector": "Private Bank",
    },
    {
        "symbol": "SBIN",
        "name": "State Bank of India",
        "tv_ticker": "NSE:SBIN",
        "yahoo_ticker": "SBIN.NS",
        "bn_weight": 10.5,
        "n50_weight": 3.0,
        "group": "bn",
        "icon": "🏦",
        "sector": "PSU Bank",
    },
    {
        "symbol": "AXISBANK",
        "name": "Axis Bank Ltd",
        "tv_ticker": "NSE:AXISBANK",
        "yahoo_ticker": "AXISBANK.NS",
        "bn_weight": 9.5,
        "n50_weight": 3.2,
        "group": "bn",
        "icon": "💳",
        "sector": "Private Bank",
    },
    {
        "symbol": "KOTAKBANK",
        "name": "Kotak Mahindra Bank",
        "tv_ticker": "NSE:KOTAKBANK",
        "yahoo_ticker": "KOTAKBANK.NS",
        "bn_weight": 8.5,
        "n50_weight": 2.8,
        "group": "bn",
        "icon": "🏦",
        "sector": "Private Bank",
    },
    {
        "symbol": "INDUSINDBK",
        "name": "IndusInd Bank Ltd",
        "tv_ticker": "NSE:INDUSINDBK",
        "yahoo_ticker": "INDUSINDBK.NS",
        "bn_weight": 5.5,
        "n50_weight": 0.0,
        "group": "bn",
        "icon": "🏛️",
        "sector": "Private Bank",
    },
    {
        "symbol": "BANKBARODA",
        "name": "Bank of Baroda",
        "tv_ticker": "NSE:BANKBARODA",
        "yahoo_ticker": "BANKBARODA.NS",
        "bn_weight": 2.7,
        "n50_weight": 0.0,
        "group": "bn",
        "icon": "🏦",
        "sector": "PSU Bank",
    },
    {
        "symbol": "PNB",
        "name": "Punjab National Bank",
        "tv_ticker": "NSE:PNB",
        "yahoo_ticker": "PNB.NS",
        "bn_weight": 2.1,
        "n50_weight": 0.0,
        "group": "bn",
        "icon": "🏦",
        "sector": "PSU Bank",
    },
    {
        "symbol": "FEDERALBNK",
        "name": "Federal Bank Ltd",
        "tv_ticker": "NSE:FEDERALBNK",
        "yahoo_ticker": "FEDERALBNK.NS",
        "bn_weight": 1.9,
        "n50_weight": 0.0,
        "group": "bn",
        "icon": "🏦",
        "sector": "Private Bank",
    },
    {
        "symbol": "AUBANK",
        "name": "AU Small Finance Bank",
        "tv_ticker": "NSE:AUBANK",
        "yahoo_ticker": "AUBANK.NS",
        "bn_weight": 1.7,
        "n50_weight": 0.0,
        "group": "bn",
        "icon": "🏦",
        "sector": "Private Bank",
    },
    {
        "symbol": "IDFCFIRSTB",
        "name": "IDFC First Bank Ltd",
        "tv_ticker": "NSE:IDFCFIRSTB",
        "yahoo_ticker": "IDFCFIRSTB.NS",
        "bn_weight": 1.2,
        "n50_weight": 0.0,
        "group": "bn",
        "icon": "🏦",
        "sector": "Private Bank",
    },

    # --- NIFTY 50 Heavyweights & Non-Bank Market Drivers ---
    {
        "symbol": "RELIANCE",
        "name": "Reliance Industries Ltd",
        "tv_ticker": "NSE:RELIANCE",
        "yahoo_ticker": "RELIANCE.NS",
        "bn_weight": 0.0,
        "n50_weight": 9.5,
        "group": "n50",
        "icon": "🏢",
        "sector": "Conglomerate / Energy",
    },
    {
        "symbol": "TCS",
        "name": "Tata Consultancy Services",
        "tv_ticker": "NSE:TCS",
        "yahoo_ticker": "TCS.NS",
        "bn_weight": 0.0,
        "n50_weight": 4.0,
        "group": "n50",
        "icon": "💻",
        "sector": "IT Services",
    },
    {
        "symbol": "INFY",
        "name": "Infosys Ltd",
        "tv_ticker": "NSE:INFY",
        "yahoo_ticker": "INFY.NS",
        "bn_weight": 0.0,
        "n50_weight": 5.6,
        "group": "n50",
        "icon": "💻",
        "sector": "IT Services",
    },
    {
        "symbol": "ITC",
        "name": "ITC Ltd",
        "tv_ticker": "NSE:ITC",
        "yahoo_ticker": "ITC.NS",
        "bn_weight": 0.0,
        "n50_weight": 4.3,
        "group": "n50",
        "icon": "🚬",
        "sector": "FMCG",
    },
    {
        "symbol": "LT",
        "name": "Larsen & Toubro Ltd",
        "tv_ticker": "NSE:LT",
        "yahoo_ticker": "LT.NS",
        "bn_weight": 0.0,
        "n50_weight": 3.9,
        "group": "n50",
        "icon": "🏗️",
        "sector": "Capital Goods",
    },
    {
        "symbol": "BHARTIARTL",
        "name": "Bharti Airtel Ltd",
        "tv_ticker": "NSE:BHARTIARTL",
        "yahoo_ticker": "BHARTIARTL.NS",
        "bn_weight": 0.0,
        "n50_weight": 3.7,
        "group": "n50",
        "icon": "📡",
        "sector": "Telecom",
    },
    {
        "symbol": "BAJFINANCE",
        "name": "Bajaj Finance Ltd",
        "tv_ticker": "NSE:BAJFINANCE",
        "yahoo_ticker": "BAJFINANCE.NS",
        "bn_weight": 0.0,
        "n50_weight": 2.1,
        "group": "n50",
        "icon": "💰",
        "sector": "NBFC",
    },
    {
        "symbol": "M&M",
        "name": "Mahindra & Mahindra Ltd",
        "tv_ticker": "NSE:M&M",
        "yahoo_ticker": "M%26M.NS",
        "bn_weight": 0.0,
        "n50_weight": 2.2,
        "group": "n50",
        "icon": "🚗",
        "sector": "Automobile",
    },
    {
        "symbol": "HINDUNILVR",
        "name": "Hindustan Unilever Ltd",
        "tv_ticker": "NSE:HINDUNILVR",
        "yahoo_ticker": "HINDUNILVR.NS",
        "bn_weight": 0.0,
        "n50_weight": 2.0,
        "group": "n50",
        "icon": "🧴",
        "sector": "FMCG",
    },
    {
        "symbol": "MARUTI",
        "name": "Maruti Suzuki India",
        "tv_ticker": "NSE:MARUTI",
        "yahoo_ticker": "MARUTI.NS",
        "bn_weight": 0.0,
        "n50_weight": 1.7,
        "group": "n50",
        "icon": "🚗",
        "sector": "Automobile",
    },
    {
        "symbol": "TATASTEEL",
        "name": "Tata Steel Ltd",
        "tv_ticker": "NSE:TATASTEEL",
        "yahoo_ticker": "TATASTEEL.NS",
        "bn_weight": 0.0,
        "n50_weight": 1.6,
        "group": "n50",
        "icon": "🔩",
        "sector": "Metals",
    },
    {
        "symbol": "SUNPHARMA",
        "name": "Sun Pharmaceutical",
        "tv_ticker": "NSE:SUNPHARMA",
        "yahoo_ticker": "SUNPHARMA.NS",
        "bn_weight": 0.0,
        "n50_weight": 1.5,
        "group": "n50",
        "icon": "💊",
        "sector": "Healthcare",
    },
    {
        "symbol": "TITAN",
        "name": "Titan Company Ltd",
        "tv_ticker": "NSE:TITAN",
        "yahoo_ticker": "TITAN.NS",
        "bn_weight": 0.0,
        "n50_weight": 1.4,
        "group": "n50",
        "icon": "💎",
        "sector": "Consumer",
    },
    {
        "symbol": "NTPC",
        "name": "NTPC Ltd",
        "tv_ticker": "NSE:NTPC",
        "yahoo_ticker": "NTPC.NS",
        "bn_weight": 0.0,
        "n50_weight": 1.4,
        "group": "n50",
        "icon": "⚡",
        "sector": "Utilities",
    },
]


class ContributorsService:
    """Manages real-time quotes, calculations, and point contributions for NIFTY & BANK NIFTY drivers."""

    _instance: Optional["ContributorsService"] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, root_dir: Optional[Path] = None) -> "ContributorsService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(root_dir=root_dir)
        return cls._instance

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent.parent
        self._cached_data: Optional[Dict[str, Any]] = None
        self._cached_timestamp: float = 0.0
        self._cache_ttl_seconds: float = 12.0  # 12-second live cache
        self._fetch_lock = threading.Lock()

    def get_contributors_summary(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Returns the full real-time contributor status, point contributions, and market aggregates."""
        now = time.time()
        if not force_refresh and self._cached_data and (now - self._cached_timestamp < self._cache_ttl_seconds):
            return self._cached_data

        with self._fetch_lock:
            # Recheck inside lock
            if not force_refresh and self._cached_data and (now - self._cached_timestamp < self._cache_ttl_seconds):
                return self._cached_data

            try:
                data = self._fetch_and_calculate()
                self._cached_data = data
                self._cached_timestamp = time.time()
                return data
            except Exception as e:
                logger.error("Failed to fetch contributors data: %s", e)
                if self._cached_data:
                    return self._cached_data
                # Return empty fallback
                return {
                    "status": "error",
                    "error": str(e),
                    "contributors": [],
                    "bn_total_pts": 0.0,
                    "n50_total_pts": 0.0,
                    "advances": 0,
                    "declines": 0,
                    "unchanged": 0,
                    "last_updated": datetime.now(IST).strftime("%H:%M:%S IST"),
                }

    def _fetch_and_calculate(self) -> Dict[str, Any]:
        """Fetches batch quotes via TradingView Scanner and computes point impacts."""
        tv_tickers = [c["tv_ticker"] for c in CONTRIBUTORS_CONFIG]
        url = "https://scanner.tradingview.com/india/scan"
        cols = ["name", "description", "close", "change", "change_abs", "volume"]
        payload = {"symbols": {"tickers": tv_tickers}, "columns": cols}
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Content-Type": "application/json",
        }

        quotes_map: Dict[str, Dict[str, Any]] = {}
        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=7.0)
            if resp.status_code == 200:
                body = resp.json()
                for item in body.get("data", []):
                    ticker = item.get("s")
                    d = item.get("d", [])
                    if len(d) >= 5:
                        quotes_map[ticker] = {
                            "name": d[0],
                            "desc": d[1],
                            "close": float(d[2] or 0.0),
                            "change_pct": float(d[3] or 0.0),
                            "change_abs": float(d[4] or 0.0),
                            "volume": int(d[5] or 0),
                        }
        except Exception as ex:
            logger.warning("TradingView scanner fetch error in ContributorsService: %s", ex)

        # Get current spot index prices for accurate point contribution estimation
        bn_index_price = 52000.0
        n50_index_price = 24000.0
        try:
            from nifty_trader.market_data.spot_service import get_spot_service
            spots = get_spot_service().latest_spots
            if "BANKNIFTY" in spots and float(spots["BANKNIFTY"].get("spot_price", 0.0)) > 0:
                bn_index_price = float(spots["BANKNIFTY"]["spot_price"])
            if "NIFTY 50" in spots and float(spots["NIFTY 50"].get("spot_price", 0.0)) > 0:
                n50_index_price = float(spots["NIFTY 50"]["spot_price"])
        except Exception:
            pass

        items: List[Dict[str, Any]] = []
        bn_total_pts = 0.0
        n50_total_pts = 0.0
        advances = 0
        declines = 0
        unchanged = 0

        for cfg in CONTRIBUTORS_CONFIG:
            sym = cfg["symbol"]
            q = quotes_map.get(cfg["tv_ticker"])
            close_val = q["close"] if q else 0.0
            chg_pct = q["change_pct"] if q else 0.0
            chg_abs = q["change_abs"] if q else 0.0
            vol = q["volume"] if q else 0

            # Calculate point contribution
            # Points contribution = (weight / 100) * Index_Price * (Stock_Change% / 100)
            bn_pts = 0.0
            if cfg["bn_weight"] > 0:
                bn_pts = round((cfg["bn_weight"] / 100.0) * bn_index_price * (chg_pct / 100.0), 2)
                bn_total_pts += bn_pts

            n50_pts = 0.0
            if cfg["n50_weight"] > 0:
                n50_pts = round((cfg["n50_weight"] / 100.0) * n50_index_price * (chg_pct / 100.0), 2)
                n50_total_pts += n50_pts

            # Direction
            if chg_pct > 0.05:
                direction = "up"
                advances += 1
            elif chg_pct < -0.05:
                direction = "down"
                declines += 1
            else:
                direction = "flat"
                unchanged += 1

            # Primary display weight and points
            if cfg["group"] == "bn":
                primary_weight_label = f"BN {cfg['bn_weight']}%"
                primary_pts = bn_pts
                primary_index = "BN"
            else:
                primary_weight_label = f"N50 {cfg['n50_weight']}%"
                primary_pts = n50_pts
                primary_index = "N50"

            item = {
                "symbol": sym,
                "name": cfg["name"],
                "icon": cfg["icon"],
                "group": cfg["group"],  # "bn" or "n50"
                "sector": cfg["sector"],
                "bn_weight": cfg["bn_weight"],
                "n50_weight": cfg["n50_weight"],
                "primary_weight_label": primary_weight_label,
                "primary_index": primary_index,
                "ltp": round(close_val, 2),
                "change_pct": round(chg_pct, 2),
                "change_abs": round(chg_abs, 2),
                "bn_pts": bn_pts,
                "n50_pts": n50_pts,
                "primary_pts": primary_pts,
                "direction": direction,
                "volume": vol,
            }
            items.append(item)

        # Sort items: Top positive contributors first, then negative draggers
        # Also compute top drivers for summary banner
        sorted_by_impact = sorted(items, key=lambda x: x["primary_pts"], reverse=True)
        top_gainers = [x for x in sorted_by_impact if x["primary_pts"] > 0][:3]
        top_draggers = [x for x in sorted_by_impact if x["primary_pts"] < 0][-3:]
        top_draggers.reverse()

        now_ist = datetime.now(IST).strftime("%H:%M:%S IST")

        return {
            "status": "ok",
            "contributors": items,
            "sorted_by_impact": sorted_by_impact,
            "bn_total_pts": round(bn_total_pts, 1),
            "n50_total_pts": round(n50_total_pts, 1),
            "bn_index_price": round(bn_index_price, 2),
            "n50_index_price": round(n50_index_price, 2),
            "advances": advances,
            "declines": declines,
            "unchanged": unchanged,
            "top_gainers": top_gainers,
            "top_draggers": top_draggers,
            "last_updated": now_ist,
        }


def get_contributors_service(root_dir: Optional[Path] = None) -> ContributorsService:
    """Helper to access singleton ContributorsService."""
    return ContributorsService.get_instance(root_dir=root_dir)
