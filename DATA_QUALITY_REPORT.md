# Data Quality Report

## Coverage

The supplied SQLite file spans approximately five years for NIFTY Spot/Index OHLCV series. It contains 92,739 NIFTY 5-minute rows and 38,248 NIFTY 15-minute rows, observed from 2021-09-30 through 2026-09-29. Exact file SHA-256 at this audit snapshot: `948598e6f8efee5d4eaafb671ff195dbc8144e41d799ae734df622106f65af3d`. This database changed while the readiness audit was being performed; recalculate its hash/counts after freezing the supplied dataset before any future backtest.

## Findings

- **Futures coverage:** Missing. The repository's NIFTY ingestion path requests Dhan `securityId=13`, segment `IDX_I`, instrument `INDEX`; the normalized table's NIFTY series is Spot/Index. No Futures instrument/security ID, exchange-segment record, expiry-specific series, or roll mapping is present.
- **Options coverage:** Rolling monthly ATM CE/PE OHLCV rows exist. The backfill requests ATM and expiry code 1 but does not retain the resolved strike or actual expiry date per row. The 5-minute option history is limited to 43 CE and 41 PE observed dates; the older multi-year option bars are 15-minute, not 5-minute chain snapshots.
- **Option OI coverage:** Rolling ATM CE and PE OI is partially present in `open_interest`, but there is no OI by resolved strike/expiry for ATM ±5, and no `change_oi`. No reconstruction from current data or differences across rolling contracts was attempted.
- **Expiry coverage:** No actual expiry values or expiry calendar are persisted. `expiryFlag=MONTH, expiryCode=1` is ingestion request metadata, not per-row expiry identity.
- **Timestamp quality:** ISO timestamps are timezone-aware UTC values, but NIFTY rows show irregular/sub-minute timestamps and non-5/15-minute adjacent intervals. The DB value is the timestamp supplied by ingestion; whether it denotes candle open or close is undocumented.
- **Timestamp anomaly:** Latest NIFTY 15M timestamp in the audit snapshot is 18:08:01 UTC (23:38:01 India time), an unexplained out-of-session-looking index observation. Source semantics must be checked; it was not removed.
- **OHLC:** All price columns are populated, but NIFTY has 234 invalid 5-minute and 202 invalid 15-minute OHLC rows by the standard high/low envelope checks. One generic ATM PE 15-minute row also fails. Rows have not been silently removed.
- **Duplicate rows:** No duplicate timestamps within each symbol/timeframe group. Database key also enforces unique symbol/timeframe/timestamp.
- **Volume/OI:** Fields are structurally present and non-NULL. NIFTY Spot/Index 5M OI is zero for all rows; generic rolling option rows have OI values. Raw payload count is zero. Change OI is not stored.
- **Missing dates/gaps:** The file contains observed dates; distinguishing exchange holidays from missing-data dates requires an authoritative trading calendar and is not inferred here. Irregular within-day timestamp gaps are enumerated in `research/validation/dataset_audit.json`.
- **Survivorship/rollover:** Cannot be evaluated because resolved rolling-option identities and Futures contract roll records are absent.

## Assumptions and use decision

Timestamps are interpreted in their encoded UTC timezone for audit only. No undocumented timezone shift is applied. No invalid row is excluded from analysis because no valid strategy backtest was run. These observations are sufficient to reject the dataset for the requested OI/Futures validation, but not to characterize all broker-data quality.

**Decision: INSUFFICIENT DATA FOR VALIDATION.**

## Phase 3 & 4 broker sample quality & capability audit

The configured broker has been confirmed as DhanHQ. Empirical probing in Phase 3 and Phase 4 (`probe_dhan_expired_options.py`) demonstrates:
1. **Futures Intraday History:** Dhan provides 5-minute OHLCV/OI only for currently active Futures contracts. For expired contracts, querying `/charts/intraday` returns 0 bars. Dhan maintains no historical archive of expired Futures contracts and has no expired futures endpoint. Five-year Futures history is 0% available.
2. **Expired Options Structure:** `/charts/rollingoption` returns continuous minute/5-minute arrays. However, it returns synthetic spot-relative rolling slices rather than discrete contract series. It omits contract security ID, trading symbol, actual expiry date, and Change in OI (`change_oi`).
3. **Artificial OI Swings:** On 2024-07-10, rolling CALL ATM shifted across 6 strikes 14 times as spot moved, producing artificial $\Delta OI$ swings up to 1,240,000 contracts when taking differences across adjacent bars.
4. **Futures Decoupling:** The strategy strictly anchors ATM strikes to historical NIFTY Futures (nearest 50); Dhan's rolling API is hardcoded to Spot Index price buckets.

**Final Classification: DHAN INSUFFICIENT.**
DhanHQ cannot supply the required historical data. Full details in [DHAN_DATA_LIMITATION.md](research/validation/DHAN_DATA_LIMITATION.md) and [ALTERNATIVE_DATA_REQUIREMENTS.md](research/validation/ALTERNATIVE_DATA_REQUIREMENTS.md).

**Current research readiness: BLOCKED — DHAN INSUFFICIENT.** The project cannot proceed to backtesting without acquiring an authoritative external dataset conforming to the specifications in `ALTERNATIVE_DATA_REQUIREMENTS.md`. The strategy remains strictly frozen and blocked.
