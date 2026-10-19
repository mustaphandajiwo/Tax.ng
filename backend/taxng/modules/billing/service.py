"""Billing: plans, subscriptions, checkout, verified payment webhooks and receipts (PRD section 9).

Commercial payments only. tax.ng never holds tax remittances, so ``purpose``
is limited to commercial services and there is no tax purpose at all.

Payment flow::

    create_checkout -> provider session (pending)
    provider webhook (HMAC verified, event id deduplicated) -> paid
    -> receipt issued -> registered handler for the purpose called once

Prices come from content/billing/plans.yaml and are placeholders until set
after validation (``price_status: placeholder``).
"""

from __future__ import annotations

import calendar
import datetime as dt
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import yaml

from ...platform.access import NotFoundError, Unauthorized
from ...platform.adapters import Adapter
from ...platform.errors import Conflict, Invalid
from ...platform.util import canonical_json, iso, new_id, now, sign, verify_signature

if TYPE_CHECKING:
    from ...services import Services

log = logging.getLogger("taxng.billing")

PURPOSES = ("subscription", "course", "advisory", "sponsorship", "advertising")
PLACEHOLDER_LABEL = "Placeholder price, to be set after validation"
MAX_SEATS = 1000

PaymentHandler = Callable[["Services", dict[str, Any]], None]


def _add_months(day: dt.datetime, months: int) -> dt.datetime:
    month = day.month - 1 + months
    year, month = day.year + month // 12, month % 12 + 1
    return day.replace(year=year, month=month, day=min(day.day, calendar.monthrange(year, month)[1]))


def load_plans(services: Services) -> dict[str, dict[str, Any]]:
    path = services.content_dir / "billing" / "plans.yaml"
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    plans: dict[str, dict[str, Any]] = {}
    for plan in data.get("plans", []):
        if plan.get("price_status") not in ("placeholder", "approved"):
            raise ValueError(f"plan {plan.get('id')}: price_status must be placeholder or approved")
        if not isinstance(plan.get("price_kobo"), int) or plan["price_kobo"] <= 0:
            raise ValueError(f"plan {plan.get('id')}: price_kobo must be a positive integer")
        if plan.get("scope") not in ("org", "user"):
            raise ValueError(f"plan {plan.get('id')}: scope must be org or user")
        plans[plan["id"]] = {**plan, "currency": data.get("currency", "NGN")}
    return plans


