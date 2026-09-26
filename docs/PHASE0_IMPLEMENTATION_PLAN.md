# NIFTY AUTONOMOUS TRADER — PHASE 0 IMPLEMENTATION PLAN & PROJECT ASSESSMENT

**Document:** `docs/PHASE0_IMPLEMENTATION_PLAN.md`  
**Architecture Version:** 1.0.0 (Phase 0 Baseline)  
**Status:** Approved Master Implementation Plan  

---

## 1. Assessment of Existing Machine Trading Projects

The host machine was audited for existing trading assets to identify potentially reusable algorithms, data structures, and architectural conflicts.

### 1.1 `D:\Antygravity_Proj\Nifty_Banknifty`
- **Nature:** Python/FastAPI trading terminal with DhanHQ broker integration.
- **Key Modules Audited:**
  - `engine/levels_calculator.py`: High/Low pivot, CPR (Central Pivot Range), Fibonacci retracement calculations.
  - `engine/trend_detector.py`: Multi-factor trend scoring combining EMA ribbon (9/21/50/200), Supertrend (10, 3), ADX (14), RSI (14), VWAP, and PCR.
  - `engine/paper_trader.py`: Virtual account balance tracking, margin calculation, MTM PnL updates.
  - `broker/scrip_master.py`: NSE instrument token mapping and strike selection.
- **Reusable Concepts:**
  - Robust mathematical implementations of **Supertrend, ADX choppiness filters, and reaction zone levels**.
  - Logic for **incremental daily candle synchronization** (`data_sync.py`).
- **Architectural Conflicts / What NOT to Reuse:**
  - Direct coupling to DhanHQ broker API in data fetching (violates our broker-independent Data Architecture).
  - Tightly coupled options chain strike selection (our initial focus is purely NIFTY Index price action on 1H/15M).

### 1.2 `D:\Trading App`
- **Nature:** React + Vite + TypeScript PWA with client-side trading store.
- **Key Modules Audited:**
  - `src/platform/indicator/`: Client-side JavaScript technical indicators.
  - `src/platform/trading/`: Order ticket and position tracking state.
  - `src/ui/`: Interactive charting and scorecard components.
- **Reusable Concepts:**
  - UI visual layout, scorecard widgets, and color schemes for future dashboard packages (Package 16).
- **Architectural Conflicts / What NOT to Reuse:**
  - Do not port client-side TypeScript indicators into Python backend; Python provides standard, vectorized numerical computation (`pandas`, `numpy`).

---

## 2. The 20-Package Master Roadmap

Development follows a strict **One-Package-at-a-Time** methodology:
`PLAN → REVIEW → APPROVAL → IMPLEMENT → TEST → VERIFY → DOCUMENT → LOCK`.

| Package | Title | Primary Deliverable |
|---|---|---|
| **Package 0** | **Hermes Fork & Product Repository Setup** | Initialize `D:\AI_Trading\nifty-autonomous-trader` with clean virtualenv, git baseline, and verified uncorrupted Hermes engine. |
| **Package 1** | **Hermes Build & Model Router** | Implement `ModelProvider` ABC, `GeminiProvider`, `OpenRouterProvider`, fallback cooldowns, and `models.yaml`. |
| **Package 2** | **Computer & Browser Automation Agent** | Implement Puppeteer/Chrome browser bridge, clean screenshot capture, and DOM element inspection. |
| **Package 3** | **Market Perception Engine (1H + 15M)** | Implement NIFTY candle feed (`market/feed.py`), incremental SQLite cache, and anomaly filters. |
| **Package 4** | **Gemini & Cognitive Trading Brain** | Author Pydantic schemas (`MarketSnapshot`, `AnalysisOutput`), prompt templates, and reasoning parsers. |
| **Package 5** | **Autonomous Observation & Waiting Engine** | Implement event-driven `MarketClock`, non-blocking sleep, 15M candle alignment, and state transitions. |
| **Package 6** | **Strategy Discovery & Setup Scanner** | Formalize 15M setup rules (20EMA Pullback, Range Breakout, Trap Reversal) with deterministic triggers. |
| **Package 7** | **Deterministic Risk Gatekeeper** | Implement unbypassable mathematical risk gates (1% max risk, R:R ≥ 1:2, max daily loss ₹5,000, 3 trades/day). |
| **Package 8** | **Simulated Paper Broker** | Build virtual ledger simulating realistic market fills, slippage, liquidity queues, and execution timestamps. |
| **Package 9** | **Position Monitoring & Trailing Engine** | Implement active 15M candle trailing stop rules, target monitoring, and mandatory 15:15 intraday exit. |
| **Package 10** | **Trader Memory Store** | Implement SQLite FTS5 observation journal and historical setup similarity retrieval engine. |
| **Package 11** | **Post-Trade Failure Analysis** | Build automated post-mortem engine evaluating plan vs. execution, tagging defects, and tracking root causes. |
| **Package 12** | **Strategy Learning Laboratory** | Build isolated simulation sandbox for generating and testing parameter mutation hypotheses. |
| **Package 13** | **Historical Backtesting Engine** | Implement event-driven multi-month historical backtester with commission and slippage modeling. |
| **Package 14** | **Strategy Versioning & Governance** | Implement immutable strategy manifests (`v1.0.yaml`), staging gates, and cryptographic operator approval. |
| **Package 15** | **Long-Duration Autonomous Paper Testing** | Run multi-day unattended autonomous paper trading sessions verifying stability and patience. |
| **Package 16** | **Interactive Web Dashboard** | Build lightweight local FastAPI + HTML5/WebSocket dashboard showing live state, chart, and PnL. |
| **Package 17** | **Packaging & Standalone Installer** | Package application into turnkey Windows installer (`.exe`) with bundled runtime and CLI controls. |
| **Package 18** | **Production Hardening & Security Audit** | Security review, API key encryption, error boundary stress tests, and fail-safe verification. |
| **Package 19** | **Optional Broker Integration** | Optional, strictly gated live execution plugin (DhanHQ / Zerodha) requiring explicit 2FA authorization. |

---

## 3. Strict Stop Condition — Phase 0 Complete

With the delivery of these architectural specifications, **Phase 0 is complete**.

**Per Section 24 of the Project Specification:**
- DO NOT start Package 1.
- DO NOT modify Hermes source code.
- DO NOT write trading code.
- DO NOT connect any broker.
- Stop and wait for explicit operator review and approval.
