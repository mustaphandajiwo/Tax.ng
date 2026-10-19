-- Compliance module (HC-01 to HC-07). Personal data: every row is scoped by user_id.

-- One profile per user: only the facts the obligations engine needs (minimal data).
CREATE TABLE IF NOT EXISTS compliance_profiles (
    user_id TEXT PRIMARY KEY REFERENCES users (id),
    facts_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

-- A health-check run. Evidence answers are saved as the user goes (saved progress).
-- On completion the facts used and the report are frozen with the rules version.
CREATE TABLE IF NOT EXISTS compliance_checks (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users (id),
    year INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('in_progress', 'completed')),
    answers_json TEXT NOT NULL DEFAULT '{}',
    facts_json TEXT,
    report_json TEXT,
    rules_version TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS compliance_checks_user ON compliance_checks (user_id, created_at);
