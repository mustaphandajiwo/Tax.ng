"""Billing: placeholder prices, owner-only org billing, signed webhooks, handlers called once, receipts."""

from __future__ import annotations

from taxng.platform.errors import Invalid
from taxng.platform.util import canonical_json, sign

from ..helpers import Client, ServicesTestCase, add_member, create_org


class Plans(ServicesTestCase):
    def test_plans_are_public_and_marked_placeholder(self) -> None:
        status, body = Client(self.services).get("/api/billing/plans")
        self.assertEqual(status, 200)
        self.assertEqual(body["mode"], "sandbox")
        self.assertTrue(body["items"])
        for plan in body["items"]:
            self.assertEqual(plan["price_status"], "placeholder")
            self.assertEqual(plan["price_label"], "Placeholder price, to be set after validation")
            self.assertIsInstance(plan["price_kobo"], int)


class Access(ServicesTestCase):
    def test_org_billing_is_owner_only(self) -> None:
        owner = self.client("bill-owner@example.com")
        org = create_org(owner)
        self.assertEqual(Client(self.services).post("/api/billing/subscriptions", {"plan_id": "workspace_starter", "org_id": org}).status, 401)
        outsider = self.client("bill-outsider@example.com")
        self.assertEqual(outsider.post("/api/billing/subscriptions", {"plan_id": "workspace_starter", "org_id": org}).status, 404)
        self.assertEqual(outsider.get("/api/billing/payments", {"org_id": org}).status, 404)
        preparer = self.client("bill-preparer@example.com")
        add_member(self.services, org, preparer, "preparer")
        self.assertEqual(preparer.post("/api/billing/subscriptions", {"plan_id": "workspace_starter", "org_id": org}).status, 403)
        self.assertEqual(preparer.get("/api/billing/payments", {"org_id": org}).status, 403)

    def test_plan_scope_is_enforced(self) -> None:
        owner = self.client("bill-scope@example.com")
        org = create_org(owner)
        self.assertEqual(owner.post("/api/billing/subscriptions", {"plan_id": "workspace_starter"}).status, 422)
        self.assertEqual(owner.post("/api/billing/subscriptions", {"plan_id": "personal_plus", "org_id": org}).status, 422)
        self.assertEqual(owner.post("/api/billing/subscriptions", {"plan_id": "workspace_starter", "org_id": org, "quantity": 3}).status, 422)
        self.assertEqual(owner.post("/api/billing/subscriptions", {"plan_id": "nope", "org_id": org}).status, 404)


class Subscriptions(ServicesTestCase):
    def test_checkout_complete_activates_and_issues_receipt(self) -> None:
        owner = self.client("bill-sub@example.com")
        org = create_org(owner)
        status, body = owner.post("/api/billing/subscriptions", {"plan_id": "institutional_seats", "org_id": org, "quantity": 4})
        self.assertEqual(status, 201, body)
        checkout = body["checkout"]
        self.assertEqual(checkout["mode"], "sandbox")
        self.assertIn(checkout["checkout_id"], checkout["url"])
        self.assertEqual(body["subscription"]["status"], "pending")
        plan_price = self.services.modules["billing"].plans["institutional_seats"]["price_kobo"]
        status, chk = owner.get(f"/api/billing/checkout/{checkout['checkout_id']}")
        self.assertEqual((status, chk["amount_kobo"], chk["status"]), (200, plan_price * 4, "pending"))
        status, done = owner.post(f"/api/billing/checkout/{checkout['checkout_id']}/complete", {"outcome": "paid"})
        self.assertEqual((status, done["status"], done["mode"]), (200, "paid", "sandbox"))
        subs = owner.get("/api/billing/subscriptions", {"org_id": org}).body["items"]
        self.assertEqual(subs[0]["status"], "active")
        self.assertTrue(subs[0]["current_period_end"])
        payments = owner.get("/api/billing/payments", {"org_id": org}).body["items"]
        self.assertEqual(payments[0]["status"], "paid")
        status, receipt = owner.get(f"/api/billing/receipts/{payments[0]['receipt_id']}")
        self.assertEqual(status, 200)
        self.assertTrue(receipt["number"].startswith("TNG-SBX-"))
        self.assertEqual(receipt["sandbox_note"], "Sandbox receipt: no money moved.")
        self.assertIn("not a tax payment", receipt["nature"])
        # Another user cannot read the receipt or the checkout.
        stranger = self.client("bill-stranger@example.com")
        self.assertEqual(stranger.get(f"/api/billing/receipts/{receipt['id']}").status, 404)
        self.assertEqual(stranger.get(f"/api/billing/checkout/{checkout['checkout_id']}").status, 404)
        self.assertEqual(stranger.post(f"/api/billing/checkout/{checkout['checkout_id']}/complete").status, 404)
        # Already active: a second subscription to the same plan is refused.
        self.assertEqual(owner.post("/api/billing/subscriptions", {"plan_id": "institutional_seats", "org_id": org, "quantity": 4}).status, 409)

    def test_personal_plan_and_failed_payment(self) -> None:
        user = self.client("bill-personal@example.com")
        body = user.post("/api/billing/subscriptions", {"plan_id": "personal_plus"}).body
        status, done = user.post(f"/api/billing/checkout/{body['checkout']['checkout_id']}/complete", {"outcome": "failed"})
        self.assertEqual((status, done["status"]), (200, "failed"))
        self.assertEqual(user.get("/api/billing/subscriptions").body["items"][0]["status"], "pending")
        self.assertEqual(user.get("/api/billing/payments").body["items"][0]["status"], "failed")


