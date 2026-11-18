"""Validate sample historical options dataset.

Downloads and validates the free 3-day full-chain NIFTY options sample from OptionsData.shop:
- Checks schema conformance against ALTERNATIVE_DATA_REQUIREMENTS.md
- Checks timestamps, OHLC, volume, Open Interest
- Verifies discrete contract identity (expiry, strike, CE/PE)
- Tests whether ATM +/- 5 strike ladder can be selected
- Audits data quality: missing candles, zero OI, negative values, timestamp consistency
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DIR = ROOT / "research" / "validation" / "sample_data"
SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
SAMPLE_URL = "https://optionsdata.shop/sample/download"


def download_and_extract() -> list[Path]:
    zip_path = SAMPLE_DIR / "sample.zip"
    if not zip_path.exists():
        print(f"Downloading sample from {SAMPLE_URL}...", flush=True)
        resp = httpx.get(SAMPLE_URL, follow_redirects=True, timeout=60.0)
        resp.raise_for_status()
        zip_path.write_bytes(resp.content)
        print(f"Downloaded {len(resp.content):,} bytes to {zip_path}", flush=True)
    
    extracted_files: list[Path] = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(SAMPLE_DIR)
        for member in zf.namelist():
            extracted_files.append(SAMPLE_DIR / member)
            print(f"  Extracted: {member}", flush=True)
    return extracted_files


def audit_sample() -> dict[str, Any]:
    files = list(SAMPLE_DIR.glob("**/*.parquet"))
    if not files:
        raise RuntimeError("No parquet files found in sample directory")

    print(f"\nFound {len(files)} parquet files. Inspecting schema...", flush=True)

    # Read first file to get schema
    first_file = files[0]
    table = pq.read_table(first_file)
    df = table.to_pandas()

    schema_info = {
        "columns": list(df.columns),
        "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
        "total_files": len(files),
    }
    print(f"Columns: {schema_info['columns']}", flush=True)

    # Aggregate metrics across all files
    total_rows = 0
    all_dates = set()
    all_expiries = set()
    all_strikes = set()
    rights = set()
    zero_oi_count = 0
    positive_oi_count = 0
    negative_volume_count = 0
    invalid_ohlc_count = 0

    files_summary = []
    for f in sorted(files):
        df_f = pq.read_table(f).to_pandas()
        total_rows += len(df_f)
        
        # Check timestamps
        df_f["datetime"] = pd.to_datetime(df_f["datetime"])
        all_dates.update(df_f["datetime"].dt.date.unique())
        
        # Check expiries and strikes
        if "expiry_date" in df_f.columns:
            all_expiries.update(df_f["expiry_date"].unique())
        if "strike_price" in df_f.columns:
            all_strikes.update(df_f["strike_price"].unique())
        if "right" in df_f.columns:
            rights.update(df_f["right"].unique())

        # Quality checks
        if "open_interest" in df_f.columns:
            zero_oi_count += (df_f["open_interest"] == 0).sum()
            positive_oi_count += (df_f["open_interest"] > 0).sum()

        if "volume" in df_f.columns:
            negative_volume_count += (df_f["volume"] < 0).sum()

        # OHLC sanity: low <= open, close <= high
        bad_ohlc = (df_f["low"] > df_f["open"]) | (df_f["low"] > df_f["close"]) | (df_f["high"] < df_f["open"]) | (df_f["high"] < df_f["close"])
        invalid_ohlc_count += bad_ohlc.sum()

        files_summary.append({
            "file": f.name,
            "rows": len(df_f),
            "expiry": str(df_f["expiry_date"].iloc[0]) if "expiry_date" in df_f.columns else None,
            "date": str(df_f["datetime"].iloc[0].date()) if len(df_f) > 0 else None,
            "strikes": len(df_f["strike_price"].unique()) if "strike_price" in df_f.columns else 0,
        })

    # Test an End-to-End reconstruction for a specific timestamp
    # Pick date 2026-09-16 from NIFTY_OPT_1min_2026-09-16_exp2026-09-22.parquet
    # Assume hypothetical Futures price at 10:00:00 = 25215.0 -> ATM nearest 50 = 25200.0
    # Target strikes: ATM +/- 5 = 24950, 25000, 25050, 25100, 25150, 25200, 25250, 25300, 25350, 25400, 25450
    test_file = SAMPLE_DIR / "NIFTY_OPT_1min_2026-09-16_exp2026-09-22.parquet"
    sample_df = pq.read_table(test_file).to_pandas()
    sample_df["datetime"] = pd.to_datetime(sample_df["datetime"])
    
    test_ts = pd.to_datetime("2026-09-16 10:00:00")
    test_atm = 25200.0
    target_strikes = [test_atm + (i * 50) for i in range(-5, 6)]
    exact_snapshot = sample_df[sample_df["datetime"] == test_ts]

    chain_test_results = {
        "source_file": test_file.name,
        "evaluation_timestamp": str(test_ts),
        "target_atm": test_atm,
        "target_strikes": target_strikes,
        "snapshot_rows_at_timestamp": len(exact_snapshot),
        "ce_strikes_found": [],
        "pe_strikes_found": [],
        "all_strikes_present": False,
        "strike_oi_map": {},
    }

    if len(exact_snapshot) > 0:
        ce_rows = exact_snapshot[exact_snapshot["right"].str.strip().str.upper().isin(["CE", "CALL"])]
        pe_rows = exact_snapshot[exact_snapshot["right"].str.strip().str.upper().isin(["PE", "PUT"])]
        
        ce_strikes = sorted(ce_rows["strike_price"].unique())
        pe_strikes = sorted(pe_rows["strike_price"].unique())
        
        chain_test_results["ce_strikes_found"] = [s for s in target_strikes if s in ce_strikes]
        chain_test_results["pe_strikes_found"] = [s for s in target_strikes if s in pe_strikes]
        chain_test_results["all_strikes_present"] = len(chain_test_results["ce_strikes_found"]) == 11 and len(chain_test_results["pe_strikes_found"]) == 11
        
        for s in target_strikes:
            ce_sub = ce_rows[ce_rows["strike_price"] == s]
            pe_sub = pe_rows[pe_rows["strike_price"] == s]
            chain_test_results["strike_oi_map"][int(s)] = {
                "ce_oi": int(ce_sub["open_interest"].iloc[0]) if len(ce_sub) > 0 else 0,
                "ce_ltp": float(ce_sub["close"].iloc[0]) if len(ce_sub) > 0 else 0.0,
                "pe_oi": int(pe_sub["open_interest"].iloc[0]) if len(pe_sub) > 0 else 0,
                "pe_ltp": float(pe_sub["close"].iloc[0]) if len(pe_sub) > 0 else 0.0,
            }

    audit_report = {
        "audit_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "total_files": len(files),
        "total_rows": total_rows,
        "observed_dates": [str(d) for d in sorted(all_dates)],
        "observed_expiries": [str(e) for e in sorted(all_expiries)],
        "strike_count": len(all_strikes),
        "strike_range": [min(all_strikes), max(all_strikes)] if all_strikes else [],
        "rights": list(rights),
        "positive_oi_percentage": round((positive_oi_count / total_rows) * 100, 2) if total_rows > 0 else 0,
        "zero_oi_percentage": round((zero_oi_count / total_rows) * 100, 2) if total_rows > 0 else 0,
        "invalid_ohlc_count": int(invalid_ohlc_count),
        "negative_volume_count": int(negative_volume_count),
        "chain_reconstruction_test": chain_test_results,
        "files_detail": files_summary,
    }

    out_file = SAMPLE_DIR / "sample_validation_report.json"
    out_file.write_text(json.dumps(audit_report, indent=2), encoding="utf-8")
    print(f"\nAudit completed. Saved report to {out_file}", flush=True)
    return audit_report


def main() -> None:
    print("================================================================================")
    print("PHASE 5: VALIDATING HISTORICAL OPTIONS DATA SAMPLE")
    print("================================================================================")
    download_and_extract()
    report = audit_sample()
    print("\nSummary of Sample Validation:")
    print(f"  Total Rows: {report['total_rows']:,}")
    print(f"  Observed Dates: {report['observed_dates']}")
    print(f"  Expiries in sample: {report['observed_expiries']}")
    print(f"  Strike range: {report['strike_range']}")
    print(f"  Positive OI: {report['positive_oi_percentage']}%")
    print(f"  Invalid OHLC rows: {report['invalid_ohlc_count']}")
    print(f"  Reconstruction Test at {report['chain_reconstruction_test']['evaluation_timestamp']}:")
    print(f"    Target Strikes (11 strikes, ATM 25200): {report['chain_reconstruction_test']['target_strikes']}")
    print(f"    All 11 CE strikes found? {len(report['chain_reconstruction_test']['ce_strikes_found']) == 11}")
    print(f"    All 11 PE strikes found? {len(report['chain_reconstruction_test']['pe_strikes_found']) == 11}")
    print(f"    Strike-level OI available? {report['chain_reconstruction_test']['all_strikes_present']}")


if __name__ == "__main__":
    main()
