"""Filing submissions (Phase 4), remittance receipts (BIZ-06) and evidence links (BIZ-03).

Submission state machine::

    prepared -> submitting -> acknowledged -> reconciled
                          \\-> rejected
                          \\-> failed

A return becomes ``filed`` only when a production adapter that is authorised
returns an acknowledgement whose HMAC signature verifies against this exact
document. A verified sandbox acknowledgement sets ``filed_sandbox``, which is
never treated as a filing anywhere (calendar, exports, summaries).

tax.ng never holds or initiates tax remittances (PRD section 9). Payments here
are receipts the taxpayer obtained from the authority's own channels.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from ...api.router import NotFound
from ...calculators.common import Fields, money_str
from ...platform.access import Principal
from ...platform.adapters import NotConfigured
from ...platform.errors import Conflict, Invalid
from ...platform.util import iso, new_id
from .adapters import PRODUCTION_NEEDS, document_hash, verify_ack
from .returns import build_document, get_return

if TYPE_CHECKING:
    from ...services import Services

TRANSITIONS = {
    "prepared": ("submitting",),
    "submitting": ("acknowledged", "rejected", "failed"),
    "acknowledged": ("reconciled",),
    "rejected": (),
    "failed": (),
    "reconciled": (),
}
CHANNELS = ("bank_branch", "remita", "nrs_portal", "state_irs_portal", "other")
SUBMISSION_FIELDS = (
    "id, org_id, return_id, idempotency_key, status, adapter, mode, document_hash, ack_reference, ack_verified, "
    "message, created_by, created_at, updated_at, reconciled_by, reconciled_at, reconcile_note"
)


def adapter_info(services: Services) -> dict[str, Any]:
    adapter = services.adapters.get("filing")
    return {
        **adapter.info(),
        "needs": None if adapter.authorised else PRODUCTION_NEEDS,
        "available": adapter.authorised,
    }


# --------------------------------------------------------------- submissions
def _present(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out.pop("ack_signature", None)  # internal: verification material, not for display
    out["ack_verified"] = bool(out["ack_verified"])
    out["sandbox"] = out["mode"] == "sandbox"
    out["counts_as_filed"] = out["mode"] == "production" and out["status"] in ("acknowledged", "reconciled") and out["ack_verified"]
    return out


def _submission(services: Services, org_id: str, submission_id: str) -> dict[str, Any]:
    row = services.db.one(f"SELECT {SUBMISSION_FIELDS}, ack_signature FROM ws_submissions WHERE id = ? AND org_id = ?", (submission_id, org_id))
    if row is None:
        raise NotFound("Submission not found")
    return row


def _move(services: Services, sub: dict[str, Any], to: str, values: dict[str, Any] | None = None) -> None:
    if to not in TRANSITIONS[sub["status"]]:
        raise Conflict(f"A submission cannot move from {sub['status']} to {to}")
    changed = services.db.update(
        "ws_submissions", {"status": to, "updated_at": iso(), **(values or {})}, "id = ? AND org_id = ? AND status = ?", (sub["id"], sub["org_id"], sub["status"])
    )
    if not changed:
        raise Conflict("The submission changed while you were working on it. Reload and try again.")
    sub["status"] = to


def submissions_for(services: Services, org_id: str, return_id: str | None = None) -> list[dict[str, Any]]:
    sql = (
        f"SELECT s.{SUBMISSION_FIELDS.replace(', ', ', s.')}, r.title AS return_title, r.status AS return_status "
        "FROM ws_submissions s JOIN ws_returns r ON r.id = s.return_id AND r.org_id = s.org_id WHERE s.org_id = ?"
    )
    params: list[Any] = [org_id]
    if return_id:
        sql += " AND s.return_id = ?"
        params.append(return_id)
    return [_present(r) for r in services.db.query(sql + " ORDER BY s.created_at DESC, s.rowid DESC", params)]


def file_return(services: Services, actor: Principal, org_id: str, return_id: str, key: str) -> tuple[bool, dict[str, Any]]:
    """Submits an approved return. Returns ``(replayed, submission)``.

    The idempotency key makes retries safe: the same key returns the original
    submission without contacting the adapter again.
    """
    key = (key or "").strip()
    if not 8 <= len(key) <= 100:
        raise Invalid("idempotency_key: send a unique key of 8 to 100 characters")
    existing = services.db.one("SELECT id, return_id FROM ws_submissions WHERE org_id = ? AND idempotency_key = ?", (org_id, key))
    if existing:
        if existing["return_id"] != return_id:
            raise Conflict("That idempotency key was used for a different return")
        return True, _present(_submission(services, org_id, existing["id"]))

    adapter = services.adapters.get("filing")
    with services.db.transaction():
        ret = get_return(services, org_id, return_id)
        if ret["status"] == "filed":
            raise Conflict("This return has already been filed")
        if ret["status"] not in ("approved", "filed_sandbox"):
            raise Conflict("Only an approved return can be filed")
        if ret["status"] == "filed_sandbox" and adapter.mode == "sandbox":
            raise Conflict("This return already has a sandbox acknowledgement")
        if services.db.scalar(
            "SELECT COUNT(*) FROM ws_submissions WHERE org_id = ? AND return_id = ? AND status IN ('prepared', 'submitting')", (org_id, return_id)
        ):
            raise Conflict("A submission for this return is already in progress")
        document = build_document(services, ret)
        digest = document_hash(document)
        at = iso()
        sub = {
            "id": new_id("sub"),
            "org_id": org_id,
            "return_id": return_id,
            "idempotency_key": key,
            "status": "prepared",
            "adapter": adapter.name,
            "mode": adapter.mode,
            "document_hash": digest,
            "created_by": actor.user_id,
            "created_at": at,
            "updated_at": at,
        }
        try:
            services.db.insert("ws_submissions", sub)
        except sqlite3.IntegrityError:
            raise Conflict("That idempotency key is already in use") from None
        _move(services, sub, "submitting")
    services.audit.record("filing.submit", "submission", sub["id"], actor_id=actor.user_id, org_id=org_id, data={"return_id": return_id, "mode": adapter.mode})

    def finish(status: str, message: str, event: str, **values: Any) -> None:
        _move(services, sub, status, {"message": message, **values})
        services.audit.record(event, "submission", sub["id"], actor_id=actor.user_id, org_id=org_id, data={"return_id": return_id, "mode": adapter.mode, "status": status})

    try:
        ack = adapter.submit(document, secret=services.secret)  # type: ignore[attr-defined]
    except NotConfigured as exc:
        finish("failed", str(exc), "filing.failed")
        raise
    except Exception:  # noqa: BLE001 (adapter faults become a failed submission, never a filing)
        finish("failed", "The filing service did not respond. Nothing was filed. Try again with a new key.", "filing.failed")
        return False, _present(_submission(services, org_id, sub["id"]))

    outcome = ack.get("outcome") if isinstance(ack, dict) else None
    if outcome == "rejected":
        finish("rejected", str(ack.get("message") or "Rejected by the filing service"), "filing.rejected")
    elif outcome == "acknowledged":
        verified = verify_ack(services.secret, ack, digest) and ack.get("mode") == adapter.mode
        real = verified and ack.get("mode") == "production" and adapter.authorised
        if not verified or (ack.get("mode") == "production" and not real):
            finish("failed", "The acknowledgement could not be verified. The return has not been marked as filed.", "filing.unverified")
        else:
            with services.db.transaction():
                finish(
                    "acknowledged",
                    str(ack.get("message") or ""),
                    "filing.acknowledged",
                    ack_reference=str(ack["reference"]),
                    ack_signature=str(ack["signature"]),
                    ack_verified=1,
                )
                new_status = "filed" if real else "filed_sandbox"
                services.db.update(
                    "ws_returns",
                    {"status": new_status, "filed_reference": str(ack["reference"]), "updated_at": iso()},
                    "id = ? AND org_id = ? AND status IN ('approved', 'filed_sandbox')",
                    (return_id, org_id),
                )
                services.db.insert(
                    "ws_return_events",
                    {
                        "id": new_id("rev"),
                        "return_id": return_id,
                        "org_id": org_id,
                        "actor_id": actor.user_id,
                        "action": new_status,
                        "comment": f"{'Sandbox acknowledgement' if not real else 'Acknowledgement'} {ack['reference']}",
                        "at": iso(),
                    },
                )
            services.audit.record(f"return.{new_status}", "return", return_id, actor_id=actor.user_id, org_id=org_id, data={"submission_id": sub["id"]})
    else:
        finish("failed", "The filing service gave an unrecognised response. Nothing was filed.", "filing.failed")
    return False, _present(_submission(services, org_id, sub["id"]))


def reconcile_submission(services: Services, actor: Principal, org_id: str, submission_id: str, note: str) -> dict[str, Any]:
    sub = _submission(services, org_id, submission_id)
    if sub["status"] != "acknowledged":
        raise Conflict("Only an acknowledged submission can be reconciled")
    ack = {"reference": sub["ack_reference"], "mode": sub["mode"], "document_hash": sub["document_hash"], "signature": sub["ack_signature"]}
    if not verify_ack(services.secret, ack, sub["document_hash"]):
        raise Conflict("The stored acknowledgement no longer verifies. Do not rely on it.")
    _move(services, sub, "reconciled", {"reconciled_by": actor.user_id, "reconciled_at": iso(), "reconcile_note": note.strip()[:500]})
    services.audit.record("filing.reconciled", "submission", submission_id, actor_id=actor.user_id, org_id=org_id, data={"mode": sub["mode"]})
    return _present(_submission(services, org_id, submission_id))


# ------------------------------------------------------------------ payments
def payments_for(services: Services, ret: dict[str, Any]) -> list[dict[str, Any]]:
    return services.db.query(
        "SELECT id, receipt_reference, amount, paid_on, channel, file_id, recorded_by, created_at FROM ws_payments "
        "WHERE org_id = ? AND return_id = ? AND voided_at IS NULL ORDER BY paid_on, created_at",
        (ret["org_id"], ret["id"]),
    )


def reconciliation(services: Services, ret: dict[str, Any]) -> dict[str, Any]:
    liability = Decimal(str(json.loads(ret["totals_json"]).get("liability") or "0"))
    remitted = sum((Decimal(p["amount"]) for p in payments_for(services, ret)), Decimal(0))
    difference = remitted - liability
    if liability == 0 and remitted == 0:
        status = "nothing_due"
    elif remitted == 0:
        status = "unpaid"
    elif difference < 0:
        status = "underpaid"
    elif difference > 0:
        status = "overpaid"
    else:
        status = "paid"
    flags = {
        "unpaid": "No remittance receipt recorded against this return.",
        "underpaid": "Remitted amount is less than the liability on the return.",
        "overpaid": "Remitted amount is more than the liability on the return. Check the receipt or the return.",
    }
    return {
        "liability": money_str(liability),
        "remitted": money_str(remitted),
        "difference": money_str(difference),
        "status": status,
        "flag": flags.get(status),
    }


def _org_file(services: Services, org_id: str, file_id: str) -> dict[str, Any]:
    row = services.db.one("SELECT * FROM files WHERE id = ? AND org_id = ? AND deleted_at IS NULL", (file_id, org_id))
    if row is None:
        raise NotFound("Document not found")
    return row


def record_payment(services: Services, actor: Principal, org_id: str, return_id: str, body: dict[str, Any]) -> dict[str, Any]:
    ret = get_return(services, org_id, return_id)
    reference = str(body.get("receipt_reference") or "").strip()
    if not reference or len(reference) > 80:
        raise Invalid("receipt_reference: enter the authority's receipt reference (up to 80 characters)")
    f = Fields(body)
    amount = f.money("amount", required=True)
    paid_on = f.date("paid_on", default=dt.date.today())
    f.finish()
    if amount <= 0:
        raise Invalid("amount: must be more than zero")
    if paid_on > dt.date.today():
        raise Invalid("paid_on: cannot be in the future")
    channel = str(body.get("channel") or "")
    if channel not in CHANNELS:
        raise Invalid(f"channel: must be one of {', '.join(CHANNELS)}")
    file_id = str(body.get("file_id") or "") or None
    if file_id:
        _org_file(services, org_id, file_id)
    row = {
        "id": new_id("pay"),
        "org_id": org_id,
        "return_id": ret["id"],
        "receipt_reference": reference,
        "amount": money_str(amount),
        "paid_on": paid_on.isoformat(),
        "channel": channel,
        "file_id": file_id,
        "recorded_by": actor.user_id,
        "created_at": iso(),
    }
    try:
        services.db.insert("ws_payments", row)
    except sqlite3.IntegrityError:
        raise Conflict("That receipt reference is already recorded for this organisation") from None
    services.audit.record("payment.record", "return", return_id, actor_id=actor.user_id, org_id=org_id, data={"payment_id": row["id"], "amount": row["amount"], "channel": channel})
    return {"payment": row, "reconciliation": reconciliation(services, ret)}


def void_payment(services: Services, actor: Principal, org_id: str, payment_id: str) -> None:
    row = services.db.one("SELECT * FROM ws_payments WHERE id = ? AND org_id = ? AND voided_at IS NULL", (payment_id, org_id))
    if row is None:
        raise NotFound("Payment not found")
    services.db.update("ws_payments", {"voided_at": iso(), "voided_by": actor.user_id}, "id = ? AND org_id = ?", (payment_id, org_id))
    services.audit.record("payment.void", "return", row["return_id"], actor_id=actor.user_id, org_id=org_id, data={"payment_id": payment_id})


def org_payments(services: Services, org_id: str) -> list[dict[str, Any]]:
    rows = services.db.query("SELECT * FROM ws_returns WHERE org_id = ? ORDER BY period DESC", (org_id,))
    out = []
    for ret in rows:
        payments = payments_for(services, ret)
        rec = reconciliation(services, ret)
        if payments or ret["status"] in ("approved", "filed_sandbox", "filed"):
            out.append({"return_id": ret["id"], "title": ret["title"], "status": ret["status"], "payments": payments, "reconciliation": rec})
    return out


# ----------------------------------------------------------------- documents
def link_document(services: Services, actor: Principal, org_id: str, return_id: str, file_id: str) -> None:
    get_return(services, org_id, return_id)
    _org_file(services, org_id, file_id)
    services.db.execute(
        "INSERT OR IGNORE INTO ws_return_documents (return_id, file_id, org_id, linked_by, linked_at) VALUES (?, ?, ?, ?, ?)",
        (return_id, file_id, org_id, actor.user_id, iso()),
    )
    services.audit.record("return.document_link", "return", return_id, actor_id=actor.user_id, org_id=org_id, data={"file_id": file_id})


def unlink_document(services: Services, actor: Principal, org_id: str, return_id: str, file_id: str) -> None:
    get_return(services, org_id, return_id)
    if not services.db.execute("DELETE FROM ws_return_documents WHERE return_id = ? AND file_id = ? AND org_id = ?", (return_id, file_id, org_id)).rowcount:
        raise NotFound("Document is not linked to this return")
    services.audit.record("return.document_unlink", "return", return_id, actor_id=actor.user_id, org_id=org_id, data={"file_id": file_id})


def document_links(services: Services, org_id: str) -> dict[str, list[dict[str, str]]]:
    """file_id -> returns it is evidence for (for the vault view)."""
    out: dict[str, list[dict[str, str]]] = {}
    for r in services.db.query(
        "SELECT d.file_id, r.id, r.title FROM ws_return_documents d JOIN ws_returns r ON r.id = d.return_id AND r.org_id = d.org_id WHERE d.org_id = ?",
        (org_id,),
    ):
        out.setdefault(r["file_id"], []).append({"return_id": r["id"], "title": r["title"]})
    return out
