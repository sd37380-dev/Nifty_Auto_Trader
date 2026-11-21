"""
Telegram Notification & Alert Engine for NIFTY Autonomous Trader.

Handles:
1. Real-time Telegram alerts for level touch / breakout events.
2. Trade Intent alerts with full cognitive reasoning ("Why system takes trade")
   and a 15-minute countdown before automatic execution.
3. Automated paper trade execution following the 15-minute countdown.
4. Breaking Indian market news alerts (impact score >= 4 or is_important = 1).
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Callable, Dict, List, Optional
import urllib.parse
import httpx

logger = logging.getLogger(__name__)

# Indian Standard Time offset UTC+5:30
IST = timezone(timedelta(hours=5, minutes=30))


class TelegramNotificationService:
    """Manages asynchronous Telegram message delivery and alerts."""

    _instance: Optional["TelegramNotificationService"] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, root_dir: Optional[Path] = None) -> "TelegramNotificationService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(root_dir=root_dir)
        return cls._instance

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent.parent
        self.bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        self.chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

        self._executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="telegram_alert")
        self._sent_news_ids = set()
        self._load_sent_news_ids()
        # News alerts to Telegram disabled by default (only trade alerts sent)
        self.enable_news_alerts = os.environ.get("TELEGRAM_ENABLE_NEWS_ALERTS", "false").lower() in ("true", "1", "yes")

    @property
    def is_configured(self) -> bool:
        """Checks if Telegram bot token and chat ID are both present."""
        return bool(self.bot_token and self.chat_id)

    def set_credentials(self, bot_token: str, chat_id: str) -> None:
        """Dynamically updates credentials (and saves to local .env if possible)."""
        self.bot_token = bot_token.strip()
        self.chat_id = chat_id.strip()
        os.environ["TELEGRAM_BOT_TOKEN"] = self.bot_token
        os.environ["TELEGRAM_CHAT_ID"] = self.chat_id

        # Attempt to persist to .env
        env_file = self.root_dir / ".env"
        try:
            if env_file.exists():
                lines = env_file.read_text(encoding="utf-8").splitlines()
                updated_token = False
                updated_chat = False
                new_lines = []
                for line in lines:
                    if line.startswith("TELEGRAM_BOT_TOKEN="):
                        new_lines.append(f"TELEGRAM_BOT_TOKEN={self.bot_token}")
                        updated_token = True
                    elif line.startswith("TELEGRAM_CHAT_ID="):
                        new_lines.append(f"TELEGRAM_CHAT_ID={self.chat_id}")
                        updated_chat = True
                    else:
                        new_lines.append(line)
                if not updated_token:
                    new_lines.append(f"TELEGRAM_BOT_TOKEN={self.bot_token}")
                if not updated_chat:
                    new_lines.append(f"TELEGRAM_CHAT_ID={self.chat_id}")
                env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        except Exception as e:
            logger.warning("Could not persist Telegram credentials to .env: %s", e)

    def get_status(self) -> Dict[str, Any]:
        """Returns Telegram configuration status for UI and diagnostics."""
        masked_token = (
            f"{self.bot_token[:6]}...{self.bot_token[-4:]}"
            if len(self.bot_token) > 10
            else ("SET" if self.bot_token else "NOT_SET")
        )
        return {
            "configured": self.is_configured,
            "bot_token_set": bool(self.bot_token),
            "chat_id_set": bool(self.chat_id),
            "bot_token_masked": masked_token,
            "masked_token": masked_token,
            "chat_id": self.chat_id,
        }

    def _load_sent_news_ids(self) -> None:
        """Loads recently alerted news IDs to avoid duplicate alerts."""
        db_path = self.root_dir / "data" / "market" / "market_news.db"
        if not db_path.exists():
            return
        try:
            conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True, timeout=5.0)
            try:
                cur = conn.execute("SELECT id FROM market_news ORDER BY published_at DESC LIMIT 50")
                for r in cur.fetchall():
                    self._sent_news_ids.add(r[0])
            finally:
                conn.close()
        except Exception:
            pass

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Sends an HTML formatted message to Telegram asynchronously."""
        if not self.is_configured:
            logger.debug("Telegram not configured; skipping dispatch: %s", text[:80])
            return False

        def _worker():
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            }
            try:
                with httpx.Client(timeout=10.0) as client:
                    resp = client.post(url, json=payload)
                    if resp.status_code == 200:
                        logger.info("Telegram notification sent successfully.")
                        return True
                    else:
                        logger.warning("Telegram send failed (HTTP %d): %s", resp.status_code, resp.text)
                        return False
            except Exception as ex:
                logger.warning("Telegram network error: %s", ex)
                return False

        self._executor.submit(_worker)
        return True

    def send_photo(self, photo_path_or_bytes: Any, caption: str = "", parse_mode: str = "HTML") -> bool:
        """Sends a photo with optional HTML caption to Telegram asynchronously."""
        if not self.is_configured:
            logger.debug("Telegram not configured; skipping photo dispatch: %s", caption[:60])
            return False

        def _worker():
            url = f"https://api.telegram.org/bot{self.bot_token}/sendPhoto"
            try:
                safe_caption = caption[:1024] if caption else ""
                data = {
                    "chat_id": self.chat_id,
                    "caption": safe_caption,
                    "parse_mode": parse_mode,
                }
                with httpx.Client(timeout=25.0) as client:
                    if isinstance(photo_path_or_bytes, (str, Path)):
                        p = Path(photo_path_or_bytes)
                        if not p.exists():
                            logger.warning("Telegram sendPhoto: file not found: %s", p)
                            self.send_message(caption, parse_mode=parse_mode)
                            return False
                        with open(p, "rb") as f:
                            files = {"photo": (p.name, f.read(), "image/png")}
                            resp = client.post(url, data=data, files=files)
                    elif isinstance(photo_path_or_bytes, bytes):
                        files = {"photo": ("chart_screenshot.png", photo_path_or_bytes, "image/png")}
                        resp = client.post(url, data=data, files=files)
                    else:
                        self.send_message(caption, parse_mode=parse_mode)
                        return False

                    if resp.status_code == 200:
                        logger.info("Telegram photo sent successfully.")
                        return True
                    else:
                        logger.warning("Telegram sendPhoto failed (HTTP %d): %s", resp.status_code, resp.text)
                        self.send_message(caption, parse_mode=parse_mode)
                        return False
            except Exception as ex:
                logger.warning("Telegram sendPhoto error: %s", ex)
                self.send_message(caption, parse_mode=parse_mode)
                return False

        self._executor.submit(_worker)
        return True

    def send_chart_trade_executed_alert(
        self,
        trade_info: Dict[str, Any],
        photo_path: Optional[str] = None,
    ) -> bool:
        """Sends an instant alert when a visual Long/Short chart trade is executed."""
        now_ist = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        symbol = trade_info.get("symbol", "NIFTY")
        setup_type = trade_info.get("setup_type", "LONG").upper()
        strike = trade_info.get("strike", 0)
        option_type = trade_info.get("option_type", "CE")
        entry_spot = float(trade_info.get("entry_spot", 0.0))
        target_spot = float(trade_info.get("target_spot", 0.0))
        sl_spot = float(trade_info.get("sl_spot", 0.0))
        premium = float(trade_info.get("premium", 0.0))
        lots = int(trade_info.get("lots", 1))
        qty = int(trade_info.get("qty", lots * (30 if "BANK" in symbol else 65)))
        rr = trade_info.get("risk_reward", "1 : 2.0")
        mode = trade_info.get("mode", "PAPER SIMULATOR")
        trade_id = trade_info.get("trade_id", "")
        broker_order_id = trade_info.get("broker_order_id", "")

        is_long = setup_type == "LONG" or option_type == "CE"
        dir_badge = "🟢 LONG SETUP (BUY CALL - CE)" if is_long else "🔴 SHORT SETUP (BUY PUT - PE)"

        target_pts = abs(target_spot - entry_spot)
        sl_pts = abs(entry_spot - sl_spot)

        mode_badge = f"🏦 <b>LIVE BROKER (Dhan HQ)</b> | Order: <code>{broker_order_id}</code>" if "BROKER" in mode.upper() else "📄 <b>PAPER TRADING SIMULATOR</b>"

        msg = (
            f"🚀 <b>[CHART TRADE EXECUTED]</b> 🚀\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 <b>Strategy:</b> <b>{dir_badge}</b>\n"
            f"📊 <b>Option Contract:</b> <b>{symbol} {strike} {option_type}</b>\n"
            f"💵 <b>Est. Premium:</b> ₹{premium:.2f} | <b>Qty:</b> {lots} Lot ({qty} Qty)\n\n"
            f"📍 <b>Visual Chart Levels:</b>\n"
            f"   • Entry Level: <b>₹{entry_spot:,.2f}</b>\n"
            f"   • Profit Target: <b>₹{target_spot:,.2f}</b> (+{target_pts:,.2f} pts)\n"
            f"   • Stop Loss: <b>₹{sl_spot:,.2f}</b> (-{sl_pts:,.2f} pts)\n"
            f"   • Risk : Reward: <b>{rr}</b>\n\n"
            f"⚙️ <b>Execution Route:</b>\n"
            f"   {mode_badge}\n"
            f"🆔 <b>Trade ID:</b> <code>{trade_id}</code>\n"
            f"⏰ <b>Execution Time:</b> {now_ist}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        if photo_path and Path(photo_path).exists():
            return self.send_photo(photo_path, caption=msg)
        return self.send_message(msg)

    def send_trade_closed_alert(
        self,
        symbol: str,
        strike: int,
        option_type: str,
        entry_premium: float,
        exit_premium: float,
        exit_reason: str,
        net_pnl: float,
        pnl_pct: float,
        lots: int = 1,
        qty: int = 65,
        trade_id: str = "",
        rule_name: str = "",
        photo_path: Optional[str] = None,
    ) -> bool:
        """Sends an instant alert when a trade exits due to Stop Loss, Target, or Manual closure."""
        now_ist = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        reason_upper = exit_reason.upper()

        if "TARGET" in reason_upper:
            header_icon = "🎯 🏆"
            status_title = "PROFIT TARGET ACHIEVED!"
            pnl_badge = f"🟢 PROFIT: +₹{abs(net_pnl):,.2f} (+{abs(pnl_pct):.1f}%)"
        elif "STOP" in reason_upper:
            header_icon = "🛑 🛡️"
            status_title = "STOP LOSS TRIGGERED"
            pnl_badge = f"🔴 LOSS: -₹{abs(net_pnl):,.2f} (-{abs(pnl_pct):.1f}%)"
        else:
            header_icon = "🏁"
            status_title = f"POSITION CLOSED ({exit_reason})"
            sign = "+" if net_pnl >= 0 else "-"
            pnl_badge = f"{'🟢' if net_pnl >= 0 else '🔴'} NET P&L: {sign}₹{abs(net_pnl):,.2f} ({pnl_pct:+.1f}%)"

        pts_diff = exit_premium - entry_premium
        msg = (
            f"{header_icon} <b>[{status_title}]</b> {header_icon}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Contract:</b> <b>{symbol} {strike} {option_type}</b>\n"
            f"💰 <b>Net P&L:</b> <b>{pnl_badge}</b>\n\n"
            f"📈 <b>Trade Metrics:</b>\n"
            f"   • Entry Fill: ₹{entry_premium:.2f}\n"
            f"   • Exit Fill: ₹{exit_premium:.2f}\n"
            f"   • Points P&L: {pts_diff:+.2f} pts\n"
            f"   • Lots: {lots} ({qty} Qty)\n"
            f"   • Exit Reason: <code>{exit_reason}</code>\n"
            f"   • Strategy: {rule_name}\n"
            f"🆔 <b>Trade ID:</b> <code>{trade_id}</code>\n"
            f"⏰ <b>Closed At:</b> {now_ist}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        if photo_path and Path(photo_path).exists():
            return self.send_photo(photo_path, caption=msg)
        return self.send_message(msg)

    def send_test_message(self) -> Dict[str, Any]:
        """Synchronous ping to verify token and chat ID."""
        if not self.is_configured:
            return {"status": "error", "message": "Bot token or Chat ID is not configured."}

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        now_ist = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        test_msg = (
            "🔔 <b>[NIFTY AUTONOMOUS TRADER]</b> — Telegram Bot Connected!\n\n"
            "✅ <i>Telegram notification updater is online and verified.</i>\n\n"
            f"⏰ <b>Timestamp:</b> {now_ist}\n"
            "📡 <b>Alerts Enabled:</b>\n"
            "• Level Reach & Breakout Alerts\n"
            "• 15-Minute Trade Intent & Auto-Execution\n"
            "• Trade Confirmations & Execution Status\n"
            "• <i>(Market News: Disabled — Only Trade Alerts Active)</i>\n\n"
            "🚀 <i>Running on Render / Local Engine</i>"
        )
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, json={
                    "chat_id": self.chat_id,
                    "text": test_msg,
                    "parse_mode": "HTML",
                })
                if resp.status_code == 200:
                    return {"status": "ok", "message": "Test alert sent to Telegram successfully!"}
                else:
                    return {"status": "error", "message": f"Telegram API error ({resp.status_code}): {resp.text}"}
        except Exception as ex:
            return {"status": "error", "message": f"Network exception: {ex}"}

    def send_level_breakout_alert(
        self,
        instrument: str,
        current_spot: float,
        level_price: float,
        condition: str,
        trigger_reason: str,
        action_note: str = "",
    ) -> bool:
        """Sends an instant alert when spot reaches or breaks a key level."""
        now_ist = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        direction_icon = "🟢" if "ABOVE" in condition.upper() else ("🔴" if "BELOW" in condition.upper() else "🟡")
        msg = (
            f"🔔 <b>[PRICE LEVEL BREAKOUT ALERT]</b> {direction_icon}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📍 <b>Instrument:</b> {instrument}\n"
            f"⚡ <b>Condition:</b> <code>{condition}</code>\n"
            f"🎯 <b>Key Level:</b> ₹{level_price:,.2f}\n"
            f"📡 <b>Current Spot:</b> <b>₹{current_spot:,.2f}</b>\n"
            f"📝 <b>Trigger Reason:</b> {trigger_reason}\n"
            f"⏰ <b>Time:</b> {now_ist}\n"
        )
        if action_note:
            msg += f"\n💡 <b>System Action:</b> {action_note}\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━"
        return self.send_message(msg)

    def send_trade_intent_alert(self, trade_info: Dict[str, Any]) -> bool:
        """
        Sends an alert when trade criteria match.
        Announces the 15-minute countdown and explains WHY the system is taking this trade.
        """
        symbol = trade_info.get("symbol", "NIFTY")
        strike = trade_info.get("strike", 0)
        option_type = trade_info.get("option_type", "CE")
        premium = trade_info.get("premium", 0.0)
        spot_price = trade_info.get("spot_price", 0.0)
        sl_price = trade_info.get("sl_price", 0.0)
        sl_points = trade_info.get("sl_points", 20.0)
        target_price = trade_info.get("target_price", 0.0)
        target_points = trade_info.get("target_points", 40.0)
        lots = trade_info.get("lots", 1)
        qty = trade_info.get("qty", lots * 65)
        reasoning = trade_info.get("reasoning", "Technical confirmation on 15M chart.")
        armed_at = trade_info.get("armed_at_ist", datetime.now(IST).strftime("%H:%M:%S IST"))
        execute_at = trade_info.get("execute_at_ist", (datetime.now(IST) + timedelta(minutes=15)).strftime("%H:%M:%S IST"))
        pending_id = trade_info.get("pending_id", "")

        type_badge = "🟢 BUY CALL (CE)" if option_type == "CE" else "🔴 BUY PUT (PE)"

        msg = (
            f"🚨 <b>[PROPOSED TRADE ALERT] — 15-MIN COUNTDOWN ARMED</b> 🚨\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Target Contract:</b> <b>{symbol} {strike} {option_type}</b> ({type_badge})\n"
            f"💰 <b>Estimated Premium:</b> ₹{premium:.2f} | <b>Spot:</b> ₹{spot_price:,.2f}\n"
            f"🛡️ <b>Risk Parameters:</b>\n"
            f"   • Stop Loss: ₹{sl_price:.2f} (-{sl_points:.1f} pts)\n"
            f"   • Target: ₹{target_price:.2f} (+{target_points:.1f} pts)\n"
            f"   • Lots: {lots} ({qty} Qty)\n\n"
            f"🧠 <b>WHY THE SYSTEM IS TAKING THIS TRADE:</b>\n"
            f"<i>{reasoning}</i>\n\n"
            f"⏱️ <b>15-MINUTE CONFIRMATION COUNTDOWN:</b>\n"
            f"• Armed At: {armed_at}\n"
            f"• <b>Auto-Execute At: {execute_at} (in 15 min)</b>\n"
            "• <i>System is waiting 15 minutes to verify candle close stability and ensure no adverse market news occurs before firing.</i>\n"
            f"• <b>Cancel ID:</b> <code>{pending_id}</code> (Aborting available via Dashboard)\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        return self.send_message(msg)

    def send_trade_executed_alert(self, trade_info: Dict[str, Any]) -> bool:
        """Sends an alert once the 15-minute countdown elapses and order executes."""
        symbol = trade_info.get("symbol", "NIFTY")
        strike = trade_info.get("strike", 0)
        option_type = trade_info.get("option_type", "CE")
        premium = trade_info.get("premium", 0.0)
        sl_price = trade_info.get("sl_price", 0.0)
        target_price = trade_info.get("target_price", 0.0)
        lots = trade_info.get("lots", 1)
        qty = trade_info.get("qty", lots * 65)
        trade_id = trade_info.get("trade_id", "")
        now_ist = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

        msg = (
            "⚡ <b>[TRADE AUTO-EXECUTED] — 15-MIN TIMER COMPLETED</b> ⚡\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ <b>Position Entered:</b> <b>{symbol} {strike} {option_type}</b>\n"
            f"💵 <b>Fill Premium:</b> ₹{premium:.2f} (Qty: {qty})\n"
            f"🛡️ <b>Live Stop Loss:</b> ₹{sl_price:.2f}\n"
            f"🎯 <b>Live Target:</b> ₹{target_price:.2f}\n"
            f"🆔 <b>Trade ID:</b> <code>{trade_id}</code>\n"
            f"⏰ <b>Execution Time:</b> {now_ist}\n"
            "📈 <b>Status:</b> Active in Option Paper Simulator & Real-time MTM Tracking\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        return self.send_message(msg)

    def send_trade_cancelled_alert(self, trade_info: Dict[str, Any], reason: str = "User Cancelled") -> bool:
        """Sends an alert if a pending 15-min countdown trade is cancelled."""
        symbol = trade_info.get("symbol", "NIFTY")
        strike = trade_info.get("strike", 0)
        option_type = trade_info.get("option_type", "CE")
        pending_id = trade_info.get("pending_id", "")
        now_ist = datetime.now(IST).strftime("%H:%M:%S IST")

        msg = (
            "🛑 <b>[PROPOSED TRADE CANCELLED]</b> 🛑\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Contract: <b>{symbol} {strike} {option_type}</b>\n"
            f"Order ID: <code>{pending_id}</code>\n"
            f"Cancellation Reason: <b>{reason}</b>\n"
            f"Time: {now_ist}\n"
            "<i>No trade was executed in the simulator.</i>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        return self.send_message(msg)

    def send_big_news_alert(self, item: Dict[str, Any]) -> bool:
        """
        Sends an instant alert for high impact / important Indian market news.
        Disabled: Only trade alerts are sent via Telegram. Can be overridden with TELEGRAM_ENABLE_NEWS_ALERTS=true.
        """
        if not getattr(self, "enable_news_alerts", False):
            logger.debug("Telegram news alert skipped: news alerts disabled (only trade alerts active).")
            return False

        news_id = item.get("id", "")
        if news_id and news_id in self._sent_news_ids:
            return False  # Already dispatched

        title = item.get("title", "")
        summary = item.get("summary", "")
        source = item.get("source", "Market Wire")
        category = item.get("category", "MARKET_IMPACT")
        impact_type = item.get("impact_type", "VOLATILE")
        impact_score = item.get("impact_score", 4)
        market_effect = item.get("market_effect", "Watch for volatility spikes.")
        published_at = item.get("published_at", "")

        if news_id:
            self._sent_news_ids.add(news_id)

        impact_emoji = {
            "BULLISH": "🟢 BULLISH",
            "BEARISH": "🔴 BEARISH",
            "VOLATILE": "⚡ HIGH VOLATILITY",
            "NEUTRAL": "⚪ NEUTRAL",
        }.get(impact_type.upper(), "⚡ VOLATILE")

        score_stars = "⭐" * min(impact_score, 5)

        msg = (
            "🚨 <b>[BREAKING INDIAN MARKET NEWS ALERT]</b> 🚨\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📰 <b>{title}</b>\n\n"
            f"📌 <b>Category:</b> <code>{category}</code>\n"
            f"💥 <b>Impact Bias:</b> <b>{impact_emoji}</b> ({score_stars} {impact_score}/5)\n"
            f"🏢 <b>Source:</b> {source} | {published_at}\n\n"
            f"💡 <b>Market Effect:</b>\n"
            f"<b>{market_effect}</b>\n\n"
            f"📝 <b>Summary:</b>\n"
            f"<i>{summary[:280] + '...' if len(summary) > 280 else summary}</i>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        return self.send_message(msg)


class PendingTradeManager:
    """
    Manages proposed trades waiting during the 15-minute confirmation countdown.
    Executes trades automatically after 15 minutes unless cancelled.
    """

    _instance: Optional["PendingTradeManager"] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, root_dir: Optional[Path] = None) -> "PendingTradeManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(root_dir=root_dir)
        return cls._instance

    def __init__(self, root_dir: Optional[Path] = None, countdown_seconds: int = 900):
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent.parent
        self.countdown_seconds = countdown_seconds  # 15 minutes = 900 seconds
        self.pending_trades: Dict[str, Dict[str, Any]] = {}
        self._timers: Dict[str, threading.Thread] = {}
        self._cancel_events: Dict[str, threading.Event] = {}

    def arm_trade(
        self,
        symbol: str,
        strike: int,
        option_type: str,
        lots: int = 1,
        premium: float = 0.0,
        spot_price: float = 0.0,
        sl_points: float = 20.0,
        target_points: float = 40.0,
        reasoning: str = "Technical breakout confirmation on 15M chart.",
        custom_countdown: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Arms a trade for automatic execution after a 15-minute countdown.
        Dispatches the initial Telegram notification explaining the rationale.
        """
        pending_id = f"PT-{int(time.time())}-{strike}{option_type}"
        countdown = custom_countdown if custom_countdown is not None else self.countdown_seconds
        now_dt = datetime.now(IST)
        execute_dt = now_dt + timedelta(seconds=countdown)

        sl_price = max(0.05, round(premium - sl_points, 2))
        target_price = round(premium + target_points, 2)

        trade_info = {
            "pending_id": pending_id,
            "symbol": symbol.upper(),
            "strike": strike,
            "option_type": option_type.upper(),
            "lots": lots,
            "qty": lots * 65,
            "premium": premium,
            "spot_price": spot_price,
            "sl_points": sl_points,
            "sl_price": sl_price,
            "target_points": target_points,
            "target_price": target_price,
            "reasoning": reasoning,
            "status": "ARMED_15M",
            "armed_timestamp": now_dt.timestamp(),
            "armed_at_ist": now_dt.strftime("%Y-%m-%d %H:%M:%S IST"),
            "execute_timestamp": execute_dt.timestamp(),
            "execute_at_ist": execute_dt.strftime("%Y-%m-%d %H:%M:%S IST"),
            "countdown_seconds": countdown,
        }

        self.pending_trades[pending_id] = trade_info
        cancel_evt = threading.Event()
        self._cancel_events[pending_id] = cancel_evt

        # Send Telegram Intent Alert (if countdown > 0)
        try:
            tele = get_telegram_service(self.root_dir)
            if countdown > 0:
                tele.send_trade_intent_alert(trade_info)
        except Exception as e:
            logger.warning("Error dispatching Telegram trade intent: %s", e)

        # Immediate Execution: If countdown is 0, execute instantly without waiting
        if countdown <= 0:
            logger.info("⚡ Immediate execution mode active (countdown=0). Executing %s instantly.", pending_id)
            self._execute_pending_trade(pending_id)
            return trade_info

        # Launch countdown thread
        def _countdown_worker():
            start_t = time.time()
            while time.time() - start_t < countdown:
                if cancel_evt.is_set():
                    logger.info("Pending trade %s cancelled before execution.", pending_id)
                    return
                time.sleep(1.0)

            # Timer completed without cancellation -> Auto-execute trade!
            if not cancel_evt.is_set():
                self._execute_pending_trade(pending_id)

        worker = threading.Thread(target=_countdown_worker, daemon=True, name=f"timer_{pending_id}")
        self._timers[pending_id] = worker
        worker.start()

        logger.info(
            "⚡ Trade %s ARMED for 15-minute auto-execution at %s IST (%s %d %s)",
            pending_id, trade_info["execute_at_ist"], symbol, strike, option_type
        )
        return trade_info

    def cancel_trade(self, pending_id: str, reason: str = "Cancelled by user via dashboard") -> bool:
        """Cancels an armed trade before its 15-minute timer finishes."""
        if pending_id not in self.pending_trades:
            return False

        trade = self.pending_trades[pending_id]
        if trade["status"] != "ARMED_15M":
            return False

        trade["status"] = "CANCELLED"
        trade["cancelled_at_ist"] = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        trade["cancel_reason"] = reason

        evt = self._cancel_events.get(pending_id)
        if evt:
            evt.set()

        try:
            tele = get_telegram_service(self.root_dir)
            tele.send_trade_cancelled_alert(trade, reason=reason)
        except Exception as e:
            logger.warning("Error dispatching Telegram cancellation alert: %s", e)

        logger.info("🛑 Pending trade %s was successfully cancelled (%s).", pending_id, reason)
        return True

    def _execute_pending_trade(self, pending_id: str) -> None:
        """Executes the trade in SimulatorBackgroundService after 15 min."""
        if pending_id not in self.pending_trades:
            return
        trade = self.pending_trades[pending_id]
        if trade["status"] != "ARMED_15M":
            return

        trade["status"] = "EXECUTED"
        trade["executed_at_ist"] = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

        # Execute into Simulator
        try:
            from nifty_trader.market_data.option_chain_service import get_option_chain_service
            ocs = get_option_chain_service(self.root_dir)
            res = ocs.execute_option_chain_paper_trade(
                symbol=trade["symbol"],
                strike=trade["strike"],
                option_type=trade["option_type"],
                lots=trade["lots"],
                premium=trade["premium"],
                sl_points=trade["sl_points"],
                target_points=trade["target_points"],
            )
            if res.get("status") == "ok":
                trade["trade_id"] = res.get("trade_id", pending_id)
            else:
                trade["trade_id"] = pending_id
        except Exception as sim_err:
            logger.error("Could not execute pending trade in simulator: %s", sim_err)
            trade["trade_id"] = pending_id

        # Dispatch Telegram Execution Confirmation
        try:
            tele = get_telegram_service(self.root_dir)
            tele.send_trade_executed_alert(trade)
        except Exception as e:
            logger.warning("Error dispatching Telegram executed alert: %s", e)

        logger.info("🏁 15-minute countdown finished: Trade %s auto-executed into simulator.", pending_id)

    def list_pending_trades(self) -> List[Dict[str, Any]]:
        """Returns all armed and recent pending trades with remaining time."""
        now_ts = datetime.now(IST).timestamp()
        res = []
        for pid, t in sorted(self.pending_trades.items(), key=lambda x: x[1]["armed_timestamp"], reverse=True):
            rem = max(0, int(t["execute_timestamp"] - now_ts)) if t["status"] == "ARMED_15M" else 0
            t_copy = dict(t)
            t_copy["remaining_seconds"] = rem
            mins, secs = divmod(rem, 60)
            t_copy["remaining_str"] = f"{mins:02d}:{secs:02d}"
            res.append(t_copy)
        return res


def get_telegram_service(root_dir: Optional[Path] = None) -> TelegramNotificationService:
    """Convenience accessor for TelegramNotificationService singleton."""
    return TelegramNotificationService.get_instance(root_dir=root_dir)


def get_pending_trade_manager(root_dir: Optional[Path] = None) -> PendingTradeManager:
    """Convenience accessor for PendingTradeManager singleton."""
    return PendingTradeManager.get_instance(root_dir=root_dir)
