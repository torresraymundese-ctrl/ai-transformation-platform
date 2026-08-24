CREATE TABLE media_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    storage_name TEXT NOT NULL UNIQUE
        CHECK(length(storage_name) BETWEEN 1 AND 255)
        CHECK(instr(storage_name, '/') = 0 AND instr(storage_name, char(92)) = 0),
    display_name TEXT NOT NULL CHECK(length(display_name) BETWEEN 1 AND 255),
    detected_mime TEXT NOT NULL CHECK(detected_mime IN (
        'image/jpeg', 'image/png', 'image/webp', 'application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )),
    byte_size INTEGER NOT NULL CHECK(byte_size > 0),
    sha256 TEXT NOT NULL
        CHECK(length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
    scan_result_code TEXT,
    scan_checked_at TEXT
        CHECK(scan_checked_at IS NULL OR (
            length(scan_checked_at) = 19 AND
            scan_checked_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
        )),
    status TEXT NOT NULL CHECK(status IN ('pending', 'ready', 'archived')),
    created_at TEXT NOT NULL CHECK(
        length(created_at) = 19 AND
        created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
    ),
    ready_at TEXT
        CHECK(ready_at IS NULL OR (
            length(ready_at) = 19 AND
            ready_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
        )),
    archived_at TEXT
        CHECK(archived_at IS NULL OR (
            length(archived_at) = 19 AND
            archived_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
        )),
    updated_at TEXT NOT NULL CHECK(
        length(updated_at) = 19 AND
        updated_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
    ),
    CHECK(
        (status = 'pending' AND ready_at IS NULL AND archived_at IS NULL) OR
        (status = 'ready' AND ready_at IS NOT NULL AND archived_at IS NULL
            AND scan_result_code IS NOT NULL AND scan_checked_at IS NOT NULL) OR
        (status = 'archived' AND archived_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX active_media_sha256_unique
ON media_assets(sha256) WHERE status IN ('pending', 'ready');

CREATE TRIGGER prevent_media_storage_name_update
BEFORE UPDATE OF storage_name ON media_assets
WHEN NEW.storage_name <> OLD.storage_name
BEGIN
    SELECT RAISE(ABORT, 'media storage name is immutable');
END;

CREATE TRIGGER enforce_media_status_transition
BEFORE UPDATE OF status ON media_assets
WHEN NEW.status <> OLD.status AND NOT (
    (OLD.status = 'pending' AND NEW.status IN ('ready', 'archived')) OR
    (OLD.status = 'ready' AND NEW.status = 'archived')
)
BEGIN
    SELECT RAISE(ABORT, 'invalid media status transition');
END;

CREATE TRIGGER freeze_ready_media_identity
BEFORE UPDATE ON media_assets
WHEN OLD.ready_at IS NOT NULL AND (
    NEW.storage_name IS NOT OLD.storage_name OR
    NEW.detected_mime IS NOT OLD.detected_mime OR
    NEW.byte_size IS NOT OLD.byte_size OR
    NEW.sha256 IS NOT OLD.sha256 OR
    NEW.scan_result_code IS NOT OLD.scan_result_code OR
    NEW.ready_at IS NOT OLD.ready_at
)
BEGIN
    SELECT RAISE(ABORT, 'ready media identity is immutable');
END;

CREATE TABLE content_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_type TEXT NOT NULL CHECK(entry_type IN (
        'industry', 'scenario', 'service', 'case', 'resource', 'announcement'
    )),
    industry_id INTEGER UNIQUE,
    scenario_id INTEGER UNIQUE,
    service_id INTEGER UNIQUE,
    canonical_slug TEXT NOT NULL CHECK(length(canonical_slug) BETWEEN 1 AND 80),
    created_at TEXT NOT NULL CHECK(
        length(created_at) = 19 AND
        created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
    ),
    updated_at TEXT NOT NULL CHECK(
        length(updated_at) = 19 AND
        updated_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
    ),
    UNIQUE(entry_type, canonical_slug),
    FOREIGN KEY (industry_id) REFERENCES industries(id),
    FOREIGN KEY (scenario_id) REFERENCES scenarios(id),
    FOREIGN KEY (service_id) REFERENCES services(id),
    CHECK(
        (entry_type = 'industry' AND industry_id IS NOT NULL
            AND scenario_id IS NULL AND service_id IS NULL) OR
        (entry_type = 'scenario' AND scenario_id IS NOT NULL
            AND industry_id IS NULL AND service_id IS NULL) OR
        (entry_type = 'service' AND service_id IS NOT NULL
            AND industry_id IS NULL AND scenario_id IS NULL) OR
        (entry_type IN ('case', 'resource', 'announcement')
            AND industry_id IS NULL AND scenario_id IS NULL AND service_id IS NULL)
    )
);

CREATE TRIGGER prevent_content_group_identity_update
BEFORE UPDATE OF entry_type, industry_id, scenario_id, service_id ON content_groups
WHEN NEW.entry_type IS NOT OLD.entry_type
    OR NEW.industry_id IS NOT OLD.industry_id
    OR NEW.scenario_id IS NOT OLD.scenario_id
    OR NEW.service_id IS NOT OLD.service_id
BEGIN
    SELECT RAISE(ABORT, 'content group identity is immutable');
END;

CREATE TABLE content_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_group_id INTEGER NOT NULL,
    entry_type TEXT NOT NULL CHECK(entry_type IN (
        'industry', 'scenario', 'service', 'case', 'resource', 'announcement'
    )),
    revision_number INTEGER NOT NULL CHECK(revision_number > 0),
    slug TEXT NOT NULL CHECK(length(slug) BETWEEN 1 AND 80),
    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 120),
    summary TEXT NOT NULL CHECK(length(summary) BETWEEN 1 AND 300),
    seo_title TEXT NOT NULL CHECK(length(seo_title) BETWEEN 1 AND 60),
    seo_description TEXT NOT NULL CHECK(length(seo_description) BETWEEN 1 AND 160),
    share_image_media_id INTEGER,
    status TEXT NOT NULL CHECK(status IN ('draft', 'published', 'archived')),
    publish_at TEXT
        CHECK(publish_at IS NULL OR (
            length(publish_at) = 19 AND
            publish_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
        )),
    published_at TEXT
        CHECK(published_at IS NULL OR (
            length(published_at) = 19 AND
            published_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
        )),
    archived_at TEXT
        CHECK(archived_at IS NULL OR (
            length(archived_at) = 19 AND
            archived_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
        )),
    lock_version INTEGER NOT NULL CHECK(lock_version > 0),
    created_at TEXT NOT NULL CHECK(
        length(created_at) = 19 AND
        created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
    ),
    updated_at TEXT NOT NULL CHECK(
        length(updated_at) = 19 AND
        updated_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
    ),
    UNIQUE(content_group_id, revision_number),
    FOREIGN KEY (content_group_id) REFERENCES content_groups(id),
    FOREIGN KEY (share_image_media_id) REFERENCES media_assets(id),
    CHECK(
        (status = 'draft' AND published_at IS NULL AND archived_at IS NULL) OR
        (status = 'published' AND published_at IS NOT NULL AND archived_at IS NULL) OR
        (status = 'archived' AND archived_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX one_draft_content_revision
ON content_items(content_group_id) WHERE status = 'draft';

CREATE UNIQUE INDEX one_published_content_revision
ON content_items(content_group_id) WHERE status = 'published';

CREATE UNIQUE INDEX one_public_slug_per_type
ON content_items(entry_type, slug) WHERE status = 'published';

CREATE INDEX content_items_group_status
ON content_items(content_group_id, status);

CREATE TRIGGER require_new_content_item_draft
BEFORE INSERT ON content_items
WHEN NEW.status <> 'draft'
BEGIN
    SELECT RAISE(ABORT, 'new content revision must be draft');
END;

CREATE TRIGGER check_content_item_entry_type_insert
BEFORE INSERT ON content_items
WHEN NOT EXISTS (
    SELECT 1 FROM content_groups
    WHERE id = NEW.content_group_id AND entry_type = NEW.entry_type
)
BEGIN
    SELECT RAISE(ABORT, 'content item entry type does not match group');
END;

CREATE TRIGGER check_content_item_entry_type_update
BEFORE UPDATE OF content_group_id, entry_type ON content_items
WHEN NOT EXISTS (
    SELECT 1 FROM content_groups
    WHERE id = NEW.content_group_id AND entry_type = NEW.entry_type
)
BEGIN
    SELECT RAISE(ABORT, 'content item entry type does not match group');
END;

CREATE TRIGGER enforce_content_item_status_transition
BEFORE UPDATE OF status ON content_items
WHEN NEW.status <> OLD.status AND NOT (
    (OLD.status = 'draft' AND NEW.status = 'published') OR
    (OLD.status = 'published' AND NEW.status = 'archived')
)
BEGIN
    SELECT RAISE(ABORT, 'invalid content status transition');
END;

CREATE TRIGGER prevent_published_content_edit
BEFORE UPDATE ON content_items
WHEN OLD.status = 'published' AND (
    NEW.content_group_id IS NOT OLD.content_group_id OR
    NEW.entry_type IS NOT OLD.entry_type OR
    NEW.revision_number IS NOT OLD.revision_number OR
    NEW.slug IS NOT OLD.slug OR
    NEW.title IS NOT OLD.title OR
    NEW.summary IS NOT OLD.summary OR
    NEW.seo_title IS NOT OLD.seo_title OR
    NEW.seo_description IS NOT OLD.seo_description OR
    NEW.share_image_media_id IS NOT OLD.share_image_media_id OR
    NEW.publish_at IS NOT OLD.publish_at OR
    NEW.published_at IS NOT OLD.published_at OR
    (NEW.status = OLD.status AND (
        NEW.archived_at IS NOT OLD.archived_at OR
        NEW.lock_version IS NOT OLD.lock_version
    ))
)
BEGIN
    SELECT RAISE(ABORT, 'published content is immutable');
END;

CREATE TRIGGER prevent_archived_content_edit
BEFORE UPDATE ON content_items
WHEN OLD.status = 'archived'
BEGIN
    SELECT RAISE(ABORT, 'archived content is immutable');
END;

CREATE TABLE industry_content (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_item_id INTEGER NOT NULL UNIQUE,
    industry_id INTEGER NOT NULL,
    FOREIGN KEY (content_item_id) REFERENCES content_items(id),
    FOREIGN KEY (industry_id) REFERENCES industries(id)
);

CREATE TABLE scenario_content (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_item_id INTEGER NOT NULL UNIQUE,
    scenario_id INTEGER NOT NULL,
    FOREIGN KEY (content_item_id) REFERENCES content_items(id),
    FOREIGN KEY (scenario_id) REFERENCES scenarios(id)
);

CREATE TABLE service_content (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_item_id INTEGER NOT NULL UNIQUE,
    service_id INTEGER NOT NULL,
    FOREIGN KEY (content_item_id) REFERENCES content_items(id),
    FOREIGN KEY (service_id) REFERENCES services(id)
);

CREATE TABLE case_content (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_item_id INTEGER NOT NULL UNIQUE,
    verification_code TEXT NOT NULL CHECK(length(verification_code) BETWEEN 1 AND 64),
    is_anonymized INTEGER NOT NULL DEFAULT 0 CHECK(is_anonymized IN (0, 1)),
    basis_type TEXT NOT NULL CHECK(basis_type IN ('public_source', 'private_authorization')),
    private_basis_reference TEXT CHECK(
        private_basis_reference IS NULL OR length(private_basis_reference) BETWEEN 1 AND 300
    ),
    source_url TEXT CHECK(source_url IS NULL OR source_url LIKE 'https://%'),
    source_url_sha256 TEXT CHECK(
        source_url_sha256 IS NULL OR (
            length(source_url_sha256) = 64 AND source_url_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    source_check_code TEXT,
    source_checked_at TEXT CHECK(source_checked_at IS NULL OR (
        length(source_checked_at) = 19 AND
        source_checked_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
    )),
    source_check_expires_at TEXT CHECK(source_check_expires_at IS NULL OR (
        length(source_check_expires_at) = 19 AND
        source_check_expires_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
    )),
    source_check_url_sha256 TEXT CHECK(
        source_check_url_sha256 IS NULL OR (
            length(source_check_url_sha256) = 64 AND
            source_check_url_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    is_verified INTEGER NOT NULL DEFAULT 0 CHECK(is_verified IN (0, 1)),
    review_confirmed INTEGER NOT NULL DEFAULT 0 CHECK(review_confirmed IN (0, 1)),
    verified_at TEXT CHECK(verified_at IS NULL OR (
        length(verified_at) = 19 AND
        verified_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
    )),
    FOREIGN KEY (content_item_id) REFERENCES content_items(id),
    CHECK(
        (basis_type = 'public_source' AND source_url IS NOT NULL
            AND source_url_sha256 IS NOT NULL) OR
        (basis_type = 'private_authorization' AND private_basis_reference IS NOT NULL)
    ),
    CHECK(
        (source_check_code IS NULL AND source_checked_at IS NULL
            AND source_check_expires_at IS NULL AND source_check_url_sha256 IS NULL) OR
        (source_check_code IS NOT NULL AND source_checked_at IS NOT NULL
            AND source_check_expires_at IS NOT NULL AND source_check_url_sha256 IS NOT NULL)
    )
);

CREATE TABLE case_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_content_item_id INTEGER NOT NULL,
    name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 120),
    before_value TEXT NOT NULL CHECK(length(before_value) BETWEEN 1 AND 120),
    after_value TEXT NOT NULL CHECK(length(after_value) BETWEEN 1 AND 120),
    unit TEXT NOT NULL CHECK(length(unit) BETWEEN 1 AND 40),
    statistical_period TEXT NOT NULL CHECK(length(statistical_period) BETWEEN 1 AND 120),
    evidence_explanation TEXT NOT NULL CHECK(length(evidence_explanation) BETWEEN 1 AND 1000),
    sort_order INTEGER NOT NULL DEFAULT 0 CHECK(sort_order >= 0),
    FOREIGN KEY (case_content_item_id) REFERENCES content_items(id)
);

CREATE TABLE resource_content (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_item_id INTEGER NOT NULL UNIQUE,
    resource_type TEXT NOT NULL CHECK(resource_type IN (
        'article', 'guide', 'report', 'template', 'policy'
    )),
    is_original INTEGER NOT NULL CHECK(is_original IN (0, 1)),
    source_name TEXT CHECK(source_name IS NULL OR length(source_name) BETWEEN 1 AND 200),
    source_url TEXT CHECK(source_url IS NULL OR source_url LIKE 'https://%'),
    source_url_sha256 TEXT CHECK(
        source_url_sha256 IS NULL OR (
            length(source_url_sha256) = 64 AND source_url_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    source_check_code TEXT,
    source_checked_at TEXT CHECK(source_checked_at IS NULL OR (
        length(source_checked_at) = 19 AND
        source_checked_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
    )),
    source_check_expires_at TEXT CHECK(source_check_expires_at IS NULL OR (
        length(source_check_expires_at) = 19 AND
        source_check_expires_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
    )),
    source_check_url_sha256 TEXT CHECK(
        source_check_url_sha256 IS NULL OR (
            length(source_check_url_sha256) = 64 AND
            source_check_url_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    original_published_at TEXT CHECK(original_published_at IS NULL OR (
        length(original_published_at) = 19 AND
        original_published_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
    )),
    copyright_notice TEXT CHECK(
        copyright_notice IS NULL OR length(copyright_notice) BETWEEN 1 AND 500
    ),
    attachment_media_id INTEGER,
    FOREIGN KEY (content_item_id) REFERENCES content_items(id),
    FOREIGN KEY (attachment_media_id) REFERENCES media_assets(id),
    CHECK(
        (source_check_code IS NULL AND source_checked_at IS NULL
            AND source_check_expires_at IS NULL AND source_check_url_sha256 IS NULL) OR
        (source_check_code IS NOT NULL AND source_checked_at IS NOT NULL
            AND source_check_expires_at IS NOT NULL AND source_check_url_sha256 IS NOT NULL)
    )
);

CREATE TABLE announcement_content (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_item_id INTEGER NOT NULL UNIQUE,
    valid_from TEXT CHECK(valid_from IS NULL OR (
        length(valid_from) = 19 AND
        valid_from GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
    )),
    valid_until TEXT CHECK(valid_until IS NULL OR (
        length(valid_until) = 19 AND
        valid_until GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
    )),
    cta_url TEXT CHECK(
        cta_url IS NULL OR cta_url LIKE 'https://%' OR
        (cta_url LIKE '/%' AND cta_url NOT LIKE '//%')
    ),
    FOREIGN KEY (content_item_id) REFERENCES content_items(id),
    CHECK(valid_from IS NULL OR valid_until IS NULL OR valid_from <= valid_until)
);

CREATE TABLE content_blocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_item_id INTEGER NOT NULL,
    block_type TEXT NOT NULL CHECK(block_type IN (
        'heading', 'rich_text', 'image_text', 'metric', 'steps', 'download', 'cta'
    )),
    title TEXT CHECK(title IS NULL OR length(title) <= 120),
    body_html TEXT CHECK(body_html IS NULL OR length(CAST(body_html AS BLOB)) <= 20000),
    settings_json TEXT CHECK(
        settings_json IS NULL OR (
            length(CAST(settings_json AS BLOB)) <= 2000 AND json_valid(settings_json)
        )
    ),
    media_asset_id INTEGER,
    sort_order INTEGER NOT NULL DEFAULT 0 CHECK(sort_order >= 0),
    FOREIGN KEY (content_item_id) REFERENCES content_items(id),
    FOREIGN KEY (media_asset_id) REFERENCES media_assets(id),
    UNIQUE(content_item_id, sort_order),
    CHECK(media_asset_id IS NULL OR block_type IN ('image_text', 'download'))
);

CREATE TABLE content_maturity_levels (
    content_item_id INTEGER NOT NULL,
    maturity_code TEXT NOT NULL CHECK(maturity_code IN (
        'explore', 'pilot', 'scale', 'collaborate'
    )),
    sort_order INTEGER NOT NULL DEFAULT 0 CHECK(sort_order >= 0),
    PRIMARY KEY (content_item_id, maturity_code),
    UNIQUE(content_item_id, sort_order),
    FOREIGN KEY (content_item_id) REFERENCES content_items(id)
);

CREATE TABLE content_slug_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_type TEXT NOT NULL CHECK(entry_type IN (
        'industry', 'scenario', 'service', 'case', 'resource', 'announcement'
    )),
    old_slug TEXT NOT NULL CHECK(length(old_slug) BETWEEN 1 AND 80),
    content_group_id INTEGER NOT NULL,
    created_at TEXT NOT NULL CHECK(
        length(created_at) = 19 AND
        created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
    ),
    UNIQUE(entry_type, old_slug),
    FOREIGN KEY (content_group_id) REFERENCES content_groups(id)
);

CREATE TRIGGER validate_content_slug_alias_insert
BEFORE INSERT ON content_slug_aliases
WHEN NOT EXISTS (
        SELECT 1 FROM content_groups
        WHERE id = NEW.content_group_id AND entry_type = NEW.entry_type
    ) OR EXISTS (
        SELECT 1 FROM content_groups
        WHERE entry_type = NEW.entry_type AND canonical_slug = NEW.old_slug
    )
BEGIN
    SELECT RAISE(ABORT, 'content slug alias conflicts with group identity');
END;

CREATE TRIGGER validate_content_slug_alias_update
BEFORE UPDATE OF entry_type, old_slug, content_group_id ON content_slug_aliases
WHEN NOT EXISTS (
        SELECT 1 FROM content_groups
        WHERE id = NEW.content_group_id AND entry_type = NEW.entry_type
    ) OR EXISTS (
        SELECT 1 FROM content_groups
        WHERE entry_type = NEW.entry_type AND canonical_slug = NEW.old_slug
    )
BEGIN
    SELECT RAISE(ABORT, 'content slug alias conflicts with group identity');
END;

CREATE TRIGGER prevent_canonical_slug_alias_collision_insert
BEFORE INSERT ON content_groups
WHEN EXISTS (
    SELECT 1 FROM content_slug_aliases
    WHERE entry_type = NEW.entry_type AND old_slug = NEW.canonical_slug
)
BEGIN
    SELECT RAISE(ABORT, 'canonical slug conflicts with alias');
END;

CREATE TRIGGER prevent_canonical_slug_alias_collision_update
BEFORE UPDATE OF entry_type, canonical_slug ON content_groups
WHEN EXISTS (
    SELECT 1 FROM content_slug_aliases
    WHERE entry_type = NEW.entry_type AND old_slug = NEW.canonical_slug
)
BEGIN
    SELECT RAISE(ABORT, 'canonical slug conflicts with alias');
END;

CREATE TABLE scenario_cases (
    scenario_content_item_id INTEGER NOT NULL,
    case_content_group_id INTEGER NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0 CHECK(sort_order >= 0),
    PRIMARY KEY (scenario_content_item_id, case_content_group_id),
    UNIQUE(scenario_content_item_id, sort_order),
    FOREIGN KEY (scenario_content_item_id) REFERENCES content_items(id),
    FOREIGN KEY (case_content_group_id) REFERENCES content_groups(id)
);

CREATE TABLE scenario_resources (
    scenario_content_item_id INTEGER NOT NULL,
    resource_content_group_id INTEGER NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0 CHECK(sort_order >= 0),
    PRIMARY KEY (scenario_content_item_id, resource_content_group_id),
    UNIQUE(scenario_content_item_id, sort_order),
    FOREIGN KEY (scenario_content_item_id) REFERENCES content_items(id),
    FOREIGN KEY (resource_content_group_id) REFERENCES content_groups(id)
);

CREATE TABLE service_cases (
    service_content_item_id INTEGER NOT NULL,
    case_content_group_id INTEGER NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0 CHECK(sort_order >= 0),
    PRIMARY KEY (service_content_item_id, case_content_group_id),
    UNIQUE(service_content_item_id, sort_order),
    FOREIGN KEY (service_content_item_id) REFERENCES content_items(id),
    FOREIGN KEY (case_content_group_id) REFERENCES content_groups(id)
);

CREATE TABLE service_resources (
    service_content_item_id INTEGER NOT NULL,
    resource_content_group_id INTEGER NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0 CHECK(sort_order >= 0),
    PRIMARY KEY (service_content_item_id, resource_content_group_id),
    UNIQUE(service_content_item_id, sort_order),
    FOREIGN KEY (service_content_item_id) REFERENCES content_items(id),
    FOREIGN KEY (resource_content_group_id) REFERENCES content_groups(id)
);

CREATE TABLE industry_cases (
    industry_content_item_id INTEGER NOT NULL,
    case_content_group_id INTEGER NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0 CHECK(sort_order >= 0),
    PRIMARY KEY (industry_content_item_id, case_content_group_id),
    UNIQUE(industry_content_item_id, sort_order),
    FOREIGN KEY (industry_content_item_id) REFERENCES content_items(id),
    FOREIGN KEY (case_content_group_id) REFERENCES content_groups(id)
);

CREATE TABLE industry_resources (
    industry_content_item_id INTEGER NOT NULL,
    resource_content_group_id INTEGER NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0 CHECK(sort_order >= 0),
    PRIMARY KEY (industry_content_item_id, resource_content_group_id),
    UNIQUE(industry_content_item_id, sort_order),
    FOREIGN KEY (industry_content_item_id) REFERENCES content_items(id),
    FOREIGN KEY (resource_content_group_id) REFERENCES content_groups(id)
);

CREATE TABLE content_audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_item_id INTEGER,
    event_code TEXT NOT NULL CHECK(length(event_code) BETWEEN 1 AND 80),
    actor_text TEXT NOT NULL CHECK(length(actor_text) BETWEEN 1 AND 200),
    details_json TEXT CHECK(details_json IS NULL OR json_valid(details_json)),
    created_at TEXT NOT NULL CHECK(
        length(created_at) = 19 AND
        created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
    ),
    FOREIGN KEY (content_item_id) REFERENCES content_items(id)
);

CREATE TABLE legacy_content_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_table TEXT NOT NULL CHECK(source_table IN (
        'services', 'cases', 'articles', 'announcements'
    )),
    source_id INTEGER NOT NULL CHECK(source_id > 0),
    title_summary TEXT NOT NULL CHECK(length(title_summary) BETWEEN 1 AND 300),
    source_checksum TEXT NOT NULL CHECK(
        length(source_checksum) = 64 AND source_checksum NOT GLOB '*[^0-9a-f]*'
    ),
    proposed_action TEXT NOT NULL CHECK(proposed_action IN (
        'keep', 'clean', 'archive', 'delete_later'
    )),
    reason_code TEXT NOT NULL CHECK(length(reason_code) BETWEEN 1 AND 80),
    decision_action TEXT CHECK(decision_action IS NULL OR decision_action IN (
        'keep', 'clean', 'archive', 'delete_later'
    )),
    decision_at TEXT CHECK(decision_at IS NULL OR (
        length(decision_at) = 19 AND
        decision_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
    )),
    decision_source_checksum TEXT CHECK(
        decision_source_checksum IS NULL OR (
            length(decision_source_checksum) = 64 AND
            decision_source_checksum NOT GLOB '*[^0-9a-f]*'
        )
    ),
    source_state TEXT NOT NULL CHECK(source_state IN (
        'reachable', 'unreachable', 'invalid', 'missing', 'unchecked'
    )),
    source_check_code TEXT,
    source_checked_at TEXT CHECK(source_checked_at IS NULL OR (
        length(source_checked_at) = 19 AND
        source_checked_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
    )),
    source_check_expires_at TEXT CHECK(source_check_expires_at IS NULL OR (
        length(source_check_expires_at) = 19 AND
        source_check_expires_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
    )),
    check_source_checksum TEXT CHECK(
        check_source_checksum IS NULL OR (
            length(check_source_checksum) = 64 AND
            check_source_checksum NOT GLOB '*[^0-9a-f]*'
        )
    ),
    review_stale_at TEXT CHECK(review_stale_at IS NULL OR (
        length(review_stale_at) = 19 AND
        review_stale_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
    )),
    target_type TEXT CHECK(target_type IS NULL OR target_type IN (
        'industry', 'scenario', 'service', 'case', 'resource', 'announcement'
    )),
    target_group TEXT CHECK(target_group IS NULL OR length(target_group) BETWEEN 1 AND 200),
    required_confirmations_json TEXT CHECK(
        required_confirmations_json IS NULL OR json_valid(required_confirmations_json)
    ),
    target_preview_json TEXT CHECK(
        target_preview_json IS NULL OR json_valid(target_preview_json)
    ),
    source_url_display TEXT CHECK(
        source_url_display IS NULL OR (
            (source_url_display LIKE 'https://%' OR source_url_display LIKE 'http://%')
            AND instr(source_url_display, '?') = 0
            AND instr(source_url_display, '#') = 0
            AND instr(source_url_display, '@') = 0
        )
    ),
    source_url_sha256 TEXT CHECK(
        source_url_sha256 IS NULL OR (
            length(source_url_sha256) = 64 AND
            source_url_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    created_at TEXT NOT NULL CHECK(
        length(created_at) = 19 AND
        created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
    ),
    updated_at TEXT NOT NULL CHECK(
        length(updated_at) = 19 AND
        updated_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
    ),
    UNIQUE(source_table, source_id),
    CHECK(
        (decision_action IS NULL AND decision_at IS NULL
            AND decision_source_checksum IS NULL) OR
        (decision_action IS NOT NULL AND decision_at IS NOT NULL
            AND decision_source_checksum IS NOT NULL)
    ),
    CHECK(
        (source_check_code IS NULL AND source_checked_at IS NULL
            AND source_check_expires_at IS NULL AND check_source_checksum IS NULL) OR
        (source_check_code IS NOT NULL AND source_checked_at IS NOT NULL
            AND source_check_expires_at IS NOT NULL AND check_source_checksum IS NOT NULL)
    )
);

CREATE TABLE legacy_content_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_table TEXT NOT NULL CHECK(source_table IN (
        'services', 'cases', 'articles', 'announcements'
    )),
    source_id INTEGER NOT NULL CHECK(source_id > 0),
    source_checksum TEXT NOT NULL CHECK(
        length(source_checksum) = 64 AND source_checksum NOT GLOB '*[^0-9a-f]*'
    ),
    target_content_group_id INTEGER NOT NULL,
    target_content_item_id INTEGER NOT NULL,
    created_at TEXT NOT NULL CHECK(
        length(created_at) = 19 AND
        created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
    ),
    updated_at TEXT NOT NULL CHECK(
        length(updated_at) = 19 AND
        updated_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
    ),
    UNIQUE(source_table, source_id),
    FOREIGN KEY (target_content_group_id) REFERENCES content_groups(id),
    FOREIGN KEY (target_content_item_id) REFERENCES content_items(id)
);

CREATE TRIGGER validate_industry_content_insert
BEFORE INSERT ON industry_content
WHEN NOT EXISTS (
    SELECT 1 FROM content_items ci
    JOIN content_groups cg ON cg.id = ci.content_group_id
    WHERE ci.id = NEW.content_item_id AND ci.entry_type = 'industry'
        AND cg.industry_id = NEW.industry_id
)
BEGIN
    SELECT RAISE(ABORT, 'industry extension does not match content identity');
END;

CREATE TRIGGER validate_industry_content_update
BEFORE UPDATE OF content_item_id, industry_id ON industry_content
WHEN NOT EXISTS (
    SELECT 1 FROM content_items ci
    JOIN content_groups cg ON cg.id = ci.content_group_id
    WHERE ci.id = NEW.content_item_id AND ci.entry_type = 'industry'
        AND cg.industry_id = NEW.industry_id
)
BEGIN
    SELECT RAISE(ABORT, 'industry extension does not match content identity');
END;

CREATE TRIGGER validate_scenario_content_insert
BEFORE INSERT ON scenario_content
WHEN NOT EXISTS (
    SELECT 1 FROM content_items ci
    JOIN content_groups cg ON cg.id = ci.content_group_id
    WHERE ci.id = NEW.content_item_id AND ci.entry_type = 'scenario'
        AND cg.scenario_id = NEW.scenario_id
)
BEGIN
    SELECT RAISE(ABORT, 'scenario extension does not match content identity');
END;

CREATE TRIGGER validate_scenario_content_update
BEFORE UPDATE OF content_item_id, scenario_id ON scenario_content
WHEN NOT EXISTS (
    SELECT 1 FROM content_items ci
    JOIN content_groups cg ON cg.id = ci.content_group_id
    WHERE ci.id = NEW.content_item_id AND ci.entry_type = 'scenario'
        AND cg.scenario_id = NEW.scenario_id
)
BEGIN
    SELECT RAISE(ABORT, 'scenario extension does not match content identity');
END;

CREATE TRIGGER validate_service_content_insert
BEFORE INSERT ON service_content
WHEN NOT EXISTS (
    SELECT 1 FROM content_items ci
    JOIN content_groups cg ON cg.id = ci.content_group_id
    WHERE ci.id = NEW.content_item_id AND ci.entry_type = 'service'
        AND cg.service_id = NEW.service_id
)
BEGIN
    SELECT RAISE(ABORT, 'service extension does not match content identity');
END;

CREATE TRIGGER validate_service_content_update
BEFORE UPDATE OF content_item_id, service_id ON service_content
WHEN NOT EXISTS (
    SELECT 1 FROM content_items ci
    JOIN content_groups cg ON cg.id = ci.content_group_id
    WHERE ci.id = NEW.content_item_id AND ci.entry_type = 'service'
        AND cg.service_id = NEW.service_id
)
BEGIN
    SELECT RAISE(ABORT, 'service extension does not match content identity');
END;

CREATE TRIGGER validate_case_content_insert
BEFORE INSERT ON case_content
WHEN NOT EXISTS (
    SELECT 1 FROM content_items WHERE id = NEW.content_item_id AND entry_type = 'case'
)
BEGIN
    SELECT RAISE(ABORT, 'case extension does not match content type');
END;

CREATE TRIGGER validate_case_content_update
BEFORE UPDATE OF content_item_id ON case_content
WHEN NOT EXISTS (
    SELECT 1 FROM content_items WHERE id = NEW.content_item_id AND entry_type = 'case'
)
BEGIN
    SELECT RAISE(ABORT, 'case extension does not match content type');
END;

CREATE TRIGGER validate_resource_content_insert
BEFORE INSERT ON resource_content
WHEN NOT EXISTS (
    SELECT 1 FROM content_items WHERE id = NEW.content_item_id AND entry_type = 'resource'
)
BEGIN
    SELECT RAISE(ABORT, 'resource extension does not match content type');
END;

CREATE TRIGGER validate_resource_content_update
BEFORE UPDATE OF content_item_id ON resource_content
WHEN NOT EXISTS (
    SELECT 1 FROM content_items WHERE id = NEW.content_item_id AND entry_type = 'resource'
)
BEGIN
    SELECT RAISE(ABORT, 'resource extension does not match content type');
END;

CREATE TRIGGER validate_announcement_content_insert
BEFORE INSERT ON announcement_content
WHEN NOT EXISTS (
    SELECT 1 FROM content_items WHERE id = NEW.content_item_id AND entry_type = 'announcement'
)
BEGIN
    SELECT RAISE(ABORT, 'announcement extension does not match content type');
END;

CREATE TRIGGER validate_announcement_content_update
BEFORE UPDATE OF content_item_id ON announcement_content
WHEN NOT EXISTS (
    SELECT 1 FROM content_items WHERE id = NEW.content_item_id AND entry_type = 'announcement'
)
BEGIN
    SELECT RAISE(ABORT, 'announcement extension does not match content type');
END;

CREATE TRIGGER validate_case_metric_insert
BEFORE INSERT ON case_metrics
WHEN NOT EXISTS (
    SELECT 1 FROM content_items
    WHERE id = NEW.case_content_item_id AND entry_type = 'case'
)
BEGIN
    SELECT RAISE(ABORT, 'case metric does not reference case content');
END;

CREATE TRIGGER validate_case_metric_update
BEFORE UPDATE OF case_content_item_id ON case_metrics
WHEN NOT EXISTS (
    SELECT 1 FROM content_items
    WHERE id = NEW.case_content_item_id AND entry_type = 'case'
)
BEGIN
    SELECT RAISE(ABORT, 'case metric does not reference case content');
END;

CREATE TRIGGER validate_content_relation_scenario_cases_insert
BEFORE INSERT ON scenario_cases
WHEN NOT EXISTS (
        SELECT 1 FROM content_items
        WHERE id = NEW.scenario_content_item_id AND entry_type = 'scenario'
    ) OR NOT EXISTS (
        SELECT 1 FROM content_groups
        WHERE id = NEW.case_content_group_id AND entry_type = 'case'
    )
BEGIN
    SELECT RAISE(ABORT, 'invalid scenario case relation types');
END;

CREATE TRIGGER validate_content_relation_scenario_cases_update
BEFORE UPDATE OF scenario_content_item_id, case_content_group_id ON scenario_cases
WHEN NOT EXISTS (
        SELECT 1 FROM content_items
        WHERE id = NEW.scenario_content_item_id AND entry_type = 'scenario'
    ) OR NOT EXISTS (
        SELECT 1 FROM content_groups
        WHERE id = NEW.case_content_group_id AND entry_type = 'case'
    )
BEGIN
    SELECT RAISE(ABORT, 'invalid scenario case relation types');
END;

CREATE TRIGGER validate_content_relation_scenario_resources_insert
BEFORE INSERT ON scenario_resources
WHEN NOT EXISTS (
        SELECT 1 FROM content_items
        WHERE id = NEW.scenario_content_item_id AND entry_type = 'scenario'
    ) OR NOT EXISTS (
        SELECT 1 FROM content_groups
        WHERE id = NEW.resource_content_group_id AND entry_type = 'resource'
    )
BEGIN
    SELECT RAISE(ABORT, 'invalid scenario resource relation types');
END;

CREATE TRIGGER validate_content_relation_scenario_resources_update
BEFORE UPDATE OF scenario_content_item_id, resource_content_group_id ON scenario_resources
WHEN NOT EXISTS (
        SELECT 1 FROM content_items
        WHERE id = NEW.scenario_content_item_id AND entry_type = 'scenario'
    ) OR NOT EXISTS (
        SELECT 1 FROM content_groups
        WHERE id = NEW.resource_content_group_id AND entry_type = 'resource'
    )
BEGIN
    SELECT RAISE(ABORT, 'invalid scenario resource relation types');
END;

CREATE TRIGGER validate_content_relation_service_cases_insert
BEFORE INSERT ON service_cases
WHEN NOT EXISTS (
        SELECT 1 FROM content_items
        WHERE id = NEW.service_content_item_id AND entry_type = 'service'
    ) OR NOT EXISTS (
        SELECT 1 FROM content_groups
        WHERE id = NEW.case_content_group_id AND entry_type = 'case'
    )
BEGIN
    SELECT RAISE(ABORT, 'invalid service case relation types');
END;

CREATE TRIGGER validate_content_relation_service_cases_update
BEFORE UPDATE OF service_content_item_id, case_content_group_id ON service_cases
WHEN NOT EXISTS (
        SELECT 1 FROM content_items
        WHERE id = NEW.service_content_item_id AND entry_type = 'service'
    ) OR NOT EXISTS (
        SELECT 1 FROM content_groups
        WHERE id = NEW.case_content_group_id AND entry_type = 'case'
    )
BEGIN
    SELECT RAISE(ABORT, 'invalid service case relation types');
END;

CREATE TRIGGER validate_content_relation_service_resources_insert
BEFORE INSERT ON service_resources
WHEN NOT EXISTS (
        SELECT 1 FROM content_items
        WHERE id = NEW.service_content_item_id AND entry_type = 'service'
    ) OR NOT EXISTS (
        SELECT 1 FROM content_groups
        WHERE id = NEW.resource_content_group_id AND entry_type = 'resource'
    )
BEGIN
    SELECT RAISE(ABORT, 'invalid service resource relation types');
END;

CREATE TRIGGER validate_content_relation_service_resources_update
BEFORE UPDATE OF service_content_item_id, resource_content_group_id ON service_resources
WHEN NOT EXISTS (
        SELECT 1 FROM content_items
        WHERE id = NEW.service_content_item_id AND entry_type = 'service'
    ) OR NOT EXISTS (
        SELECT 1 FROM content_groups
        WHERE id = NEW.resource_content_group_id AND entry_type = 'resource'
    )
BEGIN
    SELECT RAISE(ABORT, 'invalid service resource relation types');
END;

CREATE TRIGGER validate_content_relation_industry_cases_insert
BEFORE INSERT ON industry_cases
WHEN NOT EXISTS (
        SELECT 1 FROM content_items
        WHERE id = NEW.industry_content_item_id AND entry_type = 'industry'
    ) OR NOT EXISTS (
        SELECT 1 FROM content_groups
        WHERE id = NEW.case_content_group_id AND entry_type = 'case'
    )
BEGIN
    SELECT RAISE(ABORT, 'invalid industry case relation types');
END;

CREATE TRIGGER validate_content_relation_industry_cases_update
BEFORE UPDATE OF industry_content_item_id, case_content_group_id ON industry_cases
WHEN NOT EXISTS (
        SELECT 1 FROM content_items
        WHERE id = NEW.industry_content_item_id AND entry_type = 'industry'
    ) OR NOT EXISTS (
        SELECT 1 FROM content_groups
        WHERE id = NEW.case_content_group_id AND entry_type = 'case'
    )
BEGIN
    SELECT RAISE(ABORT, 'invalid industry case relation types');
END;

CREATE TRIGGER validate_content_relation_industry_resources_insert
BEFORE INSERT ON industry_resources
WHEN NOT EXISTS (
        SELECT 1 FROM content_items
        WHERE id = NEW.industry_content_item_id AND entry_type = 'industry'
    ) OR NOT EXISTS (
        SELECT 1 FROM content_groups
        WHERE id = NEW.resource_content_group_id AND entry_type = 'resource'
    )
BEGIN
    SELECT RAISE(ABORT, 'invalid industry resource relation types');
END;

CREATE TRIGGER validate_content_relation_industry_resources_update
BEFORE UPDATE OF industry_content_item_id, resource_content_group_id ON industry_resources
WHEN NOT EXISTS (
        SELECT 1 FROM content_items
        WHERE id = NEW.industry_content_item_id AND entry_type = 'industry'
    ) OR NOT EXISTS (
        SELECT 1 FROM content_groups
        WHERE id = NEW.resource_content_group_id AND entry_type = 'resource'
    )
BEGIN
    SELECT RAISE(ABORT, 'invalid industry resource relation types');
END;

CREATE TRIGGER protect_industry_content_update
BEFORE UPDATE ON industry_content
WHEN EXISTS (
    SELECT 1 FROM content_items
    WHERE id IN (OLD.content_item_id, NEW.content_item_id) AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content children are immutable'); END;

CREATE TRIGGER protect_scenario_content_update
BEFORE UPDATE ON scenario_content
WHEN EXISTS (
    SELECT 1 FROM content_items
    WHERE id IN (OLD.content_item_id, NEW.content_item_id) AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content children are immutable'); END;

CREATE TRIGGER protect_service_content_update
BEFORE UPDATE ON service_content
WHEN EXISTS (
    SELECT 1 FROM content_items
    WHERE id IN (OLD.content_item_id, NEW.content_item_id) AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content children are immutable'); END;

CREATE TRIGGER protect_case_content_update
BEFORE UPDATE ON case_content
WHEN EXISTS (
    SELECT 1 FROM content_items
    WHERE id IN (OLD.content_item_id, NEW.content_item_id) AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content children are immutable'); END;

CREATE TRIGGER protect_resource_content_update
BEFORE UPDATE ON resource_content
WHEN EXISTS (
    SELECT 1 FROM content_items
    WHERE id IN (OLD.content_item_id, NEW.content_item_id) AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content children are immutable'); END;

CREATE TRIGGER protect_announcement_content_update
BEFORE UPDATE ON announcement_content
WHEN EXISTS (
    SELECT 1 FROM content_items
    WHERE id IN (OLD.content_item_id, NEW.content_item_id) AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content children are immutable'); END;

CREATE TRIGGER protect_content_blocks_insert
BEFORE INSERT ON content_blocks
WHEN EXISTS (
    SELECT 1 FROM content_items WHERE id = NEW.content_item_id AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content children are immutable'); END;

CREATE TRIGGER protect_content_blocks_update
BEFORE UPDATE ON content_blocks
WHEN EXISTS (
    SELECT 1 FROM content_items
    WHERE id IN (OLD.content_item_id, NEW.content_item_id) AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content children are immutable'); END;

CREATE TRIGGER protect_content_blocks_delete
BEFORE DELETE ON content_blocks
WHEN EXISTS (
    SELECT 1 FROM content_items WHERE id = OLD.content_item_id AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content children are immutable'); END;

CREATE TRIGGER protect_case_metrics_insert
BEFORE INSERT ON case_metrics
WHEN EXISTS (
    SELECT 1 FROM content_items
    WHERE id = NEW.case_content_item_id AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content children are immutable'); END;

CREATE TRIGGER protect_case_metrics_update
BEFORE UPDATE ON case_metrics
WHEN EXISTS (
    SELECT 1 FROM content_items
    WHERE id IN (OLD.case_content_item_id, NEW.case_content_item_id)
        AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content children are immutable'); END;

CREATE TRIGGER protect_case_metrics_delete
BEFORE DELETE ON case_metrics
WHEN EXISTS (
    SELECT 1 FROM content_items
    WHERE id = OLD.case_content_item_id AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content children are immutable'); END;

CREATE TRIGGER protect_content_maturity_insert
BEFORE INSERT ON content_maturity_levels
WHEN EXISTS (
    SELECT 1 FROM content_items WHERE id = NEW.content_item_id AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content children are immutable'); END;

CREATE TRIGGER protect_content_maturity_update
BEFORE UPDATE ON content_maturity_levels
WHEN EXISTS (
    SELECT 1 FROM content_items
    WHERE id IN (OLD.content_item_id, NEW.content_item_id) AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content children are immutable'); END;

CREATE TRIGGER protect_content_maturity_delete
BEFORE DELETE ON content_maturity_levels
WHEN EXISTS (
    SELECT 1 FROM content_items WHERE id = OLD.content_item_id AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content children are immutable'); END;

CREATE TRIGGER protect_scenario_cases_insert
BEFORE INSERT ON scenario_cases
WHEN EXISTS (
    SELECT 1 FROM content_items
    WHERE id = NEW.scenario_content_item_id AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content relations are immutable'); END;

CREATE TRIGGER protect_scenario_cases_update
BEFORE UPDATE ON scenario_cases
WHEN EXISTS (
    SELECT 1 FROM content_items
    WHERE id IN (OLD.scenario_content_item_id, NEW.scenario_content_item_id)
        AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content relations are immutable'); END;

CREATE TRIGGER protect_scenario_cases_delete
BEFORE DELETE ON scenario_cases
WHEN EXISTS (
    SELECT 1 FROM content_items
    WHERE id = OLD.scenario_content_item_id AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content relations are immutable'); END;

CREATE TRIGGER protect_scenario_resources_insert
BEFORE INSERT ON scenario_resources
WHEN EXISTS (
    SELECT 1 FROM content_items
    WHERE id = NEW.scenario_content_item_id AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content relations are immutable'); END;

CREATE TRIGGER protect_scenario_resources_update
BEFORE UPDATE ON scenario_resources
WHEN EXISTS (
    SELECT 1 FROM content_items
    WHERE id IN (OLD.scenario_content_item_id, NEW.scenario_content_item_id)
        AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content relations are immutable'); END;

CREATE TRIGGER protect_scenario_resources_delete
BEFORE DELETE ON scenario_resources
WHEN EXISTS (
    SELECT 1 FROM content_items
    WHERE id = OLD.scenario_content_item_id AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content relations are immutable'); END;

CREATE TRIGGER protect_service_cases_insert
BEFORE INSERT ON service_cases
WHEN EXISTS (
    SELECT 1 FROM content_items
    WHERE id = NEW.service_content_item_id AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content relations are immutable'); END;

CREATE TRIGGER protect_service_cases_update
BEFORE UPDATE ON service_cases
WHEN EXISTS (
    SELECT 1 FROM content_items
    WHERE id IN (OLD.service_content_item_id, NEW.service_content_item_id)
        AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content relations are immutable'); END;

CREATE TRIGGER protect_service_cases_delete
BEFORE DELETE ON service_cases
WHEN EXISTS (
    SELECT 1 FROM content_items
    WHERE id = OLD.service_content_item_id AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content relations are immutable'); END;

CREATE TRIGGER protect_service_resources_insert
BEFORE INSERT ON service_resources
WHEN EXISTS (
    SELECT 1 FROM content_items
    WHERE id = NEW.service_content_item_id AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content relations are immutable'); END;

CREATE TRIGGER protect_service_resources_update
BEFORE UPDATE ON service_resources
WHEN EXISTS (
    SELECT 1 FROM content_items
    WHERE id IN (OLD.service_content_item_id, NEW.service_content_item_id)
        AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content relations are immutable'); END;

CREATE TRIGGER protect_service_resources_delete
BEFORE DELETE ON service_resources
WHEN EXISTS (
    SELECT 1 FROM content_items
    WHERE id = OLD.service_content_item_id AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content relations are immutable'); END;

CREATE TRIGGER protect_industry_cases_insert
BEFORE INSERT ON industry_cases
WHEN EXISTS (
    SELECT 1 FROM content_items
    WHERE id = NEW.industry_content_item_id AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content relations are immutable'); END;

CREATE TRIGGER protect_industry_cases_update
BEFORE UPDATE ON industry_cases
WHEN EXISTS (
    SELECT 1 FROM content_items
    WHERE id IN (OLD.industry_content_item_id, NEW.industry_content_item_id)
        AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content relations are immutable'); END;

CREATE TRIGGER protect_industry_cases_delete
BEFORE DELETE ON industry_cases
WHEN EXISTS (
    SELECT 1 FROM content_items
    WHERE id = OLD.industry_content_item_id AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content relations are immutable'); END;

CREATE TRIGGER protect_industry_resources_insert
BEFORE INSERT ON industry_resources
WHEN EXISTS (
    SELECT 1 FROM content_items
    WHERE id = NEW.industry_content_item_id AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content relations are immutable'); END;

CREATE TRIGGER protect_industry_resources_update
BEFORE UPDATE ON industry_resources
WHEN EXISTS (
    SELECT 1 FROM content_items
    WHERE id IN (OLD.industry_content_item_id, NEW.industry_content_item_id)
        AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content relations are immutable'); END;

CREATE TRIGGER protect_industry_resources_delete
BEFORE DELETE ON industry_resources
WHEN EXISTS (
    SELECT 1 FROM content_items
    WHERE id = OLD.industry_content_item_id AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content relations are immutable'); END;

CREATE TRIGGER validate_content_publication
BEFORE UPDATE OF status ON content_items
WHEN NEW.status = 'published' AND OLD.status <> 'published'
BEGIN
    SELECT CASE WHEN (
        (SELECT COUNT(*) FROM industry_content WHERE content_item_id = NEW.id) +
        (SELECT COUNT(*) FROM scenario_content WHERE content_item_id = NEW.id) +
        (SELECT COUNT(*) FROM service_content WHERE content_item_id = NEW.id) +
        (SELECT COUNT(*) FROM case_content WHERE content_item_id = NEW.id) +
        (SELECT COUNT(*) FROM resource_content WHERE content_item_id = NEW.id) +
        (SELECT COUNT(*) FROM announcement_content WHERE content_item_id = NEW.id)
    ) <> 1 THEN RAISE(ABORT, 'published content requires one domain extension') END;

    SELECT CASE WHEN
        (NEW.entry_type = 'industry' AND NOT EXISTS (
            SELECT 1 FROM industry_content WHERE content_item_id = NEW.id
        )) OR
        (NEW.entry_type = 'scenario' AND NOT EXISTS (
            SELECT 1 FROM scenario_content WHERE content_item_id = NEW.id
        )) OR
        (NEW.entry_type = 'service' AND NOT EXISTS (
            SELECT 1 FROM service_content WHERE content_item_id = NEW.id
        )) OR
        (NEW.entry_type = 'case' AND NOT EXISTS (
            SELECT 1 FROM case_content WHERE content_item_id = NEW.id
        )) OR
        (NEW.entry_type = 'resource' AND NOT EXISTS (
            SELECT 1 FROM resource_content WHERE content_item_id = NEW.id
        )) OR
        (NEW.entry_type = 'announcement' AND NOT EXISTS (
            SELECT 1 FROM announcement_content WHERE content_item_id = NEW.id
        ))
    THEN RAISE(ABORT, 'published content extension has wrong type') END;

    SELECT CASE WHEN NEW.share_image_media_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM media_assets
        WHERE id = NEW.share_image_media_id AND status = 'ready'
    ) THEN RAISE(ABORT, 'published share image must be ready') END;

    SELECT CASE WHEN EXISTS (
        SELECT 1 FROM content_blocks cb
        LEFT JOIN media_assets ma ON ma.id = cb.media_asset_id
        WHERE cb.content_item_id = NEW.id AND cb.media_asset_id IS NOT NULL
            AND (ma.id IS NULL OR ma.status <> 'ready')
    ) THEN RAISE(ABORT, 'published block media must be ready') END;

    SELECT CASE WHEN EXISTS (
        SELECT 1 FROM resource_content rc
        LEFT JOIN media_assets ma ON ma.id = rc.attachment_media_id
        WHERE rc.content_item_id = NEW.id AND rc.attachment_media_id IS NOT NULL
            AND (ma.id IS NULL OR ma.status <> 'ready')
    ) THEN RAISE(ABORT, 'published attachment must be ready') END;

    SELECT CASE WHEN EXISTS (
        SELECT 1 FROM scenario_cases rel
        WHERE rel.scenario_content_item_id = NEW.id AND NOT EXISTS (
            SELECT 1 FROM content_items target
            WHERE target.content_group_id = rel.case_content_group_id
                AND target.entry_type = 'case' AND target.status = 'published'
        )
    ) THEN RAISE(ABORT, 'scenario case target is not published') END;

    SELECT CASE WHEN EXISTS (
        SELECT 1 FROM scenario_resources rel
        WHERE rel.scenario_content_item_id = NEW.id AND NOT EXISTS (
            SELECT 1 FROM content_items target
            WHERE target.content_group_id = rel.resource_content_group_id
                AND target.entry_type = 'resource' AND target.status = 'published'
        )
    ) THEN RAISE(ABORT, 'scenario resource target is not published') END;

    SELECT CASE WHEN EXISTS (
        SELECT 1 FROM service_cases rel
        WHERE rel.service_content_item_id = NEW.id AND NOT EXISTS (
            SELECT 1 FROM content_items target
            WHERE target.content_group_id = rel.case_content_group_id
                AND target.entry_type = 'case' AND target.status = 'published'
        )
    ) THEN RAISE(ABORT, 'service case target is not published') END;

    SELECT CASE WHEN EXISTS (
        SELECT 1 FROM service_resources rel
        WHERE rel.service_content_item_id = NEW.id AND NOT EXISTS (
            SELECT 1 FROM content_items target
            WHERE target.content_group_id = rel.resource_content_group_id
                AND target.entry_type = 'resource' AND target.status = 'published'
        )
    ) THEN RAISE(ABORT, 'service resource target is not published') END;

    SELECT CASE WHEN EXISTS (
        SELECT 1 FROM industry_cases rel
        WHERE rel.industry_content_item_id = NEW.id AND NOT EXISTS (
            SELECT 1 FROM content_items target
            WHERE target.content_group_id = rel.case_content_group_id
                AND target.entry_type = 'case' AND target.status = 'published'
        )
    ) THEN RAISE(ABORT, 'industry case target is not published') END;

    SELECT CASE WHEN EXISTS (
        SELECT 1 FROM industry_resources rel
        WHERE rel.industry_content_item_id = NEW.id AND NOT EXISTS (
            SELECT 1 FROM content_items target
            WHERE target.content_group_id = rel.resource_content_group_id
                AND target.entry_type = 'resource' AND target.status = 'published'
        )
    ) THEN RAISE(ABORT, 'industry resource target is not published') END;
END;

CREATE TRIGGER prevent_published_extension_delete_industry
BEFORE DELETE ON industry_content
WHEN EXISTS (SELECT 1 FROM content_items WHERE id = OLD.content_item_id AND status <> 'draft')
BEGIN SELECT RAISE(ABORT, 'published content extension is required'); END;

CREATE TRIGGER prevent_published_extension_delete_scenario
BEFORE DELETE ON scenario_content
WHEN EXISTS (SELECT 1 FROM content_items WHERE id = OLD.content_item_id AND status <> 'draft')
BEGIN SELECT RAISE(ABORT, 'published content extension is required'); END;

CREATE TRIGGER prevent_published_extension_delete_service
BEFORE DELETE ON service_content
WHEN EXISTS (SELECT 1 FROM content_items WHERE id = OLD.content_item_id AND status <> 'draft')
BEGIN SELECT RAISE(ABORT, 'published content extension is required'); END;

CREATE TRIGGER prevent_published_extension_delete_case
BEFORE DELETE ON case_content
WHEN EXISTS (SELECT 1 FROM content_items WHERE id = OLD.content_item_id AND status <> 'draft')
BEGIN SELECT RAISE(ABORT, 'published content extension is required'); END;

CREATE TRIGGER prevent_published_extension_delete_resource
BEFORE DELETE ON resource_content
WHEN EXISTS (SELECT 1 FROM content_items WHERE id = OLD.content_item_id AND status <> 'draft')
BEGIN SELECT RAISE(ABORT, 'published content extension is required'); END;

CREATE TRIGGER prevent_published_extension_delete_announcement
BEFORE DELETE ON announcement_content
WHEN EXISTS (SELECT 1 FROM content_items WHERE id = OLD.content_item_id AND status <> 'draft')
BEGIN SELECT RAISE(ABORT, 'published content extension is required'); END;

CREATE TRIGGER prevent_referenced_ready_media_archive
BEFORE UPDATE OF status ON media_assets
WHEN OLD.status = 'ready' AND NEW.status = 'archived' AND (
    EXISTS (
        SELECT 1 FROM content_items
        WHERE status = 'published' AND share_image_media_id = OLD.id
    ) OR EXISTS (
        SELECT 1 FROM content_blocks cb
        JOIN content_items ci ON ci.id = cb.content_item_id
        WHERE ci.status = 'published' AND cb.media_asset_id = OLD.id
    ) OR EXISTS (
        SELECT 1 FROM resource_content rc
        JOIN content_items ci ON ci.id = rc.content_item_id
        WHERE ci.status = 'published' AND rc.attachment_media_id = OLD.id
    )
)
BEGIN
    SELECT RAISE(ABORT, 'published content still references media');
END;

CREATE TRIGGER prevent_media_asset_delete
BEFORE DELETE ON media_assets
BEGIN
    SELECT RAISE(ABORT, 'media assets must be archived, not deleted');
END;

CREATE TRIGGER prevent_content_item_delete
BEFORE DELETE ON content_items
BEGIN
    SELECT RAISE(ABORT, 'content revisions are append-only');
END;

CREATE TRIGGER prevent_content_group_delete
BEFORE DELETE ON content_groups
BEGIN
    SELECT RAISE(ABORT, 'content groups are append-only');
END;

CREATE TRIGGER prevent_legacy_article_delete
BEFORE DELETE ON articles
BEGIN
    SELECT RAISE(ABORT, 'legacy content deletion is deferred');
END;

CREATE TRIGGER prevent_legacy_case_delete
BEFORE DELETE ON cases
BEGIN
    SELECT RAISE(ABORT, 'legacy content deletion is deferred');
END;

CREATE TRIGGER prevent_legacy_service_delete
BEFORE DELETE ON services
BEGIN
    SELECT RAISE(ABORT, 'legacy content deletion is deferred');
END;

CREATE TRIGGER prevent_legacy_announcement_delete
BEFORE DELETE ON announcements
BEGIN
    SELECT RAISE(ABORT, 'legacy content deletion is deferred');
END;
