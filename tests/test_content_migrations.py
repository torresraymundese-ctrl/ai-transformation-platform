import hashlib
import json
import sqlite3
import shutil
from datetime import datetime
from pathlib import Path

import pytest

from assessment.seed import seed_v2_defaults
import catalog_content_repository as catalog
from content_clock import SHANGHAI
from content_contracts import ContentBlock, ContentDraft
from content_seed import CATALOG_SEED_PATH, SCENARIO_INPUT_SEED_PATH
import migrations
import models
import publishing_repository
from publishing_service import copy_revision


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


def _remove_task5_seed_aggregates(db):
    rows = db.execute(
        "SELECT DISTINCT ci.id,ci.content_group_id FROM content_items ci "
        "JOIN content_audit_events audit ON audit.content_item_id=ci.id "
        "WHERE ci.entry_type IN ('industry','scenario','service') "
        "AND audit.actor_text='reviewed-neutral-stage5a'"
    ).fetchall()
    item_ids = tuple(row["id"] for row in rows)
    group_ids = tuple(row["content_group_id"] for row in rows)
    if not item_ids:
        return
    trigger_sql = {
        row["name"]: row["sql"]
        for row in db.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='trigger' "
            "AND name IN ('prevent_content_item_delete','prevent_content_group_delete')"
        )
    }
    assert set(trigger_sql) == {
        "prevent_content_item_delete",
        "prevent_content_group_delete",
    }
    db.execute("DROP TRIGGER prevent_content_item_delete")
    db.execute("DROP TRIGGER prevent_content_group_delete")
    item_marks = ",".join("?" for _ in item_ids)
    for table, owner in (
        ("content_maturity_levels", "content_item_id"),
        ("scenario_public_inputs", "content_item_id"),
        ("content_blocks", "content_item_id"),
        ("industry_content", "content_item_id"),
        ("scenario_content", "content_item_id"),
        ("service_content", "content_item_id"),
        ("content_audit_events", "content_item_id"),
    ):
        db.execute(f"DELETE FROM {table} WHERE {owner} IN ({item_marks})", item_ids)
    db.execute(f"DELETE FROM content_items WHERE id IN ({item_marks})", item_ids)
    group_marks = ",".join("?" for _ in group_ids)
    db.execute(f"DELETE FROM content_groups WHERE id IN ({group_marks})", group_ids)
    for sql in trigger_sql.values():
        db.execute(sql)
    db.commit()


@pytest.fixture(autouse=True)
def migration_contract_tests_use_an_explicit_unseeded_catalog(request):
    if "db" in request.fixturenames:
        _remove_task5_seed_aggregates(request.getfixturevalue("db"))


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


def _insert_case_extension(db, item_id, basis_type):
    source_url = "https://example.com/case" if basis_type == "public_source" else None
    source_hash = hashlib.sha256(source_url.encode()).hexdigest() if source_url else None
    db.execute(
        "INSERT INTO case_content "
        "(content_item_id,verification_code,is_anonymized,basis_type,"
        "private_basis_reference,source_url,source_url_sha256,is_verified,"
        "review_confirmed,verified_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            item_id,
            "public_verified" if basis_type == "public_source" else "authorized_anonymous",
            0 if basis_type == "public_source" else 1,
            basis_type,
            None if basis_type == "public_source" else f"evidence-{basis_type}",
            source_url,
            source_hash,
            1,
            1,
            SHANGHAI_TIME,
        ),
    )


def test_009_case_basis_types_apply_on_an_empty_database(tmp_path, monkeypatch):
    """A fresh schema must accept only the three editable structured basis codes."""
    db = sqlite3.connect(tmp_path / "empty-case-basis.db")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        monkeypatch.setattr(migrations, "MIGRATIONS_DIR", PROJECT_ROOT / "migrations")
        migrations.apply_migrations(db)

        assert db.execute(
            "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
        ).fetchone()[0] == "009_case_basis_types"

        stored = []
        for index, basis_type in enumerate(
            ("public_source", "client_authorization", "internal_delivery_record")
        ):
            slug = f"empty-basis-{index}"
            group_id = insert_group(db, entry_type="case", slug=slug)
            item_id = insert_item(db, group_id, entry_type="case", slug=slug)
            _insert_case_extension(db, item_id, basis_type)
            stored.append(db.execute(
                "SELECT basis_type FROM case_content WHERE content_item_id=?",
                (item_id,),
            ).fetchone()[0])

        assert stored == [
            "public_source", "client_authorization", "internal_delivery_record"
        ]
        invalid_group = insert_group(db, entry_type="case", slug="invalid-basis")
        invalid_item = insert_item(
            db, invalid_group, entry_type="case", slug="invalid-basis"
        )
        with pytest.raises(sqlite3.IntegrityError):
            _insert_case_extension(db, invalid_item, "invented_basis")
    finally:
        db.close()


