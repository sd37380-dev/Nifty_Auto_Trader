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
    table.add_row("Capability (Paper Broker)", "[blue]NOT INSTALLED[/blue]")
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
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
