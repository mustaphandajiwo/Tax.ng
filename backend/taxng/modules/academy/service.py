"""Academy domain logic (PRD section 8, ACAD-01/02).

* Courses are content (``content/academy/courses/*.yaml``), validated at load:
  lesson and quiz text may not state figures, and every linked parameter and
  provision must exist. Figures are rendered from the rules engine when a
  lesson is served.
* Quiz answers and explanations never leave the server before submission.
  Grading is done here from the learner's chosen option ids.
* Certificates carry a public code ``TNGC-<id>-<mac>`` where ``mac`` is an
  HMAC over the certificate's fields with a key derived from the platform
  secret, so codes cannot be guessed or altered.
* A CPD claim (ACAD-02) is shown only after staff record an approval with the
  accrediting body and its reference. Course content cannot carry one.
* Paid enrolments and institutional seats are paid through the billing
  module's contract and activated by its payment handler, exactly once.
"""

from __future__ import annotations

import datetime as dt
import hmac
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from ...legal.corpus import ContentError, _check_no_figures
from ...platform.access import NotFoundError
from ...platform.errors import Conflict, Invalid
from ...platform.util import iso, new_id, sign
from ...rules import ParameterError

if TYPE_CHECKING:
    from ...services import Services

CPD_BODIES = ("CITN", "ICAN")
CERT_CODE = re.compile(r"^TNGC-([0-9a-f]{20})-([0-9a-f]{20})$")
MAX_SEATS_PER_PURCHASE = 500  # operational guard, not a commercial figure


# ------------------------------------------------------------------ content
@dataclass(frozen=True)
class Question:
    id: str
    prompt: str
    options: tuple[tuple[str, str], ...]
    answer: str
    explanation: str

    def public(self) -> dict[str, Any]:
        """What the learner sees before answering: no answer, no explanation."""
        return {"id": self.id, "prompt": self.prompt, "options": [{"id": o, "text": t} for o, t in self.options]}


@dataclass(frozen=True)
class Quiz:
    id: str
    kind: str  # "quiz" | "assessment"
    pass_mark_percent: int
    questions: tuple[Question, ...]

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "pass_mark_percent": self.pass_mark_percent,
            "questions": [q.public() for q in self.questions],
        }


@dataclass(frozen=True)
class Lesson:
    id: str
    title: str
    body: tuple[str, ...]
    parameters: tuple[str, ...]
    provisions: tuple[str, ...]


@dataclass(frozen=True)
class CourseModule:
    id: str
    title: str
    lessons: tuple[Lesson, ...]
    quiz: Quiz | None


@dataclass(frozen=True)
class Course:
    id: str
    title: str
    summary: str
    level: str
    audience: tuple[str, ...]
    duration_hours: int | None
    trainer: str
    review_status: str
    review_note: str
    price_model: str  # "free" | "paid"
    price_amount_kobo: int | None
    price_label: str
    cohorts: tuple[dict[str, Any], ...]
    modules: tuple[CourseModule, ...]
    assessment: Quiz
    case_study: dict[str, Any] = field(default_factory=dict)

    @property
    def lessons(self) -> list[Lesson]:
        return [lesson for m in self.modules for lesson in m.lessons]

    def quiz(self, quiz_id: str) -> Quiz | None:
        if quiz_id == self.assessment.id:
            return self.assessment
        for m in self.modules:
            if m.quiz and m.quiz.id == quiz_id:
                return m.quiz
        return None


def _quiz(raw: dict[str, Any], kind: str, where: str) -> Quiz:
    questions = []
    for q in raw.get("questions") or []:
        options = tuple((str(o["id"]), str(o["text"])) for o in q["options"])
        if q["answer"] not in {o for o, _ in options}:
            raise ContentError(f"{where} question {q['id']} answer is not one of its options")
        for text in (q["prompt"], q["explanation"], *(t for _, t in options)):
            _check_no_figures(f"{where} question {q['id']}", str(text))
        questions.append(Question(str(q["id"]), str(q["prompt"]), options, str(q["answer"]), str(q["explanation"])))
    if not questions:
        raise ContentError(f"{where} has no questions")
    mark = int(raw["pass_mark_percent"])
    if not 0 < mark <= 100:
        raise ContentError(f"{where} pass mark must be between 1 and 100")
    return Quiz(str(raw["id"]), kind, mark, tuple(questions))


