"""
Autonomous Trader Lifecycle & Process Manager.
Provides thread-safe start, stop, status query, and log monitoring
for scripts/autonomous_price_action_trader.py.

Powers:
- Option B: Telegram Bot Remote Control (!trade, !stop, !status)
- Option C: 1-Click Dashboard Web UI Start/Stop Button
- Option D: Antigravity CLI / Local execution
"""

from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))


class AutonomousTraderManager:
    """Manages the background execution of the Autonomous Price Action Trader."""

    _instance: Optional["AutonomousTraderManager"] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, root_dir: Optional[Path] = None) -> "AutonomousTraderManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(root_dir=root_dir)
        return cls._instance

    def __init__(self, root_dir: Optional[Path] = None):
        candidates = [
            root_dir,
            (root_dir / "nifty-autonomous-trader") if root_dir else None,
            Path(__file__).resolve().parent.parent.parent,
            Path("d:/AI_Trading/nifty-autonomous-trader"),
            Path(".").resolve(),
        ]
        chosen_root = None
        for c in candidates:
            if c and (c / "scripts" / "autonomous_price_action_trader.py").exists():
                chosen_root = c.resolve()
                break
        if chosen_root is None:
            chosen_root = Path(__file__).resolve().parent.parent.parent

        self.root_dir = chosen_root
        self.script_path = self.root_dir / "scripts" / "autonomous_price_action_trader.py"
        self.log_file = self.root_dir / "data" / "paper_trading" / "AUTONOMOUS_PA_VOLUME.log"
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        self.process: Optional[subprocess.Popen] = None
        self.start_time: float = 0.0
        self.last_status: str = "IDLE"
        self._proc_lock = threading.Lock()

    def _get_python_executable(self) -> str:
        """Finds active virtualenv python or system python."""
        venv_py_win = self.root_dir / "venv" / "Scripts" / "python.exe"
        venv_py_nix = self.root_dir / "venv" / "bin" / "python"
        if venv_py_win.exists():
            return str(venv_py_win)
        if venv_py_nix.exists():
            return str(venv_py_nix)
        return sys.executable

    def start_trader(self, symbol: str = "NIFTY", interval: int = 15) -> Dict[str, Any]:
        """Starts the autonomous trading engine in background."""
        with self._proc_lock:
            if self.is_running():
                return {
                    "status": "already_running",
                    "message": f"Autonomous Trader is already active (PID {self.process.pid}).",
                    "pid": self.process.pid,
                    "uptime_seconds": int(time.time() - self.start_time),
                }

            if not self.script_path.exists():
                return {"status": "error", "message": f"Script not found at {self.script_path}"}

            python_exe = self._get_python_executable()
            cmd = [
                python_exe,
                str(self.script_path),
                "--mode", "live",
                "--symbol", symbol,
                "--interval", str(interval),
            ]

            try:
                # Open log file for output redirection
                out_handle = open(self.log_file, "a", encoding="utf-8", buffering=1)
                self.process = subprocess.Popen(
                    cmd,
                    stdout=out_handle,
                    stderr=subprocess.STDOUT,
                    cwd=str(self.root_dir),
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                )
                self.start_time = time.time()
                self.last_status = "RUNNING"
                logger.info("Autonomous Price Action Trader launched with PID %d", self.process.pid)

                return {
                    "status": "ok",
                    "message": "Autonomous Price Action Trader launched successfully.",
                    "pid": self.process.pid,
                    "symbol": symbol,
                    "interval": interval,
                    "trading_mode": os.environ.get("TRADING_MODE", "PAPER"),
                }
            except Exception as ex:
                logger.error("Failed to launch Autonomous Trader: %s", ex)
                self.last_status = "ERROR"
                return {"status": "error", "message": f"Could not launch trader: {ex}"}

    def stop_trader(self) -> Dict[str, Any]:
        """Gracefully terminates the autonomous trader process."""
        with self._proc_lock:
            if not self.is_running():
                self.process = None
                return {"status": "already_stopped", "message": "Autonomous Trader is not currently running."}

            pid = self.process.pid
            try:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2.0)
                logger.info("Autonomous Trader (PID %d) stopped successfully.", pid)
            except Exception as ex:
                logger.warning("Error stopping Autonomous Trader process %d: %s", pid, ex)

            self.process = None
            self.last_status = "STOPPED"
            return {"status": "ok", "message": f"Autonomous Trader (PID {pid}) stopped successfully."}

    def is_running(self) -> bool:
        """Returns True if the autonomous trader process is currently alive."""
        if self.process is None:
            return False
        ret = self.process.poll()
        return ret is None

    def get_status(self) -> Dict[str, Any]:
        """Returns complete operational status and recent log output."""
        running = self.is_running()
        uptime = int(time.time() - self.start_time) if running and self.start_time > 0 else 0

        # Read last 25 lines of log file safely
        recent_logs = []
        if self.log_file.exists():
            try:
                with open(self.log_file, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                    recent_logs = [line.rstrip() for line in lines[-25:]]
            except Exception as e:
                recent_logs = [f"Error reading logs: {e}"]

        return {
            "status": "ok",
            "is_running": running,
            "pid": self.process.pid if running else None,
            "uptime_seconds": uptime,
            "uptime_formatted": str(timedelta(seconds=uptime)),
            "trading_mode": os.environ.get("TRADING_MODE", "PAPER"),
            "log_path": str(self.log_file),
            "recent_logs": recent_logs,
            "last_status": "RUNNING" if running else self.last_status,
        }


def get_trader_manager(root_dir: Optional[Path] = None) -> AutonomousTraderManager:
    return AutonomousTraderManager.get_instance(root_dir=root_dir)
