"""One immutable pagination contract shared by server-side list views."""

from dataclasses import dataclass
import unicodedata
from typing import Generic, Literal, TypeVar


T = TypeVar("T")
ALLOWED_PER_PAGE = (20, 50)
MAX_PAGE_NUMBER = 2_147_483_647


def _require_exact_int(value, field_name):
    if type(value) is not int:
        raise TypeError(f"{field_name} must be an exact integer")
    return value


@dataclass(frozen=True)
class Page(Generic[T]):
    items: tuple[T, ...]
    page: int
    per_page: int
    total: int
    total_pages: int

    def __post_init__(self):
        if type(self.items) is not tuple:
            raise TypeError("items must be a tuple")
        page = _require_exact_int(self.page, "page")
        per_page = _require_exact_int(self.per_page, "per_page")
        total = _require_exact_int(self.total, "total")
        total_pages = _require_exact_int(self.total_pages, "total_pages")
        if page < 1 or per_page not in ALLOWED_PER_PAGE or total < 0:
            raise ValueError("invalid page bounds")
        expected_pages = (total + per_page - 1) // per_page if total else 0
        if total_pages != expected_pages:
            raise ValueError("total_pages is inconsistent with total")
        if total == 0:
            if page != 1 or self.items:
                raise ValueError("empty pages must use the exact empty contract")
        elif page > total_pages:
            raise ValueError("page exceeds total_pages")
        if len(self.items) > per_page:
            raise ValueError("page contains too many items")


@dataclass(frozen=True)
class PageRequest:
    page: int
    per_page: Literal[20, 50]

    def __post_init__(self):
        page = _require_exact_int(self.page, "page")
        per_page = _require_exact_int(self.per_page, "per_page")
        if not 1 <= page <= MAX_PAGE_NUMBER:
            raise ValueError("page is out of bounds")
        if per_page not in ALLOWED_PER_PAGE:
            raise ValueError("unsupported per_page")


def _parse_positive_decimal(value, default):
    if type(value) is int:
        parsed = value
    elif type(value) is str and value and value.isascii() and value.isdecimal():
        try:
            parsed = int(value, 10)
        except ValueError:
            return default
    else:
        return default
    if not 1 <= parsed <= MAX_PAGE_NUMBER:
        return default
    return parsed


def parse_pagination(values) -> PageRequest:
    """Parse mapping-like query values with fail-closed, bounded defaults."""
    try:
        raw_page = values.get("page")
        raw_per_page = values.get("per_page")
    except (AttributeError, TypeError):
        raw_page = None
        raw_per_page = None
    page = _parse_positive_decimal(raw_page, 1)
    per_page = _parse_positive_decimal(raw_per_page, 20)
    if per_page not in ALLOWED_PER_PAGE:
        per_page = 20
    return PageRequest(page=page, per_page=per_page)


def parse_bounded_search(values, name="q", maximum=100):
    """Return normalized bounded search text, or the safe empty default."""
    try:
        raw = values.get(name)
    except (AttributeError, TypeError):
        return None
    if type(raw) is not str:
        return None
    value = unicodedata.normalize("NFKC", raw).strip()
    if not value or len(value) > maximum or any(ord(char) < 32 for char in value):
        return None
    return value
