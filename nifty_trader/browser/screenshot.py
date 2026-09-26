"""
Screenshot Manager.

Manages screenshot storage, structured filename generation,
and retention cleanup.
"""

import base64
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class ScreenshotManager:
    """
    Handles capturing, persisting, and pruning browser screenshots.
    """

    def __init__(
        self,
        storage_dir: Optional[Path] = None,
        retention_days: int = 7,
    ):
        self.storage_dir = storage_dir or Path("data/browser/screenshots")
        self.retention_days = retention_days
        self._ensure_storage_dir()

    def _ensure_storage_dir(self) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def generate_filename(self, source_name: str, session_id: str, suffix: str = "") -> str:
        """Generates a standardized filename: YYYYMMDD_HHMMSS_{source}_{session}.png"""
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        safe_source = "".join(c if c.isalnum() or c in "-_" else "_" for c in source_name.lower())
        safe_session = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)
        extra = f"_{suffix}" if suffix else ""
        return f"{ts}_{safe_source}_{safe_session}{extra}.png"

    def save_base64_screenshot(self, b64_data: str, filename: str) -> Path:
        """Decodes base64 PNG data and writes to the screenshot directory."""
        self._ensure_storage_dir()
        dest = self.storage_dir / filename
        data = base64.b64decode(b64_data)
        with open(dest, "wb") as f:
            f.write(data)
        return dest.resolve()

    def read_screenshot_bytes(self, filepath: Path) -> bytes:
        """Reads raw bytes of a saved screenshot."""
        with open(filepath, "rb") as f:
            return f.read()

    def cleanup_old_screenshots(self) -> int:
        """Removes screenshots older than the retention threshold. Returns count of deleted files."""
        if not self.storage_dir.exists():
            return 0

        cutoff = time.time() - (self.retention_days * 86400)
        deleted_count = 0

        for item in self.storage_dir.glob("*.png"):
            if item.is_file() and item.stat().st_mtime < cutoff:
                try:
                    item.unlink()
                    deleted_count += 1
                except OSError:
                    pass

        return deleted_count
