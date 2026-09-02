import sqlite3
from pathlib import Path
import shutil

import pytest
from bs4 import BeautifulSoup
from flask import render_template_string
from werkzeug.security import generate_password_hash

import app as app_module
import migrations
import models


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def login_token(client):
    response = client.get("/admin/login")
    field = BeautifulSoup(response.data, "html.parser").select_one(
        'input[name="csrf_token"]'
    )
    assert field is not None
    return field["value"]


def secure_config(username, password):
    return {
        "TESTING": True,
        "SECRET_KEY": f"session-key-for-{username}",
        "ADMIN_USERNAME": username,
        "ADMIN_PASSWORD_HASH": generate_password_hash(password),
        "SESSION_COOKIE_SECURE": False,
        "PUBLIC_BASE_URL": "https://test.example",
    }


def test_create_app_builds_distinct_instances_with_isolated_auth(tmp_path, monkeypatch):
    """Tests and deployment environments must not share mutable Flask configuration."""
    monkeypatch.setattr(models, "DB_PATH", str(tmp_path / "platform.db"))
    models.init_db()

    first = app_module.create_app(secure_config("first-admin", "first-long-password"))
    second = app_module.create_app(secure_config("second-admin", "second-long-password"))
    first_client = first.test_client()
    second_client = second.test_client()

    first_response = first_client.post(
        "/admin/login",
        data={
            "csrf_token": login_token(first_client),
            "username": "first-admin",
            "password": "first-long-password",
        },
    )
    second_response = second_client.post(
        "/admin/login",
        data={
            "csrf_token": login_token(second_client),
            "username": "first-admin",
            "password": "first-long-password",
        },
    )

    assert first is not second
    assert first_response.status_code == 302
    assert second_response.status_code == 401
    assert first_client.get("/health").get_json() == {"status": "ok"}


def test_database_migrations_are_versioned_idempotent_and_preserve_data(
    tmp_path, monkeypatch
):
    """Repeated startup migrations must preserve existing business rows."""
    monkeypatch.setattr(models, "DB_PATH", str(tmp_path / "platform.db"))
    models.init_db()
    db = models.get_db()
    try:
        db.execute(
            "INSERT INTO site_config (key, value) VALUES (?, ?)",
            ("migration-sentinel", "keep-me"),
        )
        db.commit()
    finally:
        db.close()

    models.init_db()
    db = models.get_db()
    try:
        versions = [
            row[0]
            for row in db.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        ]
        sentinel = db.execute(
            "SELECT value FROM site_config WHERE key=?", ("migration-sentinel",)
        ).fetchone()[0]
    finally:
        db.close()

    assert versions == [
        "001_initial",
        "002_security",
        "003_v2_catalog",
        "004_v2_assessment_leads",
        "005_v2_appointments_analytics",
        "006_content_catalog",
        "007_scenario_public_inputs",
        "008_service_content_maturity",
        "009_case_basis_types",
        "010_ingestion_operations",
        "011_private_http_resource_drafts",
        "012_operations_query_indexes",
        "013_admin_export_audit",
    ]
    assert sentinel == "keep-me"


def test_013_adds_append_only_admin_export_audit_after_012(tmp_path, monkeypatch):
    staged = tmp_path / "migrations"
    staged.mkdir()
    for source in sorted((PROJECT_ROOT / "migrations").glob("*.sql")):
        if int(source.name[:3]) <= 12:
            shutil.copy2(source, staged / source.name)
    monkeypatch.setattr(migrations, "MIGRATIONS_DIR", staged)
    monkeypatch.setattr(models, "DB_PATH", str(tmp_path / "platform.db"))
    models.init_db()
    db = models.get_db()
    try:
        assert db.execute(
            "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
        ).fetchone()[0] == "012_operations_query_indexes"
    finally:
        db.close()

    shutil.copy2(
        PROJECT_ROOT / "migrations" / "013_admin_export_audit.sql",
        staged / "013_admin_export_audit.sql",
    )
    models.init_db()
    db = models.get_db()
    try:
        columns = {
            row["name"]: (row["type"], row["notnull"], row["pk"])
            for row in db.execute("PRAGMA table_info(admin_export_logs)")
        }
        db.execute(
            "INSERT INTO admin_export_logs "
            "(actor,filter_json,row_count,created_at) VALUES ('admin','{}',10000,?)",
            ("2026-08-21 10:30:45",),
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO admin_export_logs "
                "(actor,filter_json,row_count,created_at) VALUES ('admin','{}',10001,?)",
                ("2026-08-21 10:30:45",),
            )
    finally:
        db.close()

    assert columns == {
        "id": ("INTEGER", 0, 1),
        "actor": ("TEXT", 1, 0),
        "filter_json": ("TEXT", 1, 0),
        "row_count": ("INTEGER", 1, 0),
        "created_at": ("TEXT", 1, 0),
    }


