CREATE TABLE IF NOT EXISTS request_rate_limits (
    bucket TEXT NOT NULL,
    identity_hash TEXT NOT NULL,
    window_start INTEGER NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (bucket, identity_hash, window_start)
);

CREATE TABLE IF NOT EXISTS admin_audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    ip_hash TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
