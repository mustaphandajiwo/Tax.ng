"""Advisory module: listings and verification, directory, bookings, consents and engagements (ADV-01 to ADV-05, GOV-04)."""

from __future__ import annotations

import json
import unittest

from taxng.modules.advisory.adapters import ProductionRegister
from taxng.platform.adapters import NotConfigured

from ..helpers import Client, ServicesTestCase

LISTING = {
    "name": "Ada Obi",
    "firm": "Obi Tax Partners",
    "state": "Lagos",
    "location": "Ikeja",
    "specialisms": ["vat", "cit"],
    "citn_number": "CITN/12345",
    "bio": "Corporate tax adviser.",
}


class Base(ServicesTestCase):
    _n = 0

    def email(self, label: str) -> str:
        Base._n += 1
        return f"adv-{label}-{Base._n}@example.com"

    def staff(self) -> Client:
        return self.client(self.email("staff"), staff_role="support")

    def adviser(self, label: str = "adviser", **overrides: object) -> tuple[Client, str]:
        """An approved, sandbox-verified adviser."""
        c = self.client(self.email(label))
        status, body = c.post("/api/advisory/advisers", {**LISTING, **overrides})
        self.assertEqual(status, 201, body)
        status, decided = self.staff().post(f"/api/advisory/admin/advisers/{body['id']}/decision", {"decision": "approve"})
        self.assertEqual(status, 200, decided)
        return c, body["id"]

    def client_with_report(self, label: str = "client") -> Client:
        """A taxpayer with a completed health check (rental income gaps)."""
        c = self.client(self.email(label))
        status, state = c.post("/api/compliance/checks", {"year": 2026})
        check_id = state["check"]["id"]
        answers = {"q.entity_type": "individual", "q.has_employment_income": True, "q.has_business_income": False, "q.has_employees": False,
                   "q.has_rental_income": True, "q.has_foreign_income": False, "q.has_capital_gains": False}  # fmt: skip
        state = c.put(f"/api/compliance/checks/{check_id}/answers", {"answers": answers}).body
        evidence = {q["id"]: "no" for q in state["questions"] if q["kind"] == "evidence"}
        c.put(f"/api/compliance/checks/{check_id}/answers", {"answers": evidence})
        self.assertEqual(c.post(f"/api/compliance/checks/{check_id}/complete").status, 200)
        return c

    def book(self, client: Client, adviser_id: str, fields: list[str] | None = None) -> dict:
        status, body = client.post(
            "/api/advisory/bookings",
            {"adviser_id": adviser_id, "topic": "Rental income return", "intake_fields": fields or [], "pre_engagement_consent": True},
        )
        self.assertEqual(status, 201, body)
        return body


