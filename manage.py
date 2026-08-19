#!/usr/bin/env python3
"""Explicit operational commands for deployment and maintenance."""

import argparse

from models import init_db


def main(argv=None):
    parser = argparse.ArgumentParser(description="Manage the AI platform")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("migrate", help="Apply database migrations and seed defaults")
    args = parser.parse_args(argv)

    if args.command == "migrate":
        init_db()
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
