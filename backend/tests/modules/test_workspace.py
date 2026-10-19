"""Workspace module: organisations, members, invitations, calendar, returns and maker-checker."""

from __future__ import annotations

import base64
import json
import re
from decimal import Decimal
from typing import Any

from taxng.calculators import calculate_vat, calculate_wht

from ..helpers import Client, ServicesTestCase, add_member, create_org


def make_org(owner: Client, **body: Any) -> str:
    status, org = owner.post("/api/orgs", {"name": "Acme Ltd", "entity_type": "company", "tin": "12345678", "state": "Lagos", **body})
    assert status == 201, org
    return org["id"]


def vat_line(day: str = "2026-03-10", amount: str = "100000", kind: str = "output") -> dict[str, Any]:
    return {"kind": kind, "details": {"invoice_ref": "INV-1", "counterparty": "Buyer Ltd"}, "inputs": {"supply_date": day, "amount": amount, "category": "standard"}}


class Team:
    """An organisation with one member per role and an outsider with their own organisation."""

    def __init__(self, case: ServicesTestCase, tag: str) -> None:
        self.owner = case.client(f"owner-{tag}@example.com")
        self.org = make_org(self.owner, name=f"Org {tag}")
        self.preparer = case.client(f"prep-{tag}@example.com")
        self.reviewer = case.client(f"rev-{tag}@example.com")
        self.viewer = case.client(f"view-{tag}@example.com")
        add_member(case.services, self.org, self.preparer, "preparer")
        add_member(case.services, self.org, self.reviewer, "reviewer")
        add_member(case.services, self.org, self.viewer, "read_only")
        self.outsider = case.client(f"out-{tag}@example.com")
        self.other_org = make_org(self.outsider, name=f"Other {tag}")

    def vat_return(self, period: str = "2026-03") -> str:
        status, ret = self.preparer.post(f"/api/orgs/{self.org}/returns", {"return_type": "vat_monthly", "period": period})
        assert status == 201, ret
        return ret["id"]

    def approved_vat(self, period: str = "2026-03") -> str:
        rid = self.vat_return(period)
        base = f"/api/orgs/{self.org}/returns/{rid}"
        assert self.preparer.post(f"{base}/lines", vat_line(f"{period}-10")).status == 201
        assert self.preparer.post(f"{base}/submit").status == 200
        status, body = self.reviewer.post(f"{base}/approve")
        assert status == 200, body
        return rid


