# DhanHQ Historical Data Acquisition Capability Report

Audit date: 2026-09-29. This report records a credentialed, small-sample API investigation. It is not a five-year dataset download and contains no strategy performance.

## Broker, APIs, and authentication

- **Broker/provider:** DhanHQ REST API v2.
- **Authentication:** Existing `.env` values `DHAN_CLIENT_ID` and `DHAN_ACCESS_TOKEN`, sent as `client-id` and `access-token` headers. Values were not displayed, copied into source, or saved to the manifest.
- **Instrument master:** Official detailed CSV at `https://images.dhan.co/api-data/api-scrip-master-detailed.csv`. The raw response is preserved at [dhan_scrip_master_detailed.csv](broker_samples/dhan_scrip_master_detailed.csv). It identified three NIFTY `FUTIDX` entries at the time of the probe, including security ID `68407` expiring 2026-09-29 and ID `48704` expiring 2026-10-27.
- **Futures historical candles:** `POST https://api.dhan.co/v2/charts/intraday`, `exchangeSegment=NSE_FNO`, `instrument=FUTIDX`, actual `securityId`, `interval=5`, `oi=true`. The request returns 5-minute OHLCV, epoch timestamps, and open interest. Dhan's docs say intraday history reaches five years for **active instruments**, up to 90 days per request; the docs do not promise an archived expired-Futures contract master or old expired-contract bars.
- **Expired options history:** `POST https://api.dhan.co/v2/charts/rollingoption`. Dhan documents up to five years of minute-based rolling expired-option OHLC, volume, OI, IV, strike, and spot; up to 30 days per request. It accepts an expiry interval/code selector and a rolling strike selector (`ATM`, `ATM±n`). The response has timestamped arrays including OI and the resolved strike, but does not return an actual expiry date or option contract/security ID. Its rolling ATM and offsets are spot-relative; the endpoint does not accept the strategy's historical Futures price to anchor ATM.
- **Live option-chain endpoint:** `POST /v2/optionchain` and `/v2/optionchain/expirylist` provide current chain/active-expiry information. The official page describes this as real-time and documents one unique request every three seconds. It is not a historical snapshot service and was not used to fill historical timestamps.
- **Documented rate controls:** Dhan release notes say minute/hour historical data APIs have no rate limit and cap Data APIs at 100,000 requests/day; seconds data have a 5 requests/second limit. In practice this account received `429 DH-904` (“Too many requests … Try throttling”) during rapid rolling-option requests. The reproducible probe now spaces calls by at least 1.1 seconds and retries 429/5xx with bounded backoff. The endpoint-specific rolling-option rate limit is not documented in the expired-options page.
- **Historical options/OI availability:** Yes, timestamped rolling OI was returned for the sampled dates. No historical full-chain snapshots or expiry-resolved option records were returned.
- **Historical Futures availability:** Verified only for two known 2026 contract IDs over a short sample. Five-year expired-contract coverage was not established. The same current ID queried for a 2022 date returned HTTP 200 with zero rows; this is consistent with the official active-instrument limitation and does not supply the missing 2022 Futures contract ID/history.

## Probe results

| Probe | Broker response | Interpretation |
|---|---:|---|
| NIFTY FUTIDX `68407`, 2026-09-10 to 2026-09-11 | 151 five-minute bars with OHLCV, timestamp, OI | Valid Futures sample for this identified contract and period |
| NIFTY FUTIDX `48704`, same dates | 151 five-minute bars with OHLCV, timestamp, OI | Valid Futures sample for this identified contract and period |
| ID `68407`, 2022-01-12 to 2022-01-13 | HTTP 200, zero bars | Does not establish five-year Futures history; current ID has no bars for this old range |
| Rolling NIFTY monthly CALL ATM, 2022-01-12 | 75 five-minute rows; 75 OI observations | Historical timestamped rolling OI exists |
| Rolling NIFTY monthly CALL ATM, 2024-07-10 | 75 five-minute rows; 75 OI observations | Historical timestamped rolling OI exists |
| Rolling NIFTY monthly CALL ATM, 2026-09-10 | 77 five-minute rows; 77 OI observations | Historical timestamped rolling OI exists |
| 2024-07-10 CALL and PUT `ATM-5`, `ATM`, `ATM+5` | All six calls returned 75 rows and OI; returned strikes resolve to multiple actual strike values as spot moves | API can produce strike values, but the ladder is spot-relative and no actual expiry/contract ID is included |

