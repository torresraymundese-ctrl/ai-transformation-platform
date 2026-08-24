import hashlib
import sqlite3

import pytest

import models


SHANGHAI_TIME = "2026-08-24 12:34:56"

EXPECTED_CONTENT_TABLES = {
    "content_groups",
    "content_items",
    "content_blocks",
    "industry_content",
    "scenario_content",
    "service_content",
    "case_content",
    "case_metrics",
    "resource_content",
    "announcement_content",
    "content_maturity_levels",
    "media_assets",
    "content_slug_aliases",
    "scenario_cases",
    "scenario_resources",
    "service_cases",
    "service_resources",
    "industry_cases",
    "industry_resources",
    "content_audit_events",
    "legacy_content_reviews",
    "legacy_content_mappings",
}


def database_tables(db):
    return {
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def columns(db, table):
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


def frozen_catalog_counts(db):
    return tuple(
        db.execute(query).fetchone()[0]
        for query in (
            "SELECT COUNT(*) FROM industries WHERE status='published'",
            "SELECT COUNT(*) FROM scenarios WHERE status='published'",
            "SELECT COUNT(*) FROM services "
            "WHERE code IS NOT NULL AND status='published'",
        )
    )


def insert_group(db, entry_type="announcement", slug="news"):
    identity_column = {
        "industry": "industry_id",
        "scenario": "scenario_id",
        "service": "service_id",
    }.get(entry_type)
    if identity_column:
        source_table = {
            "industry_id": "industries",
            "scenario_id": "scenarios",
            "service_id": "services",
        }[identity_column]
        identity_id = db.execute(
            f"SELECT id FROM {source_table} WHERE status='published' LIMIT 1"
        ).fetchone()[0]
        return db.execute(
            f"INSERT INTO content_groups "
            f"(entry_type,{identity_column},canonical_slug,created_at,updated_at) "
            "VALUES (?,?,?,?,?)",
            (entry_type, identity_id, slug, SHANGHAI_TIME, SHANGHAI_TIME),
        ).lastrowid
    return db.execute(
        "INSERT INTO content_groups "
        "(entry_type,canonical_slug,created_at,updated_at) VALUES (?,?,?,?)",
        (entry_type, slug, SHANGHAI_TIME, SHANGHAI_TIME),
    ).lastrowid


def insert_item(
    db,
    group_id,
    *,
    entry_type="announcement",
    revision=1,
    slug="news",
    status="draft",
    share_image_media_id=None,
):
    return db.execute(
        "INSERT INTO content_items "
        "(content_group_id,entry_type,revision_number,slug,title,summary,"
        "seo_title,seo_description,share_image_media_id,status,lock_version,"
        "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            group_id,
            entry_type,
            revision,
            slug,
            f"Revision {revision}",
            "Summary",
            "SEO title",
            "SEO description",
            share_image_media_id,
            status,
            1,
            SHANGHAI_TIME,
            SHANGHAI_TIME,
        ),
    ).lastrowid


def add_announcement_extension(db, item_id):
    db.execute(
        "INSERT INTO announcement_content (content_item_id) VALUES (?)",
        (item_id,),
    )


def publish(db, item_id):
    db.execute(
        "UPDATE content_items SET status='published',published_at=?,updated_at=? "
        "WHERE id=?",
        (SHANGHAI_TIME, SHANGHAI_TIME, item_id),
    )


def insert_media(db, suffix, *, status="pending", storage_suffix=None):
    ready_at = SHANGHAI_TIME if status == "ready" else None
    archived_at = SHANGHAI_TIME if status == "archived" else None
    scan_code = "clean" if status == "ready" else None
    scan_checked_at = SHANGHAI_TIME if status == "ready" else None
    return db.execute(
        "INSERT INTO media_assets "
        "(storage_name,display_name,detected_mime,byte_size,sha256,"
        "scan_result_code,scan_checked_at,status,created_at,ready_at,"
        "archived_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            f"random-{storage_suffix or suffix}.png",
            f"display-{suffix}.png",
            "image/png",
            100,
            hashlib.sha256(suffix.encode("ascii")).hexdigest(),
            scan_code,
            scan_checked_at,
            status,
            SHANGHAI_TIME,
            ready_at,
            archived_at,
            SHANGHAI_TIME,
        ),
    ).lastrowid