class Organisations(ServicesTestCase):
    def test_create_makes_caller_owner_and_is_audited(self) -> None:
        owner = self.client("o-create@example.com")
        status, org = owner.post("/api/orgs", {"name": "Kano Foods", "entity_type": "company", "tin": "12345678-0001", "cac_number": "rc123456", "state": "Kano"})
        self.assertEqual(status, 201)
        self.assertEqual((org["role"], org["cac_number"]), ("owner", "RC123456"))
        self.assertEqual(org["facts"], {"entity_type": "company", "state": "Kano"})
        me = owner.get("/api/me").body
        self.assertEqual(me["memberships"][org["id"]], "owner")
        self.assertIn("org.create", [e["action"] for e in self.services.audit.events(org_id=org["id"])])

    def test_validation(self) -> None:
        owner = self.client("o-valid@example.com")
        self.assertEqual(owner.post("/api/orgs", {"name": ""}).status, 422)
        self.assertEqual(owner.post("/api/orgs", {"name": "X", "entity_type": "individual"}).status, 422)
        self.assertEqual(owner.post("/api/orgs", {"name": "X", "tin": "12"}).status, 422)

    def test_anonymous_is_401(self) -> None:
        anon = Client(self.services)
        self.assertEqual(anon.post("/api/orgs", {"name": "X"}).status, 401)
        self.assertEqual(anon.get("/api/orgs").status, 401)
        self.assertEqual(anon.get("/api/orgs/org_x").status, 401)

    def test_facts_use_contract_keys_and_roles(self) -> None:
        t = Team(self, "facts")
        facts = {"has_employees": True, "employee_count": 12, "annual_turnover": "45,000,000", "sells_taxable_supplies": True, "makes_wht_payments": False}
        status, org = t.preparer.put(f"/api/orgs/{t.org}/facts", facts)
        self.assertEqual(status, 200, org)
        self.assertEqual(org["facts"]["annual_turnover"], "45000000.00")
        self.assertEqual(org["facts"]["employee_count"], 12)
        self.assertEqual(org["facts"]["entity_type"], "company")
        self.assertEqual(t.preparer.put(f"/api/orgs/{t.org}/facts", {"sector": "x"}).status, 422)
        self.assertEqual(t.preparer.put(f"/api/orgs/{t.org}/facts", {"employee_count": -1}).status, 422)
        self.assertEqual(t.reviewer.put(f"/api/orgs/{t.org}/facts", facts).status, 403)
        self.assertEqual(t.viewer.put(f"/api/orgs/{t.org}/facts", facts).status, 403)
        self.assertEqual(t.outsider.put(f"/api/orgs/{t.org}/facts", facts).status, 404)
        # Core details are owner-only.
        self.assertEqual(t.preparer.put(f"/api/orgs/{t.org}", {"name": "Renamed"}).status, 403)
        self.assertEqual(t.owner.put(f"/api/orgs/{t.org}", {"name": "Renamed"}).status, 200)
        self.assertEqual(self.services.modules["workspace"].facts(t.org)["has_employees"], True)

    def test_identity_verification_is_sandbox_and_owner_only(self) -> None:
        t = Team(self, "kyc")
        status, result = t.owner.post(f"/api/orgs/{t.org}/verify", {"id_type": "tin"})
        self.assertEqual((status, result["result"], result["mode"]), (200, "verified", "sandbox"))
        self.assertEqual(t.owner.post(f"/api/orgs/{t.org}/verify", {"id_type": "cac"}).status, 422)  # no CAC on file
        self.assertEqual(t.preparer.post(f"/api/orgs/{t.org}/verify", {"id_type": "tin"}).status, 403)
        self.assertEqual(t.outsider.post(f"/api/orgs/{t.org}/verify", {"id_type": "tin"}).status, 404)
        status, org = t.viewer.get(f"/api/orgs/{t.org}")
        self.assertEqual(org["verifications"][0]["id_masked"], "****5678")

    def test_staff_have_no_access_to_org_data(self) -> None:
        t = Team(self, "staff")
        for role in ("editor", "sales", "support", "admin"):
            staff = self.client(f"staff-{role}@example.com", staff_role=role)
            self.assertEqual(staff.get(f"/api/orgs/{t.org}").status, 404, role)
            self.assertEqual(staff.get(f"/api/orgs/{t.org}/returns").status, 404, role)
            self.assertEqual(staff.get(f"/api/orgs/{t.org}/audit").status, 404, role)

    def test_org_list_is_own_only(self) -> None:
        t = Team(self, "list")
        ids = {o["id"] for o in t.outsider.get("/api/orgs").body["items"]}
        self.assertEqual(ids, {t.other_org})


class Members(ServicesTestCase):
    def test_role_change_and_removal_rules(self) -> None:
        t = Team(self, "mem")
        base = f"/api/orgs/{t.org}/members"
        self.assertEqual(len(t.viewer.get(base).body["items"]), 4)
        self.assertEqual(t.preparer.put(f"{base}/{t.viewer.user_id}", {"role": "owner"}).status, 403)
        self.assertEqual(t.outsider.put(f"{base}/{t.viewer.user_id}", {"role": "owner"}).status, 404)
        self.assertEqual(t.owner.put(f"{base}/{t.viewer.user_id}", {"role": "boss"}).status, 422)
        self.assertEqual(t.owner.put(f"{base}/{t.viewer.user_id}", {"role": "reviewer"}).status, 200)
        # Last owner can be neither demoted nor removed.
        self.assertEqual(t.owner.put(f"{base}/{t.owner.user_id}", {"role": "preparer"}).status, 409)
        self.assertEqual(t.owner.delete(f"{base}/{t.owner.user_id}").status, 409)
        # With a second owner, the first can step down.
        self.assertEqual(t.owner.put(f"{base}/{t.reviewer.user_id}", {"role": "owner"}).status, 200)
        self.assertEqual(t.owner.put(f"{base}/{t.owner.user_id}", {"role": "preparer"}).status, 200)
        self.assertEqual(t.reviewer.delete(f"{base}/{t.reviewer.user_id}").status, 409)
        # Non-owners may leave but not remove others.
        self.assertEqual(t.preparer.delete(f"{base}/{t.viewer.user_id}").status, 403)
        self.assertEqual(t.viewer.delete(f"{base}/{t.viewer.user_id}").status, 200)
        self.assertEqual(t.viewer.get(f"/api/orgs/{t.org}").status, 404)
        # Cross-tenant: an outsider's user id in this org is not found.
        self.assertEqual(t.reviewer.delete(f"{base}/{t.outsider.user_id}").status, 404)
        actions = [e["action"] for e in self.services.audit.events(org_id=t.org)]
        self.assertIn("member.role_change", actions)
        self.assertIn("member.remove", actions)


