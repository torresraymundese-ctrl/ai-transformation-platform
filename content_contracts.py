"""Immutable contracts shared by content validation and publishing."""

from dataclasses import dataclass, field
import math
from types import MappingProxyType
from typing import Any, Mapping


class ContentContractError(ValueError):
    """Raised when a contract would retain unsafe or mutable input."""


MAX_JSON_DEPTH = 64


def _freeze_json(value, *, _depth=0, _active=None):
    if _depth > MAX_JSON_DEPTH:
        raise ContentContractError("content contract JSON is too deep")
    if _active is None:
        _active = set()
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in _active:
            raise ContentContractError("content contract JSON must not be cyclic")
        _active.add(identity)
        try:
            frozen = {}
            for key, item in value.items():
                if type(key) is not str:
                    raise ContentContractError("JSON object keys must be strings")
                frozen[key] = _freeze_json(
                    item, _depth=_depth + 1, _active=_active
                )
            return MappingProxyType(frozen)
        finally:
            _active.remove(identity)
    if isinstance(value, (list, tuple)):
        identity = id(value)
        if identity in _active:
            raise ContentContractError("content contract JSON must not be cyclic")
        _active.add(identity)
        try:
            return tuple(
                _freeze_json(item, _depth=_depth + 1, _active=_active)
                for item in value
            )
        finally:
            _active.remove(identity)
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ContentContractError("content contract values must be finite JSON data")


def _contract_sequence(value, expected_type, field_name):
    if not isinstance(value, (list, tuple)) or any(
        type(item) is not expected_type for item in value
    ):
        raise ContentContractError(
            f"{field_name} must contain only {expected_type.__name__} values"
        )
    return tuple(value)


@dataclass(frozen=True)
class ContentBlock:
    block_type: str
    title: str | None = None
    body_html: str | None = None
    settings: Mapping[str, Any] = field(default_factory=dict)
    media_asset_id: int | None = None
    sort_order: int = 0

    def __post_init__(self):
        if isinstance(self.settings, Mapping):
            object.__setattr__(self, "settings", _freeze_json(self.settings))
        else:
            # Keep the invalid shape immutable so server validation can return one code.
            object.__setattr__(self, "settings", None)


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
        if not isinstance(self.extension, Mapping):
            raise ContentContractError("extension must be a JSON mapping")
        object.__setattr__(self, "extension", _freeze_json(self.extension))
        object.__setattr__(
            self, "blocks", _contract_sequence(self.blocks, ContentBlock, "blocks")
        )
        object.__setattr__(
            self,
            "relations",
            _contract_sequence(self.relations, ContentRelation, "relations"),
        )
        if not isinstance(self.maturity_codes, (list, tuple)) or any(
            type(code) is not str for code in self.maturity_codes
        ):
            raise ContentContractError("maturity_codes must contain only strings")
        object.__setattr__(self, "maturity_codes", tuple(self.maturity_codes))
        object.__setattr__(
            self, "metrics", _contract_sequence(self.metrics, CaseMetric, "metrics")
        )


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
