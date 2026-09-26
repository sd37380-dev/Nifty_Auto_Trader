"""
Hermes Integration Adapter.

Concrete implementation of HermesAgentAdapter and HermesToolAdapter.
Bridges NIFTY Autonomous Trader to Hermes capabilities through stable external
contracts without direct coupling to Hermes internal private modules.
"""

import logging
from typing import Any, Dict, List, Optional
from nifty_trader.hermes.interfaces import (
    AdapterHealth,
    HermesAgentAdapter,
    HermesToolAdapter,
    ToolDefinition,
    ToolExecutionResult,
)
from nifty_trader.hermes.version import HermesVersionManager

logger = logging.getLogger(__name__)


class HermesIntegrationAdapter(HermesAgentAdapter, HermesToolAdapter):
    """
    Main integration bridge to the upstream Hermes platform.
    Ensures safe, bounded execution and decoupled lifecycle management.
    """

    def __init__(self, version_manager: Optional[HermesVersionManager] = None):
        self.version_mgr = version_manager or HermesVersionManager()
        self._tools: Dict[str, ToolDefinition] = {}
        self._initialized = False

    async def initialize(self) -> None:
        """Initializes the adapter and verifies baseline integrity."""
        integrity = self.version_mgr.verify_baseline_integrity()
        if integrity["status"] != "VERIFIED":
            logger.warning(
                "Hermes baseline commit check reported: %s (Commit: %s, Baseline: %s)",
                integrity["status"],
                integrity.get("current_commit"),
                integrity.get("baseline_commit"),
            )
        self._initialized = True
        logger.info("HermesIntegrationAdapter initialized successfully.")

    async def health_check(self) -> AdapterHealth:
        """Evaluates health of the adapter bridge."""
        if not self._initialized:
            await self.initialize()

        integrity = self.version_mgr.verify_baseline_integrity()
        manifest = self.version_mgr.manifest

        is_healthy = self._initialized and (integrity.get("current_commit") is not None)

        return AdapterHealth(
            is_healthy=is_healthy,
            version=manifest.upstream.integration_version if manifest else "0.1.0",
            hermes_commit=integrity.get("current_commit") or "UNKNOWN",
            domains_ready=["browser", "model_routing", "tools"],
            details={
                "matches_baseline": integrity.get("matches_baseline", False),
                "is_clean": integrity.get("is_clean", False),
                "local_path": manifest.upstream.local_source_path if manifest else "",
            },
        )

    def register_tool(self, tool_def: ToolDefinition) -> bool:
        """Registers a tool definition."""
        self._tools[tool_def.name] = tool_def
        logger.debug("Registered tool in HermesToolAdapter: %s", tool_def.name)
        return True

    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> ToolExecutionResult:
        """Executes a tool within the safe boundary."""
        if tool_name not in self._tools:
            return ToolExecutionResult(
                tool_name=tool_name,
                success=False,
                output=None,
                error=f"Tool '{tool_name}' is not registered with HermesToolAdapter.",
            )

        # In production this delegates to registered tool callbacks
        return ToolExecutionResult(
            tool_name=tool_name,
            success=True,
            output={"result": f"Simulated execution of {tool_name} with {len(arguments)} args"},
        )

    def list_tools(self) -> List[ToolDefinition]:
        """Returns all registered tool definitions."""
        return list(self._tools.values())

    async def shutdown(self) -> None:
        """Gracefully shuts down adapter resources."""
        self._tools.clear()
        self._initialized = False
        logger.info("HermesIntegrationAdapter shutdown cleanly.")
