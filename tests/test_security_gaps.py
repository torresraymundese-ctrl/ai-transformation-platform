import pytest

import models


PHASE_2 = "Known V0.2 security gap; Phase 2 must make this test pass"


@pytest.mark.xfail(strict=True, reason=PHASE_2)
def test_assessment_rejects_empty_payload(client):
    """An empty object must not create an unusable lead record."""
    response = client.post("/api/assessment", json={})

    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid assessment payload"}


@pytest.mark.xfail(strict=True, reason=PHASE_2)
def test_assessment_rejects_non_object_json(client):
    """A JSON array must return a client error instead of raising in the route."""
    response = client.post("/api/assessment", json=[])

    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid assessment payload"}


@pytest.mark.xfail(strict=True, reason=PHASE_2)
def test_assessment_rejects_invalid_email(client):
    """An invalid contact address must not be stored as a qualified lead."""
    response = client.post(
        "/api/assessment",
        json={
            "company": "测试企业",
            "email": "not-an-email",
            "scores": {"strategy": 60},
            "result": "starter",
        },
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid assessment payload"}


@pytest.mark.xfail(strict=True, reason=PHASE_2)
def test_assessment_rejects_overlong_company_name(client):
    """Oversized strings must be bounded before they reach storage and logs."""
    response = client.post(
        "/api/assessment",
        json={
            "company": "企" * 300,
            "email": "security@example.invalid",
            "scores": {"strategy": 60},
            "result": "starter",
        },
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid assessment payload"}


@pytest.mark.xfail(strict=True, reason=PHASE_2)
def test_article_does_not_render_untrusted_script(client):
    """Stored article HTML must be sanitized before browser rendering."""
    db = models.get_db()
    try:
        cursor = db.execute(
            "INSERT INTO articles "
            "(title, source, content_html, status) VALUES (?, ?, ?, ?)",
            ("安全测试文章", "本地测试", '<script>alert("xss")</script><p>正文</p>', "published"),
        )
        article_id = cursor.lastrowid
        db.commit()
    finally:
        db.close()

    response = client.get(f"/article/{article_id}")

    assert response.status_code == 200
    assert b"<script>" not in response.data
    assert "正文".encode("utf-8") in response.data


@pytest.mark.xfail(strict=True, reason=PHASE_2)
def test_admin_write_rejects_missing_csrf_token(client, admin_headers):
    """Browser-supplied Basic Auth must not make admin writes CSRF-vulnerable."""
    response = client.post(
        "/admin/announcement/new",
        headers=admin_headers,
        data={
            "title": "CSRF 安全测试",
            "content_html": "测试内容",
            "is_pinned": "0",
            "status": "draft",
        },
    )

    assert response.status_code in {400, 403}
