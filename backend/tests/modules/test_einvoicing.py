"""E-invoicing: access, validation, lifecycle, idempotency, callbacks, event log, import."""

from __future__ import annotations

import datetime as dt
import sqlite3
from decimal import Decimal

from taxng.calculators import calculate_vat
from taxng.modules.einvoicing.adapters import ProductionNrsEInvoicing
from taxng.platform.util import canonical_json, sign

from ..helpers import Client, ServicesTestCase, add_member, create_org

TODAY = dt.date.today().isoformat()


def invoice(number: str = "INV-001", buyer_tin: str = "87654321-0001", **extra: object) -> dict:
    body = {
        "invoice_number": number,
        "issue_date": TODAY,
        "buyer_name": "Buyer Ltd",
        "buyer_tin": buyer_tin,
        "lines": [
            {"description": "Consulting", "quantity": "2", "unit_price": "50000", "vat_category": "standard"},
            {"description": "Exported service", "quantity": "1", "unit_price": "10000", "vat_category": "zero_rated"},
            {"description": "Medical supplies", "quantity": "3", "unit_price": "1000.50", "vat_category": "exempt"},
        ],
    }
    body.update(extra)
    return body


class Base(ServicesTestCase):
    def setup_org(self, email: str, tin: str = "12345678-0001") -> tuple[Client, str]:
        owner = self.client(email)
        org = create_org(owner, f"Org of {email}")
        self.services.db.update("organisations", {"tin": tin}, "id = ?", (org,))
        return owner, org

    def base(self, org: str) -> str:
        return f"/api/orgs/{org}/einvoices"


class Access(Base):
    def test_anonymous_outsider_and_roles(self) -> None:
        owner, org = self.setup_org("einv-owner@example.com")
        self.assertEqual(Client(self.services).get(self.base(org)).status, 401)
        outsider = self.client("einv-outsider@example.com")
        self.assertEqual(outsider.get(self.base(org)).status, 404)
        self.assertEqual(outsider.post(self.base(org), invoice()).status, 404)
        viewer = self.client("einv-viewer@example.com")
        add_member(self.services, org, viewer, "read_only")
        self.assertEqual(viewer.get(self.base(org)).status, 200)
        self.assertEqual(viewer.post(self.base(org), invoice()).status, 403)
        reviewer = self.client("einv-reviewer@example.com")
        add_member(self.services, org, reviewer, "reviewer")
        self.assertEqual(reviewer.post(self.base(org), invoice()).status, 403)
        preparer = self.client("einv-preparer@example.com")
        add_member(self.services, org, preparer, "preparer")
        status, body = preparer.post(self.base(org), invoice("P-1"))
        self.assertEqual(status, 201, body)
        self.assertEqual(viewer.post(f"{self.base(org)}/{body['id']}/submit").status, 403)
        self.assertEqual(viewer.get(f"{self.base(org)}/{body['id']}").status, 200)

    def test_cross_tenant_invoice_is_hidden(self) -> None:
        a, org_a = self.setup_org("einv-a@example.com")
        b, org_b = self.setup_org("einv-b@example.com", "22222222-0001")
        inv = a.post(self.base(org_a), invoice("X-1")).body
        self.assertEqual(b.get(f"{self.base(org_a)}/{inv['id']}").status, 404)
        # Asking for org A's invoice through org B's path finds nothing either.
        self.assertEqual(b.get(f"{self.base(org_b)}/{inv['id']}").status, 404)
        self.assertEqual(b.post(f"{self.base(org_b)}/{inv['id']}/submit").status, 404)
        self.assertEqual(b.put(f"{self.base(org_b)}/{inv['id']}", invoice("X-1")).status, 404)
        self.assertNotIn(inv["id"], [i["id"] for i in b.get(self.base(org_b)).body["items"]])


