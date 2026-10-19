"""Channels: WhatsApp webhook and bot (CH-02), localisation workflow (CH-04, CH-05)."""

from __future__ import annotations

import tempfile
from decimal import Decimal
from pathlib import Path

from taxng.calculators import CALCULATORS
from taxng.format import naira
from taxng.legal.corpus import ContentError
from taxng.modules.channels.i18n import load_catalogues
from taxng.modules.channels.whatsapp import RATE_LIMIT, sign_payload
from taxng.platform.util import canonical_json, iso, new_id
from taxng.services import build_services

from ..helpers import Client, ServicesTestCase

PHONE = "+2348031234567"
DIGITS = "2348031234567"


class Bot(ServicesTestCase):
    counter = 0

    def say(self, text: str, phone: str = PHONE) -> dict:
        status, body = self.client().post("/api/channels/whatsapp/demo", {"phone": phone, "text": text})
        self.assertEqual(status, 200, body)
        return body

    def fresh_phone(self) -> str:
        Bot.counter += 1
        return f"+234809{Bot.counter:07d}"

    def pit(self, annual: Decimal) -> dict:
        return CALCULATORS["pit"]({"annual_gross_income": str(annual)}, self.services.tree).to_dict()["outputs"]

    def test_paye_parsing(self) -> None:
        phone = self.fresh_phone()
        reply = self.say("PAYE 500000", phone)
        self.assertEqual(reply["kind"], "paye")
        self.assertIn(f"Annual tax: {naira(Decimal(self.pit(Decimal(500000))['annual_tax']))}", reply["reply"])

        reply = self.say("PAYE 6m", phone)["reply"]
        out = self.pit(Decimal(6) * 10**6)
        self.assertIn(f"Gross income: {naira(Decimal(6) * 10**6)}", reply)
        self.assertIn(f"Monthly PAYE: {naira(Decimal(out['monthly_tax']))}", reply)
        self.assertIn("Source: ", reply)
        self.assertIn("/#/calculators/pit", reply)

        reply = self.say("tax 450k monthly", phone)["reply"]
        annual = Decimal(450) * 1000 * 12
        self.assertIn("x 12", reply)
        self.assertIn(f"Gross income: {naira(annual)}", reply)
        self.assertIn(f"Annual tax: {naira(Decimal(self.pit(annual)['annual_tax']))}", reply)

    def test_vat_parsing(self) -> None:
        reply = self.say("VAT 100000", self.fresh_phone())
        self.assertEqual(reply["kind"], "vat")
        out = CALCULATORS["vat"]({"amount": "100000"}, self.services.tree).to_dict()["outputs"]
        self.assertIn(f"Total: {naira(Decimal(out['gross_amount']))}", reply["reply"])

    def test_other_text_goes_to_tax_ai(self) -> None:
        question = "what is rent relief"
        reply = self.say(question, self.fresh_phone())
        self.assertEqual(reply["kind"], "ai")
        expected = self.services.assistant.answer(question)
        self.assertTrue(reply["reply"].startswith(expected["answer"][:60]))
        self.assertIn(expected["citations"][0]["title"], reply["reply"])
        self.assertLess(len(reply["reply"]), 1600)

    def test_help(self) -> None:
        reply = self.say("help", self.fresh_phone())
        self.assertEqual(reply["kind"], "help")
        self.assertIn("STOP", reply["reply"])

    def test_stop_opt_out_suppresses_alerts(self) -> None:
        phone = self.fresh_phone()
        support = self.client("support@wa.example", staff_role="support")
        self.assertEqual(self.client("user@wa.example").post("/api/channels/whatsapp/alerts", {"phone": phone, "text": "Hello there"}).status, 403)
        self.assertEqual(support.post("/api/channels/whatsapp/alerts", {"phone": phone, "text": "Hello there"}).body["status"], "not_opted_in")
        self.say("help", phone)
        self.assertEqual(support.post("/api/channels/whatsapp/alerts", {"phone": phone, "text": "Filing season opens soon"}).body["status"], "sent")
        self.assertEqual(self.say("STOP", phone)["kind"], "stop")
        before = len(self.services.notifier.recent(limit=500))
        status, body = support.post("/api/channels/whatsapp/alerts", {"phone": phone, "text": "Filing season opens soon"})
        self.assertEqual(body["status"], "suppressed_opted_out")
        self.assertEqual(len(self.services.notifier.recent(limit=500)), before)
        # Replies to the user's own messages still go out.
        self.assertEqual(self.say("VAT 5000", phone)["kind"], "vat")
        self.say("start", phone)
        self.assertEqual(support.post("/api/channels/whatsapp/alerts", {"phone": phone, "text": "Back on"}).body["status"], "sent")
        self.assertEqual(support.post("/api/channels/whatsapp/alerts", {"phone": phone, "text": "Rate is 7.5%"}).status, 422)

    def test_rate_limit_per_sender(self) -> None:
        phone = self.fresh_phone()
        for _ in range(RATE_LIMIT):
            self.say("help", phone)
        status, body = self.client().post("/api/channels/whatsapp/demo", {"phone": phone, "text": "help"})
        self.assertEqual(status, 429)
        # Another sender is unaffected.
        self.assertEqual(self.say("help", self.fresh_phone())["kind"], "help")

    def test_only_hashed_phone_is_stored(self) -> None:
        self.say("PAYE 2m", PHONE)
        self.say("what is VAT", "08031234567")  # same number in local format
        local = DIGITS[3:]
        for table in ("wa_contacts", "wa_messages", "outbox", "audit_events", "events"):
            dump = canonical_json(self.services.db.query(f"SELECT * FROM {table}"))
            self.assertNotIn(DIGITS, dump, table)
            self.assertNotIn(local, dump, table)
        h = self.services.modules["channels"].whatsapp.phone_hash(PHONE)
        self.assertEqual(self.services.db.scalar("SELECT COUNT(*) FROM wa_contacts WHERE phone_hash = ?", (h,)), 1)
        outbox = self.services.notifier.recent(f"wa:{h[:16]}", limit=5)
        self.assertTrue(outbox and all(m["channel"] == "whatsapp" and m["mode"] == "sandbox" for m in outbox))

    def test_retention_purge(self) -> None:
        old = iso(__import__("datetime").datetime(2020, 1, 1, tzinfo=__import__("datetime").timezone.utc))
        self.services.db.insert("wa_messages", {"id": new_id("wam"), "phone_hash": "x", "direction": "in", "kind": "ai", "snippet": "old", "created_at": old})
        self.say("help", self.fresh_phone())
        self.assertEqual(self.services.db.scalar("SELECT COUNT(*) FROM wa_messages WHERE created_at = ?", (old,)), 0)

    def test_staff_log_shows_no_phone(self) -> None:
        self.say("help", PHONE)
        self.assertEqual(self.client("plain@wa.example").get("/api/channels/whatsapp/log").status, 403)
        status, log = self.client("sup2@wa.example", staff_role="support").get("/api/channels/whatsapp/log")
        self.assertEqual(status, 200)
        self.assertNotIn(DIGITS, canonical_json(log))
        self.assertIn("retention_note", log)


