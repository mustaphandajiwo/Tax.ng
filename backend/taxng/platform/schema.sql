-- Platform core schema: identity, sessions, organisations, audit, files,
-- notifications and the Phase 1 newsletter and analytics tables.
-- Every statement is idempotent; see taxng/db.py.

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL DEFAULT '',
    phone TEXT,
    staff_role TEXT NOT NULL DEFAULT 'none'
        CHECK (staff_role IN ('none', 'editor', 'legal_reviewer', 'sales', 'support', 'admin')),
    -- AI-04: Tax AI may read this user's account data only when this is 1.
    ai_account_access INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS otp_codes (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    used_at TEXT
);
CREATE INDEX IF NOT EXISTS otp_codes_email ON otp_codes (email, created_at);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users (id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT
);

CREATE TABLE IF NOT EXISTS organisations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT 'company'
        CHECK (entity_type IN ('company', 'sole_proprietor', 'partnership', 'nonprofit', 'government', 'other')),
    tin TEXT,
    cac_number TEXT,
    state TEXT,
    -- Facts used by the obligations engine (sector, turnover band, staff count...).
    profile_json TEXT NOT NULL DEFAULT '{}',
    created_by TEXT NOT NULL REFERENCES users (id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memberships (
    org_id TEXT NOT NULL REFERENCES organisations (id),
    user_id TEXT NOT NULL REFERENCES users (id),
    role TEXT NOT NULL CHECK (role IN ('owner', 'preparer', 'reviewer', 'read_only')),
    created_at TEXT NOT NULL,
    PRIMARY KEY (org_id, user_id)
);

CREATE TABLE IF NOT EXISTS invitations (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES organisations (id),
    email TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('owner', 'preparer', 'reviewer', 'read_only')),
    token_hash TEXT NOT NULL,
    created_by TEXT NOT NULL REFERENCES users (id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    accepted_at TEXT,
    revoked_at TEXT
);

-- ADR-09: append-only, hash-chained. Never UPDATE or DELETE rows here.
CREATE TABLE IF NOT EXISTS audit_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    actor_id TEXT,
    org_id TEXT,
    action TEXT NOT NULL,
    entity TEXT NOT NULL,
    entity_id TEXT,
    data_json TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_events_org ON audit_events (org_id, seq);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;

CREATE TABLE IF NOT EXISTS identity_verifications (
    id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL CHECK (subject_type IN ('user', 'organisation', 'adviser')),
    subject_id TEXT NOT NULL,
    id_type TEXT NOT NULL CHECK (id_type IN ('nin', 'tin', 'cac')),
    id_masked TEXT NOT NULL,
    id_hash TEXT NOT NULL,
    provider TEXT NOT NULL,
    mode TEXT NOT NULL,
    result TEXT NOT NULL CHECK (result IN ('verified', 'not_found', 'mismatch', 'error')),
    checked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    org_id TEXT,
    owner_user_id TEXT NOT NULL REFERENCES users (id),
    name TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    created_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS outbox (
    id TEXT PRIMARY KEY,
    channel TEXT NOT NULL CHECK (channel IN ('email', 'sms', 'whatsapp')),
    recipient TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL,
    provider TEXT NOT NULL,
    mode TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Phase 1: newsletter (NEWS-03) and first-party analytics (AN-01, AN-02).
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