def test_content_migration_is_idempotent_and_preserves_v2_catalog(client, db):
    before = frozen_catalog_counts(db)
    sentinels = {
        "articles": db.execute(
            "INSERT INTO articles (title_hash,title,source) VALUES (?,?,?)",
            ("migration-sentinel", "Keep article", "local"),
        ).lastrowid,
        "cases": db.execute(
            "INSERT INTO cases (title,industry) VALUES (?,?)",
            ("Keep case", "manufacturing"),
        ).lastrowid,
        "services": db.execute(
            "INSERT INTO services (name,tier) VALUES (?,?)",
            ("Keep service", "legacy"),
        ).lastrowid,
        "announcements": db.execute(
            "INSERT INTO announcements (title) VALUES (?)", ("Keep notice",)
        ).lastrowid,
    }
    db.commit()

    models.init_db()
    models.init_db()

    assert EXPECTED_CONTENT_TABLES <= database_tables(db)
    assert frozen_catalog_counts(db) == before == (4, 13, 6)
    for table, row_id in sentinels.items():
        assert db.execute(
            f"SELECT 1 FROM {table} WHERE id=?", (row_id,)
        ).fetchone()


def test_content_schema_exposes_the_frozen_columns_and_real_foreign_keys(db):
    expected_columns = {
        "content_groups": {
            "id", "entry_type", "industry_id", "scenario_id", "service_id",
            "canonical_slug", "created_at", "updated_at",
        },
        "content_items": {
            "id", "content_group_id", "entry_type", "revision_number", "slug",
            "title", "summary", "seo_title", "seo_description",
            "share_image_media_id", "status", "publish_at", "published_at",
            "archived_at", "lock_version", "created_at", "updated_at",
        },
        "content_blocks": {
            "id", "content_item_id", "block_type", "title", "body_html",
            "settings_json", "media_asset_id", "sort_order",
        },
        "case_content": {
            "id", "content_item_id", "verification_code", "is_anonymized",
            "basis_type", "private_basis_reference", "source_url",
            "source_url_sha256", "source_check_code", "source_checked_at",
            "source_check_expires_at", "source_check_url_sha256", "is_verified",
            "review_confirmed", "verified_at",
        },
        "case_metrics": {
            "id", "case_content_item_id", "name", "before_value", "after_value",
            "unit", "statistical_period", "evidence_explanation", "sort_order",
        },
        "resource_content": {
            "id", "content_item_id", "resource_type", "is_original",
            "source_name", "source_url", "source_url_sha256",
            "source_check_code", "source_checked_at", "source_check_expires_at",
            "source_check_url_sha256", "original_published_at",
            "copyright_notice", "attachment_media_id",
        },
        "legacy_content_reviews": {
            "id", "source_table", "source_id", "title_summary", "source_checksum",
            "proposed_action", "reason_code", "decision_action", "decision_at",
            "decision_source_checksum", "source_state", "source_check_code",
            "source_checked_at", "source_check_expires_at", "check_source_checksum",
            "review_stale_at", "target_type", "target_group",
            "required_confirmations_json", "target_preview_json",
            "source_url_display", "source_url_sha256", "created_at", "updated_at",
        },
        "legacy_content_mappings": {
            "id", "source_table", "source_id", "source_checksum",
            "target_content_group_id", "target_content_item_id", "created_at",
            "updated_at",
        },
    }
    for table, expected in expected_columns.items():
        assert columns(db, table) == expected

    industry_id = db.execute("SELECT id FROM industries LIMIT 1").fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO industry_content (content_item_id,industry_id) "
            "VALUES (?,?)",
            (999999, industry_id),
        )