def test_database_enforces_asset_foreign_keys(tmp_path, monkeypatch):
    """Database integrity must still hold if a future caller bypasses HTTP validation."""
    monkeypatch.setattr(models, "DB_PATH", str(tmp_path / "platform.db"))
    models.init_db()
    db = models.get_db()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO unit_b_assets (asset_code_id, quantity) VALUES (?, ?)",
                (999999, 1),
            )
    finally:
        db.close()


def test_011_rebuild_preserves_resources_and_gates_http_to_unscheduled_drafts(
    tmp_path, monkeypatch
):
    migration_011 = PROJECT_ROOT / "migrations" / "011_private_http_resource_drafts.sql"
    assert migration_011.is_file()
    staged = tmp_path / "migrations"
    staged.mkdir()
    for source in sorted((PROJECT_ROOT / "migrations").glob("0[0-1][0-9]_*.sql")):
        if source.name.startswith("011_"):
            continue
        shutil.copy2(source, staged / source.name)
    monkeypatch.setattr(migrations, "MIGRATIONS_DIR", staged)
    monkeypatch.setattr(models, "DB_PATH", str(tmp_path / "platform.db"))
    models.init_db()
    db = models.get_db()
    timestamp = "2026-08-31 10:00:00"
    try:
        media_id = db.execute(
            "INSERT INTO media_assets "
            "(storage_name,display_name,detected_mime,byte_size,sha256,status,"
            "created_at,updated_at) "
            "VALUES ('m011.pdf','m011.pdf','application/pdf',1,?,'pending',?,?)",
            ("a" * 64, timestamp, timestamp),
        ).lastrowid
        db.execute(
            "UPDATE media_assets SET status='ready',scan_result_code='clean',"
            "scan_checked_at=?,ready_at=?,updated_at=? WHERE id=?",
            (timestamp, timestamp, timestamp, media_id),
        )
        group_id = db.execute(
            "INSERT INTO content_groups (entry_type,canonical_slug,created_at,updated_at) "
            "VALUES ('resource','migration-011-sentinel',?,?)",
            (timestamp, timestamp),
        ).lastrowid
        content_id = db.execute(
            "INSERT INTO content_items "
            "(content_group_id,entry_type,revision_number,slug,title,summary,seo_title,"
            "seo_description,status,lock_version,created_at,updated_at) "
            "VALUES (?,'resource',1,'migration-011-sentinel','Sentinel','Summary',"
            "'Sentinel','Summary','draft',1,?,?)",
            (group_id, timestamp, timestamp),
        ).lastrowid
        resource_id = db.execute(
            "INSERT INTO resource_content "
            "(content_item_id,resource_type,is_original,source_name,source_url,"
            "source_url_sha256,source_check_code,source_checked_at,"
            "source_check_expires_at,source_check_url_sha256,original_published_at,"
            "copyright_notice,attachment_media_id) "
            "VALUES (?,'report',0,'Source','https://example.com/report',?,"
            "'https_ok',?,'2099-01-01 00:00:00',?,?,?,?)",
            (
                content_id,
                "b" * 64,
                timestamp,
                "b" * 64,
                timestamp,
                "Copyright",
                media_id,
            ),
        ).lastrowid
        high_group = db.execute(
            "INSERT INTO content_groups (entry_type,canonical_slug,created_at,updated_at) "
            "VALUES ('resource','migration-011-deleted-high-water',?,?)",
            (timestamp, timestamp),
        ).lastrowid
        high_content = db.execute(
            "INSERT INTO content_items "
            "(content_group_id,entry_type,revision_number,slug,title,summary,seo_title,"
            "seo_description,status,lock_version,created_at,updated_at) "
            "VALUES (?,'resource',1,'migration-011-deleted-high-water','High','Summary',"
            "'High','Summary','draft',1,?,?)",
            (high_group, timestamp, timestamp),
        ).lastrowid
        historical_resource_sequence = 5_000
        db.execute(
            "INSERT INTO resource_content "
            "(id,content_item_id,resource_type,is_original,original_published_at,"
            "copyright_notice) VALUES (?,?,'report',1,?,'Copyright')",
            (historical_resource_sequence, high_content, timestamp),
        )
        db.execute(
            "DELETE FROM resource_content WHERE id=?",
            (historical_resource_sequence,),
        )
        assert db.execute(
            "SELECT seq FROM sqlite_sequence WHERE name='resource_content'"
        ).fetchone()[0] == historical_resource_sequence
        assert db.execute("SELECT MAX(id) FROM resource_content").fetchone()[0] < (
            historical_resource_sequence
        )
        before = tuple(db.execute(
            "SELECT * FROM resource_content WHERE id=?", (resource_id,)
        ).fetchone())
        before_fk = {
            (row["from"], row["table"], row["to"])
            for row in db.execute("PRAGMA foreign_key_list(resource_content)")
        }
        db.commit()
    finally:
        db.close()

    shutil.copy2(migration_011, staged / migration_011.name)
    models.init_db()
    models.init_db()
    db = models.get_db()
    try:
        assert tuple(db.execute(
            "SELECT * FROM resource_content WHERE id=?", (resource_id,)
        ).fetchone()) == before
        assert {
            (row["from"], row["table"], row["to"])
            for row in db.execute("PRAGMA foreign_key_list(resource_content)")
        } == before_fk == {
            ("content_item_id", "content_items", "id"),
            ("attachment_media_id", "media_assets", "id"),
        }
        assert any(
            row["unique"] == 1 for row in db.execute("PRAGMA index_list(resource_content)")
        )
        triggers = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            )
        }
        assert {
            "validate_resource_content_insert",
            "validate_resource_content_update",
            "protect_resource_content_update",
            "prevent_published_extension_delete_resource",
            "validate_content_publication",
            "prevent_referenced_ready_media_archive",
            "restrict_http_resource_insert",
            "restrict_http_resource_update",
            "restrict_http_resource_owner_transition",
        }.issubset(triggers)

        db.execute(
            "UPDATE resource_content SET source_url='http://example.com/private',"
            "source_url_sha256=? WHERE id=?",
            ("c" * 64, resource_id),
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "UPDATE content_items SET publish_at=? WHERE id=?",
                (timestamp, content_id),
            )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "UPDATE content_items SET status='published',published_at=? WHERE id=?",
                (timestamp, content_id),
            )

        db.execute(
            "UPDATE resource_content SET source_url='https://example.com/private',"
            "source_url_sha256=? WHERE id=?",
            ("d" * 64, resource_id),
        )
        db.execute(
            "UPDATE content_items SET status='published',published_at=? WHERE id=?",
            (timestamp, content_id),
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "UPDATE resource_content SET source_url='http://example.com/late' WHERE id=?",
                (resource_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM resource_content WHERE id=?", (resource_id,))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "UPDATE media_assets SET status='archived' WHERE id=?", (media_id,)
            )

        next_group = db.execute(
            "INSERT INTO content_groups (entry_type,canonical_slug,created_at,updated_at) "
            "VALUES ('resource','migration-011-next',?,?)",
            (timestamp, timestamp),
        ).lastrowid
        next_content = db.execute(
            "INSERT INTO content_items "
            "(content_group_id,entry_type,revision_number,slug,title,summary,seo_title,"
            "seo_description,status,lock_version,created_at,updated_at) "
            "VALUES (?,'resource',1,'migration-011-next','Next','Summary','Next',"
            "'Summary','draft',1,?,?)",
            (next_group, timestamp, timestamp),
        ).lastrowid
        next_resource = db.execute(
            "INSERT INTO resource_content "
            "(content_item_id,resource_type,is_original,original_published_at,copyright_notice) "
            "VALUES (?,'report',1,?,'Copyright')",
            (next_content, timestamp),
        ).lastrowid
        assert next_resource > historical_resource_sequence
        versions = [
            row[0] for row in db.execute(
                "SELECT version FROM schema_migrations WHERE version LIKE '011_%'"
            )
        ]
        assert versions == ["011_private_http_resource_drafts"]
    finally:
        db.close()


def test_011_preserves_deleted_resource_high_water_when_table_is_empty(
    tmp_path, monkeypatch
):
    migration_011 = PROJECT_ROOT / "migrations" / "011_private_http_resource_drafts.sql"
    staged = tmp_path / "migrations"
    staged.mkdir()
    for source in sorted((PROJECT_ROOT / "migrations").glob("0[0-1][0-9]_*.sql")):
        if not source.name.startswith("011_"):
            shutil.copy2(source, staged / source.name)
    monkeypatch.setattr(migrations, "MIGRATIONS_DIR", staged)
    monkeypatch.setattr(models, "DB_PATH", str(tmp_path / "platform.db"))
    models.init_db()
    db = models.get_db()
    timestamp = "2026-08-31 10:00:00"
    historical_sequence = 7_000
    try:
        group_id = db.execute(
            "INSERT INTO content_groups (entry_type,canonical_slug,created_at,updated_at) "
            "VALUES ('resource','migration-011-empty-sequence',?,?)",
            (timestamp, timestamp),
        ).lastrowid
        content_id = db.execute(
            "INSERT INTO content_items "
            "(content_group_id,entry_type,revision_number,slug,title,summary,seo_title,"
            "seo_description,status,lock_version,created_at,updated_at) "
            "VALUES (?,'resource',1,'migration-011-empty-sequence','Empty','Summary',"
            "'Empty','Summary','draft',1,?,?)",
            (group_id, timestamp, timestamp),
        ).lastrowid
        db.execute(
            "INSERT INTO resource_content "
            "(id,content_item_id,resource_type,is_original,original_published_at,"
            "copyright_notice) VALUES (?,?,'report',1,?,'Copyright')",
            (historical_sequence, content_id, timestamp),
        )
        db.execute("DELETE FROM resource_content WHERE id=?", (historical_sequence,))
        assert db.execute("SELECT COUNT(*) FROM resource_content").fetchone()[0] == 0
        assert db.execute(
            "SELECT seq FROM sqlite_sequence WHERE name='resource_content'"
        ).fetchone()[0] == historical_sequence
        db.commit()
    finally:
        db.close()

    shutil.copy2(migration_011, staged / migration_011.name)
    models.init_db()
    db = models.get_db()
    try:
        assert db.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE name='resource_content_sequence_011'"
        ).fetchone()[0] == 0
        next_resource = db.execute(
            "INSERT INTO resource_content "
            "(content_item_id,resource_type,is_original,original_published_at,"
            "copyright_notice) VALUES (?,'report',1,?,'Copyright')",
            (content_id, timestamp),
        ).lastrowid
        assert next_resource > historical_sequence
    finally:
        db.close()


