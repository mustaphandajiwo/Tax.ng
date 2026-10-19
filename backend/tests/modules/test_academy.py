"""Academy (ACAD-01/02): access, server-side grading, certificates, CPD gating, seats, paid enrolment."""

from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

from taxng.legal.corpus import ContentError
from taxng.modules.academy.service import load_catalogue

from ..helpers import ServicesTestCase, add_member, create_org

FREE = "paye-nta2025"
PAID = "vat-einvoicing"
HAS_BILLING = importlib.util.find_spec("taxng.modules.billing") is not None


def _keys(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for k, v in value.items():
            found.add(k)
            found |= _keys(v)
    elif isinstance(value, list):
        for v in value:
            found |= _keys(v)
    return found


class AcademyCase(ServicesTestCase):
    def course(self, course_id: str = FREE) -> Any:
        return self.services.modules["academy"].courses[course_id]

    def correct_answers(self, quiz: Any) -> dict[str, str]:
        return {q.id: q.answer for q in quiz.questions}

    def enrol(self, client: Any, course_id: str = FREE) -> str:
        status, body = client.post(f"/api/academy/courses/{course_id}/enrol")
        self.assertEqual(status, 201, body)
        return body["id"]

    def finish(self, client: Any, enrolment_id: str, course_id: str = FREE) -> None:
        course = self.course(course_id)
        for lesson in course.lessons:
            self.assertEqual(client.post(f"/api/academy/enrolments/{enrolment_id}/lessons/{lesson.id}/complete").status, 200)
        status, body = client.post(
            f"/api/academy/enrolments/{enrolment_id}/quizzes/{course.assessment.id}/attempts", {"answers": self.correct_answers(course.assessment)}
        )
        self.assertEqual(status, 201)
        self.assertTrue(body["passed"])


class Catalogue(AcademyCase):
    def test_public_catalogue_and_outline_have_no_answers(self) -> None:
        anon = self.client()
        status, body = anon.get("/api/academy/courses")
        self.assertEqual(status, 200)
        self.assertEqual({FREE, PAID} <= {c["id"] for c in body["items"]}, True)
        status, outline = anon.get(f"/api/academy/courses/{FREE}")
        self.assertEqual(status, 200)
        self.assertNotIn("answer", _keys(outline))
        self.assertNotIn("explanation", _keys(outline))
        self.assertIsNone(outline["cpd"])
        self.assertTrue(outline["trainer"]["sample"])

    def test_paid_course_price_is_a_placeholder(self) -> None:
        _, outline = self.client().get(f"/api/academy/courses/{PAID}")
        self.assertEqual(outline["price"]["model"], "paid")
        self.assertTrue(outline["price"]["placeholder"])
        self.assertNotIn("amount_kobo", json.dumps(outline))

    def test_lesson_figures_come_from_the_engine(self) -> None:
        alice = self.client("fig@example.com")
        enr = self.enrol(alice)
        _, player = alice.get(f"/api/academy/enrolments/{enr}")
        lesson = next(l for m in player["modules"] for l in m["lessons"] if l["id"] == "m2-l2")
        card = lesson["figures"][0]
        self.assertEqual(card["name"], "pit.nta2025.rates")
        expected = [{"threshold": str(b.threshold), "rate": str(b.rate)} for b in self.services.tree.scale("pit.nta2025.rates", __import__("datetime").date.today())]
        self.assertEqual(card["scale"], expected)


class Access(AcademyCase):
    def test_anonymous_cannot_enrol_or_read_lessons(self) -> None:
        anon = self.client()
        self.assertEqual(anon.post(f"/api/academy/courses/{FREE}/enrol").status, 401)
        self.assertEqual(anon.get("/api/academy/me/enrolments").status, 401)
        self.assertEqual(anon.get("/api/academy/enrolments/enr_x").status, 401)

    def test_enrolment_required_and_no_cross_user_leakage(self) -> None:
        alice = self.client("alice@example.com")
        bob = self.client("bob@example.com")
        enr = self.enrol(alice)
        lesson = self.course().lessons[0].id
        quiz = self.course().modules[0].quiz
        self.assertEqual(bob.get(f"/api/academy/enrolments/{enr}").status, 404)
        self.assertEqual(bob.post(f"/api/academy/enrolments/{enr}/lessons/{lesson}/complete").status, 404)
        self.assertEqual(bob.post(f"/api/academy/enrolments/{enr}/quizzes/{quiz.id}/attempts", {"answers": {}}).status, 404)
        self.assertEqual(bob.post(f"/api/academy/enrolments/{enr}/certificate", {"name": "Bob"}).status, 404)
        # Alice's progress does not appear in Bob's view of the course.
        alice.post(f"/api/academy/enrolments/{enr}/lessons/{lesson}/complete")
        _, outline = bob.get(f"/api/academy/courses/{FREE}")
        self.assertIsNone(outline["my_enrolment"])
        _, mine = bob.get("/api/academy/me/enrolments")
        self.assertEqual(mine["items"], [])

    def test_double_enrolment_conflicts(self) -> None:
        carol = self.client("carol@example.com")
        self.enrol(carol)
        self.assertEqual(carol.post(f"/api/academy/courses/{FREE}/enrol").status, 409)

    def test_cohort_capacity(self) -> None:
        dave = self.client("dave@example.com")
        status, _ = dave.post(f"/api/academy/courses/{FREE}/enrol", {"cohort_id": "nope"})
        self.assertEqual(status, 422)
        status, body = dave.post(f"/api/academy/courses/{FREE}/enrol", {"cohort_id": "paye-2027-q1"})
        self.assertEqual(status, 201)
        _, outline = dave.get(f"/api/academy/courses/{FREE}")
        cohort = next(c for c in outline["cohorts"] if c["id"] == "paye-2027-q1")
        self.assertEqual(cohort["places_left"], cohort["capacity"] - 1)


class Grading(AcademyCase):
    def test_answers_hidden_until_submission_and_graded_on_server(self) -> None:
        erin = self.client("erin@example.com")
        enr = self.enrol(erin)
        status, player = erin.get(f"/api/academy/enrolments/{enr}")
        self.assertEqual(status, 200)
        self.assertNotIn("answer", _keys(player))
        self.assertNotIn("explanation", _keys(player))

        quiz = self.course().modules[0].quiz
        wrong = {q.id: next(o for o, _ in q.options if o != q.answer) for q in quiz.questions}
        # A client-claimed score is ignored.
        status, result = erin.post(
            f"/api/academy/enrolments/{enr}/quizzes/{quiz.id}/attempts", {"answers": wrong, "score": len(wrong), "passed": True}
        )
        self.assertEqual(status, 201)
        self.assertEqual(result["correct"], 0)
        self.assertFalse(result["passed"])
        self.assertTrue(all("explanation" in r and "answer" in r for r in result["results"]))

        status, result = erin.post(f"/api/academy/enrolments/{enr}/quizzes/{quiz.id}/attempts", {"answers": self.correct_answers(quiz)})
        self.assertEqual(result["correct"], result["total"])
        self.assertTrue(result["passed"])
        _, player = erin.get(f"/api/academy/enrolments/{enr}")
        self.assertEqual(player["results"][quiz.id]["attempts"], 2)
        self.assertTrue(player["results"][quiz.id]["passed"])

    def test_unknown_quiz_and_bad_answers(self) -> None:
        fay = self.client("fay@example.com")
        enr = self.enrol(fay)
        self.assertEqual(fay.post(f"/api/academy/enrolments/{enr}/quizzes/nope/attempts", {"answers": {}}).status, 404)
        quiz = self.course().modules[0].quiz.id
        self.assertEqual(fay.post(f"/api/academy/enrolments/{enr}/quizzes/{quiz}/attempts", {"answers": ["a"]}).status, 422)


class Certificates(AcademyCase):
    def test_issue_and_verify_and_reject_tampering(self) -> None:
        gil = self.client("gil@example.com")
        enr = self.enrol(gil)
        self.assertEqual(gil.post(f"/api/academy/enrolments/{enr}/certificate", {"name": "Gil Ade"}).status, 409)
        self.finish(gil, enr)
        status, cert = gil.post(f"/api/academy/enrolments/{enr}/certificate", {"name": "Gil Ade"})
        self.assertEqual(status, 201, cert)
        code = cert["code"]
        # Idempotent.
        self.assertEqual(gil.post(f"/api/academy/enrolments/{enr}/certificate", {"name": "Other"}).body["code"], code)

        anon = self.client()
        status, verified = anon.get(f"/api/academy/certificates/{code}")
        self.assertEqual(status, 200)
        self.assertTrue(verified["valid"])
        self.assertEqual(verified["holder_name"], "Gil Ade")
        self.assertEqual(verified["course_id"], FREE)

        prefix, cid, mac = code.split("-")
        flipped = mac[:-1] + ("0" if mac[-1] != "0" else "1")
        self.assertEqual(anon.get(f"/api/academy/certificates/{prefix}-{cid}-{flipped}").status, 404)
        other_id = cid[:-1] + ("0" if cid[-1] != "0" else "1")
        self.assertEqual(anon.get(f"/api/academy/certificates/{prefix}-{other_id}-{mac}").status, 404)
        self.assertEqual(anon.get("/api/academy/certificates/TNGC-guess").status, 404)

        # Editing the stored holder name invalidates the code.
        self.services.db.update("academy_certificates", {"holder_name": "Someone Else"}, "enrolment_id = ?", (enr,))
        self.assertEqual(anon.get(f"/api/academy/certificates/{code}").status, 404)

    def test_failed_assessment_blocks_certificate(self) -> None:
        hal = self.client("hal@example.com")
        enr = self.enrol(hal)
        for lesson in self.course().lessons:
            hal.post(f"/api/academy/enrolments/{enr}/lessons/{lesson.id}/complete")
        assessment = self.course().assessment
        hal.post(f"/api/academy/enrolments/{enr}/quizzes/{assessment.id}/attempts", {"answers": {}})
        self.assertEqual(hal.post(f"/api/academy/enrolments/{enr}/certificate", {"name": "Hal"}).status, 409)


class Cpd(AcademyCase):
    def test_cpd_claim_only_after_staff_approval(self) -> None:
        learner = self.client("learner@example.com")
        support = self.client("support@example.com", staff_role="support")
        editor = self.client("editor@example.com", staff_role="editor")
        self.assertIsNone(self.client().get(f"/api/academy/courses/{FREE}").body["cpd"])
        self.assertEqual(self.client().post(f"/api/academy/courses/{FREE}/cpd", {"body": "CITN", "reference": "CITN/CPD/1"}).status, 401)
        self.assertEqual(learner.post(f"/api/academy/courses/{FREE}/cpd", {"body": "CITN", "reference": "CITN/CPD/1"}).status, 403)
        self.assertEqual(support.post(f"/api/academy/courses/{FREE}/cpd", {"body": "CITN", "reference": "CITN/CPD/1"}).status, 403)
        self.assertEqual(editor.post(f"/api/academy/courses/{FREE}/cpd", {"body": "ACCA", "reference": "X/1"}).status, 422)
        self.assertEqual(editor.post(f"/api/academy/courses/{FREE}/cpd", {"body": "ICAN"}).status, 422)
        self.assertIsNone(self.client().get(f"/api/academy/courses/{FREE}").body["cpd"])

        status, cpd = editor.post(f"/api/academy/courses/{FREE}/cpd", {"body": "ICAN", "reference": "ICAN/CPD/2026/017"})
        self.assertEqual(status, 201)
        shown = self.client().get(f"/api/academy/courses/{FREE}").body["cpd"]
        self.assertEqual((shown["body"], shown["reference"]), ("ICAN", "ICAN/CPD/2026/017"))
        self.assertTrue(any(e["action"] == "academy.cpd_approved" for e in self.services.audit.events(entity_id=FREE)))

        self.assertEqual(editor.post(f"/api/academy/courses/{FREE}/cpd/withdraw").status, 200)
        self.assertIsNone(self.client().get(f"/api/academy/courses/{FREE}").body["cpd"])
        self.assertEqual(editor.post(f"/api/academy/courses/{FREE}/cpd/withdraw").status, 409)

    def test_content_cannot_claim_cpd(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        src = self.services.content_dir / "academy"
        shutil.copytree(src, tmp / "academy")
        path = tmp / "academy" / "courses" / f"{FREE}.yaml"
        raw = yaml.safe_load(path.read_text())
        raw["cpd"] = {"body": "CITN", "hours": 3}
        path.write_text(yaml.safe_dump(raw))
        fake = SimpleNamespace(content_dir=tmp, tree=self.services.tree, library=self.services.library)
        with self.assertRaises(ContentError):
            load_catalogue(fake)  # type: ignore[arg-type]

    def test_lesson_text_with_a_figure_is_rejected(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        shutil.copytree(self.services.content_dir / "academy", tmp / "academy")
        path = tmp / "academy" / "courses" / f"{FREE}.yaml"
        raw = yaml.safe_load(path.read_text())
        raw["modules"][0]["lessons"][0]["body"].append("The top rate is 25%.")
        path.write_text(yaml.safe_dump(raw))
        with self.assertRaises(ContentError):
            load_catalogue(SimpleNamespace(content_dir=tmp, tree=self.services.tree, library=self.services.library))  # type: ignore[arg-type]


class Seats(AcademyCase):
    def test_owner_buys_and_assigns_seats(self) -> None:
        owner = self.client("owner@seats.example")
        preparer = self.client("prep@seats.example")
        member = self.client("member@seats.example")
        outsider = self.client("outsider@seats.example")
        org = create_org(owner, "Seat Co")
        add_member(self.services, org, preparer, "preparer")
        add_member(self.services, org, member, "read_only")

        self.assertEqual(self.client().post(f"/api/academy/orgs/{org}/seats", {"course_id": FREE, "seats": 1}).status, 401)
        self.assertEqual(outsider.post(f"/api/academy/orgs/{org}/seats", {"course_id": FREE, "seats": 1}).status, 404)
        self.assertEqual(preparer.post(f"/api/academy/orgs/{org}/seats", {"course_id": FREE, "seats": 1}).status, 403)
        self.assertEqual(preparer.get(f"/api/academy/orgs/{org}/seats").status, 403)
        self.assertEqual(owner.post(f"/api/academy/orgs/{org}/seats", {"course_id": FREE, "seats": 0}).status, 422)

        status, pool = owner.post(f"/api/academy/orgs/{org}/seats", {"course_id": FREE, "seats": 1})
        self.assertEqual(status, 201)
        self.assertEqual(pool["status"], "active")

        assign = f"/api/academy/orgs/{org}/seats/{pool['id']}/assign"
        self.assertEqual(preparer.post(assign, {"user_id": member.user_id}).status, 403)
        self.assertEqual(outsider.post(assign, {"user_id": member.user_id}).status, 404)
        self.assertEqual(owner.post(assign, {"user_id": outsider.user_id}).status, 422)
        status, seat = owner.post(assign, {"user_id": member.user_id})
        self.assertEqual(status, 201)
        self.assertEqual(owner.post(assign, {"user_id": preparer.user_id}).status, 409)  # no seats left

        _, mine = member.get("/api/academy/me/enrolments")
        self.assertEqual([(e["course_id"], e["source"], e["status"]) for e in mine["items"]], [(FREE, "seat", "active")])
        self.assertEqual(member.get(f"/api/academy/enrolments/{seat['enrolment_id']}").status, 200)
        # The owner who assigned the seat cannot read the member's learning record.
        self.assertEqual(owner.get(f"/api/academy/enrolments/{seat['enrolment_id']}").status, 404)

    def test_pools_are_tenant_scoped(self) -> None:
        a = self.client("a@tenant.example")
        b = self.client("b@tenant.example")
        org_a = create_org(a, "A Ltd")
        org_b = create_org(b, "B Ltd")
        _, pool = a.post(f"/api/academy/orgs/{org_a}/seats", {"course_id": FREE, "seats": 2})
        self.assertEqual(b.post(f"/api/academy/orgs/{org_b}/seats/{pool['id']}/assign", {"user_id": b.user_id}).status, 404)
        self.assertEqual(b.get(f"/api/academy/orgs/{org_a}/seats").status, 404)


class FakeBilling:
    def __init__(self) -> None:
        self.handlers: dict[str, Any] = {}
        self.checkouts: list[dict[str, Any]] = []

    def register_payment_handler(self, purpose: str, fn: Any) -> None:
        self.handlers[purpose] = fn

    def create_checkout(self, **kw: Any) -> dict[str, Any]:
        checkout = {"checkout_id": f"chk_{len(self.checkouts) + 1}", "url": "/app/#/billing/checkout", "mode": "sandbox", **kw}
        self.checkouts.append(checkout)
        return {k: checkout[k] for k in ("checkout_id", "url", "mode")}


class PaidEnrolmentContract(AcademyCase):
    """Uses a stand-in that implements the billing contract in docs/MODULES.md."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.billing = FakeBilling()
        cls.services.modules["billing"] = cls.billing
        cls.services.modules["academy"]._handler_registered = False

    def test_paid_enrolment_activates_exactly_once(self) -> None:
        ivy = self.client("ivy@example.com")
        status, enr = ivy.post(f"/api/academy/courses/{PAID}/enrol")
        self.assertEqual(status, 201)
        self.assertEqual(enr["status"], "pending_payment")
        self.assertEqual(enr["checkout"]["mode"], "sandbox")
        checkout = self.billing.checkouts[-1]
        self.assertEqual((checkout["purpose"], checkout["reference_id"], checkout["payer_user_id"]), ("course", enr["id"], ivy.user_id))
        self.assertEqual(ivy.get(f"/api/academy/enrolments/{enr['id']}").status, 409)

        handler = self.billing.handlers["course"]
        payment = {"reference_id": enr["id"], "checkout_id": checkout["checkout_id"], "amount_kobo": checkout["amount_kobo"], "purpose": "course"}
        handler(self.services, {**payment, "amount_kobo": checkout["amount_kobo"] + 1})  # wrong amount: ignored
        self.assertEqual(ivy.get(f"/api/academy/enrolments/{enr['id']}").status, 409)
        handler(self.services, payment)
        handler(self.services, payment)  # replayed webhook
        self.assertEqual(ivy.get(f"/api/academy/enrolments/{enr['id']}").status, 200)
        paid = [e for e in self.services.audit.events(entity_id=enr["id"]) if e["action"] == "academy.enrolment_paid"]
        self.assertEqual(len(paid), 1)

    def test_paid_seats_activate_once(self) -> None:
        owner = self.client("owner@paid.example")
        org = create_org(owner, "Paid Seats Ltd")
        _, pool = owner.post(f"/api/academy/orgs/{org}/seats", {"course_id": PAID, "seats": 3})
        self.assertEqual(pool["status"], "pending_payment")
        checkout = self.billing.checkouts[-1]
        self.assertEqual(checkout["org_id"], org)
        self.assertEqual(owner.post(f"/api/academy/orgs/{org}/seats/{pool['id']}/assign", {"user_id": owner.user_id}).status, 409)
        payment = {"reference_id": pool["id"], "checkout_id": checkout["checkout_id"], "amount_kobo": checkout["amount_kobo"]}
        self.billing.handlers["course"](self.services, payment)
        self.billing.handlers["course"](self.services, payment)
        self.assertEqual(owner.post(f"/api/academy/orgs/{org}/seats/{pool['id']}/assign", {"user_id": owner.user_id}).status, 201)
        paid = [e for e in self.services.audit.events(entity_id=pool["id"]) if e["action"] == "academy.seats_paid"]
        self.assertEqual(len(paid), 1)


class PaymentsUnavailable(AcademyCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.services.modules.pop("billing", None)  # simulate billing being absent

    def test_paid_course_degrades_gracefully(self) -> None:
        jo = self.client("jo@example.com")
        _, outline = jo.get(f"/api/academy/courses/{PAID}")
        self.assertFalse(outline["payments_available"])
        self.assertEqual(jo.post(f"/api/academy/courses/{PAID}/enrol").status, 409)


@unittest.skipUnless(HAS_BILLING, "billing module not built yet")
class RealBilling(AcademyCase):
    def test_paid_enrolment_end_to_end_activates_once(self) -> None:
        kay = self.client("kay@example.com")
        status, enr = kay.post(f"/api/academy/courses/{PAID}/enrol")
        self.assertEqual(status, 201, enr)
        self.assertEqual(enr["status"], "pending_payment")
        self.assertEqual(enr["checkout"]["mode"], "sandbox")
        self.assertEqual(kay.get(f"/api/academy/enrolments/{enr['id']}").status, 409)
        checkout = enr["checkout"]["checkout_id"]
        status, body = kay.post(f"/api/billing/checkout/{checkout}/complete", {"outcome": "paid"})
        self.assertEqual(status, 200, body)
        kay.post(f"/api/billing/checkout/{checkout}/complete", {"outcome": "paid"})  # second delivery
        self.assertEqual(kay.get(f"/api/academy/enrolments/{enr['id']}").status, 200)
        paid = [e for e in self.services.audit.events(entity_id=enr["id"]) if e["action"] == "academy.enrolment_paid"]
        self.assertEqual(len(paid), 1)

    def test_missed_handler_is_reconciled(self) -> None:
        """A payment marked paid while the academy handler was not registered still activates once."""
        lee = self.client("lee@example.com")
        _, enr = lee.post(f"/api/academy/courses/{PAID}/enrol")
        self.services.db.update("billing_payments", {"status": "paid"}, "checkout_id = ?", (enr["checkout"]["checkout_id"],))
        _, mine = lee.get("/api/academy/me/enrolments")
        self.assertEqual(next(e for e in mine["items"] if e["id"] == enr["id"])["status"], "active")
        lee.get("/api/academy/me/enrolments")
        paid = [e for e in self.services.audit.events(entity_id=enr["id"]) if e["action"] == "academy.enrolment_paid"]
        self.assertEqual(len(paid), 1)
