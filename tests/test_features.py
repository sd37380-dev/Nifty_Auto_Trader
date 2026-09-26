"""
Tests for Feature Extension Framework, Registry, and Migrations.
"""

from pathlib import Path
import pytest

from nifty_trader.features.base import (
    FeatureCapability,
    FeatureHealth,
    FeatureModule,
    FeatureStatus,
)
from nifty_trader.features.manifest import ReleaseManifestManager
from nifty_trader.features.migrations import (
    BaseMigration,
    ConfigMigrationManager,
    DatabaseMigrationManager,
)
from nifty_trader.features.registry import FeatureRegistry


class DummyMarketDataModule(FeatureModule):
    def __init__(self):
        super().__init__(
            name="market_data",
            version="0.1.0",
            status=FeatureStatus.PLANNED,
            dependencies=[],
        )

    async def initialize(self) -> None:
        pass

    async def start(self) -> None:
        self._is_started = True

    async def stop(self) -> None:
        self._is_started = False

    async def health_check(self) -> FeatureHealth:
        return FeatureHealth(
            feature_name=self.name,
            is_healthy=True,
            status=self.status,
            message="Planned placeholder",
        )

    def capabilities(self) -> list[FeatureCapability]:
        return [
            FeatureCapability(name="candles_1h", description="1H candle stream", is_operational=False)
        ]


def test_feature_registry_loading():
    """Verify feature registry loads config/features.yaml."""
    registry = FeatureRegistry()
    declarations = registry.load_declarations()

    assert "model_router" in declarations
    assert "gemini_brain" in declarations
    assert "browser" in declarations
    assert "market_data" in declarations
    assert "live_broker" in declarations

    assert declarations["browser"].status == FeatureStatus.ENABLED
    assert declarations["market_data"].status == FeatureStatus.ENABLED
    assert declarations["live_broker"].status == FeatureStatus.DISABLED


def test_feature_dependency_validation():
    """Verify dependency graph catches missing or disabled dependencies."""
    registry = FeatureRegistry()

    # Browser depends on model_router (both enabled) -> OK
    assert registry.can_start_feature("browser") is True

    # risk_engine depends on strategy_engine (which is PLANNED, not ENABLED) -> Cannot start
    errors = registry.validate_dependencies("risk_engine")
    assert len(errors) > 0
    assert any("strategy_engine" in err for err in errors)
    assert registry.can_start_feature("risk_engine") is False


def test_feature_topological_sort():
    """Verify features resolve in valid dependency order."""
    registry = FeatureRegistry()
    order = registry.get_topological_order()

    assert "model_router" in order
    assert "gemini_brain" in order
    # model_router must precede gemini_brain
    assert order.index("model_router") < order.index("gemini_brain")


def test_config_migration_manager():
    """Verify sequential schema migrations for configurations."""
    mgr = ConfigMigrationManager()

    class Migration1To2(BaseMigration):
        def __init__(self):
            super().__init__("1.0.0", "1.1.0", "Add chart layout settings")

        def apply(self, data: dict) -> dict:
            upgraded = dict(data)
            upgraded["chart_layout"] = {"theme": "dark", "grid": True}
            return upgraded

    mgr.register_migration(Migration1To2())

    old_config = {"schema_version": "1.0.0", "symbol": "NIFTY"}
    migrated = mgr.migrate(old_config, target_version="1.1.0")

    assert migrated["schema_version"] == "1.1.0"
    assert migrated["chart_layout"] == {"theme": "dark", "grid": True}
    assert migrated["symbol"] == "NIFTY"


def test_database_migration_preservation_invariants():
    """Verify migrations cannot drop or truncate whitelisted memory/journal tables."""
    db_mgr = DatabaseMigrationManager(current_db_version="1.0.0")

    # Safe migration: adding a column
    safe_script = "ALTER TABLE trade_history ADD COLUMN slippage_pts REAL;"
    assert db_mgr.verify_preservation_rules(safe_script) is True

    # Destructive script: dropping trade_history -> REJECTED
    malicious_script = "DROP TABLE trade_history;"
    assert db_mgr.verify_preservation_rules(malicious_script) is False

    # Destructive script: truncating experience_journal -> REJECTED
    truncate_script = "TRUNCATE experience_journal;"
    assert db_mgr.verify_preservation_rules(truncate_script) is False


def test_release_manifest_generation():
    """Verify release manifest generation and loading."""
    manifest_mgr = ReleaseManifestManager()
    manifest = manifest_mgr.load()

    assert manifest.product_name == "NIFTY Autonomous Trader"
    assert manifest.product_version == "0.1.0"
    assert manifest.hermes_commit.startswith("d0288be5")
    assert manifest.hermes_verified is True
    assert manifest.components.model_router_version == "1.0.0"
    assert manifest.components.browser_version == "1.0.0"
    assert manifest.components.market_data_version == "1.0.0"
    assert manifest.components.strategy_version == "UNINSTALLED"
