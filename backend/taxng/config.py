"""Runtime configuration from environment variables, with safe demo defaults."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_DIR = Path(os.environ.get("TAXNG_RULES_DIR", REPO_ROOT / "rules"))
CONTENT_DIR = Path(os.environ.get("TAXNG_CONTENT_DIR", REPO_ROOT / "content"))
WEB_DIST = Path(os.environ.get("TAXNG_WEB_DIST", REPO_ROOT / "frontend" / "dist"))
DATA_DIR = Path(os.environ.get("TAXNG_DATA_DIR", REPO_ROOT / "data"))
DATABASE = os.environ.get("TAXNG_DB", str(DATA_DIR / "taxng.sqlite3"))

# Demo mode exposes the message outbox (so sign-in codes are visible without
# email) and the seed command. It must be off in production: TAXNG_DEMO=0.
DEMO_MODE = os.environ.get("TAXNG_DEMO", "1") == "1"

# Addresses that become platform admins on first sign-in.
ADMIN_EMAILS = {e.strip().lower() for e in os.environ.get("TAXNG_ADMIN_EMAILS", "").split(",") if e.strip()}

# Used to sign newsletter unsubscribe tokens. The default is for local demos
# only; production must set TAXNG_SECRET (the app logs a warning otherwise).
SECRET = os.environ.get("TAXNG_SECRET", "dev-only-secret-change-me")
DEV_SECRET = SECRET == "dev-only-secret-change-me"

MAX_BODY_BYTES = 64 * 1024
# File uploads travel as base64 JSON; 10 MB files need about 14 MB of body.
MAX_UPLOAD_BODY_BYTES = 15 * 1024 * 1024
UPLOAD_PATH_SUFFIX = "/files"

# Public site and signed-in app origins (ADR-06). In the demo both are served
# by one process; set these in production to enforce host separation.
PUBLIC_HOST = os.environ.get("TAXNG_PUBLIC_HOST", "")
APP_HOST = os.environ.get("TAXNG_APP_HOST", "")