def load_catalogue(services: Services) -> tuple[dict[str, Course], dict[str, dict[str, Any]]]:
    base: Path = services.content_dir / "academy"
    trainers: dict[str, dict[str, Any]] = {}
    if (base / "trainers.yaml").exists():
        for t in yaml.safe_load((base / "trainers.yaml").read_text()) or []:
            for para in t.get("bio", []):
                _check_no_figures(f"trainer {t['id']}", para)
            trainers[t["id"]] = {
                "id": t["id"],
                "name": t["name"],
                "headline": t.get("headline", ""),
                "bio": list(t.get("bio", [])),
                "sample": bool(t.get("sample", False)),
            }
    courses: dict[str, Course] = {}
    for path in sorted((base / "courses").glob("*.yaml")) if (base / "courses").is_dir() else []:
        raw = yaml.safe_load(path.read_text())
        cid = raw["id"]
        if "cpd" in raw or "cpd_accreditation" in raw:
            raise ContentError(f"course {cid}: CPD claims come only from staff approval, not content (ACAD-02)")
        if raw.get("review_status") == "legal_approved":
            raise ContentError(f"course {cid}: legal approval is recorded by reviewers, not set in content")
        if raw["trainer"] not in trainers:
            raise ContentError(f"course {cid} names unknown trainer {raw['trainer']}")
        _check_no_figures(f"course {cid}", raw["summary"])
        modules = []
        for m in raw["modules"]:
            lessons = []
            for lesson in m["lessons"]:
                where = f"course {cid} lesson {lesson['id']}"
                for para in lesson.get("body", []):
                    _check_no_figures(where, para)
                for name in lesson.get("parameters", []):
                    if not services.tree.has(name):
                        raise ContentError(f"{where} links unknown parameter {name}")
                for pid in lesson.get("provisions", []):
                    if pid not in services.library.provisions:
                        raise ContentError(f"{where} cites unknown provision {pid}")
                lessons.append(
                    Lesson(
                        str(lesson["id"]),
                        lesson["title"],
                        tuple(lesson.get("body", [])),
                        tuple(lesson.get("parameters", [])),
                        tuple(lesson.get("provisions", [])),
                    )
                )
            quiz = _quiz(m["quiz"], "quiz", f"course {cid} {m['quiz']['id']}") if m.get("quiz") else None
            modules.append(CourseModule(str(m["id"]), m["title"], tuple(lessons), quiz))
        case = raw.get("case_study") or {}
        for key in ("scenario", "tasks", "discussion"):
            for para in case.get(key, []):
                _check_no_figures(f"course {cid} case study", para)
        price = raw.get("price") or {"model": "free"}
        if price["model"] not in ("free", "paid"):
            raise ContentError(f"course {cid}: price model must be free or paid")
        cohorts = tuple(
            {
                "id": str(c["id"]),
                "label": c.get("label", c["id"]),
                "starts_on": c["starts_on"].isoformat() if isinstance(c.get("starts_on"), dt.date) else c.get("starts_on"),
                "capacity": int(c["capacity"]) if c.get("capacity") else None,
            }
            for c in raw.get("cohorts") or []
        )
        ids = [lesson.id for m in modules for lesson in m.lessons]
        if len(ids) != len(set(ids)):
            raise ContentError(f"course {cid} repeats a lesson id")
        courses[cid] = Course(
            id=cid,
            title=raw["title"],
            summary=raw["summary"],
            level=raw.get("level", ""),
            audience=tuple(raw.get("audience", [])),
            duration_hours=raw.get("duration_hours"),
            trainer=raw["trainer"],
            review_status=raw["review_status"],
            review_note=raw.get("review_note", ""),
            price_model=price["model"],
            price_amount_kobo=int(price["amount_kobo"]) if price.get("amount_kobo") is not None else None,
            price_label=price.get("label") or ("Free" if price["model"] == "free" else "To be set after validation"),
            cohorts=cohorts,
            modules=tuple(modules),
            assessment=_quiz(raw["assessment"], "assessment", f"course {cid} assessment"),
            case_study=case,
        )
    return courses, trainers


