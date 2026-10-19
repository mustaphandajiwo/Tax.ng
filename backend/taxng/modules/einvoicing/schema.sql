-- E-invoicing (PRD 5, EINV-01 to EINV-03, Annex A9). Organisation-scoped.

CREATE TABLE IF NOT EXISTS einvoices (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES organisations (id),
    kind TEXT NOT NULL DEFAULT 'invoice' CHECK (kind IN ('invoice', 'credit_note')),
    original_invoice_id TEXT REFERENCES einvoices (id),
    invoice_number TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'validated', 'submitted', 'accepted', 'rejected', 'cancelled')),
    issue_date TEXT,
    buyer_name TEXT NOT NULL DEFAULT '',
    buyer_tin TEXT NOT NULL DEFAULT '',
    -- The caller's input, kept so validation can be re-run after edits.
    input_json TEXT NOT NULL,
    -- Computed lines (VAT per line from the rules engine) and totals, as decimal strings.
    lines_json TEXT NOT NULL DEFAULT '[]',
    totals_json TEXT NOT NULL DEFAULT '{}',
    declared_totals_json TEXT,
    errors_json TEXT NOT NULL DEFAULT '{}',
    rules_version TEXT,
    source TEXT NOT NULL DEFAULT 'manual',
    external_id TEXT,
    submission_ref TEXT,
    irn TEXT,
    qr_payload TEXT,
    mode TEXT,
    rejection_reason TEXT,
    last_error TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    submitted_at TEXT,
    decided_at TEXT,
    UNIQUE (org_id, invoice_number)
);
CREATE INDEX IF NOT EXISTS einvoices_org_status ON einvoices (org_id, status);
CREATE INDEX IF NOT EXISTS einvoices_submission ON einvoices (submission_ref);
CREATE UNIQUE INDEX IF NOT EXISTS einvoices_import_key ON einvoices (org_id, source, external_id)
    WHERE external_id IS NOT NULL;

-- Submission idempotency: one key maps to one invoice and one stored response.
CREATE TABLE IF NOT EXISTS einvoice_idempotency (
    org_id TEXT NOT NULL,
    idem_key TEXT NOT NULL,
    invoice_id TEXT NOT NULL REFERENCES einvoices (id),
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (org_id, idem_key)
);

-- Per-invoice event log. Append-only, like audit_events.
CREATE TABLE IF NOT EXISTS einvoice_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id TEXT NOT NULL REFERENCES einvoices (id),
    org_id TEXT NOT NULL,
    at TEXT NOT NULL,
    actor_id TEXT,
    event TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT,
    data_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS einvoice_events_invoice ON einvoice_events (invoice_id, seq);
CREATE TRIGGER IF NOT EXISTS einvoice_events_no_update BEFORE UPDATE ON einvoice_events
BEGIN SELECT RAISE(ABORT, 'einvoice_events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS einvoice_events_no_delete BEFORE DELETE ON einvoice_events
BEGIN SELECT RAISE(ABORT, 'einvoice_events is append-only'); END;
