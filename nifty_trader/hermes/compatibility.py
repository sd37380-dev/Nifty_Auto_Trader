"""
Hermes Compatibility Checker.

Evaluates upstream Hermes platform compatibility against NIFTY Autonomous Trader
architectural prerequisites, invariants, and adapter contracts.
"""

import sys
from typing import Any, Dict, List
from pydantic import BaseModel, Field
from nifty_trader.hermes.adapter import HermesIntegrationAdapter
from nifty_trader.hermes.version import HermesVersionManager


class CheckResult(BaseModel):
    name: str
    passed: bool
    details: str
    is_critical: bool = True


class CompatibilityReport(BaseModel):
    passed: bool
    hermes_commit: str
    baseline_commit: str
    checks: List[CheckResult] = Field(default_factory=list)
    breaking_changes: List[str] = Field(default_factory=list)


class HermesCompatibilityChecker:
    """Verifies that the upstream Hermes dependency complies with system contracts."""

    def __init__(self, version_manager: HermesVersionManager, adapter: HermesIntegrationAdapter):
        self.version_mgr = version_manager
        self.adapter = adapter

    async def run_all_checks(self) -> CompatibilityReport:
        """Runs the complete suite of upstream compatibility checks."""
        checks: List[CheckResult] = []
        breaking: List[str] = []

        # 1. Python Environment Check
        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        py_ok = sys.version_info >= (3, 11)
        checks.append(CheckResult(
            name="python_version",
            passed=py_ok,
            details=f"Python {py_ver} (required >= 3.11)",
            is_critical=True,
        ))
        if not py_ok:
            breaking.append(f"Incompatible Python version: {py_ver}")

        # 2. Baseline Git Integrity
        integrity = self.version_mgr.verify_baseline_integrity()
        commit_ok = integrity["matches_baseline"]
        checks.append(CheckResult(
            name="hermes_baseline_commit",
            passed=commit_ok,
            details=f"Current: {integrity.get('current_commit')[:8]} | Baseline: {integrity.get('baseline_commit')[:8]}",
            is_critical=True,
        ))
        if not commit_ok:
            breaking.append(
                f"Commit divergence: local Hermes is at {integrity.get('current_commit')} "
                f"vs baseline {integrity.get('baseline_commit')}"
            )

        # 3. Clean Repo State
        clean_ok = integrity["is_clean"]
        checks.append(CheckResult(
            name="hermes_repo_cleanliness",
            passed=clean_ok,
            details="Repository has no uncommitted changes" if clean_ok else "Repository is dirty (uncommitted modifications)",
            is_critical=False,
        ))

        # 4. Adapter Health Check
        health = await self.adapter.health_check()
        checks.append(CheckResult(
            name="adapter_bridge_health",
            passed=health.is_healthy,
            details=f"Ready domains: {', '.join(health.domains_ready)}",
            is_critical=True,
        ))
        if not health.is_healthy:
            breaking.append("HermesIntegrationAdapter failed health check")

        # 5. Safety Invariants Check
        manifest = self.version_mgr.manifest
        if manifest:
            invariants_ok = (
                manifest.safety_invariants.immutable_trading_rules
                and manifest.safety_invariants.prevent_auto_order_execution
                and manifest.safety_invariants.preserve_user_memory_on_update
            )
            checks.append(CheckResult(
                name="safety_invariants",
                passed=invariants_ok,
                details="Trading safety invariants intact & enforced",
                is_critical=True,
            ))
            if not invariants_ok:
                breaking.append("Critical safety invariants violated in configuration")

        all_critical_passed = all(c.passed for c in checks if c.is_critical)

        return CompatibilityReport(
            passed=all_critical_passed,
            hermes_commit=integrity.get("current_commit") or "UNKNOWN",
            baseline_commit=integrity.get("baseline_commit") or "UNKNOWN",
            checks=checks,
            breaking_changes=breaking,
        )
