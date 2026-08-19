import base64

import pytest

import app as app_module
import models


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Return a Flask client backed by a fresh, disposable database."""
    monkeypatch.setattr(models, "DB_PATH", str(tmp_path / "platform.db"))
    models.init_db()
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


@pytest.fixture()
def admin_headers():
    """Build current-version admin auth without copying credentials into tests."""
    credentials = (
        f"{app_module.ADMIN_USERNAME}:{app_module.ADMIN_PASSWORD}".encode("utf-8")
    )
    token = base64.b64encode(credentials).decode("ascii")
    return {"Authorization": f"Basic {token}"}
