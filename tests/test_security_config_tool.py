import os
import stat
from pathlib import Path

import pytest
from werkzeug.security import check_password_hash

from scripts.configure_security import build_environment, write_environment_file


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_environment(text):
    return dict(line.split("=", 1) for line in text.strip().splitlines())


def test_environment_contains_hash_and_random_session_key_not_plaintext():
    """The generated server file must never contain the administrator password."""
    password = "a-long-local-test-password"

    text = build_environment("platform-admin", password)
    values = parse_environment(text)

    assert password not in text
    assert values["AI_PLATFORM_ADMIN_USERNAME"] == "platform-admin"
    assert check_password_hash(values["AI_PLATFORM_ADMIN_PASSWORD_HASH"], password)
    assert len(values["AI_PLATFORM_SECRET_KEY"]) >= 43


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("bad user", "a-long-local-test-password"),
        ("admin", "too-short"),
        ("admin\nINJECTED=value", "a-long-local-test-password"),
    ],
)
def test_environment_rejects_unsafe_username_or_weak_password(username, password):
    """Unsafe environment syntax and weak credentials must be rejected before writing."""
    with pytest.raises(ValueError):
        build_environment(username, password)


def test_environment_file_is_created_exclusively_and_not_overwritten(tmp_path):
    """Credential rotation must not silently overwrite an existing security file."""
    path = tmp_path / "ai-platform.env"
    content = build_environment("platform-admin", "a-long-local-test-password")

    write_environment_file(path, content)

    assert path.read_text(encoding="utf-8") == content
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        write_environment_file(path, content)


def test_production_service_runs_migrations_before_gunicorn():
    service = (
        PROJECT_ROOT / "ops" / "systemd" / "ai-platform.service"
    ).read_text(encoding="utf-8")

    assert (
        "ExecStartPre=/opt/ai-platform/.venv/bin/python "
        "/opt/ai-platform/manage.py migrate"
    ) in service
    assert "ExecStart=/opt/ai-platform/.venv/bin/gunicorn" in service


def test_manage_migrate_command_initializes_database(monkeypatch):
    import manage

    calls = []
    monkeypatch.setattr(manage, "init_db", lambda: calls.append("migrated"))

    assert manage.main(["migrate"]) == 0
    assert calls == ["migrated"]
