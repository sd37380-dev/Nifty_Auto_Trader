"""
Dhan Market Data & Chart Sync Service (Exclusive Dhan HQ Feed).

Provides seamless integration with Dhan HQ API for:
1. Index Futures (NIFTY FUT, BANKNIFTY FUT, FINNIFTY FUT)
2. Spot Indices (NIFTY 50, BANKNIFTY, FINNIFTY, MIDCPNIFTY, SENSEX)
3. Heavyweight Equities (HDFCBANK, RELIANCE, ICICIBANK, SBIN, TCS, INFY, etc.)
4. Real Traded Volume & Candlesticks across all timeframes (1m, 5m, 15m, 30m, 60m/1h, 1d, 1w)
5. Volume Profile (Point of Control - POC, VAH, VAL) & Volume Delta
6. Futures Basis Tracking (Futures vs. Cash Spot Spread / Premium / Discount)

Configured to use Dhan HQ API exclusively for all charts and market data.
"""

import os
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path
import httpx

logger = logging.getLogger("dhan_futures_service")

# Standard Dhan Exchange & Instrument Codes
EXCHANGE_FNO = "NSE_FNO"
EXCHANGE_EQ = "NSE_EQ"
EXCHANGE_IDX = "IDX_I"

INSTRUMENT_FUTIDX = "FUTIDX"
INSTRUMENT_FUTSTK = "FUTSTK"
INSTRUMENT_EQUITY = "EQUITY"
INSTRUMENT_INDEX = "INDEX"

