#!/usr/bin/env python3
"""Explicit operational commands for deployment and maintenance."""

import argparse

import lead_repository
from models import init_db


def main(argv=None):
    parser = argparse.ArgumentParser(description="Manage the AI platform")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("migrate", help="Apply database migrations and seed defaults")
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
    if args.command == "purge-expired-leads":
        result = lead_repository.run_retention_purge(apply=args.apply)
        mode = "apply" if args.apply else "dry-run"
        identifiers = ",".join(str(lead_id) for lead_id in result.lead_ids) or "none"
        print(f"mode={mode} count={result.count} ids={identifiers}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
