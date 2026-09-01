DROP TRIGGER validate_resource_content_insert;
DROP TRIGGER validate_resource_content_update;
DROP TRIGGER protect_resource_content_update;
DROP TRIGGER prevent_published_extension_delete_resource;
DROP TRIGGER validate_content_publication;
DROP TRIGGER prevent_referenced_ready_media_archive;

CREATE TEMP TABLE resource_content_sequence_011 (
    seq INTEGER NOT NULL
);
INSERT INTO resource_content_sequence_011 (seq)
SELECT COALESCE((
    SELECT seq FROM sqlite_sequence WHERE name = 'resource_content'
), 0);

CREATE TABLE resource_content_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_item_id INTEGER NOT NULL UNIQUE,
    resource_type TEXT NOT NULL CHECK(resource_type IN (
        'article', 'guide', 'report', 'template', 'policy'
    )),
    is_original INTEGER NOT NULL CHECK(is_original IN (0, 1)),
    source_name TEXT CHECK(source_name IS NULL OR length(source_name) BETWEEN 1 AND 200),
    source_url TEXT CHECK(
        source_url IS NULL OR
        substr(source_url, 1, 8) = 'https://' OR
        substr(source_url, 1, 7) = 'http://'
    ),
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
            length(source_check_url_sha256) = 64 AND source_check_url_sha256 NOT GLOB '*[^0-9a-f]*'
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

INSERT INTO resource_content_v2 (
    id, content_item_id, resource_type, is_original, source_name, source_url,
    source_url_sha256, source_check_code, source_checked_at,
    source_check_expires_at, source_check_url_sha256, original_published_at,
    copyright_notice, attachment_media_id
)
SELECT
    id, content_item_id, resource_type, is_original, source_name, source_url,
    source_url_sha256, source_check_code, source_checked_at,
    source_check_expires_at, source_check_url_sha256, original_published_at,
    copyright_notice, attachment_media_id
FROM resource_content;

DROP TABLE resource_content;
ALTER TABLE resource_content_v2 RENAME TO resource_content;

UPDATE sqlite_sequence
SET seq = CASE
    WHEN seq < (SELECT seq FROM resource_content_sequence_011)
    THEN (SELECT seq FROM resource_content_sequence_011)
    ELSE seq
END
WHERE name = 'resource_content';
INSERT INTO sqlite_sequence (name, seq)
SELECT 'resource_content', seq
FROM resource_content_sequence_011
WHERE NOT EXISTS (
    SELECT 1 FROM sqlite_sequence WHERE name = 'resource_content'
);
DROP TABLE temp.resource_content_sequence_011;

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

CREATE TRIGGER protect_resource_content_update
BEFORE UPDATE ON resource_content
WHEN EXISTS (
    SELECT 1 FROM content_items
    WHERE id IN (OLD.content_item_id, NEW.content_item_id) AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content children are immutable'); END;

CREATE TRIGGER prevent_published_extension_delete_resource
BEFORE DELETE ON resource_content
WHEN EXISTS (SELECT 1 FROM content_items WHERE id = OLD.content_item_id AND status <> 'draft')
BEGIN SELECT RAISE(ABORT, 'published content extension is required'); END;

CREATE TRIGGER restrict_http_resource_insert
BEFORE INSERT ON resource_content
WHEN substr(NEW.source_url, 1, 7) = 'http://' AND NOT EXISTS (
    SELECT 1 FROM content_items
    WHERE id = NEW.content_item_id AND status = 'draft' AND publish_at IS NULL
)
BEGIN SELECT RAISE(ABORT, 'http resource requires an unscheduled draft'); END;

CREATE TRIGGER restrict_http_resource_update
BEFORE UPDATE OF content_item_id, source_url ON resource_content
WHEN substr(NEW.source_url, 1, 7) = 'http://' AND NOT EXISTS (
    SELECT 1 FROM content_items
    WHERE id = NEW.content_item_id AND status = 'draft' AND publish_at IS NULL
)
BEGIN SELECT RAISE(ABORT, 'http resource requires an unscheduled draft'); END;

CREATE TRIGGER restrict_http_resource_owner_transition
BEFORE UPDATE OF status, publish_at ON content_items
WHEN EXISTS (
    SELECT 1 FROM resource_content
    WHERE content_item_id = OLD.id AND substr(source_url, 1, 7) = 'http://'
) AND (NEW.status <> 'draft' OR NEW.publish_at IS NOT NULL)
BEGIN SELECT RAISE(ABORT, 'http resource requires an unscheduled draft'); END;

CREATE TRIGGER validate_content_publication
BEFORE UPDATE OF status ON content_items
WHEN NEW.status = 'published' AND OLD.status <> 'published'
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM content_groups
        WHERE id = NEW.content_group_id AND canonical_slug = NEW.slug
    ) THEN RAISE(ABORT, 'published slug must match canonical slug') END;

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