class Validation(Base):
    def test_vat_per_line_comes_from_the_rules_engine(self) -> None:
        owner, org = self.setup_org("einv-vat@example.com")
        status, inv = owner.post(self.base(org), invoice())
        self.assertEqual(status, 201, inv)
        self.assertEqual(inv["errors"], {})
        expected_vat = Decimal(0)
        for line, computed in zip(invoice()["lines"], inv["lines"]):
            net = Decimal(line["quantity"]) * Decimal(line["unit_price"])
            out = calculate_vat({"amount": str(net), "category": line["vat_category"], "supply_date": TODAY}, self.services.tree).outputs
            self.assertEqual(computed["vat"], out["vat"])
            self.assertEqual(computed["vat_rate"], out["rate"])
            expected_vat += Decimal(out["vat"])
        self.assertEqual(Decimal(inv["totals"]["vat"]), expected_vat)
        self.assertEqual(Decimal(inv["totals"]["gross"]), Decimal(inv["totals"]["net"]) + expected_vat)
        self.assertIsNotNone(inv["rules_version"])

    def test_field_level_errors(self) -> None:
        owner, org = self.setup_org("einv-errors@example.com")
        future = (dt.date.today() + dt.timedelta(days=3)).isoformat()
        bad = invoice(
            "BAD-1",
            buyer_tin="1234",
            issue_date=future,
            buyer_name="",
            lines=[{"description": "", "quantity": "0", "unit_price": "abc", "vat_category": "luxury"}],
        )
        inv = owner.post(self.base(org), bad).body
        status, body = owner.post(f"{self.base(org)}/{inv['id']}/validate")
        self.assertEqual(status, 422)
        for field in ("buyer_tin", "issue_date", "buyer_name", "lines.0.description", "lines.0.quantity", "lines.0.unit_price", "lines.0.vat_category"):
            self.assertIn(field, body["fields"])
        self.assertEqual(owner.get(f"{self.base(org)}/{inv['id']}").body["status"], "draft")

    def test_number_required_and_unique(self) -> None:
        owner, org = self.setup_org("einv-dupe@example.com")
        self.assertEqual(owner.post(self.base(org), {**invoice(), "invoice_number": ""}).status, 422)
        self.assertEqual(owner.post(self.base(org), invoice("D-1")).status, 201)
        self.assertEqual(owner.post(self.base(org), invoice("D-1")).status, 409)

    def test_supplier_tin_needed_and_declared_totals_checked(self) -> None:
        owner, org = self.setup_org("einv-notin@example.com", tin="")
        inv = owner.post(self.base(org), invoice("T-1")).body
        self.assertIn("supplier_tin", inv["errors"])
        self.services.db.update("organisations", {"tin": "1234567890"}, "id = ?", (org,))
        inv2 = owner.post(self.base(org), invoice("T-2", declared_totals={"gross": "1.00"})).body
        self.assertIn("totals.gross", inv2["errors"])
        self.assertEqual(owner.post(f"{self.base(org)}/{inv2['id']}/validate").status, 422)