class Invitations(ServicesTestCase):
    def _token(self, email: str) -> str:
        body = self.services.notifier.recent(email, limit=1)[0]["body"]
        return re.search(r"/invite/([A-Za-z0-9_\-]+)", body).group(1)

    def test_invite_accept_flow_with_email_match(self) -> None:
        t = Team(self, "inv")
        base = f"/api/orgs/{t.org}/invitations"
        self.assertEqual(t.preparer.post(base, {"email": "new@example.com", "role": "preparer"}).status, 403)
        self.assertEqual(t.outsider.post(base, {"email": "new@example.com", "role": "preparer"}).status, 404)
        self.assertEqual(t.owner.post(base, {"email": "bad", "role": "preparer"}).status, 422)
        self.assertEqual(t.owner.post(base, {"email": "new@example.com", "role": "admin"}).status, 422)
        self.assertEqual(t.owner.post(base, {"email": t.viewer.get("/api/me").body["email"], "role": "owner"}).status, 409)
        status, inv = t.owner.post(base, {"email": "New@Example.com", "role": "reviewer"})
        self.assertEqual(status, 201)
        token = self._token("new@example.com")
        # Only the hash is stored.
        row = self.services.db.one("SELECT * FROM invitations WHERE id = ?", (inv["id"],))
        self.assertNotIn(token, json.dumps(row))
        self.assertNotIn(token, json.dumps(self.services.audit.events(org_id=t.org)))
        self.assertEqual(len(t.owner.get(base).body["items"]), 1)
        self.assertEqual(t.preparer.get(base).status, 403)
        # Anonymous, then wrong email.
        self.assertEqual(Client(self.services).post("/api/invitations/accept", {"token": token}).status, 401)
        self.assertEqual(t.outsider.post("/api/invitations/accept", {"token": token}).status, 403)
        self.assertEqual(t.outsider.get(f"/api/orgs/{t.org}").status, 404)
        newcomer = self.client("new@example.com")
        self.assertEqual(newcomer.post("/api/invitations/accept", {"token": "nope"}).status, 422)
        status, body = newcomer.post("/api/invitations/accept", {"token": token})
        self.assertEqual((status, body["role"]), (200, "reviewer"))
        self.assertEqual(newcomer.get(f"/api/orgs/{t.org}").body["role"], "reviewer")
        # Single use.
        self.assertEqual(newcomer.post("/api/invitations/accept", {"token": token}).status, 422)

    def test_expired_and_revoked_and_reinvite(self) -> None:
        t = Team(self, "inv2")
        base = f"/api/orgs/{t.org}/invitations"
        t.owner.post(base, {"email": "late@example.com", "role": "read_only"})
        old = self._token("late@example.com")
        t.owner.post(base, {"email": "late@example.com", "role": "preparer"})  # re-invite revokes the first
        new = self._token("late@example.com")
        late = self.client("late@example.com")
        self.assertEqual(late.post("/api/invitations/accept", {"token": old}).status, 422)
        self.services.db.execute("UPDATE invitations SET expires_at = '2020-01-01T00:00:00+00:00' WHERE org_id = ? AND revoked_at IS NULL", (t.org,))
        status, body = late.post("/api/invitations/accept", {"token": new})
        self.assertEqual(status, 422)
        self.assertIn("expired", body["fields"]["token"])
        status, inv = t.owner.post(base, {"email": "late@example.com", "role": "preparer"})
        self.assertEqual(t.outsider.delete(f"/api/orgs/{t.other_org}/invitations/{inv['id']}").status, 404)  # cross-tenant
        self.assertEqual(t.owner.delete(f"{base}/{inv['id']}").status, 200)
        self.assertEqual(late.post("/api/invitations/accept", {"token": self._token("late@example.com")}).status, 422)


class FakeCompliance:
    def __init__(self) -> None:
        self.seen: list[dict[str, Any]] = []

    def obligations_for(self, facts: dict[str, Any], year: int) -> list[dict[str, Any]]:
        self.seen.append(dict(facts))
        return [
            {
                "id": "vat-return",
                "tax": "vat",
                "title": "VAT return",
                "frequency": "monthly",
                "period": f"{year}-{m:02d}",
                "due_date": f"{year + (m == 12)}-{m % 12 + 1:02d}-21",
                "provision": "nta2025-vat",
                "evidence": ["Sales invoices"],
                "applies_because": "You make taxable supplies",
                "review_status": "secondary_source",
            }
            for m in range(1, 13)
        ]

    def account_summary(self, user_id: str) -> dict[str, Any]:
        return {}


