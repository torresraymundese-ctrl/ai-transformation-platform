"""Authenticated HTTP adapter for core catalog narrative revisions."""

from dataclasses import dataclass
import re

from flask import abort, current_app, jsonify, redirect, render_template, request, session, url_for

from blueprints.admin import bp
import catalog_content_repository as catalog
from content_clock import shanghai_now
from content_contracts import ContentBlock, ContentDraft, ContentRelation
from content_validation import BLOCK_TYPES, MATURITY_CODES, ContentValidationError
from pagination import parse_pagination
from publishing_repository import (
    ContentConflictError,
    ContentNotFoundError,
    ContentStateError,
)


ACTIONS = frozenset({"save", "review", "publish", "archive"})
FIXED_FIELDS = frozenset(
    {
        "csrf_token",
        "content_id",
        "lock_version",
        "action",
        "title",
        "summary",
        "seo_title",
        "seo_description",
        "share_image_media_id",
        "maturity_codes",
    }
)
BLOCK_SUFFIXES = frozenset(
    {
        "type",
        "title",
        "body",
        "media_id",
        "heading_level",
        "image_alignment",
        "image_alt_text",
        "metric_value",
        "metric_unit",
        "steps_items",
        "download_label",
        "cta_label",
        "cta_url",
        "cta_style",
    }
)
BLOCK_FIELD = re.compile(r"^blocks-(0|[1-9][0-9]*)-([a-z_]+)$")
RELATION_FIELD = re.compile(
    r"^relations-(0|[1-9][0-9]*)-(type|target_group_id)$"
)
RELATION_TYPES = {
    "industry": frozenset({"industry_case", "industry_resource"}),
    "scenario": frozenset({"scenario_case", "scenario_resource"}),
    "service": frozenset({"service_case", "service_resource"}),
}
BLOCK_REQUIRED_SUFFIXES = {
    "heading": frozenset({"heading_level"}),
    "rich_text": frozenset(),
    "image_text": frozenset({"image_alignment", "image_alt_text"}),
    "metric": frozenset({"metric_value", "metric_unit"}),
    "steps": frozenset({"steps_items"}),
    "download": frozenset({"download_label"}),
    "cta": frozenset({"cta_label", "cta_url", "cta_style"}),
}


class CatalogFormError(ValueError):
    def __init__(self, code, field=None):
        self.code = code
        self.field = field
        super().__init__(code)


@dataclass(frozen=True)
class SubmittedRevision:
    id: int
    lock_version: int
    slug: str
    title: str
    summary: str
    seo_title: str
    seo_description: str
    share_image_media_id: int | None
    blocks: tuple[ContentBlock, ...]
    relations: tuple[ContentRelation, ...]
    maturity_codes: tuple[str, ...]


def _actor():
    return session.get("admin_username") or current_app.config["ADMIN_USERNAME"]


def _now():
    provider = current_app.config.get("ADMIN_NOW_PROVIDER")
    return provider() if callable(provider) else shanghai_now()


def _kind_or_404(kind):
    if kind not in catalog.KIND_CONFIG:
        abort(404)
    return kind


def _one(data, name, *, required=True):
    values = data.getlist(name)
    if len(values) != 1:
        if not values and not required:
            return ""
        raise CatalogFormError("field_invalid", name)
    return values[0]


def _positive_id(data, name, *, nullable=False):
    raw = _one(data, name, required=not nullable)
    if nullable and raw == "":
        return None
    if type(raw) is not str or not raw.isascii() or not raw.isdecimal():
        raise CatalogFormError("field_invalid", name)
    value = int(raw, 10)
    if value < 1 or value > 2_147_483_647:
        raise CatalogFormError("field_invalid", name)
    return value


def _validate_field_names(data):
    unknown = []
    for name in data.keys():
        if name in FIXED_FIELDS:
            continue
        block_match = BLOCK_FIELD.fullmatch(name)
        if block_match and block_match.group(2) in BLOCK_SUFFIXES:
            continue
        if RELATION_FIELD.fullmatch(name):
            continue
        unknown.append(name)
    if unknown:
        raise CatalogFormError("unknown_field", sorted(unknown)[0])


