"""Demo data: ``python -m taxng seed`` (demo mode only).

Creates staff accounts, a taxpayer, a business workspace with a team, a VAT
return awaiting review and an approved adviser, all through the real API
handlers so every rule and audit entry applies. Sign in as any account below;
in demo mode the sign-in code appears on screen.

    admin@demo.tax.ng     platform admin        editor@demo.tax.ng   editor
    legal@demo.tax.ng     legal reviewer        sales@demo.tax.ng    sales
    support@demo.tax.ng   support               ada@demo.tax.ng      taxpayer, owner of Zuma Foods Ltd
    musa@demo.tax.ng      preparer              ngozi@demo.tax.ng    reviewer
    chidi@demo.tax.ng     listed tax adviser
"""

from __future__ import annotations

import re
from typing import Any

from .api.router import CSRF_VALUE, Reply, Request, dispatch
from .platform.util import iso
from .services import Services

STAFF = {
    "admin@demo.tax.ng": "admin",
    "editor@demo.tax.ng": "editor",
    "legal@demo.tax.ng": "legal_reviewer",
    "sales@demo.tax.ng": "sales",
    "support@demo.tax.ng": "support",
}


class _Client:
    def __init__(self, services: Services, email: str) -> None:
        self.services = services
        self.cookies: dict[str, str] = {}
        self.call("POST", "/api/auth/request-code", {"email": email})
        body = services.notifier.recent(email, limit=1)[0]["body"]
        code = re.search(r"\b\d{6}\b", body)
        assert code, "sign-in code not found in outbox"
        reply = self.call("POST", "/api/auth/verify", {"email": email, "code": code.group(0)})
        assert reply.status == 200, reply.body
        self.user_id = self.call("GET", "/api/me").body["id"]

    def call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Reply:
        headers = {"x-requested-with": CSRF_VALUE} if self.cookies else {}
        reply = dispatch(self.services, Request(method, path, {}, body or {}, headers, dict(self.cookies)))
        for c in reply.cookies:
            self.cookies[c.name] = c.value
        return reply


def _step(log: list[str], label: str, reply: Reply, ok: tuple[int, ...] = (200, 201)) -> Any:
    if reply.status in ok:
        log.append(f"ok    {label}")
        return reply.body
    log.append(f"skip  {label}: HTTP {reply.status} {reply.body}")
    return None


def seed(services: Services) -> list[str]:
    if not services.demo_mode:
        raise SystemExit("Seeding is only allowed in demo mode (TAXNG_DEMO=1).")
    if services.db.one("SELECT 1 FROM users WHERE email = ?", ("admin@demo.tax.ng",)):
        return ["Demo data already present; nothing to do."]
    log: list[str] = []

    for email, role in STAFF.items():
        _Client(services, email)
        services.db.update("users", {"staff_role": role}, "email = ?", (email,))
        log.append(f"ok    staff {email} ({role})")

    ada = _Client(services, "ada@demo.tax.ng")
    ada.call("POST", "/api/me", {"name": "Ada Okafor", "ai_account_access": True})
    _step(log, "Ada's tax profile", ada.call("PUT", "/api/compliance/profile", {"facts": {
        "entity_type": "individual", "state": "Lagos", "has_employment_income": True,
        "has_rental_income": True, "has_business_income": False, "has_foreign_income": False,
    }}))

    org = _step(log, "workspace Zuma Foods Ltd", ada.call("POST", "/api/orgs", {
        "name": "Zuma Foods Ltd", "entity_type": "company", "tin": "12345678-0001", "cac_number": "RC1234567", "state": "Lagos",
    }))
    if org:
        org_id = org["id"]
        _step(log, "Zuma Foods profile facts", ada.call("PUT", f"/api/orgs/{org_id}/facts", {
            "has_employees": True, "employee_count": 12, "annual_turnover": "180000000", "fixed_assets": "90000000",
            "sells_taxable_supplies": True, "makes_wht_payments": True, "non_resident": False,
        }))
        musa = _Client(services, "musa@demo.tax.ng")
        ngozi = _Client(services, "ngozi@demo.tax.ng")
        for client, role in ((musa, "preparer"), (ngozi, "reviewer")):
            services.db.insert("memberships", {"org_id": org_id, "user_id": client.user_id, "role": role, "created_at": iso()})
            services.audit.record("membership.seeded", "organisation", org_id, actor_id=ada.user_id, org_id=org_id, data={"role": role})
            log.append(f"ok    {role} joined Zuma Foods Ltd")
        musa.call("POST", "/api/me", {"name": "Musa Bello"})
        ngozi.call("POST", "/api/me", {"name": "Ngozi Eze"})
        ret = _step(log, "VAT return 2026-09", musa.call("POST", f"/api/orgs/{org_id}/returns", {"return_type": "vat_monthly", "period": "2026-09"}))
        if ret:
            base = f"/api/orgs/{org_id}/returns/{ret['id']}"
            for kind, amount, ref in (("output", "4500000", "INV-0912"), ("output", "1250000", "INV-0915"), ("input", "800000", "SUP-0420")):
                _step(log, f"  {kind} line {ref}", musa.call("POST", f"{base}/lines", {
                    "kind": kind, "details": {"invoice_ref": ref, "counterparty": "Demo counterparty"},
                    "inputs": {"supply_date": "2026-09-10", "amount": amount, "category": "standard"},
                }))
            _step(log, "  submitted for review", musa.call("POST", f"{base}/submit"))

    chidi = _Client(services, "chidi@demo.tax.ng")
    adviser = _step(log, "adviser application (Chidi Nwosu)", chidi.call("POST", "/api/advisory/advisers", {
        "name": "Chidi Nwosu", "firm": "Nwosu & Partners (sample)", "location": "Ikeja", "state": "Lagos",
        "specialisms": ["vat", "paye"], "citn_number": "CITN/12345", "bio": "Sample adviser profile for the demo.",
    }))
    if adviser:
        admin = _Client(services, "admin@demo.tax.ng")
        _step(log, "adviser approved by staff", admin.call("POST", f"/api/advisory/admin/advisers/{adviser['id']}/decision", {"decision": "approve"}))
    return log
