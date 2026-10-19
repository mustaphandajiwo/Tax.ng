"""Newsletter subscribers (NEWS-03) and first-party analytics events (AN-01, AN-02).

SQLite stands in for PostgreSQL in the demo (docs/DECISIONS.md, D5). Analytics
events accept only whitelisted names and properties, so no personal data can
enter the event log.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[a-z]{2,}$", re.IGNORECASE)
TOPICS = {"nigerian_tax_brief"}

EVENTS: dict[str, set[str]] = {
    "page_view": {"page"},
    "guide_read_to_end": {"guide"},
    "calculator_started": {"calculator"},
    "calculator_completed": {"calculator", "regime"},
    "ai_question_asked": {"confidence", "blocked"},
    "ai_escalated": set(),
    "newsletter_signup": set(),
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS subscribers (
    email TEXT PRIMARY KEY,
    topics TEXT NOT NULL,
    consent_text TEXT NOT NULL,
    consented_at TEXT NOT NULL,
    unsubscribed_at TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    props TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class StoreError(ValueError):
    pass


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, database: str, secret: str) -> None:
        if database != ":memory:":
            Path(database).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(database, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._lock = threading.Lock()
        self._secret = secret.encode()

    def close(self) -> None:
        self._conn.close()

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
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO subscribers (email, topics, consent_text, consented_at, unsubscribed_at) "
                "VALUES (?, ?, ?, ?, NULL) ON CONFLICT(email) DO UPDATE SET topics=excluded.topics, "
                "consent_text=excluded.consent_text, consented_at=excluded.consented_at, unsubscribed_at=NULL",
                (email, ",".join(chosen), consent_text, _now()),
            )
        return self.token_for(email)

    def unsubscribe(self, email: str, token: str) -> bool:
        email = email.strip().lower()
        if not hmac.compare_digest(self.token_for(email), token):
            return False
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE subscribers SET unsubscribed_at=? WHERE email=? AND unsubscribed_at IS NULL", (_now(), email)
            )
        return cur.rowcount == 1

    def is_subscribed(self, email: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM subscribers WHERE email=? AND unsubscribed_at IS NULL", (email.strip().lower(),)
        ).fetchone()
        return row is not None

    # ---------------------------------------------------------------- analytics
    def record_event(self, name: str, props: dict[str, Any] | None = None) -> None:
        if name not in EVENTS:
            raise StoreError(f"event: unknown event {name!r}")
        allowed = EVENTS[name]
        clean = {k: str(v)[:64] for k, v in (props or {}).items() if k in allowed}
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO events (name, props, created_at) VALUES (?, ?, ?)",
                (name, json.dumps(clean, sort_keys=True), _now()),
            )

    def event_counts(self) -> dict[str, int]:
        rows = self._conn.execute("SELECT name, COUNT(*) FROM events GROUP BY name").fetchall()
        return {name: count for name, count in rows}

    def subscriber_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM subscribers WHERE unsubscribed_at IS NULL").fetchone()
        return int(row[0])