def test_migration_ordinals_are_unique_and_contiguous_through_013():
    paths = sorted((PROJECT_ROOT / "migrations").glob("[0-9][0-9][0-9]_*.sql"))
    ordinals = [int(path.name[:3]) for path in paths]

    assert ordinals == list(range(1, 14))


def test_012_adds_only_real_column_operations_indexes_from_recorded_011(
    tmp_path, monkeypatch
):
    migration_012 = PROJECT_ROOT / "migrations" / "012_operations_query_indexes.sql"
    assert migration_012.is_file()
    staged = tmp_path / "migrations"
    staged.mkdir()
    for source in sorted((PROJECT_ROOT / "migrations").glob("0[0-1][0-9]_*.sql")):
        if int(source.name[:3]) <= 11:
            shutil.copy2(source, staged / source.name)
    monkeypatch.setattr(migrations, "MIGRATIONS_DIR", staged)
    monkeypatch.setattr(models, "DB_PATH", str(tmp_path / "platform.db"))
    models.init_db()
    expected = {
        "operations_leads_ordinary": ("leads", ("anonymized_at", "status", "created_at", "id")),
        "operations_leads_followup": ("leads", ("anonymized_at", "next_followup_at", "id")),
        "operations_assessments_branch": ("assessments", ("lead_id", "branch_code", "completed_at", "id")),
        "operations_assessments_latest": ("assessments", ("lead_id", "completed_at", "id")),
        "operations_appointments_queue": ("appointments", ("status", "preferred_date", "time_slot", "id")),
        "operations_appointments_latest": ("appointments", ("lead_id", "created_at", "id")),
        "operations_data_requests_queue": ("data_subject_requests", ("status", "requested_at", "id")),
        "operations_content_ordinary": ("content_items", ("status", "updated_at", "id")),
        "operations_content_scheduled": ("content_items", ("status", "publish_at", "id")),
        "operations_media_queue": ("media_assets", ("status", "updated_at", "id")),
        "operations_ingestion_queue": ("ingestion_candidates", ("state", "updated_at", "id")),
    }
    db = models.get_db()
    try:
        assert db.execute(
            "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
        ).fetchone()[0] == "011_private_http_resource_drafts"
        sentinel_id = db.execute(
            "INSERT INTO leads (company_name,contact_name,status,created_at,updated_at) "
            "VALUES ('sentinel','sentinel','new','2026-08-31 10:00:00','2026-08-31 10:00:00')"
        ).lastrowid
        for table, columns in {value for value in expected.values()}:
            existing = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
            assert set(columns) <= existing
        db.commit()
    finally:
        db.close()
    shutil.copy2(migration_012, staged / migration_012.name)
    models.init_db()
    models.init_db()
    db = models.get_db()
    try:
        assert db.execute("SELECT company_name FROM leads WHERE id=?", (sentinel_id,)).fetchone()[0] == "sentinel"
        for name, (table, columns) in expected.items():
            row = db.execute(
                "SELECT tbl_name FROM sqlite_master WHERE type='index' AND name=?", (name,)
            ).fetchone()
            assert row is not None and row[0] == table
            assert tuple(item[2] for item in db.execute(f"PRAGMA index_info({name})")) == columns
        assert db.execute(
            "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
        ).fetchone()[0] == "012_operations_query_indexes"
        assert not db.execute(
            "SELECT name FROM sqlite_temp_master WHERE type IN ('table','index')"
        ).fetchall()
    finally:
        db.close()


