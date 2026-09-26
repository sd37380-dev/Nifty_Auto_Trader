# BROWSER ARCHITECTURE & CDP PROTOCOL
## Computer & Browser Automation Agent

**Product:** NIFTY Autonomous Trader  
**Component:** Package 2 Architecture Document  
**Version:** 1.0  
**Updated:** 2026-09-26  

---

## 1. Overview & Objectives

The Browser Automation layer provides the "Eyes + Hands" of the NIFTY Autonomous Trader. Rather than relying on simulated synthetic chart snapshots or opaque scrapers, the agent drives a full, native Google Chrome instance via the **Chrome DevTools Protocol (CDP)** over asynchronous WebSockets.

### Core Objectives:
1. **Human Trader Fidelity:** Inspect real websites (TradingView, NSE India, financial portals) as rendered by a modern browser.
2. **Zero Node Dependencies:** Connect directly from Python using asynchronous WebSockets (`websockets`) and HTTP client (`httpx`).
3. **Deterministic Isolation:** Dedicated Chrome user-data profile to prevent browser session contamination or interference with user desktop activity.
4. **Strategy-Agnostic Operation:** The browser agent captures observations and coordinates perception. It contains zero trading strategy, position sizing, or order execution logic.

---

## 2. Architecture & Data Flow

```text
+-------------------------------------------------------------------------+
|                              NiftyTraderRuntime                         |
|                                     │                                   |
|                                     ▼                                   |
|                              BrowserAgent                               |
|                  (Coordinates Retries, Sessions & Tasks)                |
+─────────────────────────────────────┬───────────────────────────────────+
                                      │
          ┌───────────────────────────┴───────────────────────────┐
          ▼                                                       ▼
+───────────────────────────────────+   +───────────────────────────────────+
|        HermesBrowserAdapter       |   |       ScreenshotManager           |
|  - Spawns Chrome Subprocess       |   |  - Standardized File Naming       |
|  - CDP over Async WebSocket       |   |  - Metadata & SHA-256 Checksums   |
|  - Page, Runtime, DOM Domains     |   |  - Age-based Retention Pruner     |
+─────────────────┬─────────────────+   +─────────────────┬─────────────────+
                  │                                       │
                  ▼                                       ▼
+───────────────────────────────────+   +───────────────────────────────────+
|     Google Chrome (Port 9225)     |   |     data/browser/screenshots/     |
|  - Isolated Profile Directory     |   |   {YYYYMMDD_HHMMSS}_{source}.png  |
|  - Headless / Headful Switch      |   |                                   |
+─────────────────┬─────────────────+   +─────────────────┬─────────────────+
                  │                                       │
                  └───────────────────┬───────────────────┘
                                      ▼
                        BrowserObservation Compiler
                         - URL Security Validator
                         - Web Text Sanitizer & Defuser
                         - DOM Element Extractor
                                      │
                                      ▼
                             ModelRouter (Gemini)
                    (Neutral Visual & Layout Perception)
```

---

## 3. Browser Session Lifecycle & State Machine

Every browser interaction is tracked via `BrowserSessionManager` adhering to the following state machine:

```text
       [STARTUP]
           │
           ▼
     ┌───────────┐         Network Error / Crash
     │ STARTING  ├───────────────────────────────────────┐
     └─────┬─────┘                                       │
           │ CDP Handshake Complete                      │
           ▼                                             │
     ┌───────────┐                                       │
 ┌──►│   READY   │◄────────────────┐                     │
 │   └─────┬─────┘                 │                     │
 │         │                       │                     │
 │         │ Begin Action          │ Action Complete     │
 │         ▼                       │                     ▼
 │   ┌───────────┐                 │               ┌───────────┐
 │   │   BUSY    ├─────────────────┘               │  FAILED   │
 │   └─────┬─────┘                                 └───────────┘
 │         │                                             ▲
 │         │ Stop Triggered                              │
 │         ▼                                             │
 │   ┌───────────┐                                       │
 └───┤  STOPPED  ├───────────────────────────────────────┘
     └───────────┘
```

### State Definitions:
- **`STARTING`:** Chrome process has launched; waiting for port 9225 and initial CDP WebSocket connection.
- **`READY`:** CDP domains enabled (`Page`, `Runtime`, `DOM`); ready to receive commands.
- **`BUSY`:** An action is currently being executed (e.g. `open_url`, `click`, `capture_screenshot`).
- **`STOPPED`:** CDP WebSocket cleanly closed; Chrome process terminated.
- **`FAILED`:** Chrome crashed or network timeout occurred.

---

## 4. CDP Action Primitives

The `HermesBrowserAdapter` exposes low-level CDP commands through structured methods:

### 4.1 Navigation (`open_url`)
- **CDP Command:** `Page.navigate`
- **Synchronization:** Waits for `Page.loadEventFired` with a fallback delay.
- **Validation:** Enforces HTTP/HTTPS schemes via `validate_url()`.

### 4.2 Click (`click`)
- **CDP Sequence:**
  1. `Runtime.evaluate` to query selector and extract bounding box (`getBoundingClientRect()`).
  2. `Input.dispatchMouseEvent` with `type="mousePressed"`.
  3. `Input.dispatchMouseEvent` with `type="mouseReleased"`.

### 4.3 Scrolling (`scroll`)
- **CDP Command:** `Input.dispatchMouseEvent` with `type="mouseWheel"`, `deltaX`, and `deltaY`.

### 4.4 DOM Text & Structure Extraction (`extract_text`, `extract_dom_elements`)
- **CDP Command:** `Runtime.evaluate` executing lightweight in-page JavaScript that extracts:
  - `document.body.innerText` (sanitized and bounded to 12,000 characters).
  - High-salience interactive elements (`button`, `a`, `input`, `select`, `h1-h3`) with text, CSS selectors, and ARIA labels.

### 4.5 Screenshot Capture (`capture_screenshot`)
- **CDP Command:** `Page.captureScreenshot` with `format="png"`.
- Returns base64 payload decoded directly to bytes on disk.

---

## 5. Screenshot Storage & Management

Screenshots are saved under `data/browser/screenshots/` following a strict naming convention:

```text
{YYYYMMDD_HHMMSS}_{source}_{session_prefix}.png
```
Example: `20260926_135910_tradingview_sess_4b87a6e4.png`

### Screenshot Metadata:
- **`file_path`:** Absolute path on disk.
- **`file_name`:** Standardized filename.
- **`source_type`:** Classified source (`CHART`, `NSE`, `NEWS`, `SEARCH`, `GENERAL_WEB`).
- **`dimensions`:** Width and height in pixels (default 1920x1080).
- **`sha256`:** Cryptographic integrity checksum.
- **`retention_days`:** Automatic pruning of files older than configured threshold (default 7 days).

---

## 6. Resilience & Fault Tolerance

1. **Port Collisions:** Chrome defaults to remote debugging port `9225` (configurable in `config/settings.yaml`).
2. **Process Orphan Prevention:** On `stop()`, the adapter issues `SIGTERM` followed by `kill()` if Chrome does not terminate within 3 seconds.
3. **CDP Frame Matching:** Chrome CDP transmits asynchronous event notifications (e.g. `Page.frameNavigated`) over the same WebSocket. The adapter filters incoming messages in a loop until the matching `data["id"] == req_id` response is found.
4. **Bounded Retries:** `BrowserAgent` wraps critical operations in bounded retries (default 3 attempts) with exponential backoff.