class Webhook(ServicesTestCase):
    def post(self, body: dict, signature: str | None) -> tuple[int, dict]:
        c = Client(self.services)
        if signature is not None:
            c.headers = {"x-taxng-signature": signature}
        return tuple(c.post("/api/channels/whatsapp/webhook", body))  # type: ignore[return-value]

    def test_signature_required(self) -> None:
        body = {"from": PHONE, "text": "PAYE 1m", "message_id": "wamid.1"}
        self.assertEqual(self.post(body, None)[0], 401)
        self.assertEqual(self.post(body, "0" * 64)[0], 401)
        tampered = {**body, "text": "PAYE 9m"}
        self.assertEqual(self.post(tampered, sign_payload(self.services, canonical_json(body)))[0], 401)
        status, ack = self.post(body, "sha256=" + sign_payload(self.services, canonical_json(body)))
        self.assertEqual(status, 200)
        self.assertEqual((ack["status"], ack["kind"], ack["mode"]), ("replied", "paye", "sandbox"))
        self.assertNotIn("reply", ack)
        # Provider retries are acknowledged once.
        status, ack = self.post(body, sign_payload(self.services, canonical_json(body)))
        self.assertEqual(ack["status"], "duplicate")

    def test_signature_uses_channel_key_not_platform_secret(self) -> None:
        from taxng.platform.util import sign

        body = {"from": PHONE, "text": "help"}
        self.assertEqual(self.post(body, sign(self.services.secret, canonical_json(body)))[0], 401)

    def test_bad_phone(self) -> None:
        body = {"from": "not-a-phone", "text": "help"}
        self.assertEqual(self.post(body, sign_payload(self.services, canonical_json(body)))[0], 422)


class DemoDisabled(ServicesTestCase):
    def test_demo_endpoint_404_when_demo_mode_off(self) -> None:
        services = build_services(database=":memory:", data_dir=Path(tempfile.mkdtemp()), demo_mode=False)
        try:
            status, _ = Client(services).post("/api/channels/whatsapp/demo", {"phone": PHONE, "text": "help"})
            self.assertEqual(status, 404)
            _, info = Client(services).get("/api/channels/whatsapp/status")
            self.assertFalse(info["demo_available"])
        finally:
            services.db.close()


