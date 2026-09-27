"""
Command-Line Interface (CLI) for NIFTY Autonomous Trader.
"""

import argparse
import asyncio
from pathlib import Path
import sys
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from nifty_trader.brain.contracts import BrainOutput, BrainResult, Direction, ReasoningState
from nifty_trader.core.runtime import NiftyTraderRuntime
from nifty_trader.instruction.models import InstructionPriority, InstructionStatus
from nifty_trader.market_data.models import MarketSessionStatus, Timeframe

console = Console()


async def cmd_status(runtime: NiftyTraderRuntime) -> None:
    """Prints runtime and provider health status."""
    status = await runtime.get_status()

    table = Table(title="[bold green]NIFTY Autonomous Trader — System Status[/bold green]")
    table.add_column("Property", style="cyan", no_wrap=True)
    table.add_column("Value", style="magenta")

    table.add_row("Application", status["app"])
    table.add_row("Version", status["version"])
    table.add_row("Mode", status["mode"])
    table.add_row("Current State", status["state"])

    # Providers
    for prov, ok in status["providers"].items():
        status_text = "[green][READY][/green]" if ok else "[yellow][IDLE/UNCONFIGURED][/yellow]"
        table.add_row(f"Provider ({prov})", status_text)

    # Hermes Integration Layer
    hermes_info = status.get("hermes", {})
    h_commit = str(hermes_info.get("commit", "UNKNOWN"))[:8]
    h_status = hermes_info.get("status", "UNKNOWN")
    h_color = "green" if h_status == "VERIFIED" else "yellow"
    table.add_row("Hermes Platform", f"[{h_color}]{h_commit} [{h_status}][/{h_color}]")

    # Feature Capabilities Overview
    table.add_row("Capability (Browser)", "[green]READY[/green]")
    table.add_row("Capability (Gemini Brain)", "[green]READY[/green]")
    md_info = status.get("market_data", {})
    md_prov = md_info.get("provider", "NONE")
    table.add_row("Capability (Market Data)", f"[green]READY (v1.0.0, {md_prov})[/green]")
    table.add_row("Capability (Paper Broker)", "[green]READY (v1.0.0, Sensibull Virtual)[/green]")
    table.add_row("Capability (Live Broker)", "[red]DISABLED[/red]")

    # Market Session and Cache
    sess = md_info.get("session", "UNKNOWN")
    sess_col = "green" if sess == "OPEN" else "yellow"
    table.add_row("Market Session", f"[{sess_col}]{sess}[/{sess_col}]")
    table.add_row("Cached Candles (1H / 15M)", f"{md_info.get('cache_1h_count', 0)} / {md_info.get('cache_15m_count', 0)}")
    inst_info = status.get("instructions", {})
    table.add_row("Active Operator Instructions", str(inst_info.get("active_count", 0)))

    # Browser
    b_status = status.get("browser", {}).get("status", "UNKNOWN")
    b_color = "green" if b_status == "READY" else "yellow"
    table.add_row("Browser Session", f"[{b_color}]{b_status}[/{b_color}]")

    # Risk policy constraints
    for k, v in status["risk_policies"].items():
        table.add_row(f"Policy ({k})", str(v))

    console.print(table)


async def cmd_test_brain(runtime: NiftyTraderRuntime) -> None:
    """Tests the cognitive ModelRouter with Gemini and validates output schema."""
    console.print("[bold yellow]Initiating ModelRouter cognitive test...[/bold yellow]")

    try:
        result = await runtime.test_brain()

        levels_str = ", ".join(str(lvl) for lvl in result.important_levels) if result.important_levels else "None"
        reasoning_str = "\n".join(f"  * {r}" for r in result.reasoning)
        uncertainties_str = "\n".join(f"  * {u}" for u in result.uncertainties) if result.uncertainties else "  None identified"

        panel_content = (
            f"[bold cyan]Market Context:[/bold cyan] {result.market_context}\n\n"
            f"[bold cyan]1H Bias:[/bold cyan] {result.one_hour_bias}\n"
            f"[bold cyan]15M State:[/bold cyan] {result.fifteen_minute_state}\n"
            f"[bold cyan]Setup Status:[/bold cyan] {result.setup_status}\n"
            f"[bold green]Recommended Action:[/bold green] [bold underline]{result.action.value}[/bold underline]\n"
            f"[bold cyan]Key Levels:[/bold cyan] {levels_str}\n\n"
            f"[bold cyan]Reasoning:[/bold cyan]\n{reasoning_str}\n\n"
            f"[bold cyan]Uncertainties:[/bold cyan]\n{uncertainties_str}\n\n"
            f"[bold cyan]Next Trigger:[/bold cyan] {result.next_observation}"
        )

        console.print(Panel(panel_content, title="[bold green]ModelRouter Cognitive Output (Validated Schema)[/bold green]", border_style="green"))
        console.print("[bold green][OK] Brain cognitive verification passed successfully![/bold green]")
    except Exception as e:
        console.print(f"[bold red][ERROR] Brain verification failed:[/bold red] {e}")
        sys.exit(1)


async def cmd_browser_test(runtime: NiftyTraderRuntime) -> None:
    """Runs a controlled browser startup, safe navigation, and screenshot test."""
    console.print("[bold yellow]Starting browser test suite (Chrome CDP)...[/bold yellow]")
    try:
        await runtime.browser.start()
        console.print("[bold green][OK] Browser started successfully.[/bold green]")

        test_url = "https://example.com"
        console.print(f"[cyan]Navigating to safe test page: {test_url}...[/cyan]")
        obs = await runtime.browser.navigate(test_url, capture_screen=True, screenshot_prefix="test_example")

        console.print(f"[bold green][OK] Page Loaded:[/bold green] '{obs.page_title}'")
        console.print(f"[cyan]URL:[/cyan] {obs.url}")
        console.print(f"[cyan]Source Type:[/cyan] {obs.source_type.value}")
        console.print(f"[cyan]Screenshot:[/cyan] {obs.screenshot_path}")
        console.print(f"[cyan]Visible Text ({len(obs.visible_text)} chars):[/cyan]\n  [dim]{obs.visible_text[:200]}...[/dim]")

        await runtime.browser.stop()
        console.print("[bold green][OK] Browser stopped cleanly. Browser test PASSED![/bold green]")
    except Exception as e:
        console.print(f"[bold red][ERROR] Browser test failed:[/bold red] {e}")
        try:
            await runtime.browser.stop()
        except Exception:
            pass
        sys.exit(1)


async def cmd_browser_open(runtime: NiftyTraderRuntime, url: str, run_multimodal: bool = False) -> None:
    """Opens a URL, extracts BrowserObservation, and optionally runs multimodal verification."""
    console.print(f"[bold yellow]Opening browser and navigating to:[/bold yellow] [cyan]{url}[/cyan]")
    try:
        await runtime.browser.start()
        obs = await runtime.browser.navigate(url, capture_screen=True, screenshot_prefix="inspect")

        table = Table(title="[bold green]Browser Observation[/bold green]")
        table.add_column("Field", style="cyan", no_wrap=True)
        table.add_column("Value", style="white")

        table.add_row("Page Title", obs.page_title)
        table.add_row("URL", obs.url)
        table.add_row("Source Type", obs.source_type.value)
        table.add_row("Screenshot Path", str(obs.screenshot_path))
        table.add_row("Extracted Text Length", f"{len(obs.visible_text)} characters")
        table.add_row("Key DOM Elements", f"{len(obs.important_elements)} elements")

        if obs.warnings:
            table.add_row("Warnings", ", ".join(obs.warnings))

        console.print(table)

        if run_multimodal and obs.screenshot_path:
            console.print("\n[bold yellow]Submitting screenshot to ModelRouter for neutral perception verification...[/bold yellow]")
            perception = await runtime.verify_multimodal_perception(obs)

            panel_text = (
                f"[bold cyan]Identified Symbol/Title:[/bold cyan] {perception.symbol_identified}\n\n"
                f"[bold cyan]Detected Timeframe:[/bold cyan] {perception.detected_timeframe}\n\n"
                f"[bold cyan]Visual Components:[/bold cyan]\n" + "\n".join(f"  * {c}" for c in perception.visible_components) + "\n\n"
                f"[bold cyan]Page Description:[/bold cyan]\n{perception.page_description}"
            )
            console.print(Panel(panel_text, title="[bold green]Gemini Multimodal Perception Output (Strictly Non-Trading)[/bold green]", border_style="green"))

        await runtime.browser.stop()
        console.print("\n[bold green][OK] Browser observation completed.[/bold green]")
    except Exception as e:
        console.print(f"[bold red][ERROR] Browser navigation failed:[/bold red] {e}")
        try:
            await runtime.browser.stop()
        except Exception:
            pass
        sys.exit(1)


