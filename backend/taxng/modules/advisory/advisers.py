"""Adviser listings, register verification, the public directory and paid placement (ADV-01, ADV-04).

Lifecycle of a listing (``status``):

    pending  --staff approve-->  approved  --staff suspend-->  suspended
       |                           ^                              |
       +--staff reject--> rejected +--------staff approve---------+

Approval needs a current verified register check. Changing a membership
number sends the listing back to ``pending`` and re-runs verification.

Verification (``register`` adapter) is separate from approval: the "Verified"
badge is shown only while the latest successful check is younger than
:data:`~.policy.REVERIFY_AFTER`, with its date and mode. A sandbox check is
always labelled as such.

Directory order (ADV-04) depends only on relevance to the search (specialism
match, then state match) and the adviser's name. Paid placement never changes
it: an active placement is shown in a separate, labelled "Sponsored listing"
slot.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from ...api.router import NotFound
from ...platform.errors import Conflict, Invalid
from ...platform.util import iso, mask, new_id, now, parse_iso
from .adapters import REGISTERS
from .policy import REVERIFY_AFTER, SPECIALISMS, STATES

if TYPE_CHECKING:
    from ...services import Services

MEMBERSHIP = re.compile(r"^[A-Za-z0-9/\-]{3,20}$")
PLACEMENT_PREFIX = "plc"
DECISIONS = {"approve": "approved", "reject": "rejected", "suspend": "suspended"}
ALLOWED_FROM = {"approve": ("pending", "suspended"), "reject": ("pending",), "suspend": ("approved",)}


def _text(body: dict[str, Any], key: str, *, required: bool = False, limit: int = 120) -> str:
    value = str(body.get(key) or "").strip()
    if required and not value:
        raise Invalid(f"{key}: is required")
    if len(value) > limit:
        raise Invalid(f"{key}: keep it under {limit} characters")
    return value


class Advisers:
    def __init__(self, services: Services) -> None:
        self.services = services
        self.db = services.db

    # ------------------------------------------------------------------ input
    def _parse(self, body: dict[str, Any], *, partial: bool, current: dict[str, Any] | None = None) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for key, limit in (("name", 120), ("firm", 120), ("location", 80), ("bio", 1500)):
            if not partial or key in body:
                values[key] = _text(body, key, required=key == "name", limit=limit)
        if not partial or "state" in body:
            state = body.get("state")
            if state not in STATES:
                raise Invalid("state: choose a Nigerian state or FCT")
            values["state"] = state
        if not partial or "specialisms" in body:
            specs = body.get("specialisms")
            if not isinstance(specs, list) or not specs or any(s not in SPECIALISMS for s in specs):
                raise Invalid(f"specialisms: choose one or more of {', '.join(SPECIALISMS)}")
            values["specialisms_json"] = json.dumps(sorted(set(specs)))
        for reg in REGISTERS:
            key = f"{reg}_number"
            if not partial or key in body:
                raw = str(body.get(key) or "").strip().upper()
                if raw and not MEMBERSHIP.match(raw):
                    raise Invalid(f"{key}: use letters, digits, / or - only")
                values[key] = raw or None
        merged = {**(current or {}), **values}
        if not merged.get("citn_number") and not merged.get("ican_number"):
            raise Invalid("citn_number: give a CITN or ICAN membership number")
        return values

    # ------------------------------------------------------------------ reads
    def row(self, adviser_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM advisory_advisers WHERE id = ?", (adviser_id,))
        if not row:
            raise NotFound("Adviser not found")
        return row

    def for_user(self, user_id: str) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM advisory_advisers WHERE user_id = ?", (user_id,))

    def mine(self, user_id: str) -> dict[str, Any]:
        row = self.for_user(user_id)
        if not row:
            raise NotFound("You do not have an adviser listing")
        return row

    def verification(self, adviser_id: str) -> dict[str, Any]:
        """Badge state from the latest check per register (ADV-01)."""
        checks = self.db.query(
            "SELECT register, number_masked, provider, mode, result, checked_at, expires_at FROM advisory_verifications "
            "WHERE adviser_id = ? ORDER BY checked_at DESC, rowid DESC",
            (adviser_id,),
        )
        latest: dict[str, dict[str, Any]] = {}
        for c in checks:
            latest.setdefault(c["register"], c)
        moment = now()
        current = [c for c in latest.values() if c["result"] == "verified" and c["expires_at"] and parse_iso(c["expires_at"]) > moment]
        expired = [c for c in latest.values() if c["result"] == "verified" and c not in current]
        if current:
            best = max(current, key=lambda c: c["checked_at"])
            status = "verified"
        elif expired:
            best, status = max(expired, key=lambda c: c["checked_at"]), "expired"
        else:
            best, status = None, "not_verified"
        return {
            "status": status,
            "checked_at": best["checked_at"] if best else None,
            "expires_at": best["expires_at"] if best else None,
            "mode": best["mode"] if best else None,
            "registers": [REGISTERS[c["register"]] for c in current],
            "checks": list(latest.values()),
        }

    def owner_view(self, row: dict[str, Any]) -> dict[str, Any]:
        """The adviser's own view of their listing (includes full membership numbers)."""
        return {
            **{k: row[k] for k in ("id", "name", "firm", "state", "location", "bio", "status", "review_note", "created_at", "updated_at")},
            "citn_number": row["citn_number"],
            "ican_number": row["ican_number"],
            "specialisms": json.loads(row["specialisms_json"]),
            "verification": self.verification(row["id"]),
        }

    def public_view(self, row: dict[str, Any]) -> dict[str, Any]:
        v = self.verification(row["id"])
        memberships = [
            {"register": REGISTERS[reg], "number": mask(row[f"{reg}_number"])} for reg in REGISTERS if row[f"{reg}_number"]
        ]
        return {
            **{k: row[k] for k in ("id", "name", "firm", "state", "location", "bio")},
            "specialisms": json.loads(row["specialisms_json"]),
            "memberships": memberships,
            "verification": {k: v[k] for k in ("status", "checked_at", "expires_at", "mode", "registers")},
        }

    def staff_view(self, row: dict[str, Any]) -> dict[str, Any]:
        return {**self.owner_view(row), "user_id": row["user_id"], "reviewed_by": row["reviewed_by"], "reviewed_at": row["reviewed_at"]}

    # ------------------------------------------------------------------ writes
    def apply(self, user_id: str, body: dict[str, Any]) -> dict[str, Any]:
        if self.for_user(user_id):
            raise Conflict("You already have an adviser listing; edit it instead")
        values = self._parse(body, partial=False)
        adviser_id = new_id("adv")
        at = iso()
        self.db.insert(
            "advisory_advisers",
            {"id": adviser_id, "user_id": user_id, "status": "pending", "created_at": at, "updated_at": at, **values},
        )
        self.services.audit.record("advisory.adviser_applied", "adviser", adviser_id, actor_id=user_id)
        self.verify(adviser_id, actor_id=user_id)
        return self.row(adviser_id)

    def update_mine(self, user_id: str, body: dict[str, Any]) -> dict[str, Any]:
        row = self.mine(user_id)
        values = self._parse(body, partial=True, current=row)
        numbers_changed = any(values.get(k, row[k]) != row[k] for k in ("citn_number", "ican_number"))
        if numbers_changed and row["status"] in ("approved", "suspended", "rejected"):
            values["status"] = "pending"
        values["updated_at"] = iso()
        self.db.update("advisory_advisers", values, "id = ?", (row["id"],))
        self.services.audit.record(
            "advisory.adviser_updated", "adviser", row["id"], actor_id=user_id,
            data={"fields": sorted(k for k in values if k != "updated_at"), "reverify": numbers_changed},
        )  # fmt: skip
        if numbers_changed:
            self.verify(row["id"], actor_id=user_id)
        return self.row(row["id"])

    def verify(self, adviser_id: str, *, actor_id: str) -> dict[str, Any]:
        """Check each membership number with the register adapter and record the results."""
        row = self.row(adviser_id)
        adapter = self.services.adapters.get("register")
        results = []
        for reg in REGISTERS:
            number = row[f"{reg}_number"]
            if not number:
                continue
            result = adapter.check(reg, number)  # type: ignore[attr-defined]
            checked = now()
            record = {
                "id": new_id("avf"),
                "adviser_id": adviser_id,
                "register": reg,
                "number_masked": mask(number),
                "provider": adapter.name,
                "mode": adapter.mode,
                "result": result,
                "checked_at": iso(checked),
                "expires_at": iso(checked + REVERIFY_AFTER) if result == "verified" else None,
            }
            self.db.insert("advisory_verifications", record)
            results.append({"register": reg, "result": result, "mode": adapter.mode})
        self.services.audit.record("advisory.adviser_verified", "adviser", adviser_id, actor_id=actor_id, data={"results": results})
        return self.verification(adviser_id)

    def decide(self, adviser_id: str, staff_id: str, decision: str, note: str) -> dict[str, Any]:
        if decision not in DECISIONS:
            raise Invalid("decision: must be approve, reject or suspend")
        row = self.row(adviser_id)
        if row["status"] not in ALLOWED_FROM[decision]:
            raise Conflict(f"A {row['status']} listing cannot be given decision {decision}")
        if decision == "approve" and self.verification(adviser_id)["status"] != "verified":
            raise Conflict("Approve only after a current register verification")
        at = iso()
        self.db.update(
            "advisory_advisers",
            {"status": DECISIONS[decision], "review_note": note[:500] or None, "reviewed_by": staff_id, "reviewed_at": at, "updated_at": at},
            "id = ?",
            (adviser_id,),
        )
        self.services.audit.record("advisory.adviser_decision", "adviser", adviser_id, actor_id=staff_id, data={"decision": decision})
        return self.row(adviser_id)

    def for_staff(self, status: str | None) -> list[dict[str, Any]]:
        if status:
            rows = self.db.query("SELECT * FROM advisory_advisers WHERE status = ? ORDER BY created_at", (status,))
        else:
            rows = self.db.query("SELECT * FROM advisory_advisers ORDER BY created_at")
        return [self.staff_view(r) for r in rows]

    # ------------------------------------------------------------------ directory
    def directory(self, specialism: str | None, state: str | None) -> dict[str, Any]:
        """ADV-04: relevance order, with paid placement in a separate slot only."""
        if specialism and specialism not in SPECIALISMS:
            raise Invalid("specialism: unknown specialism")
        if state and state not in STATES:
            raise Invalid("state: unknown state")
        rows = self.db.query("SELECT * FROM advisory_advisers WHERE status = 'approved'")
        items = [self.public_view(r) for r in rows]
        items.sort(key=lambda a: self.relevance(a, specialism, state))
        return {"items": items, "sponsored": self.sponsored(specialism)}

    @staticmethod
    def relevance(adviser: dict[str, Any], specialism: str | None, state: str | None) -> tuple[int, int, str, str]:
        spec = 0 if specialism and specialism in adviser["specialisms"] else 1
        loc = 0 if state and adviser["state"] == state else 1
        return (spec, loc, adviser["name"].lower(), adviser["id"])

    def sponsored(self, specialism: str | None) -> list[dict[str, Any]]:
        stamp = iso()
        rows = self.db.query(
            "SELECT a.*, p.id AS placement_id, p.starts_at AS placement_start FROM advisory_placements p "
            "JOIN advisory_advisers a ON a.id = p.adviser_id "
            "WHERE p.status = 'active' AND a.status = 'approved' AND p.starts_at <= ? AND p.ends_at > ? ORDER BY p.starts_at, p.id",
            (stamp, stamp),
        )
        if not rows:
            return []
        matching = [r for r in rows if specialism and specialism in json.loads(r["specialisms_json"])]
        chosen = (matching or rows)[0]
        return [{**self.public_view(chosen), "sponsored": True, "placement_id": chosen["placement_id"]}]

    # ------------------------------------------------------------------ placement
    def placement_terms(self) -> dict[str, Any]:
        path = Path(self.services.content_dir) / "compliance" / "advisory_placements.yaml"
        terms = (yaml.safe_load(path.read_text()) or {}).get("sponsored_listing") or {}
        if "price_kobo" not in terms or "duration_days" not in terms:
            raise Conflict("Sponsored listing terms are not set")
        return terms

    def placements(self, adviser_id: str) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM advisory_placements WHERE adviser_id = ? ORDER BY created_at DESC", (adviser_id,))

    def start_placement(self, user_id: str) -> dict[str, Any]:
        """Create a pending placement and a billing checkout with purpose "advertising"."""
        row = self.mine(user_id)
        if row["status"] != "approved":
            raise Conflict("Only approved listings can buy a sponsored listing")
        billing = self.services.modules.get("billing")
        if billing is None:
            return {"available": False, "message": "Payments are not available yet. Please try again later."}
        register_payment_handler(self.services)
        terms = self.placement_terms()
        placement_id = new_id(PLACEMENT_PREFIX)
        self.db.insert(
            "advisory_placements",
            {
                "id": placement_id,
                "adviser_id": row["id"],
                "status": "pending_payment",
                "amount_kobo": int(terms["price_kobo"]),
                "duration_days": int(terms["duration_days"]),
                "created_at": iso(),
            },
        )
        checkout = billing.create_checkout(
            payer_user_id=user_id,
            org_id=None,
            purpose="advertising",
            reference_id=placement_id,
            amount_kobo=int(terms["price_kobo"]),
            description=str(terms.get("description") or "Sponsored adviser listing"),
        )
        self.db.update("advisory_placements", {"checkout_id": checkout.get("checkout_id"), "mode": checkout.get("mode")}, "id = ?", (placement_id,))
        self.services.audit.record("advisory.placement_started", "placement", placement_id, actor_id=user_id, data={"amount_kobo": int(terms["price_kobo"])})
        return {
            "available": True,
            "placement": self.db.one("SELECT * FROM advisory_placements WHERE id = ?", (placement_id,)),
            "checkout": checkout,
            "price_status": "to_be_confirmed" if "TBC" in str(terms.get("status", "")) else "confirmed",
        }

    def activate_placement(self, payment: dict[str, Any]) -> None:
        """Billing payment handler: a verified paid checkout activates its placement (idempotent)."""
        ref = str(payment.get("reference_id") or "")
        if not ref.startswith(f"{PLACEMENT_PREFIX}_"):
            return  # another module's advertising payment
        row = self.db.one("SELECT * FROM advisory_placements WHERE id = ?", (ref,))
        if not row or row["status"] != "pending_payment":
            return
        start = now()
        self.db.update(
            "advisory_placements",
            {"status": "active", "starts_at": iso(start), "ends_at": iso(start + dt.timedelta(days=row["duration_days"])), "mode": payment.get("mode", row["mode"])},
            "id = ? AND status = 'pending_payment'",
            (ref,),
        )
        self.services.audit.record("advisory.placement_activated", "placement", ref, data={"mode": payment.get("mode")})


def register_payment_handler(services: Services) -> bool:
    """Register the "advertising" payment handler with billing once per services instance.

    Called from ``init`` (if billing initialised first), from ``post_init`` and
    lazily before any checkout is created, because modules initialise in name
    order and ``advisory`` comes before ``billing``. Returns True when it registered.
    """
    billing = services.modules.get("billing")
    facade = services.modules.get("advisory")
    if billing is None or facade is None or facade.payment_handler_registered:
        return False

    def handler(svc: Services, payment: dict[str, Any]) -> None:
        Advisers(svc).activate_placement(payment)

    billing.register_payment_handler("advertising", handler)
    facade.payment_handler_registered = True
    return True
