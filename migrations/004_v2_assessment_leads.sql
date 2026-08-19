CREATE TABLE leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,
    contact_name TEXT NOT NULL,
    phone_normalized TEXT,
    email TEXT,
    wechat TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    owner_text TEXT,
    source TEXT,
    next_followup_at TEXT,
    last_effective_followup_at TEXT,
    retention_expires_at TEXT,
    anonymized_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE UNIQUE INDEX uq_active_lead_phone
ON leads(phone_normalized) WHERE phone_normalized IS NOT NULL;

ALTER TABLE assessments ADD COLUMN submission_key TEXT;
ALTER TABLE assessments ADD COLUMN lead_id INTEGER REFERENCES leads(id);
ALTER TABLE assessments ADD COLUMN rule_version_id INTEGER REFERENCES assessment_versions(id);
ALTER TABLE assessments ADD COLUMN branch_code TEXT;
ALTER TABLE assessments ADD COLUMN subbranch_code TEXT;
ALTER TABLE assessments ADD COLUMN department_code TEXT;
ALTER TABLE assessments ADD COLUMN company_size_code TEXT;
ALTER TABLE assessments ADD COLUMN answers_json TEXT;
ALTER TABLE assessments ADD COLUMN dimension_scores_json TEXT;
ALTER TABLE assessments ADD COLUMN overall_score REAL;
ALTER TABLE assessments ADD COLUMN maturity_code TEXT;
ALTER TABLE assessments ADD COLUMN report_snapshot_json TEXT;
ALTER TABLE assessments ADD COLUMN attribution_json TEXT;
ALTER TABLE assessments ADD COLUMN completed_at TEXT;

CREATE UNIQUE INDEX uq_assessments_submission_key
ON assessments(submission_key) WHERE submission_key IS NOT NULL;

CREATE TABLE lead_consents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL,
    policy_version TEXT NOT NULL,
    consented_at TEXT NOT NULL,
    source TEXT NOT NULL,
    identity_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (lead_id) REFERENCES leads(id)
);

CREATE TABLE lead_status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL,
    previous_status TEXT,
    new_status TEXT NOT NULL,
    note TEXT,
    actor_text TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (lead_id) REFERENCES leads(id)
);

CREATE TABLE lead_followups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL,
    note TEXT NOT NULL,
    next_followup_at TEXT,
    effective_at TEXT,
    actor_text TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (lead_id) REFERENCES leads(id)
);

CREATE TABLE data_subject_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER,
    identity_hash TEXT NOT NULL,
    request_type TEXT NOT NULL
        CHECK(request_type IN ('access', 'correction', 'withdrawal', 'deletion')),
    status TEXT NOT NULL DEFAULT 'received'
        CHECK(status IN ('received', 'verifying', 'completed', 'rejected')),
    channel TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    resolution_note TEXT,
    completed_at TEXT,
    admin_received_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    admin_updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (lead_id) REFERENCES leads(id)
);

CREATE TABLE roi_estimates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_id INTEGER NOT NULL UNIQUE,
    rule_version_id INTEGER NOT NULL,
    recommended_scenarios_json TEXT NOT NULL,
    estimate_snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (assessment_id) REFERENCES assessments(id),
    FOREIGN KEY (rule_version_id) REFERENCES assessment_versions(id)
);
