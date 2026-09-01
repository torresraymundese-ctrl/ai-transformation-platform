#!/usr/bin/env python3
"""Explicit operational commands for deployment and maintenance."""

import argparse
from dataclasses import dataclass
import hashlib
from pathlib import Path
import sqlite3
import sys

import lead_repository
import legacy_content_migration
import media_service
import models
import publishing_service
import scraper
from content_clock import shanghai_now
from models import init_db
from source_url_checker import PinnedHttpTransport


def _reject_active_sidecars(database_path):
    for suffix in ("-wal", "-journal"):
        sidecar = database_path.with_name(f"{database_path.name}{suffix}")
        if sidecar.exists() and sidecar.stat().st_size:
            raise sqlite3.OperationalError("inventory database is not self-contained")


def _strong_file_fingerprint(path):
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat()
    before_shape = (before.st_size, before.st_mtime_ns)
    after_shape = (after.st_size, after.st_mtime_ns)
    if before_shape != after_shape:
        raise sqlite3.OperationalError("inventory database changed during read")
    return (*after_shape, digest.hexdigest())


@dataclass(frozen=True)
class _ReadOnlyInventorySnapshot:
    database_path: Path
    main_fingerprint: tuple[int, int, str]

    def validate(self):
        _reject_active_sidecars(self.database_path)
        if _strong_file_fingerprint(self.database_path) != self.main_fingerprint:
            raise sqlite3.OperationalError("inventory database changed during read")
        _reject_active_sidecars(self.database_path)


