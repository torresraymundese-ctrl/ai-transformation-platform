import logging

import models


def _resource_form(**overrides):
    form = {
        "csrf_token": "test-csrf-token",
        "action": "save",
        "slug": "validation-resource",
        "title": "安全测试资源",
        "summary": "经审核的安全测试摘要。",
        "seo_title": "安全测试资源",
        "seo_description": "经审核的安全测试资源摘要。",
        "share_image_media_id": "",
        "resource_type": "article",
        "is_original": "1",
        "source_name": "",
        "source_url": "",
        "original_published_at": "2026-08-20T09:30",
        "copyright_notice": "安全测试版权说明。",
        "attachment_media_id": "",
        "blocks-0-type": "rich_text",
        "blocks-0-title": "正文",
        "blocks-0-body": "<p>正文</p>",
        "blocks-0-media_id": "",
    }
    form.update(overrides)
    return form


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
    """Reviewed resource writes accept only normalized HTTPS source links."""
    response = admin_client.post(
        "/admin/resources/new",
        data=_resource_form(
            slug="dangerous-source-resource",
            title="危险链接文章",
            is_original="0",
            source_name="安全测试",
            source_url="javascript:alert(1)",
        ),
    )

    assert response.status_code == 400
    db = models.get_db()
    try:
        count = db.execute(
            "SELECT COUNT(*) FROM content_items WHERE entry_type='resource' AND title=?",
            ("危险链接文章",),
        ).fetchone()[0]
    finally:
        db.close()
    assert count == 0


def test_admin_rejects_overlong_article_title(admin_client):
    """Oversized CMS text must be bounded before storage and audit logging."""
    response = admin_client.post(
        "/admin/resources/new",
        data=_resource_form(slug="overlong-resource", title="文" * 121),
    )

    assert response.status_code == 400


def test_admin_rejects_non_numeric_boolean_field(admin_client):
    """Malformed authorship flags return 400 rather than raising ValueError."""
    response = admin_client.post(
        "/admin/resources/new",
        data=_resource_form(slug="invalid-authorship", is_original="not-a-number"),
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


def test_duplicate_asset_code_returns_conflict_and_next_write_still_works(
    admin_client
):
    """A unique-key conflict must roll back, close cleanly, and return HTTP 409."""
    duplicate = admin_client.post(
        "/admin/assets/code/new",
        data={
            "csrf_token": "test-csrf-token",
            "code": "Z001",
            "name": "重复编码",
            "category": "table",
            "sort_order": "0",
        },
    )
    valid = admin_client.post(
        "/admin/assets/code/new",
        data={
            "csrf_token": "test-csrf-token",
            "code": "TEST-UNIQUE-001",
            "name": "后续合法编码",
            "category": "table",
            "sort_order": "0",
        },
    )

    assert duplicate.status_code == 409
    assert "数据冲突".encode("utf-8") in duplicate.data
    assert valid.status_code == 302


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
