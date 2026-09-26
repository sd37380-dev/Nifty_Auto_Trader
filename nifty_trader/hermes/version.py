"""
Hermes Version & Manifest Management.

Tracks the exact commit, branch, and verification status of the upstream
Hermes Agent platform dependency.
"""

import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional
import yaml
from pydantic import BaseModel, Field


class UpstreamDetails(BaseModel):
    name: str = "hermes-agent"
    repository: str
    tracked_branch: str = "main"
    local_source_path: str
    baseline_commit: str
    last_verified_commit: str
    last_verified_date: str
    verification_status: str
    integration_version: str


class CompatibilityDetails(BaseModel):
    min_python: str = "3.11"
    verified_python: str = "3.13.11"
    adapter_layer: str
    required_domains: list[str] = Field(default_factory=list)


class SafetyInvariants(BaseModel):
    immutable_trading_rules: bool = True
    prevent_auto_order_execution: bool = True
    preserve_user_memory_on_update: bool = True
    isolated_browser_profile: bool = True


class HermesManifest(BaseModel):
    upstream: UpstreamDetails
    compatibility: CompatibilityDetails
    safety_invariants: SafetyInvariants


class HermesVersionManager:
    """Manages upstream Hermes version tracking and integrity verification."""

    def __init__(self, manifest_path: Optional[Path] = None):
        self.manifest_path = manifest_path or Path("config/hermes-version.yaml")
        self.manifest: Optional[HermesManifest] = None
        if self.manifest_path.exists():
            self.load_manifest()

    def load_manifest(self) -> HermesManifest:
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self.manifest = HermesManifest(**data)
        return self.manifest

    def get_local_hermes_commit(self, custom_path: Optional[str] = None) -> Optional[str]:
        """Queries Git for the current commit hash of the local pristine Hermes repo."""
        repo_path = custom_path or (self.manifest.upstream.local_source_path if self.manifest else "D:\\AI_Trading\\hermes-agent")
        if not os.path.exists(repo_path):
            return None

        try:
            res = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            return res.stdout.strip()
        except Exception:
            return None

    def is_repo_clean(self, custom_path: Optional[str] = None) -> bool:
        """Verifies that the local Hermes reference repository has no uncommitted modifications."""
        repo_path = custom_path or (self.manifest.upstream.local_source_path if self.manifest else "D:\\AI_Trading\\hermes-agent")
        if not os.path.exists(repo_path):
            return False

        try:
            res = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            return len(res.stdout.strip()) == 0
        except Exception:
            return False

    def verify_baseline_integrity(self) -> Dict[str, Any]:
        """
        Verifies that the local Hermes source matches the recorded baseline commit.
        """
        if not self.manifest:
            self.load_manifest()

        current_commit = self.get_local_hermes_commit()
        baseline_commit = self.manifest.upstream.baseline_commit
        last_verified = self.manifest.upstream.last_verified_commit

        matches_baseline = bool(current_commit and current_commit.startswith(baseline_commit[:8]))
        is_clean = self.is_repo_clean()

        return {
            "current_commit": current_commit,
            "baseline_commit": baseline_commit,
            "last_verified_commit": last_verified,
            "matches_baseline": matches_baseline,
            "is_clean": is_clean,
            "status": "VERIFIED" if (matches_baseline and is_clean) else "MISMATCH",
        }
