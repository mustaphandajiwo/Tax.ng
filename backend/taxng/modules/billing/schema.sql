-- Billing (PRD section 9): commercial payments only. Tax remittances never pass through here.

CREATE TABLE IF NOT EXISTS billing_subscriptions (
    id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    category TEXT NOT NULL,
    org_id TEXT REFERENCES organisations (id),
    user_id TEXT REFERENCES users (id),
    quantity INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL CHECK (status IN ('pending', 'active', 'cancelled', 'superseded')),
    checkout_id TEXT,
    current_period_start TEXT,
    current_period_end TEXT,
    created_by TEXT NOT NULL REFERENCES users (id),
    created_at TEXT NOT NULL,
    cancelled_at TEXT,
    CHECK ((org_id IS NULL) <> (user_id IS NULL))
);
CREATE INDEX IF NOT EXISTS billing_subscriptions_org ON billing_subscriptions (org_id, status);
CREATE INDEX IF NOT EXISTS billing_subscriptions_user ON billing_subscriptions (user_id, status);

CREATE TABLE IF NOT EXISTS billing_payments (
    id TEXT PRIMARY KEY,
    checkout_id TEXT NOT NULL UNIQUE,
    purpose TEXT NOT NULL CHECK (purpose IN ('subscription', 'course', 'advisory', 'sponsorship', 'advertising')),
    reference_id TEXT NOT NULL,
    payer_user_id TEXT NOT NULL REFERENCES users (id),
    org_id TEXT REFERENCES organisations (id),
    amount_kobo INTEGER NOT NULL CHECK (amount_kobo > 0),
    currency TEXT NOT NULL DEFAULT 'NGN',
    description TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'paid', 'failed')),
    provider TEXT NOT NULL,
    provider_ref TEXT,
    mode TEXT NOT NULL,
    created_at TEXT NOT NULL,
    paid_at TEXT,
    handled_at TEXT,
    handler_error TEXT
);
CREATE INDEX IF NOT EXISTS billing_payments_payer ON billing_payments (payer_user_id, created_at);
CREATE INDEX IF NOT EXISTS billing_payments_org ON billing_payments (org_id, created_at);

-- Each provider webhook event is processed once.
CREATE TABLE IF NOT EXISTS billing_webhook_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    checkout_id TEXT,
    outcome TEXT NOT NULL,
    received_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS billing_receipts (
    id TEXT PRIMARY KEY,
    number TEXT NOT NULL UNIQUE,
    payment_id TEXT NOT NULL UNIQUE REFERENCES billing_payments (id),
    payer_user_id TEXT NOT NULL,
    org_id TEXT,
    description TEXT NOT NULL,
    amount_kobo INTEGER NOT NULL,
    currency TEXT NOT NULL,
    mode TEXT NOT NULL,
    issued_at TEXT NOT NULL
);