class Calendar(ServicesTestCase):
    def setUp(self) -> None:
        self.original = self.services.modules.get("compliance")

    def tearDown(self) -> None:
        if self.original is None:
            self.services.modules.pop("compliance", None)
        else:
            self.services.modules["compliance"] = self.original

    def test_degrades_without_compliance(self) -> None:
        self.services.modules.pop("compliance", None)
        t = Team(self, "cal0")
        status, cal = t.viewer.get(f"/api/orgs/{t.org}/calendar", {"year": "2026"})
        self.assertEqual((status, cal["available"], cal["items"]), (200, False, []))
        self.assertTrue(cal["notice"])
        self.assertEqual(t.outsider.get(f"/api/orgs/{t.org}/calendar").status, 404)
        self.assertEqual(Client(self.services).get(f"/api/orgs/{t.org}/calendar").status, 401)
        summary = self.services.modules["workspace"].org_summary(t.org)
        self.assertEqual(summary["upcoming_obligations"], [])
        # Linking to an obligation needs the calendar.
        status, _ = t.preparer.post(f"/api/orgs/{t.org}/returns", {"return_type": "vat_monthly", "period": "2026-03", "obligation_id": "vat-return", "obligation_period": "2026-03"})
        self.assertEqual(status, 422)

    def test_degrades_when_compliance_raises(self) -> None:
        class Broken:
            def obligations_for(self, facts: dict[str, Any], year: int) -> list[dict[str, Any]]:
                raise RuntimeError("boom")

        self.services.modules["compliance"] = Broken()
        t = Team(self, "calx")
        self.assertFalse(t.viewer.get(f"/api/orgs/{t.org}/calendar").body["available"])

    def test_status_tracks_linked_return(self) -> None:
        fake = FakeCompliance()
        self.services.modules["compliance"] = fake
        t = Team(self, "cal1")
        t.owner.put(f"/api/orgs/{t.org}/facts", {"sells_taxable_supplies": True})
        cal = t.viewer.get(f"/api/orgs/{t.org}/calendar", {"year": "2026"}).body
        self.assertTrue(cal["available"])
        self.assertEqual(fake.seen[-1], {"entity_type": "company", "state": "Lagos", "sells_taxable_supplies": True})
        march = next(i for i in cal["items"] if i["period"] == "2026-03")
        self.assertEqual((march["status"], march["suggested_return_type"]), ("not_started", "vat_monthly"))
        self.assertEqual(t.preparer.post(f"/api/orgs/{t.org}/returns", {"return_type": "vat_monthly", "period": "2026-03", "obligation_id": "vat-return", "obligation_period": "2026-13"}).status, 422)
        status, ret = t.preparer.post(
            f"/api/orgs/{t.org}/returns", {"return_type": "vat_monthly", "period": "2026-03", "obligation_id": "vat-return", "obligation_period": "2026-03", "due_date": "1999-01-01"}
        )
        self.assertEqual(status, 201)
        self.assertEqual(ret["due_date"], "2026-04-21")  # from the obligations engine, not the client
        base = f"/api/orgs/{t.org}/returns/{ret['id']}"

        def status_now() -> str:
            items = t.viewer.get(f"/api/orgs/{t.org}/calendar", {"year": "2026"}).body["items"]
            return next(i for i in items if i["period"] == "2026-03")["status"]

        self.assertEqual(status_now(), "in_preparation")
        t.preparer.post(f"{base}/lines", vat_line())
        t.preparer.post(f"{base}/submit")
        self.assertEqual(status_now(), "submitted_for_review")
        t.reviewer.post(f"{base}/approve")
        self.assertEqual(status_now(), "approved")
        t.preparer.post(f"{base}/file", {"idempotency_key": "cal-key-0001"})
        # Sandbox acknowledgement is not a filing.
        self.assertEqual(status_now(), "approved")
        items = t.viewer.get(f"/api/orgs/{t.org}/calendar", {"year": "2026"}).body["items"]
        self.assertTrue(next(i for i in items if i["period"] == "2026-03")["sandbox_acknowledged"])
        # Simulate a real filing and full payment to reach the end of the ladder.
        self.services.db.update("ws_returns", {"status": "filed"}, "id = ?", (ret["id"],))
        self.assertEqual(status_now(), "filed")
        liability = t.viewer.get(base).body["reconciliation"]["liability"]
        t.preparer.post(f"{base}/payments", {"receipt_reference": "RCPT-CAL-1", "amount": liability, "paid_on": "2026-04-20", "channel": "remita"})
        self.assertEqual(status_now(), "paid")
        summary = self.services.modules["workspace"].org_summary(t.org)
        self.assertEqual(summary["org"]["tin_masked"], "****5678")
        self.assertNotIn("12345678", json.dumps(summary))
        self.assertTrue(summary["calendar_available"])

    def test_contract_against_real_compliance(self) -> None:
        if self.original is None:
            self.skipTest("compliance module not installed")
        t = Team(self, "calreal")
        t.owner.put(f"/api/orgs/{t.org}/facts", {"has_employees": True, "employee_count": 5, "sells_taxable_supplies": True, "makes_wht_payments": True, "annual_turnover": "200000000"})
        status, cal = t.viewer.get(f"/api/orgs/{t.org}/calendar", {"year": "2026"})
        self.assertEqual(status, 200)
        for item in cal["items"]:
            self.assertIn(item["status"], ("not_started", "in_preparation", "submitted_for_review", "approved", "filed", "paid"))
        # Every suggested return type can be started straight from the calendar.
        started = set()
        for item in cal["items"]:
            rtype = item["suggested_return_type"]
            if not rtype or rtype in started:
                continue
            period = item["period"][:4] if rtype == "cit_annual" else item["period"]
            status, ret = t.preparer.post(
                f"/api/orgs/{t.org}/returns", {"return_type": rtype, "period": period, "obligation_id": item["id"], "obligation_period": item["period"]}
            )
            self.assertEqual(status, 201, ret)
            self.assertEqual(ret["due_date"], item["due_date"])
            started.add(rtype)
        self.assertEqual(started, {"vat_monthly", "wht_monthly", "paye_monthly", "cit_annual"})
        linked = [i for i in t.viewer.get(f"/api/orgs/{t.org}/calendar", {"year": "2026"}).body["items"] if i["return_id"]]
        self.assertEqual({i["status"] for i in linked}, {"in_preparation"})


