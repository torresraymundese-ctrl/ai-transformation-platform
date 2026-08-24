"""One explicit Asia/Shanghai clock for content business timestamps."""

from datetime import datetime
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")
DB_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def as_shanghai(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("content timestamps must be timezone-aware")
    return value.astimezone(SHANGHAI).replace(microsecond=0)


def shanghai_now() -> datetime:
    return datetime.now(SHANGHAI).replace(microsecond=0)


def format_shanghai(value: datetime) -> str:
    return as_shanghai(value).strftime(DB_TIME_FORMAT)


def parse_shanghai(value: str) -> datetime:
    return datetime.strptime(value, DB_TIME_FORMAT).replace(tzinfo=SHANGHAI)
