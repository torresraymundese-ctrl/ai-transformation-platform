"""HTTP-level verification of the V2 core assessment journey.

These tests deliberately use only public and shared-admin routes.  They do not
query repositories or the database, so a passing result proves the same linked
records and Session boundaries that an operator or visitor can observe.
"""

from datetime import datetime, timezone
import uuid

from bs4 import BeautifulSoup

from conftest import TEST_ADMIN_PASSWORD, TEST_ADMIN_USERNAME
import report_pdf
from tests.assessment_flow_helpers import (
    bound_completion_payload,
    bound_preview_payload,
    ensure_test_legal_bundle,
    issue_real_config_flow,
)


PRIVACY_CONFIG = {
    "PRIVACY_PROCESSOR_NAME": "核心旅程测试处理者",
    "PRIVACY_CONTACT": "privacy@example.invalid",
    "PRIVACY_POLICY_URL": "https://example.invalid/privacy",
}


def complete_answer_payload(config):
    """Build one complete assessment solely from the published HTTP config."""
    return bound_preview_payload(config)


def complete_with_contact_and_consent(
    client,
    config,
    *,
    submission_key,
    company_name="核心旅程制造企业",
    phone="13800138000",
    consent=True,
):
    """Submit the real completion endpoint with the config's CSRF/policy data."""
    payload = bound_completion_payload(config, submission_key=submission_key)
    payload["contact"] = {
        "company_name": company_name,
        "contact_name": "核心旅程联系人",
        "phone": phone,
        "email": "journey@example.invalid",
        "wechat": "journey_wechat",
    }
    payload["consent"]["accepted"] = consent
    return client.post(
        "/api/v2/assessment/complete",
        json=payload,
        headers={"X-CSRF-Token": config["csrf_token"]},
    )


def submit_appointment(
    client,
    assessment_id,
    csrf_token,
    *,
    submission_key,
    note="核心旅程预约备注",
):
    """Submit appointment intent through the real Session-protected endpoint."""
    return client.post(
        "/api/v2/appointments",
        json={
            "assessment_id": assessment_id,
            "submission_key": submission_key,
            "preferred_date": "2026-08-25",
            "time_slot": "afternoon",
            "note": note,
        },
        headers={"X-CSRF-Token": csrf_token},
    )


def _login_admin(client):
    login_page = client.get("/admin/login")
    assert login_page.status_code == 200
    csrf_field = BeautifulSoup(login_page.data, "html.parser").select_one(
        'input[name="csrf_token"]'
    )
    assert csrf_field is not None
    login = client.post(
        "/admin/login",
        data={
            "csrf_token": csrf_field["value"],
            "username": TEST_ADMIN_USERNAME,
            "password": TEST_ADMIN_PASSWORD,
        },
    )
    assert login.status_code == 302


def _lead_row(listing, company_name):
    page = BeautifulSoup(listing.data, "html.parser")
    for row in page.select("tbody tr"):
        cells = row.find_all("td")
        if cells and cells[0].get_text(strip=True) == company_name:
            return row, cells
    return None, ()


def admin_can_see_linked_records(
    client,
    assessment_id,
    appointment_id,
    *,
    company_name="核心旅程制造企业",
    appointment_note="核心旅程预约备注",
):
    """Verify linkage through the real shared-admin lead/appointment pages."""
    _login_admin(client)
    leads = client.get("/admin/leads")
    assert leads.status_code == 200
    row, cells = _lead_row(leads, company_name)
    assert row is not None
    assert cells[6].get_text(strip=True) == "1"

    detail_link = row.select_one('a[href^="/admin/lead/"]')
    assert detail_link is not None
    detail = client.get(detail_link["href"])
    assert detail.status_code == 200
    detail_text = detail.get_data(as_text=True)
    assert f"#{assessment_id}" in detail_text
    assert company_name in detail_text

    appointments = client.get("/admin/appointments?status=pending")
    assert appointments.status_code == 200
    appointments_text = appointments.get_data(as_text=True)
    assert company_name in appointments_text
    assert appointment_note in appointments_text
    assert appointments_text.count(f'value="{appointment_id}"') == 1
    return True


