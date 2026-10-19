"""Organisations, members, invitations, compliance calendar and the module contract.

Access checks happen in ``routes.py`` (``require_org``) before any function here
runs. Every query on organisation data still filters by ``org_id``, so a
function can never return another tenant's rows even if called with a foreign id.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import secrets
import sqlite3
from typing import TYPE_CHECKING, Any

from ...calculators.common import Fields, money_str
from ...platform.access import ORG_ROLES, Forbidden, Principal
from ...platform.errors import Conflict, Invalid
from ...platform.identity import FORMATS
from ...platform.util import iso, mask, new_id, now, parse_iso, sha256

if TYPE_CHECKING:
    from ...services import Services

ENTITY_TYPES = ("company", "sole_proprietor", "partnership", "nonprofit", "government", "other")
# Organisation entity types the obligations engine understands (MODULES.md compliance contract).
FACT_ENTITY_TYPES = ("company", "sole_proprietor", "partnership", "nonprofit")
FACT_FLAGS = (
    "has_employees",
    "sells_taxable_supplies",
    "makes_wht_payments",
    "has_rental_income",
    "has_foreign_income",
    "has_capital_gains",
    "is_professional_services",
    "non_resident",
)
FACT_MONEY = ("annual_turnover", "fixed_assets")
FACT_INTS = ("employee_count",)
INVITE_TTL = dt.timedelta(days=7)
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Calendar status ladder (BIZ-01), derived from the linked return and receipts.
CALENDAR_STATUSES = ("not_started", "in_preparation", "submitted_for_review", "approved", "filed", "paid")


# ---------------------------------------------------------------- helpers
def _text(body: dict[str, Any], key: str, limit: int, *, required: bool = False) -> str | None:
    raw = body.get(key)
    value = "" if raw is None else str(raw).strip()
    if not value:
        if required:
            raise Invalid(f"{key}: is required")
        return None
    if len(value) > limit:
        raise Invalid(f"{key}: keep it under {limit} characters")
    return value


def _identifier(id_type: str, value: str | None) -> str | None:
    if value is None:
        return None
    clean = value.replace(" ", "")
    if not FORMATS[id_type].match(clean):
        raise Invalid(f"{'tin' if id_type == 'tin' else 'cac_number'}: not a valid {id_type.upper()} format")
    return clean.upper() if id_type == "cac" else clean


def org_row(services: Services, org_id: str) -> dict[str, Any]:
    row = services.db.one("SELECT * FROM organisations WHERE id = ?", (org_id,))
    if row is None:
        from ...api.router import NotFound

        raise NotFound("Organisation not found")
    return row


def facts_for(org: dict[str, Any]) -> dict[str, Any]:
    """Profile facts in the exact shape ``compliance.obligations_for`` expects."""
    stored = json.loads(org.get("profile_json") or "{}")
    facts: dict[str, Any] = {}
    for key in FACT_FLAGS:
        if isinstance(stored.get(key), bool):
            facts[key] = stored[key]
    for key in FACT_INTS:
        if isinstance(stored.get(key), int):
            facts[key] = stored[key]
    for key in FACT_MONEY:
        if stored.get(key) not in (None, ""):
            facts[key] = str(stored[key])
    if org.get("entity_type") in FACT_ENTITY_TYPES:
        facts["entity_type"] = org["entity_type"]
    if org.get("state"):
        facts["state"] = org["state"]
    return facts


def org_view(services: Services, org: dict[str, Any], role: str) -> dict[str, Any]:
    return {
        "id": org["id"],
        "name": org["name"],
        "entity_type": org["entity_type"],
        "tin": org["tin"],
        "cac_number": org["cac_number"],
        "state": org["state"],
        "facts": facts_for(org),
        "role": role,
        "created_at": org["created_at"],
        "verifications": services.identity.latest("organisation", org["id"]),
    }


# ------------------------------------------------------------ organisations
def create_org(services: Services, actor: Principal, body: dict[str, Any]) -> dict[str, Any]:
    name = _text(body, "name", 160, required=True)
    entity_type = str(body.get("entity_type") or "company")
    if entity_type not in ENTITY_TYPES:
        raise Invalid(f"entity_type: must be one of {', '.join(ENTITY_TYPES)}")
    tin = _identifier("tin", _text(body, "tin", 20))
    cac = _identifier("cac", _text(body, "cac_number", 20))
    state = _text(body, "state", 60)
    org_id = new_id("org")
    at = iso()
    with services.db.transaction():
        services.db.insert(
            "organisations",
            {
                "id": org_id,
                "name": name,
                "entity_type": entity_type,
                "tin": tin,
                "cac_number": cac,
                "state": state,
                "profile_json": "{}",
                "created_by": actor.user_id,
                "created_at": at,
            },
        )
        services.db.insert("memberships", {"org_id": org_id, "user_id": actor.user_id, "role": "owner", "created_at": at})
    services.audit.record("org.create", "organisation", org_id, actor_id=actor.user_id, org_id=org_id, data={"entity_type": entity_type})
    return org_view(services, org_row(services, org_id), "owner")


def update_org(services: Services, actor: Principal, org_id: str, body: dict[str, Any]) -> None:
    values: dict[str, Any] = {}
    if "name" in body:
        values["name"] = _text(body, "name", 160, required=True)
    if "entity_type" in body:
        if body["entity_type"] not in ENTITY_TYPES:
            raise Invalid(f"entity_type: must be one of {', '.join(ENTITY_TYPES)}")
        values["entity_type"] = body["entity_type"]
    if "tin" in body:
        values["tin"] = _identifier("tin", _text(body, "tin", 20))
    if "cac_number" in body:
        values["cac_number"] = _identifier("cac", _text(body, "cac_number", 20))
    if "state" in body:
        values["state"] = _text(body, "state", 60)
    if not values:
        raise Invalid("_: nothing to update")
    services.db.update("organisations", values, "id = ?", (org_id,))
    services.audit.record("org.update", "organisation", org_id, actor_id=actor.user_id, org_id=org_id, data={"fields": sorted(values)})


def update_facts(services: Services, actor: Principal, org_id: str, body: dict[str, Any]) -> None:
    """Replaces the stored profile facts. Only the contract keys are accepted."""
    unknown = sorted(set(body) - set(FACT_FLAGS) - set(FACT_MONEY) - set(FACT_INTS))
    if unknown:
        raise Invalid(f"{unknown[0]}: not a recognised profile fact")
    f = Fields(body)
    facts: dict[str, Any] = {}
    for key in FACT_FLAGS:
        if key in body:
            facts[key] = f.flag(key)
    for key in FACT_MONEY:
        if body.get(key) not in (None, ""):
            facts[key] = money_str(f.money(key))
    for key in FACT_INTS:
        if body.get(key) not in (None, ""):
            try:
                count = int(body[key])
            except (TypeError, ValueError):
                count = -1
            if not 0 <= count <= 10_000_000:
                f.errors[key] = "must be a whole number, zero or more"
            facts[key] = count
    f.finish()
    services.db.update("organisations", {"profile_json": json.dumps(facts, sort_keys=True)}, "id = ?", (org_id,))
    services.audit.record("org.facts_update", "organisation", org_id, actor_id=actor.user_id, org_id=org_id, data={"keys": sorted(facts)})


def verify_org_identifier(services: Services, actor: Principal, org_id: str, id_type: str) -> dict[str, Any]:
    org = org_row(services, org_id)
    column = {"tin": "tin", "cac": "cac_number"}.get(id_type)
    if column is None:
        raise Invalid("id_type: must be tin or cac")
    if not org[column]:
        raise Invalid(f"{column}: add the number to the organisation profile first")
    result = services.identity.verify("organisation", org_id, id_type, org[column])
    services.audit.record(
        "org.identity_check", "organisation", org_id, actor_id=actor.user_id, org_id=org_id, data={k: result[k] for k in ("id_type", "result", "mode")}
    )
    return result


def list_orgs(services: Services, actor: Principal) -> list[dict[str, Any]]:
    return services.db.query(
        "SELECT o.id, o.name, o.entity_type, o.state, m.role FROM memberships m JOIN organisations o ON o.id = m.org_id "
        "WHERE m.user_id = ? ORDER BY o.name",
        (actor.user_id,),
    )


# ------------------------------------------------------------------ members
def list_members(services: Services, org_id: str) -> list[dict[str, Any]]:
    return services.db.query(
        "SELECT u.id AS user_id, u.email, u.name, m.role, m.created_at FROM memberships m JOIN users u ON u.id = m.user_id "
        "WHERE m.org_id = ? ORDER BY m.created_at",
        (org_id,),
    )


def _membership(services: Services, org_id: str, user_id: str) -> dict[str, Any]:
    row = services.db.one("SELECT * FROM memberships WHERE org_id = ? AND user_id = ?", (org_id, user_id))
    if row is None:
        from ...api.router import NotFound

        raise NotFound("Member not found")
    return row


def _owner_count(services: Services, org_id: str) -> int:
    return int(services.db.scalar("SELECT COUNT(*) FROM memberships WHERE org_id = ? AND role = 'owner'", (org_id,)) or 0)


def change_role(services: Services, actor: Principal, org_id: str, user_id: str, role: str) -> None:
    if role not in ORG_ROLES:
        raise Invalid(f"role: must be one of {', '.join(ORG_ROLES)}")
    with services.db.transaction():
        member = _membership(services, org_id, user_id)
        if member["role"] == role:
            return
        if member["role"] == "owner" and _owner_count(services, org_id) <= 1:
            raise Conflict("An organisation must keep at least one owner. Make someone else an owner first.")
        services.db.update("memberships", {"role": role}, "org_id = ? AND user_id = ?", (org_id, user_id))
    services.audit.record(
        "member.role_change", "membership", user_id, actor_id=actor.user_id, org_id=org_id, data={"from": member["role"], "to": role}
    )


def remove_member(services: Services, actor: Principal, org_id: str, user_id: str) -> None:
    with services.db.transaction():
        member = _membership(services, org_id, user_id)
        if member["role"] == "owner" and _owner_count(services, org_id) <= 1:
            raise Conflict("The last owner cannot be removed. Make someone else an owner first.")
        services.db.execute("DELETE FROM memberships WHERE org_id = ? AND user_id = ?", (org_id, user_id))
    services.audit.record(
        "member.remove", "membership", user_id, actor_id=actor.user_id, org_id=org_id, data={"role": member["role"], "self": user_id == actor.user_id}
    )


# -------------------------------------------------------------- invitations
def invite(services: Services, actor: Principal, org_id: str, body: dict[str, Any]) -> dict[str, Any]:
    email = str(body.get("email") or "").strip().lower()
    role = str(body.get("role") or "")
    if not EMAIL.match(email) or len(email) > 254:
        raise Invalid("email: enter a valid email address")
    if role not in ORG_ROLES:
        raise Invalid(f"role: must be one of {', '.join(ORG_ROLES)}")
    existing = services.db.one(
        "SELECT 1 FROM memberships m JOIN users u ON u.id = m.user_id WHERE m.org_id = ? AND u.email = ?", (org_id, email)
    )
    if existing:
        raise Conflict("That person is already a member")
    org = org_row(services, org_id)
    token = secrets.token_urlsafe(32)
    at = now()
    invitation_id = new_id("inv")
    with services.db.transaction():
        # Re-inviting replaces any pending invitation for the same address.
        services.db.update(
            "invitations",
            {"revoked_at": iso(at)},
            "org_id = ? AND email = ? AND accepted_at IS NULL AND revoked_at IS NULL",
            (org_id, email),
        )
        services.db.insert(
            "invitations",
            {
                "id": invitation_id,
                "org_id": org_id,
                "email": email,
                "role": role,
                "token_hash": sha256(token),
                "created_by": actor.user_id,
                "created_at": iso(at),
                "expires_at": iso(at + INVITE_TTL),
            },
        )
    expires = (at + INVITE_TTL).date().isoformat()
    services.notifier.send(
        "email",
        email,
        f"You have been invited to join {org['name']} on tax.ng as {role.replace('_', ' ')}. "
        f"Sign in with this email address and open /app/#/invite/{token} to accept. The link expires on {expires}.",
        subject=f"Invitation to {org['name']} on tax.ng",
    )
    services.audit.record("member.invite", "invitation", invitation_id, actor_id=actor.user_id, org_id=org_id, data={"role": role})
    return {"id": invitation_id, "email": email, "role": role, "expires_at": iso(at + INVITE_TTL)}


def list_invitations(services: Services, org_id: str) -> list[dict[str, Any]]:
    return services.db.query(
        "SELECT id, email, role, created_at, expires_at FROM invitations "
        "WHERE org_id = ? AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at > ? ORDER BY created_at DESC",
        (org_id, iso()),
    )


def revoke_invitation(services: Services, actor: Principal, org_id: str, invitation_id: str) -> None:
    changed = services.db.update(
        "invitations", {"revoked_at": iso()}, "id = ? AND org_id = ? AND accepted_at IS NULL AND revoked_at IS NULL", (invitation_id, org_id)
    )
    if not changed:
        from ...api.router import NotFound

        raise NotFound("Invitation not found")
    services.audit.record("member.invite_revoke", "invitation", invitation_id, actor_id=actor.user_id, org_id=org_id)


def accept_invitation(services: Services, actor: Principal, token: str) -> dict[str, Any]:
    if not token or len(token) > 200:
        raise Invalid("token: invitation link is invalid")
    with services.db.transaction():
        inv = services.db.one("SELECT * FROM invitations WHERE token_hash = ?", (sha256(token),))
        if inv is None or inv["revoked_at"] or inv["accepted_at"]:
            raise Invalid("token: invitation link is invalid or has already been used")
        if parse_iso(inv["expires_at"]) < now():
            raise Invalid("token: invitation has expired. Ask the owner to invite you again")
        if inv["email"] != actor.email.lower():
            raise Forbidden("This invitation was sent to a different email address. Sign in with that address to accept it.")
        try:
            services.db.insert("memberships", {"org_id": inv["org_id"], "user_id": actor.user_id, "role": inv["role"], "created_at": iso()})
        except sqlite3.IntegrityError:
            raise Conflict("You are already a member of this organisation") from None
        services.db.update("invitations", {"accepted_at": iso()}, "id = ?", (inv["id"],))
    services.audit.record("member.join", "invitation", inv["id"], actor_id=actor.user_id, org_id=inv["org_id"], data={"role": inv["role"]})
    org = org_row(services, inv["org_id"])
    return {"org_id": org["id"], "name": org["name"], "role": inv["role"]}


# ----------------------------------------------------------------- calendar
def suggested_return_type(obligation: dict[str, Any]) -> str | None:
    tax = str(obligation.get("tax") or "").lower()
    frequency = str(obligation.get("frequency") or "").lower()
    if frequency.startswith("month"):
        return {"vat": "vat_monthly", "wht": "wht_monthly", "paye": "paye_monthly", "pit": "paye_monthly"}.get(tax)
    if frequency.startswith(("annual", "year")) and tax == "cit":
        return "cit_annual"
    return None


def obligations(services: Services, org: dict[str, Any], year: int) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Returns ``(items, notice)``. ``items`` is None when the calendar is unavailable."""
    compliance = services.modules.get("compliance")
    if compliance is None or not callable(getattr(compliance, "obligations_for", None)):
        return None, "The compliance calendar is not available yet. Returns can still be prepared manually."
    try:
        items = compliance.obligations_for(facts_for(org), year)
    except Exception:  # noqa: BLE001 (another module's failure must not break the workspace)
        return None, "The compliance calendar could not be worked out for this profile. Returns can still be prepared manually."
    return list(items or []), None


