import shutil
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

import app as app_module
import migrations
import models


TEST_ADMIN_USERNAME = "test-admin"
TEST_ADMIN_PASSWORD = "correct horse battery staple"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Return a Flask client backed by a fresh, disposable database."""
    monkeypatch.setattr(models, "DB_PATH", str(tmp_path / "platform.db"))
    models.init_db()
    test_app = app_module.create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-session-secret",
            "ADMIN_USERNAME": TEST_ADMIN_USERNAME,
            "ADMIN_PASSWORD_HASH": generate_password_hash(TEST_ADMIN_PASSWORD),
            "SESSION_COOKIE_SECURE": True,
            "SESSION_COOKIE_HTTPONLY": True,
            "SESSION_COOKIE_SAMESITE": "Lax",
        }
    )
    return test_app.test_client()


@pytest.fixture()
def admin_client(client):
    """Return a client with an authenticated admin session and known CSRF token."""
    with client.session_transaction() as session:
        session["admin_username"] = TEST_ADMIN_USERNAME
        session["csrf_token"] = "test-csrf-token"
    return client


@pytest.fixture()
def db(client):
    """Open the client fixture's disposable database with foreign keys enabled."""
    connection = models.get_db()
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture()
def db_through_005(tmp_path, monkeypatch):
    """Return a seeded disposable database with only migrations 001-005 applied."""
    monkeypatch.setattr(models, "DB_PATH", str(tmp_path / "platform-005.db"))
    migrations_dir = tmp_path / "migrations-through-005"
    migrations_dir.mkdir()
    for migration_path in sorted((PROJECT_ROOT / "migrations").glob("00[1-5]_*.sql")):
        shutil.copy2(migration_path, migrations_dir / migration_path.name)
    monkeypatch.setattr(migrations, "MIGRATIONS_DIR", migrations_dir)
    models.init_db()
    connection = models.get_db()
    try:
        yield connection
    finally:
        connection.close()
