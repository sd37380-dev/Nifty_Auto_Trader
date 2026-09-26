# PACKAGE 1 IMPLEMENTATION PLAN — HERMES BUILD + MODEL ROUTER

**Document:** `docs/PACKAGE1_PLAN.md`  
**Package:** Package 1  
**Status:** Approved & Implementing  
**Created:** 2026-09-26  

---

## 1. Objective

Package 1 establishes the independent runtime and the decoupled cognitive brain for the NIFTY Autonomous Trader.

```
Official Hermes Source
        ↓
Independent Build (Dedicated venv)
        ↓
Nifty Autonomous Trader Runtime
        ↓
ModelRouter
        ↓
Gemini Provider (Primary Brain)
        ↓
Future Providers (OpenRouter, OpenAI, Anthropic, Local)
```

---

## 2. Key Architecture Refinements (from User Directives)

1. **Perception Hierarchy:**
   - Real websites and web/news (via Computer/Browser tools) remain the authoritative visual and research source.
   - The local chart renderer is strictly an auxiliary verification/data tool, never replacing the agent's ability to browse like a human.
2. **Safety Policies vs. Strategy:**
   - Numerical risk limits (`Risk ≤ 1%`, `R:R ≥ 1:2`, `₹5,000 daily loss`, `3 trades/day`) are configurable safety-policy placeholders, not hardcoded strategies.
   - The AI brain remains completely free to conclude: **`NO_TRADE`** even when a technically valid setup exists.
3. **No Premature Implementation:**
   - Package 1 strictly excludes market feeds, candles, signals, paper broker, and live trading.

---

## 3. Package 1 Deliverables

| Module | Location | Purpose |
|---|---|---|
| **Base Router Types** | `nifty_trader/router/base.py` | `ModelProvider` ABC, `TaskTier` enum, structured response wrappers. |
| **Gemini Provider** | `nifty_trader/router/gemini.py` | Native Google GenAI integration with strict Pydantic JSON schemas. |
| **OpenRouter Provider** | `nifty_trader/router/openrouter.py` | Multi-model routing provider via OpenAI-compatible endpoint. |
| **OpenAI & Anthropic Providers**| `nifty_trader/router/openai_provider.py`, `anthropic_provider.py` | Pluggable providers ready for future model expansion. |
| **Model Router Engine** | `nifty_trader/router/router.py` | Task-tier dispatch, fallback cooldowns, resilience. |
| **Runtime Core** | `nifty_trader/core/runtime.py` | Autonomous runtime initializing ModelRouter and session context. |
| **CLI Dispatcher** | `nifty_trader/cli.py` | Turnkey commands: `start`, `status`, `test-brain`. |
| **Configuration** | `config/models.yaml`, `config/settings.yaml` | Task mappings, provider credentials, and risk policy placeholders. |
| **Test Suite** | `tests/test_model_router.py`, `tests/test_runtime.py` | Unit and integration tests verifying Gemini connectivity and routing. |

---

## 4. Verification Milestone

Package 1 is successful when:
1. `pytest` passes 100% of router and runtime unit tests in the clean virtualenv.
2. `nifty-trader test-brain` queries Gemini through `ModelRouter` and receives valid structured reasoning matching the Pydantic schema.
3. Fallback mechanics successfully switch providers if a simulated failure occurs.
