"""
Antigravity Bridge Manager for NIFTY Autonomous Trader.
Enables bidirectional communication between the web dashboard chat box (on Render or Localhost)
and the Antigravity AI assistant running on the user's computer.

When the local Antigravity bridge is active:
- User questions from the web chat are routed straight to Antigravity.
- Antigravity queries local files, indicators, paper trades, and historical SQLite databases.
- The comprehensive response is pushed back to the web chat box in real time.
- If the bridge is inactive or times out, the web dashboard seamlessly falls back to cloud Copilot.
"""

from collections import deque
from datetime import datetime, timezone
import logging
import threading
import time
from typing import Any, Dict, List, Optional
import uuid

logger = logging.getLogger(__name__)


class AntigravityBridgeManager:
    """Singleton bridge manager coordinating web chat requests and local Antigravity responses."""

    _instance: Optional["AntigravityBridgeManager"] = None
    _lock = threading.Lock()

    def __init__(self):
        self.pending_jobs: deque = deque()
        self.active_jobs: Dict[str, Dict[str, Any]] = {}
        self.jobs_lock = threading.Lock()
        self.condition = threading.Condition(self.jobs_lock)
        self.last_heartbeat: float = 0.0
        self.agent_name: str = "Antigravity Local Bridge"
        self.secret_token: str = "nifty-antigravity-secure-bridge-2026"

    @classmethod
    def get_instance(cls) -> "AntigravityBridgeManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = AntigravityBridgeManager()
            return cls._instance

    def register_heartbeat(self, agent_name: str = "Antigravity Local Bridge") -> None:
        """Records a heartbeat from the local bridge worker."""
        self.last_heartbeat = time.time()
        self.agent_name = agent_name

    def is_online(self) -> bool:
        """Returns True if the bridge client has sent a heartbeat within the last 25 seconds."""
        return (time.time() - self.last_heartbeat) < 25.0

    def get_status(self) -> Dict[str, Any]:
        """Returns current bridge health and status."""
        online = self.is_online()
        sec_ago = int(time.time() - self.last_heartbeat) if self.last_heartbeat > 0 else 999999
        return {
            "online": online,
            "agent": self.agent_name if online else "Offline",
            "last_seen_sec_ago": sec_ago,
            "pending_count": len(self.pending_jobs),
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        }

    def enqueue_message(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
        context: Optional[Dict[str, Any]] = None,
        timeout: float = 6.0,
    ) -> Optional[Dict[str, Any]]:
        """
        Dispatches a user message to the bridge queue and blocks until
        the local Antigravity client responds or the timeout expires.
        """
        if not self.is_online():
            return None

        job_id = f"job-{uuid.uuid4().hex[:12]}"
        event = threading.Event()
        job = {
            "job_id": job_id,
            "message": message,
            "history": history or [],
            "context": context or {},
            "event": event,
            "reply": None,
            "model": "antigravity_bridge",
            "created_at": time.time(),
        }

        with self.condition:
            self.active_jobs[job_id] = job
            self.pending_jobs.append(job_id)
            self.condition.notify()

        # Wait for reply from local bridge client
        answered = event.wait(timeout=timeout)

        with self.condition:
            resolved_job = self.active_jobs.pop(job_id, None)

        if answered and resolved_job and resolved_job.get("reply"):
            return {
                "reply": resolved_job["reply"],
                "model": resolved_job.get("model", "antigravity_bridge"),
                "job_id": job_id,
            }

        return None

    def poll_job(self, timeout: float = 12.0) -> Optional[Dict[str, Any]]:
        """Called by the local bridge client to fetch the next pending user chat request."""
        self.register_heartbeat()
        start = time.time()

        with self.condition:
            while not self.pending_jobs:
                remaining = timeout - (time.time() - start)
                if remaining <= 0:
                    return None
                self.condition.wait(timeout=remaining)

            job_id = self.pending_jobs.popleft()
            job = self.active_jobs.get(job_id)
            if not job:
                return None

            return {
                "job_id": job["job_id"],
                "message": job["message"],
                "history": job["history"],
                "context": job["context"],
                "created_at": job["created_at"],
            }

    def submit_reply(self, job_id: str, reply: str, model: str = "antigravity_bridge") -> bool:
        """Called by the local bridge client to submit an answer back to the waiting web request."""
        self.register_heartbeat()
        with self.condition:
            job = self.active_jobs.get(job_id)
            if not job:
                logger.warning("Bridge submit_reply: job %s not found or already timed out", job_id)
                return False

            job["reply"] = reply
            job["model"] = model
            job["event"].set()
            return True


def get_bridge_manager() -> AntigravityBridgeManager:
    return AntigravityBridgeManager.get_instance()
