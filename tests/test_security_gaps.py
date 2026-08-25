import models
from bs4 import BeautifulSoup


def _announcement_form(**overrides):
    form = {
        "csrf_token": "test-csrf-token",
        "action": "save",
        "slug": "security-announcement",
        "title": "合法后台提交",
        "summary": "固定有效期安全公告。",
        "seo_title": "合法后台提交",
        "seo_description": "固定有效期安全公告摘要。",
        "share_image_media_id": "",
        "valid_from": "2026-08-25T09:00",
        "valid_until": "2026-08-26T09:00",
        "cta_url": "",
        "blocks-0-type": "rich_text",
        "blocks-0-title": "正文",
        "blocks-0-body": "<p>测试内容</p>",
        "blocks-0-media_id": "",
    }
    form.update(overrides)
    return form


def _sourced_resource_form(**overrides):
    form = {
        "csrf_token": "test-csrf-token",
        "action": "save",
        "slug": "security-resource",
        "title": "来源检查安全资源",
        "summary": "来源检查必须携带当前会话 CSRF 令牌。",
        "seo_title": "来源检查安全资源",
        "seo_description": "来源检查安全资源摘要。",
        "share_image_media_id": "",
        "resource_type": "guide",
        "is_original": "0",
        "source_name": "安全来源",
        "source_url": "https://example.com/security-resource",
        "original_published_at": "2026-08-25T09:00",
        "copyright_notice": "经授权转载，版权归原作者所有。",
        "attachment_media_id": "",
        "blocks-0-type": "rich_text",
        "blocks-0-title": "正文",
        "blocks-0-body": "<p>测试内容</p>",
        "blocks-0-media_id": "",
    }
    form.update(overrides)
    return form


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
    form = _announcement_form(title="CSRF 安全测试")
    form.pop("csrf_token")
    response = admin_client.post(
        "/admin/announcements/new",
        data=form,
    )

    assert response.status_code in {400, 403}


def test_admin_write_accepts_matching_csrf_token(admin_client):
    """A legitimate admin form submission with the session token must still work."""
    response = admin_client.post(
        "/admin/announcements/new",
        data=_announcement_form(),
    )

    assert response.status_code == 302

    db = models.get_db()
    try:
        record = db.execute(
            "SELECT title FROM content_items WHERE entry_type='announcement' "
            "ORDER BY id DESC LIMIT 1"
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


def test_admin_source_check_control_submits_csrf_token(admin_client):
    """The reviewed-resource source check must carry the current session token."""
    created = admin_client.post(
        "/admin/resources/new", data=_sourced_resource_form()
    )
    assert created.status_code == 302

    response = admin_client.get(created.headers["Location"])

    assert response.status_code == 200
    form = BeautifulSoup(response.data, "html.parser").select_one(
        'form[action$="/source-check"]'
    )
    assert form is not None
    token = form.select_one('input[name="csrf_token"]')
    assert token is not None
    assert token["value"] == "test-csrf-token"


def test_admin_post_forms_render_matching_csrf_tokens(admin_client):
    """Every rendered admin POST form must carry the session CSRF token."""
    for path in (
        "/admin/resources/new",
        "/admin/announcements/new",
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


def test_retired_case_editor_keeps_auth_csrf_cache_and_audit_boundaries(client):
    anonymous = client.get("/admin/case/new")
    assert anonymous.status_code == 302
    assert "/admin/login" in anonymous.headers["Location"]

    with client.session_transaction() as session:
        session["admin_username"] = "test-admin"
        session["csrf_token"] = "test-csrf-token"
    retired = client.get("/admin/case/new")
    assert retired.status_code == 410
    assert retired.headers["Cache-Control"] == "private, no-store"

    with client.session_transaction() as session:
        session.pop("csrf_token")
    assert client.post("/admin/case/1").status_code == 403

    with client.session_transaction() as session:
        session["csrf_token"] = "test-csrf-token"
    attempted = client.post(
        "/admin/case/1", data={"csrf_token": "test-csrf-token"}
    )
    assert attempted.status_code == 410
    assert attempted.headers["Cache-Control"] == "private, no-store"
    db = models.get_db()
    try:
        audit = db.execute(
            "SELECT action,status_code FROM admin_audit_logs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        db.close()
    assert tuple(audit) == ("admin_case_edit", 410)
