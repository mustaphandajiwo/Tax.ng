"""Append-only, hash-chained audit trail (ADR-09, Annex A4).

Each event's hash covers the previous event's hash and the event's canonical
content, so editing or removing any row breaks ``verify()``. Database triggers
also reject UPDATE and DELETE on the table.
"""

from __future__ import annotations

from typing import Any

from ..db import Database
from .util import canonical_json, iso, sha256

GENESIS = "0" * 64


class AuditLog:
    def __init__(self, db: Database) -> None:
        self.db = db

    def record(
        self,
        action: str,
        entity: str,
        entity_id: str | None = None,
        *,
        actor_id: str | None = None,
        org_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> str:
        with self.db.transaction():
            prev = self.db.scalar("SELECT hash FROM audit_events ORDER BY seq DESC LIMIT 1") or GENESIS
            at = iso()
            body = canonical_json(data or {})
            digest = sha256(canonical_json([prev, at, actor_id, org_id, action, entity, entity_id, body]))
            self.db.insert(
                "audit_events",
                {
                    "at": at,
                    "actor_id": actor_id,
                    "org_id": org_id,
                    "action": action,
                    "entity": entity,
                    "entity_id": entity_id,
                    "data_json": body,
                    "prev_hash": prev,
                    "hash": digest,
                },
            )
        return digest

    def events(self, *, org_id: str | None = None, entity_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        sql = "SELECT seq, at, actor_id, org_id, action, entity, entity_id, data_json, hash FROM audit_events WHERE 1=1"
        params: list[Any] = []
        if org_id is not None:
            sql += " AND org_id = ?"
            params.append(org_id)
        if entity_id is not None:
            sql += " AND entity_id = ?"
            params.append(entity_id)
        sql += " ORDER BY seq DESC LIMIT ?"
        params.append(min(limit, 1000))
        return self.db.query(sql, params)

    def verify(self) -> dict[str, Any]:
        prev = GENESIS
        count = 0
        for row in self.db.query("SELECT * FROM audit_events ORDER BY seq"):
            expected = sha256(
                canonical_json(
                    [prev, row["at"], row["actor_id"], row["org_id"], row["action"], row["entity"], row["entity_id"], row["data_json"]]
                )
            )
            if row["prev_hash"] != prev or row["hash"] != expected:
                return {"ok": False, "broken_at": row["seq"], "checked": count}
            prev = row["hash"]
            count += 1
        return {"ok": True, "checked": count, "head": prev}
