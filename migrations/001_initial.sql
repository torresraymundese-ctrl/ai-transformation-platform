CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title_hash TEXT UNIQUE,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    source_url TEXT,
    summary TEXT,
    content_html TEXT,
    tags TEXT,
    category TEXT DEFAULT 'insight',
    publish_date TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    is_featured INTEGER DEFAULT 0,
    status TEXT DEFAULT 'published'
);

CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    industry TEXT NOT NULL,
    scale TEXT,
    pain_point TEXT,
    solution TEXT,
    result TEXT,
    tags TEXT,
    logo_text TEXT,
    is_featured INTEGER DEFAULT 0,
    sort_order INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    tier TEXT NOT NULL,
    category TEXT,
    description TEXT,
    pain_point TEXT,
    timeline TEXT,
    icon TEXT,
    sort_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT,
    contact_email TEXT,
    scores TEXT,
    result TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS site_config (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS announcements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content_html TEXT,
    is_pinned INTEGER DEFAULT 0,
    status TEXT DEFAULT 'published',
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS asset_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    category TEXT NOT NULL CHECK(category IN ('table','chair')),
    sort_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS asset_departments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    sort_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS unit_a_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    department TEXT NOT NULL,
    asset_code_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    remark TEXT DEFAULT '',
    FOREIGN KEY (asset_code_id) REFERENCES asset_codes(id)
);

CREATE TABLE IF NOT EXISTS unit_b_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_code_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    remark TEXT DEFAULT '',
    FOREIGN KEY (asset_code_id) REFERENCES asset_codes(id)
);
