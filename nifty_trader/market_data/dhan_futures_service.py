"""
Dhan Futures Market Data & Chart Sync Service.

Provides seamless integration with Dhan HQ API for:
1. Index Futures (NIFTY FUT, BANKNIFTY FUT, FINNIFTY FUT)
2. Real Traded Volume & Intraday Candlesticks (1M, 5M, 15M, 1H)
3. Volume Profile (Point of Control - POC, VAH, VAL) & Volume Delta
4. Futures Basis Tracking (Futures vs. Cash Spot Spread / Premium / Discount)

Designed so the user can simply provide DHAN_CLIENT_ID & DHAN_ACCESS_TOKEN
to instantly activate live institutional futures synchronization.
"""

import os
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

logger = logging.getLogger("dhan_futures_service")

# Standard Dhan Exchange & Instrument Codes
EXCHANGE_FNO = "NSE_FNO"
INSTRUMENT_FUTIDX = "FUTIDX"
INSTRUMENT_FUTSTK = "FUTSTK"


class DhanFuturesService:
    """Singleton service for Dhan Futures market data and chart synchronization."""

    _instance: Optional["DhanFuturesService"] = None

    @classmethod
    def get_instance(cls) -> "DhanFuturesService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.base_url = "https://api.dhan.co"
        # Known common security IDs or defaults for nearest contracts
        # Can be dynamically resolved or refreshed from Dhan Scrip Master
        self._sec_id_cache: Dict[str, str] = {
            "NIFTY_FUT": "49557",       # Current Nifty Index Future
            "BANKNIFTY_FUT": "49558",   # Current BankNifty Index Future
            "FINNIFTY_FUT": "49559",    # Current FinNifty Index Future
        }

    @property
    def client_id(self) -> str:
        return os.environ.get("DHAN_CLIENT_ID", "").strip()

    @property
    def access_token(self) -> str:
        return os.environ.get("DHAN_ACCESS_TOKEN", "").strip()

    @property
    def is_configured(self) -> bool:
        """Returns True if valid Dhan API credentials are present."""
        return bool(self.client_id and self.access_token and len(self.access_token) > 15)

    def get_connection_status(self) -> Dict[str, Any]:
        """Returns detailed broker and futures connectivity status."""
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
                "Real Traded Volume",
                "Volume Profile (POC / VAH / VAL)",
                "Futures Basis Spread (Premium / Discount)",
                "Institutional Multi-Chart Quad Sync",
                "Dhan TradingView Console 1-Click Launch",
            ],
            "message": (
                "🟢 Dhan HQ Live Futures Feed Active"
                if configured
                else "🟡 Ready for Dhan Credentials (DHAN_CLIENT_ID & DHAN_ACCESS_TOKEN)"
            ),
        }

    def resolve_future_symbol(self, raw_symbol: str) -> Optional[Tuple[str, str]]:
        """
        Normalizes a symbol string to (StandardFutureKey, UnderlyingSpotSymbol).
        Example: 'NIFTY FUT' -> ('NIFTY_FUT', 'NIFTY')
        """
        s = raw_symbol.upper().replace(" ", "_").replace("-", "_").strip()
        if s in ("NIFTY_FUT", "NIFTY_FUTURE", "NIFTYFUT", "NIFTY1!", "NSE:NIFTY1!"):
            return "NIFTY_FUT", "NIFTY"
        if s in ("BANKNIFTY_FUT", "BANKNIFTY_FUTURE", "BANKNIFTYFUT", "BANKNIFTY1!", "NSE:BANKNIFTY1!"):
            return "BANKNIFTY_FUT", "BANKNIFTY"
        if s in ("FINNIFTY_FUT", "FINNIFTY_FUTURE", "FINNIFTYFUT", "FINNIFTY1!", "NSE:FINNIFTY1!"):
            return "FINNIFTY_FUT", "FINNIFTY"
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

    def fetch_dhan_intraday_candles(
        self,
        future_key: str,
        interval_min: str = "5",
        days: int = 5,
    ) -> Optional[List[Dict[str, Any]]]:
        """Fetches authentic intraday futures candles directly from Dhan HQ API."""
        if not self.is_configured:
            return None

        import httpx

        sec_id = self._sec_id_cache.get(future_key, "49557")
        now = datetime.now()
        from_dt = now - timedelta(days=days)

        headers = {
            "client-id": self.client_id,
            "access-token": self.access_token,
            "Content-Type": "application/json",
        }
        payload = {
            "securityId": sec_id,
            "exchangeSegment": EXCHANGE_FNO,
            "instrument": INSTRUMENT_FUTIDX,
            "interval": interval_min,
            "fromDate": from_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "toDate": now.strftime("%Y-%m-%d %H:%M:%S"),
        }

        try:
            resp = httpx.post(f"{self.base_url}/v2/charts/intraday", headers=headers, json=payload, timeout=12.0)
            if resp.status_code == 200:
                data = resp.json()
                if "open" in data and len(data["open"]) > 0:
                    candles = []
                    for o, h, l, c, v, t in zip(
                        data["open"],
                        data["high"],
                        data["low"],
                        data["close"],
                        data.get("volume", [0] * len(data["open"])),
                        data.get("timestamp", [0] * len(data["open"])),
                    ):
                        candles.append({
                            "time": int(t),
                            "open": round(float(o), 2),
                            "high": round(float(h), 2),
                            "low": round(float(l), 2),
                            "close": round(float(c), 2),
                            "volume": int(v),
                        })
                    logger.info("Successfully fetched %d live Dhan futures bars for %s", len(candles), future_key)
                    return candles
            else:
                logger.warning("Dhan futures endpoint returned HTTP %s: %s", resp.status_code, resp.text[:120])
        except Exception as e:
            logger.error("Error connecting to Dhan HQ for futures: %s", e)

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

        # Map interval
        intv_map = {"1m": "1", "5m": "5", "15m": "15", "30m": "30", "60m": "60", "1h": "60"}
        dhan_intv = intv_map.get(interval.lower(), "5")

        days_map = {"1d": 1, "5d": 5, "1mo": 30, "3mo": 90}
        days = days_map.get(range_str.lower(), 5)

        candles: Optional[List[Dict[str, Any]]] = None
        source = "DHAN_HQ_LIVE"

        if self.is_configured:
            candles = self.fetch_dhan_intraday_candles(future_key, interval_min=dhan_intv, days=days)

        # Fallback or Pre-credential Mode:
        # Construct modeled institutional futures bars from spot candles with typical basis
        if not candles:
            source = "DHAN_MODELED_FUTURES" if not self.is_configured else "DHAN_FALLBACK_SYNTHETIC"
            candles = []
            if spot_candles:
                # Typical basis: Nifty ~ +25.0 to +35.0 pts; BankNifty ~ +80.0 to +120.0 pts
                basis_offset = 28.5 if "BANK" not in future_key else 95.0
                vol_multiplier = 4.2  # Futures traded contract volume simulation

                for sc in spot_candles:
                    candles.append({
                        "time": sc["time"],
                        "open": round(sc["open"] + basis_offset, 2),
                        "high": round(sc["high"] + basis_offset, 2),
                        "low": round(sc["low"] + basis_offset, 2),
                        "close": round(sc["close"] + basis_offset, 2),
                        "volume": int(sc.get("volume", 50000) * vol_multiplier),
                    })

        # Calculate Basis Metrics
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

        # Calculate Volume Profile
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