def test_009_preserves_legacy_case_rows_and_case_integrity_guards(
    tmp_path, monkeypatch
):
    """Upgrading must preserve legacy evidence exactly without making it publishable."""
    through_008 = tmp_path / "migrations-through-008"
    through_008.mkdir()
    for path in sorted((PROJECT_ROOT / "migrations").glob("00[1-8]_*.sql")):
        shutil.copy2(path, through_008 / path.name)
    monkeypatch.setattr(migrations, "MIGRATIONS_DIR", through_008)

    db = sqlite3.connect(tmp_path / "legacy-case-basis.db")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        migrations.apply_migrations(db)
        legacy_group = insert_group(db, entry_type="case", slug="legacy-private")
        legacy_item = insert_item(
            db, legacy_group, entry_type="case", slug="legacy-private"
        )
        _insert_case_extension(db, legacy_item, "private_authorization")
        legacy_before = tuple(db.execute(
            "SELECT * FROM case_content WHERE content_item_id=?", (legacy_item,)
        ).fetchone())
        columns_before = tuple(db.execute("PRAGMA table_info(case_content)"))
        foreign_keys_before = tuple(db.execute("PRAGMA foreign_key_list(case_content)"))
        preserved_trigger_names = {
            "validate_case_content_insert",
            "validate_case_content_update",
            "protect_case_content_update",
            "prevent_published_extension_delete_case",
            "validate_content_publication",
        }
        trigger_sql_before = {
            row["name"]: row["sql"]
            for row in db.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='trigger'"
            )
            if row["name"] in preserved_trigger_names
        }
        assert set(trigger_sql_before) == preserved_trigger_names
        db.commit()

        monkeypatch.setattr(migrations, "MIGRATIONS_DIR", PROJECT_ROOT / "migrations")
        migrations.apply_migrations(db)
        migrations.apply_migrations(db)

        assert db.execute(
            "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
        ).fetchone()[0] == "009_case_basis_types"
        assert tuple(db.execute(
            "SELECT * FROM case_content WHERE content_item_id=?", (legacy_item,)
        ).fetchone()) == legacy_before
        assert tuple(db.execute("PRAGMA table_info(case_content)")) == columns_before
        assert tuple(db.execute("PRAGMA foreign_key_list(case_content)")) == foreign_keys_before
        assert {
            row["name"]: row["sql"]
            for row in db.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='trigger'"
            )
            if row["name"] in preserved_trigger_names
        } == trigger_sql_before

        with pytest.raises(sqlite3.IntegrityError, match="legacy case basis"):
            publish(db, legacy_item)
        assert db.execute(
            "SELECT status FROM content_items WHERE id=?", (legacy_item,)
        ).fetchone()[0] == "draft"

        for index, basis_type in enumerate(
            ("client_authorization", "internal_delivery_record")
        ):
            slug = f"upgraded-basis-{index}"
            group_id = insert_group(db, entry_type="case", slug=slug)
            item_id = insert_item(db, group_id, entry_type="case", slug=slug)
            _insert_case_extension(db, item_id, basis_type)
            publish(db, item_id)
            with pytest.raises(
                sqlite3.IntegrityError, match="non-draft content children"
            ):
                db.execute(
                    "UPDATE case_content SET private_basis_reference='changed' "
                    "WHERE content_item_id=?",
                    (item_id,),
                )
            with pytest.raises(
                sqlite3.IntegrityError, match="published content extension is required"
            ):
                db.execute(
                    "DELETE FROM case_content WHERE content_item_id=?", (item_id,)
                )

        wrong_group = insert_group(db, entry_type="announcement", slug="wrong-case")
        wrong_item = insert_item(db, wrong_group, slug="wrong-case")
        with pytest.raises(
            sqlite3.IntegrityError, match="case extension does not match content type"
        ):
            _insert_case_extension(db, wrong_item, "client_authorization")
    finally:
        db.close()


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
        )][-1] == "009_case_basis_types"
        for label, before in protected.items():
            table, where, parameters = protected_queries[label]
            assert exact_rows(db, table, where, parameters) == before, (
                application_number,
                label,
            )
        if application_number == 1:
            migrations.apply_migrations(db)


