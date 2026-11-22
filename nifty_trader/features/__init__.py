"""
Future Feature Extension Framework.

Provides modular contracts, lifecycle management, capability discovery,
and schema migration utilities for extending NIFTY Autonomous Trader safely.
"""

from nifty_trader.features.base import FeatureModule, FeatureStatus, FeatureCapability
from nifty_trader.features.registry import FeatureRegistry
from nifty_trader.features.migrations import (
    ConfigMigrationManager,
    DatabaseMigrationManager,
    MigrationStep,
)
from nifty_trader.features.manifest import ReleaseManifestManager
from nifty_trader.features.volume_candles import VolumeBar, VolumeBarAggregator
from nifty_trader.features.volume_signals import VolumePatternDetector

__all__ = [
    "FeatureModule",
    "FeatureStatus",
    "FeatureCapability",
    "FeatureRegistry",
    "ConfigMigrationManager",
    "DatabaseMigrationManager",
    "MigrationStep",
    "ReleaseManifestManager",
    "VolumeBar",
    "VolumeBarAggregator",
    "VolumePatternDetector",
]
