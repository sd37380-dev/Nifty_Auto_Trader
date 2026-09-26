# UPGRADE, MIGRATION & ROLLBACK GOVERNANCE
## Preserving Trader Experience, History, and System Invariants

**Product:** NIFTY Autonomous Trader  
**Version:** 0.1.0  
**Status:** LOCKED ✅  
**Date:** 2026-09-26  

---

## 1. Upstream Upgrade Procedure

When upgrading the upstream Hermes dependency from verified commit $A$ to candidate commit $B$:

1. **Safety Audit:** Run `nifty-trader upstream check` to identify commit delta and file changes.
2. **Branch Isolation:** Checkout a staging branch `upstream/hermes-update-YYYY-MM-DD`.
3. **Execution of Automated Test Suite:**
   ```powershell
   venv\Scripts\pytest tests/ -v
   python -m nifty_trader.cli upstream test
   python -m nifty_trader.cli browser-test
   python -m nifty_trader.cli browser-open "https://in.tradingview.com/symbols/NSE-NIFTY/" --multimodal
   ```
4. **Approval & Manifest Update:** Update `config/hermes-version.yaml` (`last_verified_commit`, `last_verified_date`) and update `config/release-manifest.yaml`.
5. **Merge to Master:** Fast-forward or merge branch into `master`.

---

## 2. Reversible Rollback Protocol

If an upstream Hermes update introduces regressions, breaks browser automation, or disrupts ModelRouter capabilities:

1. **Immediate Abort:** If on staging branch, terminate testing and discard the branch.
2. **Reverting Verified Commit:** Reset `last_verified_commit` in `config/hermes-version.yaml` to the prior known-good commit:
   ```yaml
   baseline_commit: "d0288be5b3330d2442e3907185b8e9d0958297bb"
   last_verified_commit: "d0288be5b3330d2442e3907185b8e9d0958297bb"
   ```
3. **Local Source Reset:**
   ```powershell
   cd D:\AI_Trading\hermes-agent
   git checkout d0288be5b3330d2442e3907185b8e9d0958297bb
   ```
4. **Verification:** Run `nifty-trader upstream test` to confirm clean restoration.

---

## 3. Configuration Migration Strategy

To prevent user friction, configuration changes never force manual file rewrites:
- Every configuration file declares a `schema_version` (e.g. `1.0.0`).
- The `ConfigMigrationManager` (in `nifty_trader.features.migrations`) applies sequential migrations ($v1.0.0 \rightarrow v1.1.0$) automatically when older configurations are loaded.
- Default safety policy constraints are preserved across migrations unless explicitly relaxed by the user.

---

## 4. Database Migration & Memory Preservation Invariants

A trader's experience is irreplaceable. Upgrades must **NEVER** reset or delete historical records.

### Whitelisted Tables Protected from Destruction:
1. `trade_history` — Every paper trade order, fill, and execution record.
2. `paper_positions` — Active and closed paper account holdings.
3. `experience_journal` — Market observations, contextual setups, and AI reflections.
4. `post_mortems` — Detailed analyses of trading mistakes and lessons learned.
5. `strategy_versions` — Historical strategy performance records.

### Defensive Guardrails:
- The `DatabaseMigrationManager.verify_preservation_rules()` actively inspects SQL migration scripts.
- Any migration script containing `DROP TABLE` or `TRUNCATE` targeting whitelisted tables is **aborted immediately** with a fatal error.
- Upgrades are restricted strictly to non-destructive schema additions: `ALTER TABLE ... ADD COLUMN`, new table creations, or new indexing.

---

## 5. Strategy Version Preservation

- Strategies evolve incrementally: $v1.0 \rightarrow v1.1 \rightarrow v1.2$.
- Upgrading the application software must never overwrite, modify, or replace an active approved strategy.
- Strategy changes require explicit manual user promotion within the future StrategyLab governance framework (Package 14).