def test_008_backfills_only_draft_services_and_preserves_non_draft_maturity(
    tmp_path, monkeypatch
):
    migration_dir = tmp_path / "migrations-through-007"
    migration_dir.mkdir()
    for path in sorted((PROJECT_ROOT / "migrations").glob("00[1-7]_*.sql")):
        shutil.copy2(path, migration_dir / path.name)
    monkeypatch.setattr(migrations, "MIGRATIONS_DIR", migration_dir)
    db = sqlite3.connect(tmp_path / "pre-008.db")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        migrations.apply_migrations(db)
        seed_v2_defaults(db)

        def add_revision(group_id, entry_type, revision, slug):
            item_id = db.execute(
                "INSERT INTO content_items "
                "(content_group_id,entry_type,revision_number,slug,title,summary,"
                "seo_title,seo_description,status,lock_version,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    group_id, entry_type, revision, slug, "Upgrade title", "Upgrade summary",
                    "Upgrade SEO", "Upgrade description", "draft", 1,
                    SHANGHAI_TIME, SHANGHAI_TIME,
                ),
            ).lastrowid
            return item_id

        draft_service_items = {}
        foundation_group = None
        for service in db.execute(
            "SELECT id,code FROM services WHERE code IS NOT NULL ORDER BY sort_order,id"
        ).fetchall():
            group_id = db.execute(
                "INSERT INTO content_groups "
                "(entry_type,service_id,canonical_slug,created_at,updated_at) "
                "VALUES ('service',?,?,?,?)",
                (service["id"], service["code"].replace("_", "-"), SHANGHAI_TIME, SHANGHAI_TIME),
            ).lastrowid
            draft_id = add_revision(
                group_id, "service", 1, service["code"].replace("_", "-")
            )
            db.execute(
                "INSERT INTO service_content (content_item_id,service_id) VALUES (?,?)",
                (draft_id, service["id"]),
            )
            draft_service_items[service["code"]] = draft_id
            if service["code"] == "foundation_workshop":
                foundation_group = group_id

        foundation_draft = draft_service_items["foundation_workshop"]
        db.execute(
            "UPDATE content_items SET status='published',published_at=?,updated_at=? WHERE id=?",
            (SHANGHAI_TIME, SHANGHAI_TIME, foundation_draft),
        )
        db.execute(
            "UPDATE content_items SET status='archived',archived_at=?,updated_at=? WHERE id=?",
            (SHANGHAI_TIME, SHANGHAI_TIME, foundation_draft),
        )
        published_service = add_revision(
            foundation_group, "service", 2, "foundation-workshop"
        )
        db.execute(
            "INSERT INTO service_content (content_item_id,service_id) "
            "SELECT ?,service_id FROM content_groups WHERE id=?",
            (published_service, foundation_group),
        )
        db.execute(
            "UPDATE content_items SET status='published',published_at=?,updated_at=? WHERE id=?",
            (SHANGHAI_TIME, SHANGHAI_TIME, published_service),
        )
        current_draft = add_revision(
            foundation_group, "service", 3, "foundation-workshop-v3"
        )
        db.execute(
            "INSERT INTO service_content (content_item_id,service_id) "
            "SELECT ?,service_id FROM content_groups WHERE id=?",
            (current_draft, foundation_group),
        )
        draft_service_items["foundation_workshop"] = current_draft

        scenario = db.execute(
            "SELECT id,code FROM scenarios WHERE code='mfg_knowledge_assistant'"
        ).fetchone()
        scenario_group = db.execute(
            "INSERT INTO content_groups "
            "(entry_type,scenario_id,canonical_slug,created_at,updated_at) "
            "VALUES ('scenario',?,?,?,?)",
            (scenario["id"], "upgrade-scenario", SHANGHAI_TIME, SHANGHAI_TIME),
        ).lastrowid
        archived_scenario = add_revision(
            scenario_group, "scenario", 1, "upgrade-scenario"
        )
        db.execute(
            "INSERT INTO scenario_content (content_item_id,scenario_id) VALUES (?,?)",
            (archived_scenario, scenario["id"]),
        )
        db.execute(
            "INSERT INTO content_maturity_levels "
            "(content_item_id,maturity_code,sort_order) VALUES (?,'pilot',0)",
            (archived_scenario,),
        )
        db.execute(
            "UPDATE content_items SET status='published',published_at=?,updated_at=? WHERE id=?",
            (SHANGHAI_TIME, SHANGHAI_TIME, archived_scenario),
        )
        db.execute(
            "UPDATE content_items SET status='archived',archived_at=?,updated_at=? WHERE id=?",
            (SHANGHAI_TIME, SHANGHAI_TIME, archived_scenario),
        )
        published_scenario = add_revision(
            scenario_group, "scenario", 2, "upgrade-scenario"
        )
        db.execute(
            "INSERT INTO scenario_content (content_item_id,scenario_id) VALUES (?,?)",
            (published_scenario, scenario["id"]),
        )
        db.execute(
            "INSERT INTO content_maturity_levels "
            "(content_item_id,maturity_code,sort_order) VALUES (?,'scale',0)",
            (published_scenario,),
        )
        db.execute(
            "UPDATE content_items SET status='published',published_at=?,updated_at=? WHERE id=?",
            (SHANGHAI_TIME, SHANGHAI_TIME, published_scenario),
        )
        db.commit()

        non_draft_before = tuple(
            tuple(row) for row in db.execute(
                "SELECT maturity.content_item_id,maturity.maturity_code,maturity.sort_order "
                "FROM content_maturity_levels maturity "
                "JOIN content_items item ON item.id=maturity.content_item_id "
                "WHERE item.status<>'draft' ORDER BY maturity.content_item_id,maturity.maturity_code"
            )
        )
        protect_before = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name='protect_content_maturity_insert'"
        ).fetchone()[0]

        monkeypatch.setattr(migrations, "MIGRATIONS_DIR", PROJECT_ROOT / "migrations")
        migrations.apply_migrations(db)

        non_draft_after = tuple(
            tuple(row) for row in db.execute(
                "SELECT maturity.content_item_id,maturity.maturity_code,maturity.sort_order "
                "FROM content_maturity_levels maturity "
                "JOIN content_items item ON item.id=maturity.content_item_id "
                "WHERE item.status<>'draft' ORDER BY maturity.content_item_id,maturity.maturity_code"
            )
        )
        protect_after = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name='protect_content_maturity_insert'"
        ).fetchone()[0]
        expected = {
            "foundation_workshop": ("explore",),
            "knowledge_assistant_pilot": ("explore", "pilot", "scale"),
            "customer_growth_pilot": ("explore", "pilot", "scale"),
            "workflow_automation": ("explore", "pilot", "scale"),
            "data_insight": ("pilot", "scale", "collaborate"),
            "industry_integration": ("pilot", "scale", "collaborate"),
        }
        actual = {
            code: tuple(
                row[0] for row in db.execute(
                    "SELECT maturity_code FROM content_maturity_levels "
                    "WHERE content_item_id=? ORDER BY sort_order,maturity_code",
                    (item_id,),
                )
            )
            for code, item_id in draft_service_items.items()
        }

        assert non_draft_after == non_draft_before
        assert protect_after == protect_before
        assert actual == expected
    finally:
        db.close()


