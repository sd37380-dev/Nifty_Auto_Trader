"""
Hermes Integration & Collaborative Orchestration Layer.

Provides stable adapter boundaries between NIFTY Autonomous Trader and the
official upstream Hermes Agent platform, isolating trading logic from Hermes
internal evolution, and coordinates collaborative trading cycles with the AI Brain.
"""

from nifty_trader.hermes.adapter import HermesIntegrationAdapter
from nifty_trader.hermes.collaboration import HermesBrainOrchestrator
from nifty_trader.hermes.compatibility import HermesCompatibilityChecker
from nifty_trader.hermes.contracts import (
    CollaborationAuditStore,
    CollaborationCycle,
    CollaborationTurn,
    ContextItem,
    ContextSource,
)
from nifty_trader.hermes.interfaces import (
    HermesAgentAdapter,
    HermesMemoryAdapter,
    HermesToolAdapter,
    HermesUpdateChecker,
)
from nifty_trader.hermes.tool_bridge import HermesToolBridge
from nifty_trader.hermes.updater import HermesUpdateInspector
from nifty_trader.hermes.version import HermesManifest, HermesVersionManager

__all__ = [
    "CollaborationAuditStore",
    "CollaborationCycle",
    "CollaborationTurn",
    "ContextItem",
    "ContextSource",
    "HermesAgentAdapter",
    "HermesBrainOrchestrator",
    "HermesCompatibilityChecker",
    "HermesIntegrationAdapter",
    "HermesManifest",
    "HermesMemoryAdapter",
    "HermesToolAdapter",
    "HermesToolBridge",
    "HermesUpdateChecker",
    "HermesUpdateInspector",
    "HermesVersionManager",
]