class Lifecycle(Base):
    def test_full_path_to_acceptance_and_credit_note(self) -> None:
        owner, org = self.setup_org("einv-life@example.com")
        inv = owner.post(self.base(org), invoice("L-1")).body
        self.assertEqual(inv["status"], "draft")
        status, inv = owner.post(f"{self.base(org)}/{inv['id']}/validate")
        self.assertEqual((status, inv["status"]), (200, "validated"))
        status, sub = owner.post(f"{self.base(org)}/{inv['id']}/submit")
        self.assertEqual(status, 200, sub)
        self.assertEqual(sub["mode"], "sandbox")
        self.assertEqual(sub["invoice"]["status"], "submitted")
        self.assertIn("SBX", sub["invoice"]["irn"])
        self.assertTrue(sub["invoice"]["qr_payload"])
        # Submitted invoices cannot be edited, cancelled or resubmitted.
        self.assertEqual(owner.put(f"{self.base(org)}/{inv['id']}", invoice("L-1")).status, 409)
        self.assertEqual(owner.post(f"{self.base(org)}/{inv['id']}/cancel").status, 409)
        self.assertEqual(owner.post(f"{self.base(org)}/{inv['id']}/submit").status, 409)
        status, synced = owner.post(f"/api/orgs/{org}/einvoicing/sync")
        self.assertEqual((status, synced["processed"], synced["mode"]), (200, 1, "sandbox"))
        inv = owner.get(f"{self.base(org)}/{inv['id']}").body
        self.assertEqual(inv["status"], "accepted")
        self.assertEqual([e["event"] for e in inv["events"]], ["created", "validated", "submitted", "accepted"])
        # Accepted invoices are cancelled only through a credit note.
        self.assertEqual(owner.post(f"{self.base(org)}/{inv['id']}/cancel").status, 409)
        status, note = owner.post(f"{self.base(org)}/{inv['id']}/credit-note", {"reason": "Returned goods"})
        self.assertEqual((status, note["kind"], note["original_invoice_id"]), (201, "credit_note", inv["id"]))
        self.assertEqual(owner.post(f"{self.base(org)}/{inv['id']}/credit-note").status, 409)
        owner.post(f"{self.base(org)}/{note['id']}/submit")
        owner.post(f"/api/orgs/{org}/einvoicing/sync")
        self.assertEqual(owner.get(f"{self.base(org)}/{note['id']}").body["status"], "accepted")
        original = owner.get(f"{self.base(org)}/{inv['id']}").body
        self.assertEqual(original["status"], "cancelled")
        self.assertEqual(original["events"][-1]["event"], "cancelled_by_credit_note")
        actions = [e["action"] for e in self.services.audit.events(org_id=org, entity_id=inv["id"])]
        self.assertIn("einvoice.submit", actions)
        self.assertIn("einvoice.accepted", actions)

    def test_rejection_exception_queue_and_retry(self) -> None:
        owner, org = self.setup_org("einv-reject@example.com")
        inv = owner.post(self.base(org), invoice("R-1", buyer_tin="87650000-0000")).body
        owner.post(f"{self.base(org)}/{inv['id']}/submit")  # validates first
        owner.post(f"/api/orgs/{org}/einvoicing/sync")
        inv = owner.get(f"{self.base(org)}/{inv['id']}").body
        self.assertEqual(inv["status"], "rejected")
        self.assertIn("0000", inv["rejection_reason"])
        queue = owner.get(f"/api/orgs/{org}/einvoicing/exceptions").body["items"]
        self.assertEqual([(q["id"], q["kind"]) for q in queue], [(inv["id"], "rejected")])
        status, edited = owner.put(f"{self.base(org)}/{inv['id']}", invoice("R-1", buyer_tin="87650000-0002"))
        self.assertEqual((status, edited["status"]), (200, "draft"))
        status, retried = owner.post(f"{self.base(org)}/{inv['id']}/retry")
        self.assertEqual((status, retried["invoice"]["status"]), (200, "submitted"))
        owner.post(f"/api/orgs/{org}/einvoicing/sync")
        self.assertEqual(owner.get(f"{self.base(org)}/{inv['id']}").body["status"], "accepted")
        self.assertEqual(owner.get(f"/api/orgs/{org}/einvoicing/exceptions").body["items"], [])

    def test_cancel_draft(self) -> None:
        owner, org = self.setup_org("einv-cancel@example.com")
        inv = owner.post(self.base(org), invoice("C-1")).body
        status, body = owner.post(f"{self.base(org)}/{inv['id']}/cancel", {"reason": "Raised in error"})
        self.assertEqual((status, body["status"]), (200, "cancelled"))
        self.assertEqual(owner.post(f"{self.base(org)}/{inv['id']}/submit").status, 409)

    def test_production_adapter_is_not_configured_and_lands_in_queue(self) -> None:
        owner, org = self.setup_org("einv-prod@example.com")
        inv = owner.post(self.base(org), invoice("PR-1")).body
        registry = self.services.adapters
        saved = registry.get("einvoicing")
        registry._instances["einvoicing"] = ProductionNrsEInvoicing()
        try:
            status, body = owner.post(f"{self.base(org)}/{inv['id']}/submit")
        finally:
            registry._instances["einvoicing"] = saved
        self.assertEqual(status, 503)
        self.assertIn("accreditation", body["message"])
        queue = owner.get(f"/api/orgs/{org}/einvoicing/exceptions").body["items"]
        self.assertEqual(queue[0]["kind"], "failed")