@pytest.mark.parametrize("entry_type", ("industry", "service"))
def test_scenario_input_rows_reject_non_scenario_draft_owners(db, entry_type):
    content_id = insert_item(
        db, insert_group(db, entry_type, f"{entry_type}-input-owner"),
        entry_type=entry_type, slug=f"{entry_type}-input-owner",
    )

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO scenario_public_inputs (content_item_id,input_text,sort_order) VALUES (?,'错误归属',99)",
            (content_id,),
        )


def test_scenario_input_rows_reject_update_to_non_scenario_draft_owner(db):
    scenario_group = insert_group(db, "scenario", "scenario-input-owner")
    scenario_id = db.execute(
        "SELECT scenario_id FROM content_groups WHERE id=?", (scenario_group,)
    ).fetchone()[0]
    scenario_item = insert_item(
        db, scenario_group, entry_type="scenario", slug="scenario-input-owner",
    )
    db.execute(
        "INSERT INTO scenario_content (content_item_id,scenario_id) VALUES (?,?)",
        (scenario_item, scenario_id),
    )
    db.execute(
        "INSERT INTO scenario_public_inputs (content_item_id,input_text,sort_order) VALUES (?,'场景输入',1)",
        (scenario_item,),
    )
    industry_item = insert_item(
        db, insert_group(db, "industry", "industry-input-target"),
        entry_type="industry", slug="industry-input-target",
    )

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "UPDATE scenario_public_inputs SET content_item_id=? WHERE content_item_id=?",
            (industry_item, scenario_item),
        )


