#!/usr/bin/env python3
"""Explicit operational commands for deployment and maintenance."""

import argparse
from pathlib import Path
import sqlite3
import sys

import lead_repository
import legacy_content_migration
import models
from models import init_db


def _open_inventory_readonly():
    database_path = Path(models.DB_PATH).resolve(strict=True)
    connection = sqlite3.connect(f"{database_path.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def main(argv=None):
    parser = argparse.ArgumentParser(description="Manage the AI platform")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("migrate", help="Apply database migrations and seed defaults")
    inventory = subcommands.add_parser(
        "inventory-content",
        help="Print a local-only legacy content review inventory",
    )
    inventory.add_argument(
        "--format",
        choices=("jsonl",),
        default="jsonl",
        help="Output format (default: jsonl)",
    )
    inventory.add_argument(
        "--record",
        action="store_true",
        help="Record review rows atomically (default is zero-write dry-run)",
    )
    purge = subcommands.add_parser(
        "purge-expired-leads",
        help="Preview or anonymize expired unconverted lead contact data",
    )
    purge.add_argument(
        "--apply",
        action="store_true",
        help="Apply the anonymization (default is dry-run)",
    )
    args = parser.parse_args(argv)

    if args.command == "migrate":
        init_db()
        return 0
    if args.command == "inventory-content":
        db = None
        try:
            db = models.get_db() if args.record else _open_inventory_readonly()
            items = legacy_content_migration.inventory_legacy_content(db)
            if args.record:
                legacy_content_migration.record_legacy_inventory(db, items)
            output = legacy_content_migration.items_to_jsonl(items)
            if output:
                print(output)
        except (OSError, sqlite3.Error):
            print("error=inventory_unavailable", file=sys.stderr)
            return 1
        finally:
            if db is not None:
                db.close()
        return 0
    if args.command == "purge-expired-leads":
        result = lead_repository.run_retention_purge(apply=args.apply)
        mode = "apply" if args.apply else "dry-run"
        identifiers = ",".join(str(lead_id) for lead_id in result.lead_ids) or "none"
        print(f"mode={mode} count={result.count} ids={identifiers}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
