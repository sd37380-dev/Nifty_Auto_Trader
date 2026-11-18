# Project Audit — NIFTY Historical Research Handover

Audit date: 2026-09-29. Scope: source, research/backtest path, tests, and supplied `data/hermes_research/market_data.db`. No strategy parameters or trading code were changed during this initial audit.

## Architecture

- `nifty_trader/market_data/` provides runtime market-data models/providers and caching.
- `nifty_trader/observation/`, `brain/`, and `autonomous/` combine broker/browser observations with model-driven decisions.
- `paper/` and `safety/` handle paper orders and deterministic operational risk checks.
- `research_zone/` contains the Dhan adapter abstraction, SQLite market store, feature engineering, research engine, and persistence. The checked-in database is in `data/hermes_research/market_data.db`.
- `strategies/short/` contains the separate deterministic Futures-short prototype: contracts, historical/live providers, indicators, OI resistance, pivots, strategy, approval, and backtest engine.
- `scripts/` and `research/` contain exploratory and validation/backtest scripts. Existing tests live under `tests/`.

## Existing strategy and calculations

The deterministic strategy currently implements SHORT only. It derives ATM and ATM ±5 from `snapshot.futures_price`, chooses call OI resistance using normalized OI, positive change-in-OI, and proximity, chooses the nearest of P/R1/R2, requires 20-point level confluence, bearish EMA20/EMA50 alignment plus declining EMA20, price within 0.25 ATR below EMA20, and a red candle whose high enters the resistance zone and close falls below it. SL is rejection-candle high + 5; target is based on 2R.

EMA uses an initial SMA seed and recursive smoothing. ATR uses true range with Wilder smoothing. Pivot calculations use prior OHLC. ATM is recalculated from the current `snapshot.futures_price` and the engine builds 11 strikes at 50-point increments. This is causally usable if supplied verified historical Futures at each timestamp; current provider does not prove instrument provenance. Exact halfway values use Python's ties-to-even rule (one of two equally near strikes). The OI selector has a fallback to the 11 closest strikes when ATM-matched strikes are absent; it does not verify expiry or whether a selected call strike is an overhead level.

The runtime provider gets broker bars and a current option chain. The historical provider sorts candles and exposes a prefix through its mutable index. Its original date-key fallback could reuse an observation without proving its time; it now requires exact timestamp equality and refuses stale/future/missing/empty chain data. It accepts arbitrary candles; the database's NIFTY series is Spot/Index from the recorded Dhan `IDX_I` + `INDEX` loader path, not Futures.

## Existing backtest behavior

`strategies/short/backtest.py` evaluates at candle close, queues an entry for the next candle open, applies configurable point slippage to fills, tests stop before target within a bar, applies charges, and constrains the engine to one active position. It now requires a timestamp-exact historical option snapshot at every replay candle, non-empty strikes, and at least one positive CE and PE OI value; missing/stale/future/empty/zero-OI snapshots fail readiness. It still does not validate per-strike ATM ±5 OI completeness, expiry identity, source provenance, or Futures instrument identity. The Pydantic option model defaults absent OI to zero, so ingestion must preserve field presence or fail before normalization. The report is SHORT-only and its trade schema omits signal time, ATM, expiry, and several requested audit fields. Its date filter runs after pending-entry state is created, so boundary behavior deserves a dedicated test.

The claimed full-cost behavior is incomplete in accounting: fill slippage is already embedded in gross P&L, while a separate slippage field is calculated and reported but not subtracted again (correct for avoiding double charge); `total_charges` excludes slippage, which is only in `total_slippage`. Current yearly/long/short, regime, ablation, OOS, walk-forward, and sensitivity reporting is not implemented by this engine.

## Dataset and source inventory

The SQLite store has `raw_payloads`, `normalized_bars`, and `feature_sets`; it has no options-chain, contract master, expiry, or strike snapshot table. `raw_payloads` is empty. The repository's data loader explicitly stores NIFTY Spot/Index using Dhan security ID 13 / `IDX_I` / `INDEX`; 5M OI is always zero. The rolling ATM CE/PE series include OHLCV and OI, but not resolved strike/expiry or change OI. See [DATA_AUDIT.md](DATA_AUDIT.md), [DATA_QUALITY_REPORT.md](DATA_QUALITY_REPORT.md), and [backtest_data_requirements.json](research/validation/backtest_data_requirements.json).

## Phase 3 & 4 — Broker Acquisition & Expired Contract Data Investigation

The configured broker is DhanHQ. Existing `.env` configuration has the required client ID/access-token keys; secrets were not displayed or written to artifacts. The official detailed scrip master lists active NIFTY `FUTIDX` contracts (e.g. 68407, 48704), and authenticated requests returned 5-minute OHLCV/OI for active Futures security IDs for current dates. However, querying active IDs for historical dates (e.g. 2022) returned zero rows. Dhan's official intraday documentation states that 5-year minute history is restricted to active instruments; expired contracts are purged daily from the instrument master and have no historical intraday archive.