def test_scenario_input_rows_require_a_positive_sort_order(db):
    scenario_item = insert_item(
        db, insert_group(db, "scenario", "scenario-input-sort-order"),
        entry_type="scenario", slug="scenario-input-sort-order",
    )

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO scenario_public_inputs (content_item_id,input_text,sort_order) VALUES (?,'场景输入',0)",
            (scenario_item,),
        )


@pytest.mark.parametrize("sort_order", (1.5, "not-an-integer"), ids=("real", "text"))
def test_scenario_input_rows_require_an_exact_integer_sort_order(db, sort_order):
    scenario_item = insert_item(
        db, insert_group(db, "scenario", "scenario-input-exact-sort-order"),
        entry_type="scenario", slug="scenario-input-exact-sort-order",
    )

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO scenario_public_inputs (content_item_id,input_text,sort_order) VALUES (?,'场景输入',?)",
            (scenario_item, sort_order),
        )


@pytest.mark.parametrize("input_text", (
    "\u00a0", "\t", "\n", "\u3000", "x" * 300 + " ",
), ids=("nbsp", "tab", "newline", "fullwidth", "raw-length-over-300"))
def test_scenario_input_rows_reject_unicode_whitespace_and_raw_overlong_text(db, input_text):
    scenario_item = insert_item(
        db, insert_group(db, "scenario", "scenario-input-exact-text"),
        entry_type="scenario", slug="scenario-input-exact-text",
    )

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO scenario_public_inputs (content_item_id,input_text,sort_order) VALUES (?,?,1)",
            (scenario_item, input_text),
        )


def test_scenario_input_rows_reject_nul_text_even_with_a_valid_draft_owner(db):
    """Catch SQLite length() accepting a NUL-containing TEXT input as short."""
    scenario_item = insert_item(
        db, insert_group(db, "scenario", "scenario-input-nul"),
        entry_type="scenario", slug="scenario-input-nul",
    )

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO scenario_public_inputs (content_item_id,input_text,sort_order) VALUES (?,?,1)",
            (scenario_item, "有效\x00输入"),
        )


def test_scenario_input_rows_reject_blob_text_even_with_a_valid_draft_owner(db):
    scenario_item = insert_item(
        db, insert_group(db, "scenario", "scenario-input-blob"),
        entry_type="scenario", slug="scenario-input-blob",
    )

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO scenario_public_inputs (content_item_id,input_text,sort_order) VALUES (?,?,1)",
            (scenario_item, sqlite3.Binary(b"not-text")),
        )


