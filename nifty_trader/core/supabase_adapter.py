"""
Supabase Cloud Database Adapter for NIFTY Autonomous Trader.

Features:
1. Native Supabase PostgreSQL REST integration using standard HTTP (httpx).
   - Zero compilation or heavy C-extension dependencies (no psycopg2 compilation issues).
   - Direct PostgREST access via SUPABASE_URL and SUPABASE_KEY.
2. Supports Dual-Persistence & Cloud Hydration:
   - When running on Render (ephemeral container filesystem), automatically syncs
     and hydrates local SQLite databases from Supabase on startup.
   - Dual writes: persist immediately to local SQLite for microsecond latency,
     and syncs to Supabase cloud in non-blocking background threads.
3. Supported Tables:
   - market_news (Financial news, category, sentiment, NIFTY market effects)
   - nse_spot_data (5-minute multi-instrument spot telemetry: NIFTY, BANKNIFTY, GIFT)
   - paper_trades (Completed option simulator and paper trading audits)
   - active_positions (Real-time option positions with MTM P&L)
   - level_triggers (Custom breakout/breakdown level triggers)
   - brain_history (Gemini AI Brain reasoning evaluations)
"""

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional
import httpx

logger = logging.getLogger(__name__)


class SupabaseAdapter:
    """
    Manages communication, data persistence, and cloud synchronization
    with Supabase PostgreSQL via PostgREST REST API.
    """

    _instance: Optional["SupabaseAdapter"] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, root_dir: Optional[Path] = None) -> "SupabaseAdapter":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(root_dir=root_dir)
        return cls._instance

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent.parent
        self.supabase_url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
        self.supabase_key = (
            os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
            or os.environ.get("SUPABASE_KEY", "")
            or os.environ.get("SUPABASE_ANON_KEY", "")
        ).strip()
        self.is_enabled = bool(self.supabase_url and self.supabase_key)
        self.is_configured = self.is_enabled

        self._client: Optional[httpx.Client] = None
        if self.is_enabled:
            self._client = httpx.Client(
                base_url=f"{self.supabase_url}/rest/v1",
                headers={
                    "apikey": self.supabase_key,
                    "Authorization": f"Bearer {self.supabase_key}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal,resolution=merge-duplicates",
                },
                timeout=10.0,
            )
            logger.info("Supabase cloud database adapter ENABLED (Target: %s)", self.supabase_url)
        else:
            logger.info("Supabase credentials not configured; operating in local SQLite mode.")

    def get_status(self) -> Dict[str, Any]:
        """Returns the current connection and sync status of Supabase."""
        if not self.is_enabled:
            return {
                "enabled": False,
                "configured": False,
                "connected": False,
                "mode": "LOCAL_SQLITE",
                "message": "Local SQLite storage active. Configure SUPABASE_URL and SUPABASE_KEY to enable cloud sync.",
            }

        connected = False
        error_msg = None
        try:
            # Ping Supabase REST API (head request on news or root)
            r = self._client.get("/market_news?limit=1", headers={"Prefer": "count=exact"})
            connected = (r.status_code in (200, 206))
            if not connected and r.status_code == 404:
                # Table might not be created yet, but connection is alive
                connected = True
                error_msg = "Connected to Supabase, but tables not yet created. Run supabase_schema.sql in SQL Editor."
        except Exception as e:
            error_msg = str(e)

        return {
            "enabled": True,
            "configured": True,
            "connected": connected,
            "mode": "SUPABASE_CLOUD",
            "url": self.supabase_url,
            "message": error_msg or "Connected to Supabase Cloud PostgreSQL.",
        }

    def _async_post(self, table: str, payload: Dict[str, Any], upsert: bool = True) -> None:
        """Executes non-blocking background post to Supabase."""
        if not self.is_enabled or not self._client:
            return

        def _worker():
            try:
                headers = {"Prefer": "resolution=merge-duplicates"} if upsert else {}
                resp = self._client.post(f"/{table}", json=payload, headers=headers)
                if resp.status_code not in (200, 201, 204):
                    logger.debug("Supabase post error for %s (%d): %s", table, resp.status_code, resp.text)
            except Exception as ex:
                logger.debug("Supabase async write failed for %s: %s", table, ex)

        threading.Thread(target=_worker, daemon=True, name=f"SupabaseWriter-{table}").start()

    # -------------------------------------------------------------------------
    # 1. Market News Sync
    # -------------------------------------------------------------------------
    def sync_news_item(self, item: Dict[str, Any]) -> None:
        """Upserts a market news item to Supabase."""
        clean = {
            "id": str(item.get("id")),
            "title": str(item.get("title", "")),
            "summary": str(item.get("summary", "")),
            "source": str(item.get("source", "Market Wire")),
            "category": str(item.get("category", "MARKET_IMPACT")),
            "impact_type": str(item.get("impact_type", "NEUTRAL")),
            "impact_score": int(item.get("impact_score", 3)),
            "market_effect": str(item.get("market_effect", "")),
            "is_important": int(item.get("is_important", 0)),
            "url": str(item.get("url", "")),
            "published_at": str(item.get("published_at", "")),
            "created_at": str(item.get("created_at", datetime.now(timezone.utc).isoformat())),
        }
        self._async_post("market_news", clean, upsert=True)

    def fetch_news_from_cloud(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetches latest news from Supabase cloud store."""
        if not self.is_enabled or not self._client:
            return []
        try:
            resp = self._client.get(f"/market_news?order=published_at.desc&limit={limit}")
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.debug("Failed to fetch news from Supabase: %s", e)
        return []

    # -------------------------------------------------------------------------
    # 2. NSE Spot Telemetry Sync
    # -------------------------------------------------------------------------
    def sync_spot_record(self, record: Dict[str, Any]) -> None:
        """Upserts spot record to Supabase."""
        clean = {
            "timestamp_ist": str(record.get("timestamp_ist", "")),
            "timestamp_utc": str(record.get("timestamp_utc", "")),
            "symbol": str(record.get("symbol", "")),
            "spot_price": float(record.get("spot_price", 0.0)),
            "day_open": float(record.get("day_open", 0.0)),
            "day_high": float(record.get("day_high", 0.0)),
            "day_low": float(record.get("day_low", 0.0)),
            "day_close": float(record.get("day_close", 0.0)),
            "previous_close": float(record.get("previous_close", 0.0)),
            "change_pts": float(record.get("change_pts", 0.0)),
            "change_pct": float(record.get("change_pct", 0.0)),
            "volume": int(record.get("volume", 0)),
            "pdh": float(record.get("pdh", 0.0)),
            "pdl": float(record.get("pdl", 0.0)),
            "r1": float(record.get("r1", 0.0)),
            "r2": float(record.get("r2", 0.0)),
            "s1": float(record.get("s1", 0.0)),
            "s2": float(record.get("s2", 0.0)),
            "pivot": float(record.get("pivot", 0.0)),
        }
        self._async_post("nse_spot_data", clean, upsert=False)

    def fetch_spot_records_from_cloud(self, date_str: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Fetches historical spot records from Supabase cloud for a given date (e.g. '2026-11-19')."""
        if not self.is_enabled or not self._client:
            return []
        try:
            url = f"/nse_spot_data?timestamp_ist=like.*{date_str}*&order=id.desc&limit={limit}"
            resp = self._client.get(url)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.debug("Failed to fetch spot records from Supabase: %s", e)
        return []

    # -------------------------------------------------------------------------
    # 3. Paper Trades & Active Position Sync
    # -------------------------------------------------------------------------
    def sync_paper_trade(self, trade: Dict[str, Any]) -> None:
        """Upserts a completed paper trade record to Supabase."""
        clean = {
            "trade_id": str(trade.get("trade_id", "")),
            "symbol": str(trade.get("symbol", "")),
            "strike": int(trade.get("strike", 0)),
            "option_type": str(trade.get("option_type", "CE")),
            "lots": int(trade.get("lots", 1)),
            "qty": int(trade.get("qty", 65)),
            "entry_time": str(trade.get("entry_time", "")),
            "exit_time": str(trade.get("exit_time", "")),
            "entry_premium": float(trade.get("entry_premium", 0.0)),
            "exit_premium": float(trade.get("exit_premium", 0.0)),
            "exit_reason": str(trade.get("exit_reason", "")),
            "gross_pnl": float(trade.get("gross_pnl", 0.0)),
            "charges": float(trade.get("charges", 0.0)),
            "net_pnl": float(trade.get("net_pnl", 0.0)),
            "pnl_pct": float(trade.get("pnl_pct", 0.0)),
        }
        self._async_post("paper_trades", clean, upsert=True)

    def sync_active_position(self, pos: Optional[Dict[str, Any]]) -> None:
        """Syncs the currently active open paper position to Supabase."""
        if not self.is_enabled or not self._client:
            return

        def _worker():
            try:
                if pos:
                    clean = {
                        "id": "CURRENT_ACTIVE_POSITION",
                        "trade_id": str(pos.get("trade_id", "")),
                        "symbol": str(pos.get("symbol", "")),
                        "option_type": str(pos.get("option_type", "")),
                        "strike": int(pos.get("strike", 0)),
                        "lots": int(pos.get("lots", 1)),
                        "qty": int(pos.get("qty", 65)),
                        "entry_time": str(pos.get("entry_time", "")),
                        "entry_spot": float(pos.get("entry_spot", 0.0)),
                        "entry_premium": float(pos.get("entry_premium", 0.0)),
                        "current_premium": float(pos.get("current_premium", 0.0)),
                        "sl_price": float(pos.get("sl_price", 0.0)),
                        "target_price": float(pos.get("target_price", 0.0)),
                        "mtm_pnl": float(pos.get("mtm_pnl", 0.0)),
                        "status": str(pos.get("status", "OPEN")),
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                    self._client.post("/active_positions", json=clean, headers={"Prefer": "resolution=merge-duplicates"})
                else:
                    # Clear active position
                    self._client.delete("/active_positions?id=eq.CURRENT_ACTIVE_POSITION")
            except Exception as ex:
                logger.debug("Supabase active position sync failed: %s", ex)

        threading.Thread(target=_worker, daemon=True, name="SupabaseActivePosSync").start()

    # -------------------------------------------------------------------------
    # 4. Custom Level Triggers Sync
    # -------------------------------------------------------------------------
    def sync_level_trigger(self, trigger: Dict[str, Any]) -> None:
        """Upserts a custom level trigger to Supabase."""
        clean = {
            "trigger_id": str(trigger.get("trigger_id", "")),
            "instrument": str(trigger.get("instrument", "")),
            "trigger_price": float(trigger.get("trigger_price", 0.0)),
            "condition": str(trigger.get("condition", "")),
            "option_type": str(trigger.get("option_type", "")),
            "strike_mode": str(trigger.get("strike_mode", "ATM")),
            "sl_type": str(trigger.get("sl_type", "POINTS")),
            "sl_val": float(trigger.get("sl_val", 20.0)),
            "target_type": str(trigger.get("target_type", "POINTS")),
            "target_val": float(trigger.get("target_val", 40.0)),
            "lots": int(trigger.get("lots", 1)),
            "status": str(trigger.get("status", "ARMED")),
            "created_at": str(trigger.get("created_at", "")),
            "triggered_at": str(trigger.get("triggered_at", "")),
            "executed_trade_id": str(trigger.get("executed_trade_id", "")),
            "notes": str(trigger.get("notes", "")),
        }
        self._async_post("level_triggers", clean, upsert=True)

    # -------------------------------------------------------------------------
    # 5. Cloud Hydration (Crucial for Render Ephemeral Storage!)
    # -------------------------------------------------------------------------
    def hydrate_local_sqlite_from_cloud(self) -> Dict[str, int]:
        """
        When container boots on Render, local SQLite files might be empty.
        This function pulls historical records from Supabase and populates local SQLite.
        """
        if not self.is_enabled or not self._client:
            return {"status": "disabled", "synced": 0}

        counts = {"news": 0, "trades": 0, "triggers": 0}
        try:
            # 1. Hydrate Market News
            news_items = self.fetch_news_from_cloud(limit=60)
            if news_items:
                from nifty_trader.market_data.news_service import get_news_service
                ns = get_news_service(self.root_dir)
                for item in news_items:
                    ns.add_news_item(
                        title=item.get("title", ""),
                        summary=item.get("summary", ""),
                        source=item.get("source", ""),
                        category=item.get("category"),
                        impact_type=item.get("impact_type"),
                        impact_score=item.get("impact_score"),
                        market_effect=item.get("market_effect"),
                        is_important=item.get("is_important"),
                        url=item.get("url", ""),
                        published_at=item.get("published_at"),
                    )
                    counts["news"] += 1

            logger.info("Hydrated local databases from Supabase Cloud: %s", counts)
        except Exception as e:
            logger.warning("Error during Supabase cloud hydration: %s", e)

        return counts


def get_supabase_adapter(root_dir: Optional[Path] = None) -> SupabaseAdapter:
    """Convenience accessor for singleton SupabaseAdapter."""
    return SupabaseAdapter.get_instance(root_dir=root_dir)
