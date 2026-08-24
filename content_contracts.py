"""Immutable contracts shared by content validation and publishing."""

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class ContentBlock:
    block_type: str
    title: str | None = None
    body_html: str | None = None
    settings: Mapping[str, Any] = field(default_factory=dict)
    media_asset_id: int | None = None
    sort_order: int = 0

    def __post_init__(self):
        object.__setattr__(self, "settings", _freeze(self.settings))


@dataclass(frozen=True)
class ContentRelation:
    relation_type: str
    target_group_id: int
    sort_order: int = 0


@dataclass(frozen=True)
class CaseMetric:
    name: str
    before_value: str
    after_value: str
    unit: str
    statistical_period: str
    evidence_explanation: str
    sort_order: int = 0


@dataclass(frozen=True)
class ContentDraft:
    entry_type: str
    slug: str
    title: str
    summary: str
    seo_title: str
    seo_description: str
    content_group_id: int | None = None
    share_image_media_id: int | None = None
    publish_at: str | None = None
    extension: Mapping[str, Any] = field(default_factory=dict)
    blocks: tuple[ContentBlock, ...] = ()
    relations: tuple[ContentRelation, ...] = ()
    maturity_codes: tuple[str, ...] = ()
    metrics: tuple[CaseMetric, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "extension", _freeze(self.extension))
        object.__setattr__(self, "blocks", tuple(_freeze(self.blocks)))
        object.__setattr__(self, "relations", tuple(_freeze(self.relations)))
        object.__setattr__(self, "maturity_codes", tuple(self.maturity_codes))
        object.__setattr__(self, "metrics", tuple(_freeze(self.metrics)))


@dataclass(frozen=True)
class SourceCheckResult:
    ok: bool
    code: str
    normalized_url: str
    source_url_sha256: str
    source_check_url_sha256: str
    checked_at: str
    expires_at: str


@dataclass(frozen=True)
class PublishResult:
    published_id: int
    archived_id: int | None


@dataclass(frozen=True)
class ScheduleResult:
    content_id: int
    publish_at: str
    lock_version: int


@dataclass(frozen=True)
class PublishDueResult:
    published_ids: tuple[int, ...]
    failures: tuple[tuple[int, str], ...]

    @property
    def published_count(self):
        return len(self.published_ids)

    @property
    def failed_count(self):
        return len(self.failures)


@dataclass(frozen=True)
class PublicRevisionResolution:
    revision: Any
    canonical_slug: str
    redirect: bool
