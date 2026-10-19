"""Publishing: contributor portal, editorial workflow by role, revisions, corrections, takedowns, complaints, news."""

from __future__ import annotations

import os
import sqlite3
from typing import Any

from ..helpers import Client, ServicesTestCase


def submission(**over: Any) -> dict[str, Any]:
    body = {
        "title": "How the development levy works",
        "summary": "A plain explanation of the single levy on assessable profits.",
        "body": "The reform replaces several sector levies with one development levy.",
        "author_name": "Ada Contributor",
        "author_credentials": "Chartered tax adviser",
        "affiliation": "Independent",
        "citations": [{"text": "Nigeria Tax Act 2025", "url": "https://taxsummaries.pwc.com/nigeria"}],
        "jurisdiction": "Nigeria",
        "rights_warranty": True,
        "conflicts": "None",
        "ai_disclosure": "No AI tools used",
        "sponsorship_declaration": "none",
    }
    body.update(over)
    return body


class PublishingCase(ServicesTestCase):
    """Shared actors, signed in once per class (sign-in codes are rate limited)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        mk = lambda email, role=None: Client(cls.services).sign_in(email, staff_role=role)  # noqa: E731
        cls.alice = mk("alice@example.com")
        cls.bob = mk("bob@example.com")
        cls.ed = mk("editor@example.com", "editor")
        cls.ed2 = mk("editor2@example.com", "editor")
        cls.lee = mk("legal@example.com", "legal_reviewer")
        cls.sam = mk("sales@example.com", "sales")
        cls.sue = mk("support@example.com", "support")
        cls.anon = Client(cls.services)

    def setUp(self) -> None:
        old = os.environ.get("TAXNG_SPONSOR_THRESHOLD")
        os.environ["TAXNG_SPONSOR_THRESHOLD"] = "0"
        self.addCleanup(lambda: os.environ.__setitem__("TAXNG_SPONSOR_THRESHOLD", old) if old is not None else os.environ.pop("TAXNG_SPONSOR_THRESHOLD", None))

    # ----------------------------------------------------------- helpers
    def act(self, who: Client, article_id: str, action: str, body: dict[str, Any] | None = None) -> Any:
        return who.post(f"/api/publishing/submissions/{article_id}/transition/{action}", body or {})

    def ok(self, reply: Any, status: int = 200) -> Any:
        self.assertEqual(reply.status, status, reply.body)
        return reply.body

    def create(self, who: Client | None = None, **over: Any) -> str:
        return self.ok((who or self.alice).post("/api/publishing/submissions", submission(**over)), 201)["id"]

    def to_review(self, article_id: str) -> None:
        self.ok(self.act(self.alice, article_id, "submit"))
        self.ok(self.act(self.ed, article_id, "screen"))
        self.ok(self.act(self.ed, article_id, "send_to_review"))

    def to_approved(self, **over: Any) -> str:
        article_id = self.create(**over)
        self.to_review(article_id)
        self.ok(self.act(self.lee, article_id, "sign_off"))
        self.ok(self.act(self.ed, article_id, "approve"))
        return article_id

    def to_published(self, **over: Any) -> dict[str, Any]:
        article_id = self.to_approved(**over)
        return self.ok(self.act(self.ed, article_id, "publish"))


class Access(PublishingCase):
    def test_anonymous_gets_401(self) -> None:
        self.assertEqual(self.anon.get("/api/publishing/submissions").status, 401)
        self.assertEqual(self.anon.post("/api/publishing/submissions", submission()).status, 401)
        self.assertEqual(self.anon.get("/api/publishing/queue").status, 401)
        self.assertEqual(self.anon.get("/api/publishing/complaints").status, 401)
        self.assertEqual(self.anon.get("/api/publishing/editions").status, 401)
        self.assertEqual(self.anon.get("/api/publishing/sponsorships").status, 401)

    def test_other_contributor_gets_404(self) -> None:
        article_id = self.create()
        self.assertEqual(self.bob.get(f"/api/publishing/submissions/{article_id}").status, 404)
        self.assertEqual(self.bob.post(f"/api/publishing/submissions/{article_id}", {"title": "Hijack"}).status, 404)
        self.assertEqual(self.act(self.bob, article_id, "submit").status, 404)
        self.assertNotIn(article_id, [i["id"] for i in self.ok(self.bob.get("/api/publishing/submissions"))["items"]])
        # Sales sees only paid content.
        self.assertEqual(self.sam.get(f"/api/publishing/submissions/{article_id}").status, 404)

    def test_contributor_cannot_move_editorial_states(self) -> None:
        article_id = self.create()
        self.ok(self.act(self.alice, article_id, "submit"))
        for action in ("screen", "approve", "publish", "request_revision", "reject"):
            self.assertEqual(self.act(self.alice, article_id, action, {"note": "x"}).status, 403, action)

    def test_sales_never_moves_editorial_states(self) -> None:
        article_id = self.create(sponsorship_declaration="paid")  # paid, so sales can see it
        self.ok(self.act(self.alice, article_id, "submit"))
        for action in ("screen", "send_to_review", "sign_off", "approve", "publish", "request_revision", "reject", "withdraw"):
            self.assertEqual(self.act(self.sam, article_id, action, {"note": "x"}).status, 403, action)
        self.assertEqual(self.sam.get("/api/publishing/queue").status, 403)
        self.assertEqual(self.sam.post(f"/api/publishing/submissions/{article_id}/classify", {"section": "africa"}).status, 403)

    def test_legal_reviewer_signs_off_but_cannot_approve_or_screen(self) -> None:
        article_id = self.create()
        self.ok(self.act(self.alice, article_id, "submit"))
        self.assertEqual(self.act(self.lee, article_id, "screen").status, 403)
        self.assertEqual(self.act(self.lee, article_id, "request_revision", {"note": "x"}).status, 403)  # not yet in review
        self.ok(self.act(self.ed, article_id, "screen"))
        self.ok(self.act(self.ed, article_id, "send_to_review"))
        self.assertEqual(self.act(self.ed, article_id, "sign_off").status, 403)
        self.ok(self.act(self.lee, article_id, "sign_off"))
        self.assertEqual(self.act(self.lee, article_id, "approve").status, 403)
        queue = self.ok(self.lee.get("/api/publishing/queue"))["items"]
        self.assertTrue(all(i["state"] == "fact_legal_review" for i in queue))

    def test_support_has_no_editorial_queue(self) -> None:
        self.assertEqual(self.sue.get("/api/publishing/queue").status, 403)
        self.assertEqual(self.alice.get("/api/publishing/dashboard").status, 403)
        self.ok(self.sue.get("/api/publishing/dashboard"))


class Workflow(PublishingCase):
    def test_every_transition_on_the_happy_path(self) -> None:
        article_id = self.create()
        states = [self.ok(self.act(self.alice, article_id, "submit"))["state"]]
        states.append(self.ok(self.act(self.ed, article_id, "screen"))["state"])
        states.append(self.ok(self.act(self.ed, article_id, "send_to_review"))["state"])
        signed = self.ok(self.act(self.lee, article_id, "sign_off"))
        self.assertTrue(signed["legal_signoff_by"])
        states.append(self.ok(self.act(self.ed, article_id, "approve"))["state"])
        states.append(self.ok(self.act(self.ed, article_id, "schedule", {"scheduled_for": "2099-01-01T08:00"}))["state"])
        states.append(self.ok(self.act(self.ed, article_id, "publish"))["state"])
        self.assertEqual(states, ["submitted", "screening", "fact_legal_review", "approved", "scheduled", "published"])
        detail = self.ok(self.ed.get(f"/api/publishing/submissions/{article_id}"))
        self.assertEqual([h["action"] for h in detail["history"]], ["create", "submit", "screen", "send_to_review", "sign_off", "approve", "schedule", "publish"])
        actions = {e["action"] for e in self.services.audit.events(entity_id=article_id)}
        self.assertIn("publishing.article.approve", actions)
        self.assertTrue(self.services.audit.verify()["ok"])

    def test_wrong_state_is_409(self) -> None:
        article_id = self.create()
        self.assertEqual(self.act(self.ed, article_id, "approve").status, 409)
        self.assertEqual(self.act(self.ed, article_id, "publish").status, 409)
        self.assertEqual(self.act(self.ed, article_id, "nonsense").status, 404)

    def test_submission_requires_rights_warranty_and_fields(self) -> None:
        article_id = self.create(rights_warranty=False)
        status, body = self.act(self.alice, article_id, "submit")
        self.assertEqual(status, 422)
        self.assertIn("rights_warranty", body["fields"])
        article_id = self.create(citations=[])
        self.assertIn("citations", self.act(self.alice, article_id, "submit").body["fields"])
        article_id = self.create(ai_disclosure="")
        self.assertIn("ai_disclosure", self.act(self.alice, article_id, "submit").body["fields"])

    def test_revision_request_feedback_and_resubmission(self) -> None:
        article_id = self.create()
        self.to_review(article_id)
        self.ok(self.act(self.lee, article_id, "sign_off"))
        self.assertEqual(self.act(self.ed, article_id, "request_revision").status, 422)  # feedback required
        revised = self.ok(self.act(self.lee, article_id, "request_revision", {"note": "Cite the section number."}))
        self.assertEqual(revised["state"], "revision_requested")
        mine = self.ok(self.alice.get("/api/publishing/submissions"))["items"]
        self.assertEqual(next(i for i in mine if i["id"] == article_id)["feedback"], "Cite the section number.")
        edited = self.ok(self.alice.post(f"/api/publishing/submissions/{article_id}", {"body": "Now with the section cited."}))
        self.assertEqual(edited["version"], 2)
        self.assertIsNone(edited["legal_signoff_by"])  # edits void the earlier sign-off
        self.assertEqual(self.ok(self.act(self.alice, article_id, "submit"))["state"], "submitted")

    def test_contributor_cannot_edit_after_submission(self) -> None:
        article_id = self.create()
        self.ok(self.act(self.alice, article_id, "submit"))
        self.assertEqual(self.alice.post(f"/api/publishing/submissions/{article_id}", {"title": "Changed"}).status, 409)
        self.assertEqual(self.ed.post(f"/api/publishing/submissions/{article_id}", {"title": "Changed"}).status, 403)

    def test_approval_needs_legal_signoff_and_not_own_article(self) -> None:
        article_id = self.create()
        self.to_review(article_id)
        self.assertEqual(self.act(self.ed, article_id, "approve").status, 409)
        own = self.create(self.ed, article_type="commentary")
        self.ok(self.act(self.ed, own, "submit"))
        self.ok(self.act(self.ed2, own, "screen"))
        self.ok(self.act(self.ed2, own, "send_to_review"))
        self.ok(self.act(self.lee, own, "sign_off"))
        self.assertEqual(self.act(self.ed, own, "approve").status, 409)
        self.ok(self.act(self.ed2, own, "approve"))

    def test_contributor_cannot_choose_editorial_type(self) -> None:
        self.assertEqual(self.alice.post("/api/publishing/submissions", submission(article_type="news")).status, 422)
        article_id = self.create(self.ed, article_type="news", section="africa")
        self.assertEqual(self.ok(self.ed.get(f"/api/publishing/submissions/{article_id}"))["badge"], "News")

    def test_reject(self) -> None:
        article_id = self.create()
        self.ok(self.act(self.alice, article_id, "submit"))
        self.assertEqual(self.ok(self.act(self.ed, article_id, "reject", {"note": "Out of scope"}))["state"], "rejected")
        self.assertEqual(self.anon.get(f"/api/publishing/articles/{self.ok(self.ed.get(f'/api/publishing/submissions/{article_id}'))['slug']}").status, 404)

    def test_scheduled_article_publishes_when_due(self) -> None:
        article_id = self.to_approved()
        self.ok(self.act(self.ed, article_id, "schedule", {"scheduled_for": "2099-01-01T08:00"}))
        self.assertEqual(self.ed.post("/api/publishing/run-scheduled").body["articles"]["published"], [])
        self.services.db.update("pub_articles", {"scheduled_for": "2000-01-01T00:00:00+00:00"}, "id = ?", (article_id,))
        self.assertEqual(self.sam.post("/api/publishing/run-scheduled").status, 403)
        self.assertIn(article_id, self.ok(self.ed.post("/api/publishing/run-scheduled"))["articles"]["published"])
        self.assertEqual(self.ok(self.ed.get(f"/api/publishing/submissions/{article_id}"))["state"], "published")

    def test_correction_is_public_and_versioned(self) -> None:
        published = self.to_published()
        article_id, slug = published["id"], published["slug"]
        self.assertEqual(self.act(self.ed, article_id, "correct", {}).status, 422)
        corrected = self.ok(self.act(self.ed, article_id, "correct", {"note": "We corrected the commencement date.", "body": "Corrected text."}))
        self.assertEqual((corrected["state"], corrected["version"]), ("corrected", 2))
        self.ok(self.act(self.ed, article_id, "correct", {"note": "Fixed a typo in the title.", "title": "How the development levy works now"}))
        page = self.ok(self.anon.get(f"/api/publishing/articles/{slug}"))
        self.assertEqual([c["note"] for c in page["corrections"]], ["We corrected the commencement date.", "Fixed a typo in the title."])
        self.assertEqual(page["body"], "Corrected text.")
        self.assertTrue(page["corrected"])
        revisions = self.ok(self.ed.get(f"/api/publishing/submissions/{article_id}"))["revisions"]
        self.assertEqual([r["version"] for r in revisions], [1, 2, 3])

    def test_withdrawal_leaves_tombstone(self) -> None:
        published = self.to_published()
        self.assertEqual(self.act(self.ed, published["id"], "withdraw").status, 422)
        self.ok(self.act(self.ed, published["id"], "withdraw", {"note": "Withdrawn after a legal complaint."}))
        page = self.ok(self.anon.get(f"/api/publishing/articles/{published['slug']}"))
        self.assertTrue(page["tombstone"])
        self.assertEqual(page["withdrawn_reason"], "Withdrawn after a legal complaint.")
        self.assertNotIn("body", page)
        listed = self.ok(self.anon.get("/api/publishing/articles"))["items"]
        self.assertNotIn(published["id"], [a["id"] for a in listed])

    def test_unpublished_is_not_public(self) -> None:
        article_id = self.to_approved()
        slug = self.ok(self.ed.get(f"/api/publishing/submissions/{article_id}"))["slug"]
        self.assertEqual(self.anon.get(f"/api/publishing/articles/{slug}").status, 404)


class AppendOnly(PublishingCase):
    def test_revisions_history_and_corrections_are_immutable(self) -> None:
        published = self.to_published()
        self.ok(self.act(self.ed, published["id"], "correct", {"note": "A correction."}))
        db = self.services.db
        for table in ("pub_revisions", "pub_history", "pub_corrections"):
            self.assertTrue(db.scalar(f"SELECT COUNT(*) FROM {table}"))
            with self.assertRaises(sqlite3.DatabaseError, msg=table):
                db.execute(f"UPDATE {table} SET created_at = 'x'")
            with self.assertRaises(sqlite3.DatabaseError, msg=table):
                db.execute(f"DELETE FROM {table}")


class Complaints(PublishingCase):
    def test_intake_tracking_and_staff_handling(self) -> None:
        published = self.to_published()
        self.assertEqual(self.anon.post("/api/publishing/complaints", {"kind": "accuracy", "details": "short"}).status, 422)
        filed = self.ok(self.anon.post("/api/publishing/complaints", {"kind": "accuracy", "details": "The date in paragraph two is wrong.", "article_slug": published["slug"], "contact_email": "reader@example.com"}), 201)
        path = f"/api/publishing/complaints/{filed['id']}/status"
        self.assertEqual(self.anon.get(path, {"token": "0" * 32}).status, 404)
        self.assertEqual(self.ok(self.anon.get(path, {"token": filed["tracking_token"]}))["status"], "received")
        self.assertEqual(self.alice.get("/api/publishing/complaints").status, 403)
        self.assertEqual(self.sam.get("/api/publishing/complaints").status, 403)
        self.assertIn(filed["id"], [c["id"] for c in self.ok(self.sue.get("/api/publishing/complaints"))["items"]])
        self.assertEqual(self.alice.post(f"/api/publishing/complaints/{filed['id']}", {"status": "investigating"}).status, 403)
        self.ok(self.ed.post(f"/api/publishing/complaints/{filed['id']}", {"status": "investigating"}))
        self.assertEqual(self.ed.post(f"/api/publishing/complaints/{filed['id']}", {"status": "resolved"}).status, 422)
        self.ok(self.lee.post(f"/api/publishing/complaints/{filed['id']}", {"status": "resolved", "resolution": "Corrected."}))
        self.assertEqual(self.ok(self.anon.get(path, {"token": filed["tracking_token"]}))["status"], "resolved")
        self.assertEqual(self.ed.post(f"/api/publishing/complaints/{filed['id']}", {"status": "investigating"}).status, 409)
        audit = [e for e in self.services.audit.events(entity_id=filed["id"])]
        self.assertNotIn("reader@example.com", str(audit))


class NewsSections(PublishingCase):
    def test_africa_and_global_sections_are_sample_and_sourced(self) -> None:
        for section in ("africa", "global"):
            items = self.ok(self.anon.get("/api/publishing/news", {"section": section}))["items"]
            self.assertTrue(items, section)
            for item in items:
                self.assertTrue(item["sample"])
                self.assertTrue(item["source_url"].startswith("https://"))
                self.assertNotRegex(item["headline"] + item["standfirst"], r"₦|\d\s*%|per\s*cent")
        self.assertEqual(self.anon.get("/api/publishing/news", {"section": "mars"}).status, 422)

    def test_published_news_article_joins_its_section(self) -> None:
        article_id = self.create(self.ed, article_type="news", section="global")
        self.ok(self.act(self.ed, article_id, "submit"))
        self.ok(self.act(self.ed2, article_id, "screen"))
        self.ok(self.act(self.ed2, article_id, "send_to_review"))
        self.ok(self.act(self.lee, article_id, "sign_off"))
        self.ok(self.act(self.ed2, article_id, "approve"))
        self.ok(self.act(self.ed2, article_id, "publish"))
        items = self.ok(self.anon.get("/api/publishing/news", {"section": "global"}))["items"]
        self.assertIn(article_id, [i["id"] for i in items])
        self.assertNotIn(article_id, [i["id"] for i in self.ok(self.anon.get("/api/publishing/news", {"section": "africa"}))["items"]])
