import hashlib
import sqlite3
from pathlib import Path

import pytest

import migrations
import models


SHANGHAI_TIME = "2026-08-24 12:34:56"
PROJECT_ROOT = Path(__file__).resolve().parents[1]

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


def foreign_keys(db, table):
    return {
        (row[3], row[2], row[4], row[6])
        for row in db.execute(f"PRAGMA foreign_key_list({table})")
    }


def named_index(db, table, name):
    index_row = next(
        row for row in db.execute(f"PRAGMA index_list({table})") if row[1] == name
    )
    index_columns = tuple(
        row[2] for row in db.execute(f"PRAGMA index_info({name})")
    )
    return index_row[2], index_row[4], index_columns


def exact_rows(db, table, where="1=1", parameters=()):
    return [
        tuple(row)
        for row in db.execute(
            f"SELECT * FROM {table} WHERE {where} ORDER BY id", parameters
        )
    ]


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
    assert status in ("pending", "ready")
    media_id = db.execute(
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
            None,
            None,
            "pending",
            SHANGHAI_TIME,
            None,
            None,
            SHANGHAI_TIME,
        ),
    ).lastrowid
    if status == "ready":
        db.execute(
            "UPDATE media_assets SET scan_result_code='clean',scan_checked_at=?,"
            "status='ready',ready_at=?,updated_at=? WHERE id=?",
            (SHANGHAI_TIME, SHANGHAI_TIME, SHANGHAI_TIME, media_id),
        )
    return media_id


def test_content_migration_is_idempotent_and_preserves_populated_005_rows(
    db_through_005, monkeypatch
):
    db = db_through_005
    version_id = db.execute(
        "SELECT id FROM assessment_versions WHERE code='v2.0-2026-08-19'"
    ).fetchone()[0]
    lead_id = db.execute(
        "INSERT INTO leads "
        "(company_name,contact_name,phone_normalized,status,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?)",
        ("Upgrade sentinel", "Operator", "13800000000", "new", SHANGHAI_TIME, SHANGHAI_TIME),
    ).lastrowid
    assessment_id = db.execute(
        "INSERT INTO assessments "
        "(company_name,lead_id,rule_version_id,submission_key,report_snapshot_json,"
        "completed_at) VALUES (?,?,?,?,?,?)",
        ("Upgrade sentinel", lead_id, version_id, "assessment-005", '{"report":1}', SHANGHAI_TIME),
    ).lastrowid
    db.execute(
        "INSERT INTO roi_estimates "
        "(assessment_id,rule_version_id,recommended_scenarios_json,"
        "estimate_snapshot_json,created_at) VALUES (?,?,?,?,?)",
        (assessment_id, version_id, '["scenario"]', '{"estimate":1}', SHANGHAI_TIME),
    )
    db.execute(
        "INSERT INTO lead_consents "
        "(lead_id,policy_version,consented_at,source,identity_hash,created_at) "
        "VALUES (?,?,?,?,?,?)",
        (lead_id, "privacy-v1", SHANGHAI_TIME, "assessment", "identity-hash", SHANGHAI_TIME),
    )
    db.execute(
        "INSERT INTO lead_status_history "
        "(lead_id,previous_status,new_status,note,actor_text,created_at) "
        "VALUES (?,?,?,?,?,?)",
        (lead_id, None, "new", "created in 005", "migration-test", SHANGHAI_TIME),
    )
    db.execute(
        "INSERT INTO lead_followups "
        "(lead_id,note,next_followup_at,effective_at,actor_text,created_at) "
        "VALUES (?,?,?,?,?,?)",
        (
            lead_id, "Follow up after upgrade", "2026-08-25 09:00:00",
            SHANGHAI_TIME, "migration-test", SHANGHAI_TIME,
        ),
    )
    db.execute(
        "INSERT INTO data_subject_requests "
        "(lead_id,identity_hash,request_type,status,channel,requested_at,"
        "admin_received_at,admin_updated_at) VALUES (?,?,?,?,?,?,?,?)",
        (lead_id, "privacy-hash", "access", "received", "web", SHANGHAI_TIME, SHANGHAI_TIME, SHANGHAI_TIME),
    )
    db.execute(
        "INSERT INTO appointments "
        "(assessment_id,lead_id,submission_key,preferred_date,time_slot,status,"
        "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
        (assessment_id, lead_id, "appointment-005", "2026-08-25", "morning", "pending", SHANGHAI_TIME, SHANGHAI_TIME),
    )
    db.execute(
        "INSERT INTO analytics_events "
        "(event_name,assessment_id,analytics_id_hash,created_at) VALUES (?,?,?,?)",
        ("upgrade_sentinel", assessment_id, "analytics-hash", SHANGHAI_TIME),
    )
    legacy_ids = {
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

    protected_queries = {
        "core_industries": ("industries", "status='published'", ()),
        "core_scenarios": ("scenarios", "status='published'", ()),
        "core_services": (
            "services", "code IS NOT NULL AND status='published'", (),
        ),
        "assessment": ("assessments", "id=?", (assessment_id,)),
        "report": ("roi_estimates", "assessment_id=?", (assessment_id,)),
        "lead": ("leads", "id=?", (lead_id,)),
        "consent": ("lead_consents", "lead_id=?", (lead_id,)),
        "lead_status_history": ("lead_status_history", "lead_id=?", (lead_id,)),
        "lead_followups": ("lead_followups", "lead_id=?", (lead_id,)),
        "privacy": ("data_subject_requests", "lead_id=?", (lead_id,)),
        "appointment": ("appointments", "assessment_id=?", (assessment_id,)),
        "analytics": ("analytics_events", "assessment_id=?", (assessment_id,)),
        **{
            f"legacy_{table}": (table, "id=?", (row_id,))
            for table, row_id in legacy_ids.items()
        },
    }
    protected = {
        label: exact_rows(db, table, where, parameters)
        for label, (table, where, parameters) in protected_queries.items()
    }
    assert [row[0] for row in db.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    )] == [
        "001_initial", "002_security", "003_v2_catalog",
        "004_v2_assessment_leads", "005_v2_appointments_analytics",
    ]
    assert frozen_catalog_counts(db) == (4, 13, 6)

    monkeypatch.setattr(migrations, "MIGRATIONS_DIR", PROJECT_ROOT / "migrations")
    migrations.apply_migrations(db)
    for application_number in (1, 2):
        assert EXPECTED_CONTENT_TABLES <= database_tables(db)
        assert frozen_catalog_counts(db) == (4, 13, 6)
        assert [row[0] for row in db.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )][-1] == "006_content_catalog"
        for label, before in protected.items():
            table, where, parameters = protected_queries[label]
            assert exact_rows(db, table, where, parameters) == before, (
                application_number,
                label,
            )
        if application_number == 1:
            migrations.apply_migrations(db)