def cmd_browser_login(target: str = "both", url: Optional[str] = None) -> None:
    """
    Launches a visible, regular Chrome browser window using Hermes's persistent
    profile sandbox (data/browser/chrome_profile).
    Allows the human user to sign into Google, Sensibull, and TradingView safely without
    exposing passwords or 2FA to automated scripts, LLMs, or chat logs.
    """
    profile_dir = Path("data/browser/chrome_profile").resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)

    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if not Path(chrome_path).exists():
        chrome_path = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"

    if not Path(chrome_path).exists():
        console.print("[bold red]Chrome binary not found at standard installation paths.[/bold red]")
        return

    if url:
        urls = [url]
    elif target == "sensibull":
        urls = ["https://web.sensibull.com"]
    elif target == "tradingview":
        urls = ["https://in.tradingview.com"]
    else:
        urls = ["https://web.sensibull.com", "https://in.tradingview.com"]

    urls_display = "\n".join(f"  * [cyan]{u}[/cyan]" for u in urls)

    console.print(Panel.fit(
        "[bold cyan]SECURE INTERACTIVE BROWSER LOGIN[/bold cyan]\n\n"
        f"[green]Opening Chrome with Hermes profile:[/green] [dim]{profile_dir}[/dim]\n"
        f"[green]Target Services:[/green]\n{urls_display}\n\n"
        "[bold yellow]Instructions:[/bold yellow]\n"
        "1. In the Chrome window that opens, sign into Google (e.g. sd37380@gmail.com) or your broker.\n"
        "2. For TradingView: click user icon -> 'Sign in' -> 'Continue with Google'.\n"
        "3. For Sensibull: click 'Login' -> 'Continue with Google' or broker login.\n"
        "4. Complete any 2FA verification prompts directly on your phone/screen.\n"
        "5. Once logged in, close the browser window or return here and press Enter.\n\n"
        "[bold green]The authenticated sessions will be saved permanently in Hermes's profile for automated observations and paper trading.[/bold green]",
        border_style="cyan"
    ))

    cmd = [
        chrome_path,
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
    ] + urls

    subprocess.Popen(cmd)

    input("\nPress Enter once you have finished logging in and are ready to save the sessions...")
    console.print("[bold green][OK] Browser sessions stored in Hermes profile sandbox.[/bold green]")


async def cmd_start(runtime: NiftyTraderRuntime) -> None:
    """Starts the autonomous trading runtime session."""
    console.print(Panel.fit(
        "[bold green]Starting NIFTY Autonomous Trader Runtime[/bold green]\n"
        "[dim]Independent build on Hermes extension layer[/dim]",
        border_style="green"
    ))

    await runtime.start()
    await cmd_status(runtime)

    console.print("\n[bold cyan]Performing startup cognitive verification...[/bold cyan]")
    await cmd_test_brain(runtime)

    console.print(f"\n[bold green][OK] Runtime operational in state: {runtime.state.value}[/bold green]")


async def cmd_upstream(runtime: NiftyTraderRuntime, action: str) -> None:
    """Handles upstream Hermes check, inspect, and test commands."""
    if action == "check":
        result = runtime.hermes_updater.check_upstream()
        compat = await runtime.hermes_checker.run_all_checks()
        compat_str = "PASS" if compat.passed else "FAIL"

        text = (
            f"Current Hermes:\n{result.current_commit[:8]}\n\n"
            f"Latest Hermes:\n{result.latest_commit[:8]}\n\n"
            f"New commits:\n{result.new_commits_count}\n\n"
            f"Compatibility:\n{compat_str}\n\n"
            f"Update:\n{result.status}\n\n"
            f"Action:\n{result.action_required}"
        )
        console.print(Panel(text, title="[bold cyan]Hermes Upstream Check[/bold cyan]", border_style="cyan"))

    elif action == "inspect":
        result = runtime.hermes_updater.check_upstream()
        report = runtime.hermes_updater.generate_report(result)
        console.print(Panel(report, title="[bold cyan]Hermes Upstream Inspection Report[/bold cyan]", border_style="cyan"))

    elif action == "test":
        console.print("[bold yellow]Running Hermes compatibility test suite...[/bold yellow]")
        compat = await runtime.hermes_checker.run_all_checks()

        table = Table(title="[bold green]Hermes Compatibility Test Suite[/bold green]")
        table.add_column("Check Name", style="cyan")
        table.add_column("Status", style="magenta")
        table.add_column("Details", style="white")

        for c in compat.checks:
            status_text = "[green]PASS[/green]" if c.passed else "[red]FAIL[/red]"
            table.add_row(c.name, status_text, c.details)

        console.print(table)
        if compat.breaking_changes:
            console.print("\n[bold red]BREAKING CHANGES DETECTED:[/bold red]")
            for b in compat.breaking_changes:
                console.print(f"  * [red]{b}[/red]")
        else:
            console.print(f"\n[bold green][OK] All upstream compatibility checks passed ({compat.hermes_commit[:8]}).[/bold green]")


async def cmd_features(runtime: NiftyTraderRuntime) -> None:
    """Displays declared features, versions, dependencies, and rollout states."""
    summary = runtime.features.get_status_summary()

    table = Table(title="[bold green]NIFTY Autonomous Trader — Feature Extension Registry[/bold green]")
    table.add_column("Feature", style="cyan")
    table.add_column("Version", style="magenta")
    table.add_column("Status", style="bold")
    table.add_column("Dependencies", style="white")
    table.add_column("Description", style="dim")

    status_colors = {
        "ENABLED": "green",
        "INSTALLED": "cyan",
        "EXPERIMENTAL": "yellow",
        "PLANNED": "blue",
        "DISABLED": "red",
        "DEPRECATED": "dim red",
    }

    for name, info in summary["features"].items():
        st = info["status"]
        col = status_colors.get(st, "white")
        deps_str = ", ".join(info["dependencies"]) if info["dependencies"] else "None"
        table.add_row(name, info["version"], f"[{col}]{st}[/{col}]", deps_str, info["description"])

    console.print(table)