class Returns(ServicesTestCase):
    def test_access_rules(self) -> None:
        t = Team(self, "racc")
        base = f"/api/orgs/{t.org}/returns"
        anon = Client(self.services)
        self.assertEqual(anon.get(base).status, 401)
        self.assertEqual(anon.post(base, {"return_type": "vat_monthly", "period": "2026-03"}).status, 401)
        self.assertEqual(t.outsider.get(base).status, 404)
        self.assertEqual(t.outsider.post(base, {"return_type": "vat_monthly", "period": "2026-03"}).status, 404)
        self.assertEqual(t.viewer.post(base, {"return_type": "vat_monthly", "period": "2026-03"}).status, 403)
        self.assertEqual(t.reviewer.post(base, {"return_type": "vat_monthly", "period": "2026-03"}).status, 403)
        rid = t.vat_return()
        self.assertEqual(t.viewer.get(f"{base}/{rid}").status, 200)
        self.assertEqual(t.viewer.post(f"{base}/{rid}/lines", vat_line()).status, 403)
        self.assertEqual(t.reviewer.post(f"{base}/{rid}/lines", vat_line()).status, 403)
        # Cross-tenant: the outsider uses their own org id with this return id.
        other = f"/api/orgs/{t.other_org}/returns/{rid}"
        self.assertEqual(t.outsider.get(other).status, 404)
        self.assertEqual(t.outsider.post(f"{other}/lines", vat_line()).status, 404)
        self.assertEqual(t.outsider.post(f"{other}/submit").status, 404)
        self.assertEqual(t.outsider.post(f"{other}/approve").status, 404)
        self.assertEqual(t.outsider.get(f"{other}/export").status, 404)
        self.assertEqual(t.outsider.post(f"{other}/file", {"idempotency_key": "x-tenant-01"}).status, 404)
        self.assertEqual(t.outsider.post(f"{other}/payments", {"receipt_reference": "R", "amount": "1", "paid_on": "2026-01-01", "channel": "remita"}).status, 404)
        self.assertEqual(t.outsider.get(f"/api/orgs/{t.other_org}/returns").body["items"], [])

    def test_validation(self) -> None:
        t = Team(self, "rval")
        base = f"/api/orgs/{t.org}/returns"
        self.assertEqual(t.preparer.post(base, {"return_type": "stamp_duty", "period": "2026-03"}).status, 422)
        self.assertEqual(t.preparer.post(base, {"return_type": "vat_monthly", "period": "2026"}).status, 422)
        self.assertEqual(t.preparer.post(base, {"return_type": "cit_annual", "period": "2026-01"}).status, 422)
        rid = t.vat_return("2026-04")
        self.assertEqual(t.preparer.post(base, {"return_type": "vat_monthly", "period": "2026-04"}).status, 409)
        lines = f"{base}/{rid}/lines"
        self.assertEqual(t.preparer.post(lines, vat_line("2026-05-01")).status, 422)  # outside period
        self.assertEqual(t.preparer.post(lines, vat_line(kind="payment")).status, 422)
        self.assertEqual(t.preparer.post(lines, {"kind": "output", "inputs": {"supply_date": "2026-04-01", "amount": "-5"}}).status, 422)
        self.assertEqual(t.preparer.post(lines, {"kind": "output", "inputs": {"supply_date": "2026-04-01", "amount": "5", "rate": "0.5"}}).status, 422)

    def test_figures_come_from_calculators_with_rules_version(self) -> None:
        t = Team(self, "rcalc")
        rid = t.vat_return("2026-03")
        base = f"/api/orgs/{t.org}/returns/{rid}"
        t.preparer.post(f"{base}/lines", vat_line("2026-03-02", "250000", "output"))
        t.preparer.post(f"{base}/lines", vat_line("2026-03-03", "80000", "input"))
        body = t.viewer.get(base).body
        expected_out = calculate_vat({"supply_date": "2026-03-02", "amount": "250000", "category": "standard"}, self.services.tree)
        expected_in = calculate_vat({"supply_date": "2026-03-03", "amount": "80000", "category": "standard"}, self.services.tree)
        self.assertEqual(body["lines"][0]["result"]["outputs"], expected_out.to_dict()["outputs"])
        self.assertEqual(body["lines"][0]["rules_version"], self.services.tree.version)
        net = Decimal(expected_out.outputs["vat"]) - Decimal(expected_in.outputs["vat"])
        self.assertEqual(body["totals"]["net_vat"], str(net))
        self.assertEqual(body["totals"]["liability"], str(net))

        status, wret = t.preparer.post(f"/api/orgs/{t.org}/returns", {"return_type": "wht_monthly", "period": "2026-03"})
        wline = {"payment_date": "2026-03-05", "payment_type": "rent", "recipient_type": "corporate", "amount": "1000000"}
        status, line = t.preparer.post(f"/api/orgs/{t.org}/returns/{wret['id']}/lines", {"kind": "payment", "details": {"payee_name": "Landlord Ltd"}, "inputs": wline})
        self.assertEqual(status, 201, line)
        self.assertEqual(line["result"]["outputs"]["wht"], calculate_wht(wline, self.services.tree).outputs["wht"])

        status, pret = t.preparer.post(f"/api/orgs/{t.org}/returns", {"return_type": "paye_monthly", "period": "2026-03"})
        status, line = t.preparer.post(f"/api/orgs/{t.org}/returns/{pret['id']}/lines", {"kind": "employee", "details": {"employee_ref": "E1"}, "inputs": {"annual_gross_income": "6000000"}})
        self.assertEqual(status, 201, line)
        self.assertEqual(line["result"]["inputs"]["tax_year"], 2026)
        self.assertEqual(t.viewer.get(f"/api/orgs/{t.org}/returns/{pret['id']}").body["totals"]["monthly_paye"], line["result"]["outputs"]["monthly_tax"])

        status, cret = t.preparer.post(f"/api/orgs/{t.org}/returns", {"return_type": "cit_annual", "period": "2026"})
        cbase = f"/api/orgs/{t.org}/returns/{cret['id']}/lines"
        status, line = t.preparer.post(cbase, {"kind": "computation", "inputs": {"annual_turnover": "500000000", "total_profits": "80000000"}})
        self.assertEqual(status, 201, line)
        self.assertEqual(t.preparer.post(cbase, {"kind": "computation", "inputs": {"annual_turnover": "1", "total_profits": "1"}}).status, 409)

    def test_lifecycle_locking_and_reopen(self) -> None:
        t = Team(self, "rlife")
        rid = t.vat_return()
        base = f"/api/orgs/{t.org}/returns/{rid}"
        self.assertEqual(t.preparer.post(f"{base}/submit").status, 409)  # no lines yet
        status, line = t.preparer.post(f"{base}/lines", vat_line())
        lid = line["id"]
        self.assertEqual(t.reviewer.post(f"{base}/approve").status, 409)  # not submitted
        self.assertEqual(t.preparer.post(f"{base}/submit").status, 200)
        self.assertEqual(t.preparer.post(f"{base}/lines", vat_line()).status, 409)  # with reviewer
        self.assertEqual(t.preparer.put(f"{base}/lines/{lid}", vat_line(amount="1")).status, 409)
        self.assertEqual(t.reviewer.post(f"{base}/request-changes", {"comment": ""}).status, 422)
        status, body = t.reviewer.post(f"{base}/request-changes", {"comment": "Attach the invoice"})
        self.assertEqual((status, body["status"]), (200, "changes_requested"))
        self.assertEqual(t.preparer.put(f"{base}/lines/{lid}", vat_line(amount="120000")).status, 200)
        self.assertEqual(t.preparer.post(f"{base}/submit").status, 200)
        status, body = t.reviewer.post(f"{base}/approve", {"comment": "OK"})
        self.assertEqual((status, body["status"], body["locked"]), (200, "approved", True))
        self.assertTrue(body["approval_hash"])
        for call in (
            lambda: t.preparer.post(f"{base}/lines", vat_line()),
            lambda: t.owner.put(f"{base}/lines/{lid}", vat_line(amount="1")),
            lambda: t.owner.delete(f"{base}/lines/{lid}"),
            lambda: t.preparer.post(f"{base}/submit"),
        ):
            self.assertEqual(call().status, 409)
        # Reopening: owner only, reason required, audited.
        self.assertEqual(t.preparer.post(f"{base}/reopen", {"reason": "x"}).status, 403)
        self.assertEqual(t.reviewer.post(f"{base}/reopen", {"reason": "x"}).status, 403)
        self.assertEqual(t.owner.post(f"{base}/reopen", {"reason": ""}).status, 422)
        status, body = t.owner.post(f"{base}/reopen", {"reason": "Late credit note"})
        self.assertEqual((status, body["status"], body["approval_hash"]), (200, "draft", None))
        self.assertEqual(t.preparer.delete(f"{base}/lines/{lid}").status, 200)
        actions = [e["action"] for e in self.services.audit.events(org_id=t.org, entity_id=rid)]
        for action in ("return.create", "return.line_add", "return.submit", "return.request_changes", "return.approve", "return.reopen", "return.line_delete"):
            self.assertIn(action, actions)
        self.assertEqual([e["action"] for e in body["events"]], ["created", "submitted", "changes_requested", "submitted", "approved", "reopened"])


