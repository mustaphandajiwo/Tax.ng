"""Developer platform: API keys, /api/v1, rate limits, idempotency, OpenAPI, webhooks, ERP import."""

from __future__ import annotations

import base64
import datetime as dt
import json
import re

from taxng.api import router
from taxng.modules.developer.openapi import OPERATIONS
from taxng.modules.developer.service import verify_webhook_signature

from ..helpers import Client, ServicesTestCase, add_member, create_org

TODAY = dt.date.today().isoformat()
ALL_SCOPES = ["calculators:read", "rules:read", "einvoices:read", "einvoices:write"]


def an_invoice(number: str, buyer_tin: str = "87654321-0001") -> dict:
    return {
        "invoice_number": number,
        "issue_date": TODAY,
        "buyer_name": "Buyer Ltd",
        "buyer_tin": buyer_tin,
        "lines": [{"description": "Service", "quantity": "1", "unit_price": "1000", "vat_category": "standard"}],
    }


class Base(ServicesTestCase):
    def setup_org(self, email: str, tin: str = "12345678-0001") -> tuple[Client, str]:
        owner = self.client(email)
        org = create_org(owner, f"Org of {email}")
        self.services.db.update("organisations", {"tin": tin}, "id = ?", (org,))
        return owner, org

    def key(self, owner: Client, org: str, scopes: list[str] | None = None, **extra: object) -> dict:
        status, body = owner.post(f"/api/orgs/{org}/api-keys", {"name": "ERP", "scopes": scopes or ALL_SCOPES, **extra})
        assert status == 201, body
        return body

    def api(self, token: str, **headers: str) -> Client:
        c = Client(self.services)
        c.headers = {"authorization": f"Bearer {token}", **headers}
        return c


class Keys(Base):
    def test_owner_only_and_shown_once(self) -> None:
        owner, org = self.setup_org("dev-keys@example.com")
        self.assertEqual(Client(self.services).post(f"/api/orgs/{org}/api-keys", {"name": "x", "scopes": ALL_SCOPES}).status, 401)
        outsider = self.client("dev-keys-out@example.com")
        self.assertEqual(outsider.get(f"/api/orgs/{org}/api-keys").status, 404)
        preparer = self.client("dev-keys-prep@example.com")
        add_member(self.services, org, preparer, "preparer")
        self.assertEqual(preparer.post(f"/api/orgs/{org}/api-keys", {"name": "x", "scopes": ALL_SCOPES}).status, 403)
        self.assertEqual(owner.post(f"/api/orgs/{org}/api-keys", {"name": "x", "scopes": ["admin:all"]}).status, 422)
        created = self.key(owner, org)
        self.assertTrue(created["token"].startswith("tng_test_"))
        self.assertEqual(created["mode"], "sandbox")
        listed = owner.get(f"/api/orgs/{org}/api-keys").body["items"]
        self.assertNotIn("token", listed[0])
        self.assertTrue(created["token"].startswith(listed[0]["prefix"]))
        stored = self.services.db.one("SELECT * FROM api_keys WHERE id = ?", (created["id"],))
        self.assertNotIn(created["token"], json.dumps(stored))

    def test_cross_tenant_key_revoke_is_hidden(self) -> None:
        a, org_a = self.setup_org("dev-key-a@example.com")
        b, org_b = self.setup_org("dev-key-b@example.com", "22222222-0001")
        key_a = self.key(a, org_a)
        self.assertEqual(b.post(f"/api/orgs/{org_b}/api-keys/{key_a['id']}/revoke").status, 404)
        self.assertEqual(b.post(f"/api/orgs/{org_a}/api-keys/{key_a['id']}/revoke").status, 404)
        self.assertEqual(self.api(key_a["token"]).get("/api/v1/key").status, 200)


