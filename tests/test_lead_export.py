import csv
from datetime import datetime
from io import StringIO
import json
import sqlite3
import uuid

from bs4 import BeautifulSoup
from werkzeug.datastructures import MultiDict
import pytest

import assessment_repository
from assessment.contracts import (
    AssessmentProfile,
    Attribution,
    CompletionRequest,
    Consent,
    Contact,
)
from assessment_completion_service import complete_assessment
import lead_export
import lead_repository
import models
from validation import ValidationError


EXPECTED_EXPORT_HEADERS = (
    "企业名称",
    "联系人",
    "手机号",
    "邮箱",
    "微信",
    "线索状态",
    "负责人",
    "行业分支",
    "部门",
    "评估编号",
    "成熟度",
    "推荐主场景",
    "预约状态",
    "意向日期",
    "时间段",
    "最后有效跟进时间",
    "下次跟进时间",
)
QUESTION_CODES = (
    "business_value_frequency",
    "business_value_scope",
    "process_documentation",
    "process_stability",
    "data_availability",
    "data_quality",
    "systems_foundation",
    "systems_automation",
    "organization_owner",
    "organization_adoption",
    "delivery_budget",
    "delivery_timeline",
)
FIXED_NOW = datetime(2026, 8, 21, 10, 30, 45)


def _completion_request(*, suffix="one"):
    return CompletionRequest(
        submission_key=str(uuid.uuid4()),
        profile=AssessmentProfile(
            branch_code="manufacturing",
            subbranch_code="discrete_manufacturing",
            department_code="production",
            company_size_code="50_200",
            pain_codes=("production_reporting",),
            answers={code: "level_3" for code in QUESTION_CODES},
            roi_choices={
                "headcount": "6_20",
                "monthly_hours": "20_80",
                "monthly_cost": "8000_15000",
                "loss_factor": "normal",
                "budget": "50000_200000",
            },
        ),
        contact=Contact(
            company_name=f"{suffix}企业",
            contact_name=f"{suffix}联系人",
            phone=f"139{sum(map(ord, suffix)) % 100_000_000:08d}",
            email=f"{suffix}@example.invalid",
            wechat=f"wx_{suffix}",
        ),
        consent=Consent(accepted=True, policy_version="2026-08-19"),
        attribution=Attribution(source="website_assessment"),
    )


def _create_completed_lead(*, suffix="one", status="new"):
    result = complete_assessment(_completion_request(suffix=suffix), "ip-hash")
    db = models.get_db()
    try:
        db.execute(
            "UPDATE leads SET status=?,owner_text='Owner',"
            "last_effective_followup_at='2026-08-20 09:00:00',"
            "next_followup_at='2026-08-25 10:00:00',"
            "created_at='2026-08-20 08:00:00',updated_at='2026-08-20 08:00:00' "
            "WHERE id=?",
            (status, result.lead_id),
        )
        db.commit()
    finally:
        db.close()
    return result.lead_id, result.assessment_id


def _post_export(admin_client, **filters):
    return admin_client.post(
        "/admin/leads/export",
        data={"csrf_token": "test-csrf-token", **filters},
    )


def _decode_csv(payload):
    assert payload.startswith(b"\xef\xbb\xbf")
    return list(csv.reader(StringIO(payload.decode("utf-8-sig"))))


def _db_row(statement, parameters=()):
    db = models.get_db()
    try:
        return db.execute(statement, parameters).fetchone()
    finally:
        db.close()


@pytest.mark.parametrize("value", ["=1+1", "+CMD", "-2+3", "@SUM(A1)", "  =1"])
def test_csv_neutralizes_formula_prefix(value):
    assert lead_export.csv_cell(value).startswith("'")


def test_csv_normalizes_nfkc_controls_quotes_newlines_and_phone_as_text():
    row = {
        "company_name": "Ａ\x00公司\n总部",
        "contact_name": 'A "quoted" name',
        "phone": "13800138000",
        "email": "＝SUM(A1)",
        "wechat": None,
        "status": "new",
        "owner_text": None,
        "industry_branch": None,
        "department": None,
        "assessment_number": None,
        "maturity": None,
        "primary_scenario": None,
        "appointment_status": None,
        "preferred_date": None,
        "time_slot": None,
        "last_effective_followup_at": None,
        "next_followup_at": None,
    }

    rows = _decode_csv(lead_export.write_lead_csv([row]))

    assert tuple(rows[0]) == EXPECTED_EXPORT_HEADERS
    assert rows[1][0] == "A公司\n总部"
    assert rows[1][1] == 'A "quoted" name'
    assert rows[1][2] == "'13800138000"
    assert rows[1][3] == "'=SUM(A1)"