class MakerChecker(ServicesTestCase):
    def test_submitter_can_never_approve_own_return(self) -> None:
        t = Team(self, "mc1")
        # Owner prepares and submits: owner cannot approve, reviewer can.
        status, ret = t.owner.post(f"/api/orgs/{t.org}/returns", {"return_type": "vat_monthly", "period": "2026-06"})
        base = f"/api/orgs/{t.org}/returns/{ret['id']}"
        t.owner.post(f"{base}/lines", vat_line("2026-06-01"))
        t.owner.post(f"{base}/submit")
        status, body = t.owner.post(f"{base}/approve")
        self.assertEqual(status, 403)
        self.assertIn("different reviewer", body["message"])
        self.assertEqual(t.owner.post(f"{base}/request-changes", {"comment": "self"}).status, 403)
        self.assertFalse(t.owner.get(base).body["permissions"]["review"])
        self.assertTrue(t.reviewer.get(base).body["permissions"]["review"])
        self.assertEqual(t.preparer.post(f"{base}/approve").status, 403)  # wrong role
        self.assertEqual(t.viewer.post(f"{base}/approve").status, 403)
        self.assertEqual(t.reviewer.post(f"{base}/approve").status, 200)

    def test_editor_cannot_approve_even_if_someone_else_submitted(self) -> None:
        t = Team(self, "mc2")
        rid = t.vat_return("2026-07")
        base = f"/api/orgs/{t.org}/returns/{rid}"
        t.owner.post(f"{base}/lines", vat_line("2026-07-01"))  # owner is a maker
        t.preparer.post(f"{base}/submit")
        status, body = t.owner.post(f"{base}/approve")
        self.assertEqual(status, 403)
        self.assertIn("edited", body["message"])
        self.assertEqual(t.reviewer.post(f"{base}/approve").status, 200)

    def test_reopen_starts_a_fresh_maker_set(self) -> None:
        t = Team(self, "mc3")
        rid = t.approved_vat("2026-08")
        base = f"/api/orgs/{t.org}/returns/{rid}"
        t.owner.post(f"{base}/reopen", {"reason": "Correction"})
        t.preparer.post(f"{base}/submit")
        self.assertEqual(t.owner.post(f"{base}/approve").status, 200)

    def test_review_by_api_key_is_refused(self) -> None:
        from taxng.platform.access import Principal

        t = Team(self, "mc4")
        rid = t.vat_return("2026-09")
        base = f"/api/orgs/{t.org}/returns/{rid}"
        t.preparer.post(f"{base}/lines", vat_line("2026-09-01"))
        t.preparer.post(f"{base}/submit")
        me = t.reviewer.get("/api/me").body
        key_principal = Principal(me["id"], me["email"], "", "none", False, {t.org: "reviewer"}, via="api_key", scopes=("workspace:read", "workspace:write"))
        self.services.hooks["api_key"] = lambda services, token: key_principal if token == "k1" else None
        try:
            key = Client(self.services)
            key.headers = {"authorization": "Bearer k1"}
            # API keys are resolved only on /api/v1 (router), so workspace routes
            # treat the caller as anonymous and the key can never approve.
            self.assertEqual(key.get(base).status, 401)
            self.assertEqual(key.post(f"{base}/approve").status, 401)
            # Defence in depth: even a key principal injected directly is refused.
            from taxng.api.router import Request, dispatch

            reply = dispatch(self.services, Request("POST", f"{base}/approve", principal=key_principal))
            self.assertEqual(reply.status, 403)
        finally:
            self.services.hooks.pop("api_key", None)


