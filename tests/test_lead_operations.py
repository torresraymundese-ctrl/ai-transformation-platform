import json
import re
from datetime import datetime, timedelta

import pytest
from bs4 import BeautifulSoup

import lead_repository
import manage
import models


FIXED_NOW = datetime(2026, 8, 21, 10, 30)
ADMIN_PRIVATE_HEADERS = {
    "Cache-Control": "private, no-store",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _assert_admin_private(response):
    assert {
        key: response.headers.get(key) for key in ADMIN_PRIVATE_HEADERS
    } == ADMIN_PRIVATE_HEADERS
    assert b'data-admin-shell="true"' in response.data
    assert b"data-analytics-endpoint" not in response.data
    assert b"/api/v2/events" not in response.data
    assert b"/static/js/app.js" not in response.data


def _insert_lead(
    *,
    status="new",
    branch="manufacturing",
    created_at="2026-08-10 09:00:00",
    retention_expires_at="2027-08-10 09:00:00",
    suffix="one",
    with_followup=False,
    with_appointment=False,
):
    db = models.get_db()
    try:
        lead_id = db.execute(
            "INSERT INTO leads "
            "(company_name,contact_name,phone_normalized,email,wechat,status,"
            "owner_text,source,next_followup_at,last_effective_followup_at,"
            "retention_expires_at,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"{suffix}企业",
                f"{suffix}联系人",
                f"138{lead_id_digits(suffix)}",
                f"{suffix}@example.invalid",
                f"wx_{suffix}",
                status,
                "共享负责人",
                "website_assessment",
                None,
                None,
                None if status == "won" else retention_expires_at,
                created_at,
                created_at,
            ),
        ).lastrowid
        version_id = db.execute(
            "SELECT id FROM assessment_versions WHERE status='published'"
        ).fetchone()[0]
        assessment_id = db.execute(
            "INSERT INTO assessments "
            "(submission_key,lead_id,rule_version_id,branch_code,subbranch_code,"
            "department_code,company_size_code,answers_json,"
            "dimension_scores_json,overall_score,maturity_code,"
            "report_snapshot_json,attribution_json,completed_at,company_name,"
            "contact_email) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"00000000-0000-4000-8000-{lead_id:012d}",
                lead_id,
                version_id,
                branch,
                "discrete_manufacturing"
                if branch == "manufacturing"
                else "chain_retail",
                "operations",
                "size_20_99",
                "{}",
                json.dumps({"business_value": 82.5}),
                82.5,
                "scale",
                json.dumps(
                    {"summary": f"{suffix}保留报告"}, ensure_ascii=False
                ),
                "{}",
                created_at,
                f"{suffix}旧企业副本",
                f"legacy-{suffix}@example.invalid",
            ),
        ).lastrowid
        db.execute(
            "INSERT INTO analytics_events "
            "(event_name,assessment_id,analytics_id_hash,branch_code,metadata_json) "
            "VALUES (?,?,?,?,?)",
            ("report_viewed", assessment_id, "a" * 64, branch, "{}"),
        )
        if with_followup:
            db.execute(
                "INSERT INTO lead_followups "
                "(lead_id,note,next_followup_at,effective_at,actor_text) "
                "VALUES (?,?,?,?,?)",
                (
                    lead_id,
                    f"{suffix}私密跟进备注",
                    "2026-08-25 10:00:00",
                    "2026-08-20 10:00:00",
                    "test-admin",
                ),
            )
        if with_appointment:
            db.execute(
                "INSERT INTO appointments "
                "(assessment_id,lead_id,submission_key,preferred_date,time_slot,note) "
                "VALUES (?,?,?,?,?,?)",
                (
                    assessment_id,
                    lead_id,
                    f"10000000-0000-4000-8000-{lead_id:012d}",
                    "2026-08-28",
                    "morning",
                    f"{suffix}预约私密备注",
                ),
            )
        db.commit()
        return lead_id, assessment_id
    finally:
        db.close()


def lead_id_digits(suffix):
    value = sum(ord(character) for character in suffix) % 100_000_000
    return f"{value:08d}"


def _row(statement, parameters=()):
    db = models.get_db()
    try:
        return db.execute(statement, parameters).fetchone()
    finally:
        db.close()


def _rows(statement, parameters=()):
    db = models.get_db()
    try:
        return db.execute(statement, parameters).fetchall()
    finally:
        db.close()


def _post(admin_client, path, data):
    return admin_client.post(
        path,
        data={"csrf_token": "test-csrf-token", **data},
    )


def _create_request(admin_client, lead_id, request_type="access"):
    response = _post(
        admin_client,
        "/admin/data-requests",
        {
            "action": "create",
            "lead_id": str(lead_id),
            "request_type": request_type,
            "channel": "phone",
            "requested_at": "2026-08-20T14:30",
            "verification_confirmed": "yes",
        },
    )
    assert response.status_code == 302
    return _row(
        "SELECT id FROM data_subject_requests ORDER BY id DESC LIMIT 1"
    )["id"]


def _move_request_to_verifying(admin_client, request_id):
    response = _post(
        admin_client,
        "/admin/data-requests",
        {
            "action": "transition",
            "request_id": str(request_id),
            "new_status": "verifying",
        },
    )
    assert response.status_code == 302