The count `979` is the sum of rows across these overlapping probe responses (302 Futures rows, 227 historical ATM CALL rows, and 450 repeated CALL/PUT offset rows). It is **not** a count of unique historical market records and is not a five-year download. The old Futures probe returned zero rows. A rapid initial batch also received `DH-904`; after adding request pacing, all saved option-side/offset probes returned HTTP 200.

**Failure/retry accounting:** initial exploratory requests included HTTP 400 `DH-905` while correcting the endpoint parameter combination and one HTTP 429 `DH-904` during a rapid burst. The 400/429 response files were superseded by corrected raw responses and are not included as separate manifest entries. The final paced sample run completed its 12 authenticated market-data calls without a 429 and required 0 retries; the probe script records retry counts when rerun. This is a small capability test, not a claim that production-scale downloads will never be throttled.

Raw JSON responses, including the exact request parameters and broker response, are saved under [broker_samples](broker_samples/). The sample Futures IDs are explicitly `FUTIDX`; the existing database's `NIFTY` series remains `IDX_I`/`INDEX` Spot data and has not been replaced by these samples.

## Data shape and limits

The expected *complete* normalized options schema remains:

```text
timestamp,symbol,expiry,strike,option_type,open,high,low,close,volume,oi,change_oi,instrument_id
```

The rolling endpoint supports timestamp, underlying ID, rolling expiry selector, requested strike selector, option side, resolved strike, OHLC, volume, OI, and spot. It does not return `expiry`, `instrument_id`, or `change_oi`. Its relative strike ladder is based on spot, not verified historical NIFTY Futures. We therefore do not normalize its output into the strategy-ready schema or forward-fill / difference OI across changing rolling identities.

The expected Futures schema is:

```text
timestamp,symbol,expiry,instrument_id,exchange_segment,instrument_type,open,high,low,close,volume,oi
```

The Futures endpoint supplies the price fields and OI when an actual contract ID is known. This repository currently lacks the five-year expired NIFTY Futures IDs/expiry map needed to request every historical contract and document rollovers. No synthetic continuous series has been created.

Timezone: broker epoch timestamps are retained as raw integer seconds and should be normalized to UTC. The broker's candle timestamp open/close convention still needs confirmation before strategy snapshot alignment.

## Download decision

No five-year downloader run or normalized acquisition was started. A downloader cannot honestly meet this strategy's minimum using these APIs alone: the rolling options API anchors its ladder to spot and omits actual expiry identity, while the Futures history endpoint/master do not establish five-year expired-contract coverage. Downloading large amounts of these partial series would not resolve those blockers and must not be presented as backtest-ready data.

The existing historical provider's no-look-ahead rule remains exact timestamp equality in UTC. It rejects future or stale option snapshots and does not forward-fill. The sample data are not fed to the strategy.

## Coverage decision

| Year | Futures | Timestamped option OI | Complete for strategy? |
|---|---|---|---|
| 2021 | Not verified | Not probed | Incomplete |
| 2022 | Not available from tested current contract ID; no historical Futures ID set | CALL rolling OI sample on 2022-01-12 | Incomplete |
| 2023 | Not verified | Not probed | Incomplete |
| 2024 | Not verified for five-year contracts | CALL OI sample plus CALL/PUT offset probes on 2024-07-10 | Incomplete: spot-relative, no actual expiry |
| 2025 | Not verified | Not probed | Incomplete |
| 2026 | Two contract samples on 2026-09-10/11 | CALL rolling OI sample on 2026-09-10 | Incomplete: only isolated dates/contracts |

**Decision: `DATA PARTIALLY READY — historical rolling option OI is available in sampled years, but five-year dated NIFTY Futures coverage and Futures-anchored, expiry-resolved ATM±5 CE/PE OI are missing.`** The OI strategy cannot be backtested honestly from the retrieved samples or supplied database.

## Reproduction and validation

Run `python research/validation/probe_dhan_history.py` with the existing `DHAN_CLIENT_ID` and `DHAN_ACCESS_TOKEN` environment variables or `.env` configuration to repeat the small probes. It saves raw responses and redacts credentials by never serializing headers. The pacing interval defaults to 1.1 seconds and can be raised with `DHAN_PROBE_REQUEST_INTERVAL_SECONDS`. Run `python research/validation/build_broker_manifest.py` afterward to rebuild SHA-256 hashes and row counts in [broker_download_manifest.json](broker_download_manifest.json).

The tests in `tests/test_short_strategy.py` cover causal historical prefix use, future-snapshot rejection, missing/empty OI failure, and no stale cross-session option carry. No broker request is made by those unit tests.
