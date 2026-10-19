"""Navigation and feature visibility by phase (PRD section 5).

One list drives the public header, the public footer and the signed-in app.
An item that depends on an integration appears only when that integration's
adapter is authorised. "File & Pay" therefore stays hidden while filing runs in
sandbox mode, as the PRD requires.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .services import Services


@dataclass(frozen=True)
class Feature:
    id: str
    label: str
    path: str
    phase: int
    placement: str  # "header" | "footer" | "app"
    requires_adapter: str | None = None  # adapter kind that must be authorised
    staff_only: bool = False


FEATURES: list[Feature] = [
    # Public header
    Feature("reform", "New Tax Law 2026", "/reform", 1, "header"),
    Feature("calculators", "Calculators", "/calculators", 1, "header"),
    Feature("health-check", "Check My Tax Health", "/health-check", 2, "header"),
    Feature("advisers", "Find an Adviser", "/advisers", 2, "header"),
    Feature("laws", "Laws & Regulations", "/laws", 1, "header"),
    Feature("news", "Tax News", "/news", 1, "header"),
    Feature("ask", "Ask Tax AI", "/ask", 1, "header"),
    Feature("academy", "Academy", "/academy", 3, "header"),
    Feature("file-pay", "File & Pay", "/file-pay", 4, "header", requires_adapter="filing"),
    # Public footer
    Feature("insights", "Insights & Articles", "/insights", 3, "footer"),
    Feature("business", "Business Solutions", "/business", 3, "footer"),
    Feature("newsletter", "Newsletter", "/newsletter", 1, "footer"),
    Feature("contribute", "Contribute", "/contribute", 3, "footer"),
    Feature("advertise", "Advertise", "/advertise", 3, "footer"),
    Feature("developers", "Developers & API", "/developers", 4, "footer"),
    Feature("whatsapp", "tax.ng on WhatsApp", "/whatsapp", 3, "footer"),
    Feature("languages", "Languages", "/languages", 3, "footer"),
    Feature("about", "About & Ownership", "/about", 1, "footer"),
    # Signed-in app (served at /app)
    Feature("app-home", "Dashboard", "/", 2, "app"),
    Feature("app-compliance", "My tax health", "/compliance", 2, "app"),
    Feature("app-ask", "Ask Tax AI", "/ask", 4, "app"),
    Feature("app-advisory", "Advisers & bookings", "/advisory", 2, "app"),
    Feature("app-workspaces", "Business workspaces", "/workspaces", 3, "app"),
    Feature("app-einvoicing", "E-invoicing", "/einvoicing", 3, "app"),
    Feature("app-filing", "Filing", "/filing", 4, "app"),
    Feature("app-billing", "Billing", "/billing", 3, "app"),
    Feature("app-integrations", "Integrations & API", "/integrations", 4, "app"),
    Feature("app-academy", "My learning", "/learning", 3, "app"),
    Feature("app-publishing", "Publishing", "/publishing", 3, "app"),
    Feature("app-channels", "Channels", "/channels", 3, "app", staff_only=True),
    Feature("app-translations", "Translations", "/staff/translations", 3, "app", staff_only=True),
    Feature("app-staff", "Staff", "/staff", 1, "app", staff_only=True),
    Feature("app-account", "Account", "/account", 2, "app"),
]


def nav_for(services: Services, placement: str) -> list[dict[str, Any]]:
    items = []
    for f in FEATURES:
        if f.placement != placement:
            continue
        if f.requires_adapter and not services.adapters.is_authorised(f.requires_adapter):
            continue
        items.append(asdict(f))
    return items