@pytest.mark.parametrize(
    "path",
    (
        "/admin/leads",
        "/admin/lead/1",
        "/admin/appointments",
        "/admin/data-requests",
        "/admin/not-a-route",
    ),
)
def test_anonymous_admin_surfaces_redirect_without_public_analytics(client, path):
    response = client.get(path)

    assert response.status_code == 302
    assert "/admin/login" in response.headers["Location"]
    assert {
        key: response.headers.get(key) for key in ADMIN_PRIVATE_HEADERS
    } == ADMIN_PRIVATE_HEADERS
    assert b"data-analytics" not in response.data


def test_login_and_authenticated_admin_errors_use_private_admin_shell(
    client, admin_client
):
    anonymous_client = client.application.test_client()
    login = anonymous_client.get("/admin/login")
    assert login.status_code == 200
    _assert_admin_private(login)

    missing = admin_client.get("/admin/not-a-route")

    assert missing.status_code == 404
    _assert_admin_private(missing)
    assert "页面未找到" in missing.get_data(as_text=True)
    assert "返回后台" in missing.get_data(as_text=True)


def test_admin_login_rate_limit_error_uses_private_admin_shell(client):
    client.application.config.update(LOGIN_RATE_LIMIT=1, LOGIN_RATE_WINDOW=900)
    login = client.get("/admin/login")
    token = BeautifulSoup(login.data, "html.parser").select_one(
        'input[name="csrf_token"]'
    )["value"]
    payload = {
        "csrf_token": token,
        "username": "not-the-admin",
        "password": "wrong",
    }

    assert client.post("/admin/login", data=payload).status_code == 401
    limited = client.post("/admin/login", data=payload)

    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "900"
    _assert_admin_private(limited)
    assert "请求过于频繁" in limited.get_data(as_text=True)


def test_authenticated_admin_500_is_private_and_does_not_expose_error(
    admin_client, monkeypatch, caplog
):
    def fail_list(**_filters):
        raise RuntimeError("private-admin-failure-marker")

    monkeypatch.setattr(lead_repository, "list_leads", fail_list, raising=False)

    response = admin_client.get("/admin/leads")

    assert response.status_code == 500
    _assert_admin_private(response)
    assert b"private-admin-failure-marker" not in response.data
    assert "private-admin-failure-marker" not in caplog.text


def test_admin_can_filter_leads_and_view_contact_assessment_and_report(admin_client):
    wanted_id, _ = _insert_lead(
        status="contacted",
        branch="manufacturing",
        created_at="2026-08-10 09:00:00",
        suffix="wanted",
    )
    _insert_lead(
        status="contacted",
        branch="retail",
        created_at="2026-08-10 09:00:00",
        suffix="retail",
    )
    _insert_lead(
        status="new",
        branch="manufacturing",
        created_at="2026-08-10 09:00:00",
        suffix="newlead",
    )
    _insert_lead(
        status="contacted",
        branch="manufacturing",
        created_at="2026-07-01 09:00:00",
        suffix="oldlead",
    )

    listing = admin_client.get(
        "/admin/leads?status=contacted&branch=manufacturing&"
        "date_from=2026-08-01&date_to=2026-08-31"
    )

    assert listing.status_code == 200
    _assert_admin_private(listing)
    text = listing.get_data(as_text=True)
    assert "wanted联系人" in text
    assert "retail联系人" not in text
    assert "newlead联系人" not in text
    assert "oldlead联系人" not in text

    detail = admin_client.get(f"/admin/lead/{wanted_id}")

    assert detail.status_code == 200
    _assert_admin_private(detail)
    detail_text = detail.get_data(as_text=True)
    assert "wanted企业" in detail_text
    assert "wanted联系人" in detail_text
    assert "wanted@example.invalid" in detail_text
    assert "82.5" in detail_text
    assert "scale" in detail_text
    assert "wanted保留报告" in detail_text


def test_lead_filter_validation_fails_safely_in_admin_shell(admin_client):
    response = admin_client.get(
        "/admin/leads?status=won&branch=not-real&date_from=2026-99-99"
    )

    assert response.status_code == 400
    _assert_admin_private(response)
    assert b"not-real" not in response.data


def test_lead_posts_require_csrf_and_each_success_is_audited(admin_client):
    lead_id, _ = _insert_lead(status="new", suffix="audit")

    rejected = admin_client.post(
        f"/admin/lead/{lead_id}",
        data={"action": "owner", "owner_text": "新负责人"},
    )
    assert rejected.status_code == 403
    assert _row("SELECT owner_text FROM leads WHERE id=?", (lead_id,))[0] == (
        "共享负责人"
    )

    owner = _post(
        admin_client,
        f"/admin/lead/{lead_id}",
        {"action": "owner", "owner_text": "新负责人"},
    )
    status = _post(
        admin_client,
        f"/admin/lead/{lead_id}",
        {"action": "status", "new_status": "pending_contact"},
    )

    assert owner.status_code == status.status_code == 302
    lead = _row("SELECT owner_text,status FROM leads WHERE id=?", (lead_id,))
    assert dict(lead) == {
        "owner_text": "新负责人",
        "status": "pending_contact",
    }
    audits = _rows(
        "SELECT action,status_code FROM admin_audit_logs "
        "WHERE action='admin_lead_detail' ORDER BY id"
    )
    assert [tuple(row) for row in audits] == [
        ("admin_lead_detail", 403),
        ("admin_lead_detail", 302),
        ("admin_lead_detail", 302),
    ]


