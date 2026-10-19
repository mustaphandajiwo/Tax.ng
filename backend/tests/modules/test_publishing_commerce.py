"""Publishing hard rules: disclosure and ARCON, approval independent of payment, label propagation,
audience threshold, reject and refund, untargeted ads, newsletter editions."""

from __future__ import annotations

import ast
import inspect
import os
import re
import textwrap
from typing import Any

from taxng.modules.publishing import commerce, service

from .test_publishing import PublishingCase


class FakeBilling:
    def __init__(self) -> None:
        self.handlers: dict[str, Any] = {}
        self.checkouts: list[dict[str, Any]] = []

    def register_payment_handler(self, purpose: str, fn: Any) -> None:
        self.handlers[purpose] = fn

    def create_checkout(self, **kw: Any) -> dict[str, Any]:
        self.checkouts.append(kw)
        return {"checkout_id": f"chk_{len(self.checkouts)}", "url": "/pay/sandbox", "mode": "sandbox"}


class CommerceCase(PublishingCase):
    def setUp(self) -> None:
        super().setUp()
        self.real_billing = self.services.modules.get("billing")
        self.billing = FakeBilling()
        self.services.modules["billing"] = self.billing
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        if self.real_billing is None:
            self.services.modules.pop("billing", None)
        else:
            self.services.modules["billing"] = self.real_billing

    def order(self, **over: Any) -> dict[str, Any]:
        body = {"sponsor_name": "Acme Bank Plc", "funding_relationship": "Paid sponsorship; sponsor reviewed facts only", "placement": "sponsored_article", "amount_kobo": 100}
        body.update(over)
        return self.ok(self.sam.post("/api/publishing/sponsorships", body), 201)

    def pay(self, order_id: str, purpose: str = "sponsorship") -> None:
        self.ok(self.sam.post(f"/api/publishing/sponsorships/{order_id}/checkout") if purpose == "sponsorship" else self.sam.post(f"/api/ads/campaigns/{order_id}/checkout"))
        self.billing.handlers[purpose](self.services, {"purpose": purpose, "reference_id": order_id, "status": "paid"})

    def sponsored_published(self, **order_over: Any) -> dict[str, Any]:
        order = self.order(**order_over)
        article_id = self.to_approved()
        self.ok(self.sam.post(f"/api/publishing/sponsorships/{order['id']}/attach", {"article_id": article_id}))
        return self.ok(self.act(self.ed, article_id, "publish"))


class DisclosureAndArcon(CommerceCase):
    def test_paid_content_needs_disclosure_then_arcon(self) -> None:
        article_id = self.to_approved(sponsorship_declaration="paid")
        status, body = self.act(self.ed, article_id, "publish")
        self.assertEqual(status, 409)
        self.assertIn("disclosure", body["message"])
        detail = self.ok(self.ed.get(f"/api/publishing/submissions/{article_id}"))
        self.assertTrue(detail["publish_blockers"])
        self.assertEqual(self.alice.post(f"/api/publishing/submissions/{article_id}/disclosure", {"sponsor_name": "X", "funding_relationship": "Y"}).status, 403)
        self.assertEqual(self.ed.post(f"/api/publishing/submissions/{article_id}/disclosure", {"sponsor_name": "Acme"}).status, 422)
        self.ok(self.ed.post(f"/api/publishing/submissions/{article_id}/disclosure", {"sponsor_name": "Acme", "funding_relationship": "Paid", "arcon_required": True}))
        status, body = self.act(self.ed, article_id, "publish")
        self.assertEqual(status, 409)
        self.assertIn("ARCON", body["message"])
        self.ok(self.sam.post(f"/api/publishing/submissions/{article_id}/disclosure", {"sponsor_name": "Acme", "funding_relationship": "Paid", "arcon_required": True, "arcon_reference": "ARCON/2026/0001"}))
        self.assertEqual(self.ok(self.act(self.ed, article_id, "publish"))["state"], "published")

    def test_attached_order_with_arcon_required_blocks_until_reference(self) -> None:
        order = self.order(arcon_required=True)
        article_id = self.to_approved()
        self.ok(self.sam.post(f"/api/publishing/sponsorships/{order['id']}/attach", {"article_id": article_id}))
        self.assertEqual(self.act(self.ed, article_id, "publish").status, 409)
        self.ok(self.sam.post(f"/api/publishing/sponsorships/{order['id']}", {"arcon_reference": "ARCON/REF/7"}))
        self.ok(self.act(self.ed, article_id, "publish"))

    def test_scheduler_holds_paid_content_without_disclosure(self) -> None:
        article_id = self.to_approved(sponsorship_declaration="in_kind")
        self.ok(self.act(self.ed, article_id, "schedule", {"scheduled_for": "2099-01-01T00:00"}))
        self.services.db.update("pub_articles", {"scheduled_for": "2000-01-01T00:00:00+00:00"}, "id = ?", (article_id,))
        result = self.ok(self.ed.post("/api/publishing/run-scheduled"))["articles"]
        self.assertEqual(result["held"][0]["id"], article_id)

    def test_paid_content_cannot_be_reclassified_unsponsored(self) -> None:
        article_id = self.create(sponsorship_declaration="paid")
        self.ok(self.act(self.alice, article_id, "submit"))
        self.assertEqual(self.ed.post(f"/api/publishing/submissions/{article_id}/classify", {"article_type": "commentary"}).status, 409)


