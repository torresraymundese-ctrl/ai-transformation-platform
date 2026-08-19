CREATE TABLE industries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK(status IN ('draft', 'published', 'archived')),
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE industry_branches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    industry_id INTEGER NOT NULL,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK(status IN ('draft', 'published', 'archived')),
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (industry_id) REFERENCES industries(id)
);

CREATE TABLE departments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK(status IN ('draft', 'published', 'archived')),
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE scenarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    category_code TEXT NOT NULL,
    public_name TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK(status IN ('draft', 'published', 'archived')),
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE scenario_branches (
    scenario_id INTEGER NOT NULL,
    industry_id INTEGER NOT NULL,
    PRIMARY KEY (scenario_id, industry_id),
    FOREIGN KEY (scenario_id) REFERENCES scenarios(id),
    FOREIGN KEY (industry_id) REFERENCES industries(id)
);

CREATE TABLE scenario_departments (
    scenario_id INTEGER NOT NULL,
    department_id INTEGER NOT NULL,
    PRIMARY KEY (scenario_id, department_id),
    FOREIGN KEY (scenario_id) REFERENCES scenarios(id),
    FOREIGN KEY (department_id) REFERENCES departments(id)
);

CREATE TABLE service_deliverables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    service_id INTEGER,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK(status IN ('draft', 'published', 'archived')),
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (service_id) REFERENCES services(id)
);

CREATE TABLE scenario_services (
    scenario_id INTEGER NOT NULL,
    service_deliverable_id INTEGER NOT NULL,
    PRIMARY KEY (scenario_id, service_deliverable_id),
    FOREIGN KEY (scenario_id) REFERENCES scenarios(id),
    FOREIGN KEY (service_deliverable_id) REFERENCES service_deliverables(id)
);

CREATE TABLE assessment_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK(status IN ('draft', 'published', 'archived')),
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    published_at TEXT
);

CREATE TRIGGER prevent_assessment_version_code_update
BEFORE UPDATE OF code ON assessment_versions
BEGIN
    SELECT RAISE(ABORT, 'assessment version code is immutable');
END;

CREATE TABLE assessment_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_version_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    dimension_code TEXT NOT NULL,
    prompt TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK(status IN ('draft', 'published', 'archived')),
    UNIQUE (assessment_version_id, code),
    FOREIGN KEY (assessment_version_id) REFERENCES assessment_versions(id)
);

CREATE TABLE assessment_options (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    label TEXT NOT NULL,
    score INTEGER NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    UNIQUE (question_id, code),
    FOREIGN KEY (question_id) REFERENCES assessment_questions(id)
);

CREATE TABLE industry_benchmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_version_id INTEGER NOT NULL,
    industry_id INTEGER NOT NULL,
    label TEXT NOT NULL,
    business_value_score INTEGER NOT NULL,
    process_score INTEGER NOT NULL,
    data_score INTEGER NOT NULL,
    systems_score INTEGER NOT NULL,
    organization_score INTEGER NOT NULL,
    delivery_score INTEGER NOT NULL,
    UNIQUE (assessment_version_id, industry_id),
    FOREIGN KEY (assessment_version_id) REFERENCES assessment_versions(id),
    FOREIGN KEY (industry_id) REFERENCES industries(id)
);

CREATE TABLE roi_option_ranges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_version_id INTEGER NOT NULL,
    option_group TEXT NOT NULL,
    code TEXT NOT NULL,
    low_value REAL NOT NULL,
    mid_value REAL NOT NULL,
    high_value REAL NOT NULL,
    CHECK(low_value <= mid_value AND mid_value <= high_value),
    UNIQUE (assessment_version_id, option_group, code),
    FOREIGN KEY (assessment_version_id) REFERENCES assessment_versions(id)
);

CREATE TABLE scenario_roi_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_version_id INTEGER NOT NULL,
    scenario_id INTEGER NOT NULL,
    efficiency_low REAL NOT NULL,
    efficiency_mid REAL NOT NULL,
    efficiency_high REAL NOT NULL,
    loss_improvement_low REAL NOT NULL,
    loss_improvement_mid REAL NOT NULL,
    loss_improvement_high REAL NOT NULL,
    annual_support_rate_low REAL NOT NULL,
    annual_support_rate_mid REAL NOT NULL,
    annual_support_rate_high REAL NOT NULL,
    UNIQUE (assessment_version_id, scenario_id),
    FOREIGN KEY (assessment_version_id) REFERENCES assessment_versions(id),
    FOREIGN KEY (scenario_id) REFERENCES scenarios(id)
);
