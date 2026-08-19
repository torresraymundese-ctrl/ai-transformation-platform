#!/usr/bin/env python3
"""Create a root-readable systemd EnvironmentFile without storing plaintext passwords."""

import argparse
import getpass
import os
from pathlib import Path
import re
import secrets

from werkzeug.security import generate_password_hash


USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")
MINIMUM_PASSWORD_LENGTH = 14


def build_environment(username, password):
    """Build environment contents containing only a password hash and session secret."""
    if not isinstance(username, str) or not USERNAME_PATTERN.fullmatch(username):
        raise ValueError(
            "Username must be 3-64 letters, numbers, dots, underscores, or hyphens."
        )
    if not isinstance(password, str) or len(password) < MINIMUM_PASSWORD_LENGTH:
        raise ValueError(
            f"Password must contain at least {MINIMUM_PASSWORD_LENGTH} characters."
        )

    return (
        f"AI_PLATFORM_SECRET_KEY={secrets.token_urlsafe(48)}\n"
        f"AI_PLATFORM_ADMIN_USERNAME={username}\n"
        f"AI_PLATFORM_ADMIN_PASSWORD_HASH={generate_password_hash(password)}\n"
    )


def write_environment_file(path, content):
    """Create a new mode-0600 file and refuse to overwrite existing credentials."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except Exception:
        try:
            destination.unlink()
        except OSError:
            pass
        raise
    os.chmod(destination, 0o600)


def main():
    parser = argparse.ArgumentParser(
        description="Create the AI platform's root-readable security EnvironmentFile."
    )
    parser.add_argument("--username", required=True, help="Administrator username")
    parser.add_argument("--output", required=True, help="New environment file path")
    args = parser.parse_args()

    password = getpass.getpass("New administrator password: ")
    confirmation = getpass.getpass("Confirm administrator password: ")
    if password != confirmation:
        parser.error("Passwords do not match.")

    try:
        content = build_environment(args.username, password)
        write_environment_file(args.output, content)
    except (ValueError, FileExistsError) as error:
        parser.error(str(error))
    finally:
        password = ""
        confirmation = ""

    print(f"Security configuration written to {args.output}")


if __name__ == "__main__":
    main()