def test_database_rejects_invalid_revision_identity_status_and_timestamp(db):
    group_id = insert_group(db)
    insert_item(db, group_id)

    with pytest.raises(sqlite3.IntegrityError):
        insert_item(db, group_id, revision=0)
    with pytest.raises(sqlite3.IntegrityError):
        insert_item(db, group_id, revision=2, status="review")
    with pytest.raises(sqlite3.IntegrityError):
        insert_item(db, group_id, revision=2, entry_type="resource")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "UPDATE content_groups SET entry_type='resource' WHERE id=?",
            (group_id,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO content_groups "
            "(entry_type,canonical_slug,created_at,updated_at) VALUES (?,?,?,?)",
            ("case", "bad-time", "2026-08-24 12:34:56.1", SHANGHAI_TIME),
        )


def test_database_rejects_two_drafts_or_two_published_in_one_group(db):
    draft_group = insert_group(db, slug="draft-limit")
    insert_item(db, draft_group, slug="draft-limit")
    with pytest.raises(sqlite3.IntegrityError):
        insert_item(db, draft_group, revision=2, slug="draft-limit")

    published_group = insert_group(db, slug="published-limit")
    first = insert_item(db, published_group, slug="published-limit")
    add_announcement_extension(db, first)
    publish(db, first)
    second = insert_item(db, published_group, revision=2, slug="published-limit")
    add_announcement_extension(db, second)
    with pytest.raises(sqlite3.IntegrityError):
        publish(db, second)


def test_publication_requires_exactly_the_matching_domain_extension(db):
    industry_group = insert_group(db, entry_type="industry", slug="manufacturing-copy")
    item_id = insert_item(
        db, industry_group, entry_type="industry", slug="manufacturing-copy"
    )
    with pytest.raises(sqlite3.IntegrityError):
        publish(db, item_id)

    industry_id = db.execute("SELECT id FROM industries LIMIT 1").fetchone()[0]
    db.execute(
        "INSERT INTO industry_content (content_item_id,industry_id) VALUES (?,?)",
        (item_id, industry_id),
    )
    publish(db, item_id)
    assert db.execute(
        "SELECT status FROM content_items WHERE id=?", (item_id,)
    ).fetchone()[0] == "published"

    case_group = insert_group(db, entry_type="case", slug="wrong-extension")
    case_item = insert_item(
        db, case_group, entry_type="case", slug="wrong-extension"
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO announcement_content (content_item_id) VALUES (?)",
            (case_item,),
        )


def test_blocks_maturity_resource_types_and_relation_targets_are_constrained(db):
    media_id = insert_media(db, "a", status="ready")
    group_id = insert_group(db, slug="blocks")
    item_id = insert_item(db, group_id, slug="blocks")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO content_blocks (content_item_id,block_type,sort_order) "
            "VALUES (?,?,?)",
            (item_id, "script", 0),
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO content_blocks "
            "(content_item_id,block_type,media_asset_id,sort_order) VALUES (?,?,?,?)",
            (item_id, "rich_text", media_id, 0),
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO content_maturity_levels (content_item_id,maturity_code) "
            "VALUES (?,?)",
            (item_id, "optimize"),
        )

    resource_group = insert_group(db, entry_type="resource", slug="resource")
    resource_item = insert_item(
        db, resource_group, entry_type="resource", slug="resource"
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO resource_content (content_item_id,resource_type,is_original) "
            "VALUES (?,?,?)",
            (resource_item, "video", 1),
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO scenario_resources "
            "(scenario_content_item_id,resource_content_group_id,sort_order) "
            "VALUES (?,?,?)",
            (item_id, resource_group, 0),
        )