class Webhooks(ServicesTestCase):
    calls_log: list[str]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.calls_log = []
        cls.services.modules["billing"].register_payment_handler("course", lambda services, payment: cls.calls_log.append(payment["checkout_id"]))

    def setUp(self) -> None:
        self.billing = self.services.modules["billing"]

    def _checkout(self, email: str) -> tuple[Client, dict]:
        user = self.client(email)
        chk = self.billing.create_checkout(payer_user_id=user.user_id, org_id=None, purpose="course", reference_id="course_1", amount_kobo=500000, description="Course fee")
        return user, chk

    def _event(self, chk: dict, event_id: str, amount: int = 500000, event: str = "charge.success") -> dict:
        payment = self.billing.payment_by_checkout(chk["checkout_id"])
        return {"id": event_id, "event": event, "data": {"reference": chk["checkout_id"], "provider_ref": payment["provider_ref"], "amount_kobo": amount, "currency": "NGN"}}

    def _post(self, payload: dict, signature: str | None = None):
        psp = Client(self.services)
        psp.headers = {"x-psp-signature": signature if signature is not None else sign(self.billing.webhook_secret, canonical_json(payload))}
        return psp.post("/api/billing/webhooks/psp", payload)

    def test_bad_signature_rejected_and_nothing_paid(self) -> None:
        _, chk = self._checkout("wh-bad@example.com")
        payload = self._event(chk, "evt_bad")
        self.assertEqual(self._post(payload, "0" * 64).status, 401)
        self.assertEqual(self._post({**payload, "data": {**payload["data"], "amount_kobo": 1}}, sign(self.billing.webhook_secret, canonical_json(payload))).status, 401)
        self.assertEqual(self.billing.payment_by_checkout(chk["checkout_id"])["status"], "pending")

    def test_handler_runs_exactly_once_and_replay_is_idempotent(self) -> None:
        _, chk = self._checkout("wh-once@example.com")
        payload = self._event(chk, "evt_once")
        status, body = self._post(payload)
        self.assertEqual((status, body["status"]), (200, "paid"))
        self.assertEqual(self._post(payload).body["status"], "duplicate")
        # A different event for the same, already-paid payment does not run handlers again.
        self.assertEqual(self._post(self._event(chk, "evt_once_2")).body["status"], "ignored")
        self.assertEqual(self.calls_log.count(chk["checkout_id"]), 1)
        self.assertIsNotNone(self.billing.payment_by_checkout(chk["checkout_id"])["handled_at"])

    def test_amount_mismatch_is_not_paid(self) -> None:
        _, chk = self._checkout("wh-amount@example.com")
        self.assertEqual(self._post(self._event(chk, "evt_amount", amount=1)).body["status"], "amount_mismatch")
        self.assertEqual(self.billing.payment_by_checkout(chk["checkout_id"])["status"], "pending")
        self.assertNotIn(chk["checkout_id"], self.calls_log)

    def test_tax_remittance_is_not_a_billing_purpose(self) -> None:
        user = self.client("wh-tax@example.com")
        with self.assertRaises(Invalid):
            self.billing.create_checkout(payer_user_id=user.user_id, org_id=None, purpose="tax", reference_id="x", amount_kobo=100, description="VAT")
        with self.assertRaises(Invalid):
            self.billing.create_checkout(payer_user_id=user.user_id, org_id=None, purpose="course", reference_id="x", amount_kobo=10.5, description="Fee")  # type: ignore[arg-type]
