# Data Recovery Plan — NIFTY Futures + Option OI

## Current disposition

**BACKTEST BLOCKED.** The supplied `NIFTY` 5-minute and 15-minute bars are Spot/Index data: `scripts/fetch_broker_data.py` requests Dhan `securityId=13`, `exchangeSegment=IDX_I`, `instrument=INDEX`, stores the result as `NIFTY`, and explicitly writes OI as zero. The normalized table does not preserve that provenance, and `raw_payloads` is empty, but the ingestion source is explicit. Do not relabel these bars Futures.

The available `NIFTY_ATM_CE/PE` series contain rolling ATM option OHLCV and OI from a monthly rolling-option request. The backfill requests `strike=ATM`, `expiryFlag=MONTH`, `expiryCode=1`, but does not persist the resolved strike or actual expiry at each timestamp. It also has no change OI. Historical chain walls cannot be recovered from a single rolling ATM series.

## Required acquisition

Obtain historical, contract-identified data from a broker/vendor archive or licensed market-data source. The source must provide:

1. NIFTY Futures 5-minute bars for each actual contract across the full desired period. Preserve security ID, exchange/segment, instrument type, expiry, and enough information to reconstruct and audit rolls. Do not splice contracts without recording the roll rule and both contracts around the roll.
2. A timestamped option-chain snapshot for each evaluated 5-minute candle close (or an explicitly documented source cadence and backward-only join). Each snapshot must cover at least the historical Futures ATM ±5 strikes and the expiry selected by the frozen strategy specification.
3. For each option row, preserve OI, option type, strike, expiry, snapshot time, and preferably change OI, volume, LTP and OHLC. Retain raw source files/API responses and a manifest so source fields can be traced.
4. Exchange session calendar/timezone, timestamp convention (bar open or close), and contract master/expiry calendar.

Current/today's chain values are not a substitute for historical observations. Do not synthesize change OI across strike/expiry rolls. Do not fill missing snapshots from a future timestamp. Do not use PCR, Greeks, or option premiums as OI substitutes.

## Expected normalized schemas

Futures bars (one row per contract and bar):

```csv
timestamp,symbol,security_id,exchange,exchange_segment,instrument_type,expiry,open,high,low,close,volume,oi
2024-01-02T03:45:00Z,NIFTY,EXAMPLE,NSE,NSE_FNO,FUTIDX,2024-01-25,21700.0,21725.0,21690.0,21710.0,123456,987654
```

Option bars or snapshots (one row per expiry/strike/type/time):

```csv
timestamp,symbol,expiry,strike,option_type,open,high,low,close,volume,oi,change_oi
2024-01-02T03:45:00Z,NIFTY,2024-01-04,21700,CE,125.0,130.0,120.0,127.5,12345,654321,12000
```

The example values are schema illustrations only; they are not real observations and must not be ingested as data.

## Alignment and fail-closed rule

The signal is evaluated at the close timestamp of a completed 5-minute Futures candle. The option snapshot must match that same timestamp after conversion to UTC. The current historical provider requires exact timestamp equality, no forward-fill, and non-empty strikes. A missing snapshot causes unavailable option data and blocks a valid full-period replay.

If the eventual vendor only timestamps snapshots independently from candle closes, first document its capture cadence. A permitted join must be backward-only: choose the latest snapshot timestamp `S` satisfying `S <= candle_close_T`, from the same exchange session, and reject if its age exceeds one 5-minute interval. Never use a snapshot after `T`, carry across sessions, or silently fill a missing interval. This backward join is not currently implemented; exact matching remains the production gate until an explicit reviewed change and tests exist.

## Intake validation before research

- Hash original files and save vendor/source/version/license metadata.
- Validate contract identifiers against the contract master and verify instrument type is Futures or option, not index/spot.
- Check timezone awareness, bar timestamp convention, uniqueness, ordering, five-minute session cadence, OHLC invariants, nulls, zero/missing OI semantics, and all gaps.
- Confirm Futures expiry and rollover continuity; preserve per-contract series and document any continuous series construction separately.
- For options, check every required expiry/strike/type exists at each snapshot; compare row counts and key coverage over time; do not mistake rolling ATM labels for resolved strikes.
- Confirm OI/change-OI source semantics and distinguish an actual zero from a missing field.
- Rerun `research/validation/audit_supplied_dataset.py`, update `backtest_data_requirements.json`, and do not open the backtest gate until mandatory fields and coverage pass.

## Readiness gate

Proceed to the frozen baseline only after both the 5-minute Futures contract history and timestamped strike/expiry-resolved option chain meet the schemas and coverage rules above. Until then, performance metrics remain unreported.

## Phase 3 update — DhanHQ capability checked

The configured source is DhanHQ. Its active-instrument Futures endpoint returned a small 5-minute sample for two verified NIFTY `FUTIDX` security IDs in 2026, but the current master does not provide the required historical expired-contract identifier sequence; a known ID queried for 2022 returned zero rows. Its rolling expired-options endpoint returned timestamped 5-minute OI and resolved strike values in sample dates from 2022, 2024, and 2026. Those strikes are anchored to spot, and the API response has no actual expiry date or option contract ID. The current option-chain API is realtime only.

Therefore Dhan has useful historical OI data but does not meet this study's complete inputs. No bulk download or normalization into the strategy schema was done: doing so would label spot-relative strikes as Futures-ATM strikes and leave expiry unverified. The raw capability responses and hashes are in `research/validation/broker_samples/` and `research/validation/broker_download_manifest.json`. Continue the gate above until Dhan supplies archived Futures contract history and a Futures-anchored, actual-expiry-resolved option snapshot source, or the user explicitly selects another licensed provider.
