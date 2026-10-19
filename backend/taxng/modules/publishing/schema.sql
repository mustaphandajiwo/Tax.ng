-- Publishing module: contributor articles, editorial workflow, corrections,
-- complaints, sponsorship, display advertising and newsletter editions.
-- PRD sections 6 and 7, Annex A8 and Annex B. Idempotent; see taxng/db.py.

CREATE TABLE IF NOT EXISTS pub_articles (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    author_user_id TEXT NOT NULL REFERENCES users (id),
    article_type TEXT NOT NULL DEFAULT 'submission'
        CHECK (article_type IN ('commentary', 'news', 'opinion', 'submission', 'sponsored')),
    section TEXT CHECK (section IS NULL OR section IN ('nigeria', 'africa', 'global')),
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    author_name TEXT NOT NULL DEFAULT '',
    author_credentials TEXT NOT NULL DEFAULT '',
    affiliation TEXT NOT NULL DEFAULT '',
    citations_json TEXT NOT NULL DEFAULT '[]',
    jurisdiction TEXT NOT NULL DEFAULT 'Nigeria',
    rights_warranty INTEGER NOT NULL DEFAULT 0,
    conflicts TEXT NOT NULL DEFAULT '',
    ai_disclosure TEXT NOT NULL DEFAULT '',
    sponsorship_declaration TEXT NOT NULL DEFAULT 'none'
        CHECK (sponsorship_declaration IN ('none', 'paid', 'in_kind')),
    sponsorship_id TEXT,
    state TEXT NOT NULL DEFAULT 'draft'
        CHECK (state IN ('draft', 'submitted', 'screening', 'revision_requested', 'fact_legal_review', 'approved',
                         'scheduled', 'published', 'corrected', 'withdrawn', 'rejected')),
    feedback TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1,
    legal_signoff_by TEXT,
    legal_signoff_at TEXT,
    approved_by TEXT,
    approved_at TEXT,
    scheduled_for TEXT,
    published_at TEXT,
    withdrawn_at TEXT,
    withdrawn_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS pub_articles_author ON pub_articles (author_user_id, updated_at);
CREATE INDEX IF NOT EXISTS pub_articles_state ON pub_articles (state, published_at);

-- Immutable revision history: one row per saved content version.
CREATE TABLE IF NOT EXISTS pub_revisions (
    id TEXT PRIMARY KEY,
    article_id TEXT NOT NULL REFERENCES pub_articles (id),
    version INTEGER NOT NULL,
    actor_id TEXT,
    reason TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    body TEXT NOT NULL,
    citations_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (article_id, version)
);
CREATE TRIGGER IF NOT EXISTS pub_revisions_no_update BEFORE UPDATE ON pub_revisions
BEGIN SELECT RAISE(ABORT, 'pub_revisions is append-only'); END;
CREATE TRIGGER IF NOT EXISTS pub_revisions_no_delete BEFORE DELETE ON pub_revisions
BEGIN SELECT RAISE(ABORT, 'pub_revisions is append-only'); END;

-- Workflow history: every state change with its note (feedback, reasons).
CREATE TABLE IF NOT EXISTS pub_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id TEXT NOT NULL REFERENCES pub_articles (id),
    action TEXT NOT NULL,
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    actor_id TEXT,
    actor_role TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS pub_history_no_update BEFORE UPDATE ON pub_history
BEGIN SELECT RAISE(ABORT, 'pub_history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS pub_history_no_delete BEFORE DELETE ON pub_history
BEGIN SELECT RAISE(ABORT, 'pub_history is append-only'); END;

-- Public correction notes; never edited or removed.
CREATE TABLE IF NOT EXISTS pub_corrections (
    id TEXT PRIMARY KEY,
    article_id TEXT NOT NULL REFERENCES pub_articles (id),
    version INTEGER NOT NULL,
    note TEXT NOT NULL,
    actor_id TEXT,
    created_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS pub_corrections_no_update BEFORE UPDATE ON pub_corrections
BEGIN SELECT RAISE(ABORT, 'pub_corrections is append-only'); END;
CREATE TRIGGER IF NOT EXISTS pub_corrections_no_delete BEFORE DELETE ON pub_corrections
BEGIN SELECT RAISE(ABORT, 'pub_corrections is append-only'); END;

-- SPON-03: disclosure record for paid content (one per article).
CREATE TABLE IF NOT EXISTS pub_disclosures (
    article_id TEXT PRIMARY KEY REFERENCES pub_articles (id),
    sponsorship_id TEXT,
    sponsor_name TEXT NOT NULL,
    funding_relationship TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT 'Sponsored' CHECK (label IN ('Sponsored', 'Paid Partnership')),
    arcon_required INTEGER NOT NULL DEFAULT 0,
    arcon_reference TEXT,
    recorded_by TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);

-- GOV-06: complaints and takedown requests.
CREATE TABLE IF NOT EXISTS pub_complaints (
    id TEXT PRIMARY KEY,
    article_id TEXT,
    kind TEXT NOT NULL CHECK (kind IN ('accuracy', 'legal', 'privacy', 'sponsorship', 'advertising', 'other')),
    details TEXT NOT NULL,
    contact_email TEXT,
    submitted_by TEXT,
    status TEXT NOT NULL DEFAULT 'received' CHECK (status IN ('received', 'investigating', 'resolved', 'rejected')),
    resolution TEXT NOT NULL DEFAULT '',
    handled_by TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- SPON-02: sponsorship orders. Payment state lives here and is never read by
-- editorial approval.
CREATE TABLE IF NOT EXISTS pub_sponsorships (
    id TEXT PRIMARY KEY,
    sponsor_name TEXT NOT NULL,
    funding_relationship TEXT NOT NULL,
    placement TEXT NOT NULL CHECK (placement IN ('sponsored_article', 'newsletter_sponsor')),
    label TEXT NOT NULL DEFAULT 'Sponsored' CHECK (label IN ('Sponsored', 'Paid Partnership')),
    arcon_required INTEGER NOT NULL DEFAULT 0,
    arcon_reference TEXT,
    amount_kobo INTEGER NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'rejected', 'cancelled', 'fulfilled')),
    payment_status TEXT NOT NULL DEFAULT 'unpaid' CHECK (payment_status IN ('unpaid', 'pending', 'paid', 'refund_due', 'refunded')),
    checkout_id TEXT,
    checkout_mode TEXT,
    terms_version TEXT NOT NULL,
    rejection_reason TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Display advertising (direct-sold).
CREATE TABLE IF NOT EXISTS pub_ad_campaigns (
    id TEXT PRIMARY KEY,
    advertiser TEXT NOT NULL,
    starts_on TEXT NOT NULL,
    ends_on TEXT NOT NULL,
    slots TEXT NOT NULL,
    arcon_reference TEXT,
    amount_kobo INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'paused', 'ended', 'rejected')),
    payment_status TEXT NOT NULL DEFAULT 'unpaid' CHECK (payment_status IN ('unpaid', 'pending', 'paid', 'refund_due', 'refunded')),
    checkout_id TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pub_ad_creatives (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES pub_ad_campaigns (id),
    headline TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    link_url TEXT NOT NULL,
    image_file_id TEXT,
    review_status TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending', 'approved', 'rejected')),
    review_note TEXT NOT NULL DEFAULT '',
    reviewed_by TEXT,
    reviewed_at TEXT,
    created_at TEXT NOT NULL
);

-- Aggregate daily counters only: no user, IP, cookie or page-level identifiers.
CREATE TABLE IF NOT EXISTS pub_ad_stats (
    creative_id TEXT NOT NULL REFERENCES pub_ad_creatives (id),
    day TEXT NOT NULL,
    impressions INTEGER NOT NULL DEFAULT 0,
    clicks INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (creative_id, day)
);

-- NEWS-02/04: newsletter editions.
CREATE TABLE IF NOT EXISTS pub_editions (
    id TEXT PRIMARY KEY,
    newsletter TEXT NOT NULL CHECK (newsletter IN ('nigerian_tax_brief', 'global_tax_watch')),
    title TEXT NOT NULL,
    intro TEXT NOT NULL DEFAULT '',
    items_json TEXT NOT NULL DEFAULT '[]',
    sponsorship_id TEXT,
    state TEXT NOT NULL DEFAULT 'draft'
        CHECK (state IN ('draft', 'fact_check', 'fact_checked', 'approved', 'scheduled', 'sent', 'archived')),
    fact_checked_by TEXT,
    approved_by TEXT,
    scheduled_for TEXT,
    sent_at TEXT,
    sent_count INTEGER NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
