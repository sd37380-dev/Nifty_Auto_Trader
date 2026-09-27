# STAGE 6 — HERMES–BRAIN COLLABORATIVE TRADING ORCHESTRATION IMPLEMENTATION PLAN

## 1. Executive Summary

Stage 6 implements the **collaborative partnership between Hermes Agent and the AI Trading Brain** for the NIFTY Autonomous Trader.
In this unified architecture:
- **Hermes** serves as the autonomous agent, operator, orchestrator, and custodian of safety and operational boundaries.
- **The Brain** (Package 4 via ModelRouter/Gemini) serves as the reasoning intelligence, formulating market regimes, hypotheses, scenarios, and trade candidates.
- **Tools & Browser** act as Hermes' eyes and hands (Yahoo Finance, TradingView, Sensibull).
- **Memory** acts as descriptive market context (never hard-coded strategy rules).
- **Deterministic Boundaries** govern risk, execution safety, and untrusted web input.

```text
┌─────────────────────────────────────────────────────────────┐
│                 HERMES ORCHESTRATION LAYER                  │
│                                                             │
│   Tool Bridge ──► Context Security ──► Context Selector     │
│   (Perception)    (Sanitize Web)       (10-Tier Budget)     │
│                                              │              │
│                                              ▼              │
│                                    HermesContextBuilder     │
│                                              │              │
│                                              ▼ (BrainInput) │
│                                    ┌──────────────────┐     │
│                                    │  PACKAGE 4 BRAIN │     │
│                                    │  (Reasoning Engine)│   │
│                                    └─────────┬────────┘     │
│                                              │ (BrainResult)│
│                                              ▼              │
│   Observation Fulfillment ◄── BrainOutput Handling          │
│   (Sensibull/TradingView)     (WAIT / WATCH / CANDIDATE)    │
│            │                                 │              │
│            ▼ (Next Turn)                     ▼ (Halt)       │
│      Re-evaluation                     TradeCandidate       │
│                                        (No live orders)     │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Core Non-Negotiable Invariants

1. **Zero Hard-Coded Strategy Engines**: No EMA crossover, VWAP bounce, RSI, MACD, or Supertrend hard-coded decision rules. The Brain reasons autonomously based on real multi-timeframe market evidence.
2. **Zero Broker Execution**: Hermes halts immediately upon receiving `TradeCandidate`. It never sizes positions, places orders, or interacts with a broker in this stage.
3. **Quarantine of Untrusted Web Content**: All content from TradingView charts, Sensibull option chains, or external web browsing is strictly treated as untrusted data. Prompt injection attempts and command-like strings are neutralized by `ContextSecurityValidator`.
4. **Bounded Context Budgets**: Context window is strictly bounded using the Spec Section 7 priority ranking (10 tiers) to prevent token exhaustion and distraction.
5. **Memory as Context, Never Strategy**: Hermes memory stores descriptive historical context (prior session regimes, levels, operator notes) with explicit non-rule disclaimers.
6. **Canonical Package 4 Contracts**: Consumes and produces canonical `BrainInput`, `BrainOutput`, `BrainResult`, `BrainState`, `ObservationRequest`, and `TradeCandidate`.
7. **Complete Audit Trail**: Every collaboration turn and cycle is recorded in SQLite (`data/collaboration/collaboration_audit.db`).

---

## 3. Architecture & Subsystem Implementation

### 3.1 Context & Security Subsystem (`nifty_trader/brain/context/`)
- **`ContextSecurityValidator` (`context_validator.py`)**:
  - Enforces prompt injection neutralization (strips "ignore previous instructions", "system prompt", "execute order", etc.).
  - Encapsulates untrusted browser content in structured JSON tags `<untrusted_web_data>`.
  - Enforces length caps per field (5,000 characters).
  - Validates operator instructions to ensure only authorized human sources are processed.
- **`ContextMemoryStore` (`context_memory.py`)**:
  - Thread-safe SQLite store (`data/memory/hermes_memory.db`) for long-term trader experience and observations.
  - Formats memories with explicit non-rule disclaimer: *"Descriptive context only; DO NOT interpret as hard-coded rules"*.
  - Bounded memory retrieval (top $k$ by relevance/recency, capped at 1,000 items).
- **`ContextSelector` (`context_selector.py`)**:
  - Implements Spec Section 7 priority ranking:
    1. Active Operator Instructions (Urgent/Safety)
    2. Primary Tactical Price Structure (15M)
    3. Primary Context Price Structure (1H)
    4. Active Brain State & Hypotheses
    5. Prior Cycle Pending Observation Requests
    6. Verified Derivative / Sensibull Telemetry
    7. Multi-Source Validation / Cross-Check Status
    8. Relevant Hermes Memory Context
    9. Unverified Visual / TradingView Web Observations
    10. Background Reference Data
  - Enforces character budgeting (default 12,000 characters max).
- **`HermesContextBuilder` (`context_builder.py`)**:
  - Assembles Hermes world state (market observation, browser telemetry, memory, instructions, prior brain state) into canonical `BrainInput`.

### 3.2 Hermes Collaboration Subsystem (`nifty_trader/hermes/`)
- **`HermesToolBridge` (`tool_bridge.py`)**:
  - Bridges Hermes tools (MarketObservationService, BrowserManager, InstructionRegistry, MemoryStore) to fulfill specific observation requests from the Brain.
  - Dynamically invokes Sensibull or TradingView browser workflows when requested by the Brain.
- **`HermesBrainOrchestrator` (`collaboration.py`)**:
  - Manages the multi-turn interactive collaboration loop between Hermes and the Brain.
  - Supports observation request fulfillment, multi-turn re-evaluation, prior state continuity, and wait policy integration.
  - Bounded turn count (default 3, configurable up to 10) prevents runaway reasoning loops.
  - Halts cleanly on `CANDIDATE` and dispatches trade candidate without broker interaction.
- **`CollaborationAuditStore` (`contracts.py`)**:
  - Persists all collaboration cycles and turns to SQLite (`data/collaboration/collaboration_audit.db`).

### 3.3 Core Runtime & CLI (`nifty_trader/core/runtime.py`, `nifty_trader/cli.py`)
- Integrated `HermesBrainOrchestrator` into `NiftyTraderRuntime`.
- Added CLI commands:
  - `python -m nifty_trader.cli collaborate [--symbol NIFTY] [--max-turns N] [--once]`
  - `python -m nifty_trader.cli collaborate-status [--limit N]`
