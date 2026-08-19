"""Minimal ordered SQLite migration runner."""

from pathlib import Path


MIGRATIONS_DIR = Path(__file__).with_name("migrations")


def apply_migrations(connection):
    """Apply each numbered SQL file once and record its filename stem."""
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version TEXT PRIMARY KEY, "
        "applied_at TEXT DEFAULT (datetime('now','localtime'))"
        ")"
    )
    applied = {
        row[0]
        for row in connection.execute("SELECT version FROM schema_migrations")
    }
    for path in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")):
        version = path.stem
        if version in applied:
            continue
        connection.executescript(path.read_text(encoding="utf-8"))
        connection.execute(
            "INSERT INTO schema_migrations (version) VALUES (?)", (version,)
        )
        connection.commit()
