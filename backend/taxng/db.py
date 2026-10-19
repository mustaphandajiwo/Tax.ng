"""SQLite access layer and schema migrations.

SQLite stands in for PostgreSQL in the demo (docs/DECISIONS.md, D5). All SQL
goes through this class so the port is one file. Rules for callers:

* Use ``?`` placeholders only. Table and column names passed to ``insert`` and
  ``update`` are validated against an identifier pattern.
* Tenant-scoped tables carry ``org_id`` (or ``user_id`` for personal data) and
  every query on them filters by it. Access checks live in
  ``taxng.platform.access``; this layer does not bypass them.
* Schema files: ``taxng/platform/schema.sql`` runs first, then every
  ``taxng/modules/*/schema.sql`` in name order. Statements must be idempotent
  (``CREATE TABLE IF NOT EXISTS``).
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
PACKAGE_DIR = Path(__file__).resolve().parent


def _ident(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return name


def schema_files() -> list[Path]:
    core = PACKAGE_DIR / "platform" / "schema.sql"
    modules = sorted((PACKAGE_DIR / "modules").glob("*/schema.sql"))
    return [core, *modules]


class Database:
    def __init__(self, path: str) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._lock = threading.RLock()
        self._depth = 0

    # ------------------------------------------------------------ migrations
    def migrate(self) -> list[str]:
        """Apply every schema file whose content has not been applied yet."""
        applied: list[str] = []
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, sha256 TEXT NOT NULL, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            for path in schema_files():
                sql = path.read_text(encoding="utf-8")
                digest = hashlib.sha256(sql.encode()).hexdigest()
                name = path.relative_to(PACKAGE_DIR).as_posix()
                row = self._conn.execute("SELECT sha256 FROM schema_migrations WHERE name = ?", (name,)).fetchone()
                if row and row["sha256"] == digest:
                    continue
                self._conn.executescript(sql)
                self._conn.execute(
                    "INSERT INTO schema_migrations (name, sha256) VALUES (?, ?) "
                    "ON CONFLICT(name) DO UPDATE SET sha256 = excluded.sha256, applied_at = CURRENT_TIMESTAMP",
                    (name, digest),
                )
                applied.append(name)
        return applied

    # -------------------------------------------------------------- queries
    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, tuple(params))

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, tuple(params)).fetchall()]

    def one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(sql, tuple(params)).fetchone()
        return dict(row) if row else None

    def scalar(self, sql: str, params: Sequence[Any] = ()) -> Any:
        with self._lock:
            row = self._conn.execute(sql, tuple(params)).fetchone()
        return row[0] if row else None

    def insert(self, table: str, row: dict[str, Any]) -> int:
        cols = [_ident(c) for c in row]
        sql = f"INSERT INTO {_ident(table)} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
        with self._lock:
            return int(self._conn.execute(sql, tuple(row.values())).lastrowid or 0)

    def update(self, table: str, values: dict[str, Any], where: str, params: Sequence[Any]) -> int:
        """``where`` is a fixed SQL fragment with ``?`` placeholders, never user input."""
        sets = ", ".join(f"{_ident(c)} = ?" for c in values)
        sql = f"UPDATE {_ident(table)} SET {sets} WHERE {where}"
        with self._lock:
            return self._conn.execute(sql, (*values.values(), *params)).rowcount

    @contextmanager
    def transaction(self) -> Iterator[Database]:
        """Nestable; only the outermost level commits or rolls back."""
        with self._lock:
            outer = self._depth == 0
            if outer:
                self._conn.execute("BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield self
            except BaseException:
                self._depth -= 1
                if outer:
                    self._conn.execute("ROLLBACK")
                raise
            self._depth -= 1
            if outer:
                self._conn.execute("COMMIT")

    def close(self) -> None:
        self._conn.close()