def _indexed_fields(data, pattern, maximum):
    indices = {
        int(match.group(1))
        for name in data.keys()
        if (match := pattern.fullmatch(name)) is not None
    }
    if not indices:
        return ()
    if len(indices) > maximum or indices != set(range(max(indices) + 1)):
        raise CatalogFormError("indexed_fields_invalid")
    return tuple(sorted(indices))


def _block_value(data, index, suffix, *, required=False):
    return _one(data, f"blocks-{index}-{suffix}", required=required)


def _parse_block(data, index):
    block_type = _block_value(data, index, "type", required=True)
    if block_type not in BLOCK_TYPES:
        raise CatalogFormError("block_type_invalid", f"blocks-{index}-type")
    provided_suffixes = {
        match.group(2)
        for name in data.keys()
        if (match := BLOCK_FIELD.fullmatch(name)) is not None
        and int(match.group(1)) == index
    }
    expected_suffixes = frozenset({"type", "title", "body", "media_id"}) | BLOCK_REQUIRED_SUFFIXES[block_type]
    if provided_suffixes != expected_suffixes:
        raise CatalogFormError("block_settings_invalid")
    title = _block_value(data, index, "title") or None
    body = _block_value(data, index, "body") or None
    media_id = _positive_id(data, f"blocks-{index}-media_id", nullable=True)
    settings = {}
    if block_type == "heading":
        level = _block_value(data, index, "heading_level", required=True)
        if level not in {"2", "3", "4"}:
            raise CatalogFormError("block_settings_invalid")
        settings = {"level": int(level)}
    elif block_type == "image_text":
        alignment = _block_value(data, index, "image_alignment", required=True)
        alt_text = _block_value(data, index, "image_alt_text", required=True)
        if alignment not in {"left", "right"} or not alt_text:
            raise CatalogFormError("block_settings_invalid")
        settings = {"alignment": alignment, "alt_text": alt_text}
    elif block_type == "metric":
        value = _block_value(data, index, "metric_value", required=True)
        unit = _block_value(data, index, "metric_unit", required=True)
        if not value or not unit:
            raise CatalogFormError("block_settings_invalid")
        settings = {"value": value, "unit": unit}
    elif block_type == "steps":
        raw_items = _block_value(data, index, "steps_items", required=True)
        items = tuple(line.strip() for line in raw_items.splitlines() if line.strip())
        if not items or len(items) > 20 or any(len(item) > 300 for item in items):
            raise CatalogFormError("block_settings_invalid")
        settings = {"items": items}
    elif block_type == "download":
        label = _block_value(data, index, "download_label", required=True)
        if not label or media_id is None:
            raise CatalogFormError("block_settings_invalid")
        settings = {"label": label}
    elif block_type == "cta":
        label = _block_value(data, index, "cta_label", required=True)
        target = _block_value(data, index, "cta_url", required=True)
        style = _block_value(data, index, "cta_style", required=True)
        if not label or not target or style not in {"primary", "secondary", "text"}:
            raise CatalogFormError("block_settings_invalid")
        settings = {"label": label, "url": target, "style": style}
    return ContentBlock(
        block_type=block_type,
        title=title,
        body_html=body,
        settings=settings,
        media_asset_id=media_id,
        sort_order=index,
    )


def _parse_relations(data, kind):
    relations = []
    for index in _indexed_fields(data, RELATION_FIELD, 50):
        relation_type = _one(data, f"relations-{index}-type")
        if relation_type not in RELATION_TYPES[kind]:
            raise CatalogFormError("relation_type_invalid")
        target_group_id = _positive_id(data, f"relations-{index}-target_group_id")
        relations.append(ContentRelation(relation_type, target_group_id, index))
    return tuple(relations)


