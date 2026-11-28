"""Tests for 5-minute and 15-minute PDF-only Market Status Summary Bulletins."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from nifty_trader.market_data.report_service import (
    FifteenMinuteReportService,
    TradeIntelligenceReportService,
    get_5m_report_service,
    get_15m_report_service,
    get_report_service,
)

IST = timezone(timedelta(hours=5, minutes=30))


def _sample_candles():
    base_ts = int(datetime.now(IST).replace(hour=9, minute=15, second=0, microsecond=0).timestamp())
    return [
        {"time": base_ts, "open": 25700.0, "high": 25740.0, "low": 25690.0, "close": 25730.0, "volume": 12000},
        {"time": base_ts + 300, "open": 25730.0, "high": 25760.0, "low": 25720.0, "close": 25755.0, "volume": 15000},
    ]


def _fake_html_to_pdf(html_path: Path, pdf_path: Path) -> bool:
    assert html_path.exists()
    pdf_path.write_bytes(b"%PDF-1.4\n%fake\n")
    return True


def test_5m_and_15m_bulletins_write_only_pdfs_in_date_subfolders(tmp_path: Path):
    pkg_root = tmp_path / "nifty-autonomous-trader"
    pkg_root.mkdir()

    srv_5m = TradeIntelligenceReportService(root_dir=pkg_root, interval_minutes=5)
    srv_15m = TradeIntelligenceReportService(root_dir=pkg_root, interval_minutes=15)

    with (
        patch("nifty_trader.market_data.report_service._fetch_intraday_candles", return_value=_sample_candles()),
        patch("nifty_trader.market_data.report_service._html_to_pdf", side_effect=_fake_html_to_pdf),
    ):
        out_5m = srv_5m.generate_report()
        out_15m = srv_15m.generate_report()

    today_ist = datetime.now(IST).strftime("%Y-%m-%d")

    assert out_5m["status"] == "ok"
    assert out_5m["date_folder"] == today_ist
    assert out_5m["sub_folder"] == "5m_reports"
    assert len(out_5m["pdfs"]) == 2

    assert out_15m["status"] == "ok"
    assert out_15m["date_folder"] == today_ist
    assert out_15m["sub_folder"] == "15m_reports"
    assert len(out_15m["pdfs"]) == 2

    for base in (pkg_root / "reports" / today_ist, tmp_path / "reports" / today_ist):
        for sub in ("5m_reports", "15m_reports"):
            files = list((base / sub).iterdir())
            assert len(files) == 1
            assert files[0].suffix == ".pdf"
            assert files[0].name.startswith("Market_Bulletin_")


def test_singletons_are_separate_per_interval(tmp_path: Path):
    TradeIntelligenceReportService._instances.clear()
    s5 = get_5m_report_service(tmp_path)
    s15 = get_15m_report_service(tmp_path)
    s15_default = get_report_service(tmp_path)

    assert s5 is not s15
    assert s15 is s15_default
    assert s5.interval_seconds == 300
    assert s15.interval_seconds == 900
    assert isinstance(FifteenMinuteReportService(tmp_path), TradeIntelligenceReportService)