class Export(ServicesTestCase):
    def test_export_only_after_approval_and_marked_official_channels(self) -> None:
        t = Team(self, "exp")
        rid = t.vat_return("2026-03")
        base = f"/api/orgs/{t.org}/returns/{rid}"
        self.assertEqual(t.viewer.get(f"{base}/export").status, 409)
        t.preparer.post(f"{base}/lines", vat_line())
        t.preparer.post(f"{base}/submit")
        t.reviewer.post(f"{base}/approve")
        reply = t.viewer.get(f"{base}/export", {"format": "json"})
        self.assertEqual(reply.status, 200)
        doc = json.loads(reply.raw)
        self.assertEqual(doc["layout"], "taxng.return.v1")
        self.assertEqual(doc["filing_status"], "not_filed")
        self.assertIn("For submission through official channels", doc["notice"])
        self.assertEqual(doc["taxpayer"]["tin"], "12345678")
        self.assertEqual(doc["return"]["period_end"], "2026-03-31")
        self.assertEqual(doc["schedule"][0]["rules_version"], self.services.tree.version)
        self.assertIn("vat", doc["columns"])
        reply = t.viewer.get(f"{base}/export", {"format": "csv"})
        self.assertEqual(reply.content_type, "text/csv")
        text = reply.raw.decode()
        self.assertIn("For submission through official channels", text)
        self.assertIn("line_no,kind,invoice_ref", text)
        self.assertEqual(t.viewer.get(f"{base}/export", {"format": "xml"}).status, 422)
        # After a sandbox acknowledgement the export says so and still points to official channels.
        t.preparer.post(f"{base}/file", {"idempotency_key": "exp-key-0001"})
        doc = json.loads(t.viewer.get(f"{base}/export").raw)
        self.assertEqual(doc["filing_status"], "not_filed_sandbox_acknowledgement_only")
        self.assertIn("NOT been filed", doc["notice"])


