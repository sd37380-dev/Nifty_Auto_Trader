"""Re-run small, raw-preserving Dhan history capability probes.

This is an audit probe, not a production downloader. It deliberately tests
historical identifiers and Dhan's rolling option selector without converting
the responses into strategy-ready bars. Credentials are read from the normal
dotenv/environment configuration and are never written or printed.
"""

from __future__ import annotations

import json
import os
import csv
import io
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research" / "validation" / "broker_samples"
API = "https://api.dhan.co/v2"
MIN_REQUEST_INTERVAL = max(1.0, float(os.getenv("DHAN_PROBE_REQUEST_INTERVAL_SECONDS", "1.1")))
_last_request = 0.0
_retry_count = 0
_request_count = 0


def persist(name: str, request: dict[str, Any], response: httpx.Response) -> dict[str, Any]:
    try:
        body: Any = response.json()
    except ValueError:
        body = response.text
    record = {
        "requested_at_utc": datetime.now(timezone.utc).isoformat(),
        "request": request,
        "http_status": response.status_code,
        "response": body,
    }
    (OUT / name).write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def paced_post(client: httpx.Client, path: str, request: dict[str, Any]) -> httpx.Response:
    """Pace calls and retry documented transient HTTP failures without logging secrets."""
    global _last_request, _retry_count, _request_count
    response: httpx.Response | None = None
    for attempt in range(4):
        wait = MIN_REQUEST_INTERVAL - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()
        _request_count += 1
        response = client.post(f"{API}{path}", json=request)
        if response.status_code not in (429, 500, 502, 503, 504) or attempt == 3:
            return response
        _retry_count += 1
        retry_after = response.headers.get("Retry-After")
        try:
            delay = float(retry_after) if retry_after else 2.0**attempt
        except ValueError:
            delay = 2.0**attempt
        time.sleep(min(max(delay, 1.0), 30.0))
    assert response is not None
    return response