class Localisation(ServicesTestCase):
    def test_english_served_and_drafts_not_served(self) -> None:
        anon = self.client()
        status, body = anon.get("/api/i18n")
        self.assertEqual(status, 200)
        self.assertEqual([l["lang"] for l in body["languages"]], ["en"])
        self.assertIn("ha", {l["lang"] for l in body["in_review"]})
        status, en = anon.get("/api/i18n/en")
        self.assertEqual(status, 200)
        self.assertEqual(en["strings"]["nav.academy"], "Academy")
        self.assertEqual(anon.get("/api/i18n/ha").status, 404)
        self.assertEqual(anon.get("/api/i18n/xx").status, 404)

    def test_submit_then_approve_serves_string(self) -> None:
        loc = self.services.modules["channels"].i18n
        draft = loc.catalogues["yo"]["drafts"]["button.sign_in"]
        submitter = self.client("translator@i18n.example", staff_role="support")
        reviewer = self.client("legal@i18n.example", staff_role="legal_reviewer")
        anon = self.client()

        self.assertEqual(self.client("user@i18n.example").post("/api/channels/translations", {"lang": "yo", "key": "button.sign_in", "text": draft}).status, 403)
        self.assertEqual(submitter.post("/api/channels/translations", {"lang": "yo", "key": "no.such", "text": "x"}).status, 422)
        self.assertEqual(submitter.post("/api/channels/translations", {"lang": "en", "key": "button.sign_in", "text": "x"}).status, 422)
        status, sub = submitter.post("/api/channels/translations", {"lang": "yo", "key": "button.sign_in", "text": draft})
        self.assertEqual(status, 201)
        self.assertEqual(anon.get("/api/i18n/yo").status, 404)  # submitted is not approved

        self.assertEqual(submitter.post(f"/api/channels/translations/{sub['id']}/approve").status, 403)  # support cannot approve
        reviewer_own = reviewer.post("/api/channels/translations", {"lang": "yo", "key": "nav.about", "text": "Nipa wa"}).body
        self.assertEqual(reviewer.post(f"/api/channels/translations/{reviewer_own['id']}/approve").status, 409)  # four eyes

        self.assertEqual(reviewer.post(f"/api/channels/translations/{sub['id']}/approve", {"note": "Checked"}).status, 200)
        self.assertEqual(reviewer.post(f"/api/channels/translations/{sub['id']}/approve").status, 409)
        status, yo = anon.get("/api/i18n/yo")
        self.assertEqual(status, 200)
        self.assertEqual(yo["strings"]["button.sign_in"], draft)
        # Other keys fall back to English; unapproved drafts are not served.
        self.assertEqual(yo["strings"]["nav.about"], "About & Ownership")
        self.assertIn("nav.about", yo["fallback_keys"])
        self.assertIn("yo", [l["lang"] for l in anon.get("/api/i18n").body["languages"]])

    def test_translations_may_not_state_figures(self) -> None:
        support = self.client("fig@i18n.example", staff_role="support")
        self.assertEqual(support.post("/api/channels/translations", {"lang": "ha", "key": "button.send", "text": "Aika 5%"}).status, 422)

    def test_content_cannot_mark_translation_approved(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        (tmp / "i18n").mkdir()
        (tmp / "i18n" / "en.yaml").write_text("lang: en\nname: English\nstrings:\n  button.send: Send\n")
        (tmp / "i18n" / "ha.yaml").write_text("lang: ha\nname: Hausa\nstrings:\n  button.send: {text: Aika, status: approved}\n")
        with self.assertRaises(ContentError):
            load_catalogues(tmp)

    def test_guide_summary_translation_workflow(self) -> None:
        editor = self.client("editor@guides.example", staff_role="editor")
        reviewer = self.client("reviewer@guides.example", staff_role="legal_reviewer")
        anon = self.client()
        path = "/api/channels/guide-translations"
        self.assertEqual(anon.get(f"{path}/rent-relief").body["items"], [])
        self.assertEqual(anon.get(f"{path}/nope").status, 404)
        self.assertEqual(editor.post(path, {"guide_id": "nope", "lang": "pcm", "summary": "Something"}).status, 422)
        self.assertEqual(editor.post(path, {"guide_id": "rent-relief", "lang": "pcm", "summary": "Pay 20% less"}).status, 422)
        status, sub = editor.post(path, {"guide_id": "rent-relief", "lang": "pcm", "summary": "If you dey pay rent, you fit remove part of am from your tax, up to one limit every year."})
        self.assertEqual(status, 201)
        self.assertEqual(anon.get(f"{path}/rent-relief").body["items"], [])
        self.assertEqual(anon.get(path).status, 401)
        _, queue = reviewer.get(path, {"status": "submitted"})
        self.assertEqual([q["id"] for q in queue["items"]], [sub["id"]])
        self.assertEqual(editor.post(f"{path}/{sub['id']}/approve").status, 409)  # own submission
        self.assertEqual(reviewer.post(f"{path}/{sub['id']}/approve").status, 200)
        items = anon.get(f"{path}/rent-relief").body["items"]
        self.assertEqual([(i["lang"], i["source"]) for i in items], [("pcm", "review")])

        status, rej = editor.post(path, {"guide_id": "vat-basics", "lang": "ha", "summary": "Bayani kan VAT"})
        self.assertEqual(reviewer.post(f"{path}/{rej['id']}/reject", {"note": "Terminology"}).status, 200)
        self.assertEqual(anon.get(f"{path}/vat-basics").body["items"], [])
