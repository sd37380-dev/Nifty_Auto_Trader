# Package 3 — Implementation Plan: Market Perception & 1H/15M Observation Engine

## 1. Executive Summary

Package 3 equips **NIFTY Autonomous Trader** with institutional-grade market perception capabilities. Operating under the strict invariant of **"SEE THE MARKET, DO NOT TRADE THE MARKET"**, this package provides:

1. **Multi-Timeframe Market Data Pipeline:** Strict 1H (macro context/regime) and 15M (tactical state) numerical candle ingestion.
2. **Provider Abstraction & Dual Feeds:** Abstract `MarketDataProvider` decoupling vendors; primary live `YahooFinanceProvider` (`^NSEI`) and offline deterministic `MockMarketDataProvider`.
3. **Local SQLite Incremental Storage:** High-performance local caching (`data/market/market_cache.db`) with zero network duplicate overhead.
4. **Exchange Schedule & Clock Management:** Real-time Asia/Kolkata exchange tracking (`09:15-15:30 IST`) and periodic candle closure timers.
5. **Cross-Check Validation:** Cross-referencing visual chart prices (TradingView via CDP) against numerical close feeds (< 0.5% tolerance).
6. **Manual Agent Steering Subsystem:** First-class persistent operator instruction box with non-negotiable safety policy validation.
7. **Cognitive Perception Synthesis:** Synthesizing factual market observations for Gemini 2.5/3.5 reasoning without trade recommendations.

---

## 2. Invariants & Scope Boundaries

* **Timeframe Boundaries:** STRICTLY 1H and 15M candles. No 1M, 5M, or tick feeds.
* **Symbol Boundaries:** NIFTY 50 index (`^NSEI`).
* **Non-Trading Guarantee:** ZERO order placement, ZERO signals (BUY/SELL), ZERO stop loss / profit target calculations, ZERO broker execution.
* **Upstream Protection:** Zero modifications to `C:\Users\Administrator\AppData\Local\hermes\` or pristine `D:\AI_Trading\hermes-agent`.
* **State Machine Guard:** System operates in `OBSERVE_1H` and `OBSERVE_15M` states. Progression to `DETECT_SETUP` or execution is locked until Package 4.

---

## 3. Component Architecture & Modules

```text
nifty_trader/
├── market_data/
│   ├── models.py         # Candle (OHLC validation), Timeframe, Session, Events
│   ├── base.py           # MarketDataProvider abstract base class
│   ├── cache.py          # SQLite engine for candle persistence & incremental sync
│   ├── session.py        # Indian market session manager (Asia/Kolkata)
│   ├── clock.py          # Deterministic candle completion & boundary timer
│   ├── events.py         # Async event bus for CANDLE_CLOSED & session shifts
│   ├── cross_check.py    # Visual vs numerical price alignment validator
│   ├── observation.py    # MarketObservation & MarketPerceptionOutput schemas
│   ├── service.py        # Orchestrating MarketObservationService
│   └── providers/
│       ├── yahoo.py      # Live Yahoo Finance v8 chart ingestion
│       └── mock.py       # Deterministic test series generator
└── instruction/
    ├── models.py         # AgentInstruction, InstructionPriority, Status
    ├── storage.py        # SQLite persistent instruction store
    └── manager.py        # Safety validation, lifecycle, and LLM context formatting
```

---

## 4. Verification Deliverables

* 67 passing unit tests spanning all modules (`pytest tests/ -v`).
* Live CLI commands:
  - `python -m nifty_trader.cli market-status`
  - `python -m nifty_trader.cli market-sync`
  - `python -m nifty_trader.cli market-observe`
  - `python -m nifty_trader.cli instruction <text> [--priority]`
  - `python -m nifty_trader.cli instruction-list`
