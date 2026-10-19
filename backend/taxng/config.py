"""Runtime configuration from environment variables, with safe demo defaults."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_DIR = Path(os.environ.get("TAXNG_RULES_DIR", REPO_ROOT / "rules"))
CONTENT_DIR = Path(os.environ.get("TAXNG_CONTENT_DIR", REPO_ROOT / "content"))
WEB_DIST = Path(os.environ.get("TAXNG_WEB_DIST", REPO_ROOT / "frontend" / "dist"))
DATABASE = os.environ.get("TAXNG_DB", str(REPO_ROOT / "data" / "taxng.sqlite3"))

# Used to sign newsletter unsubscribe tokens. The default is for local demos
# only; production must set TAXNG_SECRET (the app logs a warning otherwise).
SECRET = os.environ.get("TAXNG_SECRET", "dev-only-secret-change-me")
DEV_SECRET = SECRET == "dev-only-secret-change-me"

MAX_BODY_BYTES = 64 * 1024
