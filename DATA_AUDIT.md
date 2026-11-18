# Historical Data Audit

Audit generated read-only on 2026-09-29 from `data/hermes_research/market_data.db` by `research/validation/audit_supplied_dataset.py`. Machine-readable details and file hash: `research/validation/dataset_audit.json`.

## Database inventory

- Database size: 104,640,512 bytes; SHA-256: `948598e6f8efee5d4eaafb671ff195dbc8144e41d799ae734df622106f65af3d`.
- Tables: `normalized_bars` 202,907 rows; `feature_sets` 28 rows; `raw_payloads` 0 rows.
- No options-chain/expiry/strike table exists.

| Symbol | Timeframe | Rows | Observed timestamp range (UTC) | Distinct dates | Invalid OHLC rows |
|---|---:|---:|---|---:|---:|
| NIFTY | 5M | 92,739 | 2021-09-30 11:30 to 2026-09-29 13:40 | 1,246 | 234 |
| NIFTY | 15M | 38,248 | 2021-09-30 08:30 to 2026-09-29 18:08:01.122788 | 1,247 | 202 |
| NIFTY_ATM_CE | 5M | 3,265 | 2026-07-01 03:45 to 2026-09-29 10:05 | 43 | 0 |
| NIFTY_ATM_CE | 15M | 29,469 | 2021-10-01 03:45 to 2026-09-29 10:00 | 1,170 | 0 |
| NIFTY_ATM_PE | 5M | 3,157 | 2026-08-03 03:45 to 2026-09-29 10:05 | 41 | 0 |
| NIFTY_ATM_PE | 15M | 29,819 | 2021-10-01 03:45 to 2026-09-29 10:00 | 1,184 | 1 |
| BANKNIFTY | 15M | 6,210 | 2025-09-29 08:15 to 2026-09-29 13:30 | 248 | 0 |

NIFTY 5M and 15M timestamp rows are unique and sorted, but not uniformly spaced throughout the entire series. Typical within-session differences are 5 and 15 minutes respectively, while day breaks create larger gaps. NIFTY 5M includes three 1-minute, one 2-minute, one 3-minute and one 4-minute adjacent timestamp differences, among other anomalies. NIFTY 15M has 2,909 adjacent pairs with a zero-minute difference at whole-minute precision plus 926 one-minute and 562 two-minute differences; timestamps carry sub-minute precision in parts of the data. The latest 15M timestamp is 18:08:01 UTC (23:38:01 in India), an unexplained out-of-session-looking observation for an index bar. See the JSON audit for gap distributions.

## Instrument identity and required-field coverage

The database schema alone does not include security ID, exchange segment, exchange, instrument type, expiry, or contract ID. Repository provenance resolves `NIFTY`: `scripts/fetch_broker_data.py` uses security ID `13` with Dhan `exchangeSegment="IDX_I"` and `instrument="INDEX"`, then stores it with symbol `NIFTY` and `open_interest=0`. The supplied `NIFTY|5M` group has zero OI on all 92,739 rows. We therefore classify the existing `NIFTY` bars as **Spot/Index**, not Futures. There are no Futures contracts or Futures roll records in this database. The database continued changing during this audit (new NIFTY 15M rows and feature sets appeared between snapshots); counts and hash above are point-in-time values and must be rechecked against the exact files delivered for research.

The SQLite schema declares OHLC, volume, open_interest and VWAP as NOT NULL, and the audit found no SQL NULLs in these fields. That does **not** prove OI availability or quality: zero OI counts are captured in the JSON audit, and raw broker payloads are absent for independent verification. Change OI, option LTPs, call/put classification per timestamp, expiry, and strike are not stored as structured fields.

## Data type and resolution findings

