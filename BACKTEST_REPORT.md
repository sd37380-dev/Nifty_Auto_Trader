# NIFTY Strategy Historical Validation — Status Report

**Status: INSUFFICIENT DATA FOR VALIDATION**

## Dataset and quality

The audited SQLite database contains multi-year NIFTY Spot/Index 5-minute and 15-minute OHLCV bars plus rolling monthly ATM CE/PE OHLCV/OI bars. The repository's loader identifies NIFTY as Dhan `IDX_I` / `INDEX` (`securityId=13`); it is not Futures. Rolling option rows do not retain actual strike or expiry per timestamp and lack change OI. The NIFTY index data contain invalid OHLC envelopes and irregular timestamps. Full details and the exact dataset hash are in [DATA_AUDIT.md](DATA_AUDIT.md), [DATA_QUALITY_REPORT.md](DATA_QUALITY_REPORT.md), and [backtest_data_requirements.json](research/validation/backtest_data_requirements.json).

## Strategy definition and baseline configuration

The requested exact baseline remains: EMA20/EMA50, ATR14, 20-point OI/Pivot confluence, EMA-distance multiplier 0.25, 5-point stop buffer, 2R target, one position, next 5-minute open entry, and 15:00 session cutoff. Long and short require historical Futures and timestamped, expiry/strike-resolved OI at each evaluation time. Those inputs are absent/unverified. No substitute instrument, OI, or parameter was introduced.

## Results

No baseline trades or P&L are reported. Running the current short backtest on NIFTY generic bars would imply they are Futures and would allow incomplete/stale options data; doing so would not test the specified strategy. Therefore trades, win rate, expectancy, profit factor, drawdown, year-by-year/regime, sensitivity, walk-forward, OOS and ablation results are **not available**. No conclusion about profitability follows.

## Engine/look-ahead and execution review

The historical provider now requires a non-empty snapshot with positive CE and PE OI at the exact same timestamp as every replay candle. It does not forward-fill or accept future observations, and the engine blocks if option/OI snapshots are missing. The model still cannot prove per-strike ATM ±5/expiry/OI field provenance or Futures identity; timestamp convention remains undocumented. The research analyzer has same-candle-close entry timing and full-sample strategy selection, so its prior tournament report is not accepted as evidence. Full findings are in [LOOKAHEAD_AUDIT.md](LOOKAHEAD_AUDIT.md).

## Costs and reproducibility

Existing Futures charge defaults are embedded in `TransactionCostConfig`, but they have not been independently reconciled to dated contract rules. The code records slippage separately while fills already include slippage, which is appropriate only if P&L remains net of fills and slippage is not deducted again. The database hash is recorded in the audit JSON. Since required inputs are invalid/incomplete, a reproducible baseline artifact cannot be produced.

## Verification performed

- Focused strategy tests: **29 passed** (`pytest -q tests/test_short_strategy.py -p no:cacheprovider`).
- Hermes compatibility tests: **6 passed** with process-local `safe.directory` for the pinned checkout.
- The five previous full-suite failures were environment-only. The pinned Hermes checkout exists at the expected path and exact commit; Git rejected subprocess access due Windows ownership mismatch. Marking only that repository path safe for the test process resolves the failures. The compatibility checker has a separate robustness bug when Git returns no commit (`None[:8]`), but that path was not triggered in the successful run.
- An initial default-temp full-suite invocation additionally hit Windows access-denied errors under `%LOCALAPPDATA%\Temp`; using a workspace basetemp resolved fixture setup.
- Full repository suite: **262 passed** (`pytest -q --basetemp=research/.pytest_tmp -p no:cacheprovider`, with process-local `safe.directory=D:/AI_Trading/hermes-agent`). Four warnings are upstream Google GenAI aiohttp session deprecations.
- The database audit completed read-only and generated the JSON evidence file. No trading performance test was run because data requirements failed.

## What is needed

Provide verified external NIFTY Futures 5-minute bars with instrument/security identifiers, timestamp convention, and rollover mapping; timestamped option-chain snapshots at a resolution suitable for each signal, including expiry, strike, CE/PE, OI, change OI, and (for execution-price studies) option OHLC/LTP; plus applicable dated charges/lot sizes. The exact requirements are formally specified in [ALTERNATIVE_DATA_REQUIREMENTS.md](research/validation/ALTERNATIVE_DATA_REQUIREMENTS.md).

## Phase 3 & 4 Broker Data Investigation & Capability Decision

The configured broker is DhanHQ. Following Phase 3, Phase 4 specifically investigated whether Dhan's **Expired Options Data** capability (`POST /charts/rollingoption`) and historical intraday API could supply the missing components.

The empirical findings from `probe_dhan_expired_options.py`:
1. **Five-Year NIFTY Futures:** **NOT AVAILABLE**. Dhan provides 5-minute intraday bars only for currently active Futures contracts. Historical queries for expired contracts return 0 bars. Undocumented trial endpoints (`/charts/rollingfuture`, `/charts/expiredfuture`) returned HTTP 404.
2. **Expired Options Contracts:** **NOT AVAILABLE AS DISCRETE CONTRACTS**. Dhan provides only synthetic spot-relative rolling slices.
3. **Exact Expiry & Security ID:** **MISSING**. Dhan omits actual expiry dates, contract security IDs, trading symbols, and Change in OI (`change_oi`).
4. **Mid-Session Strike Shifting:** On 2024-07-10, rolling CALL ATM shifted across 6 strikes 14 times as spot moved, producing artificial $\Delta OI$ swings up to 1,240,000 contracts when taking differences across adjacent bars.
5. **Decoupled from Futures:** ATM cannot be anchored to historical Futures prices because Dhan's rolling option API anchors only to Spot.

**Classification:** `DHAN INSUFFICIENT`. See [DHAN_DATA_LIMITATION.md](research/validation/DHAN_DATA_LIMITATION.md).

No backtest was run. No strategy parameters were altered. No synthetic substitute data was used.

**Current status: STRICTLY BLOCKED — DHAN INSUFFICIENT.** Backtesting cannot proceed until an external historical dataset matching [ALTERNATIVE_DATA_REQUIREMENTS.md](research/validation/ALTERNATIVE_DATA_REQUIREMENTS.md) is provided.
