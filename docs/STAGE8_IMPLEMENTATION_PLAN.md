# STAGE 8 — SENSIBULL PAPER-TRADING EXECUTION & STATE SYNCHRONIZATION ENGINE

## Implementation Plan & Engineering Specification

---

# 1. Purpose & Core Principles

Stage 8 implements the **Sensibull Paper-Trading Execution and State Synchronization Engine**.

It acts as Hermes's hands and eyes for paper trading on Sensibull's Virtual Portfolio platform.

> **CRITICAL INVARIANT:**  
> **Stage 8 DOES NOT decide whether a trade is good.**  
> Decision-making, scenario evaluation, and trade thesis generation belong exclusively to the **Hermes + AI Brain** partnership (Stage 6).  
> Stage 8 is strictly an **autonomous executor, verifier, state reconciler, and observer**.

```text
┌─────────────────────────────────────────────────────────────┐
│                 HERMES + BRAIN (Stage 6)                    │
│   Formulates Market Reasoning -> Yields TradeCandidate      │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│            DETERMINISTIC RISK GATE (Stage 7)                │
│   Checks: <= 1.0% Risk, R:R >= 2.0, Max 3 trades, Sizing    │
└─────────────────────────────┬───────────────────────────────┘
                              │ ApprovedPaperOrder
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              STAGE 8: SENSIBULL PAPER ENGINE                │
│                                                             │
│   1. Environment Safety Check (MUST be Virtual Portfolio)   │
│   2. Idempotency & Duplicate Action Prevention              │
│   3. Browser Execution & Visual Action Verification         │
│   4. Real-Time Position & P&L Monitoring                    │
│   5. Dual-State Ground Truth Reconciliation                 │
│   6. Fail-Safe Interruption & Indeterminate State Handling  │
└─────────────────────────────┬───────────────────────────────┘
                              │ Position & P&L Telemetry
                              ▼
               Hermes World State & Brain Context
```

---

# 2. Scope & Functional Requirements

1. **Sensibull Paper-Trading Navigation**: Navigate directly to `https://web.sensibull.com/virtual-trade` and verify page responsiveness.
2. **Detect Paper-Trading Environment**: Strict verification that the active tab is **Virtual Portfolio / Paper Trading** and NOT a real broker trading terminal. If live trading is detected, abort instantly.
3. **Create Paper Trade**: Place virtual orders (NIFTY strike, Call/Put, Expiry, Buy/Sell, Lot Quantity) using deterministic browser interactions.
4. **Verify Trade Actually Opened (Visual & DOM Verification)**: Check confirmation toasts, inspect active position rows, and capture cryptographic screenshots.
5. **Read Current Paper Position & Order Status**: Extract strike, instrument, quantity, entry price, LTP, unrealized P&L (₹ and %), and realized P&L.
6. **Monitor P&L & Detect Position Changes**: Continuously track MTM and detect fills, closures, or stop-loss/target breaches.
7. **Modify / Close Paper Position**: Autonomously square off positions when commanded by Hermes/Brain or risk cutoff (15:15 IST), with visual verification of exit.
8. **Handle Rejected / Failed / Unknown Actions**: Detect error dialogs, margin issues, or session timeouts without entering blind retry loops.
9. **Reconcile Hermes State with Sensibull State**: Reconcile internal trade records against Sensibull's ground truth positions table.
10. **Prevent Duplicate Actions**: SHA-256 idempotency fingerprinting prevents submitting the same trade twice during network latency.
11. **Feed Position Telemetry to Hermes**: Exposes `PaperPositionObservation` to `HermesToolBridge` and `UnifiedMarketObservation`.
12. **Maintain Complete Trade Lifecycle**: `PENDING -> SUBMITTING -> OPEN -> MONITORING -> CLOSING -> CLOSED / REJECTED`.
13. **Handle Browser / Session Interruptions**: Safe auto-reconnect, profile re-use, and session recovery without state loss.
14. **Stop Safely on Indeterminate State**: Freeze actions and alert the operator if Sensibull's state cannot be definitively proven.

---

# 3. Subsystem Architecture

```text
nifty_trader/paper/
├── __init__.py                  # Package exports
├── contracts.py                 # Pydantic schemas (Order, Position, Lifecycle, Result)
├── environment.py               # Strict Virtual Trading environment detector & guard
├── navigator.py                 # Sensibull Virtual Portfolio navigation & selectors
├── executor.py                  # Paper trade order submission & visual verification
├── position_reader.py           # DOM table parser for open/closed positions & P&L
├── reconciler.py                # Dual-state reconciler & idempotency engine
├── store.py                     # SQLite persistence for paper trade lifecycle
└── service.py                   # High-level SensibullPaperTradingService
```

