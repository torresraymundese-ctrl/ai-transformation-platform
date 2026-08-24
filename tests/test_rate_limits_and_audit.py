from bs4 import BeautifulSoup

import models


VALID_ASSESSMENT = {
    "company": "限流测试企业",
    "email": "rate-limit@example.invalid",
    "scores": {"strategy": 60},
    "result": "starter",
}


def login_csrf(client):
    response = client.get("/admin/login")
    field = BeautifulSoup(response.data, "html.parser").select_one(
        'input[name="csrf_token"]'
    )
    assert field is not None
    return field["value"]


def test_assessment_rate_limit_blocks_excess_submissions(client):
    """One source must not be able to flood the lead database."""
    client.application.config.update(
        ASSESSMENT_RATE_LIMIT=2,
        ASSESSMENT_RATE_WINDOW=3600,
    )

    assert client.post("/api/assessment", json=VALID_ASSESSMENT).status_code == 200
    assert client.post("/api/assessment", json=VALID_ASSESSMENT).status_code == 200
    blocked = client.post("/api/assessment", json=VALID_ASSESSMENT)

    assert blocked.status_code == 429
    assert blocked.get_json() == {"error": "rate limit exceeded"}
    assert blocked.headers["Retry-After"] == "3600"


def test_rate_limit_distinguishes_clients_behind_the_trusted_proxy(client):
    """Nginx-forwarded client addresses must not collapse all visitors into one bucket."""
    client.application.config.update(
        ASSESSMENT_RATE_LIMIT=1,
        ASSESSMENT_RATE_WINDOW=3600,
    )

    first = client.post(
        "/api/assessment",
        json=VALID_ASSESSMENT,
        headers={"X-Forwarded-For": "198.51.100.10", "X-Forwarded-Proto": "https"},
    )
    second = client.post(
        "/api/assessment",
        json=VALID_ASSESSMENT,
        headers={"X-Forwarded-For": "198.51.100.11", "X-Forwarded-Proto": "https"},
    )

    assert first.status_code == 200
    assert second.status_code == 200


def test_login_rate_limit_blocks_repeated_wrong_passwords(client):
    """Repeated login failures from one source must be throttled."""
    client.application.config.update(LOGIN_RATE_LIMIT=2, LOGIN_RATE_WINDOW=900)
    token = login_csrf(client)
    payload = {
        "csrf_token": token,
        "username": "test-admin",
        "password": "definitely-wrong",
    }

    assert client.post("/admin/login", data=payload).status_code == 401
    assert client.post("/admin/login", data=payload).status_code == 401
    blocked = client.post("/admin/login", data=payload)

    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "900"


def test_short_rate_limit_window_cannot_delete_an_active_long_window(
    client, monkeypatch
):
    """Cleanup for one bucket must never reset another bucket's active quota."""
    import security

    clock = {"now": 100}
    monkeypatch.setattr(security.time, "time", lambda: clock["now"])
    client.application.config.update(
        ASSESSMENT_RATE_LIMIT=1,
        ASSESSMENT_RATE_WINDOW=3600,
        LOGIN_RATE_LIMIT=10,
        LOGIN_RATE_WINDOW=900,
    )
    assert client.post("/api/assessment", json=VALID_ASSESSMENT).status_code == 200

    token = login_csrf(client)
    clock["now"] = 2000
    assert client.post(
        "/admin/login",
        data={
            "csrf_token": token,
            "username": "test-admin",
            "password": "definitely-wrong",
        },
    ).status_code == 401

    clock["now"] = 2001
    assert client.post("/api/assessment", json=VALID_ASSESSMENT).status_code == 429


def test_scrape_rate_limit_still_bounds_repeated_retired_ingestion_requests(admin_client):
    """The retired endpoint must keep its existing request-rate boundary."""
    admin_client.application.config.update(SCRAPE_RATE_LIMIT=1, SCRAPE_RATE_WINDOW=3600)
    headers = {"X-CSRF-Token": "test-csrf-token"}

    assert admin_client.post("/admin/scrape", headers=headers).status_code == 410
    blocked = admin_client.post("/admin/scrape", headers=headers)

    assert blocked.status_code == 429
    assert blocked.get_json() == {"error": "rate limit exceeded"}


def test_successful_admin_write_creates_a_minimal_audit_record(admin_client):
    """A successful content change must be attributable without storing form data."""
    response = admin_client.post(
        "/admin/announcement/new",
        data={
            "csrf_token": "test-csrf-token",
            "title": "审计测试",
            "content_html": "<p>不应进入审计详情</p>",
            "is_pinned": "0",
            "status": "draft",
        },
    )
    assert response.status_code == 302

    db = models.get_db()
    try:
        record = db.execute(
            "SELECT actor, action, status_code FROM admin_audit_logs "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        columns = {
            row[1] for row in db.execute("PRAGMA table_info(admin_audit_logs)")
        }
    finally:
        db.close()

    assert dict(record) == {
        "actor": "test-admin",
        "action": "admin_announcement_new",
        "status_code": 302,
    }
    assert "request_body" not in columns
    assert "password" not in columns


def test_rejected_admin_write_is_recorded_for_investigation(admin_client):
    """A blocked CSRF write must leave an audit trail without mutating content."""
    response = admin_client.post(
        "/admin/announcement/new",
        data={"title": "不应写入", "status": "draft"},
    )
    assert response.status_code == 403

    db = models.get_db()
    try:
        record = db.execute(
            "SELECT action, status_code FROM admin_audit_logs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        count = db.execute(
            "SELECT COUNT(*) FROM announcements WHERE title=?", ("不应写入",)
        ).fetchone()[0]
    finally:
        db.close()

    assert dict(record) == {
        "action": "admin_announcement_new",
        "status_code": 403,
    }
    assert count == 0
