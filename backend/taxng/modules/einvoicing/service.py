"""E-invoicing domain logic (PRD 5, EINV-01 to EINV-03, Annex A9).

Lifecycle::

    draft -> validated -> submitted -> accepted | rejected
    draft | validated | rejected -> cancelled
    accepted -> cancelled, only through an accepted credit note

VAT on every line comes from ``calculate_vat`` (the rules engine). This module
holds no rates. Each transition writes one row to the append-only
``einvoice_events`` table; key transitions also go to ``services.audit``.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from ...calculators import InputError, calculate_vat
from ...calculators.common import money, money_str
from ...calculators.vat import CATEGORIES
from ...platform.access import NotFoundError, Unauthorized
from ...platform.adapters import Adapter, NotConfigured
from ...platform.errors import Conflict, Invalid
from ...platform.util import canonical_json, iso, new_id, sign, verify_signature
from ...rules import ParameterError

if TYPE_CHECKING:
    from ...services import Services

log = logging.getLogger("taxng.einvoicing")

STATUSES = ("draft", "validated", "submitted", "accepted", "rejected", "cancelled")
EDITABLE = ("draft", "validated", "rejected")
CANCELLABLE = ("draft", "validated", "rejected")
# Nigerian TINs: the legacy FIRS form 12345678-0001 or the 10-digit JTB TIN.
TIN_RE = re.compile(r"^(\d{8}-\d{4}|\d{10})$")
NUMBER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/_.\-]{0,49}$")
SOURCE_RE = re.compile(r"^[a-z0-9_:.\-]{1,60}$")
MAX_LINES = 200
INPUT_KEYS = ("invoice_number", "issue_date", "due_date", "buyer_name", "buyer_tin", "buyer_email", "currency", "notes", "lines", "declared_totals")
LINE_KEYS = ("description", "quantity", "unit_price", "vat_category")


def _text(value: Any, limit: int) -> str:
    return str(value if value is not None else "").strip()[:limit]


def _clean_input(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Keeps only known fields, as strings, so stored input stays small and predictable."""
    p = payload if isinstance(payload, dict) else {}
    out: dict[str, Any] = {k: _text(p.get(k), 500) for k in INPUT_KEYS if k not in ("lines", "declared_totals") and p.get(k) not in (None, "")}
    lines = p.get("lines")
    if isinstance(lines, list):
        out["lines"] = [
            {k: _text(line.get(k), 500) for k in LINE_KEYS if line.get(k) not in (None, "")} if isinstance(line, dict) else "invalid"
            for line in lines[: MAX_LINES + 1]
        ]
    declared = p.get("declared_totals")
    if isinstance(declared, dict):
        out["declared_totals"] = {k: _text(declared.get(k), 40) for k in ("net", "vat", "gross") if declared.get(k) not in (None, "")}
    return out


def _date(raw: Any, key: str, errors: dict[str, str], *, required: bool = False) -> dt.date | None:
    if raw in (None, ""):
        if required:
            errors[key] = "is required"
        return None
    try:
        return dt.date.fromisoformat(str(raw))
    except ValueError:
        errors[key] = "must be a date (YYYY-MM-DD)"
        return None


def _decimal(raw: Any, key: str, errors: dict[str, str], *, positive: bool = False) -> Decimal | None:
    if raw in (None, ""):
        errors[key] = "is required"
        return None
    try:
        value = Decimal(re.sub(r"[,\s₦]", "", str(raw)))
    except InvalidOperation:
        errors[key] = "must be a number"
        return None
    if not value.is_finite() or value < 0 or (positive and value == 0):
        errors[key] = "must be more than zero" if positive else "must be zero or more"
        return None
    if value.as_tuple().exponent < -4:  # type: ignore[operator]
        errors[key] = "use at most 4 decimal places"
        return None
    return value