class Idempotency(Base):
    def test_submission_key_replays_and_cannot_be_reused(self) -> None:
        owner, org = self.setup_org("einv-idem@example.com")
        inv = owner.post(self.base(org), invoice("I-1")).body
        other = owner.post(self.base(org), invoice("I-2")).body
        first = owner.post(f"{self.base(org)}/{inv['id']}/submit", {"idempotency_key": "k-123"}).body
        second = owner.post(f"{self.base(org)}/{inv['id']}/submit", {"idempotency_key": "k-123"}).body
        self.assertFalse(first["replayed"])
        self.assertTrue(second["replayed"])
        self.assertEqual(first["invoice"]["irn"], second["invoice"]["irn"])
        self.assertEqual(owner.post(f"{self.base(org)}/{other['id']}/submit", {"idempotency_key": "k-123"}).status, 409)
        events = [e["event"] for e in owner.get(f"{self.base(org)}/{inv['id']}").body["events"]]
        self.assertEqual(events.count("submitted"), 1)


class Callbacks(Base):
    def test_signed_callback_is_verified_and_idempotent(self) -> None:
        owner, org = self.setup_org("einv-cb@example.com")
        inv = owner.post(self.base(org), invoice("CB-1")).body
        sub = owner.post(f"{self.base(org)}/{inv['id']}/submit").body["invoice"]
        payload = {"event_id": "cb_1", "submission_ref": sub["submission_ref"], "irn": sub["irn"], "status": "accepted", "reason": None, "mode": "sandbox"}
        nrs = Client(self.services)
        nrs.headers = {"x-nrs-signature": "bad"}
        self.assertEqual(nrs.post("/api/einvoicing/callbacks/nrs", payload).status, 401)
        self.assertEqual(owner.get(f"{self.base(org)}/{inv['id']}").body["status"], "submitted")
        key = self.services.modules["einvoicing"].callback_key()
        nrs.headers = {"x-nrs-signature": sign(key, canonical_json(payload))}
        status, body = nrs.post("/api/einvoicing/callbacks/nrs", payload)
        self.assertEqual((status, body["status"], body["duplicate"]), (200, "accepted", False))
        status, body = nrs.post("/api/einvoicing/callbacks/nrs", payload)
        self.assertEqual((status, body["duplicate"]), (200, True))
        # Tampering after signing is caught.
        nrs.headers = {"x-nrs-signature": sign(key, canonical_json(payload))}
        self.assertEqual(nrs.post("/api/einvoicing/callbacks/nrs", {**payload, "status": "rejected"}).status, 401)


class EventLog(Base):
    def test_event_log_is_append_only(self) -> None:
        owner, org = self.setup_org("einv-log@example.com")
        inv = owner.post(self.base(org), invoice("E-1")).body
        db = self.services.db
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("UPDATE einvoice_events SET event = 'forged' WHERE invoice_id = ?", (inv["id"],))
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("DELETE FROM einvoice_events WHERE invoice_id = ?", (inv["id"],))
        self.assertEqual(owner.get(f"{self.base(org)}/{inv['id']}").body["events"][0]["event"], "created")


class Import(Base):
    def test_import_is_idempotent_on_source_and_external_id(self) -> None:
        owner, org = self.setup_org("einv-import@example.com")
        svc = self.services.modules["einvoicing"]
        rows = [
            {**invoice("IM-1"), "external_id": "ext-1"},
            {**invoice("IM-2", buyer_tin="99"), "external_id": "ext-2"},
            {**invoice("IM-3")},
        ]
        first = svc.import_invoices(org, owner.user_id, rows, source="erp:test")
        self.assertEqual(first["counts"], {"created": 2, "validated": 1, "duplicate": 0, "failed": 1})
        self.assertIn("buyer_tin", first["items"][1]["errors"])
        again = svc.import_invoices(org, owner.user_id, rows[:2], source="erp:test")
        self.assertEqual(again["counts"]["duplicate"], 2)
        self.assertEqual(again["counts"]["created"], 0)
        # Same external id from another source is a different record, but the invoice number must still be unique.
        other = svc.import_invoices(org, owner.user_id, rows[:1], source="erp:other")
        self.assertEqual(other["counts"]["failed"], 1)
        report = svc.source_report(org, "erp:test")
        self.assertEqual((report["imported"], report["by_status"]["validated"]), (2, 1))
