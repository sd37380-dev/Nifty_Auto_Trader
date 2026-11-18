# Look-Ahead Audit

Scope reviewed: `strategies/short/market_data_provider.py`, `strategy.py`, `indicators.py`, `pivot.py`, `oi_resistance.py`, `backtest.py`, plus exploratory `scripts/analyze_5year_data.py` and `scripts/backtest_real_option_contracts.py`.

## Existing paths and risks

| Data access | Intended availability | Finding |
|---|---|---|
| Historical candles in provider | Up to current index | Provider returns a prefix, so its indicator and current-candle inputs are causal when timestamps are properly sorted and timestamp denotes candle close. No explicit guard prevents asking for an arbitrary index/timestamp mismatch. |
| EMA20/EMA50 | Current and previous candle close | Series routines are chronological and do not use future observations. Snapshot values are trusted if supplied, without verifying they were derived from the visible prefix. |
| ATR14 | Current and previous bars | Wilder calculation is chronological. Same external-snapshot trust issue applies. |
| Previous-day OHLC/pivots | Strictly prior date | Historical provider selects date keys `< current date`; aggregation uses only visible prior dates. This is causal if date/timezone semantics are correct. |
| Historical option chain | Timestamped snapshot at signal time | Originally the provider fell back to date-only keys and could expose later observations. Replay now requires a non-empty chain snapshot with positive CE and PE OI at the exact evaluation timestamp for every replay candle; it does not forward-fill stale chains. Missing, future, stale, empty, or all-zero-OI snapshots fail safely. Per-strike ATM ±5 completeness, expiry, and raw-field-presence validation remain absent because the supplied schema has no strike-resolved chain records. |
| OI engine | Snapshot strikes in ATM ±5 | ATM derives from current supplied Futures price; however fallback to nearest 11 chain rows can bypass strike completeness and expiry checks. |
| Signal/rejection | Current candle OHLC after close | Evaluating after close is compatible with the declared signal time. Same candle high/low are then known. Entry is scheduled on next candle open in engine. |
| Stop/target exit | Current candle range | Stop is checked before target, conservatively resolving both touched in one candle. However next-entry candle is also immediately checked for exits, valid only if candle high/low follow its open chronologically; gap fills are simplified. |
| Session cutoff | Candle timestamp time | Engine exits when timestamp time is at/after cutoff. If timestamps label candle opens, this could exit later than 15:00; convention is undocumented. It may also carry a position across a calendar date if the final session candle is absent. |
| Exploratory analyzer | Forward returns and OHLC | Analyzer creates `fwd_ret_4/8`; those are labels and must not be used as entry features. Its bar simulator enters at same bar close as the close-based signal, a timing look-ahead. Rolling quantile is not shifted before squeeze use, and its “best” model is selected on all data. |
| `backtest_real_option_contracts.py` | Option bars aligned with market bars | Uses generic ATM option series and daily pivot joins; contract identity/expiry mapping cannot be verified from supplied schema. Results are not admissible evidence for the requested strike-specific strategy. |

## Audit verdict

The candle-prefix and indicator math are causal, and the historical provider now refuses missing, stale, future, empty, or all-zero-OI option-chain observations by requiring exact timestamp equality for every candle. A requested evaluation time that disagrees with the replay cursor also fails closed. Precomputed indicator fields can still be injected into `MarketSnapshot`, date filtering is coupled to a pending signal, and timestamp convention is unknown. Tests verify that future candles cannot change earlier snapshot calculations and future, prior-session, empty, or zero-OI option observations are not treated as sufficient. Existing test 16 only asserts a hand-calculated fill and does not exercise the full engine.

No historical strategy result is accepted from the supplied data. The requested baseline is blocked by missing verified Futures and timestamped option-chain/OI data, not just by this engine audit.

## Required invariant before future valid runs

For a signal at `T`, the current historical provider requires a non-empty option snapshot with at least one positive CE and PE OI value timestamped exactly at `T` (no forward-fill; if exact alignment is absent, fail closed). Compute indicator values from the same causal candle prefix inside a single provider/feature path. Require verified Futures instrument identity and contract metadata. Use only prior completed-session OHLC for pivots. Do not consume forward-return columns in signal generation. Preserve the prefix-invariance test by modifying all records after `T` and asserting all snapshot fields and strategy output at `T` remain identical.

## Phase 3 & 4 broker timestamp and lookup review

The Dhan probes retained raw epoch timestamp arrays for each Futures and rolling-option request and did not merge those rows into the backtest. No `rollingoption` sample was selected based on a future observation or filled backward. The historical replay provider strictly requires exact timestamp equality in UTC and rejects a future snapshot, stale prior-session snapshot, or absent/empty CE/PE OI. Existing regression tests include `test_historical_provider_never_uses_future_option_chain_snapshot`, `test_historical_provider_does_not_carry_option_chain_across_sessions`, empty/zero OI checks, requested-time/cursor mismatch, and prefix mutation invariance.

Phase 4 causal evaluation findings:
1. **Timestamp Invariant:** For an evaluation timestamp $T$, the condition $T_{\text{futures}} \le T$ and $T_{\text{option}} \le T$ is strictly enforced. No forward-filling is permitted.
2. **Structural Lookahead Risk in Rolling API:** While Dhan's `/charts/rollingoption` response timestamps advance sequentially, the strike values embedded in the arrays change mid-session based on contemporaneous spot price movement. Attempting to backtest an option position on this rolling data introduces lookahead/synthetic bias because the option identity itself shifts retrospectively as spot crosses strike boundaries.
3. **Absence of Futures Anchoring:** The strategy evaluates ATM at timestamp $T$ based on the latest Futures candle close $\le T$. Because Dhan provides no historical Futures bars for expired contracts, causal anchoring of ATM $\pm 5$ strikes is physically impossible on Dhan data alone.

**Status:** Lookahead safety invariants remain verified and strictly enforced. Backtesting remains **BLOCKED** due to `DHAN INSUFFICIENT`.