async def cmd_market_status(runtime: NiftyTraderRuntime) -> None:
    """Displays detailed session state, candle cache counts, latest candles, and clock boundaries."""
    session_status = runtime.market_service.session_manager.get_current_session_status()
    h1_candles = runtime.market_service.cache.get_candles(symbol="NIFTY", timeframe=Timeframe.H1, limit=1)
    m15_candles = runtime.market_service.cache.get_candles(symbol="NIFTY", timeframe=Timeframe.M15, limit=1)
    cache_stats = runtime.market_service.cache.get_stats("NIFTY")
    active_instructions = runtime.instruction_manager.get_active_instructions()

    table = Table(title="[bold green]NIFTY Autonomous Trader — Market Perception Status[/bold green]")
    table.add_column("Attribute", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    table.add_row("Symbol", "NIFTY 50 (^NSEI)")
    sess_color = "green" if session_status == MarketSessionStatus.OPEN else "yellow"
    table.add_row("Session State", f"[{sess_color}]{session_status.value}[/{sess_color}]")
    table.add_row("Exchange Hours", "09:15 - 15:30 IST (Mon-Fri)")
    table.add_row("Cached 1H Candles", str(cache_stats.get(Timeframe.H1, 0)))
    table.add_row("Cached 15M Candles", str(cache_stats.get(Timeframe.M15, 0)))

    if h1_candles:
        c = h1_candles[-1]
        table.add_row("Latest 1H Candle", f"{c.timestamp_ist.strftime('%Y-%m-%d %H:%M IST')} | O:{c.open:.2f} H:{c.high:.2f} L:{c.low:.2f} C:{c.close:.2f}")
    else:
        table.add_row("Latest 1H Candle", "[dim]No cached candles. Run 'market-sync'.[/dim]")

    if m15_candles:
        c = m15_candles[-1]
        table.add_row("Latest 15M Candle", f"{c.timestamp_ist.strftime('%Y-%m-%d %H:%M IST')} | O:{c.open:.2f} H:{c.high:.2f} L:{c.low:.2f} C:{c.close:.2f}")
    else:
        table.add_row("Latest 15M Candle", "[dim]No cached candles. Run 'market-sync'.[/dim]")

    table.add_row("Active Instructions", str(len(active_instructions)))
    console.print(table)


async def cmd_market_sync(runtime: NiftyTraderRuntime) -> None:
    """Synchronizes latest 1H and 15M candles from market data provider to local SQLite cache."""
    console.print(f"[bold yellow]Synchronizing market data from {runtime.market_service.provider.name}...[/bold yellow]")
    try:
        results = await runtime.sync_market_data()
        table = Table(title="[bold green]Market Data Synchronization Results[/bold green]")
        table.add_column("Timeframe", style="cyan")
        table.add_column("Candles Processed/Stored", style="magenta")

        for tf, count in results.items():
            table.add_row(tf.upper(), str(count))

        console.print(table)
        console.print("[bold green][OK] Market data synchronization complete.[/bold green]")
    except Exception as e:
        console.print(f"[bold red][ERROR] Sync failed:[/bold red] {e}")
        sys.exit(1)


async def cmd_sensibull_test(runtime: NiftyTraderRuntime) -> None:
    """Tests Sensibull option chain navigation and perception extraction."""
    console.print(Panel.fit(
        "[bold green]Sensibull Observation Test[/bold green]\n"
        "[dim]Option Chain, PCR & Derivatives Sentiment Inspection[/dim]",
        border_style="green",
    ))
    console.print("[cyan]Launching browser and interrogating Sensibull...[/cyan]")
    try:
        await runtime.browser.start()
        res = await runtime.test_sensibull_observation()

        table = Table(title="[bold green]Sensibull Observation Result[/bold green]")
        table.add_column("Field", style="cyan", no_wrap=True)
        table.add_column("Value", style="white")

        data = res.data
        status = res.status
        st_color = "green" if status == "OBSERVED" else ("yellow" if status == "AUTHENTICATION_REQUIRED" else "red")
        table.add_row("Status", f"[{st_color}]{status}[/{st_color}]")
        table.add_row("Spot Reference", str(data.get("spot_reference") or "N/A"))
        table.add_row("PCR (Put-Call Ratio)", str(data.get("pcr") if data.get("pcr") is not None else "N/A"))
        table.add_row("Max Pain Strike", str(data.get("max_pain_information") or "N/A"))
        table.add_row("ATM IV", str(data.get("iv_information", {}).get("atm_iv") or "N/A"))
        strikes = data.get("strike_information", [])
        table.add_row("Visible Strikes", f"{len(strikes)} strike(s) identified")
        table.add_row("Screenshot", str(data.get("screenshot_reference") or "None"))

        if res.warnings:
            table.add_row("Warnings", "\n".join(f"[yellow]{w}[/yellow]" for w in res.warnings))
        if res.errors:
            table.add_row("Errors", "\n".join(f"[red]{e}[/red]" for e in res.errors))

        console.print(table)
        await runtime.browser.stop()
        console.print("[bold green][OK] Sensibull observation test completed.[/bold green]")
    except Exception as e:
        console.print(f"[bold red][ERROR] Sensibull test failed:[/bold red] {e}")
        try:
            await runtime.browser.stop()
        except Exception:
            pass
        sys.exit(1)


async def cmd_market_observe(
    runtime: NiftyTraderRuntime,
    multimodal: bool = False,
    cross_check: bool = True,
    sources: Optional[str] = None,
) -> None:
    """Performs full market observation across multi-source perception channels (strictly non-trading)."""
    source_list = [s.strip().lower() for s in sources.split(",")] if sources else None
    sources_desc = f"Sources: {', '.join(source_list)}" if source_list else "Default observation sources"
    console.print(f"[bold yellow]Collecting market observation (1H + 15M, {sources_desc})...[/bold yellow]")
    try:
        # Sync latest data first to ensure observation has fresh data
        await runtime.sync_market_data()

        screenshot_bytes: Optional[bytes] = None
        needs_browser = (
            multimodal
            or (source_list and ("sensibull" in source_list or "tradingview" in source_list))
        )

        if needs_browser:
            await runtime.browser.start()

        try:
            if multimodal:
                console.print("[cyan]Capturing visual chart state from TradingView...[/cyan]")
                obs_browser = await runtime.browser.inspect_tradingview_nifty()
                if obs_browser.screenshot_path and Path(obs_browser.screenshot_path).exists():
                    screenshot_bytes = Path(obs_browser.screenshot_path).read_bytes()

            obs = await runtime.get_market_observation(
                cross_check=cross_check,
                sources=source_list,
            )
        finally:
            if needs_browser:
                await runtime.browser.stop()

        table = Table(title="[bold green]NIFTY Multi-Source Market Observation[/bold green]")
        table.add_column("Component", style="cyan", no_wrap=True)
        table.add_column("Details", style="white")

        table.add_row("Timestamp (IST)", obs.timestamp_ist.strftime("%Y-%m-%d %H:%M:%S IST"))
        table.add_row("Session Status", obs.market_status.value)
        table.add_row("Data Quality", obs.data_quality.value)
        table.add_row("1H Context Summary", obs.h1_summary)
        table.add_row("15M Tactical Summary", obs.m15_summary)
        table.add_row("Sensibull Derivatives", f"{obs.sensibull_summary} ({obs.pcr_summary})")

        match_str = "[green]MATCH[/green]" if obs.cross_check_match else "[yellow]MISMATCH/SKIPPED[/yellow]"
        table.add_row("TradingView Cross-Check", f"{match_str} (discrepancy: {obs.cross_check_discrepancy_pct:.2f}%)")

        if obs.multi_source_cross_check:
            mc = obs.multi_source_cross_check
            s_diff_str = f"{mc.sensibull_vs_numerical_diff} pts ({mc.sensibull_vs_numerical_pct}%)" if mc.sensibull_vs_numerical_diff is not None else "N/A"
            s_color = "green" if mc.sensibull_vs_numerical_status == "MATCH" else ("yellow" if mc.sensibull_vs_numerical_status == "MINOR_DIFFERENCE" else "red")
            table.add_row("Sensibull vs Numerical", f"[{s_color}]{mc.sensibull_vs_numerical_status}[/{s_color}] ({s_diff_str})")

        active_instructions = runtime.instruction_manager.get_active_instructions()
        active_instr_str = "\n".join(f"[{i.priority.value}] {i.text}" for i in active_instructions) if active_instructions else "None"
        table.add_row("Active Instructions", active_instr_str)

        console.print(table)

        # Submit to Gemini for objective perception analysis
        console.print("\n[bold yellow]Submitting observation to Gemini for objective perception analysis...[/bold yellow]")
        perception = await runtime.analyze_market_perception(obs, image_bytes=screenshot_bytes)

        levels_str = ", ".join(f"{lvl:.2f}" for lvl in perception.notable_levels) if perception.notable_levels else "None"
        changes_str = "\n".join(f"  * {p}" for p in perception.recent_changes) if perception.recent_changes else "  * None noted"
        uncertain_str = "\n".join(f"  * {u}" for u in perception.uncertainties) if perception.uncertainties else "  * None noted"

        panel_text = (
            f"[bold cyan]Regime Classification:[/bold cyan] {perception.market_regime_description}\n\n"
            f"[bold cyan]1H Structural State:[/bold cyan] {perception.one_hour_structure_description}\n\n"
            f"[bold cyan]15M Tactical State:[/bold cyan] {perception.fifteen_minute_structure_description}\n\n"
            f"[bold cyan]Key Structural Levels:[/bold cyan] {levels_str}\n\n"
            f"[bold cyan]Data Integrity Status:[/bold cyan] {perception.data_quality_assessment}\n\n"
            f"[bold cyan]Recent Changes:[/bold cyan]\n{changes_str}\n\n"
            f"[bold cyan]Uncertainties:[/bold cyan]\n{uncertain_str}\n\n"
            f"[bold cyan]Observation Summary:[/bold cyan]\n{perception.observation_summary}"
        )
        console.print(Panel(panel_text, title="[bold green]Objective Market Perception (Zero Trading Recommendations)[/bold green]", border_style="green"))
        console.print("[bold green][OK] Observation and perception analysis complete.[/bold green]")
    except Exception as e:
        console.print(f"[bold red][ERROR] Observation failed:[/bold red] {e}")
        sys.exit(1)


async def cmd_instruction(
    runtime: NiftyTraderRuntime,
    text: str,
    priority: str = "NORMAL",
    expires_in_hours: Optional[float] = 4.0,
) -> None:
    """Submits a human operator steering instruction with safety boundary validation."""
    pri_enum = InstructionPriority(priority.upper()) if priority.upper() in [p.value for p in InstructionPriority] else InstructionPriority.NORMAL
    console.print(f"[bold yellow]Submitting operator instruction:[/bold yellow] \"{text}\" (Priority: {pri_enum.value})")

    inst = runtime.submit_instruction(
        text=text,
        priority=pri_enum,
        expires_in_hours=expires_in_hours,
        created_by="human_operator",
    )

    table = Table(title="[bold green]Operator Instruction Status[/bold green]")
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    table.add_row("Instruction ID", inst.instruction_id)
    table.add_row("Text", inst.text)
    table.add_row("Priority", inst.priority.value)

    if inst.status == InstructionStatus.REJECTED:
        table.add_row("Status", "[bold red]REJECTED (SAFETY VIOLATION)[/bold red]")
        table.add_row("Reason", f"[red]{inst.agent_response}[/red]")
    else:
        table.add_row("Status", "[bold green]ACCEPTED[/bold green]")
        exp_str = inst.expires_at.strftime("%Y-%m-%d %H:%M UTC") if inst.expires_at else "No expiration"
        table.add_row("Expires At", exp_str)

    console.print(table)


async def cmd_instruction_list(runtime: NiftyTraderRuntime, status_filter: Optional[str] = None) -> None:
    """Lists operator instructions from the persistent SQLite store."""
    st_enum = InstructionStatus(status_filter.upper()) if status_filter and status_filter.upper() in [s.value for s in InstructionStatus] else None
    instructions = runtime.list_instructions(status=st_enum)

    table = Table(title="[bold green]Operator Instruction History[/bold green]")
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Priority", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Text", style="white")
    table.add_column("Expires", style="yellow")
    table.add_column("Response / Notes", style="dim")

    status_colors = {
        InstructionStatus.PENDING: "yellow",
        InstructionStatus.ACTIVE: "green",
        InstructionStatus.COMPLETED: "blue",
        InstructionStatus.REJECTED: "red",
        InstructionStatus.EXPIRED: "dim white",
    }

    for inst in instructions:
        col = status_colors.get(inst.status, "white")
        exp_str = inst.expires_at.strftime("%H:%M UTC") if inst.expires_at else "None"
        resp_str = inst.agent_response or ""
        table.add_row(inst.instruction_id[:8], inst.priority.value, f"[{col}]{inst.status.value}[/{col}]", inst.text[:50], exp_str, resp_str[:40])

    console.print(table)


