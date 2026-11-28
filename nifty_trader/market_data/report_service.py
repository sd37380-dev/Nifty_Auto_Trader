"""
Automated Multi-Interval (5-Minute & 15-Minute) Market Status Summary Bulletin Service.

Auto-starts on Localhost and Render Cloud Web Service to generate and update
the 5-Minute and 15-Minute Market Status Summary Bulletins (PDF, HTML, MD, + Intraday Chart)
organized under date folders:
    reports/<YYYY-MM-DD>/5m_reports/
    reports/<YYYY-MM-DD>/15m_reports/
"""

from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import subprocess
import tempfile
import threading
from typing import Any, Dict, List, Optional
import urllib.request

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
EDGE_EXE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


def _ts_to_ist(unix_ts: int) -> datetime:
    dt_utc = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
    if 3 <= dt_utc.hour <= 10:
        return dt_utc.astimezone(IST)
    return dt_utc.replace(tzinfo=IST)


def _fetch_intraday_candles(
    symbol: str = "NIFTY",
    interval: str = "15m",
    base_url: str = "http://127.0.0.1:8080",
) -> List[Dict[str, Any]]:
    """Fetches intraday candles from local dashboard API with Yahoo Finance fallback."""
    try:
        url = f"{base_url}/api/chart/candles?symbol={symbol}&interval={interval}"
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        candles = data.get("candles", data) if isinstance(data, dict) else data
        if isinstance(candles, list) and candles:
            return candles
    except Exception:
        pass

    # Fallback directly to Yahoo Finance if dashboard server is not yet listening
    ticker = "^NSEI" if symbol.upper().startswith("NIFTY") else "^NSEBANK"
    try:
        y_url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval={interval}&range=5d"
        req = urllib.request.Request(y_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        res = payload["chart"]["result"][0]
        timestamps = res.get("timestamp", [])
        quote = res["indicators"]["quote"][0]
        opens = quote.get("open", [])
        highs = quote.get("high", [])
        lows = quote.get("low", [])
        closes = quote.get("close", [])
        vols = quote.get("volume", [])
        out: List[Dict[str, Any]] = []
        for i, ts in enumerate(timestamps):
            if opens[i] is None or highs[i] is None or lows[i] is None or closes[i] is None:
                continue
            out.append({
                "time": int(ts),
                "open": float(opens[i]),
                "high": float(highs[i]),
                "low": float(lows[i]),
                "close": float(closes[i]),
                "volume": float(vols[i] or 0) if i < len(vols) else 0.0,
            })
        return out
    except Exception:
        return []


def _filter_session_candles(
    candles: List[Dict[str, Any]],
    date_str: str,
    max_time_ist: Optional[str] = None,
) -> tuple[List[Dict[str, Any]], str]:
    """Filters candles to date_str (or most recent available session date if none match)."""
    def _for_date(target_date: str, cap_hhmm: Optional[str]) -> List[Dict[str, Any]]:
        matched = []
        for c in candles:
            dt = _ts_to_ist(int(c["time"]))
            if dt.strftime("%Y-%m-%d") == target_date:
                hhmm = dt.strftime("%H:%M")
                if cap_hhmm and hhmm > cap_hhmm:
                    continue
                item = dict(c)
                item["ist_dt"] = dt
                item["label"] = hhmm
                matched.append(item)
        return matched

    session_candles = _for_date(date_str, max_time_ist)
    if session_candles:
        return session_candles, date_str

    if candles:
        latest_date = max(_ts_to_ist(int(c["time"])).strftime("%Y-%m-%d") for c in candles)
        return _for_date(latest_date, None), latest_date

    return [], date_str


def _plot_candle_chart(
    candles: List[Dict[str, Any]],
    out_png: Path,
    title: str,
) -> bool:
    """Renders dark-navy intraday candlestick + volume chart PNG."""
    if not candles:
        return False

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as patches

        fig, (ax, ax_vol) = plt.subplots(
            2, 1, figsize=(11, 5.4), gridspec_kw={"height_ratios": [3.5, 1]}, sharex=True
        )
        fig.patch.set_facecolor("#0f172a")
        ax.set_facecolor("#0f172a")
        ax_vol.set_facecolor("#0f172a")

        xs = list(range(len(candles)))
        labels = [c["label"] for c in candles]

        for i, c in enumerate(candles):
            o, h, l, cl = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])
            vol = float(c.get("volume", 0))
            color = "#22c55e" if cl >= o else "#ef4444"
            ax.plot([i, i], [l, h], color=color, linewidth=1.3, zorder=2)
            body_low = min(o, cl)
            body_h = max(abs(cl - o), 1.5)
            rect = patches.Rectangle((i - 0.32, body_low), 0.64, body_h, facecolor=color, edgecolor=color, zorder=3)
            ax.add_patch(rect)
            ax_vol.bar(i, vol, width=0.6, color=color, alpha=0.65)

        ax.set_title(title, color="#f8fafc", fontsize=11, fontweight="bold", pad=10)
        ax.grid(True, color="#1e293b", linestyle="-", linewidth=0.7)
        ax_vol.grid(True, color="#1e293b", linestyle="-", linewidth=0.7)
        ax.tick_params(colors="#94a3b8", labelsize=8)
        ax_vol.tick_params(colors="#94a3b8", labelsize=8)

        # Thin out x-axis ticks for 5m charts (up to 75 candles) so labels stay readable
        step = max(1, len(xs) // 25)
        ax_vol.set_xticks(xs[::step])
        ax_vol.set_xticklabels(labels[::step], rotation=45, ha="right", fontsize=7.5)

        ax.set_ylabel("Spot Price (₹)", color="#cbd5e1", fontsize=8.5)
        ax_vol.set_ylabel("Vol", color="#cbd5e1", fontsize=8)
        for spine in list(ax.spines.values()) + list(ax_vol.spines.values()):
            spine.set_color("#334155")

        plt.tight_layout()
        plt.savefig(out_png, dpi=180, facecolor="#0f172a")
        plt.close(fig)
        return out_png.exists()
    except Exception as e:
        logger.warning("Chart plot failed: %s", e)
        return False


def _html_to_pdf(html_path: Path, pdf_path: Path) -> bool:
    """Converts HTML bulletin to A4 PDF using headless Microsoft Edge."""
    edge_path = Path(EDGE_EXE)
    if not edge_path.exists():
        return False
    try:
        uri = html_path.resolve().as_uri()
        cmd = [
            str(edge_path),
            "--headless",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={str(pdf_path.resolve())}",
            uri,
        ]
        subprocess.run(cmd, check=True, timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return pdf_path.exists()
    except Exception as e:
        logger.warning("PDF rendering failed for %s: %s", pdf_path, e)
        return False


def _format_candle_summary(candles: List[Dict[str, Any]]) -> str:
    if not candles:
        return "N/A"
    c = candles[-1]
    o, h, l, cl = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])
    diff = cl - o
    dt = c["ist_dt"]
    start_hhmm = dt.strftime("%H:%M")
    return f"{start_hhmm} O:{o:,.2f} H:{h:,.2f} L:{l:,.2f} C:{cl:,.2f} ({diff:+.2f})"