def test_content_schema_exposes_the_frozen_columns_and_real_foreign_keys(db):
    expected_columns = {
        "media_assets": {
            "id", "storage_name", "display_name", "detected_mime", "byte_size",
            "sha256", "scan_result_code", "scan_checked_at", "status",
            "created_at", "ready_at", "archived_at", "updated_at",
        },
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
        "industry_content": {"id", "content_item_id", "industry_id"},
        "scenario_content": {"id", "content_item_id", "scenario_id"},
        "service_content": {"id", "content_item_id", "service_id"},
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
        "announcement_content": {
            "id", "content_item_id", "valid_from", "valid_until", "cta_url",
        },
        "content_maturity_levels": {
            "content_item_id", "maturity_code", "sort_order",
        },
        "content_slug_aliases": {
            "id", "entry_type", "old_slug", "content_group_id", "created_at",
        },
        "scenario_cases": {
            "scenario_content_item_id", "case_content_group_id", "sort_order",
        },
        "scenario_resources": {
            "scenario_content_item_id", "resource_content_group_id", "sort_order",
        },
        "service_cases": {
            "service_content_item_id", "case_content_group_id", "sort_order",
        },
        "service_resources": {
            "service_content_item_id", "resource_content_group_id", "sort_order",
        },
        "industry_cases": {
            "industry_content_item_id", "case_content_group_id", "sort_order",
        },
        "industry_resources": {
            "industry_content_item_id", "resource_content_group_id", "sort_order",
        },
        "content_audit_events": {
            "id", "content_item_id", "event_code", "actor_text", "details_json",
            "created_at",
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

    expected_foreign_keys = {
        "media_assets": set(),
        "content_groups": {
            ("industry_id", "industries", "id", "NO ACTION"),
            ("scenario_id", "scenarios", "id", "NO ACTION"),
            ("service_id", "services", "id", "NO ACTION"),
        },
        "content_items": {
            ("content_group_id", "content_groups", "id", "NO ACTION"),
            ("share_image_media_id", "media_assets", "id", "NO ACTION"),
        },
        "content_blocks": {
            ("content_item_id", "content_items", "id", "NO ACTION"),
            ("media_asset_id", "media_assets", "id", "NO ACTION"),
        },
        "industry_content": {
            ("content_item_id", "content_items", "id", "NO ACTION"),
            ("industry_id", "industries", "id", "NO ACTION"),
        },
        "scenario_content": {
            ("content_item_id", "content_items", "id", "NO ACTION"),
            ("scenario_id", "scenarios", "id", "NO ACTION"),
        },
        "service_content": {
            ("content_item_id", "content_items", "id", "NO ACTION"),
            ("service_id", "services", "id", "NO ACTION"),
        },
        "case_content": {
            ("content_item_id", "content_items", "id", "NO ACTION"),
        },
        "case_metrics": {
            ("case_content_item_id", "content_items", "id", "NO ACTION"),
        },
        "resource_content": {
            ("content_item_id", "content_items", "id", "NO ACTION"),
            ("attachment_media_id", "media_assets", "id", "NO ACTION"),
        },
        "announcement_content": {
            ("content_item_id", "content_items", "id", "NO ACTION"),
        },
        "content_maturity_levels": {
            ("content_item_id", "content_items", "id", "NO ACTION"),
        },
        "content_slug_aliases": {
            ("content_group_id", "content_groups", "id", "NO ACTION"),
        },
        "scenario_cases": {
            ("scenario_content_item_id", "content_items", "id", "NO ACTION"),
            ("case_content_group_id", "content_groups", "id", "NO ACTION"),
        },
        "scenario_resources": {
            ("scenario_content_item_id", "content_items", "id", "NO ACTION"),
            ("resource_content_group_id", "content_groups", "id", "NO ACTION"),
        },
        "service_cases": {
            ("service_content_item_id", "content_items", "id", "NO ACTION"),
            ("case_content_group_id", "content_groups", "id", "NO ACTION"),
        },
        "service_resources": {
            ("service_content_item_id", "content_items", "id", "NO ACTION"),
            ("resource_content_group_id", "content_groups", "id", "NO ACTION"),
        },
        "industry_cases": {
            ("industry_content_item_id", "content_items", "id", "NO ACTION"),
            ("case_content_group_id", "content_groups", "id", "NO ACTION"),
        },
        "industry_resources": {
            ("industry_content_item_id", "content_items", "id", "NO ACTION"),
            ("resource_content_group_id", "content_groups", "id", "NO ACTION"),
        },
        "content_audit_events": {
            ("content_item_id", "content_items", "id", "NO ACTION"),
        },
        "legacy_content_reviews": set(),
        "legacy_content_mappings": {
            ("target_content_group_id", "content_groups", "id", "NO ACTION"),
            ("target_content_item_id", "content_items", "id", "NO ACTION"),
        },
    }
    for table, expected in expected_foreign_keys.items():
        assert foreign_keys(db, table) == expected

    expected_indexes = {
        ("content_groups", "unique_content_group_canonical_slug"): (
            1, 0, ("entry_type", "canonical_slug"), None,
        ),
        ("media_assets", "active_media_sha256_unique"): (
            1, 1, ("sha256",), "where status in ('pending', 'ready')",
        ),
        ("content_items", "one_draft_content_revision"): (
            1, 1, ("content_group_id",), "where status = 'draft'",
        ),
        ("content_items", "one_published_content_revision"): (
            1, 1, ("content_group_id",), "where status = 'published'",
        ),
        ("content_items", "one_public_slug_per_type"): (
            1, 1, ("entry_type", "slug"), "where status = 'published'",
        ),
        ("content_items", "content_items_group_status"): (
            0, 0, ("content_group_id", "status"), None,
        ),
    }
    for (table, name), (unique, partial, index_columns, predicate) in expected_indexes.items():
        assert named_index(db, table, name) == (unique, partial, index_columns)
        sql = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name=?", (name,)
        ).fetchone()[0]
        normalized_sql = " ".join(sql.lower().split())
        if predicate is not None:
            assert predicate in normalized_sql

    expected_triggers = {
        "prevent_assessment_version_code_update",
        "require_new_media_pending",
        "prevent_media_storage_name_update",
        "enforce_media_status_transition",
        "freeze_ready_media_identity",
        "prevent_content_group_identity_update",
        "require_new_content_item_draft",
        "check_content_item_entry_type_insert",
        "check_content_item_entry_type_update",
        "enforce_content_item_status_transition",
        "prevent_published_content_edit",
        "prevent_archived_content_edit",
        "validate_content_maturity_insert",
        "validate_content_maturity_update",
        "validate_content_slug_alias_insert",
        "validate_content_slug_alias_update",
        "prevent_canonical_slug_alias_collision_insert",
        "prevent_canonical_slug_alias_collision_update",
        "validate_industry_content_insert",
        "validate_industry_content_update",
        "validate_scenario_content_insert",
        "validate_scenario_content_update",
        "validate_service_content_insert",
        "validate_service_content_update",
        "validate_case_content_insert",
        "validate_case_content_update",
        "validate_resource_content_insert",
        "validate_resource_content_update",
        "validate_announcement_content_insert",
        "validate_announcement_content_update",
        "validate_case_metric_insert",
        "validate_case_metric_update",
        "validate_content_relation_scenario_cases_insert",
        "validate_content_relation_scenario_cases_update",
        "validate_content_relation_scenario_resources_insert",
        "validate_content_relation_scenario_resources_update",
        "validate_content_relation_service_cases_insert",
        "validate_content_relation_service_cases_update",
        "validate_content_relation_service_resources_insert",
        "validate_content_relation_service_resources_update",
        "validate_content_relation_industry_cases_insert",
        "validate_content_relation_industry_cases_update",
        "validate_content_relation_industry_resources_insert",
        "validate_content_relation_industry_resources_update",
        "protect_industry_content_update",
        "protect_scenario_content_update",
        "protect_service_content_update",
        "protect_case_content_update",
        "protect_resource_content_update",
        "protect_announcement_content_update",
        "protect_content_blocks_insert",
        "protect_content_blocks_update",
        "protect_content_blocks_delete",
        "protect_case_metrics_insert",
        "protect_case_metrics_update",
        "protect_case_metrics_delete",
        "protect_content_maturity_insert",
        "protect_content_maturity_update",
        "protect_content_maturity_delete",
        "protect_scenario_cases_insert",
        "protect_scenario_cases_update",
        "protect_scenario_cases_delete",
        "protect_scenario_resources_insert",
        "protect_scenario_resources_update",
        "protect_scenario_resources_delete",
        "protect_service_cases_insert",
        "protect_service_cases_update",
        "protect_service_cases_delete",
        "protect_service_resources_insert",
        "protect_service_resources_update",
        "protect_service_resources_delete",
        "protect_industry_cases_insert",
        "protect_industry_cases_update",
        "protect_industry_cases_delete",
        "protect_industry_resources_insert",
        "protect_industry_resources_update",
        "protect_industry_resources_delete",
        "validate_content_publication",
        "prevent_published_extension_delete_industry",
        "prevent_published_extension_delete_scenario",
        "prevent_published_extension_delete_service",
        "prevent_published_extension_delete_case",
        "prevent_published_extension_delete_resource",
        "prevent_published_extension_delete_announcement",
        "prevent_referenced_ready_media_archive",
        "prevent_media_asset_delete",
        "prevent_content_item_delete",
        "prevent_content_group_delete",
        "prevent_legacy_article_delete",
        "prevent_legacy_case_delete",
        "prevent_legacy_service_delete",
        "prevent_legacy_announcement_delete",
    }
    actual_triggers = {
        row[0]
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
    }
    assert actual_triggers == expected_triggers

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


@pytest.mark.parametrize("column", ["created_at", "updated_at"])
def test_published_revision_rejects_direct_timestamp_edits(db, column):
    group_id = insert_group(db, slug=f"published-{column}")
    item_id = insert_item(db, group_id, slug=f"published-{column}")
    add_announcement_extension(db, item_id)
    publish(db, item_id)

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            f"UPDATE content_items SET {column}=? WHERE id=?",
            ("2026-08-24 12:35:00", item_id),
        )