class ApprovalIndependentOfPayment(CommerceCase):
    def test_approval_code_never_reads_payment(self) -> None:
        for fn in (service._guard_approve, service.transition, service._check_role, service.publish_blockers, service._guard_publish):
            tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
            node = tree.body[0]
            if ast.get_docstring(node):  # type: ignore[arg-type]
                node.body = node.body[1:]  # type: ignore[attr-defined]
            self.assertNotRegex(ast.unparse(tree), re.compile("payment|sponsorships|checkout", re.I), fn.__name__)

    def test_unpaid_order_does_not_block_approval_and_payment_never_publishes(self) -> None:
        order = self.order()
        article_id = self.create()
        self.ok(self.sam.post(f"/api/publishing/sponsorships/{order['id']}/attach", {"article_id": article_id}))
        self.to_review(article_id)
        self.ok(self.act(self.lee, article_id, "sign_off"))
        self.assertEqual(self.ok(self.act(self.ed, article_id, "approve"))["state"], "approved")
        self.pay(order["id"])
        orders = self.ok(self.sam.get("/api/publishing/sponsorships"))["items"]
        self.assertEqual(next(o for o in orders if o["id"] == order["id"])["payment_status"], "paid")
        self.assertEqual(self.ok(self.ed.get(f"/api/publishing/submissions/{article_id}"))["state"], "approved")

    def test_payment_before_review_changes_nothing_and_sales_still_cannot_approve(self) -> None:
        order = self.order()
        self.pay(order["id"])
        article_id = self.create()
        self.ok(self.sam.post(f"/api/publishing/sponsorships/{order['id']}/attach", {"article_id": article_id}))
        self.to_review(article_id)
        self.assertEqual(self.ok(self.ed.get(f"/api/publishing/submissions/{article_id}"))["state"], "fact_legal_review")
        self.assertEqual(self.act(self.sam, article_id, "approve").status, 403)
        self.assertEqual(self.act(self.ed, article_id, "approve").status, 409)  # still needs legal sign-off

    def test_checkout_uses_billing_contract(self) -> None:
        order = self.order()
        reply = self.ok(self.sam.post(f"/api/publishing/sponsorships/{order['id']}/checkout"))
        self.assertEqual((reply["billing_available"], reply["mode"]), (True, "sandbox"))
        call = self.billing.checkouts[-1]
        self.assertEqual((call["purpose"], call["reference_id"], call["amount_kobo"]), ("sponsorship", order["id"], 100))
        self.assertEqual(self.ed.post(f"/api/publishing/sponsorships/{order['id']}/checkout").status, 403)

    def test_degrades_when_billing_is_absent(self) -> None:
        self.services.modules.pop("billing")
        order = self.order()
        reply = self.ok(self.sam.post(f"/api/publishing/sponsorships/{order['id']}/checkout"))
        self.assertFalse(reply["billing_available"])