def test_effective_followup_refreshes_retention_and_stores_next_time(admin_client):
    lead_id, _ = _insert_lead(status="contacted", suffix="followup")
    admin_client.application.config["ADMIN_NOW_PROVIDER"] = lambda: FIXED_NOW

    response = _post(
        admin_client,
        f"/admin/lead/{lead_id}",
        {
            "action": "followup",
            "followup_note": "已完成需求沟通",
            "next_followup_at": "2026-08-30T09:15",
        },
    )

    assert response.status_code == 302
    lead = _row(
        "SELECT next_followup_at,last_effective_followup_at,retention_expires_at "
        "FROM leads WHERE id=?",
        (lead_id,),
    )
    assert dict(lead) == {
        "next_followup_at": "2026-08-30 09:15:00",
        "last_effective_followup_at": "2026-08-21 10:30:00",
        "retention_expires_at": "2027-08-21 10:30:00",
    }
    followup = _row(
        "SELECT note,effective_at,actor_text FROM lead_followups WHERE lead_id=?",
        (lead_id,),
    )
    assert dict(followup) == {
        "note": "已完成需求沟通",
        "effective_at": "2026-08-21 10:30:00",
        "actor_text": "test-admin",
    }


def test_won_is_terminal_but_not_progressing_can_reopen(admin_client):
    won_id, _ = _insert_lead(status="proposal", suffix="wonlead")
    won = _post(
        admin_client,
        f"/admin/lead/{won_id}",
        {"action": "status", "new_status": "won"},
    )
    assert won.status_code == 302
    assert tuple(
        _row(
            "SELECT status,retention_expires_at FROM leads WHERE id=?", (won_id,)
        )
    ) == ("won", None)

    terminal = _post(
        admin_client,
        f"/admin/lead/{won_id}",
        {"action": "status", "new_status": "pending_contact"},
    )
    assert terminal.status_code == 409
    _assert_admin_private(terminal)
    assert _row("SELECT status FROM leads WHERE id=?", (won_id,))[0] == "won"

    reopen_id, _ = _insert_lead(status="not_progressing", suffix="reopen")
    reopened = _post(
        admin_client,
        f"/admin/lead/{reopen_id}",
        {"action": "status", "new_status": "pending_contact"},
    )
    assert reopened.status_code == 302
    assert _row("SELECT status FROM leads WHERE id=?", (reopen_id,))[0] == (
        "pending_contact"
    )


def test_admin_can_confirm_and_cancel_pending_appointments(admin_client):
    first_lead, _ = _insert_lead(with_appointment=True, suffix="confirm")
    second_lead, _ = _insert_lead(with_appointment=True, suffix="cancel")
    appointments = _rows(
        "SELECT id,lead_id FROM appointments ORDER BY id"
    )
    first_id = next(row["id"] for row in appointments if row["lead_id"] == first_lead)
    second_id = next(
        row["id"] for row in appointments if row["lead_id"] == second_lead
    )

    listing = admin_client.get("/admin/appointments?status=pending")
    assert listing.status_code == 200
    _assert_admin_private(listing)
    assert "confirm企业" in listing.get_data(as_text=True)

    confirmed = _post(
        admin_client,
        "/admin/appointments",
        {
            "action": "transition",
            "appointment_id": str(first_id),
            "new_status": "confirmed",
        },
    )
    cancelled = _post(
        admin_client,
        "/admin/appointments",
        {
            "action": "transition",
            "appointment_id": str(second_id),
            "new_status": "cancelled",
        },
    )

    assert confirmed.status_code == cancelled.status_code == 302
    states = _rows(
        "SELECT status,confirmed_at,cancelled_at FROM appointments ORDER BY id"
    )
    assert states[0]["status"] == "confirmed"
    assert states[0]["confirmed_at"] is not None
    assert states[1]["status"] == "cancelled"
    assert states[1]["cancelled_at"] is not None


def test_offline_privacy_request_requires_verification_and_duplicates_no_contacts(
    admin_client
):
    lead_id, _ = _insert_lead(suffix="privacy")
    unverified = _post(
        admin_client,
        "/admin/data-requests",
        {
            "action": "create",
            "lead_id": str(lead_id),
            "request_type": "access",
            "channel": "email",
            "requested_at": "2026-08-20T14:30",
        },
    )
    assert unverified.status_code == 400
    assert _row("SELECT COUNT(*) FROM data_subject_requests")[0] == 0

    request_id = _create_request(admin_client, lead_id)
    request_row = _row(
        "SELECT * FROM data_subject_requests WHERE id=?", (request_id,)
    )
    assert request_row["lead_id"] == lead_id
    assert request_row["request_type"] == "access"
    assert request_row["status"] == "received"
    assert request_row["channel"] == "phone"
    assert request_row["requested_at"] == "2026-08-20 14:30:00"
    assert re.fullmatch(r"[0-9a-f]{64}", request_row["identity_hash"])

    columns = {
        row[1]
        for row in _rows("PRAGMA table_info(data_subject_requests)")
    }
    assert not {
        "company_name",
        "contact_name",
        "phone",
        "phone_normalized",
        "email",
        "wechat",
    } & columns