def _open_inventory_readonly():
    database_path = Path(models.DB_PATH).resolve(strict=True)
    _reject_active_sidecars(database_path)
    snapshot = _ReadOnlyInventorySnapshot(
        database_path=database_path,
        main_fingerprint=_strong_file_fingerprint(database_path),
    )
    _reject_active_sidecars(database_path)
    connection = None
    try:
        connection = sqlite3.connect(
            f"{database_path.as_uri()}?mode=ro&immutable=1", uri=True
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        snapshot.validate()
        return connection, snapshot
    except Exception:
        if connection is not None:
            connection.close()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description="Manage the AI platform")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("migrate", help="Apply database migrations and seed defaults")
    subcommands.add_parser(
        "fetch-content",
        help="Fetch explicitly enabled reviewed sources into the private queue",
    )
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
    source_check = subcommands.add_parser(
        "check-content-sources",
        help="Preflight reviewed legacy sources and persist generic results",
    )
    migrate_legacy = subcommands.add_parser(
        "migrate-legacy-content",
        help="Preview or apply approved legacy content decisions",
    )
    migrate_legacy.add_argument(
        "--decisions",
        required=True,
        help="Operator-authored strict JSONL decision artifact",
    )
    migrate_legacy.add_argument(
        "--apply",
        action="store_true",
        help="Create or explicitly merge drafts (default is read-only preview)",
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
    publish_due = subcommands.add_parser(
        "publish-due-content",
        help="Atomically publish due content revisions",
    )
    recover_media = subcommands.add_parser(
        "recover-media-storage",
        help="Preview or apply non-destructive media storage reconciliation",
    )
    recover_media.add_argument(
        "--apply",
        action="store_true",
        help="Apply safe state transitions (default is dry-run)",
    )
    args = parser.parse_args(argv)

    if args.command == "migrate":
        init_db()
        return 0
    if args.command == "fetch-content":
        try:
            result = scraper.run_scraper()
        except scraper.IngestionQueueNotReadyError:
            print("error=ingestion_queue_not_ready", file=sys.stderr)
            return 1
        except (OSError, sqlite3.Error, ValueError, RuntimeError):
            print("error=ingestion_failed", file=sys.stderr)
            return 1
        identifiers = ",".join(str(item) for item in result.created_ids) or "none"
        print(
            f"created_count={len(result.created_ids)} created_ids={identifiers} "
            f"deduplicated={result.deduplicated} attempted_sources={result.attempted_sources} "
            f"failed_sources={result.failed_sources}"
        )
        return 0
    if args.command == "inventory-content":
        db = None
        snapshot = None
        try:
            if args.record:
                db = models.get_db()
            else:
                db, snapshot = _open_inventory_readonly()
            items = legacy_content_migration.inventory_legacy_content(db)
            if args.record:
                legacy_content_migration.record_legacy_inventory(db, items)
            output = legacy_content_migration.items_to_jsonl(items)
            if snapshot is not None:
                snapshot.validate()
            if output:
                print(output)
        except (OSError, sqlite3.Error, ValueError):
            print("error=inventory_unavailable", file=sys.stderr)
            return 1
        finally:
            if db is not None:
                db.close()
        return 0
    if args.command == "check-content-sources":
        db = None
        try:
            if not Path(models.DB_PATH).is_file():
                raise OSError("content database is unavailable")
            db = models.get_db()
            result = legacy_content_migration.check_legacy_sources(
                db,
                transport=PinnedHttpTransport(),
                actor="legacy_source_check",
                now=shanghai_now(),
            )
            if result.errors:
                raise ValueError("source preflight did not complete")
            for line in legacy_content_migration.check_result_to_lines(result):
                print(line)
        except (OSError, sqlite3.Error, ValueError, RuntimeError):
            print("error=content_source_check_unavailable", file=sys.stderr)
            return 1
        finally:
            if db is not None:
                db.close()
        return 0
    if args.command == "migrate-legacy-content":
        db = None
        snapshot = None
        try:
            decisions = legacy_content_migration.load_legacy_decisions(args.decisions)
            if args.apply:
                if not Path(models.DB_PATH).is_file():
                    raise OSError("content database is unavailable")
                db = models.get_db()
                result = legacy_content_migration.apply_legacy_decisions(
                    db,
                    decisions,
                    actor="legacy_migration",
                    now=shanghai_now(),
                )
            else:
                db, snapshot = _open_inventory_readonly()
                result = legacy_content_migration.preview_legacy_decisions(
                    db, decisions, now=shanghai_now()
                )
            output = legacy_content_migration.migration_result_to_jsonl(result)
            if snapshot is not None:
                snapshot.validate()
            if output:
                print(output)
            return 0 if not result.errors else 1
        except (OSError, sqlite3.Error, ValueError, RuntimeError, OverflowError):
            print("error=legacy_migration_unavailable", file=sys.stderr)
            return 1
        finally:
            if db is not None:
                db.close()
    if args.command == "purge-expired-leads":
        result = lead_repository.run_retention_purge(apply=args.apply)
        mode = "apply" if args.apply else "dry-run"
        identifiers = ",".join(str(lead_id) for lead_id in result.lead_ids) or "none"
        print(f"mode={mode} count={result.count} ids={identifiers}")
        return 0
    if args.command == "publish-due-content":
        try:
            result = publishing_service.publish_due_content()
        except (OSError, sqlite3.Error, ValueError):
            print("error=publish_due_unavailable", file=sys.stderr)
            return 1
        published_ids = ",".join(str(item) for item in result.published_ids) or "none"
        failures = ",".join(
            f"{content_id}:{code}" for content_id, code in result.failures
        ) or "none"
        print(
            f"published_count={result.published_count} published_ids={published_ids} "
            f"failed_count={result.failed_count} failures={failures}"
        )
        return 0
    if args.command == "recover-media-storage":
        try:
            result = media_service.recover_media_storage(apply=args.apply)
        except (OSError, sqlite3.Error, ValueError):
            print("error=media_recovery_unavailable", file=sys.stderr)
            return 1
        mode = "apply" if args.apply else "dry-run"
        findings = ",".join(
            f"{item.asset_id if item.asset_id is not None else 'none'}:{item.status}"
            for item in result.findings
        ) or "none"
        print(f"mode={mode} count={result.count} findings={findings}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
