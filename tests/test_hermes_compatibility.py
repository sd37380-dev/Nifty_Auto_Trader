"""
Tests for Hermes Version Tracking and Compatibility Layer.
"""

from pathlib import Path
import pytest

from nifty_trader.hermes.adapter import HermesIntegrationAdapter
from nifty_trader.hermes.compatibility import HermesCompatibilityChecker
from nifty_trader.hermes.interfaces import ToolDefinition
from nifty_trader.hermes.updater import HermesUpdateInspector
from nifty_trader.hermes.version import HermesManifest, HermesVersionManager


def test_hermes_version_manifest_loading():
    """Verify hermes-version.yaml loads and validates schema."""
    mgr = HermesVersionManager()
    manifest = mgr.load_manifest()

    assert manifest.upstream.name == "hermes-agent"
    assert manifest.upstream.baseline_commit == "d0288be5b3330d2442e3907185b8e9d0958297bb"
    assert manifest.upstream.verification_status == "VERIFIED"
    assert manifest.compatibility.adapter_layer == "nifty_trader.hermes.adapter"
    assert manifest.safety_invariants.immutable_trading_rules is True
    assert manifest.safety_invariants.preserve_user_memory_on_update is True


def test_hermes_local_commit_detection():
    """Verify Git commit detection against local pristine repo."""
    mgr = HermesVersionManager()
    commit = mgr.get_local_hermes_commit()
    assert commit is not None
    assert len(commit) == 40
    assert commit.startswith("d0288be5")


def test_hermes_baseline_integrity():
    """Verify baseline integrity check matches expected commit."""
    mgr = HermesVersionManager()
    integrity = mgr.verify_baseline_integrity()

    assert integrity["matches_baseline"] is True
    assert integrity["is_clean"] is True
    assert integrity["status"] == "VERIFIED"


@pytest.mark.asyncio
async def test_hermes_adapter_lifecycle_and_tools():
    """Verify HermesIntegrationAdapter initialization, health, and tool execution."""
    mgr = HermesVersionManager()
    adapter = HermesIntegrationAdapter(mgr)

    await adapter.initialize()
    health = await adapter.health_check()

    assert health.is_healthy is True
    assert health.hermes_commit.startswith("d0288be5")
    assert "browser" in health.domains_ready

    # Register and execute tool
    tool_def = ToolDefinition(
        name="market_inspector",
        description="Inspects market conditions",
        parameters={"symbol": {"type": "string"}},
    )
    assert adapter.register_tool(tool_def) is True
    assert len(adapter.list_tools()) == 1

    exec_res = await adapter.execute_tool("market_inspector", {"symbol": "NIFTY"})
    assert exec_res.success is True

    await adapter.shutdown()
    assert len(adapter.list_tools()) == 0


@pytest.mark.asyncio
async def test_hermes_compatibility_checker():
    """Verify all system compatibility checks pass against baseline."""
    mgr = HermesVersionManager()
    adapter = HermesIntegrationAdapter(mgr)
    checker = HermesCompatibilityChecker(mgr, adapter)

    report = await checker.run_all_checks()
    assert report.passed is True
    assert len(report.breaking_changes) == 0
    assert report.hermes_commit.startswith("d0288be5")


def test_hermes_update_inspector():
    """Verify upstream update inspector detects commit state without modifying repo."""
    inspector = HermesUpdateInspector()
    result = inspector.check_upstream(fetch_remote=False)

    assert result.current_commit.startswith("d0288be5")
    assert result.update_available is False
    assert result.status == "UP_TO_DATE"
    assert result.action_required == "NONE REQUIRED"

    report = inspector.generate_report(result)
    assert "HERMES UPSTREAM UPDATE INSPECTION REPORT" in report
    assert "d0288be5" in report