def test_offline_privacy_request_cannot_target_an_already_anonymized_lead(
    admin_client
):
    lead_id, _ = _insert_lead(suffix="alreadyanonymous")
    db = models.get_db()
    try:
        db.execute(
            "UPDATE leads SET company_name='已匿名化',contact_name='已匿名化',"
            "phone_normalized=NULL,email=NULL,wechat=NULL,anonymized_at=? WHERE id=?",
            ("2026-08-19 10:00:00", lead_id),
        )
        db.commit()
    finally:
        db.close()

    response = _post(
        admin_client,
        "/admin/data-requests",
        {
            "action": "create",
            "lead_id": str(lead_id),
            "request_type": "access",
            "channel": "phone",
            "requested_at": "2026-08-20T14:30",
            "verification_confirmed": "yes",
        },
    )

    assert response.status_code == 409
    assert _row("SELECT COUNT(*) FROM data_subject_requests")[0] == 0
    page = BeautifulSoup(
        admin_client.get("/admin/data-requests").data, "html.parser"
    )
    assert page.select_one(f'form select[name="lead_id"] option[value="{lead_id}"]') is None


def test_access_request_completion_requires_sanitized_non_pii_result(admin_client):
    lead_id, _ = _insert_lead(suffix="access")
    request_id = _create_request(admin_client, lead_id, "access")
    _move_request_to_verifying(admin_client, request_id)

    missing_note = _post(
        admin_client,
        "/admin/data-requests",
        {
            "action": "complete",
            "request_id": str(request_id),
            "resolution_note": "",
        },
    )
    assert missing_note.status_code == 400

    completed = _post(
        admin_client,
        "/admin/data-requests",
        {
            "action": "complete",
            "request_id": str(request_id),
            "resolution_note": (
                "<b>已向申请人当面提供数据副本</b>"
                "<script>private-note-marker</script>"
            ),
        },
    )

    assert completed.status_code == 302
    request_row = _row(
        "SELECT status,resolution_note,completed_at FROM data_subject_requests "
        "WHERE id=?",
        (request_id,),
    )
    assert request_row["status"] == "completed"
    assert request_row["resolution_note"] == "已向申请人当面提供数据副本"
    assert request_row["completed_at"] is not None
    assert _row("SELECT anonymized_at FROM leads WHERE id=?", (lead_id,))[0] is None


def test_privacy_request_can_be_rejected_only_after_verification(admin_client):
    lead_id, _ = _insert_lead(suffix="rejected")
    request_id = _create_request(admin_client, lead_id, "correction")
    _move_request_to_verifying(admin_client, request_id)

    rejected = _post(
        admin_client,
        "/admin/data-requests",
        {
            "action": "transition",
            "request_id": str(request_id),
            "new_status": "rejected",
            "resolution_note": "身份核验未通过，已告知补充材料要求",
        },
    )

    assert rejected.status_code == 302
    request_row = _row(
        "SELECT status,resolution_note,completed_at FROM data_subject_requests "
        "WHERE id=?",
        (request_id,),
    )
    assert request_row["status"] == "rejected"
    assert request_row["resolution_note"] == (
        "身份核验未通过，已告知补充材料要求"
    )
    assert request_row["completed_at"] is not None
    assert _row("SELECT anonymized_at FROM leads WHERE id=?", (lead_id,))[0] is None


def test_privacy_resolution_note_is_limited_to_one_thousand_characters(
    admin_client
):
    lead_id, _ = _insert_lead(suffix="longnote")
    request_id = _create_request(admin_client, lead_id, "access")
    _move_request_to_verifying(admin_client, request_id)

    response = _post(
        admin_client,
        "/admin/data-requests",
        {
            "action": "complete",
            "request_id": str(request_id),
            "resolution_note": "完" * 1001,
        },
    )

    assert response.status_code == 400
    assert tuple(
        _row(
            "SELECT status,resolution_note FROM data_subject_requests WHERE id=?",
            (request_id,),
        )
    ) == ("verifying", None)


@pytest.mark.parametrize(
    "private_note",
    (
        "已发送至138-0013-8000",
        "已发送至 user @ example.com",
        "已发送至١٣٨٠٠١٣٨٠٠٠",
    ),
)
def test_privacy_resolution_note_rejects_contact_values(
    admin_client, private_note
):
    lead_id, _ = _insert_lead(suffix=f"pii{len(private_note)}")
    request_id = _create_request(admin_client, lead_id, "correction")
    _move_request_to_verifying(admin_client, request_id)

    response = _post(
        admin_client,
        "/admin/data-requests",
        {
            "action": "complete",
            "request_id": str(request_id),
            "resolution_note": private_note,
        },
    )

    assert response.status_code == 400
    assert private_note.encode("utf-8") not in response.data
    row = _row(
        "SELECT status,resolution_note FROM data_subject_requests WHERE id=?",
        (request_id,),
    )
    assert tuple(row) == ("verifying", None)


