import sqlite3

import pytest

import models


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
    """A V0.2 assessment remains readable after all V2 schema migrations run."""
    monkeypatch.setattr(models, "DB_PATH", str(tmp_path / "platform.db"))
    models.init_db()
    db = models.get_db()
    try:
        db.execute(
            "INSERT INTO assessments (company_name, contact_email, scores, result) "
            "VALUES (?,?,?,?)",
            ("旧企业", "legacy@example.invalid", '{"legacy": 1}', "starter"),
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

    assert versions == [
        "001_initial",
        "002_security",
        "003_v2_catalog",
        "004_v2_assessment_leads",
        "005_v2_appointments_analytics",
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
