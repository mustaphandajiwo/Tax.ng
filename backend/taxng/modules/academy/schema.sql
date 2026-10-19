-- Academy (PRD section 8, ACAD-01/02). Course content lives in content/academy;
-- these tables hold enrolments, progress, graded attempts, certificates,
-- institutional seats and staff-approved CPD claims.

CREATE TABLE IF NOT EXISTS academy_enrolments (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users (id),
    course_id TEXT NOT NULL,
    cohort_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('pending_payment', 'active', 'cancelled')),
    source TEXT NOT NULL CHECK (source IN ('free', 'paid', 'seat')),
    seat_pool_id TEXT,
    checkout_id TEXT,
    checkout_url TEXT,
    checkout_mode TEXT,
    created_at TEXT NOT NULL,
    activated_at TEXT,
    UNIQUE (user_id, course_id)
);
CREATE INDEX IF NOT EXISTS academy_enrolments_user ON academy_enrolments (user_id);

CREATE TABLE IF NOT EXISTS academy_progress (
    enrolment_id TEXT NOT NULL REFERENCES academy_enrolments (id),
    lesson_id TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    PRIMARY KEY (enrolment_id, lesson_id)
);

-- Graded on the server. answers_json holds the option ids the learner chose.
CREATE TABLE IF NOT EXISTS academy_attempts (
    id TEXT PRIMARY KEY,
    enrolment_id TEXT NOT NULL REFERENCES academy_enrolments (id),
    quiz_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('quiz', 'assessment')),
    answers_json TEXT NOT NULL,
    correct INTEGER NOT NULL,
    total INTEGER NOT NULL,
    passed INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS academy_attempts_enrolment ON academy_attempts (enrolment_id, quiz_id);

-- One certificate per enrolment. ``mac`` is the HMAC part of the public code.
CREATE TABLE IF NOT EXISTS academy_certificates (
    id TEXT PRIMARY KEY,
    enrolment_id TEXT NOT NULL UNIQUE REFERENCES academy_enrolments (id),
    user_id TEXT NOT NULL REFERENCES users (id),
    course_id TEXT NOT NULL,
    holder_name TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    mac TEXT NOT NULL,
    cpd_json TEXT NOT NULL DEFAULT 'null'
);

-- Institutional seats bought by an organisation owner.
CREATE TABLE IF NOT EXISTS academy_seat_pools (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES organisations (id),
    course_id TEXT NOT NULL,
    seats_total INTEGER NOT NULL CHECK (seats_total > 0),
    status TEXT NOT NULL CHECK (status IN ('pending_payment', 'active')),
    checkout_id TEXT,
    checkout_url TEXT,
    checkout_mode TEXT,
    created_by TEXT NOT NULL REFERENCES users (id),
    created_at TEXT NOT NULL,
    activated_at TEXT
);
CREATE INDEX IF NOT EXISTS academy_seat_pools_org ON academy_seat_pools (org_id);

CREATE TABLE IF NOT EXISTS academy_seat_assignments (
    pool_id TEXT NOT NULL REFERENCES academy_seat_pools (id),
    user_id TEXT NOT NULL REFERENCES users (id),
    enrolment_id TEXT NOT NULL REFERENCES academy_enrolments (id),
    assigned_by TEXT NOT NULL REFERENCES users (id),
    assigned_at TEXT NOT NULL,
    PRIMARY KEY (pool_id, user_id)
);

-- ACAD-02: a CPD claim exists only once staff record the accrediting body and reference.
CREATE TABLE IF NOT EXISTS academy_cpd_approvals (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL,
    body TEXT NOT NULL CHECK (body IN ('CITN', 'ICAN')),
    reference TEXT NOT NULL,
    approved_by TEXT NOT NULL REFERENCES users (id),
    approved_at TEXT NOT NULL,
    withdrawn_at TEXT,
    withdrawn_by TEXT
);
CREATE INDEX IF NOT EXISTS academy_cpd_course ON academy_cpd_approvals (course_id);