@pytest.mark.parametrize(
    ("value_kind", "note_template"),
    (
        ("company_name", "已向{value}确认处理结果"),
        ("wechat", "已通过微信 {value} 完成核验"),
        ("landline", "已通过座机 010-12345678 完成核验"),
        ("landline", "身份核验结果已电话告知，号码 12345678"),
        ("landline", "身份核验结果已电话告知，号码 +44 20 7946 0958"),
        ("landline", "身份核验使用 wechat_secret88 完成"),
        ("landline", "身份核验使用 wxid_private88 完成"),
    ),
)
def test_privacy_completion_rejects_target_identifiers_and_phone_shapes_atomically(
    admin_client, value_kind, note_template
):
    lead_id, _ = _insert_lead(
        suffix=f"private-{value_kind}", with_followup=True
    )
    lead_before = _row(
        "SELECT company_name,contact_name,phone_normalized,email,wechat,"
        "anonymized_at FROM leads WHERE id=?",
        (lead_id,),
    )
    value = lead_before[value_kind] if value_kind != "landline" else ""
    request_id = _create_request(admin_client, lead_id, "deletion")
    _move_request_to_verifying(admin_client, request_id)

    response = _post(
        admin_client,
        "/admin/data-requests",
        {
            "action": "complete",
            "request_id": str(request_id),
            "resolution_note": note_template.format(value=value),
            "confirm_anonymization": "yes",
        },
    )

    assert response.status_code == 400
    assert tuple(
        _row(
            "SELECT status,resolution_note FROM data_subject_requests WHERE id=?",
            (request_id,),
        )
    ) == ("verifying", None)
    assert tuple(
        _row(
            "SELECT company_name,contact_name,phone_normalized,email,wechat,"
            "anonymized_at FROM leads WHERE id=?",
            (lead_id,),
        )
    ) == tuple(lead_before)
    assert _row(
        "SELECT COUNT(*) FROM lead_followups WHERE lead_id=?", (lead_id,)
    )[0] == 1


def test_privacy_rejection_rejects_target_contact_name_and_rolls_back(admin_client):
    lead_id, _ = _insert_lead(suffix="rejection-private")
    contact_name = _row(
        "SELECT contact_name FROM leads WHERE id=?", (lead_id,)
    )[0]
    request_id = _create_request(admin_client, lead_id, "access")
    _move_request_to_verifying(admin_client, request_id)

    response = _post(
        admin_client,
        "/admin/data-requests",
        {
            "action": "transition",
            "request_id": str(request_id),
            "new_status": "rejected",
            "resolution_note": f"无法核验联系人 {contact_name}",
        },
    )

    assert response.status_code == 400
    assert tuple(
        _row(
            "SELECT status,resolution_note,completed_at "
            "FROM data_subject_requests WHERE id=?",
            (request_id,),
        )
    ) == ("verifying", None, None)


@pytest.mark.parametrize(
    "private_landline",
    ("010-1234-5678", "1234-5678", "1234 5678"),
)
@pytest.mark.parametrize("workflow", ("completion", "rejection"))
def test_privacy_note_rejects_separator_formatted_landlines_and_rolls_back(
    admin_client, caplog, private_landline, workflow
):
    lead_id, _ = _insert_lead(
        suffix=f"formatted-{workflow}-{len(private_landline)}", with_followup=True
    )
    lead_before = tuple(
        _row(
            "SELECT company_name,contact_name,phone_normalized,email,wechat,"
            "anonymized_at FROM leads WHERE id=?",
            (lead_id,),
        )
    )
    request_id = _create_request(admin_client, lead_id, "deletion")
    _move_request_to_verifying(admin_client, request_id)
    note = f"已通过号码 {private_landline} 完成核验"
    if workflow == "completion":
        form = {
            "action": "complete",
            "request_id": str(request_id),
            "resolution_note": note,
            "confirm_anonymization": "yes",
        }
    else:
        form = {
            "action": "transition",
            "request_id": str(request_id),
            "new_status": "rejected",
            "resolution_note": note,
        }

    response = _post(admin_client, "/admin/data-requests", form)

    assert response.status_code == 400
    assert note.encode("utf-8") not in response.data
    assert note not in caplog.text
    assert tuple(
        _row(
            "SELECT status,resolution_note,completed_at "
            "FROM data_subject_requests WHERE id=?",
            (request_id,),
        )
    ) == ("verifying", None, None)
    assert tuple(
        _row(
            "SELECT company_name,contact_name,phone_normalized,email,wechat,"
            "anonymized_at FROM leads WHERE id=?",
            (lead_id,),
        )
    ) == lead_before
    assert _row(
        "SELECT COUNT(*) FROM lead_followups WHERE lead_id=?", (lead_id,)
    )[0] == 1


def test_privacy_completion_rejects_embedded_one_character_target_name(
    admin_client,
):
    lead_id, _ = _insert_lead(suffix="one-character-name", with_followup=True)
    db = models.get_db()
    try:
        db.execute("UPDATE leads SET contact_name='王' WHERE id=?", (lead_id,))
        db.commit()
    finally:
        db.close()
    request_id = _create_request(admin_client, lead_id, "withdrawal")
    _move_request_to_verifying(admin_client, request_id)

    response = _post(
        admin_client,
        "/admin/data-requests",
        {
            "action": "complete",
            "request_id": str(request_id),
            "resolution_note": "已由王完成身份核验",
            "confirm_anonymization": "yes",
        },
    )

    assert response.status_code == 400
    assert tuple(
        _row(
            "SELECT status,resolution_note FROM data_subject_requests WHERE id=?",
            (request_id,),
        )
    ) == ("verifying", None)
    assert tuple(
        _row(
            "SELECT contact_name,anonymized_at FROM leads WHERE id=?", (lead_id,)
        )
    ) == ("王", None)
    assert _row(
        "SELECT COUNT(*) FROM lead_followups WHERE lead_id=?", (lead_id,)
    )[0] == 1


