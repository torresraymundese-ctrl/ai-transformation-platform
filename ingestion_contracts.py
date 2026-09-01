"""Immutable contracts for reviewed ingestion candidates."""

from dataclasses import dataclass
from datetime import datetime
import re


class IngestionContractError(ValueError):
    """Raised when ingestion input cannot be represented safely."""


SOURCE_CODE_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")


def require_source_code(value: str) -> str:
    if type(value) is not str or SOURCE_CODE_PATTERN.fullmatch(value) is None:
        raise IngestionContractError("source_code_invalid")
    return value


@dataclass(frozen=True)
class FetchedItem:
    source_code: str
    source_name: str
    url: str
    title: str
    summary: str
    body_html: str
    original_published_at: datetime | None

    def __post_init__(self):
        require_source_code(self.source_code)


@dataclass(frozen=True)
class IngestResult:
    created_ids: tuple[int, ...]
    deduplicated: int


@dataclass(frozen=True)
class IngestionCandidate:
    id: int
    source_code: str
    source_name: str
    canonical_url: str
    content_sha256: str
    title: str
    licensed_summary: str
    body_html: str | None
    original_published_at: datetime | None
    state: str
    rejection_code: str | None
    rejection_note: str | None
    lock_version: int
    target_content_id: int | None
    created_at: datetime
    updated_at: datetime
