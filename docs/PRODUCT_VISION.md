# NIFTY AUTONOMOUS TRADER — PRODUCT VISION

**Document:** `docs/PRODUCT_VISION.md`  
**Product Name:** NIFTY Autonomous Trader  
**Version:** 0.1.0-alpha (Phase 0 Architecture)  
**Status:** Approved Architectural Vision  

---

## 1. Executive Summary

**NIFTY AUTONOMOUS TRADER** is an autonomous AI trading research, observation, and paper-trading software application.

Unlike conventional algorithmic bots that execute rigid mathematical rules or naive "LLM signal generators" that ask an AI every minute whether to buy or sell, **NIFTY Autonomous Trader** is designed to emulate the behavior, discipline, and reflective learning of an expert human discretionary trader sitting in front of a computer workstation.

```
       HUMAN DISCRETIONARY TRADER MODEL
                      ↓
  OBSERVE     → Monitor 1H market structure & 15M candle action
  UNDERSTAND  → Contextualize price action against key reaction levels
  RESEARCH    → Cross-reference macroeconomic context & news sentiment
  WAIT        → Default state; patient observation until high-probability setup
  DETECT      → Recognize predefined structural setup
  PLAN        → Calculate strict entry, invalidation (SL), and target (TP)
  RISK CHECK  → Deterministic mathematical validation (R:R ≥ 1:2, exposure limit)
  PAPER TRADE → Execute simulated fill with realistic slippage/broker model
  MONITOR     → Supervise trade lifecycle and active trailing rules
  EXIT        → Orderly closure at target, invalidation, or session close
  ANALYZE     → Rigorous post-trade post-mortem comparing execution vs. plan
  LEARN       → Identify mistakes, cognitive biases, or regime shifts
  IMPROVE     → Propose formal strategy hypotheses for laboratory backtesting
  OBSERVE     → Return to patient market observation
```

---

## 2. Core Architectural Pillars

```
┌────────────────────────────────────────────────────────────────────────┐
│                        NIFTY AUTONOMOUS TRADER                         │
├────────────────────────────────┬───────────────────────────────────────┤
│ 1. HERMES ORCHESTRATOR         │ Autonomous agent loop, computer use,  │
│    (Operator / Hands)          │ tool execution, scheduling, state     │
├────────────────────────────────┼───────────────────────────────────────┤
│ 2. MODEL ROUTER                │ Decoupled AI reasoning engine routing │
│    (Cognitive Brain)           │ tasks to Gemini, OpenRouter, or local │
├────────────────────────────────┼───────────────────────────────────────┤
│ 3. DETERMINISTIC ENGINE        │ Strict mathematical indicators, risk  │
│    (Rules / Gatekeeper)        │ limits, position sizing, paper fills  │
├────────────────────────────────┼───────────────────────────────────────┤
│ 4. BROWSER & COMPUTER TOOLS    │ Chrome/Puppeteer/CDP automation for   │
│    (Sensory Perception)        │ visual chart and DOM inspection       │
├────────────────────────────────┼───────────────────────────────────────┤
│ 5. TRADER MEMORY               │ Structured SQLite/JSON journal of     │
│    (Experience / Context)      │ market conditions, setups, and lessons│
├────────────────────────────────┼───────────────────────────────────────┤
│ 6. STRATEGY LABORATORY         │ Controlled self-improvement pipeline: │
│    (Evolution / Backtesting)   │ Post-mortem → Hypothesis → Validation │
└────────────────────────────────┴───────────────────────────────────────┘
```

---

## 3. Product Principles & Philosophy

### Principle I: The Agent Must Be Patient ("WAIT" as First-Class Action)
The single greatest failure mode of retail traders and naive AI trading systems is **overtrading**. In this product:
- The default action on every assessment is **`WAIT`**.
- The system assesses market conditions only at deliberate structural milestones (e.g. 15-minute candle completion, 1-hour candle completion, or high-impact volatility breakout).
- Doing nothing while waiting for a confirmed setup is considered optimal behavior.

### Principle II: Deterministic Risk Gates Over AI Discretion
AI models are creative, contextual, and probabilistic—making them exceptional at perceiving nuanced patterns and market sentiment. However, they are prone to hallucination, emotional drift, and mathematical inconsistency.
- **AI proposes trade setups.**
- **Deterministic math approves or rejects trades.**
- No trade plan can bypass hardcoded rules: maximum risk per trade (e.g., 1% of equity), maximum daily loss limit, maximum drawdown, minimum Risk-to-Reward ratio (1:2), and session time limits.

### Principle III: Multi-Timeframe Discipline (1H Context + 15M Setup)
To eliminate noise and high-frequency friction:
- **1-Hour (1H) Timeframe:** Governs broader market context, trend regime (bullish/bearish/neutral), major support/resistance zones, and daily volatility baseline.
- **15-Minute (15M) Timeframe:** Governs localized price action, setup formation, entry triggers, stop-loss invalidation levels, and trade management.
- Scalping timeframes (1M, 3M, 5M, ticks) are strictly forbidden in initial phases.

### Principle IV: Controlled Self-Improvement (No Uncontrolled Live Tweaks)
Trading systems that alter their live strategy rules dynamically in response to single losses inevitably curve-fit and blow up.
- **Post-trade reflection produces hypotheses, NOT live changes.**
- Any proposed improvement must graduate through a formal pipeline:
  `Post-Mortem → Pattern Aggregation → Formal Proposal → Historical Backtesting → Out-of-Sample Paper Validation → Human Review & Approval → Versioned Strategy Deployment`.

### Principle V: Independence from Pre-Installed Host Environments
The software must be a standalone, distributable product:
- It maintains its own isolated virtual environment, configuration, and data stores.
- It operates completely independently of any host Hermes installations (`C:\Users\Administrator\AppData\Local\hermes\`).

---

## 4. Operational Modes

The product provides three distinct operational modes:

1. **Research & Observation Mode (Default / Phase 1):**
   - Continuously observes NIFTY 1H and 15M price action via browser charts.
   - Evaluates market context and records detailed observations.
   - Generates trade hypotheses and setup logs.
   - **Zero orders are placed.**

2. **Paper Trading Mode (Phase 2):**
   - Extends Research Mode by executing simulated fills via an internal paper broker.
   - Simulates realistic slippage, liquidity delays, and statutory exchange fees.
   - Tracks portfolio equity, margin, drawdowns, and real-time MTM.
   - Produces rigorous post-trade journals.

3. **Live Trading Mode (Future / Strictly Gated):**
   - Connects to approved broker APIs (e.g., DhanHQ) via authenticated endpoints.
   - Implements multi-signature or explicit human authorization barriers.
   - Strictly disabled by default in software configuration.

---

## 5. Long-Term Success Criteria

The ultimate vision of NIFTY Autonomous Trader is achieved when an operator can start the software on an ordinary PC, leave it unattended during Indian market hours (09:15 to 15:30 IST), and observe:
1. The agent autonomously opens its chart workspace and inspects NIFTY structure.
2. The agent waits patiently across hours of choppy sideways action without placing low-quality trades.
3. Upon detecting a high-confluence 15M setup aligned with 1H trend, it generates a comprehensive, risk-checked trade plan.
4. It logs and executes the trade in its paper account, trailing stops deterministically.
5. At the close of the trading session, it generates a human-readable debrief, updates its experience database, and shuts down safely.