@pytest.mark.parametrize(
    ("request_type", "reason_code"),
    (("withdrawal", "consent_withdrawn"), ("deletion", "deletion_requested")),
)
def test_verified_withdrawal_or_deletion_anonymizes_atomically_but_keeps_metrics(
    admin_client, request_type, reason_code, caplog
):
    lead_id, assessment_id = _insert_lead(
        status="won",
        suffix=request_type,
        with_followup=True,
        with_appointment=True,
    )
    private_values = tuple(
        _row(
            "SELECT company_name,contact_name,phone_normalized,email,wechat "
            "FROM leads WHERE id=?",
            (lead_id,),
        )
    )
    request_id = _create_request(admin_client, lead_id, request_type)
    _move_request_to_verifying(admin_client, request_id)
    hostile_landline = "010-1234-5678"
    hostile_attribution = json.dumps(
        {
            "utm_source": private_values[0],
            "utm_medium": private_values[1],
            "utm_campaign": f"{private_values[4]} {hostile_landline}",
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    hostile_source = f"{private_values[0]} {hostile_landline}"
    db = models.get_db()
    try:
        version_id = db.execute(
            "SELECT rule_version_id FROM assessments WHERE id=?", (assessment_id,)
        ).fetchone()[0]
        db.execute(
            "UPDATE leads SET source=? WHERE id=?", (hostile_source, lead_id)
        )
        db.execute(
            "UPDATE assessments SET attribution_json=? WHERE id=?",
            (hostile_attribution, assessment_id),
        )
        db.execute(
            "INSERT INTO roi_estimates "
            "(assessment_id,rule_version_id,recommended_scenarios_json,"
            "estimate_snapshot_json,created_at) VALUES (?,?,?,?,?)",
            (
                assessment_id,
                version_id,
                '["retained_scenario"]',
                '{"midpoint":{"annual_savings":12345}}',
                "2026-08-10 09:00:00",
            ),
        )
        db.execute(
            "INSERT INTO lead_consents "
            "(lead_id,policy_version,consented_at,source,identity_hash) "
            "VALUES (?,?,?,?,?)",
            (
                lead_id,
                "2026-08-19",
                "2026-08-20 09:00:00",
                "website_assessment",
                "b" * 32,
            ),
        )
        db.execute(
            "INSERT INTO lead_status_history "
            "(lead_id,previous_status,new_status,note,actor_text) "
            "VALUES (?,?,?,?,?)",
            (
                lead_id,
                "proposal",
                "won",
                f"{request_type}旧私密状态备注",
                "test-admin",
            ),
        )
        db.commit()
    finally:
        db.close()
    assessment_before = tuple(
        _row(
            "SELECT answers_json,dimension_scores_json,overall_score,"
            "report_snapshot_json FROM assessments WHERE id=?",
            (assessment_id,),
        )
    )
    roi_before = tuple(
        _row(
            "SELECT recommended_scenarios_json,estimate_snapshot_json "
            "FROM roi_estimates WHERE assessment_id=?",
            (assessment_id,),
        )
    )

    unconfirmed = _post(
        admin_client,
        "/admin/data-requests",
        {
            "action": "complete",
            "request_id": str(request_id),
            "resolution_note": "已完成身份核验",
        },
    )
    assert unconfirmed.status_code == 409
    assert _row("SELECT anonymized_at FROM leads WHERE id=?", (lead_id,))[0] is None

    completed = _post(
        admin_client,
        "/admin/data-requests",
        {
            "action": "complete",
            "request_id": str(request_id),
            "resolution_note": "已完成身份核验并执行请求",
            "confirm_anonymization": "yes",
        },
    )

    assert completed.status_code == 302
    lead = _row(
        "SELECT company_name,contact_name,phone_normalized,email,wechat,source,"
        "anonymized_at,status FROM leads WHERE id=?",
        (lead_id,),
    )
    assert dict(lead) == {
        "company_name": "已匿名化",
        "contact_name": "已匿名化",
        "phone_normalized": None,
        "email": None,
        "wechat": None,
        "source": None,
        "anonymized_at": lead["anonymized_at"],
        "status": "won",
    }
    assert lead["anonymized_at"] is not None
    assert _row(
        "SELECT COUNT(*) FROM lead_followups WHERE lead_id=?", (lead_id,)
    )[0] == 0
    assert _row(
        "SELECT COUNT(*) FROM lead_consents WHERE lead_id=?", (lead_id,)
    )[0] == 0
    assert _row(
        "SELECT note FROM appointments WHERE lead_id=?", (lead_id,)
    )[0] is None
    assessment = _row(
        "SELECT company_name,contact_email,attribution_json,report_snapshot_json "
        "FROM assessments "
        "WHERE id=?",
        (assessment_id,),
    )
    assert assessment["company_name"] is None
    assert assessment["contact_email"] is None
    assert assessment["attribution_json"] == "{}"
    assert f"{request_type}保留报告" in assessment["report_snapshot_json"]
    assert tuple(
        _row(
            "SELECT answers_json,dimension_scores_json,overall_score,"
            "report_snapshot_json FROM assessments WHERE id=?",
            (assessment_id,),
        )
    ) == assessment_before
    assert tuple(
        _row(
            "SELECT recommended_scenarios_json,estimate_snapshot_json "
            "FROM roi_estimates WHERE assessment_id=?",
            (assessment_id,),
        )
    ) == roi_before
    assert _row(
        "SELECT COUNT(*) FROM analytics_events WHERE assessment_id=?",
        (assessment_id,),
    )[0] == 1
    request_row = _row(
        "SELECT status,completed_at,resolution_note "
        "FROM data_subject_requests WHERE id=?",
        (request_id,),
    )
    assert request_row["status"] == "completed"
    assert request_row["completed_at"] is not None
    assert request_row["resolution_note"] == "已完成身份核验并执行请求"
    assert all(
        value not in request_row["resolution_note"] for value in private_values
    )
    for marker in (*private_values, hostile_landline, hostile_source):
        assert marker.encode("utf-8") not in completed.data
        assert marker not in caplog.text
    reasons = _rows(
        "SELECT note FROM lead_status_history WHERE lead_id=? AND note IS NOT NULL "
        "ORDER BY id",
        (lead_id,),
    )
    assert [row["note"] for row in reasons] == [reason_code]


def test_unauthenticated_admin_audit_never_copies_submitted_username(client):
    marker = "13800138000-private-login-marker"
    login = client.get("/admin/login")
    token = BeautifulSoup(login.data, "html.parser").select_one(
        'input[name="csrf_token"]'
    )["value"]

    response = client.post(
        "/admin/login",
        data={"csrf_token": token, "username": marker, "password": "wrong"},
    )

    assert response.status_code == 401
    assert marker.encode() not in response.data
    audit = _row(
        "SELECT actor,action,status_code FROM admin_audit_logs ORDER BY id DESC"
    )
    assert dict(audit) == {
        "actor": "anonymous",
        "action": "admin_login",
        "status_code": 401,
    }


def test_privacy_completion_rolls_back_request_and_anonymization_together(
    admin_client, monkeypatch, caplog
):
    lead_id, _ = _insert_lead(
        suffix="rollback", with_followup=True, with_appointment=True
    )
    request_id = _create_request(admin_client, lead_id, "deletion")
    _move_request_to_verifying(admin_client, request_id)
    original = lead_repository.anonymize_lead

    def fail_after_anonymization(db, target_lead_id, reason_code, **kwargs):
        original(db, target_lead_id, reason_code, **kwargs)
        raise RuntimeError("rollback-private-contact-marker")

    monkeypatch.setattr(lead_repository, "anonymize_lead", fail_after_anonymization)

    response = _post(
        admin_client,
        "/admin/data-requests",
        {
            "action": "complete",
            "request_id": str(request_id),
            "resolution_note": "已完成核验",
            "confirm_anonymization": "yes",
        },
    )

    assert response.status_code == 500
    _assert_admin_private(response)
    assert b"rollback-private-contact-marker" not in response.data
    assert "rollback-private-contact-marker" not in caplog.text
    lead = _row(
        "SELECT company_name,phone_normalized,anonymized_at FROM leads WHERE id=?",
        (lead_id,),
    )
    assert lead["company_name"] == "rollback企业"
    assert lead["phone_normalized"] is not None
    assert lead["anonymized_at"] is None
    assert _row(
        "SELECT COUNT(*) FROM lead_followups WHERE lead_id=?", (lead_id,)
    )[0] == 1
    assert _row(
        "SELECT status FROM data_subject_requests WHERE id=?", (request_id,)
    )[0] == "verifying"


def test_expired_unconverted_lead_is_anonymized_but_metrics_remain(client):
    lead_id, assessment_id = _insert_lead(
        status="not_progressing",
        retention_expires_at="2026-08-20 10:30:00",
        suffix="expired",
        with_followup=True,
        with_appointment=True,
    )
    hostile_attribution = json.dumps(
        {
            "utm_source": "expired企业",
            "utm_medium": "expired联系人",
            "utm_campaign": "wx_expired 010-1234-5678",
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    db = models.get_db()
    try:
        version_id = db.execute(
            "SELECT rule_version_id FROM assessments WHERE id=?", (assessment_id,)
        ).fetchone()[0]
        db.execute(
            "UPDATE leads SET source=? WHERE id=?",
            ("expired企业 010-1234-5678", lead_id),
        )
        db.execute(
            "UPDATE assessments SET attribution_json=? WHERE id=?",
            (hostile_attribution, assessment_id),
        )
        db.execute(
            "INSERT INTO roi_estimates "
            "(assessment_id,rule_version_id,recommended_scenarios_json,"
            "estimate_snapshot_json,created_at) VALUES (?,?,?,?,?)",
            (
                assessment_id,
                version_id,
                '["retained_scenario"]',
                '{"midpoint":{"annual_savings":12345}}',
                "2026-08-10 09:00:00",
            ),
        )
        db.commit()
    finally:
        db.close()
    assessment_before = tuple(
        _row(
            "SELECT answers_json,dimension_scores_json,overall_score,"
            "report_snapshot_json FROM assessments WHERE id=?",
            (assessment_id,),
        )
    )
    roi_before = tuple(
        _row(
            "SELECT recommended_scenarios_json,estimate_snapshot_json "
            "FROM roi_estimates WHERE assessment_id=?",
            (assessment_id,),
        )
    )

    preview_count = lead_repository.purge_expired_leads(
        now=FIXED_NOW, apply=False
    )
    assert preview_count == 1
    assert _row("SELECT anonymized_at FROM leads WHERE id=?", (lead_id,))[0] is None

    count = lead_repository.purge_expired_leads(now=FIXED_NOW, apply=True)

    assert count == 1
    lead = _row(
        "SELECT company_name,contact_name,phone_normalized,email,wechat,source,"
        "anonymized_at "
        "FROM leads WHERE id=?",
        (lead_id,),
    )
    assert lead["company_name"] == lead["contact_name"] == "已匿名化"
    assert lead["phone_normalized"] is None
    assert lead["email"] is None and lead["wechat"] is None
    assert lead["source"] is None
    assert lead["anonymized_at"] is not None
    assert _row(
        "SELECT COUNT(*) FROM lead_followups WHERE lead_id=?", (lead_id,)
    )[0] == 0
    assert _row(
        "SELECT COUNT(*) FROM assessments WHERE lead_id=?", (lead_id,)
    )[0] == 1
    assessment = _row(
        "SELECT attribution_json,answers_json,dimension_scores_json,overall_score,"
        "report_snapshot_json FROM assessments WHERE id=?",
        (assessment_id,),
    )
    assert assessment["attribution_json"] == "{}"
    assert tuple(assessment)[1:] == assessment_before
    assert tuple(
        _row(
            "SELECT recommended_scenarios_json,estimate_snapshot_json "
            "FROM roi_estimates WHERE assessment_id=?",
            (assessment_id,),
        )
    ) == roi_before
    assert _row(
        "SELECT COUNT(*) FROM analytics_events WHERE assessment_id=?",
        (assessment_id,),
    )[0] == 1
    assert _row(
        "SELECT note FROM lead_status_history WHERE lead_id=? ORDER BY id DESC",
        (lead_id,),
    )[0] == "retention_expired"


def test_won_lead_is_never_automatically_purged(client):
    lead_id, _ = _insert_lead(
        status="won",
        retention_expires_at="2020-01-01 00:00:00",
        suffix="protectedwon",
    )

    assert lead_repository.purge_expired_leads(now=FIXED_NOW, apply=True) == 0
    lead = _row(
        "SELECT company_name,anonymized_at FROM leads WHERE id=?", (lead_id,)
    )
    assert tuple(lead) == ("protectedwon企业", None)


def test_purge_cli_defaults_to_dry_run_and_prints_only_counts_and_ids(
    client, capsys
):
    lead_id, _ = _insert_lead(
        status="not_progressing",
        retention_expires_at="2020-01-01 00:00:00",
        suffix="cli-private-marker",
        with_followup=True,
    )

    assert manage.main(["purge-expired-leads"]) == 0
    dry_output = capsys.readouterr().out

    assert "mode=dry-run" in dry_output
    assert "count=1" in dry_output
    assert f"ids={lead_id}" in dry_output
    assert "cli-private-marker" not in dry_output
    assert _row("SELECT anonymized_at FROM leads WHERE id=?", (lead_id,))[0] is None

    assert manage.main(["purge-expired-leads", "--apply"]) == 0
    apply_output = capsys.readouterr().out

    assert "mode=apply" in apply_output
    assert "count=1" in apply_output
    assert f"ids={lead_id}" in apply_output
    assert "cli-private-marker" not in apply_output
    assert _row("SELECT anonymized_at FROM leads WHERE id=?", (lead_id,))[0] is not None


def test_retention_result_reports_exact_ids_selected_by_apply(client):
    lead_id, _ = _insert_lead(
        status="not_progressing",
        retention_expires_at="2026-08-21 10:30:00",
        suffix="result-api",
    )

    result = lead_repository.run_retention_purge(now=FIXED_NOW, apply=True)

    assert result.lead_ids == (lead_id,)
    assert result.count == 1
    assert _row("SELECT anonymized_at FROM leads WHERE id=?", (lead_id,))[0]


def test_purge_cli_uses_one_shanghai_clock_snapshot_at_expiry_boundary(
    client, capsys, monkeypatch
):
    lead_id, _ = _insert_lead(
        status="not_progressing",
        retention_expires_at="2026-08-21 10:30:01",
        suffix="cli-clock-boundary",
    )
    clock_values = iter(
        (
            datetime(2026, 8, 21, 10, 30, 0),
            datetime(2026, 8, 21, 10, 30, 2),
        )
    )
    clock_calls = []

    def advancing_clock():
        value = next(clock_values)
        clock_calls.append(value)
        return value

    monkeypatch.setattr(lead_repository, "current_shanghai_datetime", advancing_clock)

    assert manage.main(["purge-expired-leads", "--apply"]) == 0
    output = capsys.readouterr().out

    assert len(clock_calls) == 1
    assert "count=0" in output
    assert "ids=none" in output
    assert f"ids={lead_id}" not in output
    assert _row("SELECT anonymized_at FROM leads WHERE id=?", (lead_id,))[0] is None


def test_data_request_page_lists_workflow_without_contact_values_in_errors(
    admin_client
):
    lead_id, _ = _insert_lead(suffix="requestlist")
    request_id = _create_request(admin_client, lead_id, "correction")

    listing = admin_client.get("/admin/data-requests?status=received")

    assert listing.status_code == 200
    _assert_admin_private(listing)
    page = BeautifulSoup(listing.data, "html.parser")
    row = page.select_one(f'tr[data-request-id="{request_id}"]')
    assert row is not None
    assert "correction" in row.get_text(" ", strip=True)
    assert "received" in row.get_text(" ", strip=True)
