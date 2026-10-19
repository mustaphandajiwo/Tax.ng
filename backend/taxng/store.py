"""Newsletter subscribers (NEWS-03) and first-party analytics events (AN-01, AN-02).

Tables live in the platform schema. Analytics events accept only whitelisted
names and properties, so no personal data can enter the event log. Modules add
their own event names with ``register_events``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any

from .db import Database
from .platform.errors import Invalid
from .platform.util import iso

EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[a-z]{2,}$", re.IGNORECASE)
TOPICS = {"nigerian_tax_brief", "global_tax_watch", "topic_alerts"}

EVENTS: dict[str, set[str]] = {
    "page_view": {"page"},
    "guide_read_to_end": {"guide"},
    "calculator_started": {"calculator"},
    "calculator_completed": {"calculator", "regime"},
    "ai_question_asked": {"confidence", "blocked"},
    "ai_escalated": set(),
    "newsletter_signup": set(),
}


def register_events(events: dict[str, set[str]]) -> None:
    """Modules call this at import time to whitelist their analytics events."""
    for name, props in events.items():
        EVENTS.setdefault(name, set()).update(props)


class StoreError(Invalid):
    pass


class Store:
    def __init__(self, db: Database, secret: str) -> None:
        self.db = db
        self._secret = secret.encode()

    def close(self) -> None:
        self.db.close()

    # ---------------------------------------------------------------- newsletter
    def token_for(self, email: str) -> str:
        return hmac.new(self._secret, email.lower().encode(), hashlib.sha256).hexdigest()[:32]

    def subscribe(self, email: str, *, consent: bool, consent_text: str, topics: list[str] | None = None) -> str:
        email = email.strip().lower()
        if not EMAIL.match(email):
            raise StoreError("email: enter a valid email address")
        if consent is not True:
            raise StoreError("consent: explicit consent is required")
        chosen = sorted(set(topics or ["nigerian_tax_brief"]) & TOPICS) or ["nigerian_tax_brief"]
        self.db.execute(
            "INSERT INTO subscribers (email, topics, consent_text, consented_at, unsubscribed_at) "
            "VALUES (?, ?, ?, ?, NULL) ON CONFLICT(email) DO UPDATE SET topics=excluded.topics, "
            "consent_text=excluded.consent_text, consented_at=excluded.consented_at, unsubscribed_at=NULL",
            (email, ",".join(chosen), consent_text, iso()),
        )
        return self.token_for(email)

    def unsubscribe(self, email: str, token: str) -> bool:
        email = email.strip().lower()
        if not hmac.compare_digest(self.token_for(email), token):
            return False
        cur = self.db.execute(
            "UPDATE subscribers SET unsubscribed_at=? WHERE email=? AND unsubscribed_at IS NULL", (iso(), email)
        )
        return cur.rowcount == 1

    def is_subscribed(self, email: str) -> bool:
        return (
            self.db.one("SELECT 1 FROM subscribers WHERE email=? AND unsubscribed_at IS NULL", (email.strip().lower(),))
            is not None
        )

    def subscribers(self, topic: str) -> list[str]:
        rows = self.db.query("SELECT email, topics FROM subscribers WHERE unsubscribed_at IS NULL")
        return [r["email"] for r in rows if topic in r["topics"].split(",")]

    # ---------------------------------------------------------------- analytics
    def record_event(self, name: str, props: dict[str, Any] | None = None) -> None:
        if name not in EVENTS:
            raise StoreError(f"event: unknown event {name!r}")
        allowed = EVENTS[name]
        clean = {k: str(v)[:64] for k, v in (props or {}).items() if k in allowed}
        self.db.insert("events", {"name": name, "props": json.dumps(clean, sort_keys=True), "created_at": iso()})

    def event_counts(self) -> dict[str, int]:
        rows = self.db.query("SELECT name, COUNT(*) AS n FROM events GROUP BY name")
        return {r["name"]: r["n"] for r in rows}

    def subscriber_count(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM subscribers WHERE unsubscribed_at IS NULL") or 0)
