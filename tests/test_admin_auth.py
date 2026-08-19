from bs4 import BeautifulSoup

from conftest import TEST_ADMIN_PASSWORD, TEST_ADMIN_USERNAME


def csrf_from(response):
    """Read the real CSRF field rendered by the login form."""
    field = BeautifulSoup(response.data, "html.parser").select_one(
        'input[name="csrf_token"]'
    )
    assert field is not None
    return field["value"]


def test_admin_login_page_is_public_and_renders_csrf_token(client):
    """An unauthenticated administrator must be able to reach a protected login form."""
    response = client.get("/admin/login")

    assert response.status_code == 200
    assert csrf_from(response)


def test_admin_login_rejects_wrong_password(client):
    """A wrong password must not establish an authenticated session."""
    token = csrf_from(client.get("/admin/login"))

    response = client.post(
        "/admin/login",
        data={
            "csrf_token": token,
            "username": TEST_ADMIN_USERNAME,
            "password": "wrong-password",
        },
    )

    assert response.status_code == 401
    assert client.get("/admin").status_code == 302


def test_admin_login_uses_password_hash_and_establishes_secure_session(client):
    """The configured password hash must unlock a secure browser session."""
    token = csrf_from(client.get("/admin/login"))

    response = client.post(
        "/admin/login",
        data={
            "csrf_token": token,
            "username": TEST_ADMIN_USERNAME,
            "password": TEST_ADMIN_PASSWORD,
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin")
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=Lax" in cookie
    assert client.get("/admin").status_code == 200


def test_http_basic_credentials_no_longer_authenticate_admin(client):
    """Legacy Basic Auth headers must not bypass the new login flow."""
    response = client.get(
        "/admin",
        headers={"Authorization": "Basic dGVzdC1hZG1pbjp3cm9uZw=="},
    )

    assert response.status_code == 302
    assert "/admin/login" in response.headers["Location"]


def test_logout_clears_admin_session(client):
    """Logging out must revoke access from the existing browser session."""
    token = csrf_from(client.get("/admin/login"))
    client.post(
        "/admin/login",
        data={
            "csrf_token": token,
            "username": TEST_ADMIN_USERNAME,
            "password": TEST_ADMIN_PASSWORD,
        },
    )
    with client.session_transaction() as session:
        logout_token = session["csrf_token"]

    response = client.post(
        "/admin/logout",
        data={"csrf_token": logout_token},
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin/login")
    assert client.get("/admin").status_code == 302


def test_admin_fails_closed_when_security_configuration_is_missing(client):
    """Missing production credentials must disable login instead of using defaults."""
    client.application.config["ADMIN_PASSWORD_HASH"] = None

    response = client.get("/admin/login")

    assert response.status_code == 503


def test_security_headers_are_added_to_public_responses(client):
    """Public responses must carry the baseline browser security policy."""
    response = client.get("/health")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "camera=()" in response.headers["Permissions-Policy"]