---

# 4. Detailed Component Specifications

### 4.1 Environment Safety Guard (`environment.py`)
- Checks page URL, header labels, and badge text:
  - Must find `"Virtual Trade"`, `"Virtual Portfolio"`, or `"Paper Trading"`.
  - Must ensure NO active live broker order buttons (`"Place Real Order"`, `"Send to Zerodha/Kite"`) are active.
- If ambiguous or live broker detected:
  - Raises typed `UnsafeTradingEnvironmentError`.
  - Halts execution immediately.

### 4.2 Order Execution & Verification Protocol (`executor.py`)
```text
[Receive Approved Order]
        ↓
Compute Idempotency Hash (Symbol + Strike + OptionType + Lots + Expiry)
        ↓ Check SQLite: Already submitted?
  YES ──► Return existing order (Prevent duplicate)
   NO
        ↓
Fill Virtual Order Form (Select NIFTY, Strike, Option Type, Lots)
        ↓
Capture Pre-Execution Screenshot
        ↓
Click "Add to Virtual Portfolio"
        ↓
Wait for Result Event (Toast: "Trade added successfully" or Error)
        ↓
Inspect Positions Table: Does row exist with matching Strike & Lots?
  YES ──► Mark OPEN, Capture Post-Execution Screenshot, Record Entry Price
   NO ──► Query Reconciler, if not found mark FAILED, DO NOT blind retry
```

### 4.3 Position Reader & DOM Parser (`position_reader.py`)
- Extracts table rows under `#virtual-positions-table` or active DOM cards:
  - Strike (e.g. `24500 CE`, `24600 PE`)
  - Expiry date
  - Quantity / Lots (e.g. `25` or `1 Lot`)
  - Avg Entry Price
  - Current LTP (Last Traded Price)
  - Unrealized P&L (`₹` and `%`)
  - Overall Portfolio Realized P&L
- Handles empty positions gracefully (`no active positions`).

### 4.4 State Reconciliation (`reconciler.py`)
- Dual-state tracking:
  - **Local Hermes State**: What Hermes thinks is open.
  - **Sensibull Ground Truth**: What Sensibull actually displays.
- Resolution rules:
  - If Hermes shows `OPEN` but Sensibull shows `CLOSED`: Reconcile to `CLOSED`, record exit price and P&L.
  - If Hermes shows `OPEN` but Sensibull has zero positions: Mark `EXTERNAL_CLOSED_OR_EXPIRED`.
  - If Sensibull has a position not in Hermes: Ingest as `UNTRACKED_EXTERNAL_POSITION`.

### 4.5 SQLite Audit Store (`store.py`)
- Database: `data/paper_trading/paper_trades.db`
- Tables:
  - `paper_orders`: Order ID, Request ID, Symbol, Strike, Direction, Lots, Status, Sent At, Verified At.
  - `paper_positions`: Position ID, Strike, Option Type, Lots, Entry Price, Current LTP, P&L, Status, Updated At.
  - `paper_reconciliations`: Timestamp, Discrepancies Found, Action Taken.

---

# 5. CLI Commands

```bash
# Check current paper trading environment and open positions
python -m nifty_trader.cli paper-status

# Synchronize and display current Sensibull virtual positions
python -m nifty_trader.cli paper-positions

# Manually trigger emergency paper position square-off
python -m nifty_trader.cli paper-close --all
```

---

# 6. Verification & Test Plan

1. **Environment Detection Tests**: Validates virtual environment detection, detects simulated live-broker screens, and triggers instant abort.
2. **Idempotency Tests**: Verifies duplicate order submissions with identical hashes are rejected before hitting the browser.
3. **DOM Position Parsing Tests**: Feeds fixture HTML/DOM strings from Sensibull Virtual Portfolio and asserts accurate strike, quantity, LTP, and P&L extraction.
4. **Order Execution & Toast Verification**: Tests confirmation detection, error toast detection, and screenshot logging.
5. **Reconciliation Tests**: Tests discrepancies between local SQLite and remote DOM, asserting correct ground-truth resolution.
6. **Fail-Safe Disconnect Tests**: Simulates CDP browser crash during order entry, verifying safe recovery without unverified executions.