def test_007_upgrade_backfills_published_revision_without_a_draft_and_copy_keeps_inputs(tmp_path, monkeypatch):
    legacy_migrations = tmp_path / "migrations-through-006"
    legacy_migrations.mkdir()
    for migration_path in sorted((PROJECT_ROOT / "migrations").glob("00[1-6]_*.sql")):
        shutil.copy2(migration_path, legacy_migrations / migration_path.name)
    monkeypatch.setattr(models, "DB_PATH", str(tmp_path / "upgrade.db"))
    monkeypatch.setattr(migrations, "MIGRATIONS_DIR", legacy_migrations)
    db = models.get_db()
    try:
        migrations.apply_migrations(db)
        seed_v2_defaults(db)
        catalog_entries = json.loads(CATALOG_SEED_PATH.read_text(encoding="utf-8"))["scenarios"]
        input_entries = json.loads(SCENARIO_INPUT_SEED_PATH.read_text(encoding="utf-8"))["scenarios"]
        expected_inputs = {
            entry["code"]: [
                value if type(value) is str else value["input_text"]
                for value in entry["inputs"]
            ]
            for entry in input_entries
        }
        old_ids = {}
        for entry in catalog_entries:
            scenario_id = db.execute(
                "SELECT id FROM scenarios WHERE code=?", (entry["code"],)
            ).fetchone()[0]
            old_id = publishing_repository.insert_content_draft(
                db,
                ContentDraft(
                    entry_type="scenario", slug=entry["slug"], title=entry["title"],
                    summary=entry["summary"], seo_title=entry["seo_title"],
                    seo_description=entry["seo_description"], extension={"scenario_id": scenario_id},
                    maturity_codes=tuple(entry["maturity_codes"]),
                    blocks=(ContentBlock("rich_text", body_html=entry["body_html"]),),
                ),
                actor="migration-test", now=datetime(2026, 8, 24, 10, 0, tzinfo=SHANGHAI),
            )
            old_ids[entry["code"]] = old_id
            db.execute(
                "UPDATE content_items SET status='published',published_at=?,updated_at=? WHERE id=?",
                (SHANGHAI_TIME, SHANGHAI_TIME, old_id),
            )
        db.commit()
        monkeypatch.setattr(migrations, "MIGRATIONS_DIR", PROJECT_ROOT / "migrations")
        migrations.apply_migrations(db)
        actual_inputs = {
            row["code"]: [item[0] for item in db.execute(
                "SELECT spi.input_text FROM scenario_public_inputs spi JOIN content_items ci ON ci.id=spi.content_item_id "
                "JOIN content_groups g ON g.id=ci.content_group_id JOIN scenarios s ON s.id=g.scenario_id "
                "WHERE ci.id=? ORDER BY spi.sort_order,spi.id",
                (old_ids[row["code"]],),
            )]
            for row in input_entries
        }
        assert actual_inputs == expected_inputs
    finally:
        db.close()

    assert catalog.public_scenario(
        "mfg-knowledge-assistant", datetime(2026, 8, 24, 12, 0, tzinfo=SHANGHAI)
    ) is not None
    old_id = old_ids["mfg_knowledge_assistant"]
    copied_id = copy_revision(
        old_id, actor="migration-test", now=datetime(2026, 8, 24, 12, 0, tzinfo=SHANGHAI)
    )
    upgraded = models.get_db()
    try:
        assert [row[0] for row in upgraded.execute(
            "SELECT input_text FROM scenario_public_inputs WHERE content_item_id=? ORDER BY sort_order,id",
            (copied_id,),
        )] == ["设备与工艺知识文档的受控副本", "近三个月高频现场问题清单"]
        with pytest.raises(sqlite3.IntegrityError):
            upgraded.execute(
                "UPDATE scenario_public_inputs SET input_text='不可更改' WHERE content_item_id=?", (old_id,)
            )
    finally:
        upgraded.close()


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
        "scenario_public_inputs": {
            "id", "content_item_id", "input_text", "sort_order",
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
        "scenario_public_inputs": {
            ("content_item_id", "content_items", "id", "NO ACTION"),
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
            ("scenario_public_inputs", "scenario_public_inputs_revision_order"): (
                0, 0, ("content_item_id", "sort_order", "id"), None,
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
            "protect_scenario_public_inputs_insert",
            "protect_scenario_public_inputs_update",
            "protect_scenario_public_inputs_delete",
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
        "reject_legacy_case_basis_publication",
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


def test_maturity_levels_require_a_scenario_or_service_owner_on_insert(db):
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


def test_maturity_levels_reject_updating_owner_away_from_scenario_or_service(db):
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