def _parse_submission(data, view):
    _validate_field_names(data)
    action = _one(data, "action")
    if action not in ACTIONS:
        raise CatalogFormError("action_invalid", "action")
    content_id = _positive_id(data, "content_id")
    lock_version = _positive_id(data, "lock_version")
    if action == "archive":
        return action, content_id, lock_version, None
    maturity_codes = tuple(data.getlist("maturity_codes"))
    if view.kind == "scenario":
        if not maturity_codes or len(set(maturity_codes)) != len(maturity_codes):
            raise CatalogFormError("maturity_invalid")
        if any(code not in MATURITY_CODES for code in maturity_codes):
            raise CatalogFormError("maturity_invalid")
    elif maturity_codes:
        raise CatalogFormError("maturity_invalid")
    blocks = tuple(
        _parse_block(data, index)
        for index in _indexed_fields(data, BLOCK_FIELD, 40)
    )
    draft = ContentDraft(
        entry_type=view.kind,
        slug=view.slug,
        title=_one(data, "title"),
        summary=_one(data, "summary"),
        seo_title=_one(data, "seo_title"),
        seo_description=_one(data, "seo_description"),
        content_group_id=view.group_id,
        share_image_media_id=_positive_id(data, "share_image_media_id", nullable=True),
        extension={f"{view.kind}_id": view.core_id},
        blocks=blocks,
        relations=_parse_relations(data, view.kind),
        maturity_codes=maturity_codes,
    )
    return action, content_id, lock_version, draft


def _submitted(content_id, lock_version, draft):
    return SubmittedRevision(
        id=content_id,
        lock_version=lock_version,
        slug=draft.slug,
        title=draft.title,
        summary=draft.summary,
        seo_title=draft.seo_title,
        seo_description=draft.seo_description,
        share_image_media_id=draft.share_image_media_id,
        blocks=draft.blocks,
        relations=draft.relations,
        maturity_codes=draft.maturity_codes,
    )


def _form_error(error):
    payload = {"error": error.code}
    if error.field is not None:
        payload["field"] = error.field
    return jsonify(payload), 400


@bp.get("/admin/catalog/<kind>")
def admin_catalog(kind):
    kind = _kind_or_404(kind)
    page = catalog.get_catalog_page(kind, parse_pagination(request.args))
    return render_template("admin/catalog_list.html", kind=kind, page=page)


@bp.route("/admin/catalog/<kind>/<int:core_id>", methods=["GET", "POST"])
def admin_catalog_edit(kind, core_id):
    kind = _kind_or_404(kind)
    try:
        if request.method == "GET":
            view = catalog.ensure_editable_revision(
                kind, core_id, actor=_actor(), now=_now()
            )
            return render_template(
                "admin/catalog_edit.html",
                view=view,
                form=view.draft_revision,
                error=None,
            )

        view = catalog.get_editor(kind, core_id)
        action, content_id, lock_version, draft = _parse_submission(request.form, view)
        if action == "archive":
            catalog.archive_catalog_revision(
                kind,
                core_id,
                content_id,
                lock_version,
                actor=_actor(),
                now=_now(),
            )
        else:
            catalog.save_catalog_draft(
                kind,
                core_id,
                content_id,
                lock_version,
                draft,
                action=action,
                actor=_actor(),
                now=_now(),
            )
        return redirect(url_for("admin.admin_catalog_edit", kind=kind, core_id=core_id))
    except CatalogFormError as error:
        return _form_error(error)
    except ContentConflictError:
        view = catalog.get_editor(kind, core_id)
        if "draft" in locals() and draft is not None:
            form = _submitted(content_id, lock_version, draft)
        else:
            form = view.draft_revision
        return (
            render_template(
                "admin/catalog_edit.html",
                view=view,
                form=form,
                error="内容已被其他操作更新，请核对后重新提交。",
            ),
            409,
        )
    except ContentValidationError as error:
        return jsonify({"error": error.code}), 400
    except ContentStateError as error:
        return jsonify({"error": error.code}), 409
    except ContentNotFoundError:
        abort(404)