class Auth(Base):
    def test_missing_bad_revoked_and_scope(self) -> None:
        owner, org = self.setup_org("dev-auth@example.com")
        status, body = Client(self.services).post("/api/v1/calculate/vat", {"amount": "1000"})
        self.assertEqual((status, body["error"]), (401, "unauthorized"))
        self.assertTrue(body["correlation_id"])
        self.assertEqual(self.api("tng_test_0000000000_" + "0" * 40).post("/api/v1/calculate/vat", {"amount": "1000"}).status, 401)
        narrow = self.key(owner, org, ["rules:read"])
        status, body = self.api(narrow["token"]).post("/api/v1/calculate/vat", {"amount": "1000"})
        self.assertEqual((status, body["error"]), (403, "insufficient_scope"))
        status, body = self.api(narrow["token"]).get("/api/v1/parameters/vat.standard_rate")
        self.assertEqual(status, 200, body)
        self.assertIn("value", body)
        full = self.key(owner, org)
        client = self.api(full["token"], **{"x-correlation-id": "abc-123"})
        reply = client.post("/api/v1/calculate/vat", {"amount": "1000"})
        self.assertEqual(reply.status, 200)
        self.assertEqual(reply.headers["X-Correlation-Id"], "abc-123")
        self.assertIn("vat", reply.body["outputs"])
        self.assertEqual(client.post("/api/v1/calculate/nope", {}).body["error"], "not_found")
        self.assertEqual(client.post("/api/v1/calculate/vat", {}).body["error"], "invalid_input")
        owner.post(f"/api/orgs/{org}/api-keys/{full['id']}/revoke")
        self.assertEqual(client.post("/api/v1/calculate/vat", {"amount": "1000"}).status, 401)

    def test_api_key_cannot_use_session_routes(self) -> None:
        owner, org = self.setup_org("dev-session@example.com")
        token = self.key(owner, org)["token"]
        api = self.api(token)
        # The router resolves API keys only on /api/v1, so session routes see an
        # anonymous caller (401) and never a key principal.
        self.assertEqual(api.get(f"/api/orgs/{org}/einvoices").status, 401)
        self.assertEqual(api.get(f"/api/orgs/{org}/api-keys").status, 401)
        self.assertEqual(api.get("/api/billing/payments").status, 401)


class RateLimit(Base):
    def test_token_bucket_returns_429_then_refills(self) -> None:
        owner, org = self.setup_org("dev-rate@example.com")
        token = self.key(owner, org, rate_per_minute=2)["token"]
        dev = self.services.modules["developer"]
        clock = [1000.0]
        saved = dev.limiter.clock
        dev.limiter.clock = lambda: clock[0]
        try:
            api = self.api(token)
            self.assertEqual(api.get("/api/v1/key").status, 200)
            self.assertEqual(api.get("/api/v1/key").status, 200)
            reply = api.get("/api/v1/key")
            self.assertEqual((reply.status, reply.body["error"]), (429, "rate_limited"))
            self.assertGreaterEqual(int(reply.headers["Retry-After"]), 1)
            self.assertEqual(reply.headers["X-RateLimit-Limit"], "2")
            clock[0] += 30
            self.assertEqual(api.get("/api/v1/key").status, 200)
        finally:
            dev.limiter.clock = saved


class PublicEInvoices(Base):
    def test_create_idempotent_submit_status_and_tenancy(self) -> None:
        owner, org = self.setup_org("dev-v1@example.com")
        api = self.api(self.key(owner, org)["token"], **{"idempotency-key": "create-1"})
        first = api.post("/api/v1/einvoices", an_invoice("API-1"))
        self.assertEqual(first.status, 201, first.body)
        again = api.post("/api/v1/einvoices", an_invoice("API-1"))
        self.assertEqual((again.status, again.body["id"]), (201, first.body["id"]))
        self.assertEqual(again.headers.get("Idempotent-Replayed"), "true")
        clash = api.post("/api/v1/einvoices", an_invoice("API-2"))
        self.assertEqual((clash.status, clash.body["error"]), (409, "idempotency_conflict"))
        api.headers.pop("idempotency-key")
        self.assertEqual(api.post("/api/v1/einvoices", an_invoice("API-1")).body["error"], "conflict")
        inv_id = first.body["id"]
        api.headers["idempotency-key"] = "submit-1"
        sub = api.post(f"/api/v1/einvoices/{inv_id}/submit")
        self.assertEqual((sub.status, sub.body["invoice"]["status"], sub.body["mode"]), (200, "submitted", "sandbox"))
        self.assertEqual(api.post(f"/api/v1/einvoices/{inv_id}/submit").body["invoice"]["irn"], sub.body["invoice"]["irn"])
        owner.post(f"/api/orgs/{org}/einvoicing/sync")
        status, body = api.get(f"/api/v1/einvoices/{inv_id}")
        self.assertEqual((status, body["status"], body["source"]), (200, "accepted", "api"))
        self.assertEqual(api.get("/api/v1/einvoices", {"status": "accepted"}).body["counts"]["accepted"], 1)
        # Another organisation's key cannot see this invoice.
        other_owner, other_org = self.setup_org("dev-v1-other@example.com", "22222222-0001")
        other = self.api(self.key(other_owner, other_org)["token"])
        self.assertEqual(other.get(f"/api/v1/einvoices/{inv_id}").status, 404)
        self.assertEqual(other.post(f"/api/v1/einvoices/{inv_id}/submit").status, 404)
        self.assertEqual(other.get("/api/v1/einvoices").body["items"], [])

    def test_validation_errors_use_the_taxonomy(self) -> None:
        owner, org = self.setup_org("dev-v1-err@example.com")
        api = self.api(self.key(owner, org)["token"])
        inv = api.post("/api/v1/einvoices", {**an_invoice("API-E"), "buyer_tin": "12"}).body
        status, body = api.post(f"/api/v1/einvoices/{inv['id']}/submit")
        self.assertEqual((status, body["error"]), (422, "invalid_input"))
        self.assertIn("buyer_tin", body["fields"])
        self.assertIn("correlation_id", body)