def find_obligation(services: Services, org: dict[str, Any], obligation_id: str, period: str, year: int) -> dict[str, Any]:
    for y in (year, year + 1):
        items, notice = obligations(services, org, y)
        if items is None:
            raise Invalid(f"obligation_id: {notice}")
        for item in items:
            if str(item.get("id")) == obligation_id and str(item.get("period")) == period:
                return item
    raise Invalid("obligation_id: no such obligation for this organisation's profile")


def calendar(services: Services, org_id: str, year: int) -> dict[str, Any]:
    from .filing import reconciliation

    org = org_row(services, org_id)
    items, notice = obligations(services, org, year)
    if items is None:
        return {"available": False, "notice": notice, "year": year, "items": []}
    linked = {
        (r["obligation_id"], r["obligation_period"]): r
        for r in services.db.query("SELECT * FROM ws_returns WHERE org_id = ? AND obligation_id IS NOT NULL", (org_id,))
    }
    today = dt.date.today().isoformat()
    out = []
    for item in sorted(items, key=lambda i: str(i.get("due_date") or "")):
        ret = linked.get((str(item.get("id")), str(item.get("period"))))
        status, payment = "not_started", None
        if ret:
            payment = reconciliation(services, ret)
            status = {
                "draft": "in_preparation",
                "changes_requested": "in_preparation",
                "submitted_for_review": "submitted_for_review",
                "approved": "approved",
                "filed_sandbox": "approved",  # a sandbox acknowledgement is not a filing
                "filed": "filed",
            }[ret["status"]]
            if ret["status"] == "filed" and payment["status"] in ("paid", "overpaid"):
                status = "paid"
        out.append(
            {
                **item,
                "status": status,
                "return_id": ret["id"] if ret else None,
                "return_status": ret["status"] if ret else None,
                "sandbox_acknowledged": bool(ret and ret["status"] == "filed_sandbox"),
                "payment": payment,
                "suggested_return_type": suggested_return_type(item),
                "overdue": bool(item.get("due_date")) and str(item["due_date"]) < today and status not in ("filed", "paid"),
            }
        )
    return {"available": True, "notice": None, "year": year, "items": out}


