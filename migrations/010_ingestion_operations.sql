CREATE TABLE ingestion_fetch_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_code TEXT NOT NULL CHECK(
        length(source_code) BETWEEN 1 AND 64 AND
        source_code GLOB '[a-z0-9]*' AND
        source_code NOT GLOB '*[^a-z0-9_-]*'
    ),
    source_name TEXT NOT NULL CHECK(length(source_name) BETWEEN 1 AND 200),
    outcome_code TEXT NOT NULL CHECK(outcome_code IN ('succeeded', 'failed')),
    error_code TEXT CHECK(
        error_code IS NULL OR (
            length(error_code) BETWEEN 1 AND 64 AND
            error_code GLOB '[a-z0-9]*' AND
            error_code NOT GLOB '*[^a-z0-9_-]*'
        )
    ),
    fetched_count INTEGER NOT NULL DEFAULT 0 CHECK(fetched_count >= 0),
    started_at TEXT NOT NULL CHECK(
        length(started_at) = 19 AND
        started_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
    ),
    completed_at TEXT NOT NULL CHECK(
        length(completed_at) = 19 AND
        completed_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
    ),
    created_at TEXT NOT NULL CHECK(
        length(created_at) = 19 AND
        created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
    ),
    CHECK(
        (outcome_code = 'succeeded' AND error_code IS NULL) OR
        (outcome_code = 'failed' AND error_code IS NOT NULL AND fetched_count = 0)
    )
);

CREATE TABLE ingestion_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_code TEXT NOT NULL CHECK(
        length(source_code) BETWEEN 1 AND 64 AND
        source_code GLOB '[a-z0-9]*' AND
        source_code NOT GLOB '*[^a-z0-9_-]*'
    ),
    source_name TEXT NOT NULL CHECK(length(source_name) BETWEEN 1 AND 200),
    canonical_url TEXT NOT NULL CHECK(
        length(canonical_url) BETWEEN 1 AND 2048 AND
        (canonical_url LIKE 'https://%' OR canonical_url LIKE 'http://%')
    ),
    content_sha256 TEXT NOT NULL CHECK(
        length(content_sha256) = 64 AND
        content_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 300),
    licensed_summary TEXT NOT NULL CHECK(length(licensed_summary) <= 2000),
    body_html TEXT CHECK(body_html IS NULL OR length(CAST(body_html AS BLOB)) <= 262144),
    original_published_at TEXT CHECK(
        original_published_at IS NULL OR (
            length(original_published_at) = 19 AND
            original_published_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
        )
    ),
    state TEXT NOT NULL DEFAULT 'fetched' CHECK(
        state IN ('fetched', 'pending_review', 'accepted', 'rejected')
    ),
    rejection_code TEXT CHECK(rejection_code IS NULL OR rejection_code IN (
        'duplicate', 'irrelevant', 'outdated', 'licensing_restricted',
        'unsafe_content', 'insufficient_evidence'
    )),
    rejection_note TEXT CHECK(rejection_note IS NULL OR length(rejection_note) <= 500),
    lock_version INTEGER NOT NULL DEFAULT 1 CHECK(lock_version > 0),
    target_content_id INTEGER REFERENCES content_items(id),
    created_at TEXT NOT NULL CHECK(
        length(created_at) = 19 AND
        created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
    ),
    updated_at TEXT NOT NULL CHECK(
        length(updated_at) = 19 AND
        updated_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
    ),
    CHECK(
        (state IN ('fetched', 'pending_review') AND rejection_code IS NULL
            AND rejection_note IS NULL AND target_content_id IS NULL) OR
        (state = 'accepted' AND rejection_code IS NULL
            AND rejection_note IS NULL AND target_content_id IS NOT NULL) OR
        (state = 'rejected' AND rejection_code IS NOT NULL
            AND target_content_id IS NULL)
    )
);

CREATE UNIQUE INDEX unique_ingestion_candidate_canonical_url
ON ingestion_candidates(canonical_url);