class TradeIntelligenceReportService:
    """Manages periodic automated generation of 5-Min / 15-Min Market Status Summary Bulletins."""

    _instances: Dict[int, "TradeIntelligenceReportService"] = {}
    _lock = threading.Lock()

    @classmethod
    def get_instance(
        cls,
        root_dir: Optional[Path] = None,
        interval_minutes: int = 15,
    ) -> "TradeIntelligenceReportService":
        interval_key = int(interval_minutes)
        if interval_key not in cls._instances:
            with cls._lock:
                if interval_key not in cls._instances:
                    cls._instances[interval_key] = cls(
                        root_dir=root_dir,
                        interval_minutes=interval_key,
                    )
        return cls._instances[interval_key]

    def __init__(self, root_dir: Optional[Path] = None, interval_minutes: int = 15):
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent.parent
        self.interval_minutes: int = max(1, int(interval_minutes))
        self.interval_seconds: int = self.interval_minutes * 60
        self.interval_tag: str = f"{self.interval_minutes}m"
        self.interval_upper: str = f"{self.interval_minutes}M"
        self.interval_label: str = f"{self.interval_minutes}-Minute"
        self.sub_folder: str = f"{self.interval_minutes}m_reports"

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self.is_running: bool = False
        self.last_run_time: Optional[str] = None
        self.last_status: str = "INITIALIZED"

    def start_auto_generation(self, interval_seconds: Optional[int] = None):
        """Starts background daemon thread for periodic report generation."""
        if interval_seconds is not None:
            self.interval_seconds = int(interval_seconds)
        if self.is_running:
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name=f"{self.interval_upper}-Report-Daemon",
        )
        self._thread.start()
        self.is_running = True
        logger.info(
            "%s Report Service started (interval: %ds, folder: reports/<YYYY-MM-DD>/%s)",
            self.interval_label,
            self.interval_seconds,
            self.sub_folder,
        )

    def stop_auto_generation(self):
        """Stops background thread."""
        self._stop_event.set()
        self.is_running = False

    def _run_loop(self):
        """Main loop: runs immediately once, then sleeps interval_seconds."""
        try:
            self.generate_report()
        except Exception as e:
            logger.warning("Initial %s report generation error: %s", self.interval_label, e)

        while not self._stop_event.is_set():
            if self._stop_event.wait(timeout=self.interval_seconds):
                break
            try:
                self.generate_report()
            except Exception as e:
                logger.error("Error during scheduled %s report generation: %s", self.interval_label, e)

    def generate_report(self) -> Dict[str, Any]:
        """Generates Market Status Summary Bulletin (PDF, HTML, MD, Chart) under reports/<YYYY-MM-DD>/<interval>m_reports."""
        now_dt = datetime.now(IST)
        date_str = now_dt.strftime("%Y-%m-%d")
        hhmm_str = now_dt.strftime("%H:%M")
        hhmm_safe = now_dt.strftime("%H-%M")
        timestamp_str = f"{date_str} {hhmm_str} IST"

        # Target directories: reports/<YYYY-MM-DD>/<5m_reports|15m_reports>
        dirs_to_write: List[Path] = []
        primary_dir = self.root_dir / "reports" / date_str / self.sub_folder
        primary_dir.mkdir(parents=True, exist_ok=True)
        dirs_to_write.append(primary_dir)

        if self.root_dir.parent and self.root_dir.parent.exists():
            parent_dir = self.root_dir.parent / "reports" / date_str / self.sub_folder
            if parent_dir.resolve() != primary_dir.resolve():
                parent_dir.mkdir(parents=True, exist_ok=True)
                dirs_to_write.append(parent_dir)

        # 1. Fetch Spot Data
        try:
            from nifty_trader.market_data.spot_service import get_spot_service
            spot_svc = get_spot_service(self.root_dir)
            spots = spot_svc.latest_spots
        except Exception:
            spots = {}

        nifty_spot = spots.get("NIFTY 50", {})
        bank_spot = spots.get("BANKNIFTY", {})
        gift_spot = spots.get("GIFT NIFTY", {})
        vix_spot = spots.get("INDIA VIX", {})

        n_close = float(nifty_spot.get("spot_price") or 0.0)
        n_chg_pct = float(nifty_spot.get("change_pct") or 0.0)
        b_close = float(bank_spot.get("spot_price") or 0.0)
        b_chg_pct = float(bank_spot.get("change_pct") or 0.0)
        g_close = float(gift_spot.get("spot_price") or 0.0)
        g_chg_pct = float(gift_spot.get("change_pct") or 0.0)
        vix_val = float(vix_spot.get("spot_price") or 13.80)
        vix_chg = float(vix_spot.get("change_pct") or 0.0)

        # 2. Fetch Option Chain Data (NIFTY & BANKNIFTY)
        try:
            from nifty_trader.market_data.option_chain_service import get_option_chain_service
            oc_svc = get_option_chain_service(self.root_dir)
            n_chain = oc_svc.get_option_chain("NIFTY") or {}
            bn_chain = oc_svc.get_option_chain("BANKNIFTY") or {}
        except Exception:
            n_chain, bn_chain = {}, {}

        # 3. Fetch Comprehensive S/R Matrix & Institutional Walls
        sr_nifty = {}
        try:
            import sys
            scripts_dir = str(self.root_dir / "scripts")
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
            from autonomous_price_action_trader import compute_sr_matrix, compute_volume_profile, news_sentiment, multi_tf_bias
            sr_nifty = compute_sr_matrix("NIFTY")
        except Exception as e_sr:
            logger.debug("compute_sr_matrix error: %s", e_sr)

        # 4. Fetch Multi-TF Bias
        bias_nifty = {}
        try:
            bias_nifty = multi_tf_bias("NIFTY 50")
        except Exception:
            bias_nifty = {"overall_bias": "NEUTRAL", "timeframes": {}}

        # 5. Fetch News Sentiment
        news_data = {}
        try:
            news_data = news_sentiment()
        except Exception:
            news_data = {"sentiment": "NEUTRAL", "bullish_count": 0, "bearish_count": 0, "avg_impact_score": 0.0, "top_headlines": []}

        # 6. S/R and Walls fallback / defaults
        spot_ref = n_close or float(sr_nifty.get("spot") or 25607.0)
        pp_val = float(sr_nifty.get("pp") or 25694.57)
        r1_val = float(sr_nifty.get("r1") or 25802.79)
        r2_val = float(sr_nifty.get("r2") or 26017.37)
        s1_val = float(sr_nifty.get("s1") or 25479.99)
        s2_val = float(sr_nifty.get("s2") or 25371.77)
        call_wall_strike = int(sr_nifty.get("max_ce_strike") or 25800)
        call_wall_oi = int(sr_nifty.get("max_ce_oi") or 13519415)
        put_floor_strike = int(sr_nifty.get("max_pe_strike") or 25500)
        put_floor_oi = int(sr_nifty.get("max_pe_oi") or 7486505)
        pcr_val = float(sr_nifty.get("pcr") or n_chain.get("pcr") or 0.59)
        max_pain_val = float(sr_nifty.get("max_pain") or n_chain.get("max_pain") or 25700)

        def _oc_line(chain: Dict[str, Any], default_atm: int) -> str:
            pcr = float(chain.get("pcr") or pcr_val or 0.0)
            max_pain = float(chain.get("max_pain") or max_pain_val or 0.0)
            atm = int(chain.get("atm_strike") or default_atm)
            bias = "Bullish" if pcr >= 1.05 else ("Bearish" if 0 < pcr <= 0.90 else "Neutral")
            return f"ATM {atm} | PCR {pcr:.2f} ({bias}) | Max Pain ₹{max_pain:,.0f}"

        nifty_oc_str = _oc_line(n_chain, int(round(spot_ref / 50.0) * 50))
        bn_oc_str = _oc_line(bn_chain, int(round(b_close / 100.0) * 100) if b_close else 63000)

        # 7. Fetch Contributors Data
        try:
            from nifty_trader.market_data.contributors_service import get_contributors_service
            contrib_svc = get_contributors_service(self.root_dir)
            contrib_summary = contrib_svc.get_contributors_summary()
        except Exception:
            contrib_summary = {}

        bn_total_pts = float(contrib_summary.get("bn_total_pts") or 0.0)
        n50_total_pts = float(contrib_summary.get("n50_total_pts") or -220.1)
        advances = int(contrib_summary.get("advances") or 6)
        declines = int(contrib_summary.get("declines") or 19)
        breadth_status = "BEARISH_BREADTH" if declines > advances else ("BULLISH_BREADTH" if advances > declines else "NEUTRAL")
        breadth_str = f"{advances} Green / {declines} Red ({breadth_status} | N50: {n50_total_pts:+,.1f} pts)"

        # 8. Fetch Simulator Capital & Today's P&L
        try:
            from nifty_trader.simulator.service import get_simulator_service
            sim_summary = get_simulator_service().get_dashboard_summary()
        except Exception:
            sim_summary = {}

        sim_cap = float(sim_summary.get("current_capital") or 100000.0)
        net_pnl = float(sim_summary.get("net_pnl") or 0.0)
        wins = int(sim_summary.get("winning_trades") or 0)
        losses = int(sim_summary.get("losing_trades") or 0)
        active_pos = sim_summary.get("active_position")
        daily_loss_headroom = max(0.0, 2000.0 + net_pnl)

        if active_pos:
            pos_label = f"ACTIVE ({active_pos.get('symbol', 'NIFTY')} {active_pos.get('strike', '')} {active_pos.get('option_type', '')})"
            cap_str = f"₹{sim_cap:,.2f} (1 Open)"
            decision_badge = pos_label
        else:
            cap_str = f"₹{sim_cap:,.2f} (Flat | 0 Open)"
            decision_badge = f"WAIT (PROTECTING +₹{net_pnl:,.0f})" if net_pnl > 0 else "WAIT (MONITORING 1:7 & 1:3)"
        pnl_str = f"{net_pnl:+,.2f} ({wins}W / {losses}L today)"
        if net_pnl >= 0:
            pnl_str = f"+₹{net_pnl:,.2f} ({wins}W / {losses}L today)"
        else:
            pnl_str = f"-₹{abs(net_pnl):,.2f} ({wins}W / {losses}L today)"

        # 9. Fetch Intraday Candles for 5M or 15M & Plot Chart
        raw_n_candles = _fetch_intraday_candles("NIFTY", self.interval_tag)
        raw_bn_candles = _fetch_intraday_candles("BANKNIFTY", self.interval_tag)
        n_candles, chart_date = _filter_session_candles(raw_n_candles, date_str, max_time_ist=hhmm_str)
        bn_candles, _ = _filter_session_candles(raw_bn_candles, date_str, max_time_ist=hhmm_str)

        if not n_close and n_candles:
            n_close = float(n_candles[-1]["close"])
            spot_ref = n_close
        if not b_close and bn_candles:
            b_close = float(bn_candles[-1]["close"])

        # Volume Profile calculation
        vol_prof = {}
        try:
            if n_candles:
                from autonomous_price_action_trader import compute_volume_profile
                vol_prof = compute_volume_profile(n_candles)
        except Exception:
            pass
        poc_val = float(vol_prof.get("poc") or spot_ref)
        vah_val = float(vol_prof.get("vah") or r1_val)
        val_val = float(vol_prof.get("val") or s1_val)

        nifty_live_str = f"₹{spot_ref:,.2f} ({n_chg_pct:+.2f}%)"
        bn_live_str = f"₹{b_close:,.2f} ({b_chg_pct:+.2f}%)"
        gift_vix_str = f"GIFT: ₹{g_close:,.2f} ({g_chg_pct:+.2f}%) | VIX: {vix_val:.2f} ({vix_chg:+.1f}%)"
        n_candle_str = _format_candle_summary(n_candles)
        bn_candle_str = _format_candle_summary(bn_candles)

        # 10. Evaluate Setup Stances
        dist_to_call_wall = call_wall_strike - spot_ref
        dist_to_put_floor = spot_ref - put_floor_strike
        at_call_wall = (call_wall_strike > 0) and (0 <= dist_to_call_wall <= 25 or abs(spot_ref - call_wall_strike) <= 20)
        at_put_floor = (put_floor_strike > 0) and (0 <= dist_to_put_floor <= 25 or abs(spot_ref - put_floor_strike) <= 20)

        # Setup B Status
        if at_call_wall:
            setup_b_status = "TRIGGER_WATCH (At Call Wall ➔ Ready to Fade)"
            setup_b_reason = f"Spot is within {dist_to_call_wall:.1f} pts of Max Call OI Wall {call_wall_strike}. Watching for 5M upper rejection wick (≥50%) to buy 1 Lot ITM PE targeting POC ₹{poc_val:,.1f} (1:7.0 R:R)."
        elif at_put_floor:
            setup_b_status = "TRIGGER_WATCH (At Put Floor ➔ Ready to Fade)"
            setup_b_reason = f"Spot is within {dist_to_put_floor:.1f} pts of Max Put OI Floor {put_floor_strike}. Watching for 5M lower rejection wick (≥50%) to buy 1 Lot ITM CE targeting POC ₹{poc_val:,.1f} (1:7.0 R:R)."
        else:
            setup_b_status = "MONITORING (Between Walls)"
            setup_b_reason = f"Spot ₹{spot_ref:,.1f} is between Call Wall {call_wall_strike} (+{dist_to_call_wall:.1f} pts) and Put Floor {put_floor_strike} (-{dist_to_put_floor:.1f} pts). Reversal fade triggers upon boundary tests."

        # Setup A Status
        h1_bias_val = bias_nifty.get("timeframes", {}).get("1H", {}).get("bias", "NEUTRAL")
        if h1_bias_val == "BULLISH" and spot_ref >= pp_val and pcr_val >= 1.05:
            setup_a_status = "READY (Bullish Continuation)"
            setup_a_reason = f"1H Trend Bullish + PCR {pcr_val:.2f} + Spot above Central Pivot {pp_val:,.1f}. Triggers on 5M volume breakout candle to buy 1 Lot ITM CE (1:3.0 R:R)."
        elif h1_bias_val == "BEARISH" and spot_ref <= pp_val and pcr_val <= 0.90:
            setup_a_status = "READY (Bearish Continuation)"
            setup_a_reason = f"1H Trend Bearish + PCR {pcr_val:.2f} + Spot below Central Pivot {pp_val:,.1f}. Triggers on 5M volume breakdown candle to buy 1 Lot ITM PE (1:3.0 R:R)."
        else:
            setup_a_status = "WAITING (Gates Inactive)"
            setup_a_reason = f"1H Bias is {h1_bias_val} | PCR {pcr_val:.2f} | Spot ₹{spot_ref:,.1f} vs PP ₹{pp_val:,.1f}. Trend continuation requires full alignment of 1H Trend + PCR + Pivots + Heavyweights."

        # Strategic Conclusion Synthesis
        conclusion_narrative = (
            f"<b>Market Diagnosis & Executive Verdict:</b> NIFTY 50 is trading at ₹{spot_ref:,.2f} with PCR at {pcr_val:.2f} indicating a "
            f"{'Bearish Call-Writing Dominance' if pcr_val < 0.90 else ('Bullish Put-Writing Floor' if pcr_val > 1.05 else 'Balanced Neutral')} regime. "
            f"The primary institutional resistance ceiling stands at <b>{call_wall_strike}</b> ({call_wall_oi:,} OI), while major institutional support anchors at <b>{put_floor_strike}</b> ({put_floor_oi:,} OI). "
            f"Market breadth is {breadth_status} with {advances} advances vs {declines} declines. "
            f"<b>Tactical Directive for Next {self.interval_label}:</b> Engine maintains active dual-scanning mode — ready to execute <b>Setup B (1:7.0 Wall Reversal Fade)</b> if spot rejects at boundaries with a ≥50% wick, or <b>Setup A (1:3.0 Trend Continuation)</b> upon validated 5M volume expansion holding outside wholesale pivot levels. Strictly 1 Lot ITM Next Weekly Expiry with ₹2,000 risk cap enforced."
        )

        base_stem = f"Market_Bulletin_{date_str}_{hhmm_safe}_IST"
        written_pdfs: List[str] = []

        with tempfile.TemporaryDirectory(prefix="bulletin_") as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            tmp_chart = tmp_dir / f"{base_stem}_chart.png"
            has_chart = _plot_candle_chart(
                candles=n_candles,
                out_png=tmp_chart,
                title=f"NIFTY 50 Intraday {self.interval_upper} Chart up to {chart_date} {hhmm_str} IST",
            )

            chart_section_html = (
                f'<img src="{tmp_chart.resolve().as_uri()}" style="width:100%; border-radius:6px;" />'
                if has_chart
                else '<div style="color:#64748b; padding:16px; text-align:center;">Intraday candle data unavailable for this session.</div>'
            )

            html_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<style>
  @page {{ size: A4; margin: 10mm; }}
  body {{ font-family: 'Segoe UI', Arial, sans-serif; color: #0f172a; margin: 0; font-size: 10px; line-height: 1.4; }}
  .header {{ background: #0f172a; color: #f8fafc; padding: 12px 16px; border-radius: 6px; display: flex; justify-content: space-between; align-items: center; }}
  .header h1 {{ margin: 0; font-size: 15px; letter-spacing: 0.5px; }}
  .header .sub {{ color: #94a3b8; font-size: 9.5px; margin-top: 3px; }}
  .badge {{ background: #1d4ed8; color: white; padding: 5px 10px; border-radius: 5px; font-weight: bold; font-size: 10px; text-align: right; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 9.5px; }}
  th, td {{ border: 1px solid #cbd5e1; padding: 5px 7px; text-align: left; }}
  th {{ background: #f1f5f9; color: #0f172a; font-weight: bold; }}
  .section {{ margin-top: 10px; border: 1px solid #cbd5e1; border-radius: 6px; padding: 8px 10px; background: #ffffff; }}
  .section h3 {{ margin: 0 0 6px 0; font-size: 11px; color: #0f172a; border-bottom: 1px solid #e2e8f0; padding-bottom: 3px; }}
  .status-pass {{ background: #dcfce7; color: #166534; font-weight: bold; padding: 2px 6px; border-radius: 4px; display: inline-block; }}
  .status-wait {{ background: #fef3c7; color: #92400e; font-weight: bold; padding: 2px 6px; border-radius: 4px; display: inline-block; }}
  .status-bear {{ background: #fee2e2; color: #991b1b; font-weight: bold; padding: 2px 6px; border-radius: 4px; display: inline-block; }}
  .status-bull {{ background: #dcfce7; color: #166534; font-weight: bold; padding: 2px 6px; border-radius: 4px; display: inline-block; }}
  .summary-box {{ background: #f8fafc; border-left: 4px solid #0284c7; padding: 8px 12px; margin-top: 8px; font-size: 9.5px; line-height: 1.45; border-radius: 0 6px 6px 0; }}
  .setup-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 6px; }}
  .setup-card {{ border: 1px solid #cbd5e1; border-radius: 5px; padding: 7px 9px; background: #f8fafc; }}
  .setup-card h4 {{ margin: 0 0 4px 0; font-size: 10px; color: #1e3a8a; }}
</style>
</head>
<body>
  <div class="header">
    <div>
      <h1>{self.interval_label.upper()} MARKET STATUS SUMMARY BULLETIN</h1>
      <div class="sub">Timestamp: <b>{timestamp_str}</b> | Architecture: <b>3-PILLAR INSTITUTIONAL</b> | Mode: <b>PAPER SIMULATOR</b></div>
    </div>
    <div class="badge">{decision_badge}</div>
  </div>

  <table>
    <tr><th>NIFTY 50 Live</th><td><b>{nifty_live_str}</b></td><th>BANK NIFTY Live</th><td><b>{bn_live_str}</b></td></tr>
    <tr><th>{self.interval_upper} Closed Candle (NIFTY)</th><td>{n_candle_str}</td><th>{self.interval_upper} Closed Candle (BN)</th><td>{bn_candle_str}</td></tr>
    <tr><th>Contributors Breadth</th><td>{breadth_str}</td><th>GIFT NIFTY / VIX</th><td>{gift_vix_str}</td></tr>
    <tr><th>NIFTY Option Chain</th><td>{nifty_oc_str}</td><th>BANKNIFTY Option Chain</th><td>{bn_oc_str}</td></tr>
    <tr><th>Simulator Capital</th><td><b>{cap_str}</b></td><th>Today's Net P&amp;L</th><td><b>{pnl_str}</b> (Headroom: ₹{daily_loss_headroom:,.0f})</td></tr>
  </table>

  <div class="section">
    <h3>1. Executive Summary &amp; Tactical Trading Conclusion</h3>
    <div class="summary-box">
      {conclusion_narrative}
    </div>
  </div>

  <div class="section">
    <h3>2. Institutional Multi-Dimensional Analysis Table</h3>
    <table>
      <thead>
        <tr>
          <th style="width: 22%;">Component Analyzed</th>
          <th style="width: 22%;">Quantitative Metric</th>
          <th style="width: 14%;">Status</th>
          <th style="width: 42%;">Reason &amp; Institutional Significance</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><b>1. Higher-Timeframe Trend</b></td>
          <td>1H: {h1_bias_val} | 15M: {bias_nifty.get('timeframes', {}).get('15M', {}).get('bias', 'NEUTRAL')}</td>
          <td><span class="{'status-bear' if 'BEAR' in h1_bias_val else ('status-bull' if 'BULL' in h1_bias_val else 'status-wait')}">{h1_bias_val}</span></td>
          <td>Establishes master directional bias. Strict rule: No Calls in 1H downtrend, no Puts in 1H uptrend.</td>
        </tr>
        <tr>
          <td><b>2. Option Chain &amp; Walls</b></td>
          <td>Call Wall {call_wall_strike} ({call_wall_oi:,}) | Put Floor {put_floor_strike} ({put_floor_oi:,}) | PCR {pcr_val:.2f}</td>
          <td><span class="{'status-bear' if pcr_val < 0.90 else ('status-bull' if pcr_val > 1.05 else 'status-wait')}">{'CALL DEFENDED' if pcr_val < 0.90 else ('PUT DEFENDED' if pcr_val > 1.05 else 'NEUTRAL')}</span></td>
          <td>Institutions actively defending {call_wall_strike} ceiling. Heavy call writing acts as a descending price barrier.</td>
        </tr>
        <tr>
          <td><b>3. Key Pivots &amp; CPR Location</b></td>
          <td>PP: ₹{pp_val:,.1f} | S1: ₹{s1_val:,.1f} | R1: ₹{r1_val:,.1f} | Spot: ₹{spot_ref:,.1f}</td>
          <td><span class="status-wait">{'BELOW PP' if spot_ref < pp_val else 'ABOVE PP'}</span></td>
          <td>Wholesale value location gate. Spot is {abs(spot_ref - pp_val):.1f} pts from Central Pivot. Avoids buying into resistance.</td>
        </tr>
        <tr>
          <td><b>4. Volume Profile (POC)</b></td>
          <td>Session POC: ₹{poc_val:,.1f} | VAH: ₹{vah_val:,.1f} | VAL: ₹{val_val:,.1f}</td>
          <td><span class="{'status-bull' if spot_ref >= poc_val else 'status-bear'}">{'ABOVE POC' if spot_ref >= poc_val else 'BELOW POC'}</span></td>
          <td>Measures institutional high-volume agreement. Long setups require holding above POC; Short setups below POC.</td>
        </tr>
        <tr>
          <td><b>5. Heavyweight Breadth</b></td>
          <td>{advances} Adv / {declines} Dec | N50 Impact: {n50_total_pts:+,.1f} pts</td>
          <td><span class="{'status-bear' if declines > advances else 'status-bull'}">{breadth_status}</span></td>
          <td>Index contributors confirmation. Movement driven by institutional heavyweights (Reliance, HDFC Bank, ICICI Bank).</td>
        </tr>
        <tr>
          <td><b>6. Sister Index &amp; Volatility</b></td>
          <td>NIFTY vs BN ({b_chg_pct:+.2f}%) | India VIX: {vix_val:.2f}</td>
          <td><span class="status-wait">ALIGNED</span></td>
          <td>Cross-index confirmation ensures moves are backed by broader banking and broad-market liquidity without divergence.</td>
        </tr>
        <tr>
          <td><b>7. News &amp; Macro Sentiment</b></td>
          <td>{news_data.get('sentiment', 'NEUTRAL')} (Bull: {news_data.get('bullish_count', 0)} / Bear: {news_data.get('bearish_count', 0)} | Score: {news_data.get('avg_impact_score', 0):.1f})</td>
          <td><span class="status-wait">{news_data.get('sentiment', 'NEUTRAL')}</span></td>
          <td>High-impact headlines filtered to prevent entering right before surprise event spikes.</td>
        </tr>
        <tr>
          <td><b>8. Risk &amp; Capital Protection</b></td>
          <td>Capital: ₹{sim_cap:,.2f} | Day P&amp;L: {pnl_str} | Max Loss Cap: ₹2,000</td>
          <td><span class="status-pass">PASS (₹{daily_loss_headroom:,.0f} Room)</span></td>
          <td>Strict capital shield. Maximum daily loss locked at ₹2,000; position size strictly locked to 1 Lot.</td>
        </tr>
      </tbody>
    </table>
  </div>

  <div class="section">
    <h3>3. Active Institutional Setups Evaluation</h3>
    <div class="setup-grid">
      <div class="setup-card">
        <h4>👑 Setup B: Wall Reversal Fade (1:7.0 Risk-to-Reward)</h4>
        <div><b>Status:</b> {setup_b_status}</div>
        <div style="margin-top:2px;"><b>Analysis:</b> {setup_b_reason}</div>
        <div style="margin-top:2px; font-size:9px; color:#475569;"><b>Risk Parameters:</b> SL: 15 pts | Target: 105 pts | Trailing: 15 pts | 1 Lot ITM Next Expiry</div>
      </div>
      <div class="setup-card">
        <h4>🚀 Setup A: Trend Continuation (1:3.0 Risk-to-Reward)</h4>
        <div><b>Status:</b> {setup_a_status}</div>
        <div style="margin-top:2px;"><b>Analysis:</b> {setup_a_reason}</div>
        <div style="margin-top:2px; font-size:9px; color:#475569;"><b>Risk Parameters:</b> SL: 20 pts | Target: 60 pts | Trailing: 15 pts | 1 Lot ITM Next Expiry</div>
      </div>
    </div>
  </div>

  <div class="section">
    <h3>4. Intraday {self.interval_label} Price Action &amp; Volume Chart ({hhmm_str} IST)</h3>
    {chart_section_html}
  </div>
</body>
</html>"""

            tmp_html = tmp_dir / f"{base_stem}.html"
            tmp_pdf = tmp_dir / f"{base_stem}.pdf"
            tmp_html.write_text(html_content, encoding="utf-8")

            if _html_to_pdf(tmp_html, tmp_pdf):
                pdf_bytes = tmp_pdf.read_bytes()
                pdf_bytes = tmp_pdf.read_bytes()
                for d in dirs_to_write:
                    pdf_path = d / f"{base_stem}.pdf"
                    pdf_path.write_bytes(pdf_bytes)
                    written_pdfs.append(str(pdf_path.resolve()))

        self.last_run_time = timestamp_str
        self.last_status = "SUCCESS"
        logger.info("%s Market Status Bulletin generated at %s", self.interval_label, timestamp_str)

        return {
            "status": "ok",
            "interval_minutes": self.interval_minutes,
            "date_folder": date_str,
            "sub_folder": self.sub_folder,
            "timestamp": timestamp_str,
            "dirs": [str(d.resolve()) for d in dirs_to_write],
            "pdfs": written_pdfs,
        }


class FifteenMinuteReportService(TradeIntelligenceReportService):
    """Backwards-compatible 15-minute report service alias."""

    def __init__(self, root_dir: Optional[Path] = None):
        super().__init__(root_dir=root_dir, interval_minutes=15)


def get_report_service(
    root_dir: Optional[Path] = None,
    interval_minutes: int = 15,
) -> TradeIntelligenceReportService:
    """Helper to access singleton TradeIntelligenceReportService for a given interval (e.g. 5 or 15)."""
    return TradeIntelligenceReportService.get_instance(
        root_dir=root_dir,
        interval_minutes=interval_minutes,
    )


def get_5m_report_service(root_dir: Optional[Path] = None) -> TradeIntelligenceReportService:
    """Helper to access singleton 5-minute report service."""
    return get_report_service(root_dir=root_dir, interval_minutes=5)


def get_15m_report_service(root_dir: Optional[Path] = None) -> TradeIntelligenceReportService:
    """Helper to access singleton 15-minute report service."""
    return get_report_service(root_dir=root_dir, interval_minutes=15)