def test_012_representative_queue_plans_use_each_approved_index(db):
    timestamp = "2026-08-31 10:00:00"
    for number in range(120):
        lead_id = db.execute(
            "INSERT INTO leads (company_name,contact_name,status,next_followup_at,"
            "created_at,updated_at) VALUES (?,?, 'new',?,?,?)",
            (
                f"plan-company-{number}",
                f"plan-contact-{number}",
                f"2026-09-{(number % 20) + 1:02d} 10:00:00",
                timestamp,
                timestamp,
            ),
        ).lastrowid
        assessment_id = db.execute(
            "INSERT INTO assessments (lead_id,branch_code,completed_at) VALUES "
            "(?,'manufacturing',?)",
            (lead_id, timestamp),
        ).lastrowid
        db.execute(
            "INSERT INTO appointments (assessment_id,lead_id,submission_key,"
            "preferred_date,time_slot,status,created_at,updated_at) "
            "VALUES (?,?,?,'2026-09-01','morning','pending',?,?)",
            (assessment_id, lead_id, f"plan-appointment-{number}", timestamp, timestamp),
        )
        db.execute(
            "INSERT INTO data_subject_requests (lead_id,identity_hash,request_type,"
            "status,channel,requested_at) VALUES (?,?,'access','received','email',?)",
            (lead_id, f"plan-request-{number}", timestamp),
        )
        group_id = db.execute(
            "INSERT INTO content_groups (entry_type,canonical_slug,created_at,updated_at) "
            "VALUES ('case',?,?,?)",
            (f"plan-case-{number}", timestamp, timestamp),
        ).lastrowid
        db.execute(
            "INSERT INTO content_items (content_group_id,entry_type,revision_number,slug,"
            "title,summary,seo_title,seo_description,status,lock_version,created_at,updated_at) "
            "VALUES (?,'case',1,?,?,?,'Plan','Plan','draft',1,?,?)",
            (group_id, f"plan-case-{number}", f"Plan {number}", "Plan", timestamp, timestamp),
        )
        db.execute(
            "INSERT INTO media_assets (storage_name,display_name,detected_mime,byte_size,"
            "sha256,status,created_at,updated_at) VALUES (?,?, 'application/pdf',1,?,"
            "'pending',?,?)",
            (
                f"plan-media-{number}.pdf",
                f"plan-media-{number}.pdf",
                f"{number + 1:064x}",
                timestamp,
                timestamp,
            ),
        )
        db.execute(
            "INSERT INTO ingestion_candidates (source_code,source_name,canonical_url,"
            "content_sha256,title,licensed_summary,state,lock_version,created_at,updated_at) "
            "VALUES ('plan','Plan',?,?,?,'Plan','fetched',1,?,?)",
            (
                f"https://example.invalid/plan/{number}",
                f"{number + 1000:064x}",
                f"Plan {number}",
                timestamp,
                timestamp,
            ),
        )
    db.commit()
    db.execute("ANALYZE")
    probes = (
        ("operations_leads_ordinary", "SELECT id FROM leads WHERE anonymized_at IS NULL AND status='new' ORDER BY created_at DESC,id DESC"),
        ("operations_leads_followup", "SELECT id FROM leads WHERE anonymized_at IS NULL AND next_followup_at IS NOT NULL ORDER BY next_followup_at,id"),
        ("operations_assessments_branch", "SELECT id FROM assessments WHERE lead_id=1 AND branch_code='manufacturing' ORDER BY completed_at DESC,id DESC"),
        ("operations_assessments_latest", "SELECT id FROM assessments WHERE lead_id=1 ORDER BY completed_at DESC,id DESC"),
        ("operations_appointments_queue", "SELECT id FROM appointments WHERE status='pending' ORDER BY preferred_date,time_slot,id"),
        ("operations_appointments_latest", "SELECT id FROM appointments WHERE lead_id=1 ORDER BY created_at DESC,id DESC"),
        ("operations_data_requests_queue", "SELECT id FROM data_subject_requests WHERE status='received' ORDER BY requested_at DESC,id DESC"),
        ("operations_content_ordinary", "SELECT id FROM content_items WHERE status='draft' ORDER BY updated_at DESC,id DESC"),
        ("operations_content_scheduled", "SELECT id FROM content_items WHERE status='draft' AND publish_at IS NOT NULL ORDER BY publish_at,id"),
        ("operations_media_queue", "SELECT id FROM media_assets WHERE status='ready' ORDER BY updated_at DESC,id DESC"),
        ("operations_ingestion_queue", "SELECT id FROM ingestion_candidates WHERE state='fetched' ORDER BY updated_at DESC,id DESC"),
    )
    for index_name, sql in probes:
        details = " ".join(
            row["detail"] for row in db.execute("EXPLAIN QUERY PLAN " + sql)
        )
        assert index_name in details, (index_name, details)