class EInvoicing:
    """``services.modules["einvoicing"]``."""

    def __init__(self, services: Services) -> None:
        self.services = services
        self.db = services.db

    # ---------------------------------------------------------------- basics
    @property
    def adapter(self) -> Adapter:
        return self.services.adapters.get("einvoicing")

    def callback_key(self) -> str:
        """HMAC key for NRS status callbacks (production: the key agreed with NRS)."""
        return sign(self.services.secret, "einvoicing:nrs-callback")

    def _org(self, org_id: str) -> dict[str, Any]:
        org = self.db.one("SELECT id, name, tin FROM organisations WHERE id = ?", (org_id,))
        if org is None:
            raise NotFoundError("Organisation not found")
        return org

    def _row(self, org_id: str, invoice_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM einvoices WHERE id = ? AND org_id = ?", (invoice_id, org_id))
        if row is None:
            raise NotFoundError("Invoice not found")
        return row

    def _event(self, inv: dict[str, Any], event: str, actor_id: str | None, to_status: str | None = None, data: dict[str, Any] | None = None) -> None:
        self.db.insert(
            "einvoice_events",
            {
                "invoice_id": inv["id"],
                "org_id": inv["org_id"],
                "at": iso(),
                "actor_id": actor_id,
                "event": event,
                "from_status": inv["status"],
                "to_status": to_status or inv["status"],
                "data_json": canonical_json(data or {}),
            },
        )

    def _move(self, inv: dict[str, Any], to_status: str, actor_id: str | None, event: str, values: dict[str, Any] | None = None, data: dict[str, Any] | None = None) -> None:
        """Guarded transition: only applies if the invoice is still in the status we read."""
        changed = self.db.update(
            "einvoices",
            {"status": to_status, "updated_at": iso(), **(values or {})},
            "id = ? AND status = ?",
            (inv["id"], inv["status"]),
        )
        if changed != 1:
            raise Conflict("The invoice changed while you were working on it. Reload and try again.")
        self._event(inv, event, actor_id, to_status, data)

    def _emit(self, org_id: str, event: str, inv: dict[str, Any]) -> None:
        developer = self.services.modules.get("developer")
        if developer is None:
            return
        try:
            developer.emit(
                org_id,
                event,
                {k: inv.get(k) for k in ("id", "kind", "invoice_number", "status", "irn", "rejection_reason", "mode")},
            )
        except Exception:  # noqa: BLE001 - webhooks must never break invoicing
            log.exception("webhook emit failed")

    # ------------------------------------------------------------ validation
    def evaluate(self, org: dict[str, Any], data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        """Checks every field and computes VAT per line. Returns (computed, field errors)."""
        errors: dict[str, str] = {}
        number = data.get("invoice_number", "")
        if not number:
            errors["invoice_number"] = "is required"
        elif not NUMBER_RE.match(number):
            errors["invoice_number"] = "use up to 50 letters, digits or / _ . -"
        issue = _date(data.get("issue_date"), "issue_date", errors, required=True)
        if issue and issue > dt.date.today():
            errors["issue_date"] = "must not be in the future"
        due = _date(data.get("due_date"), "due_date", errors)
        if issue and due and due < issue:
            errors["due_date"] = "must be on or after the issue date"
        if not data.get("buyer_name"):
            errors["buyer_name"] = "is required"
        elif len(data["buyer_name"]) > 200:
            errors["buyer_name"] = "keep it under 200 characters"
        buyer_tin = data.get("buyer_tin", "")
        supplier_tin = (org.get("tin") or "").strip()
        if not buyer_tin:
            errors["buyer_tin"] = "is required"
        elif not TIN_RE.match(buyer_tin):
            errors["buyer_tin"] = "use 12345678-0001 or a 10-digit TIN"
        if not supplier_tin:
            errors["supplier_tin"] = "add your organisation's TIN in workspace settings before issuing e-invoices"
        elif not TIN_RE.match(supplier_tin):
            errors["supplier_tin"] = "your organisation's TIN is not in a recognised format"
        elif buyer_tin == supplier_tin:
            errors["buyer_tin"] = "must differ from the supplier TIN"
        if data.get("currency", "NGN").upper() != "NGN":
            errors["currency"] = "only NGN invoices are supported"
        if data.get("buyer_email") and "@" not in data["buyer_email"]:
            errors["buyer_email"] = "must be an email address"

        raw_lines = data.get("lines")
        parsed: list[dict[str, Any]] = []
        if not isinstance(raw_lines, list) or not raw_lines:
            errors["lines"] = "add at least one line"
        elif len(raw_lines) > MAX_LINES:
            errors["lines"] = f"at most {MAX_LINES} lines per invoice"
        else:
            for i, raw in enumerate(raw_lines):
                key = f"lines.{i}"
                if not isinstance(raw, dict):
                    errors[key] = "must be an object"
                    continue
                if not raw.get("description"):
                    errors[f"{key}.description"] = "is required"
                qty = _decimal(raw.get("quantity"), f"{key}.quantity", errors, positive=True)
                price = _decimal(raw.get("unit_price"), f"{key}.unit_price", errors)
                category = raw.get("vat_category") or "standard"
                if category not in CATEGORIES:
                    errors[f"{key}.vat_category"] = f"must be one of: {', '.join(CATEGORIES)}"
                parsed.append({"description": raw.get("description", ""), "quantity": qty, "unit_price": price, "vat_category": category})

        computed: dict[str, Any] = {"lines": [], "totals": {}, "rules_version": None}
        if issue is None or any(k.startswith("lines") for k in errors):
            return computed, errors
        net_total = vat_total = Decimal(0)
        for i, line in enumerate(parsed):
            net = money(line["quantity"] * line["unit_price"])
            try:
                result = calculate_vat({"amount": str(net), "category": line["vat_category"], "supply_date": issue.isoformat()}, self.services.tree)
            except InputError:
                errors[f"lines.{i}.unit_price"] = "line amount is too large"
                return computed, errors
            except ParameterError:
                errors["issue_date"] = "VAT rules are not in force for this date"
                return computed, errors
            out = result.outputs
            vat = Decimal(out["vat"])
            net_total += net
            vat_total += vat
            computed["lines"].append(
                {
                    "description": line["description"],
                    "quantity": str(line["quantity"]),
                    "unit_price": money_str(line["unit_price"]),
                    "vat_category": line["vat_category"],
                    "vat_rate": out["rate"],
                    "net": money_str(net),
                    "vat": money_str(vat),
                    "gross": money_str(net + vat),
                }
            )
            computed["rules_version"] = result.view.tree.version
        computed["totals"] = {"net": money_str(net_total), "vat": money_str(vat_total), "gross": money_str(net_total + vat_total)}
        for k, declared in (data.get("declared_totals") or {}).items():
            try:
                if money(Decimal(re.sub(r"[,\s₦]", "", declared))) != Decimal(computed["totals"][k]):
                    errors[f"totals.{k}"] = f"declared {declared} does not match the computed {computed['totals'][k]}"
            except InvalidOperation:
                errors[f"totals.{k}"] = "declared total must be a number"
        return computed, errors

    # ----------------------------------------------------------------- reads
    def to_dict(self, row: dict[str, Any], *, events: bool = False) -> dict[str, Any]:
        data = json.loads(row["input_json"])
        out = {
            "id": row["id"],
            "org_id": row["org_id"],
            "kind": row["kind"],
            "original_invoice_id": row["original_invoice_id"],
            "invoice_number": row["invoice_number"],
            "status": row["status"],
            "issue_date": row["issue_date"],
            "due_date": data.get("due_date"),
            "buyer_name": row["buyer_name"],
            "buyer_tin": row["buyer_tin"],
            "buyer_email": data.get("buyer_email"),
            "currency": data.get("currency", "NGN"),
            "notes": data.get("notes"),
            "input_lines": data.get("lines", []),
            "lines": json.loads(row["lines_json"]),
            "totals": json.loads(row["totals_json"]),
            "declared_totals": json.loads(row["declared_totals_json"]) if row["declared_totals_json"] else None,
            "errors": json.loads(row["errors_json"]),
            "rules_version": row["rules_version"],
            "source": row["source"],
            "external_id": row["external_id"],
            "submission_ref": row["submission_ref"],
            "irn": row["irn"],
            "qr_payload": row["qr_payload"],
            "mode": row["mode"] or self.adapter.mode,
            "rejection_reason": row["rejection_reason"],
            "last_error": row["last_error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "submitted_at": row["submitted_at"],
            "decided_at": row["decided_at"],
        }
        if events:
            out["events"] = self.events(row["org_id"], row["id"])
        return out

    def get(self, org_id: str, invoice_id: str) -> dict[str, Any]:
        return self.to_dict(self._row(org_id, invoice_id), events=True)

    def events(self, org_id: str, invoice_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT seq, at, actor_id, event, from_status, to_status, data_json FROM einvoice_events WHERE invoice_id = ? AND org_id = ? ORDER BY seq",
            (invoice_id, org_id),
        )
        return [{**{k: v for k, v in r.items() if k != "data_json"}, "data": json.loads(r["data_json"])} for r in rows]

    def list(self, org_id: str, status: str | None = None, *, limit: int = 200) -> dict[str, Any]:
        if status and status not in STATUSES:
            raise Invalid(f"status: must be one of {', '.join(STATUSES)}")
        sql, params = "SELECT * FROM einvoices WHERE org_id = ?", [org_id]
        if status:
            sql += " AND status = ?"
            params.append(status)
        rows = self.db.query(sql + " ORDER BY created_at DESC, rowid DESC LIMIT ?", [*params, min(limit, 500)])
        counts = {r["status"]: r["n"] for r in self.db.query("SELECT status, COUNT(*) AS n FROM einvoices WHERE org_id = ? GROUP BY status", (org_id,))}
        return {
            "items": [{k: v for k, v in self.to_dict(r).items() if k not in ("input_lines", "lines", "qr_payload")} for r in rows],
            "counts": {s: counts.get(s, 0) for s in STATUSES},
            "mode": self.adapter.mode,
        }

    def exceptions(self, org_id: str) -> dict[str, Any]:
        rows = self.db.query(
            "SELECT * FROM einvoices WHERE org_id = ? AND (status = 'rejected' OR (last_error IS NOT NULL AND status IN ('draft', 'validated'))) "
            "ORDER BY updated_at DESC",
            (org_id,),
        )
        items = []
        for r in rows:
            d = self.to_dict(r)
            items.append(
                {
                    "id": d["id"],
                    "invoice_number": d["invoice_number"],
                    "status": d["status"],
                    "kind": "rejected" if d["status"] == "rejected" else "failed",
                    "reason": d["rejection_reason"] or d["last_error"],
                    "buyer_name": d["buyer_name"],
                    "totals": d["totals"],
                    "updated_at": d["updated_at"],
                    "mode": d["mode"],
                }
            )
        return {"items": items, "mode": self.adapter.mode}

    # ---------------------------------------------------------------- writes
    def create(
        self,
        org_id: str,
        actor_id: str,
        payload: dict[str, Any],
        *,
        source: str = "manual",
        external_id: str | None = None,
        kind: str = "invoice",
        original_invoice_id: str | None = None,
    ) -> dict[str, Any]:
        org = self._org(org_id)
        data = _clean_input(payload)
        computed, errors = self.evaluate(org, data)
        if "invoice_number" in errors:
            raise InputError({"invoice_number": errors["invoice_number"]})
        if self.db.scalar("SELECT 1 FROM einvoices WHERE org_id = ? AND invoice_number = ?", (org_id, data["invoice_number"])):
            raise Conflict(f"Invoice number {data['invoice_number']} already exists in this workspace")
        invoice_id = new_id("inv")
        now = iso()
        row = {
            "id": invoice_id,
            "org_id": org_id,
            "kind": kind,
            "original_invoice_id": original_invoice_id,
            "invoice_number": data["invoice_number"],
            "status": "draft",
            "issue_date": data.get("issue_date"),
            "buyer_name": data.get("buyer_name", ""),
            "buyer_tin": data.get("buyer_tin", ""),
            "input_json": canonical_json(data),
            "lines_json": canonical_json(computed["lines"]),
            "totals_json": canonical_json(computed["totals"]),
            "declared_totals_json": canonical_json(data["declared_totals"]) if data.get("declared_totals") else None,
            "errors_json": canonical_json(errors),
            "rules_version": computed["rules_version"],
            "source": source,
            "external_id": external_id,
            "created_by": actor_id,
            "created_at": now,
            "updated_at": now,
        }
        with self.db.transaction():
            self.db.insert("einvoices", row)
            self._event({**row, "status": None}, "created", actor_id, "draft", {"source": source, "kind": kind, "errors": len(errors)})
        self.services.audit.record("einvoice.create", "einvoice", invoice_id, actor_id=actor_id, org_id=org_id, data={"source": source, "kind": kind})
        return self.get(org_id, invoice_id)

    def update(self, org_id: str, invoice_id: str, actor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        inv = self._row(org_id, invoice_id)
        if inv["kind"] == "credit_note":
            raise Conflict("Credit notes copy the original invoice and cannot be edited")
        if inv["status"] not in EDITABLE:
            raise Conflict(f"A {inv['status']} invoice cannot be edited")
        org = self._org(org_id)
        data = _clean_input(payload)
        computed, errors = self.evaluate(org, data)
        if "invoice_number" in errors:
            raise InputError({"invoice_number": errors["invoice_number"]})
        if data["invoice_number"] != inv["invoice_number"] and self.db.scalar(
            "SELECT 1 FROM einvoices WHERE org_id = ? AND invoice_number = ?", (org_id, data["invoice_number"])
        ):
            raise Conflict(f"Invoice number {data['invoice_number']} already exists in this workspace")
        values = {
            "invoice_number": data["invoice_number"],
            "issue_date": data.get("issue_date"),
            "buyer_name": data.get("buyer_name", ""),
            "buyer_tin": data.get("buyer_tin", ""),
            "input_json": canonical_json(data),
            "lines_json": canonical_json(computed["lines"]),
            "totals_json": canonical_json(computed["totals"]),
            "declared_totals_json": canonical_json(data["declared_totals"]) if data.get("declared_totals") else None,
            "errors_json": canonical_json(errors),
            "rules_version": computed["rules_version"],
            "last_error": None,
        }
        with self.db.transaction():
            self._move(inv, "draft", actor_id, "edited", values, {"errors": len(errors)})
        return self.get(org_id, invoice_id)

    def validate(self, org_id: str, invoice_id: str, actor_id: str) -> dict[str, Any]:
        inv = self._row(org_id, invoice_id)
        if inv["status"] not in EDITABLE:
            raise Conflict(f"A {inv['status']} invoice cannot be validated again")
        computed, errors = self.evaluate(self._org(org_id), json.loads(inv["input_json"]))
        values = {
            "lines_json": canonical_json(computed["lines"]),
            "totals_json": canonical_json(computed["totals"]),
            "errors_json": canonical_json(errors),
            "rules_version": computed["rules_version"],
        }
        with self.db.transaction():
            if errors:
                if inv["status"] == "draft":
                    self.db.update("einvoices", {**values, "updated_at": iso()}, "id = ?", (inv["id"],))
                    self._event(inv, "validation_failed", actor_id, "draft", {"fields": sorted(errors)})
                else:
                    self._move(inv, "draft", actor_id, "validation_failed", values, {"fields": sorted(errors)})
            else:
                self._move(inv, "validated", actor_id, "validated", values, {"totals": computed["totals"]})
        if errors:
            raise InputError(errors)
        return self.get(org_id, invoice_id)

    def _submission_doc(self, inv: dict[str, Any], org: dict[str, Any]) -> dict[str, Any]:
        doc = {
            "invoice_id": inv["id"],
            "kind": inv["kind"],
            "invoice_number": inv["invoice_number"],
            "issue_date": inv["issue_date"],
            "supplier_name": org["name"],
            "supplier_tin": org["tin"],
            "buyer_name": inv["buyer_name"],
            "buyer_tin": inv["buyer_tin"],
            "lines": json.loads(inv["lines_json"]),
            "totals": json.loads(inv["totals_json"]),
        }
        if inv["original_invoice_id"]:
            original = self.db.one("SELECT irn FROM einvoices WHERE id = ?", (inv["original_invoice_id"],))
            doc["original_irn"] = original["irn"] if original else None
        return doc

    def submit(self, org_id: str, invoice_id: str, actor_id: str, *, idempotency_key: str | None = None) -> dict[str, Any]:
        """Validates if needed, then submits to NRS through the adapter. Idempotent on ``idempotency_key``."""
        if idempotency_key is not None:
            idempotency_key = idempotency_key.strip()
            if not 1 <= len(idempotency_key) <= 100:
                raise Invalid("idempotency_key: use 1 to 100 characters")
            stored = self.db.one("SELECT * FROM einvoice_idempotency WHERE org_id = ? AND idem_key = ?", (org_id, idempotency_key))
            if stored:
                if stored["invoice_id"] != invoice_id:
                    raise Conflict("This idempotency key was already used for a different invoice")
                return {**json.loads(stored["response_json"]), "replayed": True}
        inv = self._row(org_id, invoice_id)
        if inv["status"] in ("draft", "rejected"):
            self.validate(org_id, invoice_id, actor_id)
            inv = self._row(org_id, invoice_id)
        elif inv["status"] != "validated":
            raise Conflict(f"This invoice is {inv['status']}; only draft or validated invoices can be submitted")
        org = self._org(org_id)
        adapter = self.adapter
        try:
            result = adapter.submit(self._submission_doc(inv, org))  # type: ignore[attr-defined]
        except NotConfigured as exc:
            with self.db.transaction():
                self.db.update("einvoices", {"last_error": str(exc), "updated_at": iso()}, "id = ?", (inv["id"],))
                self._event(inv, "submission_failed", actor_id, data={"error": str(exc), "mode": adapter.mode})
            raise
        values = {
            "submission_ref": result["submission_ref"],
            "irn": result["irn"],
            "qr_payload": result["qr_payload"],
            "mode": result["mode"],
            "submitted_at": iso(),
            "last_error": None,
            "rejection_reason": None,
        }
        with self.db.transaction():
            self._move(inv, "submitted", actor_id, "submitted", values, {"submission_ref": result["submission_ref"], "irn": result["irn"], "mode": result["mode"]})
            response = {"invoice": self.to_dict(self._row(org_id, invoice_id)), "mode": result["mode"], "replayed": False}
            if idempotency_key:
                self.db.insert(
                    "einvoice_idempotency",
                    {"org_id": org_id, "idem_key": idempotency_key, "invoice_id": invoice_id, "response_json": canonical_json(response), "created_at": iso()},
                )
        self.services.audit.record(
            "einvoice.submit", "einvoice", invoice_id, actor_id=actor_id, org_id=org_id, data={"mode": result["mode"], "submission_ref": result["submission_ref"]}
        )
        self._emit(org_id, "einvoice.submitted", response["invoice"])
        return response

    def cancel(self, org_id: str, invoice_id: str, actor_id: str, reason: str = "") -> dict[str, Any]:
        inv = self._row(org_id, invoice_id)
        if inv["status"] == "accepted":
            raise Conflict("An accepted invoice is cancelled by issuing a credit note")
        if inv["status"] not in CANCELLABLE:
            raise Conflict(f"A {inv['status']} invoice cannot be cancelled")
        with self.db.transaction():
            self._move(inv, "cancelled", actor_id, "cancelled", data={"reason": reason[:300]})
        self.services.audit.record("einvoice.cancel", "einvoice", invoice_id, actor_id=actor_id, org_id=org_id)
        return self.get(org_id, invoice_id)

    def credit_note(self, org_id: str, invoice_id: str, actor_id: str, reason: str = "") -> dict[str, Any]:
        inv = self._row(org_id, invoice_id)
        if inv["kind"] != "invoice" or inv["status"] != "accepted":
            raise Conflict("Credit notes can be issued only against an accepted invoice")
        if self.db.scalar(
            "SELECT 1 FROM einvoices WHERE original_invoice_id = ? AND status NOT IN ('cancelled', 'rejected')", (invoice_id,)
        ):
            raise Conflict("A credit note for this invoice is already in progress")
        data = json.loads(inv["input_json"])
        data["invoice_number"] = f"CN-{inv['invoice_number']}"[:50]
        data["issue_date"] = dt.date.today().isoformat()
        data.pop("declared_totals", None)
        data["notes"] = (reason or f"Credit note for {inv['invoice_number']}")[:300]
        note = self.create(org_id, actor_id, data, source=inv["source"], kind="credit_note", original_invoice_id=invoice_id)
        self._event(inv, "credit_note_issued", actor_id, data={"credit_note_id": note["id"]})
        return note

    # -------------------------------------------------------- status updates
    def apply_callback(self, payload: dict[str, Any], signature: str) -> dict[str, Any]:
        """Applies a signed NRS status callback. Verifies the signature first; idempotent."""
        if not isinstance(payload, dict) or not verify_signature(self.callback_key(), canonical_json(payload), signature):
            raise Unauthorized("Invalid callback signature")
        status = payload.get("status")
        if status not in ("accepted", "rejected"):
            raise Invalid("status: must be accepted or rejected")
        inv = self.db.one("SELECT * FROM einvoices WHERE submission_ref = ?", (str(payload.get("submission_ref", "")),))
        if inv is None:
            raise NotFoundError("Unknown submission")
        if inv["status"] == status:
            return {"invoice_id": inv["id"], "status": status, "duplicate": True, "mode": inv["mode"]}
        if inv["status"] != "submitted":
            raise Conflict(f"Invoice is {inv['status']}; callback ignored")
        reason = payload.get("reason") if status == "rejected" else None
        with self.db.transaction():
            self._move(
                inv,
                status,
                None,
                status,
                {"decided_at": iso(), "rejection_reason": reason},
                {"callback_id": payload.get("event_id"), "reason": reason, "mode": inv["mode"]},
            )
            if status == "accepted" and inv["kind"] == "credit_note" and inv["original_invoice_id"]:
                original = self.db.one("SELECT * FROM einvoices WHERE id = ?", (inv["original_invoice_id"],))
                if original and original["status"] == "accepted":
                    self._move(original, "cancelled", None, "cancelled_by_credit_note", data={"credit_note_id": inv["id"]})
        self.services.audit.record(f"einvoice.{status}", "einvoice", inv["id"], org_id=inv["org_id"], data={"mode": inv["mode"]})
        fresh = self.to_dict(self._row(inv["org_id"], inv["id"]))
        self._emit(inv["org_id"], f"einvoice.{status}", fresh)
        return {"invoice_id": inv["id"], "status": status, "duplicate": False, "reason": reason, "mode": inv["mode"]}

    def sync(self, org_id: str) -> dict[str, Any]:
        """Status sync job: asks the adapter for pending callbacks and applies each, signature-checked."""
        adapter = self.adapter
        rows = self.db.query("SELECT * FROM einvoices WHERE org_id = ? AND status = 'submitted' ORDER BY submitted_at", (org_id,))
        items = []
        for inv in rows:
            payload, signature = adapter.status_callback(  # type: ignore[attr-defined]
                {"submission_ref": inv["submission_ref"], "irn": inv["irn"], "buyer_tin": inv["buyer_tin"]}, self.callback_key()
            )
            items.append({"invoice_number": inv["invoice_number"], **self.apply_callback(payload, signature)})
        return {"processed": len(items), "items": items, "mode": adapter.mode}

    # ---------------------------------------------------------------- import
    def import_invoices(self, org_id: str, actor_id: str, invoices: list[dict[str, Any]], *, source: str) -> dict[str, Any]:
        """Contract for ERP connectors. Idempotent on (org_id, source, external_id)."""
        if not SOURCE_RE.match(source or ""):
            raise Invalid("source: use lower-case letters, digits and : _ . - (up to 60)")
        if not isinstance(invoices, list):
            raise Invalid("invoices: must be a list")
        if len(invoices) > 1000:
            raise Invalid("invoices: at most 1000 per import")
        self._org(org_id)
        counts = {"created": 0, "validated": 0, "duplicate": 0, "failed": 0}
        items: list[dict[str, Any]] = []
        for i, raw in enumerate(invoices):
            external_id = _text(raw.get("external_id") if isinstance(raw, dict) else None, 100)
            item: dict[str, Any] = {"index": i, "external_id": external_id or None, "invoice_number": raw.get("invoice_number") if isinstance(raw, dict) else None}
            if not external_id:
                item.update(status="failed", errors={"external_id": "is required for imports"})
                counts["failed"] += 1
                items.append(item)
                continue
            existing = self.db.one(
                "SELECT id, status FROM einvoices WHERE org_id = ? AND source = ? AND external_id = ?", (org_id, source, external_id)
            )
            if existing:
                item.update(status="duplicate", invoice_id=existing["id"], invoice_status=existing["status"])
                counts["duplicate"] += 1
                items.append(item)
                continue
            try:
                inv = self.create(org_id, actor_id, raw, source=source, external_id=external_id)
            except InputError as exc:
                item.update(status="failed", errors=exc.errors)
                counts["failed"] += 1
                items.append(item)
                continue
            except Conflict as exc:
                item.update(status="failed", errors={"invoice_number": str(exc)})
                counts["failed"] += 1
                items.append(item)
                continue
            counts["created"] += 1
            item.update(invoice_id=inv["id"])
            try:
                self.validate(org_id, inv["id"], actor_id)
                item.update(status="validated")
                counts["validated"] += 1
            except InputError as exc:
                item.update(status="created", errors=exc.errors)
            items.append(item)
        self.services.audit.record("einvoice.import", "einvoice_import", None, actor_id=actor_id, org_id=org_id, data={"source": source, **counts})
        return {"source": source, "counts": counts, "items": items, "mode": self.adapter.mode}

    def submit_validated(self, org_id: str, actor_id: str, *, source: str | None = None) -> dict[str, Any]:
        sql, params = "SELECT id FROM einvoices WHERE org_id = ? AND status = 'validated'", [org_id]
        if source:
            sql += " AND source = ?"
            params.append(source)
        submitted = [self.submit(org_id, r["id"], actor_id)["invoice"]["invoice_number"] for r in self.db.query(sql, params)]
        return {"submitted": submitted, "mode": self.adapter.mode}

    def sources(self, org_id: str, prefix: str = "") -> list[str]:
        rows = self.db.query("SELECT DISTINCT source FROM einvoices WHERE org_id = ? ORDER BY source", (org_id,))
        return [r["source"] for r in rows if r["source"].startswith(prefix)]

    def source_report(self, org_id: str, source: str) -> dict[str, Any]:
        """Reconciliation figures for one import source: imported vs submitted vs accepted, and mismatches."""
        rows = self.db.query("SELECT * FROM einvoices WHERE org_id = ? AND source = ? AND kind = 'invoice' ORDER BY created_at", (org_id, source))
        by_status = {s: 0 for s in STATUSES}
        mismatched, invalid = [], []
        for r in rows:
            by_status[r["status"]] += 1
            errors = json.loads(r["errors_json"])
            totals = json.loads(r["totals_json"])
            declared = json.loads(r["declared_totals_json"]) if r["declared_totals_json"] else {}
            diffs = {k: {"declared": v, "computed": totals.get(k)} for k, v in declared.items() if f"totals.{k}" in errors}
            if diffs:
                mismatched.append({"invoice_id": r["id"], "external_id": r["external_id"], "invoice_number": r["invoice_number"], "differences": diffs})
            elif errors and r["status"] == "draft":
                invalid.append({"invoice_id": r["id"], "external_id": r["external_id"], "invoice_number": r["invoice_number"], "errors": errors})
        return {
            "source": source,
            "imported": len(rows),
            "submitted": sum(1 for r in rows if r["submitted_at"]),
            "accepted": by_status["accepted"],
            "rejected": by_status["rejected"],
            "by_status": by_status,
            "mismatched_totals": mismatched,
            "invalid": invalid,
            "mode": self.adapter.mode,
        }
