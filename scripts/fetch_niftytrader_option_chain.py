#!/usr/bin/env python3
"""
Fetch NIFTY option chain data directly from NiftyTrader Web API
and save it locally to data/nifty_option_chain.json and data/nifty_option_chain.csv.
"""

import os
import json
import gzip
import urllib.request
import csv

from pathlib import Path
from dotenv import load_dotenv

# Load credentials from .env in repository root or current directory
env_path = Path(__file__).resolve().parent / "nifty-autonomous-trader" / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

BEARER_TOKEN = os.getenv("NIFTYTRADER_BEARER_TOKEN", "").strip()
API_KEY = os.getenv("NIFTYTRADER_API_KEY", "").strip()
API_URL = "https://webapi.niftytrader.in/webapi/option/option-chain-data?symbol=nifty&exchange=nse"

def fetch_option_chain():
    headers = {
        "Authorization": f"Bearer {BEARER_TOKEN}",
        "x-api-key": API_KEY,
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "Referer": "https://www.niftytrader.in/",
        "Origin": "https://www.niftytrader.in"
    }

    print(f"Connecting to {API_URL}...")
    req = urllib.request.Request(API_URL, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        content = resp.read()
        if resp.info().get("Content-Encoding") == "gzip":
            content = gzip.decompress(content)
        data = json.loads(content.decode("utf-8"))

    if data.get("result") != 1:
        print(f"Error fetching data: {data.get('resultMessage')}")
        return

    result_data = data.get("resultData", {})
    op_datas = result_data.get("opDatas", [])
    print(f"Successfully retrieved {len(op_datas)} strikes.")

    # Save to data directory
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    os.makedirs(out_dir, exist_ok=True)

    json_path = os.path.join(out_dir, "nifty_option_chain.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result_data, f, indent=2)
    print(f"Saved JSON to: {json_path}")

    if op_datas:
        csv_path = os.path.join(out_dir, "nifty_option_chain.csv")
        keys = list(op_datas[0].keys())
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(op_datas)
        print(f"Saved CSV to: {csv_path}")

if __name__ == "__main__":
    fetch_option_chain()
