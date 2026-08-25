import json

import pytest

import models


PUBLIC_PATHS = [
    "/",
    "/health",
    "/service-packages",
    "/cases",
    "/assessment",
    "/insights",
    "/about",
    "/static/logo.png",
    "/static/qr.png",
]

ADMIN_PATHS = [
    "/admin",
    "/admin/resources",
    "/admin/cases",
    "/admin/assessments",
    "/admin/announcements",
    "/admin/assets",
    "/admin/assets/codes",
    "/admin/assets/departments",
    "/admin/assets/unit-a",
    "/admin/assets/unit-b",
    "/admin/assets/labels",
]


@pytest.mark.parametrize("path", PUBLIC_PATHS)
def test_public_entry_point_is_available(client, path):
    """Catch a broken public route, template, seed query, or static asset."""
    response = client.get(path)

    assert response.status_code == 200


def test_health_endpoint_returns_expected_contract(client):
    """Catch changes that would make infrastructure health checks unreliable."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_shared_home_navigation_and_footer_stay_on_the_task7_baseline(client):
    response = client.get("/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert html.count('href="/services"') == 9
    assert 'href="/service-packages"' not in html


def test_admin_redirects_unauthenticated_requests_to_login(client):
    """Catch accidental removal of the session-backed admin access boundary."""
    response = client.get("/admin")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin/login?next=/admin")


@pytest.mark.parametrize("path", ADMIN_PATHS)
def test_authenticated_admin_entry_point_is_available(admin_client, path):
    """Catch a broken admin route, template, or asset-management query."""
    response = admin_client.get(path)

    assert response.status_code == 200


def test_assessment_submission_persists_the_current_contract(client):
    """Catch loss or corruption of the existing assessment-to-database flow."""
    payload = {
        "company": "本地测试企业",
        "email": "baseline@example.invalid",
        "scores": {"strategy": 60, "data": 55, "technology": 50},
        "result": "starter",
    }

    response = client.post("/api/assessment", json=payload)

    assert response.status_code == 200
    assert response.get_json() == {"success": True}

    db = models.get_db()
    try:
        record = db.execute(
            "SELECT company_name, contact_email, scores, result "
            "FROM assessments ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        db.close()

    assert record["company_name"] == "本地测试企业"
    assert record["contact_email"] == "baseline@example.invalid"
    assert json.loads(record["scores"]) == payload["scores"]
    assert record["result"] == "starter"
