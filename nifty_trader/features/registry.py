"""
Feature Registry and Capability Discovery.

Manages feature modules, verifies dependency graphs, orchestrates lifecycle,
and provides capability inspection for the NIFTY Autonomous Trader runtime.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import yaml
from pydantic import BaseModel, Field

from nifty_trader.features.base import (
    FeatureCapability,
    FeatureHealth,
    FeatureModule,
    FeatureStatus,
)

logger = logging.getLogger(__name__)


class FeatureConfigEntry(BaseModel):
    name: str
    description: str
    version: str
    status: FeatureStatus
    dependencies: List[str] = Field(default_factory=list)
    module: Optional[str] = None


class FeatureRegistry:
    """Central registry and dependency manager for product feature extensions."""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or Path("config/features.yaml")
        self._declared_configs: Dict[str, FeatureConfigEntry] = {}
        self._modules: Dict[str, FeatureModule] = {}
        if self.config_path.exists():
            self.load_declarations()

    def load_declarations(self) -> Dict[str, FeatureConfigEntry]:
        """Loads feature declarations from features.yaml."""
        with open(self.config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        features_data = data.get("features", {})
        self._declared_configs = {
            k: FeatureConfigEntry(**v) for k, v in features_data.items()
        }
        return self._declared_configs

    def register_module(self, module: FeatureModule) -> None:
        """Registers an instantiated feature module."""
        self._modules[module.name] = module
        logger.debug("Registered feature module: %s (v%s)", module.name, module.version)

    def validate_dependencies(self, feature_name: str) -> List[str]:
        """
        Validates whether all dependencies for a given feature are present and enabled.
        Returns a list of missing or unsatisfied dependency error messages.
        """
        config = self._declared_configs.get(feature_name)
        if not config:
            return [f"Feature '{feature_name}' is not declared in registry."]

        errors = []
        for dep in config.dependencies:
            dep_cfg = self._declared_configs.get(dep)
            if not dep_cfg:
                errors.append(f"Dependency '{dep}' required by '{feature_name}' is NOT installed.")
            elif dep_cfg.status not in (FeatureStatus.ENABLED, FeatureStatus.INSTALLED):
                errors.append(
                    f"Dependency '{dep}' required by '{feature_name}' is in status '{dep_cfg.status.value}', not ENABLED."
                )

        return errors

    def can_start_feature(self, feature_name: str) -> bool:
        """Determines if a feature can safely start based on its dependency tree."""
        return len(self.validate_dependencies(feature_name)) == 0

    def get_topological_order(self) -> List[str]:
        """Calculates topological start order for declared features."""
        in_degree: Dict[str, int] = {k: 0 for k in self._declared_configs}
        graph: Dict[str, List[str]] = {k: [] for k in self._declared_configs}

        for name, entry in self._declared_configs.items():
            for dep in entry.dependencies:
                if dep in graph:
                    graph[dep].append(name)
                    in_degree[name] += 1

        queue = [k for k, v in in_degree.items() if v == 0]
        order = []

        while queue:
            node = queue.pop(0)
            order.append(node)
            for neighbor in graph.get(node, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return order

    async def initialize_all_enabled(self) -> Dict[str, bool]:
        """Initializes all enabled modules in dependency order."""
        results = {}
        for name in self.get_topological_order():
            entry = self._declared_configs.get(name)
            if entry and entry.status in (FeatureStatus.ENABLED, FeatureStatus.INSTALLED):
                module = self._modules.get(name)
                if module:
                    deps_errors = self.validate_dependencies(name)
                    if deps_errors:
                        logger.error("Cannot start %s: %s", name, deps_errors)
                        results[name] = False
                        continue
                    try:
                        await module.initialize()
                        results[name] = True
                    except Exception as e:
                        logger.error("Initialization failed for %s: %s", name, e)
                        results[name] = False
        return results

    async def health_check_all(self) -> Dict[str, FeatureHealth]:
        """Queries health status across all registered modules."""
        health_reports = {}
        for name, module in self._modules.items():
            try:
                health = await module.health_check()
                health_reports[name] = health
            except Exception as e:
                health_reports[name] = FeatureHealth(
                    feature_name=name,
                    is_healthy=False,
                    status=module.status,
                    message=f"Health check error: {str(e)}",
                )
        return health_reports

    def list_all_capabilities(self) -> List[Dict[str, Any]]:
        """Collects all operational capabilities across active modules."""
        all_caps = []
        for name, module in self._modules.items():
            for cap in module.capabilities():
                all_caps.append({
                    "feature": name,
                    "capability": cap.name,
                    "description": cap.description,
                    "is_operational": cap.is_operational,
                })
        return all_caps

    def get_status_summary(self) -> Dict[str, Any]:
        """Returns structured capability & status overview for CLI reporting."""
        return {
            "declared_count": len(self._declared_configs),
            "registered_modules": list(self._modules.keys()),
            "features": {
                k: {
                    "version": v.version,
                    "status": v.status.value,
                    "dependencies": v.dependencies,
                    "description": v.description,
                }
                for k, v in self._declared_configs.items()
            },
        }
