# FEATURE EXTENSION ROADMAP & OWNERSHIP REGISTRY
## NIFTY Autonomous Trader Architecture Extension Framework

**Product:** NIFTY Autonomous Trader  
**Version:** 0.1.0  
**Status:** LOCKED ✅  
**Date:** 2026-09-26  

---

## 1. Architectural Philosophy of Feature Extensions

The NIFTY Autonomous Trader core runtime is designed to be modular and extensible. Every future capability is defined as an isolated `FeatureModule` with explicit:
1. **Ownership Boundaries:** Feature packages do not reach into or mutate other feature internals.
2. **Declared Dependencies:** A feature cannot start unless all prerequisite dependencies are installed, enabled, and healthy.
3. **Independent Versioning:** Feature module versions evolve independently from upstream Hermes versions.
4. **Lifecycle State Control:** Support for `PLANNED`, `INSTALLED`, `ENABLED`, `DISABLED`, `EXPERIMENTAL`, `DEPRECATED`, and `REMOVED`.

---

## 2. Feature Extension Points

| Feature ID | Extension Name | Target Package | Status | Prerequisite Dependencies | Ownership Module | Description |
|---|---|---|---|---|---|---|
| `EXT-01` | **Model Router & Brain** | Package 1 | **LOCKED ✅** | Core Runtime | `nifty_trader.router` | Multi-tier LLM router with fallback circuits and Gemini provider. |
| `EXT-02` | **Browser Automation** | Package 2 | **LOCKED ✅** | `EXT-01` | `nifty_trader.browser` | Chrome CDP automation for real website and chart inspection ("Eyes + Hands"). |
| `EXT-03` | **Upstream Hardening** | Pre-Pkg 3 | **LOCKED ✅** | `EXT-01`, `EXT-02` | `nifty_trader.hermes` | Hermes compatibility layer, version manifest, and feature extension registry. |
| `EXT-04` | **Market Data & Candle Engine** | Package 3 | `PLANNED` | None | `nifty_trader.market_data` | Multi-timeframe 1H + 15M candle ingestion and numerical data pipeline. |
| `EXT-05` | **Historical Data Store** | Package 3 | `PLANNED` | `EXT-04` | `nifty_trader.market_data.history` | Offline tick/candle repository for historical calibration. |
| `EXT-06` | **Research & Web News Engine** | Package 3/4 | `PLANNED` | `EXT-02` | `nifty_trader.research` | Macroeconomic calendar, sentiment, and financial news parser. |
| `EXT-07` | **Autonomous Waiting Engine** | Package 5 | `PLANNED` | `EXT-01`, `EXT-04` | `nifty_trader.observer` | Patience and observation scheduler between trading windows. |
| `EXT-08` | **Trading Strategy Engine** | Package 6 | `PLANNED` | `EXT-04`, `EXT-01` | `nifty_trader.strategy` | Discretionary setup detector and trade plan generator. |
| `EXT-09` | **Deterministic Risk Engine** | Package 7 | `PLANNED` | `EXT-08` | `nifty_trader.risk` | Inviolable mathematical gate evaluating equity risk and stop losses. |
| `EXT-10` | **Paper Broker & Ledger** | Package 8 | `PLANNED` | `EXT-09` | `nifty_trader.broker.paper` | Simulated order execution, slippage modeling, and paper account ledger. |
| `EXT-11` | **Position Monitor & Trailing** | Package 9 | `PLANNED` | `EXT-10` | `nifty_trader.broker.monitor` | Dynamic trailing stop and intraday square-off manager. |
| `EXT-12` | **Trader Experience Memory** | Package 10 | `PLANNED` | `EXT-10` | `nifty_trader.memory` | Persistent SQLite journal storing trade logs, setups, and market context. |
| `EXT-13` | **Post-Mortem & Mistake Analysis**| Package 11 | `PLANNED` | `EXT-12` | `nifty_trader.analysis` | Self-reflective learning analyzing winning and losing trades. |
| `EXT-14` | **StrategyLab & Learning Engine** | Package 12 | `PLANNED` | `EXT-13` | `nifty_trader.lab` | Hypothesis generator and strategy calibration incubator. |
| `EXT-15` | **Backtesting & Validation Engine**| Package 13 | `PLANNED` | `EXT-14`, `EXT-05` | `nifty_trader.backtest` | Historical replay and stress-testing simulator. |
| `EXT-16` | **Strategy Version Governance** | Package 14 | `PLANNED` | `EXT-14` | `nifty_trader.governance` | Immutable strategy registry with explicit rollback mechanisms. |
| `EXT-17` | **Interactive Dashboard** | Package 16 | `PLANNED` | `EXT-10`, `EXT-12` | `nifty_trader.ui` | Web/desktop UI for real-time monitoring and trader controls. |
| `EXT-18` | **Alerts & Notification Engine** | Package 16 | `PLANNED` | `EXT-10` | `nifty_trader.notifications` | Telegram/Discord/Webhook dispatch for key trading events. |
| `EXT-19` | **Voice Interface** | Package 16 | `PLANNED` | `EXT-17` | `nifty_trader.voice` | Natural language voice queries for trader status. |
| `EXT-20` | **Broker Interface Abstraction** | Package 8 | `PLANNED` | `EXT-09` | `nifty_trader.broker.base` | Common interface shared by paper and live execution engines. |
| `EXT-21` | **Optional Live Broker Connector**| Package 19 | `DISABLED` | `EXT-20`, `EXT-09` | `nifty_trader.broker.live` | Future real-money live broker adapter (strictly disabled until approved). |

---

## 3. Dependency Graph Topology

```text
Core Runtime
     │
     ├── ModelRouter [EXT-01]
     │        │
     │        ├── Gemini Brain [EXT-01]
     │        │        │
     │        └── Browser Agent [EXT-02] ──► Research/News [EXT-06]
     │
     └── Market Data [EXT-04]
              │
              ├── Strategy Engine [EXT-08]
              │        │
              │        └── Risk Engine [EXT-09]
              │                 │
              │                 └── Paper Broker [EXT-10]
              │                          │
              │                          ├── Position Monitor [EXT-11]
              │                          │
              │                          └── Memory Store [EXT-12]
              │                                   │
              │                                   └── Post-Mortem [EXT-13]
              │                                            │
              │                                            └── Strategy Lab [EXT-14]
              │                                                     │
              │                                                     └── Backtesting [EXT-15]
              └── (Future Live Broker [EXT-21] — DISABLED)
```