class LabelPropagation(CommerceCase):
    def test_label_on_every_surface(self) -> None:
        published = self.sponsored_published()
        slug, title = published["slug"], published["title"]
        card = next(a for a in self.ok(self.anon.get("/api/publishing/articles"))["items"] if a["slug"] == slug)
        self.assertEqual((card["sponsored"], card["label"], card["sponsor"]["name"]), (True, "Sponsored", "Acme Bank Plc"))
        page = self.ok(self.anon.get(f"/api/publishing/articles/{slug}"))
        self.assertEqual(page["header_label"], "Sponsored")
        self.assertEqual(page["meta"]["json_ld"]["sponsor"], {"@type": "Organization", "name": "Acme Bank Plc"})
        og = page["meta"]["open_graph"]
        self.assertTrue(og["og:title"].startswith("Sponsored: "))
        self.assertEqual(og["article:tag"], "Sponsored")
        hits = self.ok(self.anon.get("/api/publishing/search", {"q": "development levy"}))["items"]
        hit = next(h for h in hits if h["id"] == published["id"])
        self.assertEqual((hit["sponsored"], hit["label"]), (True, "Sponsored"))
        rss = self.anon.get("/api/publishing/rss.xml")
        self.assertEqual(rss.status, 200)
        self.assertTrue(rss.content_type.startswith("application/rss+xml"))
        xml = rss.raw.decode()
        self.assertIn(f"<title>Sponsored: {title}</title>", xml)
        self.assertIn("<category>Sponsored</category>", xml)
        items = self.services.modules["publishing"].newsletter_items()
        self.assertEqual(next(i for i in items if i["id"] == published["id"])["label"], "Sponsored")
        edition = self.ok(self.ed.post("/api/publishing/editions", {"newsletter": "nigerian_tax_brief", "title": "Week one", "items": [{"kind": "article", "id": published["id"]}]}), 201)
        preview = self.ok(self.ed.get(f"/api/publishing/editions/{edition['id']}/preview"))
        self.assertEqual(preview["items"][0]["label"], "Sponsored")
        self.assertIn(f"[Sponsored] {title}", preview["text"])

    def test_paid_partnership_label_and_unsponsored_has_none(self) -> None:
        published = self.sponsored_published(label="Paid Partnership")
        page = self.ok(self.anon.get(f"/api/publishing/articles/{published['slug']}"))
        self.assertEqual(page["header_label"], "Paid Partnership")
        self.assertTrue(page["meta"]["open_graph"]["og:title"].startswith("Paid Partnership: "))
        plain = self.to_published()
        page = self.ok(self.anon.get(f"/api/publishing/articles/{plain['slug']}"))
        self.assertIsNone(page["header_label"])
        self.assertNotIn("sponsor", page["meta"]["json_ld"])
        self.assertNotIn(f"Sponsored: {plain['title']}", self.anon.get("/api/publishing/rss.xml").raw.decode().replace(f"Sponsored: {published['title']}", ""))


