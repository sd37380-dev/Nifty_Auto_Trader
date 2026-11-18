"""
5-Year Rolling Option Contract Backfiller (Dhan HQ -> SQLite).
Downloads historical 15-minute candles for NIFTY ATM Call and Put options
from 2021 to 2026 in 25-day chunks and saves them into data/hermes_research/market_data.db.
"""

import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import os
import time
from datetime import datetime, timedelta, timezone
from typing import List
import httpx
from dotenv import load_dotenv

from nifty_trader.research_zone.contracts import NormalizedBar
from nifty_trader.research_zone.storage import MarketDataStore

load_dotenv()


def fetch_option_chunk(
    client_id: str,
    access_token: str,
    option_type: str,
    from_date_str: str,
    to_date_str: str,
) -> List[NormalizedBar]:
    url = "https://api.dhan.co/v2/charts/rollingoption"
    headers = {
        "client-id": client_id,
        "access-token": access_token,
        "Content-Type": "application/json",
    }
    payload = {
        "exchangeSegment": "NSE_FNO",
        "interval": "15",
        "securityId": "13",
        "instrument": "OPTIDX",
        "expiryFlag": "MONTH",
        "expiryCode": 1,
        "strike": "ATM",
        "drvOptionType": option_type.upper(),
        "requiredData": ["open", "high", "low", "close", "volume", "oi", "spot"],
        "fromDate": from_date_str,
        "toDate": to_date_str,
    }

    try:
        resp = httpx.post(url, headers=headers, json=payload, timeout=15.0)
        if resp.status_code == 200:
            data = resp.json().get("data", {})
            key = "ce" if option_type.upper() == "CALL" else "pe"
            opt = data.get(key)
            if opt and "open" in opt and len(opt["open"]) > 0:
                bars = []
                for o, h, l, c, v, oi, t in zip(
                    opt["open"],
                    opt["high"],
                    opt["low"],
                    opt["close"],
                    opt.get("volume", [0] * len(opt["open"])),
                    opt.get("oi", [0] * len(opt["open"])),
                    opt.get("timestamp", [0] * len(opt["open"])),
                ):
                    bar_dt = datetime.fromtimestamp(t, tz=timezone.utc)
                    bars.append(
                        NormalizedBar(
                            symbol=f"NIFTY_ATM_{key.upper()}",
                            timeframe="15M",
                            timestamp=bar_dt,
                            open=round(float(o), 2),
                            high=round(float(h), 2),
                            low=round(float(l), 2),
                            close=round(float(c), 2),
                            volume=int(v),
                            open_interest=int(oi),
                        )
                    )
                return bars
    except Exception as e:
        print(f"    [!] Error fetching {option_type} {from_date_str}: {e}")
    return []


def main():
    client_id = os.getenv("DHAN_CLIENT_ID")
    access_token = os.getenv("DHAN_ACCESS_TOKEN")

    if not client_id or not access_token:
        print("[ERROR] Missing DHAN credentials in .env")
        sys.exit(1)

    db_path = root_dir / "data" / "hermes_research" / "market_data.db"
    store = MarketDataStore(db_path)

    print("=" * 70)
    print("      DHAN 5-YEAR ROLLING OPTION CONTRACT BACKFILL (2021-2026)      ")
    print("=" * 70)
    print(f"Target Database : {db_path}")
    print(f"Contract Types  : NIFTY_ATM_CE and NIFTY_ATM_PE")
    print(f"Timeframe       : 15-Minute Candles")
    print("-" * 70)

    # Generate 25-day windows from Oct 2021 to Sep 2026
    start_dt = datetime(2021, 10, 1)
    end_dt = datetime(2026, 9, 29)
    step = timedelta(days=25)

    windows = []
    curr = start_dt
    while curr < end_dt:
        nxt = min(curr + step, end_dt)
        windows.append((curr.strftime("%Y-%m-%d"), nxt.strftime("%Y-%m-%d")))
        curr = nxt + timedelta(days=1)

    print(f"[*] Total 25-day chunks to process: {len(windows)}")
    total_ce_saved = 0
    total_pe_saved = 0

    for i, (f_str, t_str) in enumerate(windows, 1):
        # Fetch Call
        ce_bars = fetch_option_chunk(client_id, access_token, "CALL", f_str, t_str)
        time.sleep(0.2)
        # Fetch Put
        pe_bars = fetch_option_chunk(client_id, access_token, "PUT", f_str, t_str)
        time.sleep(0.2)

        saved_chunk_ce = 0
        saved_chunk_pe = 0
        if ce_bars:
            saved_chunk_ce = store.save_normalized_bars(ce_bars)
            total_ce_saved += saved_chunk_ce
        if pe_bars:
            saved_chunk_pe = store.save_normalized_bars(pe_bars)
            total_pe_saved += saved_chunk_pe

        pct = (i / len(windows)) * 100.0
        print(f"[{i:2d}/{len(windows)}] ({pct:4.1f}%) {f_str} -> {t_str} | CE: {len(ce_bars):3d} bars | PE: {len(pe_bars):3d} bars")

    print("\n" + "=" * 70)
    print("             OPTION CONTRACT BACKFILL COMPLETED!              ")
    print("=" * 70)
    print(f"Total ATM CE Option Bars Saved : {total_ce_saved:,}")
    print(f"Total ATM PE Option Bars Saved : {total_pe_saved:,}")
    print(f"Combined Option Bars Saved     : {total_ce_saved + total_pe_saved:,}")
    print(f"Database File Location         : {db_path}")


if __name__ == "__main__":
    main()