def test_report_summary_dispatcher_accepts_only_complete_frozen_v2_snapshot(client):
    _, assessment_id = _create_completed_lead(suffix="dispatcher")
    raw = _db_row(
        "SELECT report_snapshot_json FROM assessments WHERE id=?",
        (assessment_id,),
    )[0]
    snapshot = json.loads(raw)
    expected = (
        snapshot["scores"]["maturity_code"],
        snapshot["recommendations"][0]["scenario"]["code"],
    )

    assert assessment_repository.report_summary_from_snapshot(raw) == expected

    snapshot["schema_version"] = "2.1"
    assert assessment_repository.report_summary_from_snapshot(json.dumps(snapshot)) is None
    snapshot["schema_version"] = "2.0"
    snapshot["contact_email"] = "private@example.invalid"
    assert assessment_repository.report_summary_from_snapshot(json.dumps(snapshot)) is None
    assert assessment_repository.report_summary_from_snapshot("not-json") is None
    assert assessment_repository.report_summary_from_snapshot(
        " " * (assessment_repository.MAX_REPORT_SNAPSHOT_BYTES + 1)
    ) is None


@pytest.mark.parametrize(
    "values",
    (
        MultiDict((("status", "new"), ("status", "won"))),
        MultiDict((("q", "first"), ("q", "second"))),
        {"unknown": "value"},
        {"page": "2"},
        {"status": "invalid"},
        {"branch": "invalid"},
        {"date_from": "2026-99-99"},
        {"queue": "invalid"},
        {"q": "x" * 101},
        {"q": "private\x00search"},
        {"q": "private\u202esearch"},
        {"q": "private\u200bsearch"},
        {"q": "private\x85search"},
    ),
)
def test_strict_export_filter_parser_rejects_widening_inputs(values):
    with pytest.raises(ValidationError):
        lead_repository.parse_export_filters(values)


def test_strict_export_filter_parser_returns_exact_task15_dto():
    filters = lead_repository.parse_export_filters(
        {
            "csrf_token": "ignored-by-parser",
            "status": "pending_contact",
            "branch": "manufacturing",
            "date_from": "2026-08-01",
            "date_to": "2026-08-31",
            "queue": "followup",
            "q": "  ＡCＭＥ  ",
        }
    )

    assert filters == lead_repository.LeadFilters(
        status="pending_contact",
        branch="manufacturing",
        date_from="2026-08-01",
        date_to="2026-08-31",
        queue="followup",
        search="ACME",
    )


