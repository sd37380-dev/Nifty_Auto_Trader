"""
Hermes Integration & Compatibility Layer.

Provides stable adapter boundaries between NIFTY Autonomous Trader and the
official upstream Hermes Agent platform, isolating trading logic from Hermes
internal evolution.
"""

from nifty_trader.hermes.version import HermesVersionManager, HermesManifest
from nifty_trader.hermes.interfaces import (
    HermesAgentAdapter,
    HermesToolAdapter,
    HermesMemoryAdapter,
    HermesUpdateChecker,
)
from nifty_trader.hermes.adapter import HermesIntegrationAdapter
from nifty_trader.hermes.compatibility import HermesCompatibilityChecker
from nifty_trader.hermes.updater import HermesUpdateInspector

__all__ = [
    "HermesVersionManager",
    "HermesManifest",
    "HermesAgentAdapter",
    "HermesToolAdapter",
    "HermesMemoryAdapter",
    "HermesUpdateChecker",
    "HermesIntegrationAdapter",
    "HermesCompatibilityChecker",
    "HermesUpdateInspector",
]
