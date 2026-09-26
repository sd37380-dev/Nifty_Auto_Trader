# HERMES UPSTREAM UPDATE STRATEGY & LIFECYCLE GOVERNANCE
## Pre-Package 3 Architecture Hardening

**Product:** NIFTY Autonomous Trader  
**Component:** Upstream Platform Lifecycle Architecture  
**Status:** COMPLETE & LOCKED ✅  
**Date:** 2026-09-26  

---

## 1. Core Principle & System Boundaries

The software ecosystem consists of two independently evolving entities:

```text
OFFICIAL HERMES PLATFORM
Repository: https://github.com/NousResearch/hermes-agent.git
Local Source: D:\AI_Trading\hermes-agent
        │
        │ Upstream updates (pull only, strictly vetted)
        ▼
HERMES INTEGRATION ADAPTER LAYER
Module: nifty_trader.hermes
        │
        ▼
NIFTY AUTONOMOUS TRADER (THE PRODUCT)
Repository: D:\AI_Trading\nifty-autonomous-trader
```

### Architectural Axioms:
1. **Platform vs. Product:** Hermes is an upstream agent platform dependency. NIFTY Autonomous Trader is the standalone trading product.
2. **Never a Hard Fork:** NIFTY Autonomous Trader must never mutate into an inseparable, modified fork of Hermes.
3. **Replaceability:** Hermes versions $vX \rightarrow vY \rightarrow vZ$ must be swappable without tearing down or rewriting the trading architecture.
4. **Stable Adapter Boundary:** All product capabilities interact with Hermes exclusively through typed abstract contracts (`HermesAgentAdapter`, `HermesToolAdapter`, `HermesMemoryAdapter`), completely eliminating deep internal imports into Hermes private source code.

---

## 2. Upstream Version Manifest

All upstream dependencies are tracked deterministically in `config/hermes-version.yaml`:

```yaml
upstream:
  name: "hermes-agent"
  repository: "https://github.com/NousResearch/hermes-agent.git"
  tracked_branch: "main"
  local_source_path: "D:\\AI_Trading\\hermes-agent"
  baseline_commit: "d0288be5b3330d2442e3907185b8e9d0958297bb"
  last_verified_commit: "d0288be5b3330d2442e3907185b8e9d0958297bb"
  last_verified_date: "2026-09-26"
  verification_status: "VERIFIED"
  integration_version: "0.1.0"
```

---

## 3. Strict 14-Step Upstream Update Workflow

Upstream updates are never applied directly to production or master branches. Every candidate update must strictly traverse this pipeline:

```text
[1] Check Hermes Upstream (`nifty-trader upstream check`)
        ↓
[2] Detect New Commits & File Diffs
        ↓
[3] Fetch Upstream Commits to Reference Repo (`git fetch origin`)
        ↓
[4] Create Isolated Update Branch (`upstream/hermes-update-YYYY-MM-DD`)
        ↓
[5] Compare Changes & Impact (`nifty-trader upstream inspect`)
        ↓
[6] Identify Affected Adapter Interfaces
        ↓
[7] Run Upstream Compatibility Checks (`nifty-trader upstream test`)
        ↓
[8] Run Upstream Hermes Native Tests
        ↓
[9] Run NIFTY Trader Full Pytest Suite (`pytest tests/`)
        ↓
[10] Run Live Browser Navigation & CDP Tests (`nifty-trader browser-test`)
        ↓
[11] Run Multimodal Perception Verification (`nifty-trader browser-open --multimodal`)
        ↓
[12] Review Diff & Generate Update Report (`docs/HERMES_UPDATE_REPORT.md`)
        ↓
[13] Formal Architecture Approval & Merge
        ↓
[14] Update `config/hermes-version.yaml` & Create Tagged Product Release
```

---

## 4. Branch Strategy

```text
master (Locked, verified production builds)
│
├── package/* (Feature packages under active development)
│
└── upstream/hermes-update-YYYY-MM-DD (Temporary staging branch for vetting Hermes updates)
```

- **Rule:** Never test unverified upstream updates on `master`.
- **Rule:** If compatibility fails on `upstream/hermes-update-*`, abort and rollback cleanly without affecting ongoing work.

---

## 5. Non-Negotiable Upstream Invariants

An upstream Hermes update must **NEVER** automatically:
1. Enable live brokerage trading or instantiate live order dispatchers.
2. Alter, bypass, or weaken deterministic risk limits (1% risk, ₹5,000 daily loss limit).
3. Overwrite or modify trading strategies, rules, or setups.
4. Truncate, wipe, or reset SQLite databases, experience journals, trade history, or post-mortems.
5. Force an unverified model provider change.
6. Expose environment secrets or API keys.
7. Disable runtime safety checks or policy guards.
