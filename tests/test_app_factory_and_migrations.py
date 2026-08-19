import sqlite3
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from werkzeug.security import generate_password_hash

import app as app_module
import models


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def login_token(client):
    response = client.get("/admin/login")
    field = BeautifulSoup(response.data, "html.parser").select_one(
        'input[name="csrf_token"]'
    )
    assert field is not None
    return field["value"]


def secure_config(username, password):
    return {
        "TESTING": True,
        "SECRET_KEY": f"session-key-for-{username}",
        "ADMIN_USERNAME": username,
        "ADMIN_PASSWORD_HASH": generate_password_hash(password),
        "SESSION_COOKIE_SECURE": False,
    }


def test_create_app_builds_distinct_instances_with_isolated_auth(tmp_path, monkeypatch):
    """Tests and deployment environments must not share mutable Flask configuration."""
    monkeypatch.setattr(models, "DB_PATH", str(tmp_path / "platform.db"))
    models.init_db()

    first = app_module.create_app(secure_config("first-admin", "first-long-password"))
    second = app_module.create_app(secure_config("second-admin", "second-long-password"))
    first_client = first.test_client()
    second_client = second.test_client()

    first_response = first_client.post(
        "/admin/login",
        data={
            "csrf_token": login_token(first_client),
            "username": "first-admin",
            "password": "first-long-password",
        },
    )
    second_response = second_client.post(
        "/admin/login",
        data={
            "csrf_token": login_token(second_client),
            "username": "first-admin",
            "password": "first-long-password",
        },
    )

    assert first is not second
    assert first_response.status_code == 302
    assert second_response.status_code == 401
    assert first_client.get("/health").get_json() == {"status": "ok"}


def test_database_migrations_are_versioned_idempotent_and_preserve_data(
    tmp_path, monkeypatch
):
    """Repeated startup migrations must preserve existing business rows."""
    monkeypatch.setattr(models, "DB_PATH", str(tmp_path / "platform.db"))
    models.init_db()
    db = models.get_db()
    try:
        db.execute(
            "INSERT INTO site_config (key, value) VALUES (?, ?)",
            ("migration-sentinel", "keep-me"),
        )
        db.commit()
    finally:
        db.close()

    models.init_db()
    db = models.get_db()
    try:
        versions = [
            row[0]
            for row in db.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        ]
        sentinel = db.execute(
            "SELECT value FROM site_config WHERE key=?", ("migration-sentinel",)
        ).fetchone()[0]
    finally:
        db.close()

    assert versions == ["001_initial", "002_security"]
    assert sentinel == "keep-me"


def test_database_enforces_asset_foreign_keys(tmp_path, monkeypatch):
    """Database integrity must still hold if a future caller bypasses HTTP validation."""
    monkeypatch.setattr(models, "DB_PATH", str(tmp_path / "platform.db"))
    models.init_db()
    db = models.get_db()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO unit_b_assets (asset_code_id, quantity) VALUES (?, ?)",
                (999999, 1),
            )
    finally:
        db.close()


def test_blueprints_delegate_database_access_to_repositories():
    """HTTP adapters must not grow a second, route-local data-access layer."""
    violations = []
    for path in (PROJECT_ROOT / "blueprints").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "get_db" in source or ".execute(" in source or "execute_write" in source:
            violations.append(path.relative_to(PROJECT_ROOT).as_posix())

    assert violations == []
