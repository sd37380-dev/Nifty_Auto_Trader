"""
Hermes Browser Adapter (Chrome DevTools Protocol Implementation).

Bridges application-level browser commands into native Chrome CDP operations.
Provides deterministic, zero-dependency browser control via standard WebSockets.
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx
import websockets

from nifty_trader.browser.base import BrowserProvider
from nifty_trader.browser.errors import (
    BrowserCrashError,
    BrowserError,
    ElementNotFoundError,
    NavigationTimeoutError,
    SecurityViolationError,
)
from nifty_trader.browser.models import (
    BrowserAction,
    BrowserActionResult,
    BrowserSession,
    BrowserSessionStatus,
)
from nifty_trader.browser.navigation import validate_url
from nifty_trader.browser.screenshot import ScreenshotManager
from nifty_trader.browser.session import BrowserSessionManager

logger = logging.getLogger("nifty_trader.browser.adapter")


class HermesBrowserAdapter(BrowserProvider):
    """
    CDP-based browser automation provider interfacing directly with Chrome.
    """

    def __init__(
        self,
        chrome_path: str = r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        user_data_dir: Optional[Path] = None,
        remote_port: int = 9225,
        headless: bool = True,
        navigation_timeout_seconds: float = 30.0,
        element_timeout_seconds: float = 10.0,
        screenshot_manager: Optional[ScreenshotManager] = None,
    ):
        self.chrome_path = chrome_path
        self.user_data_dir = user_data_dir or (Path("data/browser/chrome_profile").resolve())
        self.remote_port = remote_port
        self.headless = headless
        self.navigation_timeout = navigation_timeout_seconds
        self.element_timeout = element_timeout_seconds

        self.screenshot_mgr = screenshot_manager or ScreenshotManager()
        self.session_mgr = BrowserSessionManager()

        self._process: Optional[subprocess.Popen] = None
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._req_id: int = 0
        self._target_id: Optional[str] = None
        self._active_ws_url: Optional[str] = None

    @property
    def session_id(self) -> str:
        return self.session_mgr.session_id

    def _kill_lingering_profile_processes(self) -> None:
        """Kills any orphaned Chrome processes holding our profile directory."""
        if sys.platform == "win32":
            try:
                prof_str = str(self.user_data_dir).replace("/", "\\")
                cmd = f"Get-CimInstance Win32_Process -Filter \"Name = 'chrome.exe'\" | Where-Object {{ $_.CommandLine -like '*{prof_str}*' }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}"
                subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, timeout=5)
            except Exception as e:
                logger.debug("Failed cleaning lingering profile processes: %s", e)

    async def start(self) -> BrowserSession:
        """Launches the Chrome process and establishes the CDP WebSocket connection."""
        if self._process and self._process.poll() is None and self._ws:
            return self.session_mgr.session

        self.session_mgr.set_status(BrowserSessionStatus.STARTING)
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        self._kill_lingering_profile_processes()

        if not Path(self.chrome_path).exists():
            self.session_mgr.set_status(BrowserSessionStatus.FAILED)
            raise FileNotFoundError(f"Chrome binary not found at '{self.chrome_path}'")

        cmd = [
            self.chrome_path,
            f"--remote-debugging-port={self.remote_port}",
            "--headless=new" if self.headless else "--start-maximized",
            "--window-size=1920,1080",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={self.user_data_dir}",
            "about:blank",
        ]

        logger.info("Starting Chrome process on port %s...", self.remote_port)
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Wait for CDP endpoint to respond
        endpoint = f"http://127.0.0.1:{self.remote_port}"
        connected = False
        start_wait = time.time()

        while time.time() - start_wait < 10.0:
            if self._process.poll() is not None:
                self.session_mgr.set_status(BrowserSessionStatus.FAILED)
                raise BrowserCrashError(f"Chrome process exited unexpectedly with code {self._process.returncode}")
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(f"{endpoint}/json/version", timeout=1.0)
                    if resp.status_code == 200:
                        connected = True
                        break
            except Exception:
                await asyncio.sleep(0.3)

        if not connected:
            self.session_mgr.set_status(BrowserSessionStatus.FAILED)
            raise BrowserCrashError(f"Timed out waiting for Chrome CDP on port {self.remote_port}")

        # Create or attach to a tab
        async with httpx.AsyncClient() as client:
            tabs = (await client.get(f"{endpoint}/json/list")).json()
            page_tabs = [t for t in tabs if t.get("type") == "page"]
            if page_tabs:
                target = page_tabs[0]
            else:
                target = (await client.put(f"{endpoint}/json/new?about:blank")).json()

            self._active_ws_url = target["webSocketDebuggerUrl"]
            self._target_id = target["id"]

        self._ws = await websockets.connect(self._active_ws_url, max_size=50_000_000)

        # Enable necessary CDP domains
        await self._send_cdp("Page.enable")
        await self._send_cdp("Runtime.enable")
        await self._send_cdp("DOM.enable")

        self.session_mgr.set_status(BrowserSessionStatus.READY)
        self.session_mgr.update_page_info("about:blank", "Blank Page")
        logger.info("Chrome CDP session %s established.", self.session_id)
        return self.session_mgr.session

    def _is_ws_open(self) -> bool:
        if self._ws is None:
            return False
        try:
            from websockets.protocol import State
            return self._ws.state == State.OPEN
        except Exception:
            return getattr(self._ws, "close_code", None) is None

    async def _send_cdp(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 30.0) -> Dict[str, Any]:
        """Sends a CDP command and awaits the specific response matching request ID."""
        if not self._is_ws_open():
            logger.info("CDP WebSocket not connected; automatically initializing browser session...")
            await self.start()

        if not self._is_ws_open():
            raise BrowserCrashError("CDP WebSocket is closed or uninitialized.")

        self._req_id += 1
        req_id = self._req_id
        payload = {"id": req_id, "method": method}
        if params:
            payload["params"] = params

        await self._ws.send(json.dumps(payload))

        start_time = time.time()
        while time.time() - start_time < timeout:
            raw_msg = await asyncio.wait_for(self._ws.recv(), timeout=timeout)
            data = json.loads(raw_msg)
            if data.get("id") == req_id:
                if "error" in data:
                    raise BrowserError(f"CDP command '{method}' failed: {data['error'].get('message')}")
                return data.get("result", {})

        raise NavigationTimeoutError(f"CDP command '{method}' timed out after {timeout}s")

    async def stop(self) -> None:
        """Gracefully terminates CDP WebSocket and Chrome process."""
        self.session_mgr.set_status(BrowserSessionStatus.STOPPED)

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        if self._process:
            pid = self._process.pid
            try:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=5)
                else:
                    self._process.terminate()
                    self._process.wait(timeout=3)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None
            self._kill_lingering_profile_processes()

        logger.info("Browser session %s stopped.", self.session_id)

    async def open_url(self, url: str) -> BrowserActionResult:
        """Navigates to the specified URL."""
        validated = validate_url(url)
        url_before = await self.get_current_url()
        start_time = time.perf_counter()

        self.session_mgr.set_status(BrowserSessionStatus.BUSY)
        try:
            await self._send_cdp("Page.navigate", {"url": validated}, timeout=self.navigation_timeout)
            # Allow initial scripts and DOM to stabilize
            await asyncio.sleep(2.0)

            url_after = await self.get_current_url()
            title = await self.get_title()
            self.session_mgr.update_page_info(url_after, title)
            self.session_mgr.set_status(BrowserSessionStatus.READY)

            duration = (time.perf_counter() - start_time) * 1000.0
            result = BrowserActionResult(
                action=BrowserAction.OPEN_URL,
                success=True,
                duration_ms=round(duration, 2),
                url_before=url_before,
                url_after=url_after,
                message=f"Navigated to '{url_after}' ({title})",
            )
            self.session_mgr.record_action(result)
            return result
        except Exception as e:
            self.session_mgr.set_status(BrowserSessionStatus.READY)
            duration = (time.perf_counter() - start_time) * 1000.0
            result = BrowserActionResult(
                action=BrowserAction.OPEN_URL,
                success=False,
                duration_ms=round(duration, 2),
                url_before=url_before,
                url_after=url_before,
                error=str(e),
                message=f"Navigation failed to '{validated}'",
            )
            self.session_mgr.record_action(result)
            raise

    async def get_current_url(self) -> str:
        res = await self._send_cdp("Runtime.evaluate", {"expression": "window.location.href"})
        return str(res.get("result", {}).get("value", ""))

    async def get_title(self) -> str:
        res = await self._send_cdp("Runtime.evaluate", {"expression": "document.title"})
        return str(res.get("result", {}).get("value", ""))

    async def click(self, selector: str) -> BrowserActionResult:
        start_time = time.perf_counter()
        url_before = await self.get_current_url()
        js = f"""
        (() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return false;
            el.scrollIntoView({{ behavior: 'instant', block: 'center' }});
            el.click();
            return true;
        }})()
        """
        res = await self._send_cdp("Runtime.evaluate", {"expression": js, "returnByValue": True})
        success = bool(res.get("result", {}).get("value"))
        await asyncio.sleep(0.5)

        url_after = await self.get_current_url()
        duration = (time.perf_counter() - start_time) * 1000.0

        result = BrowserActionResult(
            action=BrowserAction.CLICK,
            success=success,
            duration_ms=round(duration, 2),
            url_before=url_before,
            url_after=url_after,
            message=f"Click on '{selector}': {'Success' if success else 'Element not found'}",
            error=None if success else f"Selector '{selector}' not found in DOM",
        )
        self.session_mgr.record_action(result)
        return result

    async def type_text(self, selector: str, text: str) -> BrowserActionResult:
        start_time = time.perf_counter()
        url_before = await self.get_current_url()
        js = f"""
        (() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return false;
            el.focus();
            el.value = {json.dumps(text)};
            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            return true;
        }})()
        """
        res = await self._send_cdp("Runtime.evaluate", {"expression": js, "returnByValue": True})
        success = bool(res.get("result", {}).get("value"))
        url_after = await self.get_current_url()
        duration = (time.perf_counter() - start_time) * 1000.0

        result = BrowserActionResult(
            action=BrowserAction.TYPE,
            success=success,
            duration_ms=round(duration, 2),
            url_before=url_before,
            url_after=url_after,
            message=f"Typed text into '{selector}': {'Success' if success else 'Element not found'}",
        )
        self.session_mgr.record_action(result)
        return result

    async def press_key(self, key: str) -> BrowserActionResult:
        start_time = time.perf_counter()
        url_before = await self.get_current_url()

        # Use Input.dispatchKeyEvent for standard keys
        await self._send_cdp("Input.dispatchKeyEvent", {"type": "keyDown", "key": key})
        await self._send_cdp("Input.dispatchKeyEvent", {"type": "keyUp", "key": key})
        await asyncio.sleep(0.3)

        url_after = await self.get_current_url()
        duration = (time.perf_counter() - start_time) * 1000.0
        result = BrowserActionResult(
            action=BrowserAction.PRESS_KEY,
            success=True,
            duration_ms=round(duration, 2),
            url_before=url_before,
            url_after=url_after,
            message=f"Pressed key '{key}'",
        )
        self.session_mgr.record_action(result)
        return result

    async def scroll(self, direction: str = "down", amount: int = 500) -> BrowserActionResult:
        start_time = time.perf_counter()
        delta = amount if direction == "down" else -amount
        url_curr = await self.get_current_url()

        js = f"window.scrollBy(0, {delta});"
        await self._send_cdp("Runtime.evaluate", {"expression": js})
        await asyncio.sleep(0.3)

        duration = (time.perf_counter() - start_time) * 1000.0
        result = BrowserActionResult(
            action=BrowserAction.SCROLL,
            success=True,
            duration_ms=round(duration, 2),
            url_before=url_curr,
            url_after=url_curr,
            message=f"Scrolled {direction} by {amount}px",
        )
        self.session_mgr.record_action(result)
        return result

    async def go_back(self) -> BrowserActionResult:
        start_time = time.perf_counter()
        url_before = await self.get_current_url()
        await self._send_cdp("Runtime.evaluate", {"expression": "window.history.back();"})
        await asyncio.sleep(1.0)
        url_after = await self.get_current_url()
        duration = (time.perf_counter() - start_time) * 1000.0
        result = BrowserActionResult(
            action=BrowserAction.BACK,
            success=True,
            duration_ms=round(duration, 2),
            url_before=url_before,
            url_after=url_after,
            message="Navigated back",
        )
        self.session_mgr.record_action(result)
        return result

    async def go_forward(self) -> BrowserActionResult:
        start_time = time.perf_counter()
        url_before = await self.get_current_url()
        await self._send_cdp("Runtime.evaluate", {"expression": "window.history.forward();"})
        await asyncio.sleep(1.0)
        url_after = await self.get_current_url()
        duration = (time.perf_counter() - start_time) * 1000.0
        result = BrowserActionResult(
            action=BrowserAction.FORWARD,
            success=True,
            duration_ms=round(duration, 2),
            url_before=url_before,
            url_after=url_after,
            message="Navigated forward",
        )
        self.session_mgr.record_action(result)
        return result

    async def reload(self) -> BrowserActionResult:
        start_time = time.perf_counter()
        url_curr = await self.get_current_url()
        await self._send_cdp("Page.reload")
        await asyncio.sleep(1.5)
        duration = (time.perf_counter() - start_time) * 1000.0
        result = BrowserActionResult(
            action=BrowserAction.RELOAD,
            success=True,
            duration_ms=round(duration, 2),
            url_before=url_curr,
            url_after=url_curr,
            message="Reloaded page",
        )
        self.session_mgr.record_action(result)
        return result

    async def get_visible_text(self, max_chars: int = 12000) -> str:
        js = "document.body ? document.body.innerText : '';"
        res = await self._send_cdp("Runtime.evaluate", {"expression": js, "returnByValue": True})
        raw_text = str(res.get("result", {}).get("value", ""))
        return raw_text[:max_chars]

    async def inspect_dom(self, selector: str = "button, a, input, h1, h2, h3", max_elements: int = 200) -> List[Dict[str, Any]]:
        js = f"""
        (() => {{
            const list = Array.from(document.querySelectorAll({json.dumps(selector)}));
            return list.slice(0, {max_elements}).map(el => ({{
                tag: el.tagName,
                id: el.id || '',
                classes: el.className || '',
                text: (el.innerText || el.value || '').trim().substring(0, 100),
                aria_label: el.getAttribute('aria-label') || ''
            }}));
        }})()
        """
        res = await self._send_cdp("Runtime.evaluate", {"expression": js, "returnByValue": True})
        return res.get("result", {}).get("value") or []

    async def capture_screenshot(self, name_prefix: str = "snapshot") -> str:
        """Captures screenshot over CDP and returns local file path."""
        res = await self._send_cdp("Page.captureScreenshot", {"format": "png"})
        b64_data = res.get("data", "")
        if not b64_data:
            raise BrowserError("CDP Page.captureScreenshot returned empty data.")

        filename = self.screenshot_mgr.generate_filename(name_prefix, self.session_id)
        filepath = self.screenshot_mgr.save_base64_screenshot(b64_data, filename)
        return str(filepath)

    async def wait_for_element(self, selector: str, timeout_seconds: Optional[float] = None) -> bool:
        timeout = timeout_seconds or self.element_timeout
        start = time.time()
        while time.time() - start < timeout:
            if await self.element_exists(selector):
                return True
            await asyncio.sleep(0.5)
        return False

    async def element_exists(self, selector: str) -> bool:
        js = f"document.querySelector({json.dumps(selector)}) !== null;"
        res = await self._send_cdp("Runtime.evaluate", {"expression": js, "returnByValue": True})
        return bool(res.get("result", {}).get("value"))

    async def get_page_state(self) -> Dict[str, Any]:
        url = await self.get_current_url()
        title = await self.get_title()
        js = "document.readyState;"
        res = await self._send_cdp("Runtime.evaluate", {"expression": js, "returnByValue": True})
        ready_state = res.get("result", {}).get("value", "unknown")
        return {
            "session_id": self.session_id,
            "status": self.session_mgr.status.value,
            "url": url,
            "title": title,
            "readyState": ready_state,
        }