def test_export_rows_reuses_filters_excludes_anonymized_and_selects_latest_relations(client):
    lead_id, first_assessment = _create_completed_lead(
        suffix="wanted", status="pending_contact"
    )
    other_id, _ = _create_completed_lead(suffix="anon", status="pending_contact")
    db = models.get_db()
    try:
        raw = db.execute(
            "SELECT report_snapshot_json FROM assessments WHERE id=?",
            (first_assessment,),
        ).fetchone()[0]
        latest_assessment = db.execute(
            "INSERT INTO assessments "
            "(submission_key,lead_id,rule_version_id,branch_code,subbranch_code,"
            "department_code,company_size_code,answers_json,dimension_scores_json,"
            "overall_score,maturity_code,report_snapshot_json,attribution_json,completed_at) "
            "SELECT ?,lead_id,rule_version_id,'manufacturing',subbranch_code,'operations',"
            "company_size_code,answers_json,dimension_scores_json,overall_score,"
            "maturity_code,?,attribution_json,'2099-08-22 10:00:00' "
            "FROM assessments WHERE id=?",
            (str(uuid.uuid4()), raw, first_assessment),
        ).lastrowid
        db.execute(
            "INSERT INTO appointments "
            "(assessment_id,lead_id,submission_key,preferred_date,time_slot,status,created_at) "
            "VALUES (?,?,?,?,?,'pending','2026-08-20 10:00:00')",
            (first_assessment, lead_id, str(uuid.uuid4()), "2026-09-01", "morning"),
        )
        db.execute(
            "INSERT INTO appointments "
            "(assessment_id,lead_id,submission_key,preferred_date,time_slot,status,created_at) "
            "VALUES (?,?,?,?,?,'confirmed','2026-08-21 10:00:00')",
            (latest_assessment, lead_id, str(uuid.uuid4()), "2026-09-02", "afternoon"),
        )
        db.execute(
            "UPDATE leads SET anonymized_at='2026-08-21 12:00:00' WHERE id=?",
            (other_id,),
        )
        db.commit()
    finally:
        db.close()

    statements = []
    original_get_db = lead_repository.get_db

    def traced_get_db():
        connection = original_get_db()
        connection.set_trace_callback(statements.append)
        return connection

    lead_repository.get_db = traced_get_db
    try:
        rows = lead_repository.export_rows(
            lead_repository.LeadFilters(
                status="pending_contact",
                branch="manufacturing",
                queue="followup",
                search="wanted",
            )
        )
    finally:
        lead_repository.get_db = original_get_db

    assert len(rows) == 1
    assert rows[0]["assessment_number"] == latest_assessment
    assert rows[0]["department"] == "operations"
    assert rows[0]["appointment_status"] == "confirmed"
    assert rows[0]["preferred_date"] == "2026-09-02"
    assert rows[0]["time_slot"] == "afternoon"
    selects = [sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 1
    assert "COUNT(" not in selects[0].upper()
    assert "LIMIT 10001" in selects[0].upper()


def test_export_route_is_post_only_authenticated_and_csrf_protected(client, admin_client):
    assert admin_client.get("/admin/leads/export").status_code == 405
    anonymous = client.application.test_client()
    response = anonymous.post("/admin/leads/export", data={"csrf_token": "unbound"})
    assert response.status_code == 302
    assert "/admin/login" in response.headers["Location"]
    assert admin_client.post("/admin/leads/export").status_code == 403


def test_export_has_exact_columns_headers_timestamp_and_private_cache(admin_client):
    lead_id, assessment_id = _create_completed_lead(
        suffix="headers", status="pending_contact"
    )
    calls = []

    def fixed_clock():
        calls.append(True)
        return FIXED_NOW

    admin_client.application.config["ADMIN_NOW_PROVIDER"] = fixed_clock
    response = _post_export(admin_client, status="pending_contact")
    rows = _decode_csv(response.data)

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/csv; charset=utf-8"
    assert response.headers["Content-Disposition"] == (
        'attachment; filename="leads-20260821-103045.csv"'
    )
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["Expires"] == "0"
    assert calls == [True]
    assert tuple(rows[0]) == EXPECTED_EXPORT_HEADERS
    assert len(rows) == 2
    assert rows[1][9] == str(assessment_id)
    assert rows[1][2].startswith("'")
    forbidden = {
        "analytics_id_hash",
        "ip_hash",
        "answers_json",
        "report_snapshot_json",
        "resolution_note",
    }
    assert not forbidden.intersection(rows[0])
    serialized = response.get_data(as_text=True)
    assert "website_assessment" not in serialized
    assert str(lead_id) not in rows[0]


def test_export_form_submits_only_current_filters_and_csrf(admin_client):
    response = admin_client.get(
        "/admin/leads?status=new&branch=manufacturing&date_from=2026-08-01&"
        "date_to=2026-08-31&queue=followup&q=ACME&page=2&per_page=50"
    )
    page = BeautifulSoup(response.data, "html.parser")
    form = page.select_one('form[action="/admin/leads/export"]')

    assert form is not None
    assert form["method"].lower() == "post"
    fields = {item.get("name"): item.get("value", "") for item in form.select("input")}
    assert fields == {
        "csrf_token": "test-csrf-token",
        "status": "new",
        "branch": "manufacturing",
        "date_from": "2026-08-01",
        "date_to": "2026-08-31",
        "queue": "followup",
        "q": "ACME",
    }
    assert "page" not in fields
    assert "per_page" not in fields


def test_invalid_export_filters_return_generic_400_without_csv_or_audit(admin_client):
    response = _post_export(admin_client, status="not-real")

    assert response.status_code == 400
    assert response.mimetype == "text/html"
    assert "not-real" not in response.get_data(as_text=True)
    assert _db_row("SELECT COUNT(*) FROM admin_export_logs")[0] == 0


def _bulk_insert_leads(count):
    db = models.get_db()
    try:
        db.execute(
            "WITH RECURSIVE n(value) AS ("
            "VALUES(1) UNION ALL SELECT value+1 FROM n WHERE value<?) "
            "INSERT INTO leads (company_name,contact_name,status,created_at,updated_at) "
            "SELECT 'Bulk-'||value,'Contact-'||value,'new',"
            "'2026-08-20 10:00:00','2026-08-20 10:00:00' FROM n",
            (count,),
        )
        db.commit()
    finally:
        db.close()


def test_exactly_10000_rows_export_successfully_and_audit_exact_count(admin_client):
    _bulk_insert_leads(10_000)
    admin_client.application.config["ADMIN_NOW_PROVIDER"] = lambda: FIXED_NOW

    response = _post_export(admin_client)

    assert response.status_code == 200
    assert len(_decode_csv(response.data)) == 10_001
    audit = _db_row("SELECT actor,row_count,created_at FROM admin_export_logs")
    assert tuple(audit) == ("test-admin", 10_000, "2026-08-21 10:30:45")


def test_10001_rows_return_generic_400_without_partial_csv_or_audit(admin_client):
    _bulk_insert_leads(10_001)

    response = _post_export(admin_client)

    assert response.status_code == 400
    assert response.mimetype == "text/html"
    assert not response.data.startswith(b"\xef\xbb\xbf")
    assert _db_row("SELECT COUNT(*) FROM admin_export_logs")[0] == 0


def test_audit_metadata_is_privacy_minimized_and_matches_returned_filter(admin_client):
    _create_completed_lead(suffix="private-search", status="pending_contact")
    admin_client.application.config["ADMIN_NOW_PROVIDER"] = lambda: FIXED_NOW

    response = _post_export(
        admin_client,
        status="pending_contact",
        branch="manufacturing",
        date_from="2026-08-01",
        date_to="2026-08-31",
        queue="followup",
        q="private-search",
    )
    audit = _db_row(
        "SELECT actor,filter_json,row_count,created_at FROM admin_export_logs"
    )
    metadata = json.loads(audit["filter_json"])

    assert response.status_code == 200
    assert metadata == {
        "created_from": "2026-08-01",
        "created_to": "2026-08-31",
        "industry_branch": "manufacturing",
        "queue": "followup",
        "search_used": True,
        "status": "pending_contact",
    }
    assert set(metadata) <= {
        "status",
        "industry_branch",
        "department",
        "created_from",
        "created_to",
        "next_followup_from",
        "next_followup_to",
        "search_used",
        "queue",
    }
    assert "private-search" not in audit["filter_json"]
    assert tuple(audit[key] for key in ("actor", "row_count", "created_at")) == (
        "test-admin",
        1,
        "2026-08-21 10:30:45",
    )


def test_corrupt_snapshot_fails_generically_without_partial_csv_or_audit(admin_client):
    _, assessment_id = _create_completed_lead(suffix="corrupt")
    db = models.get_db()
    try:
        db.execute(
            "UPDATE assessments SET report_snapshot_json=? WHERE id=?",
            ('{"schema_version":"2.1","private":"marker"}', assessment_id),
        )
        db.commit()
    finally:
        db.close()

    response = _post_export(admin_client)

    assert response.status_code == 500
    assert response.mimetype == "text/html"
    assert b"marker" not in response.data
    assert not response.data.startswith(b"\xef\xbb\xbf")
    assert _db_row("SELECT COUNT(*) FROM admin_export_logs")[0] == 0


def test_audit_failure_returns_generic_503_and_no_file(admin_client, monkeypatch):
    _create_completed_lead(suffix="audit-failure")

    def fail_audit(*_args, **_kwargs):
        raise sqlite3.OperationalError("private-audit-failure-marker")

    monkeypatch.setattr(lead_repository, "record_export_audit", fail_audit)
    response = _post_export(admin_client)

    assert response.status_code == 503
    assert response.mimetype == "text/html"
    assert b"private-audit-failure-marker" not in response.data
    assert not response.data.startswith(b"\xef\xbb\xbf")


def test_export_does_not_change_lead_state_or_retention(admin_client):
    lead_id, _ = _create_completed_lead(suffix="unchanged", status="contacted")
    before = tuple(
        _db_row(
            "SELECT status,retention_expires_at,updated_at FROM leads WHERE id=?",
            (lead_id,),
        )
    )

    response = _post_export(admin_client, status="contacted")
    after = tuple(
        _db_row(
            "SELECT status,retention_expires_at,updated_at FROM leads WHERE id=?",
            (lead_id,),
        )
    )

    assert response.status_code == 200
    assert after == before
