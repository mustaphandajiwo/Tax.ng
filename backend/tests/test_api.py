"""API contract through ``dispatch`` (framework-free) plus content integrity."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from taxng.api.handlers import Request, dispatch
from taxng.config import CONTENT_DIR
from taxng.legal import ContentError, Library
from taxng.db import Database
from taxng.store import Store

from .helpers import make_services


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.s = make_services()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.s.db.close()

    def call(self, method: str, path: str, body: dict | None = None, query: dict | None = None):
        return dispatch(self.s, Request(method, path, query or {}, body or {}))

    def test_file_and_pay_hidden_until_filing_is_authorised(self) -> None:
        status, body = self.call("GET", "/api/meta")
        self.assertEqual(status, 200)
        labels = [n["label"] for n in body["nav"]]
        self.assertNotIn("File & Pay", labels)  # PRD section 5: only once an authorised filing adapter is live
        self.assertIn("Check My Tax Health", labels)
        self.assertEqual(body["owner"], "Astound Innovation Hub")

    def test_calculate_and_validation(self) -> None:
        status, body = self.call("POST", "/api/calculate/pit", {"annual_gross_income": 3_000_000, "tax_year": 2026})
        self.assertEqual((status, body["outputs"]["annual_tax"]), (200, "330000.00"))
        status, body = self.call("POST", "/api/calculate/pit", {})
        self.assertEqual(status, 422)
        self.assertIn("annual_gross_income", body["fields"])

    def test_unknown_routes_and_methods(self) -> None:
        self.assertEqual(self.call("POST", "/api/calculate/nope", {})[0], 404)
        self.assertEqual(self.call("GET", "/api/calculate/pit")[0], 405)
        self.assertEqual(self.call("GET", "/api/laws/does.not.exist")[0], 404)

    def test_law_shows_engine_values(self) -> None:
        status, body = self.call("GET", "/api/laws/nta2025.vat.rate", query={"on": "2026-06-01"})
        self.assertEqual(status, 200)
        self.assertEqual(body["parameters"][0]["value"], "0.075")

    def test_newsletter_requires_consent(self) -> None:
        status, body = self.call("POST", "/api/newsletter/subscribe", {"email": "a@example.com"})
        self.assertEqual(status, 422)
        self.assertIn("consent", body["fields"])
        status, _ = self.call("POST", "/api/newsletter/subscribe", {"email": "a@example.com", "consent": True})
        self.assertEqual(status, 201)

    def test_events_whitelist(self) -> None:
        self.assertEqual(self.call("POST", "/api/events", {"name": "calculator_completed", "props": {"calculator": "pit"}})[0], 202)
        self.assertEqual(self.call("POST", "/api/events", {"name": "steal_data"})[0], 422)


class StoreTests(unittest.TestCase):
    def test_unsubscribe_needs_valid_token(self) -> None:
        db = Database(":memory:")
        db.migrate()
        store = Store(db, "secret")
        self.addCleanup(store.close)
        token = store.subscribe("b@example.com", consent=True, consent_text="ok")
        self.assertFalse(store.unsubscribe("b@example.com", "wrong"))
        self.assertTrue(store.unsubscribe("b@example.com", token))
        self.assertFalse(store.is_subscribed("b@example.com"))

    def test_event_props_are_filtered(self) -> None:
        db = Database(":memory:")
        db.migrate()
        store = Store(db, "secret")
        self.addCleanup(store.close)
        store.record_event("calculator_completed", {"calculator": "pit", "email": "leak@example.com"})
        row = store.db.one("SELECT props FROM events")
        self.assertNotIn("leak", row["props"])


class ContentIntegrity(unittest.TestCase):
    def test_content_with_a_figure_is_rejected(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        provisions = yaml.safe_load((CONTENT_DIR / "provisions.yaml").read_text())
        provisions[0]["summary"] = "The rate is 15% for everyone."
        (tmp / "provisions.yaml").write_text(yaml.safe_dump(provisions))
        for name in ("guides.yaml", "news.yaml"):
            (tmp / name).write_text((CONTENT_DIR / name).read_text())
        services = make_services()
        self.addCleanup(services.db.close)
        with self.assertRaises(ContentError):
            Library.load(tmp, services.tree)


if __name__ == "__main__":
    unittest.main()
