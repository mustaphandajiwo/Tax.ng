"""Developer platform (Phase 4): API keys, rate limiting, idempotency and outbound webhooks.

API keys
    ``tng_test_<prefix>_<secret>``. Only a keyed hash (HMAC with the platform
    secret) is stored; the full key is shown once at creation. The prefix
    identifies the key in lists and logs.

    An API-key principal never carries organisation memberships and its
    ``user_id`` is the key id, so session routes that use ``require_org`` or
    filter personal data by ``user_id`` see nothing. Keys act only through
    ``/api/v1`` (public_api.py), where the key's own organisation is used.

Rate limiting
    Token bucket per key, in process memory: capacity = the key's
    ``rate_per_minute``, refilled continuously at that rate. One bucket per
    process, so with several workers the effective limit is multiplied;
    production moves this to the API gateway or a shared store (Redis).

Webhooks
    Deliveries are written to ``webhook_deliveries`` with an
    ``X-TaxNG-Signature: t=<unix>,v1=<hmac_sha256(secret, "<t>.<body>")>``
    header and a retry schedule. The sandbox adapter sends nothing.
"""

from __future__ import annotations

import hmac
import ipaddress
import json
import logging
import re
import secrets
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from ...platform.access import NotFoundError, Principal
from ...platform.adapters import Adapter
from ...platform.errors import Conflict, Invalid
from ...platform.util import canonical_json, iso, new_id, sign

if TYPE_CHECKING:
    from ...services import Services

log = logging.getLogger("taxng.developer")

SCOPES: dict[str, str] = {
    "calculators:read": "Run the tax calculators",
    "rules:read": "Read effective-dated rules parameters",
    "einvoices:read": "Read e-invoices and their status",
    "einvoices:write": "Create and submit e-invoices",
}
WEBHOOK_EVENTS: dict[str, str] = {
    "einvoice.submitted": "An e-invoice was submitted to NRS",
    "einvoice.accepted": "NRS accepted an e-invoice",
    "einvoice.rejected": "NRS rejected an e-invoice",
    "return.submitted": "A tax return was submitted for review",
    "return.approved": "A tax return was approved",
    "return.filed": "A tax return was filed",
    "payment.paid": "A commercial payment to tax.ng was confirmed",
    "erp.import.completed": "An ERP import finished",
}
DEFAULT_RATE_PER_MINUTE = 60
MAX_RATE_PER_MINUTE = 600
# Seconds after the first attempt at which a failed delivery is retried.
RETRY_SCHEDULE_SECONDS = (0, 60, 300, 1800, 7200, 43200)
SIGNATURE_TOLERANCE_SECONDS = 300
TOKEN_RE = re.compile(r"^tng_(test|live)_([0-9a-f]{10})_([0-9a-f]{40})$")


