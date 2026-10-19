-- Developer platform (Phase 4): API keys, idempotency, outbound webhooks, ERP imports.

CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES organisations (id),
    name TEXT NOT NULL,
    -- Public part of the key, shown in lists to identify it. The secret is never stored.
    prefix TEXT NOT NULL UNIQUE,
    key_hash TEXT NOT NULL,
    scopes TEXT NOT NULL,
    rate_per_minute INTEGER NOT NULL,
    mode TEXT NOT NULL DEFAULT 'sandbox',
    created_by TEXT NOT NULL REFERENCES users (id),
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at TEXT,
    revoked_by TEXT
);
CREATE INDEX IF NOT EXISTS api_keys_org ON api_keys (org_id);

CREATE TABLE IF NOT EXISTS api_idempotency (
    key_id TEXT NOT NULL REFERENCES api_keys (id),
    idem_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status INTEGER NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (key_id, idem_key)
);

CREATE TABLE IF NOT EXISTS webhook_endpoints (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES organisations (id),
    url TEXT NOT NULL,
    events TEXT NOT NULL,
    -- Signing secret. Needed in clear to sign deliveries; production keeps it in a KMS.
    secret TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_by TEXT NOT NULL REFERENCES users (id),
    created_at TEXT NOT NULL,
    disabled_at TEXT
);
CREATE INDEX IF NOT EXISTS webhook_endpoints_org ON webhook_endpoints (org_id, active);

-- Outbox of webhook deliveries with their signature and retry schedule.
CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id TEXT PRIMARY KEY,
    endpoint_id TEXT NOT NULL REFERENCES webhook_endpoints (id),
    org_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    event TEXT NOT NULL,
    body TEXT NOT NULL,
    signature TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('would_deliver', 'pending', 'delivered', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    schedule_json TEXT NOT NULL,
    next_attempt_at TEXT,
    last_attempt_at TEXT,
    mode TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS webhook_deliveries_org ON webhook_deliveries (org_id, created_at);

CREATE TABLE IF NOT EXISTS erp_imports (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES organisations (id),
    profile TEXT NOT NULL,
    source TEXT NOT NULL,
    filename TEXT,
    rows INTEGER NOT NULL,
    counts_json TEXT NOT NULL,
    created_by TEXT NOT NULL REFERENCES users (id),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS erp_imports_org ON erp_imports (org_id, created_at);