# ----------------------------------------------------------- module contract
class WorkspaceService:
    """``services.modules["workspace"]`` (MODULES.md cross-module contract)."""

    def __init__(self, services: Services) -> None:
        self.services = services

    def facts(self, org_id: str) -> dict[str, Any]:
        return facts_for(org_row(self.services, org_id))

    def org_summary(self, org_id: str) -> dict[str, Any]:
        """Profile facts, open returns by status and upcoming obligations. No raw identifiers."""
        org = org_row(self.services, org_id)
        counts = self.services.db.query(
            "SELECT status, COUNT(*) AS n FROM ws_returns WHERE org_id = ? AND status <> 'filed' GROUP BY status", (org_id,)
        )
        today = dt.date.today()
        cal = calendar(self.services, org_id, today.year)
        upcoming = [
            {k: i.get(k) for k in ("id", "tax", "title", "period", "due_date", "status", "return_id", "review_status")}
            for i in cal["items"]
            if str(i.get("due_date") or "") >= today.isoformat() and i["status"] not in ("filed", "paid")
        ][:5]
        return {
            "org": {
                "id": org["id"],
                "name": org["name"],
                "entity_type": org["entity_type"],
                "state": org["state"],
                "tin_masked": mask(org["tin"]) if org["tin"] else None,
            },
            "facts": facts_for(org),
            "open_returns": {r["status"]: r["n"] for r in counts},
            "upcoming_obligations": upcoming,
            "calendar_available": cal["available"],
            "calendar_notice": cal["notice"],
        }


__all__ = ["CALENDAR_STATUSES", "WorkspaceService"]
