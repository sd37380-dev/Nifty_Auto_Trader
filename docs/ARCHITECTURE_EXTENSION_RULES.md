# ARCHITECTURE EXTENSION RULES & ENGINEERING DISCIPLINE
## Rules for Future Feature Development and Upstream Integration

**Product:** NIFTY Autonomous Trader  
**Version:** 0.1.0  
**Status:** LOCKED ✅  
**Date:** 2026-09-26  

---

## 1. The Strict 10-Step Feature Introduction Pipeline

No feature may be merged or developed in an ad-hoc manner. Every new capability must traverse these exact engineering phases:

```text
[1] NEW FEATURE CONCEPT & SCOPE PROPOSAL
        ↓
[2] DEFINE STABLE ABSTRACT INTERFACE (ABC / Pydantic schema)
        ↓
[3] DEFINE OWNERSHIP & PACKAGE BOUNDARY (Separate namespace)
        ↓
[4] DECLARE PREREQUISITE DEPENDENCIES (`config/features.yaml`)
        ↓
[5] DEFINE CONFIGURATION SCHEMA & DEFAULT CONSTRAINTS
        ↓
[6] DEFINE UNIT & INTEGRATION TEST SPECIFICATIONS
        ↓
[7] IMPLEMENT FEATURE LOGIC
        ↓
[8] EXECUTE TEST SUITE & MULTIMODAL VERIFICATION
        ↓
[9] INCREMENT INDEPENDENT FEATURE VERSION
        ↓
[10] UPDATE STATUS TO LOCKED IN PROJECT ROADMAP
```

---

## 2. The Anti-Rewrite Doctrine

Future upstream Hermes platform releases or new feature expansions must **NEVER** serve as an excuse to redesign or rewrite the core application. 

Always exhaust the four standard structural solutions before even proposing an architectural revision:

```text
       ┌───────────┐
       │  ADAPTER  │  Wrap external or upstream protocol variations
       └─────┬─────┘
             │
       ┌─────▼─────┐
       │ INTERFACE │  Expose typed contracts to decouple caller from implementation
       └─────┬─────┘
             │
       ┌─────▼─────┐
       │ MIGRATION │  Adapt legacy schemas and configurations sequentially
       └─────┬─────┘
             │
       ┌─────▼─────┐
       │ EXTENSION │  Plug new capabilities via FeatureModule lifecycle contracts
       └───────────┘
```

A full rewrite requires explicit architectural justification and multi-step stakeholder approval.

---

## 3. Upstream Code Re-Use vs. Anti-Duplication Rule

Do **NOT** duplicate upstream Hermes functionality inside `nifty_trader/`. 
Do not create competing, shadow implementations of:
- Headless browser automation core protocols
- Model client dispatch loops
- MCP (Model Context Protocol) communication pipelines
- Low-level computer use interfaces
- Basic agent tool dispatchers

Always reuse upstream platform capabilities through the `nifty_trader.hermes.adapter` layer where practical.

---

## 4. Safe Feature Rollout Lifecycle

Every feature extension adheres to explicit lifecycle states declared in `config/features.yaml`:

```text
     ┌───────────┐
     │  PLANNED  │  Documented on roadmap; no execution code exists yet
     └─────┬─────┘
           │
           ▼
     ┌───────────┐
     │ INSTALLED │  Code present and tested, but inactive in production
     └─────┬─────┘
           │
           ├─────────────────────────┐
           ▼                         ▼
     ┌───────────┐             ┌──────────────┐
     │  ENABLED  │             │ EXPERIMENTAL │  Active only in explicit test flags
     └─────┬─────┘             └──────┬───────┘
           │                          │
           └────────────┬─────────────┘
                        ▼
                  ┌────────────┐
                  │ DEPRECATED │  Scheduled for sunset; warning on startup
                  └─────┬──────┘
                        │
                        ▼
                  ┌────────────┐
                  │  REMOVED   │  Uninstalled from registry and runtime
                  └────────────┘
```

**Safety Invariant:** `EXPERIMENTAL` or `DISABLED` features (such as live broker integration) can never automatically become active in production.
