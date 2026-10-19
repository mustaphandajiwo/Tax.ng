-- Workspace module (PRD Phase 3 business workspaces, Phase 4 authorised filing).
-- Core tables used as-is: organisations, memberships, invitations, files, audit_events.
-- Every table here carries org_id and every query filters by it.

CREATE TABLE IF NOT EXISTS ws_returns (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES organisations (id),
    return_type TEXT NOT NULL CHECK (return_type IN ('vat_monthly', 'wht_monthly', 'paye_monthly', 'cit_annual')),
    period TEXT NOT NULL,                 -- YYYY-MM (monthly) or YYYY (annual)
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'submitted_for_review', 'changes_requested', 'approved', 'filed_sandbox', 'filed')),
    -- Link to the compliance calendar (BIZ-01). Due date comes from the obligations engine, never from code.
    obligation_id TEXT,
    obligation_period TEXT,
    due_date TEXT,
    totals_json TEXT NOT NULL DEFAULT '{}',
    created_by TEXT NOT NULL REFERENCES users (id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    submitted_by TEXT,
    submitted_at TEXT,
    approved_by TEXT,
    approved_at TEXT,
    -- Hash of the line items and results at approval; exports and filings carry it.
    approval_hash TEXT,
    filed_reference TEXT,
    UNIQUE (org_id, return_type, period)
);
CREATE INDEX IF NOT EXISTS ws_returns_org ON ws_returns (org_id, status);

CREATE TABLE IF NOT EXISTS ws_return_lines (
    id TEXT PRIMARY KEY,
    return_id TEXT NOT NULL REFERENCES ws_returns (id),
    org_id TEXT NOT NULL REFERENCES organisations (id),
    position INTEGER NOT NULL,
    kind TEXT NOT NULL,                   -- output|input (VAT), payment (WHT), employee (PAYE), computation (CIT)
    details_json TEXT NOT NULL,           -- descriptive fields (payee, employee, invoice reference)
    inputs_json TEXT NOT NULL,            -- exactly what was passed to the calculator
    result_json TEXT NOT NULL,            -- CalculationResult.to_dict(), incl. rules_version
    rules_version TEXT NOT NULL,
    calculator TEXT NOT NULL,
    updated_by TEXT NOT NULL REFERENCES users (id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ws_return_lines_return ON ws_return_lines (org_id, return_id, position);

-- Maker-checker history (BIZ-05). Append-only by convention; the audit chain is the tamper-evident copy.
CREATE TABLE IF NOT EXISTS ws_return_events (
    id TEXT PRIMARY KEY,
    return_id TEXT NOT NULL REFERENCES ws_returns (id),
    org_id TEXT NOT NULL REFERENCES organisations (id),
    actor_id TEXT NOT NULL REFERENCES users (id),
    action TEXT NOT NULL CHECK (action IN ('created', 'submitted', 'approved', 'changes_requested', 'reopened', 'filed_sandbox', 'filed')),
    comment TEXT NOT NULL DEFAULT '',
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ws_return_events_return ON ws_return_events (org_id, return_id, at);

-- Users who edited lines since the return was last opened for editing. None of them may approve it.
CREATE TABLE IF NOT EXISTS ws_return_makers (
    return_id TEXT NOT NULL REFERENCES ws_returns (id),
    user_id TEXT NOT NULL REFERENCES users (id),
    PRIMARY KEY (return_id, user_id)
);

CREATE TABLE IF NOT EXISTS ws_return_documents (
    return_id TEXT NOT NULL REFERENCES ws_returns (id),
    file_id TEXT NOT NULL REFERENCES files (id),
    org_id TEXT NOT NULL REFERENCES organisations (id),
    linked_by TEXT NOT NULL REFERENCES users (id),
    linked_at TEXT NOT NULL,
    PRIMARY KEY (return_id, file_id)
);

-- Phase 4 filing submissions (Annex A9). State machine:
-- prepared -> submitting -> acknowledged | rejected | failed; acknowledged -> reconciled.
CREATE TABLE IF NOT EXISTS ws_submissions (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES organisations (id),
    return_id TEXT NOT NULL REFERENCES ws_returns (id),
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('prepared', 'submitting', 'acknowledged', 'rejected', 'failed', 'reconciled')),
    adapter TEXT NOT NULL,
    mode TEXT NOT NULL,
    document_hash TEXT NOT NULL,
    ack_reference TEXT,
    ack_signature TEXT,
    ack_verified INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL REFERENCES users (id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    reconciled_by TEXT,
    reconciled_at TEXT,
    reconcile_note TEXT,
    UNIQUE (org_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ws_submissions_return ON ws_submissions (org_id, return_id, created_at);

-- BIZ-06: receipts for remittances made by the taxpayer through official channels.
-- tax.ng never holds or initiates tax remittances (PRD section 9).
CREATE TABLE IF NOT EXISTS ws_payments (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES organisations (id),
    return_id TEXT NOT NULL REFERENCES ws_returns (id),
    receipt_reference TEXT NOT NULL,
    amount TEXT NOT NULL,                 -- decimal string
    paid_on TEXT NOT NULL,
    channel TEXT NOT NULL,
    file_id TEXT,
    recorded_by TEXT NOT NULL REFERENCES users (id),
    created_at TEXT NOT NULL,
    voided_at TEXT,
    voided_by TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ws_payments_receipt ON ws_payments (org_id, receipt_reference) WHERE voided_at IS NULL;
CREATE INDEX IF NOT EXISTS ws_payments_return ON ws_payments (org_id, return_id);
