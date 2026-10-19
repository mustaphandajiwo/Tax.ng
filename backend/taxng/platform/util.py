"""Small shared helpers: ids, clocks, hashing, masking."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import secrets
from typing import Any


def new_id(prefix: str) -> str:
    """Opaque, non-sequential identifier, e.g. ``org_3f9c...``."""
    return f"{prefix}_{secrets.token_hex(10)}"


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(moment: dt.datetime | None = None) -> str:
    return (moment or now()).isoformat(timespec="seconds")


def parse_iso(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def sign(secret: str, message: str) -> str:
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def verify_signature(secret: str, message: str, signature: str) -> bool:
    return hmac.compare_digest(sign(secret, message), signature or "")


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def mask(identifier: str, visible: int = 4) -> str:
    """Show only the last ``visible`` characters of an identifier."""
    clean = identifier.strip()
    if len(clean) <= visible:
        return "*" * len(clean)
    return "*" * (len(clean) - visible) + clean[-visible:]
