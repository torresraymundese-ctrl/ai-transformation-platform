CREATE TABLE appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_id INTEGER NOT NULL,
    lead_id INTEGER NOT NULL,
    submission_key TEXT NOT NULL UNIQUE,
    preferred_date TEXT NOT NULL,
    time_slot TEXT NOT NULL,
    note TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'confirmed', 'completed', 'cancelled')),
    confirmed_at TEXT,
    completed_at TEXT,
    cancelled_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (assessment_id) REFERENCES assessments(id),
    FOREIGN KEY (lead_id) REFERENCES leads(id)
);

CREATE TABLE analytics_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_name TEXT NOT NULL,
    assessment_id INTEGER,
    analytics_id_hash TEXT,
    branch_code TEXT,
    metadata_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (assessment_id) REFERENCES assessments(id)
);

CREATE UNIQUE INDEX uq_analytics_events_assessment_event
ON analytics_events(assessment_id, event_name)
WHERE assessment_id IS NOT NULL;
