#!/usr/bin/env python3
"""
Fetch NIFTY & BANKNIFTY option chain data directly from NiftyTrader Web API
with automated dynamic API-key rotation and zero synthetic data fallback.
Saves data to data/nifty_option_chain.json and data/nifty_option_chain.csv.
"""

import base64
import csv
import gzip
import json
import os
from pathlib import Path
import time
import urllib.request
from dotenv import load_dotenv

env_path = Path(__file__).resolve().parent.parent / ".env"
if not env_path.exists():
    env_path = Path(__file__).resolve().parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

BEARER_TOKEN = os.getenv(
    "NIFTYTRADER_BEARER_TOKEN",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJodHRwOi8vc2NoZW1hcy54bWxzb2FwLm9yZy93cy8yMDA1LzA1L2lkZW50aXR5L2NsYWltcy9uYW1laWRlbnRpZmllciI6IjEzNDk2ODAiLCJodHRwOi8vc2NoZW1hcy5taWNyb3NvZnQuY29tL3dzLzIwMDgvMDYvaWRlbnRpdHkvY2xhaW1zL3JvbGUiOiIwIiwiU2Vzc2lvbklkIjoiNjQ2NiIsImV4cCI6MTc5Nzc1NTkyNCwiaXNzIjoicHJvZC1uaWZ0eXRyYWRlci5pbiIsImF1ZCI6InByb2QtbmlmdHl0cmFkZXIuaW4ifQ.dJXGpCXUrRGia7f1J3jCTmH6gPeQ6ovsXhX5HdtA494",
).strip()

SSR_SECRET = "c3a5b7d9e1f02a4c6b8d0f1e3a5c7d9b2e4a6f8c0b1d3e5a7f9c2b4d6e8a0f1c3b5d7e9a1f2b4c6d8e0f1a3b5c7d9e2f4a6b8c0d1e3f5a7b9c2d4e6f8a0b"


def get_fresh_api_key() -> str:
    """Dynamically requests the latest valid API key from NiftyTrader onboarding."""
    try:
        url = "https://onboarding.niftytrader.in/api/api-key"
        headers = {
            "Accept": "application/json",
            "X-SSR-Secret": SSR_SECRET,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            key = data.get("resultData", {}).get("apiKey")
            if key:
                print(f"Refreshed NiftyTrader API key: {key[:20]}...")
                os.environ["NIFTYTRADER_API_KEY"] = key
                if env_path.exists():
                    try:
                        content = env_path.read_text(encoding="utf-8")
                        lines = []
                        updated = False
                        for line in content.splitlines():
                            if line.startswith("NIFTYTRADER_API_KEY="):
                                lines.append(f"NIFTYTRADER_API_KEY={key}")
                                updated = True
                            else:
                                lines.append(line)
                        if not updated:
                            lines.append(f"NIFTYTRADER_API_KEY={key}")
                        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                    except Exception as e:
                        print(f"Notice: Could not persist to .env: {e}")
                return key
    except Exception as e:
        print(f"Error refreshing API key: {e}")
    return os.getenv("NIFTYTRADER_API_KEY", "").strip()


def is_api_key_valid(key: str) -> bool:
    """Checks if key is non-empty and timestamp is not expired."""
    if not key or "." not in key:
        return False
    try:
        ts_part = key.split(".")[0]
        ts_part += "=" * (-len(ts_part) % 4)
        ts = int(base64.b64decode(ts_part).decode("utf-8"))
        return ts > (time.time() + 60)
    except Exception:
        return True


def fetch_option_chain(symbol: str = "nifty"):
    sym = "banknifty" if "BANK" in symbol.upper() else "nifty"
    api_url = f"https://webapi.niftytrader.in/webapi/option/option-chain-data?symbol={sym}&exchange=nse"

    api_key = os.getenv("NIFTYTRADER_API_KEY", "").strip()
    if not is_api_key_valid(api_key):
        api_key = get_fresh_api_key()

    for attempt in range(2):
        headers = {
            "Authorization": f"Bearer {BEARER_TOKEN}",
            "x-api-key": api_key,
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
            "Referer": "https://www.niftytrader.in/",
            "Origin": "https://www.niftytrader.in",
        }

        print(f"Connecting to {api_url} (attempt {attempt + 1})...")
        try:
            req = urllib.request.Request(api_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                content = resp.read()
                if resp.info().get("Content-Encoding") == "gzip":
                    content = gzip.decompress(content)
                data = json.loads(content.decode("utf-8"))

            if data.get("result") == 1:
                result_data = data.get("resultData", {})
                op_datas = result_data.get("opDatas", [])
                print(f"Successfully retrieved {len(op_datas)} strikes for {sym.upper()}.")

                dirs = [
                    Path(__file__).resolve().parent.parent / "data",
                    Path(__file__).resolve().parent.parent.parent / "data",
                ]
                for out_dir in dirs:
                    out_dir.mkdir(parents=True, exist_ok=True)
                    json_path = out_dir / f"{sym}_option_chain.json"
                    with open(json_path, "w", encoding="utf-8") as f:
                        json.dump(result_data, f, indent=2)
                    print(f"Saved JSON to: {json_path}")

                    if op_datas:
                        csv_path = out_dir / f"{sym}_option_chain.csv"
                        keys = list(op_datas[0].keys())
                        with open(csv_path, "w", newline="", encoding="utf-8") as f:
                            writer = csv.DictWriter(f, fieldnames=keys)
                            writer.writeheader()
                            writer.writerows(op_datas)
                        print(f"Saved CSV to: {csv_path}")
                return result_data
            else:
                msg = str(data.get("resultMessage", ""))
                print(f"API notice: {msg}")
                if "Unauthorized" in msg and attempt == 0:
                    api_key = get_fresh_api_key()
                    continue
        except Exception as e:
            print(f"Fetch error on attempt {attempt + 1}: {e}")
            if attempt == 0:
                api_key = get_fresh_api_key()
                continue
    return None


if __name__ == "__main__":
    fetch_option_chain("nifty")
