"""
Organizes all reports in D:\AI_Trading\reports into date-partitioned directories:
    reports/<YYYY-MM-DD>/5m_reports/
    reports/<YYYY-MM-DD>/15m_reports/
    reports/<YYYY-MM-DD>/trade_reports/
"""

import os
import re
import shutil
from pathlib import Path

REPORTS_DIR = Path(r"D:\AI_Trading\reports")
DATE_PATTERN = re.compile(r"2026-\d{2}-\d{2}")
DATE_UNDERSCORE_PATTERN = re.compile(r"2026(\d{2})(\d{2})")


def get_target_dir(date_str: str, report_type: str) -> Path:
    d = REPORTS_DIR / date_str / report_type
    d.mkdir(parents=True, exist_ok=True)
    return d


def extract_date(filename: str) -> str | None:
    m = DATE_PATTERN.search(filename)
    if m:
        return m.group(0)
    m2 = DATE_UNDERSCORE_PATTERN.search(filename)
    if m2:
        return f"2026-{m2.group(1)}-{m2.group(2)}"
    return None


def organize():
    print("Beginning report reorganization...")

    # 1. Organize loose 15m_market_pdfs into <date>/15m_reports
    loose_15m_pdfs = REPORTS_DIR / "15m_market_pdfs"
    if loose_15m_pdfs.exists():
        for f in loose_15m_pdfs.glob("*.pdf"):
            dt = extract_date(f.name)
            if dt:
                dest = get_target_dir(dt, "15m_reports") / f.name
                shutil.copy2(f, dest)
                print(f"Copied {f.name} -> {dt}/15m_reports/")

    # 2. Organize loose 15m_reports into <date>/15m_reports
    loose_15m = REPORTS_DIR / "15m_reports"
    if loose_15m.exists():
        for f in loose_15m.glob("*.*"):
            if f.name.startswith("latest_"):
                continue
            dt = extract_date(f.name)
            if dt:
                dest = get_target_dir(dt, "15m_reports") / f.name
                shutil.copy2(f, dest)
                print(f"Copied {f.name} -> {dt}/15m_reports/")

    # 3. Organize loose trade_pdfs into <date>/trade_reports
    loose_trade_pdfs = REPORTS_DIR / "trade_pdfs"
    if loose_trade_pdfs.exists():
        for f in loose_trade_pdfs.glob("*.pdf"):
            dt = extract_date(f.name)
            if dt:
                dest = get_target_dir(dt, "trade_reports") / f.name
                shutil.copy2(f, dest)
                print(f"Copied {f.name} -> {dt}/trade_reports/")

    # 4. Organize loose trade_reports into <date>/trade_reports
    loose_tr = REPORTS_DIR / "trade_reports"
    if loose_tr.exists():
        for f in loose_tr.glob("*.pdf"):
            # If date not in filename, check trade_id
            dt = extract_date(f.name)
            if not dt:
                if "602117" in f.name or "957023" in f.name:
                    dt = "2026-11-27"
                elif "272060" in f.name:
                    dt = "2026-11-26"
                elif any(x in f.name for x in ["882403", "436201", "145671"]):
                    dt = "2026-11-25"
            if dt:
                dest = get_target_dir(dt, "trade_reports") / f.name
                shutil.copy2(f, dest)
                print(f"Copied {f.name} -> {dt}/trade_reports/")

    # 5. Ensure all date folders (2026-11-25, 2026-11-26, 2026-11-27) have 5m_reports, 15m_reports, trade_reports
    for d in ["2026-11-25", "2026-11-26", "2026-11-27"]:
        for sub in ["5m_reports", "15m_reports", "trade_reports"]:
            get_target_dir(d, sub)

    print("Reorganization complete!")


if __name__ == "__main__":
    organize()
