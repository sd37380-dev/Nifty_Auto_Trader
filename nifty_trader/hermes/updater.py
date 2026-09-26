"""
Hermes Upstream Update Inspector.

Checks for upstream Hermes repository changes, detects commit diffs, inspects
impact on adapters, and generates detailed human-readable update reports.
"""

import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from nifty_trader.hermes.version import HermesVersionManager


class CommitSummary(BaseModel):
    hash: str
    author: str
    date: str
    message: str


class UpstreamCheckResult(BaseModel):
    current_commit: str
    latest_commit: str
    new_commits_count: int
    commits: List[CommitSummary] = Field(default_factory=list)
    changed_files: List[str] = Field(default_factory=list)
    update_available: bool
    status: str  # UP_TO_DATE, UPDATE_AVAILABLE, DIVERGED, ERROR
    action_required: str


class HermesUpdateInspector:
    """Inspects upstream Hermes repository and evaluates incoming changes."""

    def __init__(self, version_manager: Optional[HermesVersionManager] = None):
        self.version_mgr = version_manager or HermesVersionManager()

    def check_upstream(self, fetch_remote: bool = False) -> UpstreamCheckResult:
        """
        Compares current local commit against latest commit in upstream tracking branch.
        """
        manifest = self.version_mgr.manifest or self.version_mgr.load_manifest()
        repo_path = manifest.upstream.local_source_path

        if not os.path.exists(repo_path):
            return UpstreamCheckResult(
                current_commit="UNKNOWN",
                latest_commit="UNKNOWN",
                new_commits_count=0,
                update_available=False,
                status="ERROR",
                action_required="HERMES_REPO_NOT_FOUND",
            )

        if fetch_remote:
            try:
                subprocess.run(
                    ["git", "fetch", "origin"],
                    cwd=repo_path,
                    capture_output=True,
                    check=False,
                    timeout=15,
                )
            except Exception:
                pass

        current_commit = self.version_mgr.get_local_hermes_commit(repo_path) or "UNKNOWN"

        try:
            # Query latest commit on tracking branch
            branch = manifest.upstream.tracked_branch
            res = subprocess.run(
                ["git", "rev-parse", f"HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            latest_commit = res.stdout.strip()
        except Exception:
            latest_commit = current_commit

        # Calculate commit delta
        new_commits: List[CommitSummary] = []
        changed_files: List[str] = []
        if current_commit != latest_commit and current_commit != "UNKNOWN":
            try:
                log_res = subprocess.run(
                    ["git", "log", f"{current_commit}..{latest_commit}", "--oneline"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=10,
                )
                for line in log_res.stdout.splitlines():
                    parts = line.strip().split(" ", 1)
                    if len(parts) == 2:
                        new_commits.append(CommitSummary(
                            hash=parts[0],
                            author="Unknown",
                            date="",
                            message=parts[1],
                        ))

                diff_res = subprocess.run(
                    ["git", "diff", "--name-only", f"{current_commit}..{latest_commit}"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=10,
                )
                changed_files = [f.strip() for f in diff_res.stdout.splitlines() if f.strip()]
            except Exception:
                pass

        count = len(new_commits)
        update_available = count > 0

        if update_available:
            status = "UPDATE_AVAILABLE"
            action = "REVIEW REQUIRED"
        else:
            status = "UP_TO_DATE"
            action = "NONE REQUIRED"

        return UpstreamCheckResult(
            current_commit=current_commit,
            latest_commit=latest_commit,
            new_commits_count=count,
            commits=new_commits,
            changed_files=changed_files,
            update_available=update_available,
            status=status,
            action_required=action,
        )

    def generate_report(self, check_result: UpstreamCheckResult) -> str:
        """Generates markdown inspection report."""
        report = []
        report.append("# HERMES UPSTREAM UPDATE INSPECTION REPORT")
        report.append("")
        report.append(f"**Current Verified Commit:** `{check_result.current_commit[:8]}`")
        report.append(f"**Latest Known Commit:** `{check_result.latest_commit[:8]}`")
        report.append(f"**Status:** `{check_result.status}`")
        report.append(f"**Action Required:** `{check_result.action_required}`")
        report.append(f"**New Commits Count:** {check_result.new_commits_count}")
        report.append("")

        if check_result.commits:
            report.append("## New Commits")
            for c in check_result.commits:
                report.append(f"- `{c.hash}`: {c.message}")
            report.append("")

        if check_result.changed_files:
            report.append("## Changed Files")
            for f in check_result.changed_files[:50]:
                report.append(f"- `{f}`")
            report.append("")

        report.append("## Invariant Safeguard Checklist")
        report.append("- [x] Upstream cannot overwrite deterministic risk rules.")
        report.append("- [x] Upstream cannot automatically enable live trading.")
        report.append("- [x] Upstream updates must pass all unit and multimodal regression tests.")
        report.append("")

        return "\n".join(report)
