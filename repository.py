"""Shared database operations with explicit commit, rollback, and close semantics."""

import sqlite3

from models import get_db


class DataConflictError(RuntimeError):
    """Raised when a write violates a business uniqueness or relation constraint."""


def run_transaction(operation):
    """Run a callable in one transaction and always release the connection."""
    db = get_db()
    try:
        result = operation(db)
        db.commit()
        return result
    except sqlite3.IntegrityError as error:
        db.rollback()
        raise DataConflictError("database constraint conflict") from error
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def execute_write(statement, parameters=()):
    """Execute one statement through the shared transaction boundary."""
    return run_transaction(
        lambda db: db.execute(statement, parameters).lastrowid
    )