def test_slug_aliases_cannot_collide_with_aliases_or_canonical_slugs(db):
    first = insert_group(db, slug="first")
    second = insert_group(db, slug="second")
    db.execute(
        "INSERT INTO content_slug_aliases "
        "(entry_type,old_slug,content_group_id,created_at) VALUES (?,?,?,?)",
        ("announcement", "former-first", first, SHANGHAI_TIME),
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO content_slug_aliases "
            "(entry_type,old_slug,content_group_id,created_at) VALUES (?,?,?,?)",
            ("announcement", "former-first", second, SHANGHAI_TIME),
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO content_slug_aliases "
            "(entry_type,old_slug,content_group_id,created_at) VALUES (?,?,?,?)",
            ("announcement", "first", second, SHANGHAI_TIME),
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "UPDATE content_groups SET canonical_slug='former-first' WHERE id=?",
            (second,),
        )


def test_media_active_deduplication_and_archived_reupload_contract(db):
    first = insert_media(db, "b")
    with pytest.raises(sqlite3.IntegrityError):
        insert_media(db, "b", storage_suffix="b-active-duplicate")
    db.execute(
        "UPDATE media_assets SET status='archived',archived_at=?,updated_at=? "
        "WHERE id=?",
        (SHANGHAI_TIME, SHANGHAI_TIME, first),
    )
    replacement = insert_media(db, "b", storage_suffix="b-reupload")
    assert replacement != first


def test_media_transitions_and_ready_identity_are_database_enforced(db):
    pending = insert_media(db, "c")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "UPDATE media_assets SET status='ready',ready_at=?,updated_at=? WHERE id=?",
            (SHANGHAI_TIME, SHANGHAI_TIME, pending),
        )
    db.execute(
        "UPDATE media_assets SET scan_result_code='clean',scan_checked_at=?,"
        "status='ready',ready_at=?,updated_at=? WHERE id=?",
        (SHANGHAI_TIME, SHANGHAI_TIME, SHANGHAI_TIME, pending),
    )
    for column, value in (
        ("storage_name", "changed.png"),
        ("detected_mime", "image/jpeg"),
        ("byte_size", 101),
        ("sha256", "d" * 64),
        ("scan_result_code", "different"),
        ("ready_at", "2026-08-24 12:34:57"),
    ):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                f"UPDATE media_assets SET {column}=?,updated_at=? WHERE id=?",
                (value, SHANGHAI_TIME, pending),
            )
    db.execute(
        "UPDATE media_assets SET status='archived',archived_at=?,updated_at=? "
        "WHERE id=?",
        (SHANGHAI_TIME, SHANGHAI_TIME, pending),
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "UPDATE media_assets SET sha256=?,updated_at=? WHERE id=?",
            ("e" * 64, SHANGHAI_TIME, pending),
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "UPDATE media_assets SET status='ready',archived_at=NULL WHERE id=?",
            (pending,),
        )


def test_extension_and_relation_type_guards_also_reject_update_bypasses(db):
    industry_group = insert_group(db, entry_type="industry", slug="typed-industry")
    industry_item = insert_item(
        db, industry_group, entry_type="industry", slug="typed-industry"
    )
    expected_industry = db.execute(
        "SELECT industry_id FROM content_groups WHERE id=?", (industry_group,)
    ).fetchone()[0]
    other_industry = db.execute(
        "SELECT id FROM industries WHERE id<>? LIMIT 1", (expected_industry,)
    ).fetchone()[0]
    extension_id = db.execute(
        "INSERT INTO industry_content (content_item_id,industry_id) VALUES (?,?)",
        (industry_item, expected_industry),
    ).lastrowid
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "UPDATE industry_content SET industry_id=? WHERE id=?",
            (other_industry, extension_id),
        )

    scenario_group = insert_group(db, entry_type="scenario", slug="typed-scenario")
    scenario_item = insert_item(
        db, scenario_group, entry_type="scenario", slug="typed-scenario"
    )
    resource_group = insert_group(db, entry_type="resource", slug="typed-resource")
    wrong_group = insert_group(db, entry_type="announcement", slug="typed-wrong")
    db.execute(
        "INSERT INTO scenario_resources "
        "(scenario_content_item_id,resource_content_group_id,sort_order) "
        "VALUES (?,?,?)",
        (scenario_item, resource_group, 0),
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "UPDATE scenario_resources SET resource_content_group_id=? "
            "WHERE scenario_content_item_id=?",
            (wrong_group, scenario_item),
        )