def test_published_revision_can_archive_with_a_new_updated_timestamp(db):
    group_id = insert_group(db, slug="legal-archive")
    item_id = insert_item(db, group_id, slug="legal-archive")
    add_announcement_extension(db, item_id)
    publish(db, item_id)

    archive_time = "2026-08-24 12:35:00"
    db.execute(
        "UPDATE content_items SET status='archived',archived_at=?,updated_at=? "
        "WHERE id=?",
        (archive_time, archive_time, item_id),
    )

    assert tuple(db.execute(
        "SELECT status,archived_at,updated_at FROM content_items WHERE id=?",
        (item_id,),
    ).fetchone()) == ("archived", archive_time, archive_time)


def test_publication_requires_revision_slug_to_match_group_canonical_slug(db):
    group_id = insert_group(db, slug="canonical-slug")
    item_id = insert_item(db, group_id, slug="different-slug")
    add_announcement_extension(db, item_id)

    with pytest.raises(sqlite3.IntegrityError):
        publish(db, item_id)


def test_slug_change_order_allows_archive_alias_group_update_then_publish(db):
    group_id = insert_group(db, slug="old-slug")
    old_item = insert_item(db, group_id, slug="old-slug")
    add_announcement_extension(db, old_item)
    publish(db, old_item)
    new_item = insert_item(db, group_id, revision=2, slug="new-slug")
    add_announcement_extension(db, new_item)

    archive_time = "2026-08-24 12:35:00"
    db.execute(
        "UPDATE content_items SET status='archived',archived_at=?,updated_at=? "
        "WHERE id=?",
        (archive_time, archive_time, old_item),
    )
    db.execute(
        "UPDATE content_groups SET canonical_slug=?,updated_at=? WHERE id=?",
        ("new-slug", archive_time, group_id),
    )
    db.execute(
        "INSERT INTO content_slug_aliases "
        "(entry_type,old_slug,content_group_id,created_at) VALUES (?,?,?,?)",
        ("announcement", "old-slug", group_id, archive_time),
    )
    db.execute(
        "UPDATE content_items SET status='published',published_at=?,updated_at=? "
        "WHERE id=?",
        (archive_time, archive_time, new_item),
    )

    assert tuple(db.execute(
        "SELECT canonical_slug,old_slug FROM content_groups "
        "JOIN content_slug_aliases ON content_slug_aliases.content_group_id=content_groups.id "
        "WHERE content_groups.id=?",
        (group_id,),
    ).fetchone()) == ("new-slug", "old-slug")


