"""Exact server validation for immutable content aggregates."""

from dataclasses import replace
import json
import re
from collections.abc import Mapping
import unicodedata
from urllib.parse import urlsplit, urlunsplit

from content_clock import parse_shanghai
from content_contracts import CaseMetric, ContentBlock, ContentDraft, ContentRelation
from security import sanitize_html
from source_url_checker import normalize_source_url


ENTRY_TYPES = frozenset({"industry", "scenario", "service", "case", "resource", "announcement"})
MATURITY_CODES = frozenset({"explore", "pilot", "scale", "collaborate"})
BLOCK_TYPES = frozenset({"heading", "rich_text", "image_text", "metric", "steps", "download", "cta"})
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RELATION_OWNERS = {
    "industry_case": "industry",
    "industry_resource": "industry",
    "scenario_case": "scenario",
    "scenario_resource": "scenario",
    "service_case": "service",
    "service_resource": "service",
}
MAX_CASE_METRICS = 20
SETTINGS_KEYS = {
    "heading": frozenset({"level"}),
    "rich_text": frozenset(),
    "image_text": frozenset({"alignment", "alt_text"}),
    "metric": frozenset({"value", "unit"}),
    "steps": frozenset({"items"}),
    "download": frozenset({"label"}),
    "cta": frozenset({"label", "url", "style"}),
}


class ContentValidationError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def is_exact_nonblank_text(value, *, maximum=None):
    """Return whether a persisted public text value has the exact safe shape."""
    return (
        type(value) is str
        and "\x00" not in value
        and bool(value.strip())
        and (maximum is None or len(value) <= maximum)
    )


def public_input_texts(rows):
    """Return stable public inputs, or None when any persisted row is malformed."""
    values = []
    previous_order = 0
    seen_orders = set()
    for row in rows:
        input_text = row["input_text"]
        sort_order = row["sort_order"]
        if (
            not is_exact_nonblank_text(input_text, maximum=300)
            or type(sort_order) is not int
            or sort_order < 1
            or sort_order in seen_orders
            or sort_order <= previous_order
        ):
            return None
        values.append(input_text)
        seen_orders.add(sort_order)
        previous_order = sort_order
    return tuple(values) if values else None


def _require_text(value, maximum, code):
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise ContentValidationError(code)
    return value.strip()


def _valid_id(value, *, nullable=True):
    return (nullable and value is None) or (type(value) is int and value >= 1)


def _valid_optional_text(value, maximum):
    return value is None or (
        type(value) is str and 1 <= len(value) <= maximum
    )


def _valid_sha256(value):
    return value is None or (
        type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None
    )


def _valid_flag(value):
    return type(value) is int and value in (0, 1)


def _valid_timestamp(value):
    if value is None:
        return True
    if not (
        type(value) is str
        and re.fullmatch(
            r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", value
        )
    ):
        return False
    try:
        parse_shanghai(value)
    except ValueError:
        return False
    return True


def _normalize_https_url(value):
    normalized, error = normalize_source_url(value)
    if error or not normalized or urlsplit(normalized).scheme != "https":
        raise ContentValidationError("source_url_invalid")
    return normalized


def _safe_cta(value):
    if not isinstance(value, str) or not value:
        return False
    if (
        "\\" in value
        or any(unicodedata.category(character).startswith("C") for character in value)
        or re.search(r"%(?![0-9A-Fa-f]{2})", value)
    ):
        return False
    if value.startswith("/") and not value.startswith("//"):
        return True
    normalized, error = normalize_source_url(value)
    if error or not normalized:
        return False
    return urlsplit(normalized).scheme == "https"


def _container_depth(value, depth=0):
    if isinstance(value, dict) or hasattr(value, "items"):
        if not value:
            return depth
        return max(_container_depth(item, depth + 1) for item in value.values())
    if isinstance(value, (tuple, list)):
        if not value:
            return depth
        return max(_container_depth(item, depth + 1) for item in value)
    return depth