def test_published_aggregate_children_cannot_be_edited_by_direct_sql(db):
    group_id = insert_group(db, slug="published-children")
    item_id = insert_item(db, group_id, slug="published-children")
    extension_id = db.execute(
        "INSERT INTO announcement_content (content_item_id,cta_url) VALUES (?,?)",
        (item_id, "/before"),
    ).lastrowid
    publish(db, item_id)

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "UPDATE announcement_content SET cta_url='/after' WHERE id=?",
            (extension_id,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO content_blocks (content_item_id,block_type,sort_order) "
            "VALUES (?,?,?)",
            (item_id, "heading", 0),
        )


@pytest.mark.parametrize("reference_kind", ["share", "block", "attachment"])
def test_published_media_references_block_ready_archival(db, reference_kind):
    media_id = insert_media(db, reference_kind[0], status="ready")
    entry_type = "resource" if reference_kind == "attachment" else "announcement"
    group_id = insert_group(db, entry_type=entry_type, slug=f"ref-{reference_kind}")
    item_id = insert_item(
        db,
        group_id,
        entry_type=entry_type,
        slug=f"ref-{reference_kind}",
        share_image_media_id=media_id if reference_kind == "share" else None,
    )
    if reference_kind == "attachment":
        db.execute(
            "INSERT INTO resource_content "
            "(content_item_id,resource_type,is_original,attachment_media_id) "
            "VALUES (?,?,?,?)",
            (item_id, "guide", 1, media_id),
        )
    else:
        add_announcement_extension(db, item_id)
    if reference_kind == "block":
        db.execute(
            "INSERT INTO content_blocks "
            "(content_item_id,block_type,media_asset_id,sort_order) VALUES (?,?,?,?)",
            (item_id, "image_text", media_id, 0),
        )
    publish(db, item_id)

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "UPDATE media_assets SET status='archived',archived_at=?,updated_at=? "
            "WHERE id=?",
            (SHANGHAI_TIME, SHANGHAI_TIME, media_id),
        )


def test_legacy_review_and_mapping_checks_are_enforced_without_cascades(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO legacy_content_reviews "
            "(source_table,source_id,title_summary,source_checksum,proposed_action,"
            "reason_code,source_state,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                "cases", 1, "summary", "a" * 64, "erase", "reason",
                "unchecked", SHANGHAI_TIME, SHANGHAI_TIME,
            ),
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO legacy_content_reviews "
            "(source_table,source_id,title_summary,source_checksum,proposed_action,"
            "reason_code,source_state,source_url_display,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "articles", 1, "summary", "a" * 64, "clean", "reason",
                "unchecked", "https://example.com/path?secret=1", SHANGHAI_TIME,
                SHANGHAI_TIME,
            ),
        )

    group_id = insert_group(db, slug="mapped")
    item_id = insert_item(db, group_id, slug="mapped")
    db.execute(
        "INSERT INTO legacy_content_mappings "
        "(source_table,source_id,source_checksum,target_content_group_id,"
        "target_content_item_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
        ("announcements", 1, "b" * 64, group_id, item_id, SHANGHAI_TIME, SHANGHAI_TIME),
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM content_groups WHERE id=?", (group_id,))


def test_stage_five_rows_must_be_archived_instead_of_physically_deleted(db):
    group_id = insert_group(db, slug="no-delete")
    item_id = insert_item(db, group_id, slug="no-delete")
    media_id = insert_media(db, "no-delete")
    article_id = db.execute(
        "INSERT INTO articles (title_hash,title,source) VALUES (?,?,?)",
        ("no-delete", "No delete", "local"),
    ).lastrowid

    for table, row_id in (
        ("content_items", item_id),
        ("content_groups", group_id),
        ("media_assets", media_id),
        ("articles", article_id),
    ):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(f"DELETE FROM {table} WHERE id=?", (row_id,))
