-- Advisory module (ADV-01 to ADV-05, GOV-04).

-- ADV-01: one listing per user. Membership numbers are kept for annual
-- re-verification and are never returned by public endpoints (masked there).
CREATE TABLE IF NOT EXISTS advisory_advisers (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL UNIQUE REFERENCES users (id),
    name TEXT NOT NULL,
    firm TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    specialisms_json TEXT NOT NULL DEFAULT '[]',
    bio TEXT NOT NULL DEFAULT '',
    citn_number TEXT,
    ican_number TEXT,
    status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'suspended')),
    review_note TEXT,
    reviewed_by TEXT,
    reviewed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Register checks through the "register" adapter (CITN, ICAN). Append-only history.
CREATE TABLE IF NOT EXISTS advisory_verifications (
    id TEXT PRIMARY KEY,
    adviser_id TEXT NOT NULL REFERENCES advisory_advisers (id),
    register TEXT NOT NULL CHECK (register IN ('citn', 'ican')),
    number_masked TEXT NOT NULL,
    provider TEXT NOT NULL,
    mode TEXT NOT NULL,
    result TEXT NOT NULL CHECK (result IN ('verified', 'not_found', 'error')),
    checked_at TEXT NOT NULL,
    expires_at TEXT
);
CREATE INDEX IF NOT EXISTS advisory_verifications_adviser ON advisory_verifications (adviser_id, checked_at);

-- ADV-04: paid placement in the separate sponsored slot. Never affects default order.
CREATE TABLE IF NOT EXISTS advisory_placements (
    id TEXT PRIMARY KEY,
    adviser_id TEXT NOT NULL REFERENCES advisory_advisers (id),
    status TEXT NOT NULL CHECK (status IN ('pending_payment', 'active', 'cancelled')),
    amount_kobo INTEGER NOT NULL,
    duration_days INTEGER NOT NULL,
    checkout_id TEXT,
    mode TEXT,
    created_at TEXT NOT NULL,
    starts_at TEXT,
    ends_at TEXT
);

-- ADV-02: booking requests. intake_json holds only the fields the client chose to share.
CREATE TABLE IF NOT EXISTS advisory_bookings (
    id TEXT PRIMARY KEY,
    client_user_id TEXT NOT NULL REFERENCES users (id),
    adviser_id TEXT NOT NULL REFERENCES advisory_advisers (id),
    status TEXT NOT NULL CHECK (status IN ('requested', 'accepted', 'declined', 'cancelled')),
    topic TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    preferred_date TEXT,
    intake_json TEXT NOT NULL DEFAULT '{}',
    intake_consent_id TEXT NOT NULL,
    decision_note TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT
);
CREATE INDEX IF NOT EXISTS advisory_bookings_client ON advisory_bookings (client_user_id, created_at);
CREATE INDEX IF NOT EXISTS advisory_bookings_adviser ON advisory_bookings (adviser_id, created_at);

-- ADV-03, GOV-04: an accepted booking becomes an engagement under the practitioner's terms.
CREATE TABLE IF NOT EXISTS advisory_engagements (
    id TEXT PRIMARY KEY,
    booking_id TEXT NOT NULL UNIQUE REFERENCES advisory_bookings (id),
    client_user_id TEXT NOT NULL REFERENCES users (id),
    adviser_id TEXT NOT NULL REFERENCES advisory_advisers (id),
    status TEXT NOT NULL CHECK (status IN ('active', 'ended')),
    terms_notice TEXT NOT NULL,
    created_at TEXT NOT NULL,
    ended_at TEXT,
    ended_by TEXT
);

-- Consents are separate records by kind (ADV-02, ADV-03, ADV-05):
--   pre_engagement   fields shared with an adviser for one booking request
--   engagement       delegated read access for one engagement (revocable)
--   marketing        adviser-service offers from tax.ng
--   findings_matching  use of health-check findings to suggest advisers
CREATE TABLE IF NOT EXISTS advisory_consents (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users (id),
    kind TEXT NOT NULL CHECK (kind IN ('pre_engagement', 'engagement', 'marketing', 'findings_matching')),
    adviser_id TEXT,
    booking_id TEXT,
    engagement_id TEXT,
    scope_json TEXT NOT NULL DEFAULT '[]',
    consent_text TEXT NOT NULL,
    granted_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS advisory_consents_user ON advisory_consents (user_id, kind);