class OpenApi(Base):
    def test_document_is_public_and_every_path_is_routed(self) -> None:
        status, doc = Client(self.services).get("/api/v1/openapi.json")
        self.assertEqual(status, 200)
        self.assertEqual(doc["openapi"], "3.1.0")
        self.assertIn("sandbox", doc["info"]["description"])
        routes = [(m, re.compile(p)) for m, p in router.routes()]
        documented = set()
        for path, methods in doc["paths"].items():
            sample = re.sub(r"\{\w+\}", "sample", path)
            for method in methods:
                documented.add((method.upper(), path))
                self.assertTrue(any(m == method.upper() and r.match(sample) for m, r in routes), f"{method} {path} is not routed")
        self.assertEqual(len(documented), len(OPERATIONS))
        # And every routed /api/v1 path is documented.
        for method, pattern in router.routes():
            if pattern.startswith("^/api/v1/"):
                self.assertTrue(
                    any(m == method and re.compile(pattern).match(re.sub(r"\{\w+\}", "sample", p)) for m, p in documented),
                    f"{method} {pattern} is routed but not documented",
                )


class Webhooks(Base):
    def test_endpoint_rules_signed_delivery_replay_and_tenancy(self) -> None:
        owner, org = self.setup_org("dev-wh@example.com")
        base = f"/api/orgs/{org}/webhooks"
        self.assertEqual(owner.post(base, {"url": "http://example.com/hook", "events": ["einvoice.accepted"]}).status, 422)
        self.assertEqual(owner.post(base, {"url": "https://localhost/hook", "events": ["einvoice.accepted"]}).status, 422)
        self.assertEqual(owner.post(base, {"url": "https://10.0.0.5/hook", "events": ["einvoice.accepted"]}).status, 422)
        self.assertEqual(owner.post(base, {"url": "https://erp.example.com/hook", "events": ["nope"]}).status, 422)
        status, endpoint = owner.post(base, {"url": "https://erp.example.com/hook", "events": ["einvoice.accepted", "einvoice.rejected"]})
        self.assertEqual(status, 201, endpoint)
        secret = endpoint["secret"]
        self.assertNotIn("secret", owner.get(base).body["items"][0])
        # An accepted e-invoice emits a webhook through the developer module.
        inv = owner.post(f"/api/orgs/{org}/einvoices", an_invoice("WH-1")).body
        owner.post(f"/api/orgs/{org}/einvoices/{inv['id']}/submit")
        owner.post(f"/api/orgs/{org}/einvoicing/sync")
        deliveries = owner.get(f"/api/orgs/{org}/webhook-deliveries").body
        self.assertEqual(deliveries["mode"], "sandbox")
        self.assertEqual([d["event"] for d in deliveries["items"]], ["einvoice.accepted"])
        d = deliveries["items"][0]
        self.assertEqual((d["status"], d["attempts"]), ("would_deliver", 1))
        self.assertTrue(verify_webhook_signature(secret, d["headers"]["X-TaxNG-Signature"], d["body"]))
        self.assertFalse(verify_webhook_signature("whsec_wrong", d["headers"]["X-TaxNG-Signature"], d["body"]))
        self.assertFalse(verify_webhook_signature(secret, d["headers"]["X-TaxNG-Signature"], d["body"].replace("accepted", "rejected")))
        self.assertEqual(json.loads(d["body"])["data"]["invoice_number"], "WH-1")
        status, replayed = owner.post(f"/api/orgs/{org}/webhook-deliveries/{d['id']}/replay")
        self.assertEqual((status, replayed["attempts"], replayed["event_id"]), (200, 2, d["event_id"]))
        self.assertTrue(verify_webhook_signature(secret, replayed["headers"]["X-TaxNG-Signature"], replayed["body"]))
        other, other_org = self.setup_org("dev-wh-other@example.com", "22222222-0001")
        self.assertEqual(other.get(f"/api/orgs/{org}/webhook-deliveries").status, 404)
        self.assertEqual(other.post(f"/api/orgs/{other_org}/webhook-deliveries/{d['id']}/replay").status, 404)
        self.assertEqual(other.post(f"/api/orgs/{other_org}/webhooks/{endpoint['id']}/disable").status, 404)

    def test_emit_degrades_gracefully(self) -> None:
        dev = self.services.modules["developer"]
        self.assertEqual(dev.emit("org_missing", "einvoice.accepted", {"x": 1}), [])


