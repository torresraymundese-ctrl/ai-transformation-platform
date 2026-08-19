"""Minimal ordered SQLite migration runner."""

from pathlib import Path
import sqlite3


MIGRATIONS_DIR = Path(__file__).with_name("migrations")


def apply_migrations(connection):
    """Apply each numbered SQL file once and record its filename stem."""
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version TEXT PRIMARY KEY, "
        "applied_at TEXT DEFAULT (datetime('now','localtime'))"
        ")"
    )
    connection.commit()
    applied = {
        row[0]
        for row in connection.execute("SELECT version FROM schema_migrations")
    }
    for path in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")):
        version = path.stem
        if version in applied:
            continue
        version_sql = connection.execute("SELECT quote(?)", (version,)).fetchone()[0]
        script = path.read_text(encoding="utf-8")
        try:
            connection.executescript(
                "BEGIN IMMEDIATE;\n"
                f"{script}\n"
                "INSERT INTO schema_migrations (version) "
                f"VALUES ({version_sql});\n"
                "COMMIT;\n"
            )
        except sqlite3.Error:
            connection.rollback()
            raise
