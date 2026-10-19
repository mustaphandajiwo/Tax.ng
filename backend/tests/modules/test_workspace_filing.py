"""Workspace filing (Phase 4) and payment reconciliation (BIZ-06)."""

from __future__ import annotations

import os
from typing import Any

from taxng.features import nav_for
from taxng.modules.workspace.adapters import ProductionNrsFiling, SandboxNrsFiling, document_hash
from taxng.platform.util import sign

from ..helpers import Client, ServicesTestCase
from .test_workspace import Team


class SwapFiling:
    """Temporarily replaces the filing adapter instance."""

    def __init__(self, services: Any, adapter: Any) -> None:
        self.services, self.adapter = services, adapter

    def __enter__(self) -> None:
        self.services.adapters.get("filing")
        self.previous = self.services.adapters._instances["filing"]
        self.services.adapters._instances["filing"] = self.adapter

    def __exit__(self, *exc: Any) -> None:
        self.services.adapters._instances["filing"] = self.previous


class Filing(ServicesTestCase):
    def test_sandbox_acknowledgement_is_not_a_real_filing(self) -> None:
        t = Team(self, "f1")
        rid = t.approved_vat()
        base = f"/api/orgs/{t.org}/returns/{rid}"
        status, sub = t.preparer.post(f"{base}/file", {"idempotency_key": "f1-key-0001"})
        self.assertEqual(status, 201, sub)
        self.assertEqual((sub["status"], sub["mode"], sub["sandbox"], sub["ack_verified"]), ("acknowledged", "sandbox", True, True))
        self.assertFalse(sub["counts_as_filed"])
        self.assertTrue(sub["ack_reference"].startswith("SBX-"))
        self.assertNotIn("ack_signature", sub)
        detail = t.viewer.get(base).body
        self.assertEqual(detail["status"], "filed_sandbox")
        self.assertNotEqual(detail["status"], "filed")
        self.assertFalse(detail["permissions"]["file"])
        self.assertEqual(detail["filing"]["mode"], "sandbox")
        # A second sandbox filing is refused; reopening is still possible because nothing was filed.
        self.assertEqual(t.preparer.post(f"{base}/file", {"idempotency_key": "f1-key-0002"}).status, 409)
        actions = [e["action"] for e in self.services.audit.events(org_id=t.org)]
        self.assertIn("return.filed_sandbox", actions)
        self.assertNotIn("return.filed", actions)
        self.assertEqual(self.services.modules["workspace"].org_summary(t.org)["open_returns"].get("filed_sandbox"), 1)

    def test_access_and_preconditions(self) -> None:
        t = Team(self, "f2")
        rid = t.vat_return()
        base = f"/api/orgs/{t.org}/returns/{rid}"
        self.assertEqual(Client(self.services).post(f"{base}/file", {"idempotency_key": "anon-key-01"}).status, 401)
        self.assertEqual(t.outsider.post(f"{base}/file", {"idempotency_key": "out-key-001"}).status, 404)
        self.assertEqual(t.viewer.post(f"{base}/file", {"idempotency_key": "view-key-01"}).status, 403)
        self.assertEqual(t.reviewer.post(f"{base}/file", {"idempotency_key": "rev-key-001"}).status, 403)
        self.assertEqual(t.preparer.post(f"{base}/file", {"idempotency_key": "draft-key-1"}).status, 409)  # not approved
        self.assertEqual(t.preparer.post(f"{base}/file", {"idempotency_key": "short"}).status, 422)
        self.assertEqual(t.outsider.get(f"/api/orgs/{t.org}/submissions").status, 404)

    def test_idempotent_retry_does_not_resubmit(self) -> None:
        t = Team(self, "f3")
        rid = t.approved_vat()
        calls: list[int] = []

        class Counting(SandboxNrsFiling):
            def submit(self, document: dict[str, Any], *, secret: str) -> dict[str, Any]:
                calls.append(1)
                return super().submit(document, secret=secret)

        with SwapFiling(self.services, Counting()):
            base = f"/api/orgs/{t.org}/returns/{rid}"
            first = t.preparer.post(f"{base}/file", {"idempotency_key": "retry-key-0001"})
            again = t.owner.post(f"{base}/file", {"idempotency_key": "retry-key-0001"})
        self.assertEqual((first.status, again.status), (201, 200))
        self.assertEqual(first.body["id"], again.body["id"])
        self.assertTrue(again.body["replayed"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.services.db.scalar("SELECT COUNT(*) FROM ws_submissions WHERE return_id = ?", (rid,)), 1)
        # Same key on another return is a conflict.
        other = t.approved_vat("2026-04")
        self.assertEqual(t.preparer.post(f"/api/orgs/{t.org}/returns/{other}/file", {"idempotency_key": "retry-key-0001"}).status, 409)

    def test_rejected_when_tin_ends_0000(self) -> None:
        t = Team(self, "f4")
        t.owner.put(f"/api/orgs/{t.org}", {"tin": "12340000"})
        rid = t.approved_vat()
        status, sub = t.preparer.post(f"/api/orgs/{t.org}/returns/{rid}/file", {"idempotency_key": "rej-key-0001"})
        self.assertEqual((status, sub["status"]), (201, "rejected"))
        self.assertEqual(t.viewer.get(f"/api/orgs/{t.org}/returns/{rid}").body["status"], "approved")
        # Rejected is terminal: cannot be reconciled. A new key may retry after the TIN is corrected.
        self.assertEqual(t.reviewer.post(f"/api/orgs/{t.org}/submissions/{sub['id']}/reconcile").status, 409)

    def test_bad_signature_never_marks_filed(self) -> None:
        t = Team(self, "f5")
        rid = t.approved_vat()

        class Forger(SandboxNrsFiling):
            def submit(self, document: dict[str, Any], *, secret: str) -> dict[str, Any]:
                ack = super().submit(document, secret=secret)
                return {**ack, "signature": sign("wrong-secret", "x")}

        with SwapFiling(self.services, Forger()):
            status, sub = t.preparer.post(f"/api/orgs/{t.org}/returns/{rid}/file", {"idempotency_key": "forge-key-001"})
        self.assertEqual((status, sub["status"], sub["ack_verified"]), (201, "failed", False))
        self.assertEqual(t.viewer.get(f"/api/orgs/{t.org}/returns/{rid}").body["status"], "approved")

    def test_ack_for_a_different_document_is_rejected(self) -> None:
        t = Team(self, "f6")
        rid = t.approved_vat()

        class Swapper(SandboxNrsFiling):
            def submit(self, document: dict[str, Any], *, secret: str) -> dict[str, Any]:
                return super().submit({**document, "totals": {"liability": "0.00"}}, secret=secret)

        with SwapFiling(self.services, Swapper()):
            status, sub = t.preparer.post(f"/api/orgs/{t.org}/returns/{rid}/file", {"idempotency_key": "swap-key-001"})
        self.assertEqual(sub["status"], "failed")

    def test_sandbox_claiming_production_is_not_filed(self) -> None:
        t = Team(self, "f7")
        rid = t.approved_vat()

        class Liar(SandboxNrsFiling):
            def submit(self, document: dict[str, Any], *, secret: str) -> dict[str, Any]:
                digest = document_hash(document)
                from taxng.modules.workspace.adapters import ack_message

                return {"outcome": "acknowledged", "mode": "production", "reference": "NRS-1", "document_hash": digest, "signature": sign(secret, ack_message("production", "NRS-1", digest))}

        with SwapFiling(self.services, Liar()):
            status, sub = t.preparer.post(f"/api/orgs/{t.org}/returns/{rid}/file", {"idempotency_key": "liar-key-001"})
        self.assertEqual(sub["status"], "failed")
        self.assertEqual(t.viewer.get(f"/api/orgs/{t.org}/returns/{rid}").body["status"], "approved")

    def test_authorised_production_ack_marks_filed(self) -> None:
        """Only an authorised production adapter with a verified acknowledgement yields 'filed'."""
        t = Team(self, "f8")
        rid = t.approved_vat()

        class Authorised(ProductionNrsFiling):
            def is_configured(self) -> bool:
                return True

            def submit(self, document: dict[str, Any], *, secret: str) -> dict[str, Any]:
                from taxng.modules.workspace.adapters import ack_message

                digest = document_hash(document)
                return {"outcome": "acknowledged", "mode": "production", "reference": "NRS-ACK-9", "document_hash": digest, "signature": sign(secret, ack_message("production", "NRS-ACK-9", digest))}

        with SwapFiling(self.services, Authorised()):
            status, sub = t.preparer.post(f"/api/orgs/{t.org}/returns/{rid}/file", {"idempotency_key": "prod-key-001"})
            self.assertTrue(sub["counts_as_filed"])
            detail = t.viewer.get(f"/api/orgs/{t.org}/returns/{rid}").body
            self.assertEqual((detail["status"], detail["filed_reference"]), ("filed", "NRS-ACK-9"))
            self.assertEqual(t.owner.post(f"/api/orgs/{t.org}/returns/{rid}/reopen", {"reason": "x"}).status, 409)
            self.assertEqual(t.preparer.post(f"/api/orgs/{t.org}/returns/{rid}/file", {"idempotency_key": "prod-key-002"}).status, 409)

    def test_production_not_configured_fails_cleanly(self) -> None:
        t = Team(self, "f9")
        rid = t.approved_vat()
        with SwapFiling(self.services, ProductionNrsFiling()):
            status, body = t.preparer.post(f"/api/orgs/{t.org}/returns/{rid}/file", {"idempotency_key": "nc-key-0001"})
            self.assertEqual((status, body["error"]), (503, "integration_not_configured"))
            self.assertIn("accreditation", body["message"])
            row = self.services.db.one("SELECT status FROM ws_submissions WHERE idempotency_key = 'nc-key-0001'")
            self.assertEqual(row["status"], "failed")
            self.assertEqual(t.viewer.get(f"/api/orgs/{t.org}/returns/{rid}").body["status"], "approved")
            self.assertFalse(Client(self.services).get("/api/filing/status").body["available"])

    def test_reconcile_transitions_and_roles(self) -> None:
        t = Team(self, "f10")
        rid = t.approved_vat()
        _, sub = t.preparer.post(f"/api/orgs/{t.org}/returns/{rid}/file", {"idempotency_key": "rec-key-0001"})
        path = f"/api/orgs/{t.org}/submissions/{sub['id']}/reconcile"
        self.assertEqual(t.preparer.post(path).status, 403)
        self.assertEqual(t.outsider.post(f"/api/orgs/{t.other_org}/submissions/{sub['id']}/reconcile").status, 404)
        # Tampered stored acknowledgement is caught on reconcile.
        self.services.db.update("ws_submissions", {"ack_reference": "SBX-FORGED"}, "id = ?", (sub["id"],))
        self.assertEqual(t.reviewer.post(path).status, 409)
        self.services.db.update("ws_submissions", {"ack_reference": sub["ack_reference"]}, "id = ?", (sub["id"],))
        status, body = t.reviewer.post(path, {"note": "Checked against sandbox log"})
        self.assertEqual((status, body["status"], body["sandbox"]), (200, "reconciled", True))
        self.assertEqual(t.reviewer.post(path).status, 409)
        items = t.viewer.get(f"/api/orgs/{t.org}/submissions").body["items"]
        self.assertEqual(items[0]["status"], "reconciled")

    def test_state_machine_rejects_invalid_moves(self) -> None:
        from taxng.modules.workspace.filing import TRANSITIONS, _move

        self.assertEqual(TRANSITIONS["prepared"], ("submitting",))
        with self.assertRaises(Exception):
            _move(self.services, {"id": "sub_x", "org_id": "org_x", "status": "prepared"}, "acknowledged")
        with self.assertRaises(Exception):
            _move(self.services, {"id": "sub_x", "org_id": "org_x", "status": "failed"}, "submitting")

    def test_public_nav_and_status(self) -> None:
        self.assertNotIn("file-pay", [i["id"] for i in nav_for(self.services, "header")])
        status, body = Client(self.services).get("/api/filing/status")
        self.assertEqual((status, body["mode"], body["available"]), (200, "sandbox", False))
        self.assertIn("written authorisation", body["needs"])
        self.assertNotIn("TAXNG_ADAPTER_FILING", os.environ)


class Payments(ServicesTestCase):
    def test_reconciliation_flags_differences(self) -> None:
        t = Team(self, "p1")
        rid = t.approved_vat()
        base = f"/api/orgs/{t.org}/returns/{rid}"
        rec = t.viewer.get(base).body["reconciliation"]
        self.assertEqual(rec["status"], "unpaid")
        liability = rec["liability"]
        pay = {"receipt_reference": "RRR-1001", "amount": "1000.00", "paid_on": "2026-04-15", "channel": "remita"}
        self.assertEqual(t.viewer.post(f"{base}/payments", pay).status, 403)
        self.assertEqual(Client(self.services).post(f"{base}/payments", pay).status, 401)
        self.assertEqual(t.preparer.post(f"{base}/payments", {**pay, "channel": "card"}).status, 422)
        self.assertEqual(t.preparer.post(f"{base}/payments", {**pay, "amount": "0"}).status, 422)
        self.assertEqual(t.preparer.post(f"{base}/payments", {**pay, "paid_on": "2999-01-01"}).status, 422)
        status, body = t.preparer.post(f"{base}/payments", pay)
        self.assertEqual((status, body["reconciliation"]["status"]), (201, "underpaid"))
        self.assertEqual(t.preparer.post(f"{base}/payments", pay).status, 409)  # duplicate receipt
        from decimal import Decimal

        rest = str(Decimal(liability) - Decimal("1000.00"))
        status, body = t.preparer.post(f"{base}/payments", {**pay, "receipt_reference": "RRR-1002", "amount": rest})
        self.assertEqual(body["reconciliation"], {"liability": liability, "remitted": liability, "difference": "0.00", "status": "paid", "flag": None})
        status, body = t.preparer.post(f"{base}/payments", {**pay, "receipt_reference": "RRR-1003", "amount": "5"})
        self.assertEqual((body["reconciliation"]["status"], body["reconciliation"]["difference"]), ("overpaid", "5.00"))
        # Voiding is owner-only and tenant-scoped.
        pid = body["payment"]["id"]
        self.assertEqual(t.preparer.delete(f"/api/orgs/{t.org}/payments/{pid}").status, 403)
        self.assertEqual(t.outsider.delete(f"/api/orgs/{t.other_org}/payments/{pid}").status, 404)
        self.assertEqual(t.owner.delete(f"/api/orgs/{t.org}/payments/{pid}").status, 200)
        self.assertEqual(t.viewer.get(base).body["reconciliation"]["status"], "paid")
        overview = t.viewer.get(f"/api/orgs/{t.org}/payments").body["items"]
        self.assertEqual(overview[0]["reconciliation"]["status"], "paid")
        self.assertEqual(t.outsider.get(f"/api/orgs/{t.org}/payments").status, 404)
        self.assertIn("payment.record", [e["action"] for e in self.services.audit.events(org_id=t.org)])

    def test_receipt_evidence_must_belong_to_org(self) -> None:
        import base64

        t = Team(self, "p2")
        rid = t.approved_vat()
        data = base64.b64encode(b"%PDF receipt").decode()
        _, foreign = t.outsider.post("/api/files", {"org_id": t.other_org, "name": "r.pdf", "content_type": "application/pdf", "data_base64": data})
        pay = {"receipt_reference": "RRR-2001", "amount": "10", "paid_on": "2026-04-15", "channel": "bank_branch", "file_id": foreign["id"]}
        self.assertEqual(t.preparer.post(f"/api/orgs/{t.org}/returns/{rid}/payments", pay).status, 404)