- `NIFTY` is explicitly Spot/Index according to the repository's Dhan ingestion path (`securityId=13`, `IDX_I`, `INDEX`). The normalized table loses this metadata, but not the loader's classification; no Futures series exists.
- NIFTY 5M Spot/Index candles span approximately five years. Their timestamps are timezone-aware UTC values; candle-open versus candle-close convention is not documented. All 92,739 NIFTY 5M OI values are zero.
- `NIFTY_ATM_CE/PE` are rolling ATM monthly-option bars from `scripts/backfill_5year_options.py`. The request selects `strike=ATM`, `expiryFlag=MONTH`, `expiryCode=1`; only OHLC, volume, and OI are persisted. The resolved strike and expiry date are not saved. CE/PE is encoded in the symbol name. 15M bars exist for most dates; 5M bars exist only for the latest 43 CE and 41 PE observed dates.
- Rolling ATM option OI is therefore partially present but cannot identify OI at each exact ATM ±5 strike. Change OI is not stored and must not be differenced across changing rolling contracts. The bar close exists, but is not a standalone quote timestamp/LTP field.
- No Futures contract rollover metadata, option expiry calendar, contract master, or per-row security ID is persisted. Raw payload table has zero rows, so resolved contract metadata cannot be recovered from raw API responses.
- Calendar dates without bars are not labelled as missing trading dates; they may be holidays/weekends. This audit therefore reports observed dates and timestamp gaps, not an asserted exchange calendar.

## Conclusion

The data are insufficient to run the requested strategy faithfully. In particular: **OI strategy cannot be historically validated for periods where timestamped option-chain data is unavailable.** This database has rolling ATM option bars with partial OI, but no per-snapshot resolved strikes/expiries or ATM ±5 chain coverage; verified NIFTY Futures data are also absent. No substitute OI or Futures prices were reconstructed.

## Phase 3 & 4 broker investigation (separate from the supplied database)

The configured provider is DhanHQ. In Phase 3, NIFTY Futures (`FUTIDX`) IDs 68407 (2026-09-29 expiry) and 48704 (2026-10-27 expiry) were identified in the master; 5-minute OHLCV/OI was returned for active dates, but querying ID 68407 for 2022 returned HTTP 200 with zero bars.

Phase 4 audited Dhan's **Expired Options Data** capability (`POST /charts/rollingoption`) and historical intraday API across 2022, 2023, 2024, 2025, and 2026 via `research/validation/probe_dhan_expired_options.py`.
1. **Intraday Expired Futures:** Dhan provides no expired futures contract history. The endpoint explicitly supports only active instruments. Undocumented endpoints (`/charts/rollingfuture`, `/charts/expiredfuture`) returned HTTP 404.
2. **Expired Options API:** `/charts/rollingoption` provides continuous 5-minute OHLCV, volume, OI, and spot arrays on a rolling basis. However, the response completely omits:
   - `expiry` (actual expiration date)
   - `security_id` / contract ID
   - `change_oi`
3. **Mid-Session Strike Drift:** Because strikes are dynamically resolved relative to Spot, a single rolling series shifts contracts mid-session (14 strike shifts on 2024-07-10 across 6 distinct strikes). Differencing raw OI across candles creates spurious spikes of up to 1,240,000 contracts.
4. **Futures ATM Decoupling:** The strategy strictly anchors ATM strikes to historical NIFTY Futures (nearest 50); Dhan's rolling API is hardcoded to Spot Index price buckets.

**Classification:** `DHAN INSUFFICIENT`. Dhan cannot support the strategy's data requirements. See [DHAN_DATA_LIMITATION.md](research/validation/DHAN_DATA_LIMITATION.md) and [ALTERNATIVE_DATA_REQUIREMENTS.md](research/validation/ALTERNATIVE_DATA_REQUIREMENTS.md).

The requests and raw response files are itemized in [BROKER_DATA_DOWNLOAD_REPORT.md](research/validation/BROKER_DATA_DOWNLOAD_REPORT.md) and [broker_samples/expired_options_probe_report.json](research/validation/broker_samples/expired_options_probe_report.json). Probe response row counts overlap and are not a unique downloaded history. Existing database counts and anomalies above describe only the supplied SQLite file.
