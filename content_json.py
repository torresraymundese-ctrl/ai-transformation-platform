"""Bounded decoding for JSON persisted in governed content rows."""

import json


MAX_DATABASE_JSON_CHARS = 16_384
MAX_DATABASE_JSON_DEPTH = 32


class ContentJsonError(ValueError):
    """Raised when persisted JSON is not a bounded text JSON document."""


def _container_depth(value):
    maximum = 0
    pending = [(value, 0)]
    while pending:
        current, depth = pending.pop()
        maximum = max(maximum, depth)
        if type(current) is str:
            try:
                current.encode("utf-8")
            except UnicodeEncodeError as error:
                raise ContentJsonError("content_json_invalid") from error
        elif type(current) is dict:
            for key, child in current.items():
                pending.append((key, depth + 1))
                pending.append((child, depth + 1))
        elif type(current) is list:
            pending.extend((child, depth + 1) for child in current)
    return maximum


def decode_database_json(value):
    """Decode exact text JSON from storage without accepting binary SQLite values."""
    if type(value) is not str or len(value) > MAX_DATABASE_JSON_CHARS:
        raise ContentJsonError("content_json_invalid")
    try:
        decoded = json.loads(value)
    except (ValueError, json.JSONDecodeError, RecursionError) as error:
        raise ContentJsonError("content_json_invalid") from error
    if _container_depth(decoded) > MAX_DATABASE_JSON_DEPTH:
        raise ContentJsonError("content_json_invalid")
    return decoded