class Billing:
    """``services.modules["billing"]``. See docs/MODULES.md for the contract."""

    def __init__(self, services: Services) -> None:
        self.services = services
        self.db = services.db
        self.plans = load_plans(services)
        self._handlers: dict[str, list[PaymentHandler]] = {}

    @property
    def adapter(self) -> Adapter:
        return self.services.adapters.get("payments")

    @property
    def webhook_secret(self) -> str:
        """Provider webhook signing secret (production: issued by the PSP)."""
        return sign(self.services.secret, "billing:psp-webhook")

    # --------------------------------------------------------------- plans
    def plan_view(self, plan: dict[str, Any]) -> dict[str, Any]:
        return {
            **{k: plan.get(k) for k in ("id", "name", "category", "scope", "interval", "unit", "price_kobo", "currency", "price_status", "features")},
            "seats": bool(plan.get("seats")),
            "price_label": PLACEHOLDER_LABEL if plan["price_status"] == "placeholder" else None,
        }

    def list_plans(self) -> list[dict[str, Any]]:
        return [self.plan_view(p) for p in self.plans.values()]

    # ------------------------------------------------------------ contract
    def register_payment_handler(self, purpose: str, fn: PaymentHandler) -> None:
        if purpose not in PURPOSES:
            raise ValueError(f"Unknown payment purpose {purpose!r}")
        self._handlers.setdefault(purpose, []).append(fn)

    def create_checkout(
        self,
        *,
        payer_user_id: str,
        org_id: str | None,
        purpose: str,
        reference_id: str,
        amount_kobo: int,
        description: str,
    ) -> dict[str, Any]:
        if purpose not in PURPOSES:
            raise Invalid(f"purpose: must be one of {', '.join(PURPOSES)}. Tax remittances never pass through tax.ng billing")
        if not isinstance(amount_kobo, int) or isinstance(amount_kobo, bool) or amount_kobo <= 0:
            raise Invalid("amount_kobo: must be a positive whole number of kobo")
        if not reference_id:
            raise Invalid("reference_id: is required")
        if not description:
            raise Invalid("description: is required")
        checkout_id = new_id("chk")
        adapter = self.adapter
        session = adapter.create_session({"checkout_id": checkout_id, "amount_kobo": amount_kobo, "currency": "NGN", "description": description})  # type: ignore[attr-defined]
        payment_id = new_id("pay")
        self.db.insert(
            "billing_payments",
            {
                "id": payment_id,
                "checkout_id": checkout_id,
                "purpose": purpose,
                "reference_id": str(reference_id)[:100],
                "payer_user_id": payer_user_id,
                "org_id": org_id,
                "amount_kobo": amount_kobo,
                "currency": "NGN",
                "description": str(description)[:200],
                "status": "pending",
                "provider": adapter.name,
                "provider_ref": session["provider_ref"],
                "mode": session["mode"],
                "created_at": iso(),
            },
        )
        self.services.audit.record(
            "billing.checkout_created", "payment", payment_id, actor_id=payer_user_id, org_id=org_id, data={"purpose": purpose, "amount_kobo": amount_kobo, "mode": session["mode"]}
        )
        return {"checkout_id": checkout_id, "url": session["url"], "mode": session["mode"]}

    # ------------------------------------------------------------ payments
    def payment_by_checkout(self, checkout_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM billing_payments WHERE checkout_id = ?", (checkout_id,))
        if row is None:
            raise NotFoundError("Checkout not found")
        return row

    def can_see(self, principal_user_id: str, memberships: dict[str, str], row: dict[str, Any]) -> bool:
        if row["org_id"]:
            return memberships.get(row["org_id"]) == "owner" or row["payer_user_id"] == principal_user_id
        return row["payer_user_id"] == principal_user_id

    def simulate(self, checkout_id: str, actor_id: str, outcome: str) -> dict[str, Any]:
        """Demo only: stands in for the provider's hosted page, then delivers its signed webhook."""
        adapter = self.adapter
        if adapter.mode != "sandbox":
            raise NotFoundError("Not available")
        if outcome not in ("paid", "failed"):
            raise Invalid("outcome: must be paid or failed")
        payment = self.payment_by_checkout(checkout_id)
        if payment["payer_user_id"] != actor_id:
            raise NotFoundError("Checkout not found")
        payload, signature = adapter.simulate_webhook(payment, outcome, self.webhook_secret)  # type: ignore[attr-defined]
        result = self.handle_webhook(payload, signature)
        return {**result, "mode": adapter.mode}

    def handle_webhook(self, payload: Any, signature: str) -> dict[str, Any]:
        """Verifies the provider's HMAC signature, deduplicates by event id, then marks paid."""
        if not isinstance(payload, dict) or not verify_signature(self.webhook_secret, canonical_json(payload), signature):
            raise Unauthorized("Invalid webhook signature")
        event_id, event = str(payload.get("id") or ""), payload.get("event")
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        if not event_id or event not in ("charge.success", "charge.failed"):
            raise Invalid("event: unsupported webhook event")
        newly_paid = False
        with self.db.transaction():
            if self.db.scalar("SELECT 1 FROM billing_webhook_events WHERE event_id = ?", (event_id,)):
                return {"status": "duplicate", "event_id": event_id}
            payment = self.db.one("SELECT * FROM billing_payments WHERE checkout_id = ?", (str(data.get("reference", "")),))
            if payment is None:
                raise NotFoundError("Unknown payment reference")
            if data.get("amount_kobo") != payment["amount_kobo"] or data.get("currency") != payment["currency"]:
                outcome = "amount_mismatch"
            elif event == "charge.success":
                newly_paid = self.db.update("billing_payments", {"status": "paid", "paid_at": iso()}, "id = ? AND status = 'pending'", (payment["id"],)) == 1
                outcome = "paid" if newly_paid else "ignored"
            else:
                failed = self.db.update("billing_payments", {"status": "failed"}, "id = ? AND status = 'pending'", (payment["id"],)) == 1
                outcome = "failed" if failed else "ignored"
            self.db.insert(
                "billing_webhook_events",
                {"event_id": event_id, "event_type": event, "checkout_id": payment["checkout_id"], "outcome": outcome, "received_at": iso()},
            )
            receipt = self._issue_receipt(payment) if newly_paid else None
        self.services.audit.record(
            f"billing.webhook_{outcome}", "payment", payment["id"], org_id=payment["org_id"], data={"event": event, "mode": payment["mode"]}
        )
        if newly_paid:
            self._dispatch(self.db.one("SELECT * FROM billing_payments WHERE id = ?", (payment["id"],)) or payment)
        return {"status": outcome, "event_id": event_id, "checkout_id": payment["checkout_id"], "receipt_id": receipt["id"] if receipt else None}

    def _issue_receipt(self, payment: dict[str, Any]) -> dict[str, Any]:
        seq = int(self.db.scalar("SELECT COUNT(*) FROM billing_receipts") or 0) + 1
        prefix = "TNG-SBX" if payment["mode"] == "sandbox" else "TNG"
        receipt = {
            "id": new_id("rct"),
            "number": f"{prefix}-{now().year}-{seq:06d}",
            "payment_id": payment["id"],
            "payer_user_id": payment["payer_user_id"],
            "org_id": payment["org_id"],
            "description": payment["description"],
            "amount_kobo": payment["amount_kobo"],
            "currency": payment["currency"],
            "mode": payment["mode"],
            "issued_at": iso(),
        }
        self.db.insert("billing_receipts", receipt)
        return receipt

    def _dispatch(self, payment: dict[str, Any]) -> None:
        """Calls each handler registered for the purpose. Runs once per payment (guarded by the pending -> paid update)."""
        errors = []
        for fn in self._handlers.get(payment["purpose"], []):
            try:
                fn(self.services, dict(payment))
            except Exception as exc:  # noqa: BLE001 - a failing handler must not lose the payment record
                log.exception("payment handler failed")
                errors.append(f"{getattr(fn, '__name__', 'handler')}: {exc}")
        self.db.update(
            "billing_payments", {"handled_at": iso(), "handler_error": "; ".join(errors)[:500] or None}, "id = ?", (payment["id"],)
        )
        developer = self.services.modules.get("developer")
        if developer is not None and payment["org_id"]:
            try:
                developer.emit(payment["org_id"], "payment.paid", {"checkout_id": payment["checkout_id"], "purpose": payment["purpose"], "amount_kobo": payment["amount_kobo"], "mode": payment["mode"]})
            except Exception:  # noqa: BLE001
                log.exception("webhook emit failed")

    def payments(self, *, user_id: str, org_id: str | None) -> list[dict[str, Any]]:
        if org_id:
            rows = self.db.query("SELECT * FROM billing_payments WHERE org_id = ? ORDER BY created_at DESC, rowid DESC", (org_id,))
        else:
            rows = self.db.query(
                "SELECT * FROM billing_payments WHERE org_id IS NULL AND payer_user_id = ? ORDER BY created_at DESC, rowid DESC", (user_id,)
            )
        receipts = {r["payment_id"]: r["id"] for r in self.db.query("SELECT id, payment_id FROM billing_receipts")}
        return [{**self._payment_view(r), "receipt_id": receipts.get(r["id"])} for r in rows]

    def _payment_view(self, r: dict[str, Any]) -> dict[str, Any]:
        keys = ("id", "checkout_id", "purpose", "reference_id", "org_id", "amount_kobo", "currency", "description", "status", "provider", "mode", "created_at", "paid_at")
        return {k: r[k] for k in keys}

    def checkout_view(self, row: dict[str, Any]) -> dict[str, Any]:
        return {**self._payment_view(row), "mode": row["mode"]}

    def receipt(self, receipt_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM billing_receipts WHERE id = ?", (receipt_id,))
        if row is None:
            raise NotFoundError("Receipt not found")
        return row

    def receipt_view(self, row: dict[str, Any]) -> dict[str, Any]:
        org = self.db.one("SELECT name, tin FROM organisations WHERE id = ?", (row["org_id"],)) if row["org_id"] else None
        return {
            **{k: v for k, v in row.items() if k != "payer_user_id"},
            "seller": "Astound Innovation Hub (tax.ng)",
            "billed_to": org["name"] if org else None,
            "billed_to_tin": org["tin"] if org else None,
            "nature": "Commercial service fee. This is not a tax payment or a tax receipt.",
            "sandbox_note": "Sandbox receipt: no money moved." if row["mode"] == "sandbox" else None,
        }

    # -------------------------------------------------------- subscriptions
    def subscribe(self, *, actor_id: str, plan_id: str, org_id: str | None, quantity: int = 1) -> dict[str, Any]:
        plan = self.plans.get(plan_id)
        if plan is None:
            raise NotFoundError("Plan not found")
        if plan["scope"] == "org" and not org_id:
            raise Invalid("org_id: this plan is for a business workspace; choose one first")
        if plan["scope"] == "user" and org_id:
            raise Invalid("org_id: this is a personal plan; switch to your personal account")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or not 1 <= quantity <= MAX_SEATS:
            raise Invalid(f"quantity: must be a whole number from 1 to {MAX_SEATS}")
        if quantity > 1 and not plan.get("seats"):
            raise Invalid("quantity: only seat-based plans take a quantity")
        subject_col, subject = ("org_id", org_id) if org_id else ("user_id", actor_id)
        if self.db.scalar(f"SELECT 1 FROM billing_subscriptions WHERE {subject_col} = ? AND plan_id = ? AND status = 'active'", (subject, plan_id)):
            raise Conflict("This plan is already active")
        pending = self.db.one(
            f"SELECT * FROM billing_subscriptions WHERE {subject_col} = ? AND plan_id = ? AND status = 'pending' AND quantity = ?", (subject, plan_id, quantity)
        )
        if pending:
            payment = self.payment_by_checkout(pending["checkout_id"])
            if payment["status"] == "pending":
                return {"subscription": self.subscription_view(pending), "checkout": {"checkout_id": payment["checkout_id"], "url": self.adapter.create_session({"checkout_id": payment["checkout_id"]})["url"], "mode": payment["mode"]}}  # type: ignore[attr-defined]
        sub_id = new_id("sub")
        self.db.insert(
            "billing_subscriptions",
            {
                "id": sub_id,
                "plan_id": plan_id,
                "category": plan["category"],
                "org_id": org_id,
                "user_id": None if org_id else actor_id,
                "quantity": quantity,
                "status": "pending",
                "created_by": actor_id,
                "created_at": iso(),
            },
        )
        checkout = self.create_checkout(
            payer_user_id=actor_id,
            org_id=org_id,
            purpose="subscription",
            reference_id=sub_id,
            amount_kobo=plan["price_kobo"] * quantity,
            description=f"{plan['name']}" + (f" x {quantity} seats" if plan.get("seats") else "") + f", per {plan['interval']}",
        )
        self.db.update("billing_subscriptions", {"checkout_id": checkout["checkout_id"]}, "id = ?", (sub_id,))
        self.services.audit.record("billing.subscription_created", "subscription", sub_id, actor_id=actor_id, org_id=org_id, data={"plan_id": plan_id, "quantity": quantity})
        return {"subscription": self.subscription_view(self._sub(sub_id)), "checkout": checkout}

    def _sub(self, sub_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM billing_subscriptions WHERE id = ?", (sub_id,))
        if row is None:
            raise NotFoundError("Subscription not found")
        return row

    def subscription_view(self, row: dict[str, Any]) -> dict[str, Any]:
        plan = self.plans.get(row["plan_id"])
        return {
            **{k: row[k] for k in ("id", "plan_id", "category", "org_id", "quantity", "status", "checkout_id", "current_period_start", "current_period_end", "created_at", "cancelled_at")},
            "plan": self.plan_view(plan) if plan else None,
            "personal": row["user_id"] is not None,
        }

    def subscriptions(self, *, user_id: str, org_id: str | None) -> list[dict[str, Any]]:
        if org_id:
            rows = self.db.query("SELECT * FROM billing_subscriptions WHERE org_id = ? ORDER BY created_at DESC, rowid DESC", (org_id,))
        else:
            rows = self.db.query("SELECT * FROM billing_subscriptions WHERE user_id = ? ORDER BY created_at DESC, rowid DESC", (user_id,))
        return [self.subscription_view(r) for r in rows]

    def cancel_subscription(self, sub: dict[str, Any], actor_id: str) -> dict[str, Any]:
        if sub["status"] not in ("pending", "active"):
            raise Conflict(f"This subscription is already {sub['status']}")
        self.db.update("billing_subscriptions", {"status": "cancelled", "cancelled_at": iso()}, "id = ? AND status = ?", (sub["id"], sub["status"]))
        self.services.audit.record("billing.subscription_cancelled", "subscription", sub["id"], actor_id=actor_id, org_id=sub["org_id"])
        return self.subscription_view(self._sub(sub["id"]))

    def activate_subscription(self, services: Services, payment: dict[str, Any]) -> None:
        """Payment handler for purpose ``subscription``."""
        sub = self.db.one("SELECT * FROM billing_subscriptions WHERE id = ?", (payment["reference_id"],))
        if sub is None or sub["status"] != "pending":
            return
        plan = self.plans.get(sub["plan_id"], {})
        start = now()
        end = _add_months(start, 12 if plan.get("interval") == "year" else 1)
        subject_col, subject = ("org_id", sub["org_id"]) if sub["org_id"] else ("user_id", sub["user_id"])
        with self.db.transaction():
            self.db.update(
                "billing_subscriptions",
                {"status": "superseded", "cancelled_at": iso()},
                f"{subject_col} = ? AND category = ? AND status = 'active' AND id <> ?",
                (subject, sub["category"], sub["id"]),
            )
            self.db.update(
                "billing_subscriptions",
                {"status": "active", "current_period_start": iso(start), "current_period_end": iso(end)},
                "id = ?",
                (sub["id"],),
            )
        self.services.audit.record("billing.subscription_activated", "subscription", sub["id"], org_id=sub["org_id"], data={"plan_id": sub["plan_id"], "mode": payment["mode"]})