# Standard Dhan Security ID Mapping for Indices, Heavyweight Equities & Futures
DHAN_SECURITY_MAP: Dict[str, Tuple[str, str, str]] = {
    # Format: Symbol -> (securityId, exchangeSegment, instrument)
    # Indices
    "NIFTY": ("13", EXCHANGE_IDX, INSTRUMENT_INDEX),
    "NIFTY50": ("13", EXCHANGE_IDX, INSTRUMENT_INDEX),
    "NIFTY 50": ("13", EXCHANGE_IDX, INSTRUMENT_INDEX),
    "NSE:NIFTY": ("13", EXCHANGE_IDX, INSTRUMENT_INDEX),
    "BANKNIFTY": ("25", EXCHANGE_IDX, INSTRUMENT_INDEX),
    "BANK NIFTY": ("25", EXCHANGE_IDX, INSTRUMENT_INDEX),
    "NSE:BANKNIFTY": ("25", EXCHANGE_IDX, INSTRUMENT_INDEX),
    "FINNIFTY": ("27", EXCHANGE_IDX, INSTRUMENT_INDEX),
    "MIDCPNIFTY": ("442", EXCHANGE_IDX, INSTRUMENT_INDEX),
    "SENSEX": ("51", EXCHANGE_IDX, INSTRUMENT_INDEX),
    "BSE:SENSEX": ("51", EXCHANGE_IDX, INSTRUMENT_INDEX),

    # Bank Nifty Top Heavyweights
    "HDFCBANK": ("1333", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "NSE:HDFCBANK": ("1333", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "ICICIBANK": ("4963", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "NSE:ICICIBANK": ("4963", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "SBIN": ("3045", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "NSE:SBIN": ("3045", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "AXISBANK": ("5900", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "NSE:AXISBANK": ("5900", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "KOTAKBANK": ("1922", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "NSE:KOTAKBANK": ("1922", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "INDUSINDBK": ("5258", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "NSE:INDUSINDBK": ("5258", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "BANKBARODA": ("4668", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "NSE:BANKBARODA": ("4668", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "PNB": ("10666", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "NSE:PNB": ("10666", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "AUBANK": ("21238", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "NSE:AUBANK": ("21238", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "FEDERALBNK": ("1023", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "NSE:FEDERALBNK": ("1023", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "IDFCFIRSTB": ("11184", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "NSE:IDFCFIRSTB": ("11184", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "BANDHANBNK": ("2263", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "NSE:BANDHANBNK": ("2263", EXCHANGE_EQ, INSTRUMENT_EQUITY),

    # Nifty 50 Top Heavyweights
    "RELIANCE": ("2885", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "NSE:RELIANCE": ("2885", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "INFY": ("1594", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "NSE:INFY": ("1594", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "ITC": ("1660", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "NSE:ITC": ("1660", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "TCS": ("11536", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "NSE:TCS": ("11536", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "LT": ("11483", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "NSE:LT": ("11483", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "BHARTIARTL": ("10604", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "NSE:BHARTIARTL": ("10604", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "BAJFINANCE": ("317", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "NSE:BAJFINANCE": ("317", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "M&M": ("2031", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "MM": ("2031", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "NSE:M&M": ("2031", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "HINDUNILVR": ("1394", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "NSE:HINDUNILVR": ("1394", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "MARUTI": ("10999", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "NSE:MARUTI": ("10999", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "TATAMOTORS": ("3456", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "TMCV": ("3456", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "TATASTEEL": ("3499", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "NSE:TATASTEEL": ("3499", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "SUNPHARMA": ("3351", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "NSE:SUNPHARMA": ("3351", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "TITAN": ("3506", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "NSE:TITAN": ("3506", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "NTPC": ("11630", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "NSE:NTPC": ("11630", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "POWERGRID": ("14977", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "NSE:POWERGRID": ("14977", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "WIPRO": ("3787", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "NSE:WIPRO": ("3787", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "HCLTECH": ("7229", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "NSE:HCLTECH": ("7229", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "ASIANPAINT": ("236", EXCHANGE_EQ, INSTRUMENT_EQUITY),
    "NSE:ASIANPAINT": ("236", EXCHANGE_EQ, INSTRUMENT_EQUITY),

    # Futures (December 2026 Monthly Expiry Contracts)
    "NIFTY_FUT": ("58875", EXCHANGE_FNO, INSTRUMENT_FUTIDX),
    "NIFTY_DEC_FUT": ("58875", EXCHANGE_FNO, INSTRUMENT_FUTIDX),
    "NIFTY DEC FUT": ("58875", EXCHANGE_FNO, INSTRUMENT_FUTIDX),
    "BANKNIFTY_FUT": ("58872", EXCHANGE_FNO, INSTRUMENT_FUTIDX),
    "BANKNIFTY_DEC_FUT": ("58872", EXCHANGE_FNO, INSTRUMENT_FUTIDX),
    "BANKNIFTY DEC FUT": ("58872", EXCHANGE_FNO, INSTRUMENT_FUTIDX),
    "FINNIFTY_FUT": ("58873", EXCHANGE_FNO, INSTRUMENT_FUTIDX),
    "FINNIFTY_DEC_FUT": ("58873", EXCHANGE_FNO, INSTRUMENT_FUTIDX),
    "FINNIFTY DEC FUT": ("58873", EXCHANGE_FNO, INSTRUMENT_FUTIDX),
    "MIDCPNIFTY_FUT": ("58874", EXCHANGE_FNO, INSTRUMENT_FUTIDX),
    "MIDCPNIFTY_DEC_FUT": ("58874", EXCHANGE_FNO, INSTRUMENT_FUTIDX),
    "MIDCPNIFTY DEC FUT": ("58874", EXCHANGE_FNO, INSTRUMENT_FUTIDX),
}


class DhanFuturesService:
    """Singleton service for Dhan HQ market data and chart synchronization."""

    _instance: Optional["DhanFuturesService"] = None

    @classmethod
    def get_instance(cls) -> "DhanFuturesService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.base_url = "https://api.dhan.co"
        self._sec_id_cache: Dict[str, str] = {
            "NIFTY_FUT": "58875",
            "BANKNIFTY_FUT": "58872",
            "FINNIFTY_FUT": "58873",
            "MIDCPNIFTY_FUT": "58874",
        }

    def _reload_env_if_needed(self):
        """Ensures active token from .env is loaded dynamically."""
        if not (os.environ.get("DHAN_CLIENT_ID") and os.environ.get("DHAN_ACCESS_TOKEN")):
            env_file = Path(__file__).resolve().parent.parent.parent / ".env"
            if env_file.exists():
                try:
                    from dotenv import load_dotenv
                    load_dotenv(env_file, override=True)
                except Exception:
                    pass

    @property
    def client_id(self) -> str:
        self._reload_env_if_needed()
        return os.environ.get("DHAN_CLIENT_ID", "").strip()

    @property
    def access_token(self) -> str:
        self._reload_env_if_needed()
        return os.environ.get("DHAN_ACCESS_TOKEN", "").strip()

    @property
    def is_configured(self) -> bool:
        """Returns True if valid Dhan API credentials are present."""
        return bool(self.client_id and self.access_token and len(self.access_token) > 15)

    def get_connection_status(self) -> Dict[str, Any]:
        """Returns detailed broker and chart connectivity status."""
        configured = self.is_configured
        masked_id = (
            f"{self.client_id[:3]}***{self.client_id[-2:]}"
            if len(self.client_id) > 4
            else ("CONNECTED" if configured else "NOT_CONFIGURED")
        )
        return {
            "configured": configured,
            "client_id_masked": masked_id,
            "supported_futures": ["NIFTY_FUT", "BANKNIFTY_FUT", "FINNIFTY_FUT"],
            "features_enabled": [
                "Real Traded Volume (Dhan HQ)",
                "Spot Indices Exclusive Feed",
                "Equity Heavyweights Exclusive Feed",
                "Volume Profile (POC / VAH / VAL)",
                "Futures Basis Spread (Premium / Discount)",
                "Institutional Multi-Chart Quad Sync",
            ],
            "message": (
                "🟢 Dhan HQ Live Market Data Feed Active"
                if configured
                else "🟡 Ready for Dhan Credentials (DHAN_CLIENT_ID & DHAN_ACCESS_TOKEN)"
            ),
        }

    def resolve_future_symbol(self, raw_symbol: str) -> Optional[Tuple[str, str]]:
        """
        Normalizes a symbol string to (StandardFutureKey, UnderlyingSpotSymbol).
        Supports: 'NIFTY FUT', 'NIFTY_FUT', 'NIFTY DEC FUT', 'NIFTY1!', etc.
        """
        s = raw_symbol.upper().replace(" ", "_").replace("-", "_").strip()
        if "BANKNIFTY" in s and any(k in s for k in ("FUT", "1!", "DEC", "JAN", "FEB")):
            return "BANKNIFTY_FUT", "BANKNIFTY"
        if "FINNIFTY" in s and any(k in s for k in ("FUT", "1!", "DEC", "JAN", "FEB")):
            return "FINNIFTY_FUT", "FINNIFTY"
        if "MIDCPNIFTY" in s and any(k in s for k in ("FUT", "1!", "DEC", "JAN", "FEB")):
            return "MIDCPNIFTY_FUT", "MIDCPNIFTY"
        if "NIFTY" in s and any(k in s for k in ("FUT", "1!", "DEC", "JAN", "FEB")):
            return "NIFTY_FUT", "NIFTY"
        if s in ("NIFTY_FUT", "NIFTY_FUTURE", "NIFTYFUT", "NIFTY1!", "NSE:NIFTY1!"):
            return "NIFTY_FUT", "NIFTY"
        if s in ("BANKNIFTY_FUT", "BANKNIFTY_FUTURE", "BANKNIFTYFUT", "BANKNIFTY1!", "NSE:BANKNIFTY1!"):
            return "BANKNIFTY_FUT", "BANKNIFTY"
        if s in ("FINNIFTY_FUT", "FINNIFTY_FUTURE", "FINNIFTYFUT", "FINNIFTY1!", "NSE:FINNIFTY1!"):
            return "FINNIFTY_FUT", "FINNIFTY"
        if s in ("MIDCPNIFTY_FUT", "MIDCPNIFTY_FUTURE", "MIDCPNIFTYFUT", "MIDCPNIFTY1!", "NSE:MIDCPNIFTY1!"):
            return "MIDCPNIFTY_FUT", "MIDCPNIFTY"
        return None

    def calculate_volume_profile(self, candles: List[Dict[str, Any]], num_bins: int = 24) -> Dict[str, Any]:
        """Computes Point of Control (POC), Value Area High (VAH), and Value Area Low (VAL)."""
        if not candles:
            return {"poc": 0.0, "vah": 0.0, "val": 0.0, "total_volume": 0}

        low_min = min(c["low"] for c in candles)
        high_max = max(c["high"] for c in candles)
        if high_max <= low_min:
            return {"poc": round(candles[-1]["close"], 2), "vah": high_max, "val": low_min, "total_volume": 0}

        bin_size = (high_max - low_min) / num_bins
        bins = [0] * num_bins
        total_vol = 0

        for c in candles:
            vol = c.get("volume", 0)
            total_vol += vol
            typical_price = (c["high"] + c["low"] + c["close"]) / 3.0
            idx = int((typical_price - low_min) / bin_size)
            idx = max(0, min(num_bins - 1, idx))
            bins[idx] += vol

        max_idx = bins.index(max(bins))
        poc = round(low_min + (max_idx + 0.5) * bin_size, 2)

        # 70% Value Area calculation
        target_vol = total_vol * 0.70
        accum_vol = bins[max_idx]
        left_idx = max_idx
        right_idx = max_idx

        while accum_vol < target_vol and (left_idx > 0 or right_idx < num_bins - 1):
            left_vol = bins[left_idx - 1] if left_idx > 0 else -1
            right_vol = bins[right_idx + 1] if right_idx < num_bins - 1 else -1

            if left_vol >= right_vol and left_idx > 0:
                left_idx -= 1
                accum_vol += bins[left_idx]
            elif right_idx < num_bins - 1:
                right_idx += 1
                accum_vol += bins[right_idx]
            else:
                break

        val = round(low_min + left_idx * bin_size, 2)
        vah = round(low_min + (right_idx + 1) * bin_size, 2)

        return {
            "poc": poc,
            "vah": vah,
            "val": val,
            "total_volume": total_vol,
        }

    def fetch_dhan_candles(
        self,
        symbol: str,
        interval: str = "5m",
        range_str: str = "5d",
    ) -> Optional[Dict[str, Any]]:
        """
        Unified Dhan HQ Chart Fetcher.
        Handles Spot Indices, Equity Heavyweights, and Futures.
        Queries Dhan /v2/charts/intraday or /v2/charts/historical based on requested interval.
        """
        if not self.is_configured:
            return None

        sym_clean = symbol.upper().strip()
        config = DHAN_SECURITY_MAP.get(sym_clean)
        if not config:
            # Try stripping prefix
            if sym_clean.startswith("NSE:") or sym_clean.startswith("BSE:"):
                config = DHAN_SECURITY_MAP.get(sym_clean[4:])

        if not config:
            return None

        sec_id, exchange_seg, instrument = config

        intv_map = {"1m": "1", "2m": "2", "5m": "5", "15m": "15", "30m": "30", "60m": "60", "1h": "60"}
        days_map = {"1d": 1, "2d": 2, "5d": 5, "1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730, "5y": 1825}

        is_daily_or_longer = interval.lower() in ("1d", "1w", "1wk")
        now = datetime.now()
        days = days_map.get(range_str.lower(), 5 if not is_daily_or_longer else 60)
        from_dt = now - timedelta(days=days)

        headers = {
            "client-id": self.client_id,
            "access-token": self.access_token,
            "Content-Type": "application/json",
        }

        try:
            if is_daily_or_longer:
                # Query historical endpoint
                payload = {
                    "securityId": sec_id,
                    "exchangeSegment": exchange_seg,
                    "instrument": instrument,
                    "expiryCode": 0,
                    "fromDate": from_dt.strftime("%Y-%m-%d"),
                    "toDate": now.strftime("%Y-%m-%d"),
                }
                resp = httpx.post(f"{self.base_url}/v2/charts/historical", headers=headers, json=payload, timeout=12.0)
            else:
                # Query intraday endpoint
                dhan_intv = intv_map.get(interval.lower(), "5")
                payload = {
                    "securityId": sec_id,
                    "exchangeSegment": exchange_seg,
                    "instrument": instrument,
                    "interval": dhan_intv,
                    "fromDate": from_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "toDate": now.strftime("%Y-%m-%d %H:%M:%S"),
                }
                resp = httpx.post(f"{self.base_url}/v2/charts/intraday", headers=headers, json=payload, timeout=12.0)

            if resp.status_code == 200:
                data = resp.json()
                if "open" in data and len(data["open"]) > 0:
                    candles = []
                    opens = data["open"]
                    highs = data["high"]
                    lows = data["low"]
                    closes = data["close"]
                    vols = data.get("volume", [0] * len(opens))
                    ts = data.get("timestamp", [0] * len(opens))

                    for o, h, l, c, v, t in zip(opens, highs, lows, closes, vols, ts):
                        candles.append({
                            "time": int(t),
                            "open": round(float(o), 2),
                            "high": round(float(h), 2),
                            "low": round(float(l), 2),
                            "close": round(float(c), 2),
                            "volume": int(v),
                        })

                    if candles:
                        logger.info("Successfully fetched %d live Dhan bars for %s (%s)", len(candles), symbol, interval)
                        return {
                            "symbol": symbol,
                            "interval": interval,
                            "range": range_str,
                            "currency": "INR",
                            "status": "ok",
                            "source": "Dhan HQ API (Exclusive Feed)",
                            "regularMarketPrice": candles[-1]["close"],
                            "previousClose": candles[0]["open"],
                            "candles": candles,
                        }
            else:
                logger.warning("Dhan chart endpoint returned HTTP %s for %s: %s", resp.status_code, symbol, resp.text[:120])
        except Exception as e:
            logger.error("Error fetching Dhan candles for %s: %s", symbol, e)

        return None

    def fetch_dhan_intraday_candles(
        self,
        future_key: str,
        interval_min: str = "5",
        days: int = 5,
    ) -> Optional[List[Dict[str, Any]]]:
        """Fetches authentic intraday futures candles directly from Dhan HQ API."""
        c_res = self.fetch_dhan_candles(future_key, interval=f"{interval_min}m" if "m" not in interval_min else interval_min, range_str=f"{days}d")
        if c_res and "candles" in c_res:
            return c_res["candles"]
        return None

    def fetch_dhan_index_candles(
        self,
        symbol: str,
        interval_min: str = "5",
        days: int = 5,
    ) -> Optional[List[Dict[str, Any]]]:
        """Fetches authentic Spot Index candles directly from Dhan HQ API."""
        c_res = self.fetch_dhan_candles(symbol, interval=f"{interval_min}m" if "m" not in interval_min else interval_min, range_str=f"{days}d")
        if c_res and "candles" in c_res:
            return c_res["candles"]
        return None

    def get_futures_candles(
        self,
        raw_symbol: str,
        interval: str = "5m",
        range_str: str = "5d",
        spot_candles: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Retrieves Futures candlestick series.
        - If Dhan credentials are set: queries live Dhan HQ F&O feed.
        - If Dhan credentials are pending: models Futures from Spot with realistic basis and volume.
        """
        res = self.resolve_future_symbol(raw_symbol)
        if not res:
            return {"status": "error", "message": f"Unsupported futures symbol: {raw_symbol}"}

        future_key, spot_symbol = res

        intv_map = {"1m": "1", "5m": "5", "15m": "15", "30m": "30", "60m": "60", "1h": "60"}
        dhan_intv = intv_map.get(interval.lower(), "5")

        days_map = {"1d": 1, "5d": 5, "1mo": 30, "3mo": 90}
        days = days_map.get(range_str.lower(), 5)

        candles: Optional[List[Dict[str, Any]]] = None
        source = "Dhan HQ API (Exclusive Feed)"

        if self.is_configured:
            candles = self.fetch_dhan_intraday_candles(future_key, interval_min=dhan_intv, days=days)

        if not candles:
            source = "DHAN_MODELED_FUTURES" if not self.is_configured else "DHAN_FALLBACK_SYNTHETIC"
            candles = []
            if spot_candles:
                basis_offset = 28.5 if "BANK" not in future_key else 95.0
                vol_multiplier = 4.2

                for sc in spot_candles:
                    candles.append({
                        "time": sc["time"],
                        "open": round(sc["open"] + basis_offset, 2),
                        "high": round(sc["high"] + basis_offset, 2),
                        "low": round(sc["low"] + basis_offset, 2),
                        "close": round(sc["close"] + basis_offset, 2),
                        "volume": int(sc.get("volume", 50000) * vol_multiplier),
                    })

        basis_info = {"basis_pts": 0.0, "basis_pct": 0.0, "status": "NEUTRAL"}
        if candles and spot_candles:
            fut_c = candles[-1]["close"]
            spot_c = spot_candles[-1]["close"]
            basis_pts = round(fut_c - spot_c, 2)
            basis_pct = round((basis_pts / spot_c) * 100, 3)
            status = "PREMIUM (CONTANGO)" if basis_pts >= 0 else "DISCOUNT (BACKWARDATION)"
            basis_info = {
                "basis_pts": basis_pts,
                "basis_pct": basis_pct,
                "status": status,
                "spot_close": spot_c,
                "futures_close": fut_c,
            }

        vol_profile = self.calculate_volume_profile(candles or [])

        return {
            "status": "ok",
            "symbol": future_key,
            "underlying": spot_symbol,
            "source": source,
            "dhan_connected": self.is_configured,
            "candles": candles or [],
            "basis": basis_info,
            "volume_profile": vol_profile,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


def get_dhan_futures_service() -> DhanFuturesService:
    return DhanFuturesService.get_instance()
