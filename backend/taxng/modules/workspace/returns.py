"""Returns (BIZ-02), maker-checker review (BIZ-05) and authority-style export (PRD 5).

Figures come only from the platform calculators (``CALCULATORS``). Each line
stores the exact calculator input and the full ``CalculationResult`` including
``rules_version``, so any figure can be reproduced later. This module adds up
calculator outputs into return totals; it holds no rates, thresholds or due dates.

Lifecycle::

    draft -> submitted_for_review -> approved -> filed_sandbox | filed
                     |                   ^
                     v                   |
             changes_requested ----------+ (resubmit, then approve)

Lines can change only in ``draft`` and ``changes_requested``. After approval the
return is locked; only an owner can reopen it (audited), which returns it to
``draft``. ``filed`` and ``filed_sandbox`` are set only by ``filing.py`` on a
verified acknowledgement.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from ...api.router import NotFound
from ...calculators import CALCULATORS
from ...calculators.common import money_str
from ...platform.access import CAN_ADMIN, CAN_EDIT, CAN_REVIEW, Forbidden, Principal
from ...platform.errors import Conflict, Invalid
from ...platform.util import canonical_json, iso, new_id, sha256
from .service import find_obligation, org_row

if TYPE_CHECKING:
    from ...services import Services

EDITABLE = ("draft", "changes_requested")
EXPORTABLE = ("approved", "filed_sandbox", "filed")
LAYOUT = "taxng.return.v1"
OFFICIAL_CHANNELS_NOTICE = (
    "Prepared with tax.ng. Not filed. For submission through official channels "
    "(the NRS or State Internal Revenue Service portal or office). tax.ng has no authorised filing integration for this return."
)
SANDBOX_NOTICE = (
    "Sandbox acknowledgement only. This return has NOT been filed with any tax authority. "
    "For submission through official channels."
)

# Each return type: calculator, allowed line kinds, descriptive fields, calculator inputs
# and the export schedule columns as (column, source, key).
RETURN_TYPES: dict[str, dict[str, Any]] = {
    "vat_monthly": {
        "label": "VAT return (monthly)",
        "tax": "vat",
        "frequency": "monthly",
        "calculator": "vat",
        "authority": "Nigeria Revenue Service (NRS)",
        "kinds": ("output", "input"),
        "details": ("invoice_ref", "counterparty", "description"),
        "inputs": ("supply_date", "amount", "category", "amount_includes_vat"),
        "date_field": "supply_date",
        "columns": [
            ("kind", "line", "kind"),
            ("invoice_ref", "details", "invoice_ref"),
            ("counterparty", "details", "counterparty"),
            ("description", "details", "description"),
            ("supply_date", "inputs", "supply_date"),
            ("category", "inputs", "category"),
            ("net_amount", "outputs", "net_amount"),
            ("vat_rate", "outputs", "rate"),
            ("vat", "outputs", "vat"),
            ("gross_amount", "outputs", "gross_amount"),
        ],
    },
    "wht_monthly": {
        "label": "Withholding tax schedule (monthly)",
        "tax": "wht",
        "frequency": "monthly",
        "calculator": "wht",
        "authority": "NRS for corporate payees; State Internal Revenue Service for individual payees",
        "kinds": ("payment",),
        "details": ("payee_name", "payee_tin", "description"),
        "inputs": ("payment_date", "payment_type", "recipient_type", "amount", "recipient_has_tin", "payer_is_small_company"),
        "date_field": "payment_date",
        "columns": [
            ("payee_name", "details", "payee_name"),
            ("payee_tin", "details", "payee_tin"),
            ("description", "details", "description"),
            ("payment_date", "inputs", "payment_date"),
            ("payment_type", "inputs", "payment_type"),
            ("recipient_type", "inputs", "recipient_type"),
            ("gross_amount", "inputs", "amount"),
            ("wht_rate", "outputs", "rate"),
            ("wht", "outputs", "wht"),
            ("net_payment", "outputs", "net_payment"),
        ],
    },
    "paye_monthly": {
        "label": "PAYE schedule (monthly)",
        "tax": "paye",
        "frequency": "monthly",
        "calculator": "pit",
        "authority": "State Internal Revenue Service of each employee's state of residence",
        "kinds": ("employee",),
        "details": ("employee_ref", "employee_name", "state_of_residence"),
        "inputs": ("annual_gross_income", "annual_rent_paid", "pension", "nhf", "nhis", "life_insurance", "mortgage_interest"),
        "year_field": "tax_year",
        "columns": [
            ("employee_ref", "details", "employee_ref"),
            ("employee_name", "details", "employee_name"),
            ("state_of_residence", "details", "state_of_residence"),
            ("annual_gross_income", "inputs", "annual_gross_income"),
            ("chargeable_income", "outputs", "chargeable_income"),
            ("annual_tax", "outputs", "annual_tax"),
            ("monthly_paye", "outputs", "monthly_tax"),
        ],
    },
    "cit_annual": {
        "label": "Companies income tax return (annual)",
        "tax": "cit",
        "frequency": "annual",
        "calculator": "cit",
        "authority": "Nigeria Revenue Service (NRS)",
        "kinds": ("computation",),
        "max_lines": 1,
        "details": ("accounting_period_end",),
        "inputs": ("annual_turnover", "fixed_assets", "total_profits", "assessable_profits", "professional_services", "non_resident"),
        "year_field": "tax_year",
        "columns": [
            ("accounting_period_end", "details", "accounting_period_end"),
            ("annual_turnover", "inputs", "annual_turnover"),
            ("fixed_assets", "inputs", "fixed_assets"),
            ("total_profits", "inputs", "total_profits"),
            ("is_small_company", "outputs", "is_small_company"),
            ("cit_rate", "outputs", "cit_rate"),
            ("cit", "outputs", "cit"),
            ("development_levy", "outputs", "development_levy"),
            ("total_tax", "outputs", "total_tax"),
        ],
    },
}
MONTHLY = re.compile(r"^(20\d\d)-(0[1-9]|1[0-2])$")
ANNUAL = re.compile(r"^20\d\d$")


def return_types() -> list[dict[str, Any]]:
    return [
        {
            "id": key,
            "label": spec["label"],
            "tax": spec["tax"],
            "frequency": spec["frequency"],
            "authority": spec["authority"],
            "kinds": list(spec["kinds"]),
            "details": list(spec["details"]),
            "inputs": list(spec["inputs"]),
            "max_lines": spec.get("max_lines"),
        }
        for key, spec in RETURN_TYPES.items()
    ]


# ------------------------------------------------------------------ loading
def get_return(services: Services, org_id: str, return_id: str) -> dict[str, Any]:
    row = services.db.one("SELECT * FROM ws_returns WHERE id = ? AND org_id = ?", (return_id, org_id))
    if row is None:
        raise NotFound("Return not found")
    return row


def lines_for(services: Services, ret: dict[str, Any]) -> list[dict[str, Any]]:
    rows = services.db.query(
        "SELECT * FROM ws_return_lines WHERE org_id = ? AND return_id = ? ORDER BY position, created_at", (ret["org_id"], ret["id"])
    )
    return [
        {
            "id": r["id"],
            "position": r["position"],
            "kind": r["kind"],
            "details": json.loads(r["details_json"]),
            "inputs": json.loads(r["inputs_json"]),
            "result": json.loads(r["result_json"]),
            "rules_version": r["rules_version"],
            "calculator": r["calculator"],
            "updated_by": r["updated_by"],
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]


def makers(services: Services, return_id: str) -> set[str]:
    return {r["user_id"] for r in services.db.query("SELECT user_id FROM ws_return_makers WHERE return_id = ?", (return_id,))}


def totals_for(return_type: str, lines: list[dict[str, Any]]) -> dict[str, str | int]:
    """Adds up calculator outputs. ``liability`` is what the payer owes for the period."""
    out = lambda line, key: Decimal(str(line["result"]["outputs"][key]))  # noqa: E731
    zero = Decimal(0)
    if return_type == "vat_monthly":
        outputs = [ln for ln in lines if ln["kind"] == "output"]
        inputs = [ln for ln in lines if ln["kind"] == "input"]
        output_vat = sum((out(ln, "vat") for ln in outputs), zero)
        input_vat = sum((out(ln, "vat") for ln in inputs), zero)
        net = output_vat - input_vat
        return {
            "lines": len(lines),
            "sales_net": money_str(sum((out(ln, "net_amount") for ln in outputs), zero)),
            "purchases_net": money_str(sum((out(ln, "net_amount") for ln in inputs), zero)),
            "output_vat": money_str(output_vat),
            "input_vat": money_str(input_vat),
            "net_vat": money_str(net),
            "credit_carried_forward": money_str(-net if net < 0 else zero),
            "liability": money_str(net if net > 0 else zero),
        }
    if return_type == "wht_monthly":
        wht = sum((out(ln, "wht") for ln in lines), zero)
        return {
            "lines": len(lines),
            "gross_payments": money_str(sum((Decimal(str(ln["result"]["inputs"]["amount"])) for ln in lines), zero)),
            "wht": money_str(wht),
            "liability": money_str(wht),
        }
    if return_type == "paye_monthly":
        paye = sum((out(ln, "monthly_tax") for ln in lines), zero)
        return {"lines": len(lines), "employees": len(lines), "monthly_paye": money_str(paye), "liability": money_str(paye)}
    if return_type == "cit_annual":
        if not lines:
            return {"lines": 0, "cit": "0.00", "development_levy": "0.00", "total_tax": "0.00", "liability": "0.00"}
        line = lines[0]
        return {
            "lines": 1,
            "cit": money_str(out(line, "cit")),
            "development_levy": money_str(out(line, "development_levy")),
            "total_tax": money_str(out(line, "total_tax")),
            "liability": money_str(out(line, "total_tax")),
        }
    raise ValueError(return_type)


def _refresh_totals(services: Services, ret: dict[str, Any]) -> None:
    totals = totals_for(ret["return_type"], lines_for(services, ret))
    services.db.update("ws_returns", {"totals_json": json.dumps(totals), "updated_at": iso()}, "id = ? AND org_id = ?", (ret["id"], ret["org_id"]))


def content_hash(lines: list[dict[str, Any]]) -> str:
    return sha256(
        canonical_json(
            [
                {"id": ln["id"], "kind": ln["kind"], "details": ln["details"], "inputs": ln["inputs"], "outputs": ln["result"]["outputs"], "rules_version": ln["rules_version"]}
                for ln in lines
            ]
        )
    )


def _event(services: Services, ret: dict[str, Any], actor_id: str, action: str, comment: str = "") -> None:
    services.db.insert(
        "ws_return_events",
        {"id": new_id("rev"), "return_id": ret["id"], "org_id": ret["org_id"], "actor_id": actor_id, "action": action, "comment": comment, "at": iso()},
    )


def _set_status(services: Services, ret: dict[str, Any], expected: tuple[str, ...], values: dict[str, Any]) -> None:
    """Compare-and-set on status so two reviewers cannot act on the same version."""
    marks = ", ".join("?" for _ in expected)
    changed = services.db.update(
        "ws_returns", {**values, "updated_at": iso()}, f"id = ? AND org_id = ? AND status IN ({marks})", (ret["id"], ret["org_id"], *expected)
    )
    if not changed:
        raise Conflict("The return changed while you were working on it. Reload and try again.")


# ------------------------------------------------------------------ create
def create_return(services: Services, actor: Principal, org_id: str, body: dict[str, Any]) -> dict[str, Any]:
    return_type = str(body.get("return_type") or "")
    spec = RETURN_TYPES.get(return_type)
    if spec is None:
        raise Invalid(f"return_type: must be one of {', '.join(RETURN_TYPES)}")
    period = str(body.get("period") or "").strip()
    if not (MONTHLY if spec["frequency"] == "monthly" else ANNUAL).match(period):
        raise Invalid("period: use YYYY-MM for a monthly return" if spec["frequency"] == "monthly" else "period: use YYYY for an annual return")
    org = org_row(services, org_id)
    obligation_id = str(body.get("obligation_id") or "").strip() or None
    obligation_period = due_date = None
    if obligation_id:
        obligation_period = str(body.get("obligation_period") or "").strip()
        item = find_obligation(services, org, obligation_id, obligation_period, int(period[:4]))
        due_date = str(item.get("due_date") or "") or None
    at = iso()
    row = {
        "id": new_id("ret"),
        "org_id": org_id,
        "return_type": return_type,
        "period": period,
        "title": f"{spec['label']} {period}",
        "status": "draft",
        "obligation_id": obligation_id,
        "obligation_period": obligation_period,
        "due_date": due_date,
        "totals_json": json.dumps(totals_for(return_type, [])),
        "created_by": actor.user_id,
        "created_at": at,
        "updated_at": at,
    }
    if services.db.one("SELECT 1 FROM ws_returns WHERE org_id = ? AND return_type = ? AND period = ?", (org_id, return_type, period)):
        raise Conflict("A return of this type already exists for that period")
    services.db.insert("ws_returns", row)
    _event(services, row, actor.user_id, "created")
    services.audit.record("return.create", "return", row["id"], actor_id=actor.user_id, org_id=org_id, data={"return_type": return_type, "period": period})
    return get_return(services, org_id, row["id"])


# ------------------------------------------------------------------- lines
def _compute(services: Services, ret: dict[str, Any], kind: str, details: Any, inputs: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    spec = RETURN_TYPES[ret["return_type"]]
    if kind not in spec["kinds"]:
        raise Invalid(f"kind: must be one of {', '.join(spec['kinds'])}")
    if not isinstance(details, dict) or not isinstance(inputs, dict):
        raise Invalid("inputs: must be an object")
    unknown = sorted(set(inputs) - set(spec["inputs"]))
    if unknown:
        raise Invalid(f"{unknown[0]}: not an input for this return type")
    clean_details: dict[str, str] = {}
    for key in spec["details"]:
        value = str(details.get(key) or "").strip()
        if len(value) > 200:
            raise Invalid(f"{key}: keep it under 200 characters")
        if value:
            clean_details[key] = value
    payload: dict[str, Any] = {k: inputs[k] for k in spec["inputs"] if k in inputs}
    if "date_field" in spec:
        field = spec["date_field"]
        try:
            day = dt.date.fromisoformat(str(payload.get(field) or ""))
        except ValueError:
            raise Invalid(f"{field}: enter a date (YYYY-MM-DD) in {ret['period']}") from None
        if f"{day.year:04d}-{day.month:02d}" != ret["period"]:
            raise Invalid(f"{field}: must fall in the return period {ret['period']}")
        payload[field] = day.isoformat()
    if "year_field" in spec:
        payload[spec["year_field"]] = int(ret["period"][:4])
    result = CALCULATORS[spec["calculator"]](payload, services.tree)
    return clean_details, payload, result.to_dict()


def _editable(ret: dict[str, Any]) -> None:
    if ret["status"] not in EDITABLE:
        raise Conflict("This return is locked. An owner must reopen it before it can be changed." if ret["status"] in EXPORTABLE else "This return is with a reviewer and cannot be changed now.")


def add_line(services: Services, actor: Principal, org_id: str, return_id: str, body: dict[str, Any]) -> dict[str, Any]:
    with services.db.transaction():
        ret = get_return(services, org_id, return_id)
        _editable(ret)
        spec = RETURN_TYPES[ret["return_type"]]
        count = int(services.db.scalar("SELECT COUNT(*) FROM ws_return_lines WHERE org_id = ? AND return_id = ?", (org_id, return_id)) or 0)
        if spec.get("max_lines") and count >= spec["max_lines"]:
            raise Conflict("This return takes a single computation. Edit the existing line instead.")
        if count >= 2000:
            raise Conflict("A return can hold at most 2000 lines")
        kind = str(body.get("kind") or spec["kinds"][0])
        details, payload, result = _compute(services, ret, kind, body.get("details") or {}, body.get("inputs") or {})
        at = iso()
        line_id = new_id("line")
        services.db.insert(
            "ws_return_lines",
            {
                "id": line_id,
                "return_id": return_id,
                "org_id": org_id,
                "position": count + 1,
                "kind": kind,
                "details_json": json.dumps(details),
                "inputs_json": json.dumps(payload),
                "result_json": json.dumps(result),
                "rules_version": result["rules_version"],
                "calculator": result["calculator"],
                "updated_by": actor.user_id,
                "created_at": at,
                "updated_at": at,
            },
        )
        services.db.execute("INSERT OR IGNORE INTO ws_return_makers (return_id, user_id) VALUES (?, ?)", (return_id, actor.user_id))
        _refresh_totals(services, ret)
    services.audit.record("return.line_add", "return", return_id, actor_id=actor.user_id, org_id=org_id, data={"line_id": line_id, "rules_version": result["rules_version"]})
    return {"id": line_id, "result": result}


def update_line(services: Services, actor: Principal, org_id: str, return_id: str, line_id: str, body: dict[str, Any]) -> dict[str, Any]:
    with services.db.transaction():
        ret = get_return(services, org_id, return_id)
        _editable(ret)
        line = services.db.one("SELECT * FROM ws_return_lines WHERE id = ? AND return_id = ? AND org_id = ?", (line_id, return_id, org_id))
        if line is None:
            raise NotFound("Line not found")
        kind = str(body.get("kind") or line["kind"])
        details, payload, result = _compute(
            services, ret, kind, body.get("details", json.loads(line["details_json"])), body.get("inputs", json.loads(line["inputs_json"]))
        )
        services.db.update(
            "ws_return_lines",
            {
                "kind": kind,
                "details_json": json.dumps(details),
                "inputs_json": json.dumps(payload),
                "result_json": json.dumps(result),
                "rules_version": result["rules_version"],
                "updated_by": actor.user_id,
                "updated_at": iso(),
            },
            "id = ? AND org_id = ?",
            (line_id, org_id),
        )
        services.db.execute("INSERT OR IGNORE INTO ws_return_makers (return_id, user_id) VALUES (?, ?)", (return_id, actor.user_id))
        _refresh_totals(services, ret)
    services.audit.record("return.line_update", "return", return_id, actor_id=actor.user_id, org_id=org_id, data={"line_id": line_id, "rules_version": result["rules_version"]})
    return {"id": line_id, "result": result}


def delete_line(services: Services, actor: Principal, org_id: str, return_id: str, line_id: str) -> None:
    with services.db.transaction():
        ret = get_return(services, org_id, return_id)
        _editable(ret)
        if not services.db.execute("DELETE FROM ws_return_lines WHERE id = ? AND return_id = ? AND org_id = ?", (line_id, return_id, org_id)).rowcount:
            raise NotFound("Line not found")
        services.db.execute("INSERT OR IGNORE INTO ws_return_makers (return_id, user_id) VALUES (?, ?)", (return_id, actor.user_id))
        _refresh_totals(services, ret)
    services.audit.record("return.line_delete", "return", return_id, actor_id=actor.user_id, org_id=org_id, data={"line_id": line_id})


# ---------------------------------------------------------- maker-checker
def review_block(services: Services, ret: dict[str, Any], actor: Principal, role: str) -> str | None:
    """Why ``actor`` may not approve or request changes, or None if they may."""
    if role not in CAN_REVIEW:
        return f"Your role ({role}) cannot review returns"
    if ret["status"] != "submitted_for_review":
        return "The return is not waiting for review"
    if actor.user_id == ret["submitted_by"]:
        return "You submitted this return. A different reviewer or owner must review it."
    if actor.user_id in makers(services, ret["id"]):
        return "You edited this return. A different reviewer or owner must review it."
    return None


def submit(services: Services, actor: Principal, org_id: str, return_id: str, comment: str = "") -> None:
    with services.db.transaction():
        ret = get_return(services, org_id, return_id)
        if ret["status"] not in EDITABLE:
            raise Conflict("Only a draft, or a return with changes requested, can be submitted for review")
        if not services.db.scalar("SELECT COUNT(*) FROM ws_return_lines WHERE org_id = ? AND return_id = ?", (org_id, return_id)):
            raise Conflict("Add at least one line before submitting")
        _set_status(services, ret, EDITABLE, {"status": "submitted_for_review", "submitted_by": actor.user_id, "submitted_at": iso()})
        _event(services, ret, actor.user_id, "submitted", comment[:2000])
    services.audit.record("return.submit", "return", return_id, actor_id=actor.user_id, org_id=org_id)


def approve(services: Services, actor: Principal, role: str, org_id: str, return_id: str, comment: str = "") -> None:
    with services.db.transaction():
        ret = get_return(services, org_id, return_id)
        block = review_block(services, ret, actor, role)
        if block:
            raise (Conflict if ret["status"] != "submitted_for_review" else Forbidden)(block)
        digest = content_hash(lines_for(services, ret))
        _set_status(
            services, ret, ("submitted_for_review",), {"status": "approved", "approved_by": actor.user_id, "approved_at": iso(), "approval_hash": digest}
        )
        _event(services, ret, actor.user_id, "approved", comment[:2000])
    services.audit.record("return.approve", "return", return_id, actor_id=actor.user_id, org_id=org_id, data={"approval_hash": digest})


def request_changes(services: Services, actor: Principal, role: str, org_id: str, return_id: str, comment: str) -> None:
    comment = comment.strip()
    if not comment:
        raise Invalid("comment: say what needs to change")
    with services.db.transaction():
        ret = get_return(services, org_id, return_id)
        block = review_block(services, ret, actor, role)
        if block:
            raise (Conflict if ret["status"] != "submitted_for_review" else Forbidden)(block)
        _set_status(services, ret, ("submitted_for_review",), {"status": "changes_requested"})
        _event(services, ret, actor.user_id, "changes_requested", comment[:2000])
    services.audit.record("return.request_changes", "return", return_id, actor_id=actor.user_id, org_id=org_id)


def reopen(services: Services, actor: Principal, org_id: str, return_id: str, reason: str) -> None:
    reason = reason.strip()
    if not reason:
        raise Invalid("reason: say why the return is being reopened")
    with services.db.transaction():
        ret = get_return(services, org_id, return_id)
        if ret["status"] == "filed":
            raise Conflict("A filed return cannot be reopened. Amendments go through the tax authority.")
        if ret["status"] not in ("approved", "filed_sandbox"):
            raise Conflict("Only an approved return can be reopened")
        _set_status(
            services,
            ret,
            ("approved", "filed_sandbox"),
            {"status": "draft", "submitted_by": None, "submitted_at": None, "approved_by": None, "approved_at": None, "approval_hash": None, "filed_reference": None},
        )
        services.db.execute("DELETE FROM ws_return_makers WHERE return_id = ?", (return_id,))
        _event(services, ret, actor.user_id, "reopened", reason[:2000])
    services.audit.record("return.reopen", "return", return_id, actor_id=actor.user_id, org_id=org_id, data={"from": ret["status"]})


# ---------------------------------------------------------------- reading
def summary_row(ret: dict[str, Any]) -> dict[str, Any]:
    return {
        k: ret[k]
        for k in ("id", "return_type", "period", "title", "status", "obligation_id", "obligation_period", "due_date", "created_at", "updated_at", "approved_at", "filed_reference")
    } | {"totals": json.loads(ret["totals_json"])}


def detail(services: Services, actor: Principal, role: str, org_id: str, return_id: str) -> dict[str, Any]:
    from .filing import adapter_info, payments_for, reconciliation, submissions_for

    ret = get_return(services, org_id, return_id)
    lines = lines_for(services, ret)
    events = services.db.query(
        "SELECT e.action, e.comment, e.at, e.actor_id, u.email AS actor_email FROM ws_return_events e LEFT JOIN users u ON u.id = e.actor_id "
        "WHERE e.org_id = ? AND e.return_id = ? ORDER BY e.at, e.rowid",
        (org_id, return_id),
    )
    documents = services.db.query(
        "SELECT f.id, f.name, f.content_type, f.size, f.category, d.linked_at FROM ws_return_documents d JOIN files f ON f.id = d.file_id "
        "WHERE d.org_id = ? AND d.return_id = ? AND f.org_id = ? AND f.deleted_at IS NULL ORDER BY d.linked_at",
        (org_id, return_id, org_id),
    )
    editable = ret["status"] in EDITABLE and role in CAN_EDIT
    block = review_block(services, ret, actor, role)
    filing = adapter_info(services)
    return {
        **summary_row(ret),
        "spec": next(t for t in return_types() if t["id"] == ret["return_type"]),
        "lines": lines,
        "events": events,
        "documents": documents,
        "payments": payments_for(services, ret),
        "reconciliation": reconciliation(services, ret),
        "submissions": submissions_for(services, org_id, return_id),
        "submitted_by": ret["submitted_by"],
        "approved_by": ret["approved_by"],
        "approval_hash": ret["approval_hash"],
        "locked": ret["status"] not in EDITABLE,
        "filing": filing,
        "permissions": {
            "edit": editable,
            "submit": editable and bool(lines),
            "review": block is None,
            "review_block": block if role in CAN_REVIEW and ret["status"] == "submitted_for_review" else None,
            "reopen": role in CAN_ADMIN and ret["status"] in ("approved", "filed_sandbox"),
            "export": ret["status"] in EXPORTABLE,
            "file": role in CAN_EDIT and ret["status"] in ("approved", "filed_sandbox") and not (ret["status"] == "filed_sandbox" and filing["mode"] == "sandbox"),
            "record_payment": role in CAN_EDIT,
            "link_documents": role in CAN_EDIT,
        },
    }


# ----------------------------------------------------------------- export
def build_document(services: Services, ret: dict[str, Any]) -> dict[str, Any]:
    """Authority-style layout shared by export and filing. Deterministic: no timestamps of its own."""
    org = org_row(services, ret["org_id"])
    spec = RETURN_TYPES[ret["return_type"]]
    lines = lines_for(services, ret)
    schedule = []
    for i, ln in enumerate(lines, start=1):
        row: dict[str, Any] = {"line_no": i}
        for column, source, key in spec["columns"]:
            if source == "line":
                row[column] = ln[key]
            elif source == "details":
                row[column] = ln["details"].get(key, "")
            elif source == "inputs":
                row[column] = ln["result"]["inputs"].get(key, "")
            else:
                row[column] = ln["result"]["outputs"].get(key, "")
        row["rules_version"] = ln["rules_version"]
        schedule.append(row)
    if ret["return_type"] in ("vat_monthly", "wht_monthly", "paye_monthly"):
        y, m = int(ret["period"][:4]), int(ret["period"][5:7])
        start = dt.date(y, m, 1)
        end = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1))
    else:
        start, end = dt.date(int(ret["period"]), 1, 1), dt.date(int(ret["period"]), 12, 31)
    review = sorted({ln["result"]["review_status"] for ln in lines})
    return {
        "layout": LAYOUT,
        "taxpayer": {
            "name": org["name"],
            "tin": org["tin"] or "",
            "cac_number": org["cac_number"] or "",
            "entity_type": org["entity_type"],
            "state": org["state"] or "",
        },
        "return": {
            "id": ret["id"],
            "type": ret["return_type"],
            "title": ret["title"],
            "tax": spec["tax"],
            "authority": spec["authority"],
            "period": ret["period"],
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "due_date": ret["due_date"] or "",
            "approval_hash": ret["approval_hash"] or "",
            "approved_at": ret["approved_at"] or "",
        },
        "columns": ["line_no", *[c for c, _, _ in spec["columns"]], "rules_version"],
        "schedule": schedule,
        "totals": json.loads(ret["totals_json"]),
        "rules": {
            "rules_versions": sorted({ln["rules_version"] for ln in lines}),
            "engine_versions": sorted({ln["result"]["engine_version"] for ln in lines}),
            "review_status": review,
            "citations": sorted({c for ln in lines for c in ln["result"]["citations"]}),
        },
    }


def export(services: Services, actor: Principal, org_id: str, return_id: str, fmt: str) -> tuple[str, str, str]:
    """Returns ``(content_type, filename, text)``."""
    from .filing import adapter_info

    ret = get_return(services, org_id, return_id)
    if ret["status"] not in EXPORTABLE:
        raise Conflict("Only an approved return can be exported")
    if fmt not in ("json", "csv"):
        raise Invalid("format: must be json or csv")
    document = build_document(services, ret)
    if ret["status"] == "filed":
        notice = f"Filed through an authorised integration. Acknowledgement reference {ret['filed_reference']}."
        filing_status = "filed"
    elif ret["status"] == "filed_sandbox":
        notice, filing_status = SANDBOX_NOTICE, "not_filed_sandbox_acknowledgement_only"
    else:
        authorised = adapter_info(services)["authorised"]
        notice = "Approved. Not yet filed." if authorised else OFFICIAL_CHANNELS_NOTICE
        filing_status = "not_filed"
    document = {"notice": notice, "filing_status": filing_status, "generated_at": iso(), **document}
    services.audit.record("return.export", "return", return_id, actor_id=actor.user_id, org_id=org_id, data={"format": fmt})
    name = f"taxng-{ret['return_type']}-{ret['period']}"
    if fmt == "json":
        return "application/json", f"{name}.json", json.dumps(document, indent=2)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["# tax.ng return export", LAYOUT])
    w.writerow(["# NOTICE", notice])
    w.writerow(["# filing_status", filing_status])
    w.writerow([])
    w.writerow(["section", "field", "value"])
    for section in ("taxpayer", "return"):
        for key, value in document[section].items():
            w.writerow([section, key, value])
    for key, value in document["totals"].items():
        w.writerow(["totals", key, value])
    w.writerow(["rules", "rules_versions", " ".join(document["rules"]["rules_versions"])])
    w.writerow(["rules", "review_status", " ".join(document["rules"]["review_status"])])
    w.writerow([])
    w.writerow(document["columns"])
    for row in document["schedule"]:
        w.writerow([row.get(c, "") for c in document["columns"]])
    return "text/csv", f"{name}.csv", buf.getvalue()
