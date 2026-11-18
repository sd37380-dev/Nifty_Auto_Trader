"""Build a credential-free manifest of the saved Dhan capability probe files."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DIR = ROOT / "research" / "validation" / "broker_samples"
OUTPUT = ROOT / "research" / "validation" / "broker_download_manifest.json"


def row_count(payload: dict[str, Any]) -> int:
    response = payload.get("response", {})
    if "timestamp" in response:
        return len(response.get("timestamp", []))
    key = "ce" if payload.get("request", {}).get("drvOptionType") == "CALL" else "pe"
    return len(response.get("data", {}).get(key, {}).get("timestamp", []))


def main() -> None:
    files = []
    for path in sorted([*SAMPLE_DIR.glob("*.json"), *SAMPLE_DIR.glob("*.csv")]):
        raw = path.read_bytes()
        if path.suffix == ".csv":
            files.append({
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
                "http_status": 200,
                "rows": max(0, raw.count(b"\n") - 1),
                "endpoint": "https://images.dhan.co/api-data/api-scrip-master-detailed.csv",
                "purpose": "Unmodified public detailed instrument master response used to identify currently listed NIFTY FUTIDX contracts.",
            })
            continue
        payload = json.loads(raw)
        request = payload.get("request", {})
        files.append({
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "http_status": payload.get("http_status"),
            "rows": row_count(payload),
            "request_timestamp_utc": payload.get("requested_at_utc"),
            "endpoint": "https://api.dhan.co/v2/charts/rollingoption" if "drvOptionType" in request else "https://api.dhan.co/v2/charts/intraday",
            "request_period": {"fromDate": request.get("fromDate"), "toDate": request.get("toDate")},
            "security_id": str(request.get("securityId", "")),
            "instrument": request.get("instrument"),
            "exchange_segment": request.get("exchangeSegment"),
            "expiry_flag": request.get("expiryFlag"),
            "expiry_code": request.get("expiryCode"),
            "strike_selector": request.get("strike"),
            "option_type": request.get("drvOptionType"),
        })
    manifest = {
        "broker": "DhanHQ",
        "status": "PARTIAL_CAPABILITY_PROBE_ONLY",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "auth_method": "client-id and access-token HTTP headers; credentials read from environment/.env and excluded from manifest",
        "historical_data_download": False,
        "scope": "Small representative endpoint probes only; not a five-year market-data acquisition.",
        "files": files,
    }
    OUTPUT.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)} with {len(files)} files")


if __name__ == "__main__":
    main()
