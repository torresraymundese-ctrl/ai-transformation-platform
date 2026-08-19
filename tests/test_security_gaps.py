import models
from bs4 import BeautifulSoup
def test_assessment_rejects_empty_payload(client):
    """An empty object must not create an unusable lead record."""
    response = client.post("/api/assessment", json={})

    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid assessment payload"}


def test_assessment_rejects_non_object_json(client):
    """A JSON array must return a client error instead of raising in the route."""
    response = client.post("/api/assessment", json=[])

    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid assessment payload"}


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
    assert b'alert("xss")' not in response.data
    assert "正文".encode("utf-8") in response.data


def test_admin_write_rejects_missing_csrf_token(admin_client):
    """An authenticated browser session must not make admin writes CSRF-vulnerable."""
    response = admin_client.post(
        "/admin/announcement/new",
        data={
            "title": "CSRF 安全测试",
            "content_html": "测试内容",
            "is_pinned": "0",
            "status": "draft",
        },
    )

    assert response.status_code in {400, 403}


def test_admin_write_accepts_matching_csrf_token(admin_client):
    """A legitimate admin form submission with the session token must still work."""
    response = admin_client.post(
        "/admin/announcement/new",
        data={
            "csrf_token": "test-csrf-token",
            "title": "合法后台提交",
            "content_html": "<p>测试内容</p>",
            "is_pinned": "0",
            "status": "draft",
        },
    )

    assert response.status_code == 302

    db = models.get_db()
    try:
        record = db.execute(
            "SELECT title FROM announcements ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        db.close()
    assert record["title"] == "合法后台提交"


def test_announcement_does_not_render_untrusted_script(client):
    """Previously stored announcement HTML must be sanitized when rendered."""
    db = models.get_db()
    try:
        db.execute(
            "INSERT INTO announcements (title, content_html, status) VALUES (?, ?, ?)",
            ("安全公告", '<img src=x onerror=alert(1)><p>公告正文</p>', "published"),
        )
        db.commit()
    finally:
        db.close()

    response = client.get("/insights")

    assert response.status_code == 200
    assert b"alert(1)" not in response.data
    assert "公告正文".encode("utf-8") in response.data


def test_admin_scrape_control_submits_csrf_token(admin_client):
    """The article-list scrape action must supply the current session CSRF token."""
    response = admin_client.get("/admin/articles")

    assert response.status_code == 200
    assert b"X-CSRF-Token" in response.data
    assert b"test-csrf-token" in response.data


def test_admin_post_forms_render_matching_csrf_tokens(admin_client):
    """Every rendered admin POST form must carry the session CSRF token."""
    for path in (
        "/admin/article/new",
        "/admin/case/new",
        "/admin/announcement/new",
        "/admin/assets/code/new",
        "/admin/assets/departments/new",
        "/admin/assets/unit-a/new",
        "/admin/assets/unit-b/new",
    ):
        response = admin_client.get(path)
        assert response.status_code == 200
        forms = BeautifulSoup(response.data, "html.parser").select(
            'form[method="POST"]'
        )
        assert forms
        for form in forms:
            token = form.select_one('input[name="csrf_token"]')
            assert token is not None
            assert token["value"] == "test-csrf-token"