class Listings(Base):
    def test_apply_verify_and_approve(self) -> None:
        c = self.client(self.email("apply"))
        status, listing = c.post("/api/advisory/advisers", LISTING)
        self.assertEqual(status, 201)
        self.assertEqual(listing["status"], "pending")
        v = listing["verification"]
        self.assertEqual((v["status"], v["mode"], v["registers"]), ("verified", "sandbox", ["CITN"]))
        self.assertTrue(v["checked_at"] and v["expires_at"] > v["checked_at"])
        self.assertEqual(c.post("/api/advisory/advisers", LISTING).status, 409)  # one listing per user
        self.assertEqual(self.client().get(f"/api/advisory/directory/{listing['id']}").status, 404)  # not yet approved
        staff = self.staff()
        status, approved = staff.post(f"/api/advisory/admin/advisers/{listing['id']}/decision", {"decision": "approve"})
        self.assertEqual((status, approved["status"]), (200, "approved"))
        status, public = self.client().get(f"/api/advisory/directory/{listing['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(public["memberships"], [{"register": "CITN", "number": "******2345"}])
        self.assertNotIn("citn_number", public)
        self.assertIn("practitioner of record", public["practitioner_notice"])

    def test_not_found_number_blocks_approval(self) -> None:
        c = self.client(self.email("nf"))
        _, listing = c.post("/api/advisory/advisers", {**LISTING, "citn_number": None, "ican_number": "ICAN0000"})
        self.assertEqual(listing["verification"]["status"], "not_verified")
        self.assertEqual(listing["verification"]["checks"][0]["result"], "not_found")
        status, body = self.staff().post(f"/api/advisory/admin/advisers/{listing['id']}/decision", {"decision": "approve"})
        self.assertEqual(status, 409)
        status, body = self.staff().post(f"/api/advisory/admin/advisers/{listing['id']}/decision", {"decision": "reject", "note": "Not on register"})
        self.assertEqual((status, body["status"]), (200, "rejected"))
        self.assertEqual(self.staff().post(f"/api/advisory/admin/advisers/{listing['id']}/decision", {"decision": "suspend"}).status, 409)

    def test_validation(self) -> None:
        c = self.client(self.email("val"))
        for bad, field in (
            ({"citn_number": None}, "citn_number"),
            ({"state": "Atlantis"}, "state"),
            ({"specialisms": ["astrology"]}, "specialisms"),
            ({"name": ""}, "name"),
            ({"citn_number": "<script>"}, "citn_number"),
        ):
            status, body = c.post("/api/advisory/advisers", {**LISTING, **bad})
            self.assertEqual(status, 422, bad)
            self.assertIn(field, body["fields"])

    def test_annual_reverification_expiry(self) -> None:
        c, adviser_id = self.adviser("expiry")
        self.services.db.execute("UPDATE advisory_verifications SET expires_at = '2000-01-01T00:00:00+00:00' WHERE adviser_id = ?", (adviser_id,))
        listing = c.get("/api/advisory/advisers/me").body
        self.assertEqual(listing["verification"]["status"], "expired")
        entry = self.client().get(f"/api/advisory/directory/{adviser_id}").body
        self.assertEqual(entry["verification"]["status"], "expired")  # badge withdrawn
        status, v = c.post("/api/advisory/advisers/me/verify")
        self.assertEqual((status, v["status"]), (200, "verified"))

    def test_changing_number_returns_listing_to_review(self) -> None:
        c, adviser_id = self.adviser("edit")
        status, listing = c.put("/api/advisory/advisers/me", {"bio": "Updated"})
        self.assertEqual((status, listing["status"], listing["bio"]), (200, "approved", "Updated"))
        status, listing = c.put("/api/advisory/advisers/me", {"citn_number": "CITN/99999"})
        self.assertEqual(listing["status"], "pending")
        self.assertEqual(len([x for x in listing["verification"]["checks"] if x["register"] == "citn"]), 1)
        self.assertNotIn(adviser_id, [a["id"] for a in self.client().get("/api/advisory/directory").body["items"]])

    def test_staff_endpoints_need_staff(self) -> None:
        _, adviser_id = self.adviser("staffcheck")
        anon, plain = self.client(), self.client(self.email("plain"))
        for method, path in (
            ("GET", "/api/advisory/admin/advisers"),
            ("POST", f"/api/advisory/admin/advisers/{adviser_id}/decision"),
            ("POST", f"/api/advisory/admin/advisers/{adviser_id}/verify"),
        ):
            self.assertEqual(anon.request(method, path, {}).status, 401)
            self.assertEqual(plain.request(method, path, {"decision": "suspend"}).status, 403)
        status, body = self.staff().get("/api/advisory/admin/advisers", {"status": "approved"})
        self.assertEqual(status, 200)
        self.assertIn(adviser_id, [a["id"] for a in body["items"]])
        self.assertEqual(self.staff().post("/api/advisory/admin/advisers/adv_missing/decision", {"decision": "approve"}).status, 404)

    def test_anonymous_cannot_manage_a_listing(self) -> None:
        anon = self.client()
        for method, path in (("POST", "/api/advisory/advisers"), ("GET", "/api/advisory/advisers/me"), ("PUT", "/api/advisory/advisers/me"),
                             ("POST", "/api/advisory/advisers/me/verify"), ("GET", "/api/advisory/advisers/me/placements"),
                             ("POST", "/api/advisory/advisers/me/placements")):  # fmt: skip
            self.assertEqual(anon.request(method, path, {}).status, 401, path)
        self.assertEqual(self.client(self.email("nolisting")).get("/api/advisory/advisers/me").status, 404)

    def test_anonymous_gets_401_on_every_booking_and_engagement_endpoint(self) -> None:
        anon = self.client()
        for method, path in (
            ("GET", "/api/advisory/intake-options"), ("POST", "/api/advisory/bookings"), ("GET", "/api/advisory/bookings"),
            ("POST", "/api/advisory/bookings/bkg_x/cancel"), ("GET", "/api/advisory/engagements"),
            ("POST", "/api/advisory/engagements/eng_x/consent"), ("DELETE", "/api/advisory/engagements/eng_x/consent"),
            ("GET", "/api/advisory/engagements/eng_x/access-log"), ("POST", "/api/advisory/engagements/eng_x/end"),
            ("GET", "/api/advisory/consents"), ("POST", "/api/advisory/consents/marketing"), ("GET", "/api/advisory/suggestions"),
            ("GET", "/api/advisory/adviser/bookings"), ("GET", "/api/advisory/adviser/bookings/bkg_x"),
            ("POST", "/api/advisory/adviser/bookings/bkg_x/decision"), ("GET", "/api/advisory/adviser/engagements"),
            ("GET", "/api/advisory/adviser/engagements/eng_x/report"),
        ):  # fmt: skip
            self.assertEqual(anon.request(method, path, {}).status, 401, path)
        # Public endpoints stay public.
        self.assertEqual(anon.get("/api/advisory/meta").status, 200)
        self.assertEqual(anon.get("/api/advisory/directory").status, 200)


class ProductionRegisterNotConfigured(Base):
    def test_production_adapter_refuses(self) -> None:
        with self.assertRaises(NotConfigured):
            ProductionRegister().check("citn", "123")
        registry = self.services.adapters
        registry._instances["register"] = ProductionRegister()
        try:
            status, body = self.client(self.email("prod")).post("/api/advisory/advisers", LISTING)
            self.assertEqual((status, body["error"]), (503, "integration_not_configured"))
        finally:
            registry._instances.pop("register")
        self.assertEqual(registry.get("register").mode, "sandbox")


class Directory(Base):
    def test_relevance_order_and_sponsored_slot_is_separate(self) -> None:
        _, zed = self.adviser("dir-z", name="Zed Abuja VAT", state="FCT", specialisms=["vat"])
        _, amy = self.adviser("dir-a", name="Amy Lagos PAYE", state="Lagos", specialisms=["paye"])
        _, bob = self.adviser("dir-b", name="Bob Lagos VAT", state="Lagos", specialisms=["vat"])
        anon = self.client()
        order = lambda q: [a["id"] for a in anon.get("/api/advisory/directory", q).body["items"] if a["id"] in (zed, amy, bob)]  # noqa: E731
        self.assertEqual(order({"specialism": "vat", "state": "Lagos"}), [bob, zed, amy])
        self.assertEqual(order({"specialism": "paye"}), [amy, bob, zed])
        before = order({"specialism": "vat", "state": "Lagos"})
        # A paid placement for Amy appears only in the separate sponsored slot.
        self.services.db.insert(
            "advisory_placements",
            {"id": "plc_test", "adviser_id": amy, "status": "active", "amount_kobo": 1, "duration_days": 30, "created_at": "2026-01-01T00:00:00+00:00",
             "starts_at": "2026-01-01T00:00:00+00:00", "ends_at": "2099-01-01T00:00:00+00:00"},
        )  # fmt: skip
        body = anon.get("/api/advisory/directory", {"specialism": "vat", "state": "Lagos"}).body
        self.assertEqual(order({"specialism": "vat", "state": "Lagos"}), before)
        self.assertEqual(body["sponsored_label"], "Sponsored listing")
        self.assertEqual([s["id"] for s in body["sponsored"]], [amy])
        self.assertTrue(body["sponsored"][0]["sponsored"])
        self.assertFalse(any(a.get("sponsored") for a in body["items"]))
        self.assertEqual(anon.get("/api/advisory/directory", {"specialism": "astrology"}).status, 422)


class Placement(Base):
    @unittest.skipUnless("billing" in __import__("taxng.services", fromlist=["module_names"]).module_names(), "billing module not installed")
    def test_purchase_through_billing_activates_sponsored_slot(self) -> None:
        c, adviser_id = self.adviser("plc")
        status, body = c.post("/api/advisory/advisers/me/placements")
        self.assertEqual(status, 201, body)
        self.assertEqual((body["placement"]["status"], body["checkout"]["mode"], body["price_status"]), ("pending_payment", "sandbox", "to_be_confirmed"))
        payment = self.services.db.one("SELECT purpose, reference_id FROM billing_payments WHERE checkout_id = ?", (body["checkout"]["checkout_id"],))
        self.assertEqual(payment, {"purpose": "advertising", "reference_id": body["placement"]["id"]})
        status, done = c.post(f"/api/billing/checkout/{body['checkout']['checkout_id']}/complete", {"outcome": "paid"})
        self.assertEqual(status, 200, done)
        placements = c.get("/api/advisory/advisers/me/placements").body["items"]
        self.assertEqual(placements[0]["status"], "active")
        self.assertIn(adviser_id, [s["id"] for s in self.client().get("/api/advisory/directory").body["sponsored"]])

    def test_billing_absent_is_handled(self) -> None:
        c, _ = self.adviser("nobill")
        saved = self.services.modules.pop("billing", None)
        try:
            status, body = c.post("/api/advisory/advisers/me/placements")
            self.assertEqual((status, body["error"]), (503, "billing_unavailable"))
        finally:
            if saved is not None:
                self.services.modules["billing"] = saved
        self.assertEqual(c.get("/api/advisory/advisers/me/placements").body["items"], [])

    def test_unapproved_listing_cannot_buy(self) -> None:
        c = self.client(self.email("unapproved"))
        c.post("/api/advisory/advisers", LISTING)
        self.assertEqual(c.post("/api/advisory/advisers/me/placements").status, 409)

    def test_other_modules_advertising_payments_are_ignored(self) -> None:
        self.services.modules["advisory"].advisers.activate_placement({"reference_id": "ad_campaign_1", "mode": "sandbox"})  # no error


@unittest.skipUnless("compliance" in __import__("taxng.services", fromlist=["module_names"]).module_names(), "compliance module not installed")
class Bookings(Base):
    def test_pre_engagement_consent_and_selected_intake_only(self) -> None:
        _, adviser_id = self.adviser("bk1")
        client = self.client_with_report("bk1c")
        options = {o["id"] for o in client.get("/api/advisory/intake-options").body["items"]}
        self.assertTrue({"fact.entity_type", "fact.has_rental_income", "health_check.dimensions"} <= options)
        status, body = client.post("/api/advisory/bookings", {"adviser_id": adviser_id, "topic": "Help", "intake_fields": ["fact.entity_type"]})
        self.assertEqual(status, 422)
        self.assertIn("pre_engagement_consent", body["fields"])
        self.assertEqual(client.post("/api/advisory/bookings", {"adviser_id": adviser_id, "topic": "Help", "intake_fields": ["fact.secret"], "pre_engagement_consent": True}).status, 422)
        booking = self.book(client, adviser_id, ["fact.entity_type", "health_check.dimensions"])
        self.assertEqual(booking["status"], "requested")
        self.assertEqual(set(booking["intake"]["data"]), {"fact.entity_type", "health_check.dimensions"})
        self.assertNotIn("fact.has_rental_income", json.dumps(booking["intake"]))
        self.assertIn("practitioner of record", booking["practitioner_notice"])
        kinds = [r["kind"] for r in self.services.db.query("SELECT kind FROM advisory_consents WHERE user_id = ?", (client.user_id,))]
        self.assertEqual(kinds, ["pre_engagement"])  # no marketing or engagement consent as a side effect
        consents = client.get("/api/advisory/consents").body
        self.assertFalse(consents["marketing"]["granted"])
        self.assertFalse(consents["findings_matching"]["granted"])

    def test_booking_rules(self) -> None:
        adviser, adviser_id = self.adviser("bk2")
        self.assertEqual(adviser.post("/api/advisory/bookings", {"adviser_id": adviser_id, "topic": "x", "pre_engagement_consent": True}).status, 409)
        pending = self.client(self.email("pending"))
        _, listing = pending.post("/api/advisory/advisers", LISTING)
        other = self.client(self.email("bk2c"))
        self.assertEqual(other.post("/api/advisory/bookings", {"adviser_id": listing["id"], "topic": "x", "pre_engagement_consent": True}).status, 404)
        self.assertEqual(self.client().post("/api/advisory/bookings", {}).status, 401)

    def test_state_machine_and_cross_user_isolation(self) -> None:
        adviser, adviser_id = self.adviser("bk3")
        rival, _ = self.adviser("bk3r")
        client = self.client_with_report("bk3c")
        stranger = self.client(self.email("bk3s"))
        booking = self.book(client, adviser_id, ["fact.entity_type"])
        bid = booking["id"]
        # Only the addressed adviser sees it; a non-adviser has no portal.
        self.assertEqual(rival.get(f"/api/advisory/adviser/bookings/{bid}").status, 404)
        self.assertEqual(rival.post(f"/api/advisory/adviser/bookings/{bid}/decision", {"decision": "accept"}).status, 404)
        self.assertEqual(stranger.get("/api/advisory/adviser/bookings").status, 404)
        self.assertEqual(stranger.post(f"/api/advisory/bookings/{bid}/cancel").status, 404)
        self.assertEqual(stranger.get("/api/advisory/bookings").body["items"], [])
        listed = adviser.get("/api/advisory/adviser/bookings").body["items"]
        self.assertEqual([b["id"] for b in listed], [bid])
        self.assertNotIn("intake", listed[0])
        status, detail = adviser.get(f"/api/advisory/adviser/bookings/{bid}")
        self.assertEqual((status, detail["intake"]["data"]["fact.entity_type"]), (200, "individual"))
        accesses = [e for e in self.services.audit.events(entity_id=bid) if e["action"] == "advisory.client_data_accessed"]
        self.assertEqual(json.loads(accesses[0]["data_json"])["resource"], "intake")
        self.assertEqual(adviser.post(f"/api/advisory/adviser/bookings/{bid}/decision", {"decision": "maybe"}).status, 422)
        status, accepted = adviser.post(f"/api/advisory/adviser/bookings/{bid}/decision", {"decision": "accept"})
        self.assertEqual((status, accepted["status"]), (200, "accepted"))
        self.assertEqual(accepted["engagement"]["status"], "active")
        self.assertIsNone(accepted["engagement"]["consent"])
        self.assertEqual(adviser.post(f"/api/advisory/adviser/bookings/{bid}/decision", {"decision": "decline"}).status, 409)
        self.assertEqual(client.post(f"/api/advisory/bookings/{bid}/cancel").status, 409)
        # Decline and cancel paths
        second = self.book(client, adviser_id)
        status, declined = adviser.post(f"/api/advisory/adviser/bookings/{second['id']}/decision", {"decision": "decline"})
        self.assertEqual((status, declined["status"], declined["engagement"]), (200, "declined", None))
        self.assertNotIn("intake", adviser.get(f"/api/advisory/adviser/bookings/{second['id']}").body)  # no intake after decline
        third = self.book(client, adviser_id)
        status, cancelled = client.post(f"/api/advisory/bookings/{third['id']}/cancel")
        self.assertEqual((status, cancelled["status"]), (200, "cancelled"))
        self.assertEqual(adviser.post(f"/api/advisory/adviser/bookings/{third['id']}/decision", {"decision": "accept"}).status, 409)

    def test_delegated_report_access_is_consented_scoped_revocable_and_audited(self) -> None:
        adviser, adviser_id = self.adviser("bk4")
        rival, _ = self.adviser("bk4r")
        client = self.client_with_report("bk4c")
        stranger = self.client(self.email("bk4s"))
        bid = self.book(client, adviser_id)["id"]
        eng = adviser.post(f"/api/advisory/adviser/bookings/{bid}/decision", {"decision": "accept"}).body["engagement"]["id"]
        report_path = f"/api/advisory/adviser/engagements/{eng}/report"
        self.assertEqual(adviser.get(report_path).status, 403)  # no consent yet
        self.assertEqual(rival.get(report_path).status, 404)
        self.assertEqual(stranger.get(report_path).status, 404)
        self.assertEqual(self.client().get(report_path).status, 401)
        self.assertEqual(stranger.post(f"/api/advisory/engagements/{eng}/consent", {"consent": True}).status, 404)
        self.assertEqual(client.post(f"/api/advisory/engagements/{eng}/consent", {}).status, 422)
        self.assertEqual(client.post(f"/api/advisory/engagements/{eng}/consent", {"consent": True, "scope": ["bank_statements"]}).status, 422)
        status, granted = client.post(f"/api/advisory/engagements/{eng}/consent", {"consent": True, "scope": ["health_check_report"]})
        self.assertEqual((status, granted["consent"]["scope"]), (200, ["health_check_report"]))
        self.assertEqual(client.post(f"/api/advisory/engagements/{eng}/consent", {"consent": True}).status, 409)
        status, body = adviser.get(report_path)
        self.assertEqual(status, 200)
        self.assertIn("not an official assessment", body["report"]["statement"])
        log = client.get(f"/api/advisory/engagements/{eng}/access-log").body["items"]
        self.assertIn(("advisory.client_data_accessed", "adviser"), [(e["action"], e["by"]) for e in log])
        self.assertEqual(stranger.get(f"/api/advisory/engagements/{eng}/access-log").status, 404)
        # Revoke, then access stops.
        status, revoked = client.delete(f"/api/advisory/engagements/{eng}/consent")
        self.assertEqual((status, revoked["consent"]), (200, None))
        self.assertEqual(adviser.get(report_path).status, 403)
        self.assertEqual(client.delete(f"/api/advisory/engagements/{eng}/consent").status, 409)
        # Re-grant, then ending the engagement revokes it.
        client.post(f"/api/advisory/engagements/{eng}/consent", {"consent": True})
        self.assertEqual(rival.post(f"/api/advisory/engagements/{eng}/end").status, 404)
        status, ended = adviser.post(f"/api/advisory/engagements/{eng}/end")
        self.assertEqual((status, ended["status"], ended["consent"]), (200, "ended", None))
        self.assertEqual(adviser.get(report_path).status, 403)
        self.assertEqual(client.post(f"/api/advisory/engagements/{eng}/consent", {"consent": True}).status, 409)
        self.assertEqual(client.post(f"/api/advisory/engagements/{eng}/end").status, 409)
        self.assertEqual([e["id"] for e in client.get("/api/advisory/engagements").body["items"]], [eng])
        self.assertEqual([e["id"] for e in adviser.get("/api/advisory/adviser/engagements").body["items"]], [eng])

    def test_findings_used_for_matching_only_with_consent(self) -> None:
        _, vat_only = self.adviser("bk5v", specialisms=["vat"])
        _, pit_adviser = self.adviser("bk5p", specialisms=["pit"])
        client = self.client_with_report("bk5c")
        body = client.get("/api/advisory/suggestions").body
        self.assertEqual((body["consent_required"], body["items"]), (True, []))
        self.assertFalse([e for e in self.services.audit.events(entity_id=client.user_id) if e["action"] == "advisory.findings_used_for_matching"])
        self.assertEqual(client.post("/api/advisory/consents/findings_matching", {"granted": "yes"}).status, 422)
        self.assertEqual(client.post("/api/advisory/consents/everything", {"granted": True}).status, 404)
        consents = client.post("/api/advisory/consents/findings_matching", {"granted": True}).body
        self.assertTrue(consents["findings_matching"]["granted"])
        self.assertFalse(consents["marketing"]["granted"])  # separate consents
        body = client.get("/api/advisory/suggestions").body
        ids = [a["id"] for a in body["items"]]
        self.assertIn(pit_adviser, ids)
        self.assertNotIn(vat_only, ids)
        self.assertIn("pit", body["specialisms"])
        self.assertTrue([e for e in self.services.audit.events(entity_id=client.user_id) if e["action"] == "advisory.findings_used_for_matching"])
        client.post("/api/advisory/consents/findings_matching", {"granted": False})
        self.assertTrue(client.get("/api/advisory/suggestions").body["consent_required"])

    def test_notifications_go_to_both_parties(self) -> None:
        adviser, adviser_id = self.adviser("bk6")
        client = self.client(self.email("bk6c"))
        bid = self.book(client, adviser_id)["id"]
        adviser_email = adviser.get("/api/me").body["email"]
        self.assertIn("booking request", self.services.notifier.recent(adviser_email, limit=1)[0]["body"])
        adviser.post(f"/api/advisory/adviser/bookings/{bid}/decision", {"decision": "decline"})
        client_email = client.get("/api/me").body["email"]
        self.assertIn("declined", self.services.notifier.recent(client_email, limit=1)[0]["body"])


if __name__ == "__main__":
    unittest.main()
