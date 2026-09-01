import sqlite3
import shutil
from pathlib import Path

import pytest

import migrations
import models


PROJECT_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_V2_TABLES = {
    "industries",
    "industry_branches",
    "departments",
    "scenarios",
    "scenario_branches",
    "scenario_departments",
    "service_deliverables",
    "scenario_services",
    "assessment_versions",
    "assessment_questions",
    "assessment_options",
    "industry_benchmarks",
    "assessment_branch_weights",
    "company_sizes",
    "pain_points",
    "scenario_pains",
    "scenario_budget_options",
    "roi_option_ranges",
    "scenario_roi_profiles",
    "roi_estimates",
    "leads",
    "lead_consents",
    "lead_status_history",
    "lead_followups",
    "data_subject_requests",
    "appointments",
    "analytics_events",
}


def test_v2_migrations_preserve_legacy_assessment_and_create_core_schema(
    tmp_path, monkeypatch
):
    """A row created with only 001+002 remains readable after the V2 upgrade."""
    monkeypatch.setattr(models, "DB_PATH", str(tmp_path / "platform.db"))
    legacy_migrations_dir = tmp_path / "legacy_migrations"
    legacy_migrations_dir.mkdir()
    for migration_name in ("001_initial.sql", "002_security.sql"):
        shutil.copy2(
            PROJECT_ROOT / "migrations" / migration_name,
            legacy_migrations_dir / migration_name,
        )
    monkeypatch.setattr(migrations, "MIGRATIONS_DIR", legacy_migrations_dir)
    models.init_db()
    db = models.get_db()
    try:
        versions_before_upgrade = [
            row[0]
            for row in db.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
        db.execute(
            "INSERT INTO assessments (company_name, contact_email, scores, result) "
            "VALUES (?,?,?,?)",
            ("旧企业", "legacy@example.invalid", '{"legacy": 1}', "starter"),
        )
        db.commit()
    finally:
        db.close()

    v2_migrations_dir = tmp_path / "v2_migrations_through_005"
    v2_migrations_dir.mkdir()
    for migration_name in (
        "001_initial.sql",
        "002_security.sql",
        "003_v2_catalog.sql",
        "004_v2_assessment_leads.sql",
        "005_v2_appointments_analytics.sql",
    ):
        shutil.copy2(
            PROJECT_ROOT / "migrations" / migration_name,
            v2_migrations_dir / migration_name,
        )
    monkeypatch.setattr(migrations, "MIGRATIONS_DIR", v2_migrations_dir)
    models.init_db()
    db = models.get_db()
    try:
        versions_before_content = [
            row[0]
            for row in db.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
        monkeypatch.setattr(migrations, "MIGRATIONS_DIR", PROJECT_ROOT / "migrations")
        migrations.apply_migrations(db)
        migrations.apply_migrations(db)
        versions = [
            row[0]
            for row in db.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
        columns = {row[1] for row in db.execute("PRAGMA table_info(assessments)")}
        tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        legacy_company_name = db.execute(
            "SELECT company_name FROM assessments"
        ).fetchone()[0]
    finally:
        db.close()

    assert versions_before_upgrade == ["001_initial", "002_security"]
    assert versions_before_content == [
        "001_initial",
        "002_security",
        "003_v2_catalog",
        "004_v2_assessment_leads",
        "005_v2_appointments_analytics",
    ]
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
    ]
    assert {
        "submission_key",
        "lead_id",
        "rule_version_id",
        "branch_code",
        "subbranch_code",
        "department_code",
        "company_size_code",
        "answers_json",
        "dimension_scores_json",
        "overall_score",
        "maturity_code",
        "report_snapshot_json",
        "attribution_json",
        "completed_at",
    } <= columns
    assert EXPECTED_V2_TABLES <= tables
    assert legacy_company_name == "旧企业"


def test_failed_migration_rolls_back_schema_and_can_be_retried(tmp_path, monkeypatch):
    """A failed migration must leave no partial schema that prevents a retry."""
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    migration_path = migrations_dir / "001_atomic.sql"
    migration_path.write_text(
        "CREATE TABLE retry_target (id INTEGER PRIMARY KEY);\n"
        "CREATE TABLE retry_target (id INTEGER PRIMARY KEY);\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(migrations, "MIGRATIONS_DIR", migrations_dir)
    db = sqlite3.connect(tmp_path / "platform.db")
    try:
        with pytest.raises(sqlite3.OperationalError, match="already exists"):
            migrations.apply_migrations(db)

        table_names = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        versions = [
            row[0]
            for row in db.execute("SELECT version FROM schema_migrations ORDER BY version")
        ]

        migration_path.write_text(
            "CREATE TABLE retry_target (id INTEGER PRIMARY KEY);\n",
            encoding="utf-8",
        )
        migrations.apply_migrations(db)
        retried_versions = [
            row[0]
            for row in db.execute("SELECT version FROM schema_migrations ORDER BY version")
        ]
    finally:
        db.close()

    assert "retry_target" not in table_names
    assert versions == []
    assert retried_versions == ["001_atomic"]


def test_scenario_branch_links_reference_industry_branches(tmp_path, monkeypatch):
    """A scenario assignment must point to a specific industry branch."""
    monkeypatch.setattr(models, "DB_PATH", str(tmp_path / "platform.db"))
    models.init_db()
    db = models.get_db()
    try:
        industry_id = db.execute(
            "INSERT INTO industries (code, name) VALUES (?, ?)",
            ("industry", "Industry"),
        ).lastrowid
        industry_branch_id = db.execute(
            "INSERT INTO industry_branches (industry_id, code, name) VALUES (?, ?, ?)",
            (industry_id, "industry_branch", "Industry branch"),
        ).lastrowid
        scenario_id = db.execute(
            "INSERT INTO scenarios "
            "(code,category_code,public_name,minimum_business_value,minimum_process,"
            "minimum_data,minimum_systems,minimum_organization,minimum_delivery,"
            "integration_level,min_weeks,max_weeks,risk_codes_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "scenario", "category", "Scenario", 0, 0, 0, 0, 0, 0,
                "low", 1, 1, "[]",
            ),
        ).lastrowid

        db.execute(
            "INSERT INTO scenario_branches (scenario_id, industry_branch_id) "
            "VALUES (?, ?)",
            (scenario_id, industry_branch_id),
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO scenario_branches (scenario_id, industry_branch_id) "
                "VALUES (?, ?)",
                (scenario_id, industry_branch_id + 1),
            )
    finally:
        db.close()


def test_analytics_server_events_are_idempotent_without_blocking_anonymous_events(
    tmp_path, monkeypatch
):
    """Only assessment-linked server events deduplicate retry deliveries."""
    monkeypatch.setattr(models, "DB_PATH", str(tmp_path / "platform.db"))
    models.init_db()
    db = models.get_db()
    try:
        assessment_id = db.execute(
            "INSERT INTO assessments (company_name) VALUES (?)", ("retry target",)
        ).lastrowid
        db.execute(
            "INSERT INTO analytics_events (assessment_id, event_name) VALUES (?, ?)",
            (assessment_id, "report_generated"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO analytics_events (assessment_id, event_name) VALUES (?, ?)",
                (assessment_id, "report_generated"),
            )
        db.execute(
            "INSERT INTO analytics_events (assessment_id, event_name) VALUES (NULL, ?)",
            ("page_viewed",),
        )
        db.execute(
            "INSERT INTO analytics_events (assessment_id, event_name) VALUES (NULL, ?)",
            ("page_viewed",),
        )
        db.commit()
        anonymous_count = db.execute(
            "SELECT COUNT(*) FROM analytics_events WHERE assessment_id IS NULL"
        ).fetchone()[0]
        analytics_columns = {
            row[1] for row in db.execute("PRAGMA table_info(analytics_events)")
        }
    finally:
        db.close()

    assert anonymous_count == 2
    assert not {"contact_name", "contact_email", "phone", "wechat"} & analytics_columns