QUICKBOOKS_CSV = """InvoiceNo,Customer,Customer TIN,InvoiceDate,DueDate,ItemDescription,ItemQuantity,ItemRate,ItemTaxCode,InvoiceTotal
QB-100,Alpha Ltd,87654321-0001,{d},{d},Design,2,1000,VAT,
QB-100,Alpha Ltd,87654321-0001,{d},{d},Export support,1,500,Zero-rated,
QB-101,Beta Ltd,11112222-0001,{d},,Licence,1,2000,Exempt,9999.00
QB-102,Gamma Ltd,12345,{d},,Training,1,100,VAT,
"""

ODOO_CSV = """Number,Partner,Partner/Tax ID,Invoice/Bill Date,Due Date,Invoice lines/Label,Invoice lines/Quantity,Invoice lines/Unit Price,Invoice lines/Taxes,Total
OD-1,Delta Ltd,87654321-0001,{d},,Line one,1,100,VAT Sales,
,,,,,Line two,2,50,Exempt,
"""


class Erp(Base):
    def test_import_reconcile_and_reimport_is_idempotent(self) -> None:
        owner, org = self.setup_org("dev-erp@example.com")
        d = dt.date.today().strftime("%d/%m/%Y")
        body = {"profile": "quickbooks", "filename": "export.csv", "data_base64": base64.b64encode(QUICKBOOKS_CSV.format(d=d).encode()).decode()}
        viewer = self.client("dev-erp-view@example.com")
        add_member(self.services, org, viewer, "read_only")
        self.assertEqual(viewer.post(f"/api/orgs/{org}/erp/import", body).status, 403)
        status, result = owner.post(f"/api/orgs/{org}/erp/import", body)
        self.assertEqual(status, 201, result)
        self.assertEqual(result["rows"], 4)
        self.assertEqual(result["counts"], {"created": 3, "validated": 1, "duplicate": 0, "failed": 0})
        qb100 = next(i for i in result["items"] if i["external_id"] == "QB-100")
        inv = owner.get(f"/api/orgs/{org}/einvoices/{qb100['invoice_id']}").body
        self.assertEqual([line["vat_category"] for line in inv["lines"]], ["standard", "zero_rated"])
        again = owner.post(f"/api/orgs/{org}/erp/import", body).body
        self.assertEqual(again["counts"]["duplicate"], 3)
        owner.post(f"/api/orgs/{org}/einvoicing/submit-validated", {"source": "erp:quickbooks"})
        owner.post(f"/api/orgs/{org}/einvoicing/sync")
        status, rec = owner.get(f"/api/orgs/{org}/erp/reconciliation")
        self.assertEqual(status, 200)
        report = rec["sources"][0]
        self.assertEqual((report["source"], report["imported"], report["submitted"], report["accepted"]), ("erp:quickbooks", 3, 1, 1))
        self.assertEqual([m["external_id"] for m in report["mismatched_totals"]], ["QB-101"])
        self.assertEqual([m["external_id"] for m in report["invalid"]], ["QB-102"])
        self.assertEqual(len(rec["imports"]), 2)
        outsider = self.client("dev-erp-out@example.com")
        self.assertEqual(outsider.get(f"/api/orgs/{org}/erp/reconciliation").status, 404)

    def test_fill_down_profile_and_json(self) -> None:
        owner, org = self.setup_org("dev-erp-odoo@example.com")
        status, result = owner.post(f"/api/orgs/{org}/erp/import", {"profile": "odoo", "format": "csv", "content": ODOO_CSV.format(d=TODAY)})
        self.assertEqual(status, 201, result)
        inv = owner.get(f"/api/orgs/{org}/einvoices/{result['items'][0]['invoice_id']}").body
        self.assertEqual(len(inv["lines"]), 2)
        rows = [{"external_id": "J-1", "invoice_number": "J-1", "issue_date": TODAY, "buyer_name": "Eps", "buyer_tin": "87654321-0001", "description": "x", "quantity": "1", "unit_price": "10"}]
        status, result = owner.post(f"/api/orgs/{org}/erp/import", {"profile": "taxng", "format": "json", "content": json.dumps(rows)})
        self.assertEqual((status, result["counts"]["validated"]), (201, 1))
        self.assertEqual(owner.post(f"/api/orgs/{org}/erp/import", {"profile": "taxng", "format": "json", "content": "{bad"}).status, 422)

    def test_live_sync_needs_licensed_access(self) -> None:
        owner, org = self.setup_org("dev-erp-live@example.com")
        status, body = owner.post(f"/api/orgs/{org}/erp/sync/sap")
        self.assertEqual((status, body["error"]), (503, "integration_not_configured"))
        self.assertIn("SAP", body["message"])
