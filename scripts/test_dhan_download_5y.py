import os
import sys
import httpx
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()
cid = os.getenv("DHAN_CLIENT_ID")
tok = os.getenv("DHAN_ACCESS_TOKEN")

print(f"Client ID: {cid[:4]}... Token present: {bool(tok)}")

headers = {
    "client-id": cid,
    "access-token": tok,
    "Content-Type": "application/json",
}

# Test 1: Historical Daily Chart from Dhan for 5 Years
print("Testing Dhan /v2/charts/historical for BANKNIFTY (2021 to 2026)...")
payload_hist = {
    "securityId": "25",
    "exchangeSegment": "IDX_I",
    "instrument": "INDEX",
    "expiryCode": 0,
    "fromDate": "2021-10-01",
    "toDate": "2026-10-02"
}

try:
    resp = httpx.post("https://api.dhan.co/v2/charts/historical", headers=headers, json=payload_hist, timeout=15.0)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(f"Historical bars returned: {len(data.get('open', []))}")
        if data.get('open'):
            print("First bar:", data['open'][0], data['close'][0], datetime.fromtimestamp(data['timestamp'][0], tz=timezone.utc))
            print("Last bar:", data['open'][-1], data['close'][-1], datetime.fromtimestamp(data['timestamp'][-1], tz=timezone.utc))
    else:
        print("Response text:", resp.text)
except Exception as e:
    print(f"Error: {e}")

# Test 2: Intraday 1-Hour Chart from Dhan
print("\nTesting Dhan /v2/charts/intraday for BANKNIFTY (60-min interval)...")
payload_intra = {
    "securityId": "25",
    "exchangeSegment": "IDX_I",
    "instrument": "INDEX",
    "interval": "60",
    "fromDate": "2026-08-01 09:15:00",
    "toDate": "2026-10-02 15:30:00"
}
try:
    resp = httpx.post("https://api.dhan.co/v2/charts/intraday", headers=headers, json=payload_intra, timeout=15.0)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(f"Intraday 1H bars returned: {len(data.get('open', []))}")
    else:
        print("Response text:", resp.text)
except Exception as e:
    print(f"Error: {e}")