CREATE UNIQUE INDEX unique_ingestion_candidate_content_sha256
ON ingestion_candidates(content_sha256);

CREATE TRIGGER require_new_ingestion_candidate_fetched
BEFORE INSERT ON ingestion_candidates
WHEN
    NEW.state <> 'fetched' OR
    NEW.lock_version <> 1 OR
    NEW.rejection_code IS NOT NULL OR
    NEW.rejection_note IS NOT NULL OR
    NEW.target_content_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'invalid ingestion candidate initial state');
END;

CREATE TRIGGER validate_ingestion_candidate_state_transition
BEFORE UPDATE OF state ON ingestion_candidates
WHEN NEW.state IS NOT OLD.state AND NOT (
    (OLD.state = 'fetched' AND NEW.state = 'pending_review') OR
    (OLD.state = 'pending_review' AND NEW.state IN ('accepted', 'rejected'))
)
BEGIN
    SELECT RAISE(ABORT, 'invalid ingestion candidate transition');
END;

CREATE TABLE governance_audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL CHECK(
        length(action) BETWEEN 1 AND 64 AND
        action GLOB '[a-z0-9]*' AND
        action NOT GLOB '*[^a-z0-9_-]*'
    ),
    target_type TEXT NOT NULL CHECK(
        length(target_type) BETWEEN 1 AND 64 AND
        target_type GLOB '[a-z0-9]*' AND
        target_type NOT GLOB '*[^a-z0-9_-]*'
    ),
    target_id INTEGER NOT NULL CHECK(target_id > 0),
    actor TEXT NOT NULL CHECK(
        typeof(actor) = 'text' AND
        length(actor) BETWEEN 3 AND 64 AND
        length(CAST(actor AS BLOB)) = length(actor) AND
        instr(actor, char(0)) = 0 AND
        actor NOT GLOB '*[^A-Za-z0-9_.-]*' AND
        NOT (
            length(replace(replace(replace(actor, '-', ''), '_', ''), '.', ''))
                BETWEEN 7 AND 20 AND
            replace(replace(replace(actor, '-', ''), '_', ''), '.', '')
                NOT GLOB '*[^0-9]*'
        ) AND
        lower(actor) NOT GLOB '*.7z' AND
        lower(actor) NOT GLOB '*.bat' AND
        lower(actor) NOT GLOB '*.cmd' AND
        lower(actor) NOT GLOB '*.csv' AND
        lower(actor) NOT GLOB '*.db' AND
        lower(actor) NOT GLOB '*.doc' AND
        lower(actor) NOT GLOB '*.docx' AND
        lower(actor) NOT GLOB '*.exe' AND
        lower(actor) NOT GLOB '*.gif' AND
        lower(actor) NOT GLOB '*.gz' AND
        lower(actor) NOT GLOB '*.htm' AND
        lower(actor) NOT GLOB '*.html' AND
        lower(actor) NOT GLOB '*.jpeg' AND
        lower(actor) NOT GLOB '*.jpg' AND
        lower(actor) NOT GLOB '*.js' AND
        lower(actor) NOT GLOB '*.json' AND
        lower(actor) NOT GLOB '*.log' AND
        lower(actor) NOT GLOB '*.pdf' AND
        lower(actor) NOT GLOB '*.png' AND
        lower(actor) NOT GLOB '*.ps1' AND
        lower(actor) NOT GLOB '*.py' AND
        lower(actor) NOT GLOB '*.sh' AND
        lower(actor) NOT GLOB '*.sql' AND
        lower(actor) NOT GLOB '*.sqlite' AND
        lower(actor) NOT GLOB '*.svg' AND
        lower(actor) NOT GLOB '*.tar' AND
        lower(actor) NOT GLOB '*.txt' AND
        lower(actor) NOT GLOB '*.xls' AND
        lower(actor) NOT GLOB '*.xlsx' AND
        lower(actor) NOT GLOB '*.xml' AND
        lower(actor) NOT GLOB '*.zip'
    ),
    metadata_json TEXT CHECK(
        metadata_json IS NULL OR (
            length(CAST(metadata_json AS BLOB)) <= 2000 AND json_valid(metadata_json)
        )
    ),
    created_at TEXT NOT NULL CHECK(
        length(created_at) = 19 AND
        created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
    )
);

