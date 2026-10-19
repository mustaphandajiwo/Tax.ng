"""Passwordless sign-in with one-time codes, and server-side sessions.

* ``request_code`` emails a six-digit code (hashed at rest, 10 minute expiry,
  five attempts, five codes per hour per address).
* ``verify_code`` creates the user on first sign-in and opens a session.
* Session tokens are random; only their SHA-256 is stored. The token travels
  in an HttpOnly, SameSite=Lax cookie. State-changing requests that carry the
  cookie must also send ``X-Requested-With: taxng`` (CSRF guard, router.py).
"""

from __future__ import annotations

import datetime as dt
import re
import secrets
from typing import Any

from ..db import Database
from .errors import Invalid
from .notify import Notifier
from .util import iso, new_id, now, parse_iso, sha256, sign

EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[a-z]{2,}$", re.IGNORECASE)
CODE_TTL = dt.timedelta(minutes=10)
SESSION_TTL = dt.timedelta(hours=12)
MAX_ATTEMPTS = 5
MAX_CODES_PER_HOUR = 5
SESSION_COOKIE = "taxng_session"


class AuthError(Invalid):
    """Field-scoped auth error, formatted ``field: message``."""


class AuthService:
    def __init__(self, db: Database, notifier: Notifier, secret: str, *, admin_emails: set[str] | None = None) -> None:
        self.db = db
        self.notifier = notifier
        self.secret = secret
        self.admin_emails = {e.lower() for e in (admin_emails or set())}

    def _code_hash(self, email: str, code: str) -> str:
        return sign(self.secret, f"otp:{email}:{code}")

    def request_code(self, email: str) -> None:
        email = email.strip().lower()
        if not EMAIL.match(email):
            raise AuthError("email: enter a valid email address")
        since = iso(now() - dt.timedelta(hours=1))
        recent = self.db.scalar("SELECT COUNT(*) FROM otp_codes WHERE email = ? AND created_at > ?", (email, since))
        if recent >= MAX_CODES_PER_HOUR:
            raise AuthError("email: too many codes requested; try again later")
        code = f"{secrets.randbelow(10**6):06d}"
        self.db.insert(
            "otp_codes",
            {
                "id": new_id("otp"),
                "email": email,
                "code_hash": self._code_hash(email, code),
                "created_at": iso(),
                "expires_at": iso(now() + CODE_TTL),
            },
        )
        self.notifier.send(
            "email",
            email,
            f"Your tax.ng sign-in code is {code}. It expires in 10 minutes. If you did not ask for it, ignore this email.",
            subject="Your tax.ng sign-in code",
        )

    def verify_code(self, email: str, code: str) -> tuple[str, dict[str, Any]]:
        email = email.strip().lower()
        row = self.db.one(
            "SELECT * FROM otp_codes WHERE email = ? AND used_at IS NULL ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (email,),
        )
        if row is None or parse_iso(row["expires_at"]) < now():
            raise AuthError("code: the code has expired; request a new one")
        if row["attempts"] >= MAX_ATTEMPTS:
            raise AuthError("code: too many attempts; request a new one")
        self.db.update("otp_codes", {"attempts": row["attempts"] + 1}, "id = ?", (row["id"],))
        if not secrets.compare_digest(row["code_hash"], self._code_hash(email, code.strip())):
            raise AuthError("code: that code is not right")
        self.db.update("otp_codes", {"used_at": iso()}, "id = ?", (row["id"],))

        user = self.db.one("SELECT * FROM users WHERE email = ?", (email,))
        if user is None:
            user_id = new_id("usr")
            self.db.insert(
                "users",
                {
                    "id": user_id,
                    "email": email,
                    "staff_role": "admin" if email in self.admin_emails else "none",
                    "created_at": iso(),
                },
            )
            user = self.db.one("SELECT * FROM users WHERE id = ?", (user_id,))
        assert user is not None
        self.db.update("users", {"last_login_at": iso()}, "id = ?", (user["id"],))
        return self.open_session(user["id"]), user

    def open_session(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        self.db.insert(
            "sessions",
            {"token_hash": sha256(token), "user_id": user_id, "created_at": iso(), "expires_at": iso(now() + SESSION_TTL)},
        )
        return token

    def user_for_token(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        row = self.db.one(
            "SELECT u.* , s.expires_at AS session_expires FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash = ? AND s.revoked_at IS NULL",
            (sha256(token),),
        )
        if row is None or parse_iso(row["session_expires"]) < now():
            return None
        return row

    def revoke(self, token: str) -> None:
        self.db.update("sessions", {"revoked_at": iso()}, "token_hash = ?", (sha256(token),))