class AudienceThreshold(CommerceCase):
    def test_gate_closed_below_threshold(self) -> None:
        os.environ["TAXNG_SPONSOR_THRESHOLD"] = "1000000"
        policy = self.ok(self.anon.get("/api/publishing/policy"))
        self.assertEqual((policy["audience"]["open"], policy["audience"]["threshold"]), (False, 1000000))
        self.assertTrue(all("TBC" in r["price"] for r in policy["rate_card"]))
        self.assertEqual(self.sam.post("/api/publishing/sponsorships", {"sponsor_name": "A", "funding_relationship": "B", "amount_kobo": 1}).status, 409)
        self.assertEqual(self.sam.post("/api/ads/campaigns", {"advertiser": "A", "starts_on": "2026-01-01", "ends_on": "2099-01-01", "slots": ["home_sidebar"]}).status, 409)
        article_id = self.to_approved(sponsorship_declaration="paid")
        self.ok(self.ed.post(f"/api/publishing/submissions/{article_id}/disclosure", {"sponsor_name": "Acme", "funding_relationship": "Paid"}))
        status, body = self.act(self.ed, article_id, "publish")
        self.assertEqual(status, 409)
        self.assertIn("audience threshold", body["message"])
        self.assertEqual(self.ok(self.act(self.ed, self.to_approved(), "publish"))["state"], "published")  # editorial content unaffected
        self.assertEqual(self.ok(self.anon.get("/api/ads/slot/home_sidebar", {"page": "/"}))["reason"], "below_audience_threshold")

    def test_default_threshold_comes_from_policy(self) -> None:
        os.environ.pop("TAXNG_SPONSOR_THRESHOLD")
        self.assertEqual(commerce.threshold(self.services), service.policy(self.services)["audience_threshold"])
        os.environ["TAXNG_SPONSOR_THRESHOLD"] = "2"
        self.assertFalse(commerce.audience_status(self.services)["open"])
        self.services.store.subscribe("s1@example.com", consent=True, consent_text="x")
        self.services.store.subscribe("s2@example.com", consent=True, consent_text="x")
        self.assertTrue(commerce.audience_status(self.services)["open"])


class RejectAndRefund(CommerceCase):
    def test_reject_paid_order_marks_refund_and_removes_disclosure(self) -> None:
        order = self.order()
        article_id = self.to_approved()
        self.ok(self.sam.post(f"/api/publishing/sponsorships/{order['id']}/attach", {"article_id": article_id}))
        self.pay(order["id"])
        self.assertEqual(self.sam.post(f"/api/publishing/sponsorships/{order['id']}/reject", {}).status, 422)
        rejected = self.ok(self.ed.post(f"/api/publishing/sponsorships/{order['id']}/reject", {"reason": "Misleading claims"}))
        self.assertEqual((rejected["status"], rejected["payment_status"]), ("rejected", "refund_due"))
        detail = self.ok(self.ed.get(f"/api/publishing/submissions/{article_id}"))
        self.assertIsNone(detail["disclosure"])
        self.assertIsNone(detail["sponsorship_id"])
        self.ok(self.sam.post(f"/api/publishing/sponsorships/{order['id']}/refunded"))
        self.assertEqual(self.sam.post(f"/api/publishing/sponsorships/{order['id']}/refunded").status, 409)
        # A late webhook on a rejected order is refunded, not banked.
        late = self.order()
        self.ok(self.sam.post(f"/api/publishing/sponsorships/{late['id']}/reject", {"reason": "Declined"}))
        self.billing.handlers["sponsorship"](self.services, {"purpose": "sponsorship", "reference_id": late["id"]})
        self.assertEqual(self.services.db.scalar("SELECT payment_status FROM pub_sponsorships WHERE id = ?", (late["id"],)), "refund_due")

    def test_cannot_reject_while_published(self) -> None:
        published = self.sponsored_published()
        order_id = self.services.db.scalar("SELECT sponsorship_id FROM pub_articles WHERE id = ?", (published["id"],))
        self.assertEqual(self.sam.post(f"/api/publishing/sponsorships/{order_id}/reject", {"reason": "x"}).status, 409)

    def test_only_sales_creates_orders(self) -> None:
        body = {"sponsor_name": "A", "funding_relationship": "B", "amount_kobo": 1}
        self.assertEqual(self.ed.post("/api/publishing/sponsorships", body).status, 403)
        self.assertEqual(self.alice.post("/api/publishing/sponsorships", body).status, 403)
        self.assertEqual(self.anon.post("/api/publishing/sponsorships", body).status, 401)
        self.assertEqual(self.sam.post("/api/publishing/sponsorships", {**body, "amount_kobo": 1.5}).status, 422)