def _enable_core_journey(client):
    ensure_test_legal_bundle()
    client.application.config.update(PRIVACY_CONFIG)
    client.application.config["APPOINTMENT_NOW_PROVIDER"] = lambda: datetime(
        2026, 8, 21, 2, 0, tzinfo=timezone.utc
    )


def test_user_can_assess_unlock_report_download_pdf_and_request_appointment(
    client, monkeypatch
):
    _enable_core_journey(client)
    config = issue_real_config_flow(client)

    preview = client.post(
        "/api/v2/assessment/preview",
        json=complete_answer_payload(config),
    )
    assert preview.status_code == 200
    assert set(preview.get_json()) == {"maturity", "strongest", "weakest"}

    completed = complete_with_contact_and_consent(
        client,
        config,
        submission_key=str(uuid.uuid4()),
    )
    assert completed.status_code == 200
    completion = completed.get_json()

    report = client.get(completion["report_url"])
    assert report.status_code == 200
    assert "平台建议就绪参考线" in report.get_data(as_text=True)

    monkeypatch.setattr(
        report_pdf,
        "render_pdf",
        lambda html, base_url: b"%PDF-core-journey",
    )
    pdf = client.get(completion["pdf_url"])
    assert pdf.status_code == 200
    assert pdf.mimetype == "application/pdf"
    assert pdf.data.startswith(b"%PDF")

    appointment = submit_appointment(
        client,
        completion["assessment_id"],
        config["csrf_token"],
        submission_key=str(uuid.uuid4()),
    )
    assert appointment.status_code == 200
    assert appointment.get_json()["status"] == "pending"
    assert admin_can_see_linked_records(
        client,
        completion["assessment_id"],
        appointment.get_json()["appointment_id"],
    )


def test_session_consent_and_idempotency_boundaries_are_visible_over_http(client):
    _enable_core_journey(client)
    config = issue_real_config_flow(client)
    completion_key = str(uuid.uuid4())
    appointment_key = str(uuid.uuid4())
    company_name = "核心边界验证企业"
    appointment_note = "核心边界唯一预约备注"

    first = complete_with_contact_and_consent(
        client,
        config,
        submission_key=completion_key,
        company_name=company_name,
        phone="13900139000",
    )
    assert first.status_code == 200
    replay = complete_with_contact_and_consent(
        client,
        config,
        submission_key=completion_key,
        company_name=company_name,
        phone="13900139000",
    )
    assert replay.status_code == 200
    assert replay.get_json() == first.get_json()

    completion = first.get_json()
    other_client = client.application.test_client()
    assert other_client.get(completion["report_url"]).status_code == 404
    assert other_client.get(completion["pdf_url"]).status_code == 404

    first_appointment = submit_appointment(
        client,
        completion["assessment_id"],
        config["csrf_token"],
        submission_key=appointment_key,
        note=appointment_note,
    )
    assert first_appointment.status_code == 200
    appointment_replay = submit_appointment(
        client,
        completion["assessment_id"],
        config["csrf_token"],
        submission_key=appointment_key,
        note="重试不得覆盖原备注",
    )
    assert appointment_replay.status_code == 200
    assert appointment_replay.get_json() == first_appointment.get_json()

    invalid_company = "无同意不得写入企业"
    invalid_payload = bound_completion_payload(
        config, submission_key=str(uuid.uuid4())
    )
    invalid_payload["contact"] = {
        "company_name": invalid_company,
        "contact_name": "无同意联系人",
        "phone": "13700137000",
    }
    invalid_payload["consent"]["accepted"] = False
    rejected = client.post(
        "/api/v2/assessment/complete",
        json=invalid_payload,
        headers={"X-CSRF-Token": config["csrf_token"]},
    )
    assert rejected.status_code == 400

    _login_admin(client)
    leads = client.get("/admin/leads")
    assert leads.status_code == 200
    row, cells = _lead_row(leads, company_name)
    assert row is not None
    assert cells[6].get_text(strip=True) == "1"
    assert invalid_company not in leads.get_data(as_text=True)

    appointments = client.get("/admin/appointments")
    appointments_text = appointments.get_data(as_text=True)
    assert appointments.status_code == 200
    assert appointments_text.count(appointment_note) == 1
    assert "重试不得覆盖原备注" not in appointments_text
    assert appointments_text.count(
        f'value="{first_appointment.get_json()["appointment_id"]}"'
    ) == 1