def test_content_group_canonical_slug_is_unique_within_entry_type(db):
    insert_group(db, slug="stable-group-slug")

    with pytest.raises(
        sqlite3.IntegrityError,
        match=(
            r"UNIQUE constraint failed: "
            r"content_groups.entry_type, content_groups.canonical_slug"
        ),
    ):
        insert_group(db, slug="stable-group-slug")

    insert_group(db, entry_type="resource", slug="stable-group-slug")


def test_public_slug_is_unique_per_type_while_draft_duplicates_are_allowed(db):
    """Probe the weaker public index only inside this function-scoped test DB."""
    db.execute("DROP INDEX unique_content_group_canonical_slug")
    first_group = insert_group(db, slug="shared-public-slug")
    second_group = insert_group(db, slug="shared-public-slug")
    first_item = insert_item(db, first_group, slug="shared-public-slug")
    second_item = insert_item(db, second_group, slug="shared-public-slug")
    add_announcement_extension(db, first_item)
    add_announcement_extension(db, second_item)
    publish(db, first_item)

    assert db.execute(
        "SELECT status FROM content_items WHERE id=?", (second_item,)
    ).fetchone()[0] == "draft"
    with pytest.raises(
        sqlite3.IntegrityError,
        match=r"UNIQUE constraint failed: content_items.entry_type, content_items.slug",
    ):
        publish(db, second_item)
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


