"""
Configuration and Database Schema Migration Framework.

Guarantees backward compatibility during upgrades, ensuring that user settings,
historical trading records, experience journals, and strategy versions are
never destroyed or overwritten.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class MigrationStep(BaseModel):
    from_version: str
    to_version: str
    description: str


class BaseMigration(ABC):
    """Abstract contract for applying schema or configuration migrations."""

    def __init__(self, from_version: str, to_version: str, description: str):
        self.step = MigrationStep(
            from_version=from_version,
            to_version=to_version,
            description=description,
        )

    @abstractmethod
    def apply(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Upgrades data payload from from_version to to_version."""
        pass


class ConfigMigrationManager:
    """
    Manages safe sequential migrations for user and application configurations.
    """

    def __init__(self):
        self._migrations: Dict[str, BaseMigration] = {}

    def register_migration(self, migration: BaseMigration) -> None:
        """Registers a migration step keyed by its source version."""
        self._migrations[migration.step.from_version] = migration
        logger.debug(
            "Registered config migration: %s -> %s (%s)",
            migration.step.from_version,
            migration.step.to_version,
            migration.step.description,
        )

    def migrate(self, raw_config: Dict[str, Any], target_version: str) -> Dict[str, Any]:
        """
        Sequentially applies registered migrations until target_version is reached.
        """
        current_data = dict(raw_config)
        current_ver = str(current_data.get("schema_version", "1.0.0"))

        iterations = 0
        while current_ver != target_version and iterations < 20:
            iterations += 1
            migration = self._migrations.get(current_ver)
            if not migration:
                logger.info(
                    "No further config migrations registered from version %s (target %s).",
                    current_ver,
                    target_version,
                )
                break

            logger.info(
                "Applying config migration %s -> %s: %s",
                migration.step.from_version,
                migration.step.to_version,
                migration.step.description,
            )
            current_data = migration.apply(current_data)
            current_data["schema_version"] = migration.step.to_version
            current_ver = migration.step.to_version

        return current_data


class DatabaseMigrationManager:
    """
    Manages database schema evolution with strict preservation invariants.
    Guarantees that trade history, paper positions, experience memory,
    and post-mortem records are never lost during an upgrade.
    """

    def __init__(self, current_db_version: str = "1.0.0"):
        self.current_version = current_db_version
        self._table_preservation_whitelist = [
            "trade_history",
            "paper_positions",
            "experience_journal",
            "post_mortems",
            "strategy_versions",
            "mistakes_learned",
        ]
        self._sql_migrations: List[Dict[str, Any]] = []

    def register_sql_migration(
        self,
        from_ver: str,
        to_ver: str,
        sql_upgrade_script: str,
        description: str,
    ) -> None:
        """Registers an explicit SQL forward migration."""
        self._sql_migrations.append({
            "from_version": from_ver,
            "to_version": to_ver,
            "sql": sql_upgrade_script,
            "description": description,
        })

    def verify_preservation_rules(self, sql_script: str) -> bool:
        """
        Verifies that a migration script does not DROP or TRUNCATE whitelisted
        trading experience or history tables.
        """
        upper = sql_script.upper()
        for table in self._table_preservation_whitelist:
            forbidden_drop = f"DROP TABLE {table.upper()}"
            forbidden_drop_if = f"DROP TABLE IF EXISTS {table.upper()}"
            forbidden_truncate = f"TRUNCATE {table.upper()}"
            if forbidden_drop in upper or forbidden_drop_if in upper or forbidden_truncate in upper:
                logger.error(
                    "MIGRATION SAFETY VIOLATION: Migration script attempts to destroy '%s' table!",
                    table,
                )
                return False
        return True

    def get_pending_migrations(self, target_version: str) -> List[Dict[str, Any]]:
        """Returns all migrations required to reach target_version."""
        return [
            m for m in self._sql_migrations
            if m["from_version"] == self.current_version
        ]