async def cmd_brain_analyze(
    runtime: NiftyTraderRuntime,
    cross_check: bool = True,
    include_sensibull: bool = False,
    sources: Optional[str] = None,
    multimodal: bool = False,
) -> None:
    """Executes Package 4 Trading Brain cognitive reasoning on canonical market observations."""
    console.print("[bold yellow]Initiating Trading Brain cognitive reasoning cycle...[/bold yellow]")

    source_list = [s.strip() for s in sources.split(",")] if sources else None
    needs_browser = (cross_check or include_sensibull or (source_list and any(s in ["tradingview", "sensibull"] for s in source_list)))

    screenshot_bytes = None
    try:
        if needs_browser:
            console.print("[dim]Starting browser subsystem for observation capture...[/dim]")
            await runtime.browser.start()
            if multimodal:
                screenshot_bytes = await runtime.browser.provider.capture_screenshot()

        # Step 1: Canonical Unified Observation
        console.print("[dim]Compiling canonical UnifiedMarketObservation...[/dim]")
        unified_obs = await runtime.get_unified_market_observation(
            cross_check=cross_check,
            include_sensibull=include_sensibull,
            sources=source_list,
        )
    finally:
        if needs_browser:
            await runtime.browser.stop()

    # Step 2: Brain Cognitive Reasoning
    console.print("[bold yellow]Engaging TradingBrainEngine with ModelRouter...[/bold yellow]")
    brain_result = await runtime.reason_market(unified_obs=unified_obs, image_bytes=screenshot_bytes)

    if not brain_result.success:
        failure = brain_result.failure
        console.print(f"[bold red]Brain Reasoning Failed [{failure.code}]:[/bold red] {failure.message}")
        return

    brain_output = brain_result.output

    # State colors
    state_colors = {
        ReasoningState.NO_TRADE: "red",
        ReasoningState.WAIT: "yellow",
        ReasoningState.WATCH: "cyan",
        ReasoningState.DEVELOPING: "magenta",
        ReasoningState.CANDIDATE: "green",
    }
    scol = state_colors.get(brain_output.reasoning_state, "white")

    # Display Top Table
    table = Table(title="[bold green]Package 4 Trading Brain — Synthesis & Decision[/bold green]")
    table.add_column("Dimension", style="cyan", no_wrap=True)
    table.add_column("Assessment", style="white")

    table.add_row("Brain Request ID", brain_output.brain_request_id)
    table.add_row("Observation ID", brain_output.observation_id)
    table.add_row("Generated (UTC)", brain_output.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC'))
    table.add_row("Market Regime", f"[bold]{brain_output.market_context.regime.value}[/bold] (Confidence: {brain_output.market_context.regime_confidence.value:.2f})")
    table.add_row("Reasoning State", f"[bold {scol}]{brain_output.reasoning_state.value}[/bold {scol}]")
    table.add_row("Market Summary", brain_output.market_context.summary)
    table.add_row("Key Levels", ", ".join(brain_output.market_context.key_levels) or "None")
    table.add_row("Confidence", f"{brain_output.confidence.value:.2f} (Basis: {', '.join(brain_output.confidence.basis)})")
    console.print(table)

    # Timeframe Assessments Table
    if brain_output.timeframe_assessments:
        tf_table = Table(title="[bold cyan]Timeframe Assessments[/bold cyan]")
        tf_table.add_column("TF", style="bold")
        tf_table.add_column("Direction", style="yellow")
        tf_table.add_column("Structures", style="cyan")
        tf_table.add_column("Summary", style="white")
        for tf in brain_output.timeframe_assessments:
            structs_str = ", ".join(s.value for s in tf.structures) if tf.structures else "None"
            tf_table.add_row(tf.timeframe, tf.directional_context.value, structs_str, tf.summary)
        console.print(tf_table)

    # Scenarios Table
    if brain_output.scenarios:
        scen_table = Table(title="[bold cyan]Evaluated Market Scenarios[/bold cyan]")
        scen_table.add_column("Scenario ID", style="dim", no_wrap=True)
        scen_table.add_column("Direction", style="yellow")
        scen_table.add_column("Description", style="white")
        scen_table.add_column("Confidence", style="magenta")
        scen_table.add_column("Confirm / Invalidate", style="yellow")
        for sc in brain_output.scenarios:
            conf_str = "; ".join(sc.confirmation_conditions) or "None"
            inv_str = "; ".join(sc.invalidation_conditions) or "None"
            scen_table.add_row(
                sc.scenario_id,
                sc.direction.value,
                sc.description,
                f"{sc.confidence.value:.2f}",
                f"Confirm: {conf_str}\nInvalid: {inv_str}",
            )
        console.print(scen_table)

    # Candidate Thesis Panel (if any)
    if brain_output.candidate:
        cand = brain_output.candidate
        dcol = "green" if cand.direction == Direction.LONG else ("red" if cand.direction == Direction.SHORT else "yellow")
        cand_text = (
            f"[bold cyan]Directional Bias:[/bold cyan] [{dcol}]{cand.direction.value}[/{dcol}]\n"
            f"[bold cyan]Thesis:[/bold cyan] {cand.thesis}\n"
            f"[bold cyan]Market Context:[/bold cyan] {cand.market_context}\n"
            f"[bold cyan]Setup Conditions:[/bold cyan] {', '.join(c.description for c in cand.setup_conditions) or 'None'}\n"
            f"[bold cyan]Confirmation Conditions:[/bold cyan] {', '.join(cand.confirmation_conditions) or 'None'}\n"
            f"[bold cyan]Invalidation Conditions:[/bold cyan] {', '.join(cand.invalidation_conditions) or 'None'}\n"
            f"[bold yellow]Downstream Info Required:[/bold yellow] {', '.join(cand.required_downstream_information)}\n"
            f"[bold red]STRICT INVARIANT:[/bold red] Conceptual thesis only. Non-executable. Zero broker parameters."
        )
        console.print(Panel(cand_text, title="[bold green]Draft Trade Candidate Thesis (Non-Executable)[/bold green]", border_style="green"))

    # Observation Requests (if any)
    if brain_output.observation_requests:
        obs_req_table = Table(title="[bold yellow]Observation Requests for Next Cycle[/bold yellow]")
        obs_req_table.add_column("Req ID", style="dim")
        obs_req_table.add_column("Source", style="cyan")
        obs_req_table.add_column("Reason", style="white")
        obs_req_table.add_column("Requested Information", style="yellow")
        for r in brain_output.observation_requests:
            req_info_str = ", ".join(r.requested_information)
            obs_req_table.add_row(r.request_id, r.source, r.reason, req_info_str)
        console.print(obs_req_table)

    # Auditable Executive Summary Panel
    summary_body = (
        f"[bold cyan]Context:[/bold cyan] {brain_output.reasoning_summary.context}\n\n"
        f"[bold cyan]Interpretation:[/bold cyan] {brain_output.reasoning_summary.interpretation}\n\n"
        f"[bold cyan]What Would Change Assessment:[/bold cyan]\n"
        + "\n".join(f"  * {w}" for w in brain_output.reasoning_summary.what_would_change_assessment)
    )
    console.print(Panel(summary_body, title="[bold green]Auditable Executive Reasoning Summary[/bold green]", border_style="green"))
    console.print("[bold green][OK] Brain reasoning cycle complete. Persisted to SQLite history.[/bold green]")


async def cmd_brain_history(
    runtime: NiftyTraderRuntime,
    limit: int = 10,
    state: Optional[str] = None,
) -> None:
    """Lists persisted reasoning runs from SQLite storage."""
    state_enum = ReasoningState(state.upper()) if state and state.upper() in [s.value for s in ReasoningState] else None
    runs = runtime.brain.get_history(limit=limit, state=state_enum)

    table = Table(title="[bold green]Brain Reasoning History (SQLite Audit Trail)[/bold green]")
    table.add_column("Request ID", style="dim", no_wrap=True)
    table.add_column("Timestamp (UTC)", style="white")
    table.add_column("State", style="bold")
    table.add_column("Regime", style="cyan")
    table.add_column("Confidence", style="magenta")
    table.add_column("Direction", style="yellow")
    table.add_column("Summary", style="dim white")

    state_colors = {
        ReasoningState.NO_TRADE: "red",
        ReasoningState.WAIT: "yellow",
        ReasoningState.WATCH: "cyan",
        ReasoningState.DEVELOPING: "magenta",
        ReasoningState.CANDIDATE: "green",
    }

    for r in runs:
        scol = state_colors.get(r.reasoning_state, "white")
        cand_dir = r.candidate.direction.value if r.candidate else "NONE"
        table.add_row(
            r.brain_request_id[:12],
            r.generated_at.strftime("%Y-%m-%d %H:%M"),
            f"[{scol}]{r.reasoning_state.value}[/{scol}]",
            r.market_context.regime.value,
            f"{r.confidence.value:.2f}",
            cand_dir,
            r.reasoning_summary.interpretation[:60] + "...",
        )

    console.print(table)


async def cmd_autonomous_status(runtime: NiftyTraderRuntime) -> None:
    """Displays operational status of the Package 5 Autonomous Engine."""
    status = runtime.autonomous.get_status()

    table = Table(title="[bold green]Package 5 Autonomous Observation Engine — Operational Status[/bold green]")
    table.add_column("Parameter", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    st = status.get("status", "UNKNOWN")
    st_col = "green" if st == "OBSERVING" else ("yellow" if st in ["WAITING", "WATCHING"] else ("magenta" if st == "ANALYZING" else "white"))
    table.add_row("Engine State", f"[bold {st_col}]{st}[/bold {st_col}]")
    table.add_row("Running Active", f"{status.get('is_running')}")
    table.add_row("Market Session", f"{status.get('market_session')}")
    table.add_row("Session ID", f"{status.get('session_id')}")
    table.add_row("Current Brain State", f"{status.get('current_brain_state')}")
    table.add_row("Wait Reason", f"{status.get('wait_reason')}")
    table.add_row("Next Scheduled Wake", f"{status.get('next_wake')}")
    table.add_row("Cycles Completed", f"{status.get('cycles_completed')} / {status.get('max_cycles')}")
    table.add_row("Model Calls Used", f"{status.get('model_calls')} / {status.get('max_model_calls')}")
    table.add_row("Active Observation Plans", f"{status.get('active_observation_plans')}")
    table.add_row("Consecutive Failures", f"{status.get('consecutive_failures')}")

    console.print(table)


async def cmd_autonomous_start(runtime: NiftyTraderRuntime, once: bool = False, symbol: str = "NIFTY") -> None:
    """Starts autonomous observation and waiting engine."""
    console.print(f"[bold yellow]Starting Autonomous Observation Engine for {symbol}...[/bold yellow]")
    if once:
        console.print("[dim]Executing single bounded observation & reasoning cycle...[/dim]")
        await runtime.autonomous.start(symbol=symbol, run_once=True)
        await cmd_autonomous_status(runtime)
    else:
        console.print("[dim]Starting continuous autonomous observation loop (Press Ctrl+C to stop)...[/dim]")
        await runtime.autonomous.start(symbol=symbol, run_once=False)
        try:
            while runtime.autonomous.is_running:
                await asyncio.sleep(1.0)
        except (KeyboardInterrupt, asyncio.CancelledError):
            console.print("\n[bold yellow]Stopping autonomous engine safely...[/bold yellow]")
            await runtime.autonomous.stop("KeyboardInterrupt / User Stop")
            console.print("[bold green][OK] Autonomous engine stopped.[/bold green]")


async def cmd_autonomous_stop(runtime: NiftyTraderRuntime) -> None:
    """Stops the autonomous observation engine."""
    console.print("[bold yellow]Commanding Autonomous Engine to STOP...[/bold yellow]")
    await runtime.autonomous.stop("Operator CLI STOP")
    console.print("[bold green][OK] Autonomous engine stopped successfully.[/bold green]")


async def cmd_autonomous_pause(runtime: NiftyTraderRuntime) -> None:
    """Pauses the autonomous observation engine."""
    console.print("[bold yellow]Commanding Autonomous Engine to PAUSE...[/bold yellow]")
    await runtime.autonomous.pause("Operator CLI PAUSE")
    console.print("[bold green][OK] Autonomous engine paused.[/bold green]")


async def cmd_autonomous_resume(runtime: NiftyTraderRuntime) -> None:
    """Resumes the autonomous observation engine."""
    console.print("[bold yellow]Commanding Autonomous Engine to RESUME...[/bold yellow]")
    await runtime.autonomous.resume("Operator CLI RESUME")
    console.print("[bold green][OK] Autonomous engine resumed.[/bold green]")


async def cmd_autonomous_observe_now(runtime: NiftyTraderRuntime) -> None:
    """Triggers an immediate observation cycle."""
    console.print("[bold yellow]Commanding Autonomous Engine to OBSERVE NOW...[/bold yellow]")
    await runtime.autonomous.observe_now("Operator CLI OBSERVE_NOW")
    console.print("[bold green][OK] Immediate observation cycle requested.[/bold green]")


async def cmd_autonomous_cycles(runtime: NiftyTraderRuntime, limit: int = 10) -> None:
    """Lists persisted autonomous reasoning cycles from SQLite audit trail."""
    cycles = runtime.autonomous.storage.list_cycles(limit=limit)

    table = Table(title="[bold green]Autonomous Cycles History (SQLite Audit Trail)[/bold green]")
    table.add_column("Cycle ID", style="dim", no_wrap=True)
    table.add_column("Index", style="white")
    table.add_column("Started (UTC)", style="white")
    table.add_column("Prev State", style="yellow")
    table.add_column("Result State", style="bold green")
    table.add_column("Wait Reason", style="cyan")
    table.add_column("Wake Reason", style="dim white")
    table.add_column("Observations", style="white")
    table.add_column("Model Calls", style="white")

    for c in cycles:
        wr_str = c.wait_reason.value if c.wait_reason else "NONE"
        wake_str = (c.wake_reason[:30] + "...") if c.wake_reason else "SCHEDULED"
        table.add_row(
            c.cycle_id[:10],
            str(c.cycle_index),
            c.started_at.strftime("%H:%M:%S"),
            c.previous_state.value,
            c.resulting_state.value,
            wr_str,
            wake_str,
            str(c.observation_count),
            str(c.model_call_count),
        )

    console.print(table)


async def cmd_collaborate(
    runtime: NiftyTraderRuntime,
    symbol: str = "NIFTY",
    max_turns: int = 3,
) -> None:
    """Executes Stage 6 Hermes-Brain Collaborative Trading Orchestration."""
    console.print(Panel(
        f"[bold cyan]STAGE 6: HERMES-BRAIN COLLABORATIVE TRADING ORCHESTRATION[/bold cyan]\n"
        f"Operator: [green]Hermes Autonomous Agent[/green] | Reasoning Intelligence: [magenta]AI Brain (Gemini)[/magenta]\n"
        f"Instrument: [bold yellow]{symbol}[/bold yellow] | Max Interactive Turns: [bold]{max_turns}[/bold]\n"
        f"[dim]STRICT INVARIANT: No hard-coded strategy engine. Yields TradeCandidate only (Zero broker execution).[/dim]",
        title="[bold green]Hermes-Brain Partnership[/bold green]",
        border_style="cyan",
    ))

    with console.status("[bold green]Executing collaborative reasoning turn(s)...[/bold green]"):
        cycle = await runtime.run_collaboration(symbol=symbol, max_turns=max_turns)

    final_state_str = cycle.final_reasoning_state.value if cycle.final_reasoning_state else "FAILED/INCOMPLETE"
    state_color = "green" if final_state_str == "CANDIDATE" else ("yellow" if final_state_str == "WAIT" else "cyan")

    table = Table(title=f"Collaboration Turns Audit [Cycle ID: {cycle.cycle_id}]")
    table.add_column("Turn #", style="bold white", justify="center")
    table.add_column("Action Taken", style="cyan")
    table.add_column("State Result", style=state_color)
    table.add_column("Observation Requests", style="magenta")
    table.add_column("Tools Invoked", style="yellow")
    table.add_column("Duration", style="dim white", justify="right")

    for t in cycle.turns:
        st_val = t.reasoning_state.value if t.reasoning_state else "FAILED"
        reqs = ", ".join(t.requested_items) if t.requested_items else "None"
        tools = ", ".join(t.tools_invoked) if t.tools_invoked else "None"
        table.add_row(
            str(t.turn_index),
            t.action_taken,
            st_val,
            reqs,
            tools,
            f"{t.duration_ms:.1f}ms",
        )

    console.print(table)

    if cycle.candidate:
        console.print(Panel(
            f"[bold green]TRADE CANDIDATE PRODUCED BY BRAIN REASONING[/bold green]\n\n"
            f"[bold]Thesis:[/bold] {cycle.candidate.thesis}\n"
            f"[bold]Direction:[/bold] [{state_color}]{cycle.candidate.direction.value}[/{state_color}]\n"
            f"[bold]Market Context:[/bold] {cycle.candidate.market_context}\n"
            f"[bold]Setup Conditions:[/bold]\n" + "\n".join(f"  * {sc.description}" for sc in cycle.candidate.setup_conditions) + "\n"
            f"[bold]Required Downstream Info:[/bold] {', '.join(cycle.candidate.required_downstream_information)}\n\n"
            f"[bold red]SAFETY BOUNDARY: CANDIDATE ONLY. ZERO BROKER ORDERS EXECUTED.[/bold red]",
            title="[bold yellow]Trade Candidate Output[/bold yellow]",
            border_style="green",
        ))
    elif cycle.wait_decision:
        w = cycle.wait_decision
        console.print(Panel(
            f"[bold yellow]COLLABORATIVE WAIT ACTIVE[/bold yellow]\n\n"
            f"[bold]Wait Reason:[/bold] {w.get('reason')}\n"
            f"[bold]Earliest Wake (UTC):[/bold] {w.get('earliest_wake_at')}\n"
            f"[bold]Latest Wake (UTC):[/bold] {w.get('latest_wake_at')}\n"
            f"[bold]Explanation:[/bold] {w.get('explanation')}\n"
            f"[bold]Scheduled Wake Conditions:[/bold] {len(w.get('wake_conditions', []))} condition(s) registered",
            title="[bold cyan]Autonomous Wait State[/bold cyan]",
            border_style="yellow",
        ))
    else:
        console.print(f"[bold {state_color}]Collaboration Cycle Concluded. Final State: {final_state_str}[/bold {state_color}]")


async def cmd_collaborate_status(runtime: NiftyTraderRuntime, limit: int = 10) -> None:
    """Lists recent collaborative trading cycles from audit store."""
    cycles = runtime.collaborator.audit_store.load_recent_cycles(limit=limit)
    if not cycles:
        console.print("[yellow]No collaboration cycles found in audit log.[/yellow]")
        return

    table = Table(title="[bold green]Hermes-Brain Collaboration History (Audit Trail)[/bold green]")
    table.add_column("Cycle ID", style="dim", no_wrap=True)
    table.add_column("Session", style="white")
    table.add_column("Started (UTC)", style="white")
    table.add_column("Turns", style="bold white", justify="center")
    table.add_column("Final State", style="bold green")
    table.add_column("Model Used", style="cyan")
    table.add_column("Candidate", style="magenta")

    for c in cycles:
        final_st = c.final_reasoning_state.value if c.final_reasoning_state else "INCOMPLETE"
        has_cand = "[green]YES[/green]" if c.candidate else "[dim]NO[/dim]"
        table.add_row(
            c.cycle_id[:12],
            c.session_id[:10],
            c.started_at.strftime("%H:%M:%S"),
            str(len(c.turns)),
            final_st,
            c.model_used,
            has_cand,
        )

    console.print(table)


async def cmd_paper_status(runtime: NiftyTraderRuntime) -> None:
    """Shows Sensibull paper trading portfolio status and open positions count."""
    console.print("[cyan]Connecting to Sensibull Virtual Portfolio...[/cyan]")
    try:
        summary = await runtime.paper_service.get_portfolio_status()
        color = "green" if summary.is_safe_environment else "red"

        table = Table(title="[bold green]Sensibull Virtual Portfolio Status[/bold green]")
        table.add_column("Field", style="cyan", no_wrap=True)
        table.add_column("Value", style="bold white")

        table.add_row("Environment Mode", f"[{color}]{summary.environment.value}[/{color}]")
        table.add_row("Safe Environment Verified", f"[{color}]{'YES' if summary.is_safe_environment else 'NO - DANGER'}[/{color}]")
        table.add_row("Open Positions Count", str(summary.open_positions_count))
        table.add_row("Total Positions Tracked", str(summary.total_positions))

        unreal_color = "green" if summary.total_unrealized_pnl >= 0 else "red"
        real_color = "green" if summary.total_realized_pnl >= 0 else "red"
        net_color = "green" if summary.net_pnl >= 0 else "red"

        table.add_row("Unrealized P&L", f"[{unreal_color}]Rs. {summary.total_unrealized_pnl:,.2f}[/{unreal_color}]")
        table.add_row("Realized P&L", f"[{real_color}]Rs. {summary.total_realized_pnl:,.2f}[/{real_color}]")
        table.add_row("Net Virtual P&L", f"[{net_color}]Rs. {summary.net_pnl:,.2f}[/{net_color}]")
        table.add_row("Last Synced (UTC)", summary.last_synced_at.strftime("%Y-%m-%d %H:%M:%S"))

        console.print(table)
    except Exception as e:
        console.print(f"[bold red]Failed to fetch paper trading status:[/bold red] {e}")


async def cmd_paper_positions(runtime: NiftyTraderRuntime) -> None:
    """Lists currently open paper positions on Sensibull."""
    open_positions = runtime.paper_store.get_open_positions()
    if not open_positions:
        console.print("[yellow]No open paper positions found in local store. Running sync...[/yellow]")
        summary = await runtime.paper_service.get_portfolio_status()
        open_positions = [p for p in summary.positions if p.status.value == "OPEN"]

    if not open_positions:
        console.print("[bold green]Zero open paper positions.[/bold green]")
        return

    table = Table(title="[bold green]Open Paper Positions (Sensibull)[/bold green]")
    table.add_column("Position ID", style="dim", no_wrap=True)
    table.add_column("Symbol", style="white")
    table.add_column("Strike", style="bold cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Expiry", style="white")
    table.add_column("Lots (Qty)", style="white")
    table.add_column("Avg Price", style="white")
    table.add_column("LTP", style="white")
    table.add_column("P&L (Rs.)", style="bold")
    table.add_column("P&L (%)", style="bold")

    for p in open_positions:
        pnl_color = "green" if p.unrealized_pnl >= 0 else "red"
        table.add_row(
            p.position_id[:10],
            p.symbol,
            str(p.strike),
            p.option_type.value,
            p.expiry,
            f"{p.lots} ({p.quantity})",
            f"Rs. {p.avg_price:.2f}",
            f"Rs. {p.current_ltp:.2f}",
            f"[{pnl_color}]Rs. {p.unrealized_pnl:+,.2f}[/{pnl_color}]",
            f"[{pnl_color}]{p.pnl_percentage:+.2f}%[/{pnl_color}]",
        )
    console.print(table)


async def cmd_paper_order(
    runtime: NiftyTraderRuntime,
    strike: float,
    option_type: str,
    action: str = "BUY",
    lots: int = 1,
    expiry: str = "CURRENT",
    limit_price: Optional[float] = None,
) -> None:
    """Executes a paper order and visually verifies execution."""
    from nifty_trader.paper.contracts import PaperAction, PaperOptionType, PaperTradeOrderRequest
    req = PaperTradeOrderRequest(
        symbol="NIFTY",
        expiry=expiry,
        strike=strike,
        option_type=PaperOptionType(option_type.upper()),
        action=PaperAction(action.upper()),
        lots=lots,
        quantity=lots * 25,
        limit_price=limit_price,
    )
    console.print(f"[cyan]Submitting Paper Order: {req.action.value} {req.lots} Lot(s) NIFTY {req.strike} {req.option_type.value}...[/cyan]")
    order = await runtime.paper_service.execute_trade(req)

    status_color = "green" if order.status.value in ["OPEN", "FILLED"] else "red"
    console.print(Panel(
        f"[bold]Order ID:[/bold] {order.order_id}\n"
        f"[bold]Status:[/bold] [{status_color}]{order.status.value}[/{status_color}]\n"
        f"[bold]Details:[/bold] {order.action.value} {order.quantity} qty @ {order.strike} {order.option_type.value}\n"
        f"[bold]Entry Price:[/bold] Rs. {order.entry_price if order.entry_price else 0.0:.2f}\n"
        f"[bold]Reason/Note:[/bold] {order.status_reason or 'None'}\n"
        f"[bold]Verified At:[/bold] {order.verified_at.strftime('%H:%M:%S UTC') if order.verified_at else 'UNVERIFIED'}",
        title="[bold yellow]Paper Order Execution Result[/bold yellow]",
        border_style=status_color,
    ))


async def cmd_paper_close(runtime: NiftyTraderRuntime, position_id: Optional[str] = None, close_all: bool = False) -> None:
    """Closes an open paper position or squares off all positions."""
    if close_all:
        console.print("[bold yellow]Initiating emergency square-off of ALL open paper positions...[/bold yellow]")
        closed = await runtime.paper_service.close_all_positions(reason="Manual CLI emergency square-off")
        console.print(f"[bold green]Successfully closed {len(closed)} position(s).[/bold green]")
        return

    if not position_id:
        console.print("[bold red]Please specify a --position-id or use --all to square off everything.[/bold red]")
        return

    console.print(f"[cyan]Closing position {position_id}...[/cyan]")
    success, pos = await runtime.paper_service.close_position(position_id, reason="Manual CLI square-off")
    if success and pos:
        console.print(f"[bold green]Position {position_id} closed! Realized P&L: Rs. {pos.realized_pnl:+,.2f}[/bold green]")
    else:
        console.print(f"[bold red]Failed to close position {position_id}.[/bold red]")


async def cmd_paper_sync(runtime: NiftyTraderRuntime) -> None:
    """Synchronizes and reconciles Sensibull ground truth with Hermes store."""
    console.print("[cyan]Reconciling Sensibull virtual portfolio state with local store...[/cyan]")
    summary, discrepancies = await runtime.paper_service.sync_and_reconcile()
    console.print(f"[bold green][OK] Reconciliation complete.[/bold green] Found {len(discrepancies)} discrepancy/discrepancies.")
    if discrepancies:
        for d in discrepancies:
            console.print(f"  * [yellow]{d.discrepancy_type}[/yellow]: {d.resolution_action}")


def main() -> None:
    parser = argparse.ArgumentParser(description="NIFTY Autonomous Trader CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("start", help="Start the autonomous trading runtime")
    subparsers.add_parser("status", help="Show system status and provider health")
    subparsers.add_parser("test-brain", help="Test ModelRouter with Gemini reasoning")
    subparsers.add_parser("browser-test", help="Test Chrome CDP browser startup and navigation")

    open_parser = subparsers.add_parser("browser-open", help="Navigate to a URL and inspect page")
    open_parser.add_argument("url", help="URL to navigate to")
    open_parser.add_argument("--multimodal", action="store_true", help="Send screenshot to ModelRouter for neutral perception check")

    login_parser = subparsers.add_parser("browser-login", help="Launch interactive browser to securely log into Sensibull, TradingView, or Google without exposing credentials")
    login_parser.add_argument("--target", choices=["sensibull", "tradingview", "both"], default="both", help="Target service to log in to (default: both)")
    login_parser.add_argument("--url", default=None, help="Custom target login URL (overrides --target)")

    upstream_parser = subparsers.add_parser("upstream", help="Upstream Hermes management")
    upstream_parser.add_argument("action", choices=["check", "inspect", "test"], help="Upstream action to perform")

    subparsers.add_parser("features", help="List feature extension registry and status")

    # Package 3 Market Observation & Instruction CLI Commands
    subparsers.add_parser("market-status", help="Show market session, candle cache, and perception status")
    subparsers.add_parser("market-sync", help="Synchronize 1H and 15M candles from provider to SQLite cache")

    obs_parser = subparsers.add_parser("market-observe", help="Gather full market observation and run objective perception analysis")
    obs_parser.add_argument("--multimodal", action="store_true", help="Capture TradingView screenshot for multimodal chart analysis")
    obs_parser.add_argument("--no-cross-check", action="store_true", help="Skip browser vs numerical price cross-check")
    obs_parser.add_argument("--sources", help="Comma-separated observation sources (e.g. tradingview,sensibull,numerical)")

    # Package 3.1 Sensibull Browser Observation Test
    subparsers.add_parser("sensibull-test", help="Test Sensibull option chain browser navigation and extraction")

    inst_parser = subparsers.add_parser("instruction", help="Submit manual agent steering instruction")
    inst_parser.add_argument("text", help="Instruction text for agent observation")
    inst_parser.add_argument("--priority", default="NORMAL", choices=["NORMAL", "HIGH", "URGENT"], help="Instruction priority")
    inst_parser.add_argument("--expires-in-hours", type=float, default=4.0, help="Hours before instruction expires")

    inst_list_parser = subparsers.add_parser("instruction-list", help="List stored manual agent instructions")
    inst_list_parser.add_argument("--status", choices=["PENDING", "ACTIVE", "COMPLETED", "REJECTED", "EXPIRED"], help="Filter by status")

    # Package 4 Trading Brain & Market Reasoning CLI Commands
    brain_parser = subparsers.add_parser("brain-analyze", help="Run full market observation and execute Trading Brain reasoning")
    brain_parser.add_argument("--multimodal", action="store_true", help="Capture screenshot for visual reasoning")
    brain_parser.add_argument("--no-cross-check", action="store_true", help="Skip browser cross-check during observation")
    brain_parser.add_argument("--include-sensibull", action="store_true", help="Include Sensibull option chain in observation")
    brain_parser.add_argument("--sources", help="Comma-separated observation sources (e.g. numerical,sensibull,tradingview)")

    history_parser = subparsers.add_parser("brain-history", help="List persisted brain reasoning runs from SQLite history")
    history_parser.add_argument("--limit", type=int, default=10, help="Number of records to show")
    history_parser.add_argument("--state", choices=["NO_TRADE", "WAIT", "WATCH", "DEVELOPING", "CANDIDATE"], help="Filter by setup state")

    # Package 5 Autonomous Observation & Waiting CLI Commands
    auto_parser = subparsers.add_parser("autonomous", help="Autonomous Observation & Waiting Engine commands")
    auto_sub = auto_parser.add_subparsers(dest="auto_command", help="Autonomous sub-commands")

    auto_start = auto_sub.add_parser("start", help="Start the autonomous observation engine")
    auto_start.add_argument("--once", action="store_true", help="Run a single bounded observation cycle and exit")
    auto_start.add_argument("--symbol", default="NIFTY", help="Target instrument symbol")

    auto_sub.add_parser("status", help="Show autonomous engine operational status and next wake time")
    auto_sub.add_parser("observe-now", help="Interrupt current wait and trigger an immediate observation cycle")
    auto_sub.add_parser("pause", help="Pause the autonomous observation engine")
    auto_sub.add_parser("resume", help="Resume the autonomous observation engine")
    auto_sub.add_parser("stop", help="Stop the autonomous observation engine")

    cycles_parser = auto_sub.add_parser("cycles", help="List persisted autonomous reasoning cycles")
    cycles_parser.add_argument("--limit", type=int, default=10, help="Number of records to show")

    # Stage 6 Hermes-Brain Collaborative Orchestration CLI Commands
    collab_parser = subparsers.add_parser("collaborate", help="Execute Hermes-Brain collaborative trading cycle")
    collab_parser.add_argument("--symbol", default="NIFTY", help="Target instrument symbol")
    collab_parser.add_argument("--max-turns", type=int, default=3, help="Maximum multi-turn interactive observation/re-evaluation turns")
    collab_parser.add_argument("--once", action="store_true", default=True, help="Run a single bounded collaborative cycle (default True)")

    collab_status = subparsers.add_parser("collaborate-status", help="List recent Hermes-Brain collaboration cycles from audit log")
    collab_status.add_argument("--limit", type=int, default=10, help="Number of records to show")

    # Stage 8 Sensibull Paper-Trading Commands
    subparsers.add_parser("paper-status", help="Show Sensibull paper trading status, open positions count, and P&L")
    subparsers.add_parser("paper-positions", help="List active Sensibull virtual positions")

    paper_order_parser = subparsers.add_parser("paper-order", help="Submit a paper trade order into Sensibull Virtual Portfolio")
    paper_order_parser.add_argument("--strike", type=float, required=True, help="NIFTY option strike price")
    paper_order_parser.add_argument("--type", choices=["CE", "PE", "FUT"], required=True, help="Option type (CE/PE/FUT)")
    paper_order_parser.add_argument("--action", choices=["BUY", "SELL"], default="BUY", help="Order action (BUY/SELL)")
    paper_order_parser.add_argument("--lots", type=int, default=1, help="Number of lots")
    paper_order_parser.add_argument("--expiry", default="CURRENT", help="Expiry date")
    paper_order_parser.add_argument("--limit-price", type=float, default=None, help="Optional limit entry price")

    paper_close_parser = subparsers.add_parser("paper-close", help="Close/Square-off paper position(s)")
    paper_close_parser.add_argument("--position-id", help="Position ID to close")
    paper_close_parser.add_argument("--all", action="store_true", help="Emergency square-off for all open positions")

    subparsers.add_parser("paper-sync", help="Synchronize and reconcile Sensibull ground truth with Hermes store")

    args = parser.parse_args()
    runtime = NiftyTraderRuntime()

    if args.command == "start" or not args.command:
        asyncio.run(cmd_start(runtime))
    elif args.command == "status":
        asyncio.run(cmd_status(runtime))
    elif args.command == "test-brain":
        asyncio.run(cmd_test_brain(runtime))
    elif args.command == "browser-test":
        asyncio.run(cmd_browser_test(runtime))
    elif args.command == "browser-open":
        asyncio.run(cmd_browser_open(runtime, args.url, run_multimodal=args.multimodal))
    elif args.command == "browser-login":
        cmd_browser_login(target=args.target, url=args.url)
    elif args.command == "sensibull-test":
        asyncio.run(cmd_sensibull_test(runtime))
    elif args.command == "upstream":
        asyncio.run(cmd_upstream(runtime, args.action))
    elif args.command == "features":
        asyncio.run(cmd_features(runtime))
    elif args.command == "market-status":
        asyncio.run(cmd_market_status(runtime))
    elif args.command == "market-sync":
        asyncio.run(cmd_market_sync(runtime))
    elif args.command == "market-observe":
        asyncio.run(cmd_market_observe(
            runtime,
            multimodal=args.multimodal,
            cross_check=not args.no_cross_check,
            sources=args.sources,
        ))
    elif args.command == "instruction":
        asyncio.run(cmd_instruction(runtime, text=args.text, priority=args.priority, expires_in_hours=args.expires_in_hours))
    elif args.command == "instruction-list":
        asyncio.run(cmd_instruction_list(runtime, status_filter=args.status))
    elif args.command == "brain-analyze":
        asyncio.run(cmd_brain_analyze(
            runtime,
            cross_check=not args.no_cross_check,
            include_sensibull=args.include_sensibull,
            sources=args.sources,
            multimodal=args.multimodal,
        ))
    elif args.command == "brain-history":
        asyncio.run(cmd_brain_history(
            runtime,
            limit=args.limit,
            state=args.state,
        ))
    elif args.command == "collaborate":
        asyncio.run(cmd_collaborate(
            runtime,
            symbol=args.symbol,
            max_turns=args.max_turns,
        ))
    elif args.command == "collaborate-status":
        asyncio.run(cmd_collaborate_status(
            runtime,
            limit=args.limit,
        ))
    elif args.command == "paper-status":
        asyncio.run(cmd_paper_status(runtime))
    elif args.command == "paper-positions":
        asyncio.run(cmd_paper_positions(runtime))
    elif args.command == "paper-order":
        asyncio.run(cmd_paper_order(
            runtime,
            strike=args.strike,
            option_type=args.type,
            action=args.action,
            lots=args.lots,
            expiry=args.expiry,
            limit_price=args.limit_price,
        ))
    elif args.command == "paper-close":
        asyncio.run(cmd_paper_close(runtime, position_id=args.position_id, close_all=args.all))
    elif args.command == "paper-sync":
        asyncio.run(cmd_paper_sync(runtime))
    elif args.command == "autonomous":
        if args.auto_command == "start":
            asyncio.run(cmd_autonomous_start(runtime, once=args.once, symbol=args.symbol))
        elif args.auto_command == "status":
            asyncio.run(cmd_autonomous_status(runtime))
        elif args.auto_command == "stop":
            asyncio.run(cmd_autonomous_stop(runtime))
        elif args.auto_command == "pause":
            asyncio.run(cmd_autonomous_pause(runtime))
        elif args.auto_command == "resume":
            asyncio.run(cmd_autonomous_resume(runtime))
        elif args.auto_command == "observe-now":
            asyncio.run(cmd_autonomous_observe_now(runtime))
        elif args.auto_command == "cycles":
            asyncio.run(cmd_autonomous_cycles(runtime, limit=args.limit))
        else:
            asyncio.run(cmd_autonomous_status(runtime))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
