"""
Broker Execution Service & Chart Trade Manager for NIFTY Autonomous Trader.

Handles:
1. Broker Connectivity (Dhan HQ REST API, Zerodha / Generic Broker Architecture).
2. Routing orders to Broker (when connected) or Option Paper Trading Simulator.
3. Chart Trade executions from Visual Long/Short Chart Tool.
4. Chart Screenshot persistence and audit logging.
5. Real-time Telegram alert dispatch with attached chart screenshot photo.
"""

import base64
from datetime import datetime, timezone, timedelta
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional
import httpx

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


class BrokerService:
    """Manages Broker authentication and order execution."""

    _instance: Optional["BrokerService"] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, root_dir: Optional[Path] = None) -> "BrokerService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(root_dir=root_dir)
        return cls._instance

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent.parent
        self.dhan_client_id = os.environ.get("DHAN_CLIENT_ID", "").strip()
        self.dhan_access_token = os.environ.get("DHAN_ACCESS_TOKEN", "").strip()
        self.base_url = "https://api.dhan.co"
        self._init_db()

    def _init_db(self):
        """Initializes SQLite table for chart trade audit logs."""
        db_path = self.root_dir / "data" / "paper_trading" / "paper_trades.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = sqlite3.connect(str(db_path), timeout=10.0)
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS chart_trades (
                        trade_id TEXT PRIMARY KEY,
                        symbol TEXT NOT NULL,
                        setup_type TEXT NOT NULL,
                        option_type TEXT NOT NULL,
                        strike INTEGER NOT NULL,
                        entry_spot REAL NOT NULL,
                        target_spot REAL NOT NULL,
                        sl_spot REAL NOT NULL,
                        premium REAL NOT NULL,
                        lots INTEGER NOT NULL,
                        qty INTEGER NOT NULL,
                        risk_reward TEXT NOT NULL,
                        mode TEXT NOT NULL,
                        broker TEXT NOT NULL,
                        broker_order_id TEXT,
                        screenshot_path TEXT,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        closed_at TEXT,
                        exit_price REAL,
                        net_pnl REAL
                    )
                """)
            conn.close()
        except Exception as e:
            logger.warning("Error initializing chart_trades table: %s", e)

    @property
    def is_broker_connected(self) -> bool:
        """Checks if live broker credentials (e.g. Dhan HQ) are configured."""
        return bool(self.dhan_client_id and self.dhan_access_token and len(self.dhan_access_token) > 15)

    def get_status(self) -> Dict[str, Any]:
        """Returns live broker connectivity status."""
        masked_id = (
            f"{self.dhan_client_id[:3]}***{self.dhan_client_id[-2:]}"
            if len(self.dhan_client_id) > 4
            else ("SET" if self.dhan_client_id else "NOT_SET")
        )
        return {
            "broker_name": "Dhan HQ" if self.is_broker_connected else "None (Paper Mode)",
            "connected": self.is_broker_connected,
            "client_id_masked": masked_id,
            "has_token": bool(self.dhan_access_token),
            "execution_mode": "BROKER_LIVE" if self.is_broker_connected else "PAPER_SIMULATOR",
            "message": "Connected to Dhan HQ API for live trading" if self.is_broker_connected else "Running in Paper Simulator mode (No live broker credentials)",
        }

    def set_credentials(self, client_id: str, access_token: str) -> Dict[str, Any]:
        """Updates broker credentials and saves to local .env."""
        self.dhan_client_id = client_id.strip()
        self.dhan_access_token = access_token.strip()
        os.environ["DHAN_CLIENT_ID"] = self.dhan_client_id
        os.environ["DHAN_ACCESS_TOKEN"] = self.dhan_access_token

        env_file = self.root_dir / ".env"
        try:
            if env_file.exists():
                lines = env_file.read_text(encoding="utf-8").splitlines()
                updated_id = False
                updated_token = False
                new_lines = []
                for line in lines:
                    if line.startswith("DHAN_CLIENT_ID="):
                        new_lines.append(f"DHAN_CLIENT_ID={self.dhan_client_id}")
                        updated_id = True
                    elif line.startswith("DHAN_ACCESS_TOKEN="):
                        new_lines.append(f"DHAN_ACCESS_TOKEN={self.dhan_access_token}")
                        updated_token = True
                    else:
                        new_lines.append(line)
                if not updated_id:
                    new_lines.append(f"DHAN_CLIENT_ID={self.dhan_client_id}")
                if not updated_token:
                    new_lines.append(f"DHAN_ACCESS_TOKEN={self.dhan_access_token}")
                env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        except Exception as e:
            logger.warning("Could not persist Dhan credentials to .env: %s", e)

        return self.get_status()

    def test_broker_connection(self) -> Dict[str, Any]:
        """Tests Dhan HQ API connectivity."""
        if not self.is_broker_connected:
            return {"status": "error", "message": "Dhan Client ID or Access Token is missing."}

        headers = {
            "access-token": self.dhan_access_token,
            "client-id": self.dhan_client_id,
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(f"{self.base_url}/profile", headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    return {"status": "ok", "message": "Successfully authenticated with Dhan HQ!", "profile": data}
                else:
                    return {"status": "error", "message": f"Dhan API returned HTTP {resp.status_code}: {resp.text}"}
        except Exception as ex:
            return {"status": "error", "message": f"Connection error: {ex}"}

    def place_broker_order(
        self,
        symbol: str,
        strike: int,
        option_type: str,
        action: str = "BUY",
        quantity: int = 65,
        price: float = 0.0,
        sl_price: float = 0.0,
        target_price: float = 0.0,
    ) -> Dict[str, Any]:
        """Places a live order via Dhan HQ API."""
        if not self.is_broker_connected:
            return {"status": "error", "message": "Broker not connected. Falling back to paper trading."}

        headers = {
            "access-token": self.dhan_access_token,
            "client-id": self.dhan_client_id,
            "Content-Type": "application/json",
        }
        corr_id = f"CT-{int(time.time())}-{strike}{option_type}"
        payload = {
            "dhanClientId": self.dhan_client_id,
            "correlationId": corr_id,
            "transactionType": action.upper(),
            "exchangeSegment": "NSE_FNO",
            "productType": "INTRADAY",
            "orderType": "MARKET" if price <= 0 else "LIMIT",
            "validity": "DAY",
            "securityId": str(strike),
            "quantity": quantity,
            "price": price if price > 0 else 0.0,
            "triggerPrice": sl_price if sl_price > 0 else 0.0,
            "disclosedQuantity": 0,
            "afterMarketOrder": False,
        }
        try:
            with httpx.Client(timeout=12.0) as client:
                resp = client.post(f"{self.base_url}/orders", json=payload, headers=headers)
                if resp.status_code in (200, 201):
                    res_data = resp.json()
                    order_id = res_data.get("orderId", corr_id)
                    return {
                        "status": "ok",
                        "broker": "Dhan HQ",
                        "order_id": order_id,
                        "data": res_data,
                    }
                else:
                    logger.warning("Dhan order placement failed HTTP %d: %s", resp.status_code, resp.text)
                    return {"status": "error", "message": f"Dhan error ({resp.status_code}): {resp.text}"}
        except Exception as ex:
            logger.warning("Dhan order network error: %s", ex)
            return {"status": "error", "message": f"Broker connection error: {ex}"}

    def execute_chart_trade(
        self,
        symbol: str,
        setup_type: str,
        entry_spot: float,
        target_spot: float,
        sl_spot: float,
        lots: int = 1,
        mode: str = "AUTO",
        screenshot_base64: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Executes a trade placed visually on the chart:
        1. Derives strike (ATM), option type (CE/PE), and delta-adjusted SL/Target points.
        2. Saves chart screenshot PNG to disk.
        3. Routes to Broker (if connected and requested) or Paper Trading Simulator.
        4. Logs to SQLite and log file.
        5. Sends instant Telegram notification with attached screenshot.
        """
        is_bank = "BANK" in symbol.upper()
        step = 100 if is_bank else 50
        lot_size = 30 if is_bank else 65
        qty = lots * lot_size

        is_long = setup_type.upper() == "LONG"
        option_type = "CE" if is_long else "PE"
        strike = int(round(entry_spot / step) * step)

        # Estimate option premium from spot or option chain
        est_premium = 120.0
        try:
            from nifty_trader.market_data.option_chain_service import get_option_chain_service
            ocs = get_option_chain_service(self.root_dir)
            chain = ocs.fetch_live_chain_from_niftytrader(symbol)
            if chain and "opDatas" in chain:
                for row in chain["opDatas"]:
                    if int(row.get("strike_price", 0)) == strike:
                        est_premium = float(row.get("ce_ltp" if is_long else "pe_ltp", 120.0))
                        break
        except Exception:
            pass

        # Risk parameters
        target_pts = abs(target_spot - entry_spot)
        sl_pts = abs(entry_spot - sl_spot)
        rr_ratio = round(target_pts / max(1.0, sl_pts), 2)
        rr_str = f"1 : {rr_ratio}"

        # Option points approx (Delta 0.50)
        opt_sl_pts = max(5.0, round(sl_pts * 0.50, 1))
        opt_target_pts = max(10.0, round(target_pts * 0.50, 1))

        trade_id = f"CT-{int(time.time())}-{strike}{option_type}"
        now_dt = datetime.now(IST)
        created_at_str = now_dt.strftime("%Y-%m-%d %H:%M:%S IST")

        # Save Screenshot PNG from Base64
        screenshot_path = None
        if screenshot_base64:
            try:
                shots_dir = self.root_dir / "data" / "browser" / "screenshots"
                shots_dir.mkdir(parents=True, exist_ok=True)
                raw_b64 = screenshot_base64
                if "," in raw_b64:
                    raw_b64 = raw_b64.split(",", 1)[1]
                img_data = base64.b64decode(raw_b64)
                file_name = f"chart_trade_{symbol}_{strike}{option_type}_{int(time.time())}.png"
                target_file = shots_dir / file_name
                target_file.write_bytes(img_data)
                screenshot_path = str(target_file)
                logger.info("Saved chart trade screenshot to %s", screenshot_path)
            except Exception as ss_err:
                logger.warning("Could not save screenshot base64: %s", ss_err)

        # Fallback to latest screenshot if none saved from canvas
        if not screenshot_path:
            shots_dir = self.root_dir / "data" / "browser" / "screenshots"
            if shots_dir.exists():
                existing = sorted(shots_dir.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
                if existing:
                    screenshot_path = str(existing[0])

        # Determine Destination Route
        exec_mode = mode.upper()
        route_to_broker = False
        if exec_mode == "BROKER":
            route_to_broker = True
        elif exec_mode == "AUTO":
            route_to_broker = self.is_broker_connected

        broker_name = "Paper Trading Simulator"
        broker_order_id = ""
        exec_status = "FILLED"

        if route_to_broker and self.is_broker_connected:
            broker_res = self.place_broker_order(
                symbol=symbol,
                strike=strike,
                option_type=option_type,
                action="BUY",
                quantity=qty,
                price=0.0,
                sl_price=max(0.05, round(est_premium - opt_sl_pts, 2)),
                target_price=round(est_premium + opt_target_pts, 2),
            )
            if broker_res.get("status") == "ok":
                broker_name = "Dhan HQ"
                broker_order_id = str(broker_res.get("order_id", ""))
                logger.info("Executed chart trade LIVE on Dhan HQ: %s", broker_order_id)
            else:
                logger.warning("Broker execution failed; falling back to Paper Simulator: %s", broker_res.get("message"))
                route_to_broker = False

        if not route_to_broker:
            # Execute into Option Paper Simulator
            try:
                from nifty_trader.market_data.option_chain_service import get_option_chain_service
                ocs = get_option_chain_service(self.root_dir)
                sim_res = ocs.execute_option_chain_paper_trade(
                    symbol=symbol,
                    strike=strike,
                    option_type=option_type,
                    lots=lots,
                    premium=est_premium,
                    sl_points=opt_sl_pts,
                    target_points=opt_target_pts,
                    trailing_sl=True,
                    trail_step=round(opt_sl_pts * 0.5, 1),
                    action="BUY",
                )
                if sim_res.get("status") == "ok":
                    trade_id = sim_res.get("trade_id", trade_id)
                broker_name = "Paper Trading Simulator"
            except Exception as sim_err:
                logger.warning("Error executing into paper simulator: %s", sim_err)

        # Audit Logging to text file
        log_dir = self.root_dir / "data" / "paper_trading"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "chart_trades.log"
        log_entry = (
            f"[{created_at_str}] 🚀 CHART TRADE: {setup_type.upper()} | {symbol} {strike} {option_type} | "
            f"Lots: {lots} ({qty} qty) | Entry Spot: ₹{entry_spot:,.2f} | Target Spot: ₹{target_spot:,.2f} (+{target_pts:,.2f} pts) | "
            f"SL Spot: ₹{sl_spot:,.2f} (-{sl_pts:,.2f} pts) | R:R: {rr_str} | Est Prem: ₹{est_premium:.2f} | "
            f"Route: {broker_name} | ID: {trade_id} | Screenshot: {Path(screenshot_path).name if screenshot_path else 'None'}\n"
        )
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(log_entry)
        except Exception as log_err:
            logger.warning("Could not write to chart_trades.log: %s", log_err)

        # Persistence to SQLite
        db_path = log_dir / "paper_trades.db"
        try:
            conn = sqlite3.connect(str(db_path), timeout=5.0)
            with conn:
                conn.execute("""
                    INSERT OR REPLACE INTO chart_trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    trade_id, symbol, setup_type.upper(), option_type, strike,
                    entry_spot, target_spot, sl_spot, est_premium,
                    lots, qty, rr_str, "BROKER_LIVE" if route_to_broker else "PAPER",
                    broker_name, broker_order_id, screenshot_path or "",
                    exec_status, created_at_str, None, None, None
                ))
            conn.close()
        except Exception as db_err:
            logger.warning("Could not insert to chart_trades table: %s", db_err)

        trade_info = {
            "trade_id": trade_id,
            "symbol": symbol,
            "setup_type": setup_type.upper(),
            "option_type": option_type,
            "strike": strike,
            "entry_spot": entry_spot,
            "target_spot": target_spot,
            "sl_spot": sl_spot,
            "target_points": target_pts,
            "sl_points": sl_pts,
            "risk_reward": rr_str,
            "premium": est_premium,
            "lots": lots,
            "qty": qty,
            "mode": "BROKER LIVE" if route_to_broker else "PAPER SIMULATOR",
            "broker": broker_name,
            "broker_order_id": broker_order_id,
            "screenshot_path": screenshot_path,
            "created_at_ist": created_at_str,
        }

        # Dispatch Telegram Notification with attached chart screenshot
        try:
            from nifty_trader.notifications.telegram_service import get_telegram_service
            tele = get_telegram_service(self.root_dir)
            tele.send_chart_trade_executed_alert(trade_info, photo_path=screenshot_path)
        except Exception as tele_err:
            logger.warning("Could not dispatch Telegram chart trade alert: %s", tele_err)

        return {
            "status": "ok",
            "trade": trade_info,
            "message": f"Successfully executed {setup_type.upper()} ({symbol} {strike} {option_type}) on {broker_name}!",
        }

    def list_chart_trades(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Returns recent chart trades from SQLite."""
        db_path = self.root_dir / "data" / "paper_trading" / "paper_trades.db"
        if not db_path.exists():
            return []
        try:
            conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True, timeout=5.0)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM chart_trades ORDER BY created_at DESC LIMIT ?", (limit,))
            rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return rows
        except Exception:
            return []


def get_broker_service(root_dir: Optional[Path] = None) -> BrokerService:
    """Convenience accessor for BrokerService singleton."""
    return BrokerService.get_instance(root_dir=root_dir)