def _validate_block(block, index):
    if (
        type(block) is not ContentBlock
        or type(block.block_type) is not str
        or block.block_type not in BLOCK_TYPES
    ):
        raise ContentValidationError("block_type_invalid")
    if block.title is not None and (
        type(block.title) is not str or len(block.title) > 120
    ):
        raise ContentValidationError("block_title_invalid")
    if block.body_html is not None and type(block.body_html) is not str:
        raise ContentValidationError("block_body_invalid")
    body = str(sanitize_html(block.body_html or "")) if block.body_html is not None else None
    if body is not None and len(body.encode("utf-8")) > 20_000:
        raise ContentValidationError("block_body_too_large")
    if not isinstance(block.settings, Mapping):
        raise ContentValidationError("block_settings_invalid")
    settings = dict(block.settings)
    if _container_depth(settings) > 2:
        raise ContentValidationError("block_settings_too_deep")
    if frozenset(settings) != SETTINGS_KEYS[block.block_type]:
        raise ContentValidationError("block_settings_invalid")
    if len(json.dumps(settings, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > 2_000:
        raise ContentValidationError("block_settings_too_large")
    if block.block_type == "heading" and (
        type(settings["level"]) is not int or settings["level"] not in (2, 3, 4)
    ):
        raise ContentValidationError("block_settings_invalid")
    if block.block_type == "image_text":
        if (
            type(settings["alignment"]) is not str
            or settings["alignment"] not in {"left", "right"}
            or type(settings["alt_text"]) is not str
        ):
            raise ContentValidationError("block_settings_invalid")
    if block.block_type == "metric" and not all(
        type(settings[key]) is str and settings[key] for key in ("value", "unit")
    ):
        raise ContentValidationError("block_settings_invalid")
    if block.block_type == "steps" and not (
        isinstance(settings["items"], tuple)
        and settings["items"]
        and all(type(item) is str and item for item in settings["items"])
    ):
        raise ContentValidationError("block_settings_invalid")
    if block.block_type == "download" and not (
        type(settings["label"]) is str and settings["label"]
    ):
        raise ContentValidationError("block_settings_invalid")
    if block.block_type == "cta" and not (
        type(settings["label"]) is str
        and settings["label"]
        and type(settings["style"]) is str
        and settings["style"] in {"primary", "secondary", "text"}
        and _safe_cta(settings["url"])
    ):
        raise ContentValidationError("block_settings_invalid")
    if not _valid_id(block.media_asset_id):
        raise ContentValidationError("block_media_invalid")
    if block.media_asset_id is not None and block.block_type not in {"image_text", "download"}:
        raise ContentValidationError("block_media_invalid")
    if type(block.sort_order) is not int or block.sort_order < 0:
        raise ContentValidationError("block_order_invalid")
    return replace(block, body_html=body, sort_order=index)


def _validate_extension(draft):
    extension = dict(draft.extension)
    entry_type = draft.entry_type
    if entry_type in {"industry", "scenario", "service"}:
        key = f"{entry_type}_id"
        if frozenset(extension) != frozenset({key}) or not _valid_id(
            extension[key], nullable=False
        ):
            raise ContentValidationError("extension_invalid")
    elif entry_type == "announcement":
        allowed = {"valid_from", "valid_until", "cta_url"}
        if set(extension) != allowed or not all(_valid_timestamp(extension[key]) for key in ("valid_from", "valid_until")):
            raise ContentValidationError("extension_invalid")
        if extension["valid_from"] and extension["valid_until"] and extension["valid_from"] > extension["valid_until"]:
            raise ContentValidationError("extension_invalid")
        if extension["cta_url"] is not None and not _safe_cta(extension["cta_url"]):
            raise ContentValidationError("extension_invalid")
    elif entry_type == "resource":
        allowed = {
            "resource_type", "is_original", "source_name", "source_url", "source_url_sha256",
            "source_check_code", "source_checked_at", "source_check_expires_at",
            "source_check_url_sha256", "original_published_at", "copyright_notice",
            "attachment_media_id",
        }
        if not set(extension).issubset(allowed):
            raise ContentValidationError("extension_invalid")
        defaults = {key: None for key in allowed}
        defaults.update(extension)
        extension = defaults
        if (
            type(extension["resource_type"]) is not str
            or extension["resource_type"]
            not in {"article", "guide", "report", "template", "policy"}
            or not _valid_flag(extension["is_original"])
            or not _valid_optional_text(extension["source_name"], 200)
            or not _valid_optional_text(extension["copyright_notice"], 500)
            or not _valid_id(extension["attachment_media_id"])
            or not _valid_sha256(extension["source_url_sha256"])
            or not _valid_optional_text(extension["source_check_code"], 64)
            or not _valid_sha256(extension["source_check_url_sha256"])
        ):
            raise ContentValidationError("extension_invalid")
        if extension["is_original"] == 0:
            if extension["source_name"] is None:
                raise ContentValidationError("source_required")
            extension["source_url"] = _normalize_https_url(extension["source_url"])
            import hashlib

            extension["source_url_sha256"] = hashlib.sha256(extension["source_url"].encode()).hexdigest()
        elif extension["source_url"] is not None:
            extension["source_url"] = _normalize_https_url(extension["source_url"])
            import hashlib

            extension["source_url_sha256"] = hashlib.sha256(
                extension["source_url"].encode()
            ).hexdigest()
        elif extension["source_url_sha256"] is not None:
            raise ContentValidationError("extension_invalid")
        check = [
            extension["source_check_code"], extension["source_checked_at"],
            extension["source_check_expires_at"], extension["source_check_url_sha256"],
        ]
        if any(value is not None for value in check) and not all(value is not None for value in check):
            raise ContentValidationError("source_check_invalid")
        if not all(
            _valid_timestamp(value)
            for value in (
                extension["source_checked_at"],
                extension["source_check_expires_at"],
                extension["original_published_at"],
            )
        ):
            raise ContentValidationError("extension_invalid")
    elif entry_type == "case":
        allowed = {
            "verification_code", "is_anonymized", "basis_type", "private_basis_reference",
            "source_url", "source_url_sha256", "source_check_code", "source_checked_at",
            "source_check_expires_at", "source_check_url_sha256", "is_verified",
            "review_confirmed", "verified_at",
        }
        if set(extension) != allowed:
            raise ContentValidationError("extension_invalid")
        if (
            not _valid_optional_text(extension["verification_code"], 64)
            or extension["verification_code"] is None
            or not _valid_flag(extension["is_anonymized"])
            or type(extension["basis_type"]) is not str
            or extension["basis_type"] not in {"public_source", "private_authorization"}
            or not _valid_optional_text(extension["private_basis_reference"], 300)
            or not _valid_sha256(extension["source_url_sha256"])
            or not _valid_optional_text(extension["source_check_code"], 64)
            or not _valid_sha256(extension["source_check_url_sha256"])
            or not _valid_flag(extension["is_verified"])
            or not _valid_flag(extension["review_confirmed"])
        ):
            raise ContentValidationError("extension_invalid")
        if extension["basis_type"] == "public_source":
            extension["source_url"] = _normalize_https_url(extension["source_url"])
            import hashlib

            extension["source_url_sha256"] = hashlib.sha256(extension["source_url"].encode()).hexdigest()
        elif extension["private_basis_reference"] is None:
            raise ContentValidationError("extension_invalid")
        elif extension["source_url"] is not None:
            extension["source_url"] = _normalize_https_url(extension["source_url"])
            import hashlib

            extension["source_url_sha256"] = hashlib.sha256(
                extension["source_url"].encode()
            ).hexdigest()
        elif extension["source_url_sha256"] is not None:
            raise ContentValidationError("extension_invalid")
        check = [
            extension["source_check_code"],
            extension["source_checked_at"],
            extension["source_check_expires_at"],
            extension["source_check_url_sha256"],
        ]
        if any(value is not None for value in check) and not all(
            value is not None for value in check
        ):
            raise ContentValidationError("source_check_invalid")
        if not all(
            _valid_timestamp(value)
            for value in (
                extension["source_checked_at"],
                extension["source_check_expires_at"],
                extension["verified_at"],
            )
        ):
            raise ContentValidationError("extension_invalid")
    return extension


def _metric_text(value, maximum, code):
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise ContentValidationError(code)
    return value.strip()


def _validate_metrics(draft):
    if draft.entry_type != "case":
        if draft.metrics:
            raise ContentValidationError("metrics_not_allowed")
        return ()
    if len(draft.metrics) > MAX_CASE_METRICS:
        raise ContentValidationError("too_many_metrics")
    validated = []
    for index, metric in enumerate(draft.metrics):
        if type(metric) is not CaseMetric:
            raise ContentValidationError("metric_invalid")
        if type(metric.sort_order) is not int or metric.sort_order < 0:
            raise ContentValidationError("metric_order_invalid")
        validated.append(
            replace(
                metric,
                name=_metric_text(metric.name, 120, "metric_name_invalid"),
                before_value=_metric_text(
                    metric.before_value, 120, "metric_before_invalid"
                ),
                after_value=_metric_text(
                    metric.after_value, 120, "metric_after_invalid"
                ),
                unit=_metric_text(metric.unit, 40, "metric_unit_invalid"),
                statistical_period=_metric_text(
                    metric.statistical_period, 120, "metric_period_invalid"
                ),
                evidence_explanation=_metric_text(
                    metric.evidence_explanation, 1000, "metric_evidence_invalid"
                ),
                sort_order=index,
            )
        )
    return tuple(validated)


def validate_content_draft(draft: ContentDraft) -> ContentDraft:
    if (
        not isinstance(draft, ContentDraft)
        or type(draft.entry_type) is not str
        or draft.entry_type not in ENTRY_TYPES
    ):
        raise ContentValidationError("entry_type_invalid")
    if type(draft.slug) is not str or len(draft.slug) > 80 or not SLUG_PATTERN.fullmatch(draft.slug):
        raise ContentValidationError("slug_invalid")
    title = _require_text(draft.title, 120, "title_invalid")
    summary = _require_text(draft.summary, 300, "summary_invalid")
    seo_title = _require_text(draft.seo_title, 60, "seo_title_invalid")
    seo_description = _require_text(draft.seo_description, 160, "seo_description_invalid")
    if not _valid_id(draft.content_group_id):
        raise ContentValidationError("content_group_id_invalid")
    if not _valid_id(draft.share_image_media_id):
        raise ContentValidationError("share_image_media_invalid")
    if draft.publish_at is not None and not _valid_timestamp(draft.publish_at):
        raise ContentValidationError("publish_at_invalid")
    if len(draft.blocks) > 40:
        raise ContentValidationError("too_many_blocks")
    if len(draft.relations) > 50:
        raise ContentValidationError("too_many_relations")
    blocks = tuple(_validate_block(block, index) for index, block in enumerate(draft.blocks))
    seen_relations = set()
    relations = []
    for index, relation in enumerate(draft.relations):
        if (
            type(relation) is not ContentRelation
            or type(relation.relation_type) is not str
            or RELATION_OWNERS.get(relation.relation_type) != draft.entry_type
        ):
            raise ContentValidationError("relation_type_invalid")
        if not _valid_id(relation.target_group_id, nullable=False):
            raise ContentValidationError("relation_target_invalid")
        if type(relation.sort_order) is not int or relation.sort_order < 0:
            raise ContentValidationError("relation_order_invalid")
        key = (relation.relation_type, relation.target_group_id)
        if key in seen_relations:
            raise ContentValidationError("relation_duplicate")
        seen_relations.add(key)
        relations.append(replace(relation, sort_order=index))
    if draft.entry_type == "scenario":
        if len(set(draft.maturity_codes)) != len(draft.maturity_codes) or any(
            type(code) is not str or code not in MATURITY_CODES
            for code in draft.maturity_codes
        ):
            raise ContentValidationError("maturity_invalid")
    elif draft.maturity_codes:
        raise ContentValidationError("maturity_invalid")
    extension = _validate_extension(draft)
    metrics = _validate_metrics(draft)
    return replace(
        draft,
        title=title,
        summary=summary,
        seo_title=seo_title,
        seo_description=seo_description,
        extension=extension,
        blocks=blocks,
        relations=tuple(relations),
        metrics=metrics,
    )