class Ads(CommerceCase):
    def setUp(self) -> None:
        super().setUp()
        self.services.db.execute("UPDATE pub_ad_campaigns SET status = 'ended'")  # isolate rotation per test

    def campaign(self, **over: Any) -> dict[str, Any]:
        body = {"advertiser": "Ledger Software Ltd", "starts_on": "2026-01-01", "ends_on": "2099-12-31", "slots": ["home_sidebar", "article_inline"]}
        body.update(over)
        return self.ok(self.sam.post("/api/ads/campaigns", body), 201)

    def live_creative(self) -> dict[str, Any]:
        campaign = self.campaign()
        creative = self.ok(self.sam.post(f"/api/ads/campaigns/{campaign['id']}/creatives", {"headline": "Bookkeeping for SMEs", "body": "Try it free.", "link_url": "https://example.com/ledger"}), 201)
        self.ok(self.sam.post(f"/api/ads/campaigns/{campaign['id']}/status", {"status": "active"}))
        return {"campaign": campaign, "creative": creative}

    def test_no_targeting_inputs_accepted(self) -> None:
        for key in ("targeting", "audience", "health_check_findings", "income_band", "user_ids"):
            status, body = self.sam.post("/api/ads/campaigns", {"advertiser": "A", "starts_on": "2026-01-01", "ends_on": "2099-01-01", "slots": ["home_sidebar"], key: "x"})
            self.assertEqual(status, 422, key)
            self.assertIn("never targeted", body["fields"][key])
        for key in ("user_id", "compliance_score", "segment"):
            self.assertEqual(self.anon.get("/api/ads/slot/home_sidebar", {"page": "/", key: "1"}).status, 422, key)
        campaign = self.campaign()
        self.assertEqual(self.sam.post(f"/api/ads/campaigns/{campaign['id']}/creatives", {"headline": "H", "link_url": "https://e.com", "audience": "rich"}).status, 422)

    def test_app_and_sensitive_placements_never_serve(self) -> None:
        self.assertEqual(self.sam.post("/api/ads/campaigns", {"advertiser": "A", "starts_on": "2026-01-01", "ends_on": "2099-01-01", "slots": ["app_dashboard"]}).status, 422)
        self.live_creative()
        self.ok(self.ed.post(f"/api/ads/creatives/{self.services.db.scalar('SELECT id FROM pub_ad_creatives ORDER BY created_at DESC LIMIT 1')}/review", {"decision": "approved"}))
        self.assertEqual(self.anon.get("/api/ads/slot/app_dashboard").status, 404)
        for page in ("/app", "/app/compliance", "/health-check", "/calculators/pit", "/ask", "/file-pay"):
            self.assertIsNone(self.ok(self.anon.get("/api/ads/slot/article_inline", {"page": page}))["ad"], page)
        self.assertEqual(self.ok(self.anon.get("/api/ads/slot/home_sidebar", {"page": "/insights"}))["reason"], "slot_not_on_page")

    def test_review_then_serve_count_and_report(self) -> None:
        live = self.live_creative()
        creative_id = live["creative"]["id"]
        self.assertIsNone(self.ok(self.anon.get("/api/ads/slot/home_sidebar", {"page": "/"}))["ad"])  # pending review
        self.assertEqual(self.sam.post(f"/api/ads/creatives/{creative_id}/review", {"decision": "approved"}).status, 403)
        self.assertEqual(self.sue.post(f"/api/ads/creatives/{creative_id}/review", {"decision": "rejected"}).status, 422)
        self.ok(self.sue.post(f"/api/ads/creatives/{creative_id}/review", {"decision": "approved"}))
        anon_ad = self.ok(self.anon.get("/api/ads/slot/home_sidebar", {"page": "/"}))["ad"]
        self.assertEqual((anon_ad["creative_id"], anon_ad["label"]), (creative_id, "Advertisement"))
        signed_in_ad = self.ok(self.alice.get("/api/ads/slot/home_sidebar", {"page": "/"}))["ad"]
        self.assertEqual(signed_in_ad, anon_ad)  # identical for every visitor: no targeting
        self.assertEqual(self.anon.post(f"/api/ads/impression/{creative_id}").status, 202)
        self.assertEqual(self.ok(self.anon.post(f"/api/ads/click/{creative_id}"))["url"], "https://example.com/ledger")
        report = self.ok(self.sam.get(f"/api/ads/campaigns/{live['campaign']['id']}/report"))
        self.assertEqual(report["totals"], {"impressions": 1, "clicks": 1})
        self.assertEqual(self.ed.get(f"/api/ads/campaigns/{live['campaign']['id']}/report").status, 403)
        columns = {r["name"] for r in self.services.db.query("PRAGMA table_info(pub_ad_stats)")}
        self.assertEqual(columns, {"creative_id", "day", "impressions", "clicks"})
        self.assertIn(live["campaign"]["id"], [c["id"] for c in self.ok(self.sam.get("/api/publishing/reports"))["campaigns"]])

    def test_out_of_date_and_paused_campaigns_do_not_serve(self) -> None:
        old = self.campaign(starts_on="2020-01-01", ends_on="2020-12-31", slots=["news_sidebar"])
        creative = self.ok(self.sam.post(f"/api/ads/campaigns/{old['id']}/creatives", {"headline": "Old", "link_url": "https://e.com"}), 201)
        self.ok(self.ed.post(f"/api/ads/creatives/{creative['id']}/review", {"decision": "approved"}))
        self.ok(self.sam.post(f"/api/ads/campaigns/{old['id']}/status", {"status": "active"}))
        self.assertIsNone(self.ok(self.anon.get("/api/ads/slot/news_sidebar", {"page": "/news"}))["ad"])
        self.assertEqual(self.anon.post(f"/api/ads/impression/crv_missing").status, 404)
        self.assertEqual(self.sam.post(f"/api/ads/campaigns/{old['id']}/creatives", {"headline": "Bad", "link_url": "http://e.com"}).status, 422)


