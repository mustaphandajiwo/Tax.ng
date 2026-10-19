-- Channels: WhatsApp (CH-02) and localisation (CH-04, CH-05).
--
-- WhatsApp privacy: phone numbers are never stored. ``phone_hash`` is an HMAC
-- of the normalised number under a channel-specific key. The message log keeps
-- a short snippet of inbound text and the reply kind only, and rows older than
-- the retention period (service.RETENTION_DAYS) are purged on every inbound
-- message.

CREATE TABLE IF NOT EXISTS wa_contacts (
    phone_hash TEXT PRIMARY KEY,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    opted_out_at TEXT
);

CREATE TABLE IF NOT EXISTS wa_messages (
    id TEXT PRIMARY KEY,
    phone_hash TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    kind TEXT NOT NULL,
    snippet TEXT NOT NULL DEFAULT '',
    provider_message_id TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS wa_messages_sender ON wa_messages (phone_hash, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS wa_messages_provider_id ON wa_messages (provider_message_id) WHERE provider_message_id IS NOT NULL;

-- UI string translations. Content files hold drafts; nothing is served until a
-- reviewer approves a submission here.
CREATE TABLE IF NOT EXISTS i18n_submissions (
    id TEXT PRIMARY KEY,
    lang TEXT NOT NULL,
    key TEXT NOT NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('submitted', 'approved', 'rejected')),
    submitted_by TEXT NOT NULL REFERENCES users (id),
    submitted_at TEXT NOT NULL,
    reviewed_by TEXT REFERENCES users (id),
    reviewed_at TEXT,
    review_note TEXT
);
CREATE INDEX IF NOT EXISTS i18n_submissions_lang ON i18n_submissions (lang, key, status);

-- Translations of reform guide summaries (content/guides.yaml ids).
CREATE TABLE IF NOT EXISTS guide_translations (
    id TEXT PRIMARY KEY,
    guide_id TEXT NOT NULL,
    lang TEXT NOT NULL,
    summary TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('submitted', 'approved', 'rejected')),
    submitted_by TEXT NOT NULL REFERENCES users (id),
    submitted_at TEXT NOT NULL,
    reviewed_by TEXT REFERENCES users (id),
    reviewed_at TEXT,
    review_note TEXT
);
CREATE INDEX IF NOT EXISTS guide_translations_guide ON guide_translations (guide_id, lang, status);
