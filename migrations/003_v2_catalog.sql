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
    industry_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK(status IN ('draft', 'published', 'archived')),
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE (industry_id, code),
    FOREIGN KEY (industry_id) REFERENCES industries(id)
);

CREATE TABLE company_sizes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'published'
        CHECK(status IN ('draft', 'published', 'archived')),
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE pain_points (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    industry_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'published'
        CHECK(status IN ('draft', 'published', 'archived')),
    sort_order INTEGER NOT NULL DEFAULT 0,
    UNIQUE (industry_id, code),
    FOREIGN KEY (industry_id) REFERENCES industries(id)
);

ALTER TABLE services ADD COLUMN code TEXT;
ALTER TABLE services ADD COLUMN public_name TEXT;
ALTER TABLE services ADD COLUMN min_budget REAL;
ALTER TABLE services ADD COLUMN max_budget REAL;
ALTER TABLE services ADD COLUMN min_weeks INTEGER;
ALTER TABLE services ADD COLUMN max_weeks INTEGER;
ALTER TABLE services ADD COLUMN implementation_steps_json TEXT;
ALTER TABLE services ADD COLUMN prerequisites_json TEXT;
ALTER TABLE services ADD COLUMN not_included_json TEXT;
ALTER TABLE services ADD COLUMN acceptance_json TEXT;
ALTER TABLE services ADD COLUMN support_days INTEGER;
ALTER TABLE services ADD COLUMN support_description TEXT;
ALTER TABLE services ADD COLUMN public_disclaimer TEXT;
ALTER TABLE services ADD COLUMN status TEXT NOT NULL DEFAULT 'published'
    CHECK(status IN ('draft', 'published', 'archived'));
CREATE UNIQUE INDEX services_code_unique
    ON services(code) WHERE code IS NOT NULL;

CREATE TABLE scenarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    category_code TEXT NOT NULL,
    public_name TEXT NOT NULL,
    description TEXT,
    minimum_business_value INTEGER NOT NULL,
    minimum_process INTEGER NOT NULL,
    minimum_data INTEGER NOT NULL,
    minimum_systems INTEGER NOT NULL,
    minimum_organization INTEGER NOT NULL,
    minimum_delivery INTEGER NOT NULL,
    integration_level TEXT NOT NULL CHECK(integration_level IN ('low', 'medium', 'high')),
    min_weeks INTEGER NOT NULL,
    max_weeks INTEGER NOT NULL,
    risk_codes_json TEXT NOT NULL,
    fallback_only INTEGER NOT NULL DEFAULT 0 CHECK(fallback_only IN (0, 1)),
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK(status IN ('draft', 'published', 'archived')),
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    CHECK(min_weeks <= max_weeks)
);

CREATE TABLE scenario_branches (
    scenario_id INTEGER NOT NULL,
    industry_branch_id INTEGER NOT NULL,
    PRIMARY KEY (scenario_id, industry_branch_id),
    FOREIGN KEY (scenario_id) REFERENCES scenarios(id),
    FOREIGN KEY (industry_branch_id) REFERENCES industry_branches(id)
);

CREATE TABLE scenario_departments (
    scenario_id INTEGER NOT NULL,
    department_id INTEGER NOT NULL,
    PRIMARY KEY (scenario_id, department_id),
    FOREIGN KEY (scenario_id) REFERENCES scenarios(id),
    FOREIGN KEY (department_id) REFERENCES departments(id)
);

CREATE TABLE scenario_pains (
    scenario_id INTEGER NOT NULL,
    pain_point_id INTEGER NOT NULL,
    PRIMARY KEY (scenario_id, pain_point_id),
    FOREIGN KEY (scenario_id) REFERENCES scenarios(id),
    FOREIGN KEY (pain_point_id) REFERENCES pain_points(id)
);

CREATE TABLE scenario_budget_options (
    scenario_id INTEGER NOT NULL,
    budget_code TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (scenario_id, budget_code),
    FOREIGN KEY (scenario_id) REFERENCES scenarios(id)
);

CREATE TABLE service_deliverables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    service_id INTEGER NOT NULL,
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
    service_id INTEGER NOT NULL,
    PRIMARY KEY (scenario_id, service_id),
    FOREIGN KEY (scenario_id) REFERENCES scenarios(id),
    FOREIGN KEY (service_id) REFERENCES services(id)
);

CREATE TABLE assessment_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    pain_min_selections INTEGER NOT NULL DEFAULT 1,
    pain_max_selections INTEGER NOT NULL DEFAULT 3,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK(status IN ('draft', 'published', 'archived')),
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    published_at TEXT,
    CHECK(pain_min_selections >= 0),
    CHECK(pain_min_selections <= pain_max_selections)
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

CREATE TABLE assessment_branch_weights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_version_id INTEGER NOT NULL,
    industry_id INTEGER NOT NULL,
    business_value_weight INTEGER NOT NULL,
    process_weight INTEGER NOT NULL,
    data_weight INTEGER NOT NULL,
    systems_weight INTEGER NOT NULL,
    organization_weight INTEGER NOT NULL,
    delivery_weight INTEGER NOT NULL,
    UNIQUE (assessment_version_id, industry_id),
    FOREIGN KEY (assessment_version_id) REFERENCES assessment_versions(id),
    FOREIGN KEY (industry_id) REFERENCES industries(id),
    CHECK(business_value_weight + process_weight + data_weight + systems_weight
          + organization_weight + delivery_weight = 100)
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
