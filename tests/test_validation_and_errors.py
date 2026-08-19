import logging

import models


def test_legacy_javascript_source_url_is_not_rendered_as_a_link(client):
    """Previously stored active-scheme URLs must not become executable links."""
    db = models.get_db()
    try:
        cursor = db.execute(
            "INSERT INTO articles (title, source, source_url, summary, status) "
            "VALUES (?,?,?,?,?)",
            ("危险外链", "安全测试", "javascript:alert(1)", "摘要", "published"),
        )
        article_id = cursor.lastrowid
        db.commit()
    finally:
        db.close()

    response = client.get(f"/article/{article_id}")

    assert response.status_code == 200
    assert b'href="javascript:' not in response.data


def test_admin_rejects_active_scheme_source_url(admin_client):
    """Article writes must accept only absolute HTTP(S) source links."""
    response = admin_client.post(
        "/admin/article/new",
        data={
            "csrf_token": "test-csrf-token",
            "title": "危险链接文章",
            "source": "安全测试",
            "source_url": "javascript:alert(1)",
            "summary": "摘要",
            "content_html": "<p>正文</p>",
            "tags": "安全",
            "category": "insight",
            "is_featured": "0",
            "status": "draft",
        },
    )

    assert response.status_code == 400
    db = models.get_db()
    try:
        count = db.execute(
            "SELECT COUNT(*) FROM articles WHERE title=?", ("危险链接文章",)
        ).fetchone()[0]
    finally:
        db.close()
    assert count == 0


def test_admin_rejects_overlong_article_title(admin_client):
    """Oversized CMS text must be bounded before storage and audit logging."""
    response = admin_client.post(
        "/admin/article/new",
        data={
            "csrf_token": "test-csrf-token",
            "title": "文" * 201,
            "source": "安全测试",
            "source_url": "https://example.invalid/report",
            "summary": "摘要",
            "content_html": "<p>正文</p>",
            "tags": "安全",
            "category": "insight",
            "is_featured": "0",
            "status": "draft",
        },
    )

    assert response.status_code == 400


def test_admin_rejects_non_numeric_boolean_field(admin_client):
    """Malformed numeric form fields must return 400 rather than raising ValueError."""
    response = admin_client.post(
        "/admin/article/new",
        data={
            "csrf_token": "test-csrf-token",
            "title": "非法精选值",
            "source": "安全测试",
            "source_url": "",
            "summary": "摘要",
            "content_html": "<p>正文</p>",
            "tags": "安全",
            "category": "insight",
            "is_featured": "not-a-number",
            "status": "draft",
        },
    )

    assert response.status_code == 400


def test_admin_rejects_zero_asset_quantity(admin_client):
    """Asset quantities must stay within the server-enforced positive range."""
    response = admin_client.post(
        "/admin/assets/unit-b/new",
        data={
            "csrf_token": "test-csrf-token",
            "asset_code_id": "1",
            "quantity": "0",
            "remark": "非法数量",
        },
    )

    assert response.status_code == 400


def test_missing_page_uses_safe_custom_error_page(client):
    """Unknown routes must return a useful page without framework diagnostics."""
    response = client.get("/definitely-missing")

    assert response.status_code == 404
    assert "页面未找到".encode("utf-8") in response.data
    assert b"Traceback" not in response.data


def test_scrape_failure_does_not_leak_exception_details(
    admin_client, monkeypatch, caplog
):
    """External-service failures must not expose tokens or stack details to users/logs."""
    import scraper

    secret_marker = "private-token-marker"

    def fail_scrape():
        raise RuntimeError(secret_marker)

    monkeypatch.setattr(scraper, "run_scraper", fail_scrape)
    caplog.set_level(logging.ERROR)

    response = admin_client.post(
        "/admin/scrape",
        headers={"X-CSRF-Token": "test-csrf-token"},
    )

    assert response.status_code == 502
    assert response.get_json() == {"success": False, "error": "scrape failed"}
    assert secret_marker.encode("utf-8") not in response.data
    assert secret_marker not in caplog.text


def test_unhandled_error_uses_generic_page_and_redacted_log(
    client, monkeypatch, caplog
):
    """Unexpected exceptions must not disclose their message in HTML or logs."""
    secret_marker = "database-secret-marker"

    def fail_index():
        raise RuntimeError(secret_marker)

    monkeypatch.setitem(client.application.view_functions, "public.index", fail_index)
    caplog.set_level(logging.ERROR)

    response = client.get("/")

    assert response.status_code == 500
    assert "系统暂时无法处理请求".encode("utf-8") in response.data
    assert secret_marker.encode("utf-8") not in response.data
    assert secret_marker not in caplog.text
    assert "RuntimeError" in caplog.text
