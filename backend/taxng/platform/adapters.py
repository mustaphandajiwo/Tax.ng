"""External integrations behind adapters, each with a sandbox and a production form.

Every third-party dependency in the PRD (NRS filing and e-invoicing, payment
provider, identity verification, professional registers, messaging) has an
adapter kind. The demo registers sandbox adapters, which behave
deterministically and label every result ``mode = "sandbox"``. Production
adapters exist as classes that raise ``NotConfigured`` until credentials,
accreditation and written authorisation are in place.

Two rules follow from the PRD and are enforced by callers:

* A sandbox result is never presented as a real filing, payment or
  verification. Responses carry the adapter mode.
* "File & Pay" appears in public navigation only when an authorised production
  filing adapter is registered (PRD section 5).

Select modes with environment variables, e.g. ``TAXNG_ADAPTER_FILING=production``.
"""

from __future__ import annotations

import os
from typing import Any, NoReturn


class NotConfigured(RuntimeError):
    """A production adapter was used before it was configured and authorised."""


class Adapter:
    kind: str = "generic"
    name: str = "adapter"
    mode: str = "sandbox"  # "sandbox" | "production"
    description: str = ""

    @property
    def authorised(self) -> bool:
        """True only for a configured production adapter."""
        return self.mode == "production" and self.is_configured()

    def is_configured(self) -> bool:
        return False

    def not_configured(self, needs: str) -> NoReturn:
        raise NotConfigured(f"{self.name} is not configured: needs {needs}")

    def info(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "mode": self.mode,
            "authorised": self.authorised,
            "description": self.description,
        }


class AdapterRegistry:
    """Holds one adapter per kind. Modules register sandbox and production classes."""

    def __init__(self) -> None:
        self._classes: dict[str, dict[str, type[Adapter]]] = {}
        self._instances: dict[str, Adapter] = {}

    def register(self, sandbox: type[Adapter], production: type[Adapter]) -> None:
        kind = sandbox.kind
        if production.kind != kind:
            raise ValueError("sandbox and production adapters must share a kind")
        self._classes[kind] = {"sandbox": sandbox, "production": production}
        self._instances.pop(kind, None)

    def get(self, kind: str) -> Adapter:
        if kind not in self._instances:
            classes = self._classes.get(kind)
            if classes is None:
                raise KeyError(f"No adapter registered for {kind!r}")
            mode = os.environ.get(f"TAXNG_ADAPTER_{kind.upper()}", "sandbox")
            self._instances[kind] = classes.get(mode, classes["sandbox"])()
        return self._instances[kind]

    def kinds(self) -> list[str]:
        return sorted(self._classes)

    def info(self) -> list[dict[str, Any]]:
        return [self.get(k).info() for k in self.kinds()]

    def is_authorised(self, kind: str) -> bool:
        return kind in self._classes and self.get(kind).authorised