def test_maturity_levels_require_a_scenario_owner_on_insert(db):
    announcement_group = insert_group(db, slug="wrong-maturity-owner")
    announcement_item = insert_item(
        db, announcement_group, slug="wrong-maturity-owner"
    )

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO content_maturity_levels "
            "(content_item_id,maturity_code,sort_order) VALUES (?,?,?)",
            (announcement_item, "explore", 0),
        )


def test_maturity_levels_reject_updating_owner_away_from_scenario(db):
    scenario_group = insert_group(db, entry_type="scenario", slug="maturity-scenario")
    scenario_item = insert_item(
        db, scenario_group, entry_type="scenario", slug="maturity-scenario"
    )
    announcement_group = insert_group(db, slug="maturity-announcement")
    announcement_item = insert_item(
        db, announcement_group, slug="maturity-announcement"
    )
    db.execute(
        "INSERT INTO content_maturity_levels "
        "(content_item_id,maturity_code,sort_order) VALUES (?,?,?)",
        (scenario_item, "pilot", 0),
    )

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "UPDATE content_maturity_levels SET content_item_id=? "
            "WHERE content_item_id=? AND maturity_code='pilot'",
            (announcement_item, scenario_item),
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


@pytest.mark.parametrize("status", ["ready", "archived"])
def test_new_media_rows_must_start_pending(db, status):
    is_ready = status == "ready"
    db_values = (
        f"direct-{status}.png",
        f"direct-{status}.png",
        "image/png",
        100,
        hashlib.sha256(status.encode("ascii")).hexdigest(),
        "clean" if is_ready else None,
        SHANGHAI_TIME if is_ready else None,
        status,
        SHANGHAI_TIME,
        SHANGHAI_TIME if is_ready else None,
        SHANGHAI_TIME if status == "archived" else None,
        SHANGHAI_TIME,
    )

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO media_assets "
            "(storage_name,display_name,detected_mime,byte_size,sha256,"
            "scan_result_code,scan_checked_at,status,created_at,ready_at,"
            "archived_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            db_values,
        )


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