class Documents(ServicesTestCase):
    def _upload(self, client: Client, org: str) -> str:
        data = base64.b64encode(b"%PDF-1.4 receipt").decode()
        status, record = client.post("/api/files", {"org_id": org, "name": "invoice.pdf", "content_type": "application/pdf", "data_base64": data, "category": "invoice"})
        assert status == 201, record
        return record["id"]

    def test_link_documents_as_evidence(self) -> None:
        t = Team(self, "doc")
        rid = t.vat_return()
        base = f"/api/orgs/{t.org}/returns/{rid}/documents"
        fid = self._upload(t.preparer, t.org)
        foreign = self._upload(t.outsider, t.other_org)
        self.assertEqual(t.viewer.post(base, {"file_id": fid}).status, 403)
        self.assertEqual(t.preparer.post(base, {"file_id": foreign}).status, 404)  # another tenant's file
        self.assertEqual(t.outsider.post(f"/api/orgs/{t.other_org}/returns/{rid}/documents", {"file_id": foreign}).status, 404)
        self.assertEqual(t.preparer.post(base, {"file_id": fid}).status, 201)
        detail = t.viewer.get(f"/api/orgs/{t.org}/returns/{rid}").body
        self.assertEqual([d["id"] for d in detail["documents"]], [fid])
        links = t.viewer.get(f"/api/orgs/{t.org}/document-links").body["links"]
        self.assertEqual(links[fid][0]["return_id"], rid)
        self.assertEqual(t.outsider.get(f"/api/orgs/{t.org}/document-links").status, 404)
        self.assertEqual(t.preparer.delete(f"{base}/{fid}").status, 200)
        self.assertEqual(t.preparer.delete(f"{base}/{fid}").status, 404)


class OrgAudit(ServicesTestCase):
    def test_audit_view_roles_and_isolation(self) -> None:
        t = Team(self, "aud")
        t.approved_vat()
        self.assertEqual(t.preparer.get(f"/api/orgs/{t.org}/audit").status, 403)
        self.assertEqual(t.viewer.get(f"/api/orgs/{t.org}/audit").status, 403)
        self.assertEqual(t.outsider.get(f"/api/orgs/{t.org}/audit").status, 404)
        status, body = t.reviewer.get(f"/api/orgs/{t.org}/audit")
        self.assertEqual(status, 200)
        actions = {e["action"] for e in body["items"]}
        self.assertTrue({"org.create", "return.approve"} <= actions)
        other = {e["action"] for e in t.outsider.get(f"/api/orgs/{t.other_org}/audit").body["items"]}
        self.assertNotIn("return.approve", other)
        self.assertTrue(self.services.audit.verify()["ok"])