Phase 4 explicitly investigated Dhan's **Expired Options Data** capability (`POST /charts/rollingoption`). Key findings:
1. **No Expired Futures:** Dhan provides no historical intraday data for expired NIFTY Futures contracts (trial endpoints `/charts/rollingfuture`, `/charts/expiredfuture` return 404).
2. **Missing Contract Identity & Expiry:** `/charts/rollingoption` returns synthetic spot-relative rolling slices. It omits contract security ID, trading symbol, actual expiry date, and Change in OI (`change_oi`).
3. **Mid-Session Strike Shifting:** On 2024-07-10, rolling CALL ATM shifted across 6 strikes 14 times as spot moved, producing artificial $\Delta OI$ swings up to 1,240,000 contracts.
4. **Decoupled from Futures ATM:** The strategy anchors ATM to historical NIFTY Futures (nearest 50); Dhan's rolling API is hardcoded to Spot Index price buckets.
5. **Realtime Chain:** `/v2/optionchain` is real-time only and cannot reconstruct historical snapshots.

**Final Classification: DHAN INSUFFICIENT.**
See [DHAN_DATA_LIMITATION.md](research/validation/DHAN_DATA_LIMITATION.md) and [ALTERNATIVE_DATA_REQUIREMENTS.md](research/validation/ALTERNATIVE_DATA_REQUIREMENTS.md).

**Current readiness:** `BLOCKED — Dhan is INSUFFICIENT. Five-year dated NIFTY Futures coverage and Futures-anchored, expiry-resolved ATM±5 CE/PE OI cannot be obtained from Dhan alone.` No strategy result is produced.

## Suspicious or unreliable assumptions

- Existing `docs/5_YEAR_BACKTEST_REPORT.md` reports 15-minute NIFTY bars and strategy results, but `scripts/analyze_5year_data.py` uses `NIFTY` rows without distinguishing spot from Futures, and its generic bar backtest enters at the same close as its signal. It also calculates a rolling quantile over a window containing the current observation and reports a “winner” selected on the same full dataset. Those results do not establish performance of the requested strategy and must not be reused as validation.
- `research/candidate_discovery/audit_dataset.py` adds 5h30 to timestamps even though DB values are ISO timestamps with `+00:00`; correct timezone conversion should use timezone-aware conversion. Its 25-bars/day expectation is for 15M but does not establish session alignment.
- Some source timestamps are irregular/sub-minute, and multiple NIFTY bars fail OHLC inequalities. Per-row timestamp uniqueness does not mean bars are regularly spaced.
- The historical provider now requires exact chain timestamp equality, but the strategy method can still be called directly with a fabricated or current-chain `MarketSnapshot`; instrument/date provenance is not encoded in the model contract.
- The `ApprovalEngine` sends a paper option SELL request as risk clearance for a Futures-short model; its product/lot/charge semantics are not the same as the simulated Futures contract.

## Missing components for the requested research

Verified external historical NIFTY Futures contract bars (5-minute OHLCV, expiry, rollover mapping); timestamped option-chain snapshots with calls/puts OI, change OI, LTP, strike and expiry; a verified session timestamp convention; long strategy implementation; a reproducible NIFTY Futures transaction-cost schedule keyed to actual contract/turnover; proper baseline trade log and stratified evaluation; and automated no-future-data invariants.

## Disposition

The project is **STRICTLY BLOCKED** from backtesting. DhanHQ is `DHAN INSUFFICIENT` to supply the required historical data, and the supplied database contains NIFTY Spot rather than Futures with missing strike/expiry option records. Status: **INSUFFICIENT DATA FOR VALIDATION — BACKTEST BLOCKED**. Do not interpret prior exploratory results as evidence for this exact strategy. No backtest performance has been manufactured or inferred from incompatible instruments. External historical data adhering to `ALTERNATIVE_DATA_REQUIREMENTS.md` must be acquired before backtesting can commence.

## Hermes compatibility failures (separate from trading research)

The manifest at `config/hermes-version.yaml` pins `D:\AI_Trading\hermes-agent` to commit `d0288be5b3330d2442e3907185b8e9d0958297bb`. That checkout exists and is at exactly the pinned commit. The five prior failures occurred because Windows Git refused to operate on that checkout under the current sandbox identity: the checkout is owned by `BUILTIN\Administrators`, while tests run as `DESKTOP-0KOAU4O\CodexSandboxOffline`, triggering Git's “dubious ownership” safe-directory protection. `HermesVersionManager` catches the Git error and returns `None`; the compatibility checker then slices `None[:8]`, causing the additional TypeError. These are environment/configuration failures, not a missing checkout or trading-engine/backtester dependency. With process-local Git config marking only that exact path safe, all six Hermes compatibility tests pass. The test suite was not weakened.
