"""AI-04: account-aware Tax AI is opt-in, scoped, audited and still guarded."""

from __future__ import annotations

from .helpers import ServicesTestCase, create_org


class AccountAccess(ServicesTestCase):
    def test_requires_sign_in_and_explicit_permission(self) -> None:
        self.assertEqual(self.client().post("/api/ask/account", {"question": "What do I owe?"}).status, 401)
        user = self.client("ai-user@example.com")
        status, body = user.post("/api/ask/account", {"question": "What are my obligations?"})
        self.assertEqual(status, 403)
        self.assertIn("Account settings", body["message"])

    def test_answer_uses_own_data_and_is_audited(self) -> None:
        user = self.client("ai-owner@example.com")
        user.post("/api/me", {"ai_account_access": True})
        org = create_org(user, "Kano Traders Ltd")
        status, body = user.post("/api/ask/account", {"question": "What do I need to file next?", "org_id": org})
        self.assertEqual(status, 200)
        self.assertTrue(body["account_used"])
        self.assertFalse(body["blocked"])
        self.assertIn("get_account_summary", [c["name"] for c in body["tool_calls"]])
        actions = [e["action"] for e in self.services.audit.events(entity_id=user.user_id)]
        self.assertIn("ai.account_access", actions)

    def test_cannot_read_another_organisation(self) -> None:
        owner = self.client("ai-org-owner@example.com")
        other = self.client("ai-snoop@example.com")
        other.post("/api/me", {"ai_account_access": True})
        org = create_org(owner, "Private Ltd")
        status, _ = other.post("/api/ask/account", {"question": "What does this company owe?", "org_id": org})
        self.assertEqual(status, 404)

    def test_revoking_permission_stops_access(self) -> None:
        user = self.client("ai-revoke@example.com")
        user.post("/api/me", {"ai_account_access": True})
        self.assertEqual(user.post("/api/ask/account", {"question": "What is my position?"}).status, 200)
        user.post("/api/me", {"ai_account_access": False})
        self.assertEqual(user.post("/api/ask/account", {"question": "What is my position?"}).status, 403)
