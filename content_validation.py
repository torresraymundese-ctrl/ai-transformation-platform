"""Exact server validation for immutable content aggregates."""

from dataclasses import replace
import json
import re
from urllib.parse import urlsplit, urlunsplit

from content_contracts import ContentBlock, ContentDraft
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


def _require_text(value, maximum, code):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ContentValidationError(code)
    return value.strip()


def _valid_timestamp(value):
    if value is None:
        return True
    return bool(
        isinstance(value, str)
        and re.fullmatch(
            r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", value
        )
    )


def _normalize_https_url(value):
    normalized, error = normalize_source_url(value)
    if error or not normalized or urlsplit(normalized).scheme != "https":
        raise ContentValidationError("source_url_invalid")
    return normalized


def _safe_cta(value):
    if not isinstance(value, str) or not value:
        return False
    if any(ord(character) < 32 for character in value):
        return False
    if value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return True
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password and port in (None, 443)


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
    if not isinstance(block, ContentBlock) or block.block_type not in BLOCK_TYPES:
        raise ContentValidationError("block_type_invalid")
    if block.title is not None and (not isinstance(block.title, str) or len(block.title) > 120):
        raise ContentValidationError("block_title_invalid")
    body = str(sanitize_html(block.body_html or "")) if block.body_html is not None else None
    if body is not None and len(body.encode("utf-8")) > 20_000:
        raise ContentValidationError("block_body_too_large")
    settings = dict(block.settings)
    if _container_depth(settings) > 2:
        raise ContentValidationError("block_settings_too_deep")
    if frozenset(settings) != SETTINGS_KEYS[block.block_type]:
        raise ContentValidationError("block_settings_invalid")
    if len(json.dumps(settings, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > 2_000:
        raise ContentValidationError("block_settings_too_large")
    if block.block_type == "heading" and settings["level"] not in (2, 3, 4):
        raise ContentValidationError("block_settings_invalid")
    if block.block_type == "image_text":
        if settings["alignment"] not in {"left", "right"} or not isinstance(settings["alt_text"], str):
            raise ContentValidationError("block_settings_invalid")
    if block.block_type == "metric" and not all(isinstance(settings[key], str) and settings[key] for key in ("value", "unit")):
        raise ContentValidationError("block_settings_invalid")
    if block.block_type == "steps" and not (
        isinstance(settings["items"], tuple)
        and settings["items"]
        and all(isinstance(item, str) and item for item in settings["items"])
    ):
        raise ContentValidationError("block_settings_invalid")
    if block.block_type == "download" and not isinstance(settings["label"], str):
        raise ContentValidationError("block_settings_invalid")
    if block.block_type == "cta" and not (
        isinstance(settings["label"], str)
        and settings["label"]
        and settings["style"] in {"primary", "secondary", "text"}
        and _safe_cta(settings["url"])
    ):
        raise ContentValidationError("block_settings_invalid")
    if block.media_asset_id is not None and block.block_type not in {"image_text", "download"}:
        raise ContentValidationError("block_media_invalid")
    if not isinstance(block.sort_order, int) or block.sort_order < 0:
        raise ContentValidationError("block_order_invalid")
    return replace(block, body_html=body, sort_order=index)


def _validate_extension(draft):
    extension = dict(draft.extension)
    entry_type = draft.entry_type
    if entry_type in {"industry", "scenario", "service"}:
        key = f"{entry_type}_id"
        if frozenset(extension) != frozenset({key}) or not isinstance(extension[key], int) or extension[key] < 1:
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
        if extension["resource_type"] not in {"article", "guide", "report", "template", "policy"} or extension["is_original"] not in (0, 1):
            raise ContentValidationError("extension_invalid")
        if extension["is_original"] == 0:
            if not extension["source_name"]:
                raise ContentValidationError("source_required")
            extension["source_url"] = _normalize_https_url(extension["source_url"])
            import hashlib

            extension["source_url_sha256"] = hashlib.sha256(extension["source_url"].encode()).hexdigest()
        check = [
            extension["source_check_code"], extension["source_checked_at"],
            extension["source_check_expires_at"], extension["source_check_url_sha256"],
        ]
        if any(value is not None for value in check) and not all(value is not None for value in check):
            raise ContentValidationError("source_check_invalid")
    elif entry_type == "case":
        allowed = {
            "verification_code", "is_anonymized", "basis_type", "private_basis_reference",
            "source_url", "source_url_sha256", "source_check_code", "source_checked_at",
            "source_check_expires_at", "source_check_url_sha256", "is_verified",
            "review_confirmed", "verified_at",
        }
        if set(extension) != allowed:
            raise ContentValidationError("extension_invalid")
        if extension["basis_type"] == "public_source":
            extension["source_url"] = _normalize_https_url(extension["source_url"])
            import hashlib

            extension["source_url_sha256"] = hashlib.sha256(extension["source_url"].encode()).hexdigest()
        elif extension["basis_type"] != "private_authorization" or not extension["private_basis_reference"]:
            raise ContentValidationError("extension_invalid")
    return extension


def validate_content_draft(draft: ContentDraft) -> ContentDraft:
    if not isinstance(draft, ContentDraft) or draft.entry_type not in ENTRY_TYPES:
        raise ContentValidationError("entry_type_invalid")
    if not isinstance(draft.slug, str) or len(draft.slug) > 80 or not SLUG_PATTERN.fullmatch(draft.slug):
        raise ContentValidationError("slug_invalid")
    title = _require_text(draft.title, 120, "title_invalid")
    summary = _require_text(draft.summary, 300, "summary_invalid")
    seo_title = _require_text(draft.seo_title, 60, "seo_title_invalid")
    seo_description = _require_text(draft.seo_description, 160, "seo_description_invalid")
    if len(draft.blocks) > 40:
        raise ContentValidationError("too_many_blocks")
    if len(draft.relations) > 50:
        raise ContentValidationError("too_many_relations")
    blocks = tuple(_validate_block(block, index) for index, block in enumerate(draft.blocks))
    seen_relations = set()
    relations = []
    for index, relation in enumerate(draft.relations):
        if RELATION_OWNERS.get(relation.relation_type) != draft.entry_type:
            raise ContentValidationError("relation_type_invalid")
        if not isinstance(relation.target_group_id, int) or relation.target_group_id < 1:
            raise ContentValidationError("relation_target_invalid")
        key = (relation.relation_type, relation.target_group_id)
        if key in seen_relations:
            raise ContentValidationError("relation_duplicate")
        seen_relations.add(key)
        relations.append(replace(relation, sort_order=index))
    if draft.entry_type == "scenario":
        if len(set(draft.maturity_codes)) != len(draft.maturity_codes) or any(code not in MATURITY_CODES for code in draft.maturity_codes):
            raise ContentValidationError("maturity_invalid")
    elif draft.maturity_codes:
        raise ContentValidationError("maturity_invalid")
    extension = _validate_extension(draft)
    return replace(
        draft,
        title=title,
        summary=summary,
        seo_title=seo_title,
        seo_description=seo_description,
        extension=extension,
        blocks=blocks,
        relations=tuple(relations),
    )
