"""Document storage with short-lived signed download links (Annex A, data segregation).

Files are stored by content hash under ``DATA_DIR/files``. Metadata lives in
the ``files`` table, scoped to an organisation or a user. Download links are
HMAC-signed and expire after a few minutes; access checks happen before a link
is issued.
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import hashlib
from pathlib import Path
from typing import Any

from ..db import Database
from .errors import Invalid
from .util import iso, new_id, now, sign, verify_signature

ALLOWED_TYPES = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "text/csv": ".csv",
    "application/json": ".json",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}
MAX_FILE_BYTES = 10 * 1024 * 1024
LINK_TTL = dt.timedelta(minutes=5)


class FileError(Invalid):
    pass


class FileStore:
    def __init__(self, db: Database, root: Path, secret: str) -> None:
        self.db = db
        self.root = root
        self.secret = secret

    def save(
        self,
        *,
        owner_user_id: str,
        org_id: str | None,
        name: str,
        content_type: str,
        data_base64: str,
        category: str = "general",
    ) -> dict[str, Any]:
        if content_type not in ALLOWED_TYPES:
            raise FileError("content_type: file type not allowed")
        try:
            data = base64.b64decode(data_base64, validate=True)
        except (binascii.Error, ValueError):
            raise FileError("data_base64: not valid base64") from None
        if not data:
            raise FileError("data_base64: file is empty")
        if len(data) > MAX_FILE_BYTES:
            raise FileError("data_base64: file is larger than 10 MB")
        digest = hashlib.sha256(data).hexdigest()
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / digest
        if not path.exists():
            path.write_bytes(data)
        record = {
            "id": new_id("file"),
            "org_id": org_id,
            "owner_user_id": owner_user_id,
            "name": Path(name).name[:200] or "file",
            "content_type": content_type,
            "size": len(data),
            "sha256": digest,
            "category": category[:40],
            "created_at": iso(),
        }
        self.db.insert("files", record)
        return record

    def get(self, file_id: str) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM files WHERE id = ? AND deleted_at IS NULL", (file_id,))

    def signed_link(self, file_id: str) -> dict[str, str]:
        expires = int((now() + LINK_TTL).timestamp())
        signature = sign(self.secret, f"{file_id}:{expires}")
        return {"url": f"/api/files/{file_id}/download?exp={expires}&sig={signature}", "expires": str(expires)}

    def read_signed(self, file_id: str, exp: str, sig: str) -> tuple[dict[str, Any], bytes]:
        try:
            expires = int(exp)
        except ValueError:
            raise FileError("link: invalid") from None
        if expires < int(now().timestamp()) or not verify_signature(self.secret, f"{file_id}:{expires}", sig):
            raise FileError("link: expired or invalid")
        record = self.get(file_id)
        if record is None:
            raise FileError("link: file not found")
        return record, (self.root / record["sha256"]).read_bytes()

    def soft_delete(self, file_id: str) -> None:
        self.db.update("files", {"deleted_at": iso()}, "id = ?", (file_id,))