def parameter_card(services: Services, name: str, on: dt.date) -> dict[str, Any]:
    """Same shape as the core API's figure cards (frontend ``ParameterCard``)."""
    tree = services.tree
    info = tree.info(name)
    card: dict[str, Any] = {
        "name": name,
        "description": info.description,
        "unit": info.unit,
        "review_status": info.review_status,
        "reference": info.reference,
        "in_force": True,
    }
    try:
        if tree.is_scale(name):
            card["scale"] = [{"threshold": str(b.threshold), "rate": str(b.rate)} for b in tree.scale(name, on)]
        else:
            value = tree.value(name, on)
            card["value"] = value if isinstance(value, (list, bool)) else str(value)
    except ParameterError:
        card["in_force"] = False
    return card


# ------------------------------------------------------------------ service
class Academy:
    def __init__(self, services: Services) -> None:
        self.services = services
        self.db = services.db
        self.courses, self.trainers = load_catalogue(services)
        self._cert_key = sign(services.secret, "academy.certificate.v1")
        self._handler_registered = False

    # ---------------------------------------------------------- billing link
    @property
    def billing(self) -> Any | None:
        billing = self.services.modules.get("billing")
        if billing is not None and not self._handler_registered:
            billing.register_payment_handler("course", payment_handler)
            self._handler_registered = True
        return billing

    def payments_available(self) -> bool:
        return self.billing is not None

    def _reconcile(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        """Safety net for a missed handler call (e.g. a webhook processed before the
        lazy handler registration after a restart). Uses billing's optional
        ``payment_by_checkout`` if it exists; activation stays idempotent."""
        if row["status"] != "pending_payment" or not row.get("checkout_id"):
            return row
        lookup = getattr(self.billing, "payment_by_checkout", None)
        if lookup is None:
            return row
        try:
            payment = lookup(row["checkout_id"])
        except Exception:  # noqa: BLE001 - billing unavailable or unknown checkout: leave pending
            return row
        if payment.get("status") == "paid" and payment.get("purpose") == "course" and payment.get("reference_id") == row["id"]:
            self.activate_payment(payment)
            return self.db.one(f"SELECT * FROM {table} WHERE id = ?", (row["id"],)) or row  # fixed table names only
        return row

    # ------------------------------------------------------------- lookups
    def course(self, course_id: str) -> Course:
        course = self.courses.get(course_id)
        if course is None:
            raise NotFoundError(f"Unknown course {course_id}")
        return course

    def cpd_status(self, course_id: str) -> dict[str, Any] | None:
        row = self.db.one(
            "SELECT body, reference, approved_at FROM academy_cpd_approvals WHERE course_id = ? AND withdrawn_at IS NULL "
            "ORDER BY approved_at DESC, rowid DESC LIMIT 1",
            (course_id,),
        )
        return {"accredited": True, **row} if row else None

    def enrolment_for(self, user_id: str, enrolment_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM academy_enrolments WHERE id = ? AND user_id = ?", (enrolment_id, user_id))
        if row is None:
            raise NotFoundError("Enrolment not found")
        return self._reconcile("academy_enrolments", row)

    def active_enrolment(self, user_id: str, enrolment_id: str) -> tuple[dict[str, Any], Course]:
        row = self.enrolment_for(user_id, enrolment_id)
        if row["status"] != "active":
            raise Conflict("This enrolment is not active yet")
        return row, self.course(row["course_id"])

    # --------------------------------------------------------- public views
    def price(self, course: Course) -> dict[str, Any]:
        if course.price_model == "free":
            return {"model": "free", "label": "Free"}
        return {
            "model": "paid",
            "label": course.price_label,
            "placeholder": True,
            "note": "Prices are placeholders until validation. Checkout runs in sandbox mode only.",
        }

    def summary(self, course: Course) -> dict[str, Any]:
        return {
            "id": course.id,
            "title": course.title,
            "summary": course.summary,
            "level": course.level,
            "audience": list(course.audience),
            "duration_hours": course.duration_hours,
            "review_status": course.review_status,
            "price": self.price(course),
            "cpd": self.cpd_status(course.id),
            "trainer": self.trainers[course.trainer],
            "lesson_count": len(course.lessons),
        }

    def outline(self, course: Course) -> dict[str, Any]:
        cohorts = []
        for c in course.cohorts:
            taken = self.db.scalar(
                "SELECT COUNT(*) FROM academy_enrolments WHERE course_id = ? AND cohort_id = ? AND status != 'cancelled'",
                (course.id, c["id"]),
            )
            cohorts.append({**c, "places_left": None if c["capacity"] is None else max(0, c["capacity"] - taken)})
        return {
            **self.summary(course),
            "review_note": course.review_note,
            "payments_available": course.price_model == "free" or self.payments_available(),
            "cohorts": cohorts,
            "modules": [
                {
                    "id": m.id,
                    "title": m.title,
                    "lessons": [{"id": lesson.id, "title": lesson.title} for lesson in m.lessons],
                    "has_quiz": m.quiz is not None,
                }
                for m in course.modules
            ],
            "assessment": {"question_count": len(course.assessment.questions), "pass_mark_percent": course.assessment.pass_mark_percent},
            "case_study": {"title": course.case_study.get("title")} if course.case_study else None,
        }

    # ------------------------------------------------------------ enrolment
    def _check_cohort(self, course: Course, cohort_id: str | None) -> str | None:
        if not cohort_id:
            return None
        cohort = next((c for c in course.cohorts if c["id"] == cohort_id), None)
        if cohort is None:
            raise Invalid("cohort_id: unknown cohort for this course")
        if cohort["capacity"] is not None:
            taken = self.db.scalar(
                "SELECT COUNT(*) FROM academy_enrolments WHERE course_id = ? AND cohort_id = ? AND status != 'cancelled'",
                (course.id, cohort_id),
            )
            if taken >= cohort["capacity"]:
                raise Conflict("This cohort is full")
        return cohort_id

    def enrol(self, user_id: str, course_id: str, cohort_id: str | None = None) -> dict[str, Any]:
        course = self.course(course_id)
        existing = self.db.one("SELECT * FROM academy_enrolments WHERE user_id = ? AND course_id = ?", (user_id, course_id))
        if existing and existing["status"] == "active":
            raise Conflict("You are already enrolled on this course")
        if existing and existing["status"] == "pending_payment":
            return self.enrolment_view(existing)
        if course.price_model == "paid" and self.billing is None:
            raise Conflict("Payments are unavailable at the moment, so paid courses cannot be joined yet")
        cohort = self._check_cohort(course, cohort_id)
        enrolment_id = new_id("enr")
        row: dict[str, Any] = {
            "id": enrolment_id,
            "user_id": user_id,
            "course_id": course_id,
            "cohort_id": cohort,
            "created_at": iso(),
        }
        if course.price_model == "free":
            row.update(status="active", source="free", activated_at=iso())
            self.db.insert("academy_enrolments", row)
        else:
            row.update(status="pending_payment", source="paid")
            self.db.insert("academy_enrolments", row)
            checkout = self.billing.create_checkout(
                payer_user_id=user_id,
                org_id=None,
                purpose="course",
                reference_id=enrolment_id,
                amount_kobo=int(course.price_amount_kobo or 0),
                description=f"tax.ng Academy: {course.title}",
            )
            self.db.update(
                "academy_enrolments",
                {"checkout_id": checkout.get("checkout_id"), "checkout_url": checkout.get("url"), "checkout_mode": checkout.get("mode")},
                "id = ?",
                (enrolment_id,),
            )
        self.services.audit.record(
            "academy.enrol", "academy_enrolment", enrolment_id, actor_id=user_id, data={"course_id": course_id, "source": row["source"], "status": row["status"]}
        )
        self.services.store.record_event("academy_enrolled", {"course": course_id, "source": row["source"]})
        return self.enrolment_view(self.db.one("SELECT * FROM academy_enrolments WHERE id = ?", (enrolment_id,)))

    def enrolment_view(self, row: dict[str, Any]) -> dict[str, Any]:
        view = {k: row[k] for k in ("id", "course_id", "cohort_id", "status", "source", "created_at", "activated_at")}
        if row["status"] == "pending_payment":
            view["checkout"] = {"checkout_id": row["checkout_id"], "url": row["checkout_url"], "mode": row["checkout_mode"]}
        return view

    def my_enrolments(self, user_id: str) -> list[dict[str, Any]]:
        out = []
        for row in self.db.query("SELECT * FROM academy_enrolments WHERE user_id = ? ORDER BY created_at DESC", (user_id,)):
            row = self._reconcile("academy_enrolments", row)
            course = self.courses.get(row["course_id"])
            if course is None:
                continue
            done = self.db.scalar("SELECT COUNT(*) FROM academy_progress WHERE enrolment_id = ?", (row["id"],))
            cert = self.db.one("SELECT id FROM academy_certificates WHERE enrolment_id = ?", (row["id"],))
            out.append(
                {
                    **self.enrolment_view(row),
                    "course_title": course.title,
                    "lessons_done": done,
                    "lesson_count": len(course.lessons),
                    "certified": cert is not None,
                }
            )
        return out

    # ------------------------------------------------------------ player
    def player(self, user_id: str, enrolment_id: str) -> dict[str, Any]:
        row, course = self.active_enrolment(user_id, enrolment_id)
        on = dt.date.today()
        done = {r["lesson_id"] for r in self.db.query("SELECT lesson_id FROM academy_progress WHERE enrolment_id = ?", (enrolment_id,))}
        best = {
            a["quiz_id"]: {"attempts": a["attempts"], "best_correct": a["best"], "total": a["total"], "passed": bool(a["passed"])}
            for a in self.db.query(
                "SELECT quiz_id, COUNT(*) AS attempts, MAX(correct) AS best, MAX(total) AS total, MAX(passed) AS passed "
                "FROM academy_attempts WHERE enrolment_id = ? GROUP BY quiz_id",
                (enrolment_id,),
            )
        }
        return {
            "enrolment": self.enrolment_view(row),
            "course": self.summary(course),
            "review_note": course.review_note,
            "modules": [
                {
                    "id": m.id,
                    "title": m.title,
                    "lessons": [
                        {
                            "id": lesson.id,
                            "title": lesson.title,
                            "body": list(lesson.body),
                            "figures": [parameter_card(self.services, n, on) for n in lesson.parameters],
                            "provisions": [
                                {"id": pid, "title": self.services.library.provisions[pid].title} for pid in lesson.provisions
                            ],
                            "completed": lesson.id in done,
                        }
                        for lesson in m.lessons
                    ],
                    "quiz": m.quiz.public() if m.quiz else None,
                }
                for m in course.modules
            ],
            "assessment": course.assessment.public(),
            "case_study": course.case_study or None,
            "results": best,
            "certificate": self.certificate_for_enrolment(enrolment_id),
        }

    def complete_lesson(self, user_id: str, enrolment_id: str, lesson_id: str) -> dict[str, Any]:
        _, course = self.active_enrolment(user_id, enrolment_id)
        if lesson_id not in {lesson.id for lesson in course.lessons}:
            raise NotFoundError("Lesson not found")
        self.db.execute(
            "INSERT OR IGNORE INTO academy_progress (enrolment_id, lesson_id, completed_at) VALUES (?, ?, ?)",
            (enrolment_id, lesson_id, iso()),
        )
        done = self.db.scalar("SELECT COUNT(*) FROM academy_progress WHERE enrolment_id = ?", (enrolment_id,))
        return {"lesson_id": lesson_id, "completed": True, "lessons_done": done, "lesson_count": len(course.lessons)}

    def grade(self, user_id: str, enrolment_id: str, quiz_id: str, answers: Any) -> dict[str, Any]:
        _, course = self.active_enrolment(user_id, enrolment_id)
        quiz = course.quiz(quiz_id)
        if quiz is None:
            raise NotFoundError("Quiz not found")
        if not isinstance(answers, dict):
            raise Invalid("answers: send an object of question id to option id")
        chosen = {q.id: str(answers.get(q.id, "")) for q in quiz.questions}
        results = []
        correct = 0
        for q in quiz.questions:
            ok = hmac.compare_digest(chosen[q.id], q.answer)
            correct += ok
            results.append({"id": q.id, "chosen": chosen[q.id] or None, "correct": ok, "answer": q.answer, "explanation": q.explanation})
        total = len(quiz.questions)
        passed = correct * 100 >= quiz.pass_mark_percent * total
        attempt_id = new_id("att")
        self.db.insert(
            "academy_attempts",
            {
                "id": attempt_id,
                "enrolment_id": enrolment_id,
                "quiz_id": quiz.id,
                "kind": quiz.kind,
                "answers_json": json.dumps(chosen, sort_keys=True),
                "correct": correct,
                "total": total,
                "passed": int(passed),
                "created_at": iso(),
            },
        )
        if quiz.kind == "assessment":
            self.services.audit.record(
                "academy.assessment", "academy_enrolment", enrolment_id, actor_id=user_id, data={"passed": passed, "correct": correct, "total": total}
            )
        return {
            "attempt_id": attempt_id,
            "quiz_id": quiz.id,
            "kind": quiz.kind,
            "correct": correct,
            "total": total,
            "pass_mark_percent": quiz.pass_mark_percent,
            "passed": passed,
            "results": results,
        }

    # -------------------------------------------------------- certificates
    def _mac(self, cert_id: str, user_id: str, course_id: str, holder: str, issued_at: str) -> str:
        message = json.dumps([cert_id, user_id, course_id, holder, issued_at], separators=(",", ":"))
        return sign(self._cert_key, message)[:20]

    def code(self, row: dict[str, Any]) -> str:
        return f"TNGC-{row['id'].split('_', 1)[1]}-{row['mac']}"

    def certificate_for_enrolment(self, enrolment_id: str) -> dict[str, Any] | None:
        row = self.db.one("SELECT * FROM academy_certificates WHERE enrolment_id = ?", (enrolment_id,))
        if row is None:
            return None
        return {"code": self.code(row), "holder_name": row["holder_name"], "issued_at": row["issued_at"], "cpd": json.loads(row["cpd_json"])}

    def issue_certificate(self, user_id: str, enrolment_id: str, holder_name: str) -> dict[str, Any]:
        row, course = self.active_enrolment(user_id, enrolment_id)
        existing = self.certificate_for_enrolment(enrolment_id)
        if existing:
            return existing
        done = {r["lesson_id"] for r in self.db.query("SELECT lesson_id FROM academy_progress WHERE enrolment_id = ?", (enrolment_id,))}
        missing = [lesson.id for lesson in course.lessons if lesson.id not in done]
        if missing:
            raise Conflict(f"Complete every lesson first ({len(missing)} left)")
        passed = self.db.scalar(
            "SELECT COUNT(*) FROM academy_attempts WHERE enrolment_id = ? AND quiz_id = ? AND passed = 1",
            (enrolment_id, course.assessment.id),
        )
        if not passed:
            raise Conflict("Pass the final assessment first")
        holder = " ".join(holder_name.split())
        if not 2 <= len(holder) <= 120:
            raise Invalid("name: enter the name to print on the certificate")
        cert_id = new_id("cert")
        issued_at = iso()
        cpd = self.cpd_status(course.id)
        self.db.insert(
            "academy_certificates",
            {
                "id": cert_id,
                "enrolment_id": enrolment_id,
                "user_id": user_id,
                "course_id": course.id,
                "holder_name": holder,
                "issued_at": issued_at,
                "mac": self._mac(cert_id, user_id, course.id, holder, issued_at),
                "cpd_json": json.dumps(cpd),
            },
        )
        self.services.audit.record("academy.certificate_issued", "academy_certificate", cert_id, actor_id=user_id, data={"course_id": course.id})
        self.services.store.record_event("academy_certificate_issued", {"course": course.id})
        return self.certificate_for_enrolment(enrolment_id)  # type: ignore[return-value]

    def verify_certificate(self, code: str) -> dict[str, Any]:
        match = CERT_CODE.match(code.strip())
        if not match:
            raise NotFoundError("No valid certificate matches that code")
        row = self.db.one("SELECT * FROM academy_certificates WHERE id = ?", (f"cert_{match.group(1)}",))
        if row is None:
            raise NotFoundError("No valid certificate matches that code")
        expected = self._mac(row["id"], row["user_id"], row["course_id"], row["holder_name"], row["issued_at"])
        if not (hmac.compare_digest(expected, match.group(2)) and hmac.compare_digest(expected, row["mac"])):
            raise NotFoundError("No valid certificate matches that code")
        course = self.courses.get(row["course_id"])
        return {
            "valid": True,
            "code": self.code(row),
            "holder_name": row["holder_name"],
            "course_id": row["course_id"],
            "course_title": course.title if course else row["course_id"],
            "issued_at": row["issued_at"],
            "issuer": "tax.ng Academy, Astound Innovation Hub",
            "cpd": json.loads(row["cpd_json"]),
        }

    # ----------------------------------------------------------- CPD claims
    def approve_cpd(self, staff_id: str, course_id: str, body: str, reference: str) -> dict[str, Any]:
        self.course(course_id)
        if body not in CPD_BODIES:
            raise Invalid("body: must be CITN or ICAN")
        reference = reference.strip()
        if not 3 <= len(reference) <= 120:
            raise Invalid("reference: enter the accrediting body's approval reference")
        with self.db.transaction():
            self.db.update(
                "academy_cpd_approvals", {"withdrawn_at": iso(), "withdrawn_by": staff_id}, "course_id = ? AND withdrawn_at IS NULL", (course_id,)
            )
            approval_id = new_id("cpd")
            self.db.insert(
                "academy_cpd_approvals",
                {"id": approval_id, "course_id": course_id, "body": body, "reference": reference, "approved_by": staff_id, "approved_at": iso()},
            )
        self.services.audit.record("academy.cpd_approved", "course", course_id, actor_id=staff_id, data={"body": body, "reference": reference})
        return self.cpd_status(course_id)  # type: ignore[return-value]

    def withdraw_cpd(self, staff_id: str, course_id: str) -> None:
        self.course(course_id)
        n = self.db.update(
            "academy_cpd_approvals", {"withdrawn_at": iso(), "withdrawn_by": staff_id}, "course_id = ? AND withdrawn_at IS NULL", (course_id,)
        )
        if n == 0:
            raise Conflict("This course has no CPD claim to withdraw")
        self.services.audit.record("academy.cpd_withdrawn", "course", course_id, actor_id=staff_id)

    # --------------------------------------------------------------- seats
    def seat_pools(self, org_id: str) -> list[dict[str, Any]]:
        pools = []
        for p in self.db.query("SELECT * FROM academy_seat_pools WHERE org_id = ? ORDER BY created_at DESC", (org_id,)):
            p = self._reconcile("academy_seat_pools", p)
            assigned = self.db.query(
                "SELECT a.user_id, u.email, u.name, a.assigned_at FROM academy_seat_assignments a JOIN users u ON u.id = a.user_id "
                "WHERE a.pool_id = ? ORDER BY a.assigned_at",
                (p["id"],),
            )
            course = self.courses.get(p["course_id"])
            pools.append(
                {
                    "id": p["id"],
                    "course_id": p["course_id"],
                    "course_title": course.title if course else p["course_id"],
                    "seats_total": p["seats_total"],
                    "seats_used": len(assigned),
                    "status": p["status"],
                    "checkout": {"checkout_id": p["checkout_id"], "url": p["checkout_url"], "mode": p["checkout_mode"]}
                    if p["status"] == "pending_payment"
                    else None,
                    "assigned": assigned,
                }
            )
        return pools

    def buy_seats(self, actor_id: str, org_id: str, course_id: str, seats: Any) -> dict[str, Any]:
        course = self.course(course_id)
        try:
            count = int(seats)
        except (TypeError, ValueError):
            raise Invalid("seats: must be a whole number") from None
        if not 1 <= count <= MAX_SEATS_PER_PURCHASE:
            raise Invalid(f"seats: choose between 1 and {MAX_SEATS_PER_PURCHASE}")
        if course.price_model == "paid" and self.billing is None:
            raise Conflict("Payments are unavailable at the moment, so paid seats cannot be bought yet")
        pool_id = new_id("seats")
        row: dict[str, Any] = {
            "id": pool_id,
            "org_id": org_id,
            "course_id": course_id,
            "seats_total": count,
            "created_by": actor_id,
            "created_at": iso(),
        }
        if course.price_model == "free":
            row.update(status="active", activated_at=iso())
            self.db.insert("academy_seat_pools", row)
        else:
            row["status"] = "pending_payment"
            self.db.insert("academy_seat_pools", row)
            checkout = self.billing.create_checkout(
                payer_user_id=actor_id,
                org_id=org_id,
                purpose="course",
                reference_id=pool_id,
                amount_kobo=int(Decimal(course.price_amount_kobo or 0) * count),
                description=f"tax.ng Academy: {count} seats on {course.title}",
            )
            self.db.update(
                "academy_seat_pools",
                {"checkout_id": checkout.get("checkout_id"), "checkout_url": checkout.get("url"), "checkout_mode": checkout.get("mode")},
                "id = ?",
                (pool_id,),
            )
        self.services.audit.record(
            "academy.seats_created", "academy_seat_pool", pool_id, actor_id=actor_id, org_id=org_id, data={"course_id": course_id, "seats": count}
        )
        return next(p for p in self.seat_pools(org_id) if p["id"] == pool_id)

    def assign_seat(self, actor_id: str, org_id: str, pool_id: str, user_id: str) -> dict[str, Any]:
        pool = self.db.one("SELECT * FROM academy_seat_pools WHERE id = ? AND org_id = ?", (pool_id, org_id))
        if pool is None:
            raise NotFoundError("Seat pool not found")
        pool = self._reconcile("academy_seat_pools", pool)
        if pool["status"] != "active":
            raise Conflict("These seats are awaiting payment")
        member = self.db.one("SELECT role FROM memberships WHERE org_id = ? AND user_id = ?", (org_id, user_id))
        if member is None:
            raise Invalid("user_id: seats can be assigned only to members of this organisation")
        with self.db.transaction():
            used = self.db.scalar("SELECT COUNT(*) FROM academy_seat_assignments WHERE pool_id = ?", (pool_id,))
            if self.db.one("SELECT 1 FROM academy_seat_assignments WHERE pool_id = ? AND user_id = ?", (pool_id, user_id)):
                raise Conflict("This member already has a seat")
            if used >= pool["seats_total"]:
                raise Conflict("No seats left in this purchase")
            existing = self.db.one("SELECT * FROM academy_enrolments WHERE user_id = ? AND course_id = ?", (user_id, pool["course_id"]))
            if existing and existing["status"] == "active":
                raise Conflict("This member is already enrolled on the course")
            if existing:
                enrolment_id = existing["id"]
                self.db.update(
                    "academy_enrolments",
                    {"status": "active", "source": "seat", "seat_pool_id": pool_id, "activated_at": iso()},
                    "id = ?",
                    (enrolment_id,),
                )
            else:
                enrolment_id = new_id("enr")
                self.db.insert(
                    "academy_enrolments",
                    {
                        "id": enrolment_id,
                        "user_id": user_id,
                        "course_id": pool["course_id"],
                        "status": "active",
                        "source": "seat",
                        "seat_pool_id": pool_id,
                        "created_at": iso(),
                        "activated_at": iso(),
                    },
                )
            self.db.insert(
                "academy_seat_assignments",
                {"pool_id": pool_id, "user_id": user_id, "enrolment_id": enrolment_id, "assigned_by": actor_id, "assigned_at": iso()},
            )
        self.services.audit.record("academy.seat_assigned", "academy_seat_pool", pool_id, actor_id=actor_id, org_id=org_id, data={"enrolment_id": enrolment_id})
        return {"pool_id": pool_id, "enrolment_id": enrolment_id, "status": "active"}

    # ------------------------------------------------------------- payments
    def activate_payment(self, payment: dict[str, Any]) -> bool:
        """Billing's handler for purpose "course". Returns True only on the first activation."""
        reference = str(payment.get("reference_id") or "")
        checkout_id = payment.get("checkout_id")
        amount = payment.get("amount_kobo")
        if reference.startswith("enr_"):
            row = self.db.one("SELECT * FROM academy_enrolments WHERE id = ?", (reference,))
            if row is None or (checkout_id and row["checkout_id"] and checkout_id != row["checkout_id"]):
                return False
            course = self.courses.get(row["course_id"])
            if course and amount is not None and int(amount) != int(course.price_amount_kobo or 0):
                return False
            changed = self.db.update(
                "academy_enrolments", {"status": "active", "activated_at": iso()}, "id = ? AND status = 'pending_payment'", (reference,)
            )
            if changed:
                self.services.audit.record("academy.enrolment_paid", "academy_enrolment", reference, actor_id=row["user_id"], data={"course_id": row["course_id"]})
            return bool(changed)
        if reference.startswith("seats_"):
            row = self.db.one("SELECT * FROM academy_seat_pools WHERE id = ?", (reference,))
            if row is None or (checkout_id and row["checkout_id"] and checkout_id != row["checkout_id"]):
                return False
            course = self.courses.get(row["course_id"])
            if course and amount is not None and int(amount) != int(Decimal(course.price_amount_kobo or 0) * row["seats_total"]):
                return False
            changed = self.db.update(
                "academy_seat_pools", {"status": "active", "activated_at": iso()}, "id = ? AND status = 'pending_payment'", (reference,)
            )
            if changed:
                self.services.audit.record(
                    "academy.seats_paid", "academy_seat_pool", reference, actor_id=row["created_by"], org_id=row["org_id"], data={"seats": row["seats_total"]}
                )
            return bool(changed)
        return False


def payment_handler(services: Services, payment: dict[str, Any]) -> None:
    services.modules["academy"].activate_payment(payment)
