"""
Command-Line Interface (CLI) for NIFTY Autonomous Trader.
"""

import argparse
import asyncio
import sys
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from nifty_trader.core.runtime import NiftyTraderRuntime

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
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