class Editions(CommerceCase):
    def test_edition_workflow_send_and_archive(self) -> None:
        self.services.store.subscribe("reader1@example.com", consent=True, consent_text="x", topics=["global_tax_watch"])
        self.services.store.subscribe("reader2@example.com", consent=True, consent_text="x", topics=["nigerian_tax_brief"])
        sponsor = self.order(placement="newsletter_sponsor", arcon_required=True)
        body = {"newsletter": "global_tax_watch", "title": "Global week", "items": [{"kind": "news", "id": "oecd-global-minimum-tax"}], "sponsorship_id": sponsor["id"]}
        self.assertEqual(self.lee.post("/api/publishing/editions", body).status, 403)
        self.assertEqual(self.sam.post("/api/publishing/editions", body).status, 403)
        self.assertEqual(self.ed.post("/api/publishing/editions", {**body, "items": [{"kind": "news", "id": "nope"}]}).status, 422)
        edition = self.ok(self.ed.post("/api/publishing/editions", body), 201)
        eid = edition["id"]
        step = lambda who, action, b=None: who.post(f"/api/publishing/editions/{eid}/transition/{action}", b or {})  # noqa: E731
        self.assertEqual(self.anon.get(f"/api/publishing/newsletter/archive/{eid}").status, 404)
        self.assertEqual(step(self.ed, "approve").status, 409)
        self.assertEqual(self.ok(step(self.ed, "submit"))["state"], "fact_check")
        self.assertEqual(self.ok(step(self.lee, "fact_checked"))["state"], "fact_checked")
        self.assertEqual(step(self.lee, "approve").status, 403)
        self.assertEqual(self.ok(step(self.ed, "approve"))["state"], "approved")
        preview = self.ok(self.ed.get(f"/api/publishing/editions/{eid}/preview"))
        self.assertEqual(preview["sponsor"]["label"], "Sponsored")
        self.assertIn("Unsubscribe:", preview["text"])
        self.assertEqual(self.ok(step(self.ed, "schedule", {"scheduled_for": "2099-01-01T07:00"}))["state"], "scheduled")
        status, reply = step(self.ed, "send")
        self.assertEqual(status, 409)
        self.assertIn("ARCON", reply["message"])
        self.ok(self.sam.post(f"/api/publishing/sponsorships/{sponsor['id']}", {"arcon_reference": "ARCON/NL/1"}))
        sent = self.ok(step(self.ed, "send"))
        self.assertEqual((sent["state"], sent["sent_count"]), ("sent", 1))
        mail = self.services.notifier.recent("reader1@example.com", limit=1)[0]
        self.assertIn("[Sponsored] This edition is supported by Acme Bank Plc", mail["body"])
        self.assertIn("Unsubscribe: https://tax.ng/#/newsletter/unsubscribe/reader1%40example.com/", mail["body"])
        self.assertEqual(mail["mode"], "sandbox")
        self.assertFalse(self.services.notifier.recent("reader2@example.com"))
        archive = self.ok(self.anon.get("/api/publishing/newsletter/archive"))["items"]
        self.assertIn(eid, [e["id"] for e in archive])
        public = self.ok(self.anon.get(f"/api/publishing/newsletter/archive/{eid}"))
        self.assertIsNone(public["unsubscribe_url"])
        self.assertEqual(public["sponsor"]["label"], "Sponsored")
        self.assertEqual(self.ok(step(self.ed, "archive"))["state"], "archived")
        self.assertEqual(self.ok(self.anon.get(f"/api/publishing/newsletter/archive/{eid}"))["id"], eid)

    def test_revise_returns_to_draft_and_draft_edits(self) -> None:
        edition = self.ok(self.ed.post("/api/publishing/editions", {"newsletter": "nigerian_tax_brief", "title": "Brief", "items": [{"kind": "news", "id": "reform-acts-commence"}]}), 201)
        eid = edition["id"]
        self.ok(self.ed.post(f"/api/publishing/editions/{eid}/transition/submit"))
        self.assertEqual(self.ed.post(f"/api/publishing/editions/{eid}", {"title": "Changed"}).status, 409)
        self.assertEqual(self.ok(self.lee.post(f"/api/publishing/editions/{eid}/transition/revise"))["state"], "draft")
        self.assertEqual(self.ok(self.ed.post(f"/api/publishing/editions/{eid}", {"title": "Changed"}))["title"], "Changed")
        self.assertEqual(self.alice.get("/api/publishing/editions").status, 403)


class RealBilling(PublishingCase):
    def test_sandbox_payment_marks_order_paid_and_never_publishes(self) -> None:
        billing = self.services.modules.get("billing")
        if billing is None or not hasattr(billing, "simulate"):
            self.skipTest("billing module not present")
        order = self.ok(self.sam.post("/api/publishing/sponsorships", {"sponsor_name": "Acme", "funding_relationship": "Paid", "amount_kobo": 5000}), 201)
        article_id = self.to_approved()
        self.ok(self.sam.post(f"/api/publishing/sponsorships/{order['id']}/attach", {"article_id": article_id}))
        checkout = self.ok(self.sam.post(f"/api/publishing/sponsorships/{order['id']}/checkout"))
        self.assertEqual(checkout["mode"], "sandbox")
        billing.simulate(checkout["checkout"]["checkout_id"], self.sam.user_id, "paid")
        self.assertEqual(self.services.db.scalar("SELECT payment_status FROM pub_sponsorships WHERE id = ?", (order["id"],)), "paid")
        self.assertEqual(self.ok(self.ed.get(f"/api/publishing/submissions/{article_id}"))["state"], "approved")