class TokenBucket:
    """In-memory token bucket keyed by API key id. Thread-safe within one process."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._state: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def take(self, key: str, per_minute: int) -> tuple[bool, int, int]:
        """Returns (allowed, remaining, retry_after_seconds)."""
        rate = per_minute / 60.0
        with self._lock:
            now = self.clock()
            tokens, last = self._state.get(key, (float(per_minute), now))
            tokens = min(float(per_minute), tokens + (now - last) * rate)
            if tokens >= 1:
                self._state[key] = (tokens - 1, now)
                return True, int(tokens - 1), 0
            self._state[key] = (tokens, now)
            return False, 0, max(1, int((1 - tokens) / rate + 0.999))


def signature_header(secret: str, body: str, timestamp: int) -> str:
    return f"t={timestamp},v1={sign(secret, f'{timestamp}.{body}')}"


def verify_webhook_signature(secret: str, header: str, body: str, *, now: int | None = None, tolerance: int = SIGNATURE_TOLERANCE_SECONDS) -> bool:
    """What a receiver runs on ``X-TaxNG-Signature``. Rejects bad MACs and stale timestamps."""
    parts = dict(p.split("=", 1) for p in (header or "").split(",") if "=" in p)
    try:
        ts = int(parts.get("t", ""))
    except ValueError:
        return False
    if abs((now if now is not None else int(time.time())) - ts) > tolerance:
        return False
    return hmac.compare_digest(sign(secret, f"{ts}.{body}"), parts.get("v1", ""))


def _check_url(url: str) -> str:
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise Invalid("url: must be an https:// URL")
    if len(url) > 500:
        raise Invalid("url: keep it under 500 characters")
    host = parsed.hostname.lower()
    if host in ("localhost",) or host.endswith((".local", ".internal", ".localhost")):
        raise Invalid("url: must be a public host")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return url
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
        raise Invalid("url: must be a public host")
    return url


class Developer:
    """``services.modules["developer"]``."""

    def __init__(self, services: Services, clock: Callable[[], float] = time.monotonic) -> None:
        self.services = services
        self.db = services.db
        self.limiter = TokenBucket(clock)

    @property
    def delivery(self) -> Adapter:
        return self.services.adapters.get("webhook_delivery")

    @property
    def key_mode(self) -> str:
        """Keys issued while e-invoicing runs in sandbox are test keys."""
        return "live" if self.services.adapters.is_authorised("einvoicing") else "test"

    # ------------------------------------------------------------ API keys
    def _hash(self, token: str) -> str:
        return sign(self.services.secret, f"api-key:{token}")

    def create_key(self, org_id: str, actor_id: str, name: str, scopes: Any, rate_per_minute: Any = None) -> dict[str, Any]:
        name = str(name or "").strip()
        if not 1 <= len(name) <= 80:
            raise Invalid("name: give the key a name of up to 80 characters")
        if not isinstance(scopes, list) or not scopes:
            raise Invalid("scopes: choose at least one scope")
        unknown = [s for s in scopes if s not in SCOPES]
        if unknown:
            raise Invalid(f"scopes: unknown scope {unknown[0]}")
        rate = DEFAULT_RATE_PER_MINUTE if rate_per_minute in (None, "") else rate_per_minute
        if not isinstance(rate, int) or isinstance(rate, bool) or not 1 <= rate <= MAX_RATE_PER_MINUTE:
            raise Invalid(f"rate_per_minute: must be a whole number from 1 to {MAX_RATE_PER_MINUTE}")
        prefix = secrets.token_hex(5)
        token = f"tng_{self.key_mode}_{prefix}_{secrets.token_hex(20)}"
        key_id = new_id("key")
        row = {
            "id": key_id,
            "org_id": org_id,
            "name": name,
            "prefix": f"tng_{self.key_mode}_{prefix}",
            "key_hash": self._hash(token),
            "scopes": " ".join(sorted(set(scopes))),
            "rate_per_minute": rate,
            "mode": "sandbox" if self.key_mode == "test" else "production",
            "created_by": actor_id,
            "created_at": iso(),
        }
        self.db.insert("api_keys", row)
        self.services.audit.record("api_key.create", "api_key", key_id, actor_id=actor_id, org_id=org_id, data={"scopes": row["scopes"], "prefix": row["prefix"]})
        return {**self.key_view(row), "token": token, "token_notice": "Copy this key now. It is shown only once."}

    def key_view(self, row: dict[str, Any]) -> dict[str, Any]:
        keys = ("id", "org_id", "name", "prefix", "rate_per_minute", "mode", "created_at", "last_used_at", "revoked_at")
        return {**{k: row.get(k) for k in keys}, "scopes": row["scopes"].split()}

    def list_keys(self, org_id: str) -> list[dict[str, Any]]:
        return [self.key_view(r) for r in self.db.query("SELECT * FROM api_keys WHERE org_id = ? ORDER BY created_at DESC, rowid DESC", (org_id,))]

    def revoke_key(self, org_id: str, key_id: str, actor_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM api_keys WHERE id = ? AND org_id = ?", (key_id, org_id))
        if row is None:
            raise NotFoundError("API key not found")
        if row["revoked_at"]:
            raise Conflict("This key is already revoked")
        self.db.update("api_keys", {"revoked_at": iso(), "revoked_by": actor_id}, "id = ?", (key_id,))
        self.services.audit.record("api_key.revoke", "api_key", key_id, actor_id=actor_id, org_id=org_id, data={"prefix": row["prefix"]})
        return self.key_view({**row, "revoked_at": iso()})

    def key_row(self, key_id: str) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM api_keys WHERE id = ? AND revoked_at IS NULL", (key_id,))

    def resolve(self, services: Services, token: str) -> Principal | None:
        """``services.hooks["api_key"]``: bearer token -> Principal, or None if unknown or revoked."""
        match = TOKEN_RE.match(token or "")
        if not match:
            return None
        row = self.db.one("SELECT * FROM api_keys WHERE prefix = ?", (f"tng_{match.group(1)}_{match.group(2)}",))
        if row is None or row["revoked_at"] or not hmac.compare_digest(row["key_hash"], self._hash(token)):
            return None
        self.db.update("api_keys", {"last_used_at": iso()}, "id = ?", (row["id"],))
        return Principal(
            user_id=row["id"],
            email="",
            name=f"API key {row['name']}",
            staff_role="none",
            ai_account_access=False,
            memberships={},
            via="api_key",
            scopes=tuple(row["scopes"].split()),
        )

    # --------------------------------------------------------- idempotency
    def idempotent_lookup(self, key_id: str, idem_key: str) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM api_idempotency WHERE key_id = ? AND idem_key = ?", (key_id, idem_key))

    def idempotent_store(self, key_id: str, idem_key: str, request_hash: str, status: int, body: Any) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO api_idempotency (key_id, idem_key, request_hash, status, response_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (key_id, idem_key, request_hash, status, json.dumps(body), iso()),
        )

    # ------------------------------------------------------------ webhooks
    def add_endpoint(self, org_id: str, actor_id: str, url: Any, events: Any) -> dict[str, Any]:
        url = _check_url(str(url or ""))
        if not isinstance(events, list) or not events:
            raise Invalid("events: choose at least one event")
        unknown = [e for e in events if e not in WEBHOOK_EVENTS and e != "*"]
        if unknown:
            raise Invalid(f"events: unknown event {unknown[0]}")
        if int(self.db.scalar("SELECT COUNT(*) FROM webhook_endpoints WHERE org_id = ? AND active = 1", (org_id,)) or 0) >= 10:
            raise Conflict("At most 10 active endpoints per organisation")
        endpoint_id = new_id("whe")
        row = {
            "id": endpoint_id,
            "org_id": org_id,
            "url": url,
            "events": " ".join(sorted(set(events))),
            "secret": "whsec_" + secrets.token_hex(24),
            "created_by": actor_id,
            "created_at": iso(),
        }
        self.db.insert("webhook_endpoints", row)
        self.services.audit.record("webhook.endpoint_create", "webhook_endpoint", endpoint_id, actor_id=actor_id, org_id=org_id, data={"events": row["events"]})
        return {**self.endpoint_view({**row, "active": 1, "disabled_at": None}), "secret": row["secret"], "secret_notice": "Copy this signing secret now. It is shown only once."}

    def endpoint_view(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "url": row["url"],
            "events": row["events"].split(),
            "active": bool(row["active"]),
            "secret_hint": "whsec_..." + row["secret"][-4:],
            "created_at": row["created_at"],
            "disabled_at": row["disabled_at"],
        }

    def list_endpoints(self, org_id: str) -> list[dict[str, Any]]:
        return [self.endpoint_view(r) for r in self.db.query("SELECT * FROM webhook_endpoints WHERE org_id = ? ORDER BY created_at DESC, rowid DESC", (org_id,))]

    def disable_endpoint(self, org_id: str, endpoint_id: str, actor_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM webhook_endpoints WHERE id = ? AND org_id = ?", (endpoint_id, org_id))
        if row is None:
            raise NotFoundError("Endpoint not found")
        self.db.update("webhook_endpoints", {"active": 0, "disabled_at": iso()}, "id = ?", (endpoint_id,))
        self.services.audit.record("webhook.endpoint_disable", "webhook_endpoint", endpoint_id, actor_id=actor_id, org_id=org_id)
        return self.endpoint_view({**row, "active": 0, "disabled_at": iso()})

    def _attempt(self, endpoint: dict[str, Any], body: str, event_id: str, event: str) -> tuple[str, dict[str, Any], str]:
        ts = int(time.time())
        signature = signature_header(endpoint["secret"], body, ts)
        headers = {
            "Content-Type": "application/json",
            "X-TaxNG-Event": event,
            "X-TaxNG-Delivery": event_id,
            "X-TaxNG-Signature": signature,
        }
        result = self.delivery.deliver(endpoint["url"], headers, body)  # type: ignore[attr-defined]
        return signature, result, iso()

    def emit(self, org_id: str, event: str, payload: dict[str, Any]) -> list[str]:
        """For other modules. Never raises: a webhook problem must not break the caller."""
        try:
            endpoints = [
                e
                for e in self.db.query("SELECT * FROM webhook_endpoints WHERE org_id = ? AND active = 1", (org_id,))
                if event in e["events"].split() or "*" in e["events"].split()
            ]
            if not endpoints:
                return []
            event_id = new_id("evt")
            envelope = {"id": event_id, "type": event, "created_at": iso(), "org_id": org_id, "data": payload, "mode": self.delivery.mode}
            body = canonical_json(envelope)
            ids = []
            for endpoint in endpoints:
                signature, result, at = self._attempt(endpoint, body, event_id, event)
                delivery_id = new_id("whd")
                self.db.insert(
                    "webhook_deliveries",
                    {
                        "id": delivery_id,
                        "endpoint_id": endpoint["id"],
                        "org_id": org_id,
                        "event_id": event_id,
                        "event": event,
                        "body": body,
                        "signature": signature,
                        "status": result["status"],
                        "attempts": 1,
                        "schedule_json": json.dumps(list(RETRY_SCHEDULE_SECONDS)),
                        "next_attempt_at": None,
                        "last_attempt_at": at,
                        "mode": result["mode"],
                        "created_at": at,
                    },
                )
                ids.append(delivery_id)
            return ids
        except Exception:  # noqa: BLE001
            log.exception("webhook emit failed for %s", event)
            return []

    def delivery_view(self, row: dict[str, Any], endpoint_url: str | None = None) -> dict[str, Any]:
        return {
            "id": row["id"],
            "endpoint_id": row["endpoint_id"],
            "endpoint_url": endpoint_url,
            "event_id": row["event_id"],
            "event": row["event"],
            "status": row["status"],
            "attempts": row["attempts"],
            "retry_schedule_seconds": json.loads(row["schedule_json"]),
            "last_attempt_at": row["last_attempt_at"],
            "headers": {"X-TaxNG-Event": row["event"], "X-TaxNG-Delivery": row["event_id"], "X-TaxNG-Signature": row["signature"]},
            "body": row["body"],
            "mode": row["mode"],
            "created_at": row["created_at"],
        }

    def deliveries(self, org_id: str, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT d.*, e.url AS endpoint_url FROM webhook_deliveries d JOIN webhook_endpoints e ON e.id = d.endpoint_id "
            "WHERE d.org_id = ? ORDER BY d.created_at DESC, d.rowid DESC LIMIT ?",
            (org_id, limit),
        )
        return [self.delivery_view(r, r["endpoint_url"]) for r in rows]

    def replay(self, org_id: str, delivery_id: str, actor_id: str) -> dict[str, Any]:
        """Re-sends the same event (same event id and body), freshly signed. Receivers dedupe on the event id."""
        row = self.db.one("SELECT * FROM webhook_deliveries WHERE id = ? AND org_id = ?", (delivery_id, org_id))
        if row is None:
            raise NotFoundError("Delivery not found")
        endpoint = self.db.one("SELECT * FROM webhook_endpoints WHERE id = ? AND org_id = ?", (row["endpoint_id"], org_id))
        if endpoint is None or not endpoint["active"]:
            raise Conflict("The endpoint is disabled")
        signature, result, at = self._attempt(endpoint, row["body"], row["event_id"], row["event"])
        self.db.update(
            "webhook_deliveries",
            {"signature": signature, "status": result["status"], "attempts": row["attempts"] + 1, "last_attempt_at": at, "mode": result["mode"]},
            "id = ?",
            (delivery_id,),
        )
        self.services.audit.record("webhook.replay", "webhook_delivery", delivery_id, actor_id=actor_id, org_id=org_id)
        fresh = self.db.one("SELECT * FROM webhook_deliveries WHERE id = ?", (delivery_id,))
        return self.delivery_view(fresh or row, endpoint["url"])
