# NIFTY Autonomous Trader

Autonomous AI Trading Research and Paper-Trading Software based on Hermes Agent capabilities.

---

## 1. Overview

The **NIFTY Autonomous Trader** is an enterprise-grade autonomous trading and research system designed around a fundamental principle: **the strict separation of cognitive artificial intelligence, deterministic safety gates, execution mechanics, and isolated quantitative research**.

### Key System Capabilities:
* **Hermes Autonomous Operator Engine:** Operates the software like a disciplined human trader.
* **ModelRouter:** Provider-agnostic LLM reasoning router supporting Google Gemini, OpenRouter, and local fallback.
* **Multimodal Perception Layer:** Dual perception combining TradingView high-resolution visual screenshots with Sensibull option chain matrix DOM scraping.
* **Deterministic Safety Guard:** Non-bypassable circuit breakers enforcing hard ₹-caps on loss per trade, daily cumulative loss stops, maximum lot ceilings, and time-of-day filters.
* **Sensibull Virtual Broker:** Direct DOM paper execution and continuous position lifecycle management inside the Sensibull Virtual Portfolio.
* **Autonomous Trade Monitoring:** Continuously tracks open positions, triggers AI Brain reassessments on material price movement, and handles trailing stops and emergency square-offs.
* **Performance Analysis & Experience Memory:** Post-trade empirical post-mortems extracting structured lessons without modifying code or strategy rules.
* **Hermes Data Research Zone (Completely Segregated):** An isolated quantitative research laboratory featuring a Dhan Broker Data Adapter (offline mock + future live plug-in), Data Engineering pipeline (resampling and technical features), empirical hypothesis backtesting, aggressive contradiction search, and dynamic segment scoring.

---

## 2. System Architecture

```text
                         HERMES
                           │
                           ▼
                  AUTONOMOUS ORCHESTRATOR
                           │
          ┌────────────────┼─────────────────┐
          │                │                 │
          ▼                ▼                 ▼
     Market Data       Browser/Visual     Memory
          │                │                 │
          ▼                ▼                 ▼
      Market           TradingView       Experience
    Perception         Sensibull          Context
          │                │
          └────────┬───────┘
                   ▼
          Unified Market Observation
                   │
                   ▼
          Autonomous Observation
             & Waiting Engine
                   │
                   ▼
           Trading Brain / LLM
            Reasoning Engine
                   │
                   ▼
             Hermes Synthesis
                   │
                   ▼
             Trade Candidate
                   │
                   ▼
             Safety Guard (Deterministic Circuit Breakers)
                   │
                   ▼
          Sensibull Paper Trading
                   │
                   ▼
          Position Monitoring
                   │
                   ▼
          Completed Trade
                   │
                   ▼
          Performance Analysis
                   │
                   ▼
           Experience Memory
```

---

## 3. Installation & Build

### Prerequisites
* Python 3.11+
* Google Chrome installed on host system (for CDP visual perception)

### Setup & Editable Install
```powershell
# Clone or navigate to the directory
cd d:\AI_Trading\nifty-autonomous-trader

# Activate virtual environment
.\venv\Scripts\Activate.ps1

# Install package and build executable CLI
pip install -e .
```

---

## 4. Command-Line Interface (CLI)

The software provides the `nifty-trader` command-line executable (or `python -m nifty_trader.cli`):

### Core Runtime & Brain Reasoning
```powershell
nifty-trader status                # System status, provider health, risk constraints
nifty-trader test-brain            # Test ModelRouter reasoning with Gemini
nifty-trader browser-login         # Secure manual login to Sensibull and TradingView
nifty-trader market-observe        # Capture multi-source observation and price cross-checks
nifty-trader brain-analyze         # Full market observation + AI Brain reasoning
nifty-trader collaborate           # Run multi-turn collaborative trading inquiry
```

### Sensibull Paper Execution & Position Monitoring
```powershell
nifty-trader paper-status          # Check Sensibull paper trading status & open P&L
nifty-trader paper-positions       # List active virtual positions
nifty-trader paper-order --strike 25300 --type CE --action BUY --lots 1
nifty-trader position-monitor      # Run autonomous position monitoring pass
nifty-trader position-history      # List monitored position lifecycle records
```

### Experience Memory & Performance Analysis
```powershell
nifty-trader performance-summary   # Win rate, profit factor, operational counts
nifty-trader performance-trades    # Multidimensional evaluation of completed trades
nifty-trader experience-search --tag BREAKOUT
```

### Hermes Data Research Zone (Isolated Laboratory)
```powershell
nifty-trader research status       # Operational status, Dhan adapter, memory stats
nifty-trader research dataset --symbol NIFTY --timeframe 15M --days 15
nifty-trader research run --topic "NIFTY Momentum & Volatility Breakout Study"
nifty-trader research assessment   # Dynamic assessment and segment importance weights
nifty-trader research memory       # Verified findings and negative knowledge catalog
nifty-trader research history      # Audit progression history of empirical inquiries
```

---

## 5. Testing & Verification

Run the comprehensive unit, integration, and regression test suite:
```powershell
pytest -v
```

All 212 tests pass with 100% compliance across all 10 stages and the research zone.

---

## 6. Safety & Operating Invariants
1. **Live Broker Trading Disabled:** Live trading is permanently disabled. Execution is confined strictly to the Sensibull Virtual Portfolio.
2. **Deterministic Circuit Breakers:** The AI Brain cannot bypass risk caps or execute unauthorized trades.
3. **Dynamic Segment Scoring:** Research assessments enforce context-dependent dynamic importance scoring with strictly NO fixed percentage weights.
4. **Physical DB Segregation:** Research databases reside strictly in `data/hermes_research/` with zero dependencies on live trading data.
