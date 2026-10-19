"""Test helpers shared by platform and module tests.

    services = make_services()                 # fresh in-memory database
    alice = Client(services).sign_in("alice@example.com")
    status, body = alice.post("/api/orgs", {"name": "Acme"})
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from taxng.api.router import CSRF_VALUE, Reply, Request, dispatch
from taxng.platform.auth import SESSION_COOKIE
from taxng.services import Services, build_services


def make_services() -> Services:
    return build_services(database=":memory:", data_dir=Path(tempfile.mkdtemp()), demo_mode=True)


class Client:
    """Calls ``dispatch`` the way the browser app does (cookie + CSRF header)."""

    def __init__(self, services: Services) -> None:
        self.services = services
        self.cookies: dict[str, str] = {}
        self.headers: dict[str, str] = {}

    def request(self, method: str, path: str, body: dict[str, Any] | None = None, query: dict[str, str] | None = None) -> Reply:
        headers = dict(self.headers)
        if self.cookies:
            headers["x-requested-with"] = CSRF_VALUE
        reply = dispatch(self.services, Request(method, path, query or {}, body or {}, headers, dict(self.cookies)))
        for c in reply.cookies:
            if c.max_age == 0:
                self.cookies.pop(c.name, None)
            else:
                self.cookies[c.name] = c.value
        return reply

    def get(self, path: str, query: dict[str, str] | None = None) -> Reply:
        return self.request("GET", path, query=query)

    def post(self, path: str, body: dict[str, Any] | None = None) -> Reply:
        return self.request("POST", path, body)

    def put(self, path: str, body: dict[str, Any] | None = None) -> Reply:
        return self.request("PUT", path, body)

    def delete(self, path: str) -> Reply:
        return self.request("DELETE", path)

    def sign_in(self, email: str, *, staff_role: str | None = None) -> Client:
        """Signs in through the real OTP flow, reading the code from the outbox."""
        assert self.post("/api/auth/request-code", {"email": email}).status == 202
        body = self.services.notifier.recent(email.lower(), limit=1)[0]["body"]
        code = next(word for word in body.replace(".", " ").split() if word.isdigit() and len(word) == 6)
        reply = self.post("/api/auth/verify", {"email": email, "code": code})
        assert reply.status == 200, reply.body
        if staff_role:
            self.services.db.update("users", {"staff_role": staff_role}, "email = ?", (email.lower(),))
        return self

    @property
    def user_id(self) -> str:
        return self.get("/api/me").body["id"]


def create_org(client: Client, name: str = "Acme Ltd", **profile: Any) -> str:
    """Creates an organisation directly (the workspace module owns the HTTP route)."""
    from taxng.platform.util import iso, new_id

    services = client.services
    org_id = new_id("org")
    services.db.insert(
        "organisations",
        {"id": org_id, "name": name, "created_by": client.user_id, "created_at": iso(), "profile_json": __import__("json").dumps(profile)},
    )
    services.db.insert("memberships", {"org_id": org_id, "user_id": client.user_id, "role": "owner", "created_at": iso()})
    return org_id


def add_member(services: Services, org_id: str, client: Client, role: str) -> None:
    from taxng.platform.util import iso

    services.db.insert("memberships", {"org_id": org_id, "user_id": client.user_id, "role": role, "created_at": iso()})


class ServicesTestCase(unittest.TestCase):
    """Fresh services per test class, closed afterwards."""

    services: Services

    @classmethod
    def setUpClass(cls) -> None:
        cls.services = make_services()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.services.db.close()

    def client(self, email: str | None = None, **kw: Any) -> Client:
        c = Client(self.services)
        return c.sign_in(email, **kw) if email else c


__all__ = ["Client", "ServicesTestCase", "SESSION_COOKIE", "add_member", "create_org", "make_services"]