def main() -> None:
    run_started = datetime.now(timezone.utc).isoformat()
    load_dotenv(ROOT / ".env")
    client_id, token = os.getenv("DHAN_CLIENT_ID"), os.getenv("DHAN_ACCESS_TOKEN")
    if not client_id or not token:
        raise SystemExit("Missing DHAN_CLIENT_ID or DHAN_ACCESS_TOKEN in environment/.env")
    OUT.mkdir(parents=True, exist_ok=True)
    headers = {"client-id": client_id, "access-token": token, "Content-Type": "application/json"}

    # The sample raw responses are intentionally limited to representative days.
    with httpx.Client(timeout=45.0, headers=headers) as client:
        master_response = client.get("https://images.dhan.co/api-data/api-scrip-master-detailed.csv")
        master_response.raise_for_status()
        (OUT / "dhan_scrip_master_detailed.csv").write_bytes(master_response.content)
        master_text = master_response.content.decode("utf-8-sig", errors="replace")
        nifty_futures = [
            row for row in csv.DictReader(io.StringIO(master_text))
            if row.get("UNDERLYING_SYMBOL") == "NIFTY" and row.get("INSTRUMENT") == "FUTIDX"
        ]
        print(f"INSTRUMENT MASTER: HTTP {master_response.status_code}, NIFTY FUTIDX rows={len(nifty_futures)}")

        sample_date = "2026-09-10"
        available_futures = sorted(
            (row for row in nifty_futures if row.get("SM_EXPIRY_DATE", "") >= sample_date),
            key=lambda row: row.get("SM_EXPIRY_DATE", ""),
        )
        if len(available_futures) < 2:
            raise SystemExit("Current instrument master has fewer than two NIFTY FUTIDX contracts for the probe")
        for contract in available_futures[:2]:
            security_id = contract["SECURITY_ID"]
            expiry = contract["SM_EXPIRY_DATE"]
            name = f"futures_{security_id}_{expiry}.json"
            request = {
                "securityId": security_id,
                "exchangeSegment": "NSE_FNO",
                "instrument": "FUTIDX",
                "interval": "5",
                "oi": True,
                "fromDate": "2026-09-10 09:15:00",
                "toDate": "2026-09-11 15:30:00",
            }
            response = paced_post(client, "/charts/intraday", request)
            record = persist(name, request, response)
            body = record["response"]
            print(f"FUTURES {contract.get('DISPLAY_NAME', security_id)} ({security_id}, expiry {expiry}): HTTP {response.status_code}, 5m bars={len(body.get('timestamp', []))}")

        old_probe_id = available_futures[0]["SECURITY_ID"]
        request = {
            "securityId": old_probe_id,
            "exchangeSegment": "NSE_FNO",
            "instrument": "FUTIDX",
            "interval": "5",
            "oi": True,
            "fromDate": "2022-01-12 09:15:00",
            "toDate": "2022-01-13 15:30:00",
        }
        response = paced_post(client, "/charts/intraday", request)
        record = persist(f"futures_{old_probe_id}_2022.json", request, response)
        print(f"FUTURES old-date probe: HTTP {response.status_code}, 5m bars={len(record['response'].get('timestamp', []))}")

        for day in ("2022-01-12", "2024-07-10", "2026-09-10"):
            request = {
                "exchangeSegment": "NSE_FNO",
                "interval": "5",
                "securityId": 13,
                "instrument": "OPTIDX",
                "expiryFlag": "MONTH",
                "expiryCode": 1,
                "strike": "ATM",
                "drvOptionType": "CALL",
                "requiredData": ["open", "high", "low", "close", "volume", "oi", "strike", "spot"],
                "fromDate": day,
                "toDate": day,
            }
            response = paced_post(client, "/charts/rollingoption", request)
            record = persist(f"rolling_call_{day}.json", request, response)
            body = record["response"].get("data", {}).get("ce") or {}
            print(f"OPTIONS CALL ATM {day}: HTTP {response.status_code}, 5m rows={len(body.get('timestamp', []))}, OI={len(body.get('oi', []))}")

        # Exercise both option sides and the documented ATM +/- five selector.
        for side, key in (("CALL", "ce"), ("PUT", "pe")):
            for strike in ("ATM-5", "ATM", "ATM+5"):
                request = {
                    "exchangeSegment": "NSE_FNO",
                    "interval": "5",
                    "securityId": 13,
                    "instrument": "OPTIDX",
                    "expiryFlag": "MONTH",
                    "expiryCode": 1,
                    "strike": strike,
                    "drvOptionType": side,
                    "requiredData": ["open", "high", "low", "close", "volume", "oi", "strike", "spot"],
                    "fromDate": "2024-07-10",
                    "toDate": "2024-07-10",
                }
                response = paced_post(client, "/charts/rollingoption", request)
                slug = strike.lower().replace("+", "p").replace("-", "m")
                record = persist(f"option_{side.lower()}_{slug}_2024-07-10.json", request, response)
                body = record["response"].get("data", {}).get(key) or {}
                strikes = sorted(set(body.get("strike", [])))
                print(f"OPTIONS {side} {strike}: HTTP {response.status_code}, rows={len(body.get('timestamp', []))}, OI={len(body.get('oi', []))}, resolved_strikes={len(strikes)}")

    run_metadata = {
        "started_at_utc": run_started,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "authenticated_market_data_request_attempts": _request_count,
        "transient_retries": _retry_count,
        "minimum_request_interval_seconds": MIN_REQUEST_INTERVAL,
        "credentials_persisted": False,
        "scope": "Small capability probe; not a full historical download.",
    }
    (OUT / "probe_run.json").write_text(json.dumps(run_metadata, indent=2), encoding="utf-8")
    print(f"REQUEST ATTEMPTS: {_request_count}; TRANSIENT RETRIES: {_retry_count}")


if __name__ == "__main__":
    main()