CREATE TRIGGER prevent_sensitive_governance_audit_metadata_insert
BEFORE INSERT ON governance_audit_events
WHEN NEW.metadata_json IS NOT NULL AND (
    json_type(NEW.metadata_json) <> 'object' OR EXISTS (
        SELECT 1
        FROM json_tree(NEW.metadata_json)
        WHERE
        (typeof(key) = 'text' AND (
            length(key) NOT BETWEEN 1 AND 64 OR
            substr(key, 1, 1) NOT GLOB '[a-z0-9]' OR
            key GLOB '*[^a-z0-9_-]*' OR
            lower(key) LIKE '%body%' OR
            lower(key) LIKE '%url%' OR
            lower(key) LIKE '%filename%' OR
            lower(key) LIKE '%file_name%' OR
            lower(key) LIKE '%contact%' OR
            lower(key) LIKE '%email%' OR
            lower(key) LIKE '%phone%' OR
            lower(key) LIKE '%mobile%' OR
            lower(key) LIKE '%wechat%' OR
            lower(key) LIKE '%search%' OR
            lower(key) LIKE '%query%'
        )) OR
        (type = 'text' AND (
            length(value) NOT BETWEEN 1 AND 64 OR
            substr(value, 1, 1) NOT GLOB '[a-z0-9]' OR
            value GLOB '*[^a-z0-9_-]*' OR
            (
                length(replace(value, '-', '')) BETWEEN 7 AND 20 AND
                replace(value, '-', '') NOT GLOB '*[^0-9]*'
            )
        )) OR
        (type = 'integer' AND (value < 0 OR value > 2147483647)) OR
        type = 'real'
    )
)
BEGIN
    SELECT RAISE(ABORT, 'audit metadata contains forbidden fields');
END;

CREATE TRIGGER prevent_sensitive_governance_audit_metadata_update
BEFORE UPDATE OF metadata_json ON governance_audit_events
WHEN NEW.metadata_json IS NOT NULL AND (
    json_type(NEW.metadata_json) <> 'object' OR EXISTS (
        SELECT 1
        FROM json_tree(NEW.metadata_json)
        WHERE
        (typeof(key) = 'text' AND (
            length(key) NOT BETWEEN 1 AND 64 OR
            substr(key, 1, 1) NOT GLOB '[a-z0-9]' OR
            key GLOB '*[^a-z0-9_-]*' OR
            lower(key) LIKE '%body%' OR
            lower(key) LIKE '%url%' OR
            lower(key) LIKE '%filename%' OR
            lower(key) LIKE '%file_name%' OR
            lower(key) LIKE '%contact%' OR
            lower(key) LIKE '%email%' OR
            lower(key) LIKE '%phone%' OR
            lower(key) LIKE '%mobile%' OR
            lower(key) LIKE '%wechat%' OR
            lower(key) LIKE '%search%' OR
            lower(key) LIKE '%query%'
        )) OR
        (type = 'text' AND (
            length(value) NOT BETWEEN 1 AND 64 OR
            substr(value, 1, 1) NOT GLOB '[a-z0-9]' OR
            value GLOB '*[^a-z0-9_-]*' OR
            (
                length(replace(value, '-', '')) BETWEEN 7 AND 20 AND
                replace(value, '-', '') NOT GLOB '*[^0-9]*'
            )
        )) OR
        (type = 'integer' AND (value < 0 OR value > 2147483647)) OR
        type = 'real'
    )
)
BEGIN
    SELECT RAISE(ABORT, 'audit metadata contains forbidden fields');
END;
