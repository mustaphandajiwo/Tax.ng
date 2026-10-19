"""Business workspaces (PRD Phase 3) and authorised filing (Phase 4).

Registers the ``filing`` adapter kind and sets ``services.modules["workspace"]``
(contract: ``org_summary(org_id)``). See docs/MODULES.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .adapters import ProductionNrsFiling, SandboxNrsFiling
from .service import WorkspaceService

if TYPE_CHECKING:
    from ...services import Services


def init(services: Services) -> None:
    services.adapters.register(SandboxNrsFiling, ProductionNrsFiling)
    services.modules["workspace"] = WorkspaceService(services)