def test_blueprints_delegate_database_access_to_repositories():
    """HTTP adapters must not grow a second, route-local data-access layer."""
    violations = []
    for path in (PROJECT_ROOT / "blueprints").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "get_db" in source or ".execute(" in source or "execute_write" in source:
            violations.append(path.relative_to(PROJECT_ROOT).as_posix())

    assert violations == []


def test_base_design_system_and_behaviors_are_external_static_assets(client):
    """The shared shell must stay small and load cacheable CSS/JS from /static."""
    response = client.get("/")
    page = BeautifulSoup(response.data, "html.parser")

    stylesheet = page.select_one('link[rel="stylesheet"][href="/static/css/app.css"]')
    script = page.select_one('script[src="/static/js/app.js"]')

    assert stylesheet is not None
    assert script is not None
    assert client.get("/static/css/app.css").status_code == 200
    assert client.get("/static/js/app.js").status_code == 200
    assert b"Scroll animations + Sticky CTA" not in response.data


def test_legacy_services_path_redirects_to_the_canonical_catalog(client):
    response = client.get("/services")

    assert response.status_code == 301
    assert response.headers["Location"] == "/service-packages"


def test_shared_shells_are_composed_from_named_template_components():
    public_shell = (PROJECT_ROOT / "templates" / "base.html").read_text(
        encoding="utf-8"
    )
    admin_shell = (
        PROJECT_ROOT / "templates" / "admin" / "base_admin.html"
    ).read_text(encoding="utf-8")
    expected_files = {
        "navigation.html",
        "footer.html",
        "sticky_cta.html",
        "admin_navigation.html",
        "ui.html",
    }

    component_dir = PROJECT_ROOT / "templates" / "components"
    assert {path.name for path in component_dir.glob("*.html")} >= expected_files
    assert 'include "components/navigation.html"' in public_shell
    assert 'include "components/footer.html"' in public_shell
    assert 'include "components/sticky_cta.html"' in public_shell
    assert 'include "components/admin_navigation.html"' in admin_shell


def test_ui_component_macros_escape_values_and_expose_accessible_state(client):
    with client.application.test_request_context("/component-test"):
        rendered = render_template_string(
            """
            {% from "components/ui.html" import alert, form_field, pagination %}
            {{ alert("<unsafe>", "error") }}
            {{ form_field("company", "企业", "<script>", required=true) }}
            {{ pagination(2, 3, "public.index") }}
            """
        )
    page = BeautifulSoup(rendered, "html.parser")

    assert page.select_one('[role="alert"]').get_text(strip=True) == "<unsafe>"
    assert page.select_one('input[name="company"]')["value"] == "<script>"
    assert page.select_one('input[name="company"]').has_attr("required")
    assert page.select_one('[aria-current="page"]').get_text(strip=True) == "2"
