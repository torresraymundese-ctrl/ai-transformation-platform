import pytest
from werkzeug.security import generate_password_hash

import app as app_module
import models


TEST_ADMIN_USERNAME = "test-admin"
TEST_ADMIN_PASSWORD = "correct horse battery staple"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Return a Flask client backed by a fresh, disposable database."""
    monkeypatch.setattr(models, "DB_PATH", str(tmp_path / "platform.db"))
    models.init_db()
    app_module.app.config.update(
        TESTING=True,
        SECRET_KEY="test-only-session-secret",
        ADMIN_USERNAME=TEST_ADMIN_USERNAME,
        ADMIN_PASSWORD_HASH=generate_password_hash(TEST_ADMIN_PASSWORD),
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    return app_module.app.test_client()


@pytest.fixture()
def admin_client(client):
    """Return a client with an authenticated admin session and known CSRF token."""
    with client.session_transaction() as session:
        session["admin_username"] = TEST_ADMIN_USERNAME
        session["csrf_token"] = "test-csrf-token"
    return client
