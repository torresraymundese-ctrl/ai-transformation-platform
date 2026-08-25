DROP TRIGGER validate_content_publication;

CREATE TABLE case_content_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_item_id INTEGER NOT NULL UNIQUE,
    verification_code TEXT NOT NULL CHECK(length(verification_code) BETWEEN 1 AND 64),
    is_anonymized INTEGER NOT NULL DEFAULT 0 CHECK(is_anonymized IN (0, 1)),
    basis_type TEXT NOT NULL CHECK(basis_type IN (
        'public_source', 'client_authorization', 'internal_delivery_record',
        'private_authorization'
    )),
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
        (basis_type IN ('client_authorization', 'internal_delivery_record')
            AND private_basis_reference IS NOT NULL
            AND private_basis_reference = trim(
                private_basis_reference,
                char(9) || char(10) || char(11) || char(12) || char(13) ||
                char(28) || char(29) || char(30) || char(31) || char(32) ||
                char(133) || char(160) || char(5760) || char(8192) ||
                char(8193) || char(8194) || char(8195) || char(8196) ||
                char(8197) || char(8198) || char(8199) || char(8200) ||
                char(8201) || char(8202) || char(8232) || char(8233) ||
                char(8239) || char(8287) || char(12288)
            )
            AND length(private_basis_reference) BETWEEN 1 AND 300
            AND instr(private_basis_reference, char(0)) = 0) OR
        (basis_type = 'private_authorization' AND private_basis_reference IS NOT NULL)
    ),
    CHECK(
        (source_check_code IS NULL AND source_checked_at IS NULL
            AND source_check_expires_at IS NULL AND source_check_url_sha256 IS NULL) OR
        (source_check_code IS NOT NULL AND source_checked_at IS NOT NULL
            AND source_check_expires_at IS NOT NULL AND source_check_url_sha256 IS NOT NULL)
    )
);

INSERT INTO case_content_v2 (
    id, content_item_id, verification_code, is_anonymized, basis_type,
    private_basis_reference, source_url, source_url_sha256, source_check_code,
    source_checked_at, source_check_expires_at, source_check_url_sha256,
    is_verified, review_confirmed, verified_at
)
SELECT
    id, content_item_id, verification_code, is_anonymized, basis_type,
    private_basis_reference, source_url, source_url_sha256, source_check_code,
    source_checked_at, source_check_expires_at, source_check_url_sha256,
    is_verified, review_confirmed, verified_at
FROM case_content;

DROP TABLE case_content;
ALTER TABLE case_content_v2 RENAME TO case_content;

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

CREATE TRIGGER protect_case_content_update
BEFORE UPDATE ON case_content
WHEN EXISTS (
    SELECT 1 FROM content_items
    WHERE id IN (OLD.content_item_id, NEW.content_item_id) AND status <> 'draft'
)
BEGIN SELECT RAISE(ABORT, 'non-draft content children are immutable'); END;

CREATE TRIGGER prevent_published_extension_delete_case
BEFORE DELETE ON case_content
WHEN EXISTS (SELECT 1 FROM content_items WHERE id = OLD.content_item_id AND status <> 'draft')
BEGIN SELECT RAISE(ABORT, 'published content extension is required'); END;

CREATE TRIGGER reject_legacy_case_basis_publication
BEFORE UPDATE OF status ON content_items
WHEN NEW.status = 'published' AND OLD.status <> 'published'
    AND NEW.entry_type = 'case'
    AND EXISTS (
        SELECT 1 FROM case_content
        WHERE content_item_id = NEW.id AND basis_type = 'private_authorization'
    )
BEGIN SELECT RAISE(ABORT, 'legacy case basis cannot be published'); END;
