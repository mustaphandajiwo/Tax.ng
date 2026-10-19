"""Platform core: sign-in, sessions, CSRF, tenancy, audit chain, files, identity, adapters."""

from __future__ import annotations

import base64
import sqlite3

from taxng.api.router import Request, dispatch
from taxng.platform.access import CAN_EDIT, NotFoundError, require_org
from taxng.platform.auth import SESSION_COOKIE

from .helpers import Client, ServicesTestCase, add_member, create_org


class SignIn(ServicesTestCase):
    def test_full_flow_and_me(self) -> None:
        alice = self.client("Alice@Example.com")
        status, me = alice.get("/api/me")
        self.assertEqual(status, 200)
        self.assertEqual(me["email"], "alice@example.com")

    def test_wrong_code_counts_attempts(self) -> None:
        c = Client(self.services)
        c.post("/api/auth/request-code", {"email": "bob@example.com"})
        for _ in range(5):
            self.assertEqual(c.post("/api/auth/verify", {"email": "bob@example.com", "code": "000000"}).status, 422)
        status, body = c.post("/api/auth/verify", {"email": "bob@example.com", "code": "000000"})
        self.assertIn("too many attempts", body["fields"]["code"])

    def test_rate_limit_on_codes(self) -> None:
        c = Client(self.services)
        for _ in range(5):
            self.assertEqual(c.post("/api/auth/request-code", {"email": "spam@example.com"}).status, 202)
        self.assertEqual(c.post("/api/auth/request-code", {"email": "spam@example.com"}).status, 422)

    def test_logout_revokes_session(self) -> None:
        c = self.client("carol@example.com")
        token = c.cookies[SESSION_COOKIE]
        c.post("/api/auth/logout")
        stale = Client(self.services)
        stale.cookies = {SESSION_COOKIE: token}
        self.assertEqual(stale.get("/api/me").status, 401)

    def test_anonymous_is_401(self) -> None:
        self.assertEqual(Client(self.services).get("/api/me").status, 401)


class Csrf(ServicesTestCase):
    def test_cookie_post_without_header_is_rejected(self) -> None:
        c = self.client("dave@example.com")
        reply = dispatch(self.services, Request("POST", "/api/me", {}, {"name": "Dave"}, {}, dict(c.cookies)))
        self.assertEqual(reply.status, 403)
        self.assertEqual(reply.body["error"], "csrf")


class Tenancy(ServicesTestCase):
    def test_non_member_gets_not_found(self) -> None:
        owner = self.client("owner@example.com")
        outsider = self.client("outsider@example.com")
        org = create_org(owner)
        outsider_principal = outsider.request("GET", "/api/me")  # refresh
        self.assertEqual(outsider_principal.status, 200)
        req = Request("GET", "/api/me", cookies=dict(outsider.cookies))
        dispatch(self.services, req)
        with self.assertRaises(NotFoundError):
            require_org(req.principal, org)

    def test_read_only_cannot_upload_to_org(self) -> None:
        owner = self.client("o2@example.com")
        viewer = self.client("viewer@example.com")
        org = create_org(owner)
        add_member(self.services, org, viewer, "read_only")
        data = base64.b64encode(b"%PDF-1.4 test").decode()
        status, _ = viewer.post("/api/files", {"org_id": org, "name": "a.pdf", "content_type": "application/pdf", "data_base64": data})
        self.assertEqual(status, 403)
        self.assertIn("read_only", CAN_EDIT + ("read_only",))


class Audit(ServicesTestCase):
    def test_chain_verifies_and_rejects_tampering(self) -> None:
        audit = self.services.audit
        audit.record("test.one", "thing", "t1", data={"a": 1})
        audit.record("test.two", "thing", "t2", data={"b": 2})
        self.assertTrue(audit.verify()["ok"])
        with self.assertRaises(sqlite3.DatabaseError):
            self.services.db.execute("UPDATE audit_events SET action = 'x'")
        with self.assertRaises(sqlite3.DatabaseError):
            self.services.db.execute("DELETE FROM audit_events")

    def test_tampering_is_detected_if_triggers_are_bypassed(self) -> None:
        audit = self.services.audit
        audit.record("test.three", "thing", "t3")
        self.services.db.execute("DROP TRIGGER audit_no_update")
        self.services.db.execute("UPDATE audit_events SET data_json = '{\"forged\":true}' WHERE action = 'test.three'")
        self.assertFalse(audit.verify()["ok"])


class Files(ServicesTestCase):
    def test_upload_link_download(self) -> None:
        c = self.client("files@example.com")
        data = base64.b64encode(b"a,b\n1,2\n").decode()
        status, record = c.post("/api/files", {"name": "x.csv", "content_type": "text/csv", "data_base64": data})
        self.assertEqual(status, 201)
        status, link = c.post(f"/api/files/{record['id']}/link")
        self.assertEqual(status, 200)
        path, _, qs = link["url"].partition("?")
        query = dict(part.split("=") for part in qs.split("&"))
        reply = Client(self.services).get(path, query)
        self.assertEqual(reply.status, 200)
        self.assertEqual(reply.raw, b"a,b\n1,2\n")
        query["sig"] = "0" * 64
        self.assertEqual(Client(self.services).get(path, query).status, 422)

    def test_rejects_disallowed_type(self) -> None:
        c = self.client("files2@example.com")
        status, body = c.post("/api/files", {"name": "x.exe", "content_type": "application/x-msdownload", "data_base64": "AA=="})
        self.assertEqual(status, 422)

    def test_other_users_personal_file_is_hidden(self) -> None:
        a = self.client("fa@example.com")
        b = self.client("fb@example.com")
        _, record = a.post("/api/files", {"name": "p.pdf", "content_type": "application/pdf", "data_base64": base64.b64encode(b"x").decode()})
        self.assertEqual(b.post(f"/api/files/{record['id']}/link").status, 404)


class Identity(ServicesTestCase):
    def test_sandbox_verification_stores_masked_only(self) -> None:
        c = self.client("idv@example.com")
        status, result = c.post("/api/me/identity", {"id_type": "nin", "number": "12345678901"})
        self.assertEqual((status, result["result"], result["mode"]), (200, "verified", "sandbox"))
        self.assertEqual(result["id_masked"], "*******8901")
        row = self.services.db.one("SELECT * FROM identity_verifications WHERE id = ?", (result["id"],))
        self.assertNotIn("12345678901", str(row))
        status, result = c.post("/api/me/identity", {"id_type": "nin", "number": "12345670000"})
        self.assertEqual(result["result"], "not_found")
        self.assertEqual(c.post("/api/me/identity", {"id_type": "nin", "number": "12"}).status, 422)


class AdminAndAdapters(ServicesTestCase):
    def test_admin_endpoints_need_staff(self) -> None:
        self.assertEqual(self.client("plain@example.com").get("/api/admin/metrics").status, 403)
        admin = self.client("admin@example.com", staff_role="admin")
        status, body = admin.get("/api/admin/metrics")
        self.assertEqual(status, 200)
        self.assertTrue(body["audit_chain"]["ok"])

    def test_adapters_default_to_sandbox(self) -> None:
        for info in self.services.adapters.info():
            self.assertEqual(info["mode"], "sandbox", info)
            self.assertFalse(info["authorised"])

    def test_ai_consent_toggle_is_audited(self) -> None:
        c = self.client("ai@example.com")
        status, me = c.post("/api/me", {"ai_account_access": True})
        self.assertTrue(me["ai_account_access"])
        events = self.services.audit.events(entity_id=me["id"])
        self.assertIn("consent.ai_account_access", [e["action"] for e in events])
