import sqlite3
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from flask import render_template_string
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
        "PUBLIC_BASE_URL": "https://test.example",
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

    assert versions == [
        "001_initial",
        "002_security",
        "003_v2_catalog",
        "004_v2_assessment_leads",
        "005_v2_appointments_analytics",
        "006_content_catalog",
        "007_scenario_public_inputs",
        "008_service_content_maturity",
        "009_case_basis_types",
    ]
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


def test_base_design_system_and_behaviors_are_external_static_assets(client):
    """The shared shell must stay small and load cacheable CSS/JS from /static."""
    response = client.get("/")
    page = BeautifulSoup(response.data, "html.parser")

    stylesheet = page.select_one('link[rel="stylesheet"][href="/static/css/app.css"]')
    script = page.select_one('script[src="/static/js/app.js"]')

    assert stylesheet is not None
    assert script is not None
    assert client.get("/static/css/app.css").status_code == 200
    assert client.get("/static/js/app.js").status_code == 200
    assert b"Scroll animations + Sticky CTA" not in response.data


def test_legacy_services_path_redirects_to_the_canonical_catalog(client):
    response = client.get("/services")

    assert response.status_code == 301
    assert response.headers["Location"] == "/service-packages"


def test_shared_shells_are_composed_from_named_template_components():
    public_shell = (PROJECT_ROOT / "templates" / "base.html").read_text(
        encoding="utf-8"
    )
    admin_shell = (
        PROJECT_ROOT / "templates" / "admin" / "base_admin.html"
    ).read_text(encoding="utf-8")
    expected_files = {
        "navigation.html",
        "footer.html",
        "sticky_cta.html",
        "admin_navigation.html",
        "ui.html",
    }

    component_dir = PROJECT_ROOT / "templates" / "components"
    assert {path.name for path in component_dir.glob("*.html")} >= expected_files
    assert 'include "components/navigation.html"' in public_shell
    assert 'include "components/footer.html"' in public_shell
    assert 'include "components/sticky_cta.html"' in public_shell
    assert 'include "components/admin_navigation.html"' in admin_shell


def test_ui_component_macros_escape_values_and_expose_accessible_state(client):
    with client.application.test_request_context("/component-test"):
        rendered = render_template_string(
            """
            {% from "components/ui.html" import alert, form_field, pagination %}
            {{ alert("<unsafe>", "error") }}
            {{ form_field("company", "企业", "<script>", required=true) }}
            {{ pagination(2, 3, "public.index") }}
            """
        )
    page = BeautifulSoup(rendered, "html.parser")

    assert page.select_one('[role="alert"]').get_text(strip=True) == "<unsafe>"
    assert page.select_one('input[name="company"]')["value"] == "<script>"
    assert page.select_one('input[name="company"]').has_attr("required")
    assert page.select_one('[aria-current="page"]').get_text(strip=True) == "2"
