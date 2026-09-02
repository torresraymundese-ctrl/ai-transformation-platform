"""Authenticated HTTP adapters for reviewed resources and announcements."""

from dataclasses import replace
import re

from flask import abort, current_app, jsonify, redirect, render_template, request, session, url_for

from blueprints.admin import bp
from blueprints.admin.catalog import (
    BLOCK_FIELD,
    BLOCK_SUFFIXES,
    CatalogFormError,
    _indexed_fields,
    _one,
    _parse_block,
    _positive_id,
)
from content_clock import format_shanghai, parse_shanghai, shanghai_now
from content_contracts import ContentDraft
from content_validation import ContentValidationError
from pagination import parse_pagination
from publishing_repository import (
    ContentConflictError,
    ContentNotFoundError,
    ContentStateError,
)
import resource_repository as resources
from source_url_checker import PinnedHttpTransport


ACTIONS = frozenset({"save", "review", "publish", "archive"})
COMMON_FIELDS = frozenset(
    {
        "csrf_token", "action", "content_id", "lock_version", "slug", "title",
        "summary", "seo_title", "seo_description", "share_image_media_id",
        "review_confirmed", "media_review_confirmed",
    }
)
RESOURCE_FIELDS = frozenset(
    {
        "resource_type", "is_original", "source_name", "source_url",
        "original_published_at", "copyright_notice", "attachment_media_id",
    }
)
ANNOUNCEMENT_FIELDS = frozenset({"valid_from", "valid_until", "cta_url"})
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
LOCAL_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?$")


def _actor():
    return session.get("admin_username") or current_app.config["ADMIN_USERNAME"]


def _now():
    provider = current_app.config.get("ADMIN_NOW_PROVIDER")
    return provider() if callable(provider) else shanghai_now()


def _validate_names(data, entry_type):
    fixed = COMMON_FIELDS | (
        RESOURCE_FIELDS if entry_type == "resource" else ANNOUNCEMENT_FIELDS
    )
    for name in data.keys():
        if name in fixed:
            continue
        block = BLOCK_FIELD.fullmatch(name)
        if block is not None and block.group(2) in BLOCK_SUFFIXES:
            continue
        raise CatalogFormError("unknown_field", name)


def _exact_flag(data, name):
    raw = _one(data, name)
    if raw not in {"0", "1"}:
        raise CatalogFormError("field_invalid", name)
    return int(raw)


def _confirmation(data, name):
    raw = _one(data, name, required=False)
    if raw not in {"", "1"}:
        raise CatalogFormError("field_invalid", name)
    return raw == "1"


def _local_timestamp(data, name):
    raw = _one(data, name)
    if LOCAL_TIME_RE.fullmatch(raw) is None:
        raise CatalogFormError("field_invalid", name)
    value = raw.replace("T", " ")
    if len(value) == 16:
        value += ":00"
    try:
        return format_shanghai(parse_shanghai(value))
    except ValueError as error:
        raise CatalogFormError("field_invalid", name) from error


def _parse_submission(data, entry_type, *, content_id=None):
    _validate_names(data, entry_type)
    action = _one(data, "action")
    if action not in ACTIONS:
        raise CatalogFormError("action_invalid", "action")
    if action == "archive":
        allowed = {"csrf_token", "action", "content_id", "lock_version"}
        if set(data.keys()) != allowed:
            raise CatalogFormError("unknown_field")
        supplied_id = _positive_id(data, "content_id")
        if content_id is None or supplied_id != content_id:
            raise CatalogFormError("content_identity_invalid")
        return action, supplied_id, _positive_id(data, "lock_version"), None
    supplied_id = _positive_id(data, "content_id") if content_id is not None else None
    lock_version = _positive_id(data, "lock_version") if content_id is not None else None
    if content_id is not None and supplied_id != content_id:
        raise CatalogFormError("content_identity_invalid")
    review = _confirmation(data, "review_confirmed")
    media_review = _confirmation(data, "media_review_confirmed")
    if action in {"review", "publish"} and not (review and media_review):
        raise CatalogFormError("review_confirmation_required")
    blocks = tuple(
        _parse_block(data, index)
        for index in _indexed_fields(data, BLOCK_FIELD, 40)
    )
    extension = None
    if entry_type == "resource":
        extension = {
            "resource_type": _one(data, "resource_type"),
            "is_original": _exact_flag(data, "is_original"),
            "source_name": _one(data, "source_name", required=False) or None,
            "source_url": _one(data, "source_url", required=False) or None,
            "source_url_sha256": None,
            "source_check_code": None,
            "source_checked_at": None,
            "source_check_expires_at": None,
            "source_check_url_sha256": None,
            "original_published_at": _local_timestamp(data, "original_published_at"),
            "copyright_notice": _one(data, "copyright_notice"),
            "attachment_media_id": _positive_id(
                data, "attachment_media_id", nullable=True
            ),
        }
    else:
        extension = {
            "valid_from": _local_timestamp(data, "valid_from"),
            "valid_until": _local_timestamp(data, "valid_until"),
            "cta_url": _one(data, "cta_url", required=False) or None,
        }
    draft = ContentDraft(
        entry_type=entry_type,
        slug=_one(data, "slug"),
        title=_one(data, "title"),
        summary=_one(data, "summary"),
        seo_title=_one(data, "seo_title"),
        seo_description=_one(data, "seo_description"),
        share_image_media_id=_positive_id(
            data, "share_image_media_id", nullable=True
        ),
        extension=extension,
        blocks=blocks,
    )
    return action, supplied_id, lock_version, draft


def _json_error(error):
    payload = {"error": error.code}
    if getattr(error, "field", None) is not None:
        payload["field"] = error.field
    return jsonify(payload), 400


def _template(entry_type):
    return (
        "admin/resource_edit_v2.html"
        if entry_type == "resource"
        else "admin/announcement_edit_v2.html"
    )


def _list(entry_type):
    filters = resources.parse_admin_entry_filters(request.args)
    return render_template(
        "admin/resource_list_v2.html",
        page=resources.admin_entries(
            entry_type, parse_pagination(request.args), filters
        ),
        entry_type=entry_type,
        filters=filters,
    )


def _new(entry_type):
    draft = None
    try:
        if request.method == "GET":
            return render_template(
                _template(entry_type),
                view=resources.get_editor(entry_type),
                error=None,
                resource_types=resources.RESOURCE_TYPE_LABELS,
            )
        instant = _now()
        action, _, _, draft = _parse_submission(request.form, entry_type)
        result = resources.create_entry(
            draft, action=action, actor=_actor(), now=instant
        )
        endpoint = (
            "admin.admin_resource_edit_v2"
            if entry_type == "resource"
            else "admin.admin_announcement_edit_v2"
        )
        return redirect(url_for(endpoint, content_id=result.content_id))
    except CatalogFormError as error:
        return _json_error(error)
    except ContentConflictError as error:
        return jsonify({"error": error.code}), 409
    except ContentValidationError as error:
        return jsonify({"error": error.code}), 400


def _edit(entry_type, content_id):
    draft = None
    try:
        if request.method == "GET":
            editable_id = resources.editable_revision(content_id, entry_type)
            if editable_id is not None and editable_id != content_id:
                endpoint = (
                    "admin.admin_resource_edit_v2"
                    if entry_type == "resource"
                    else "admin.admin_announcement_edit_v2"
                )
                return redirect(url_for(endpoint, content_id=editable_id))
            return render_template(
                _template(entry_type),
                view=resources.get_editor(entry_type, content_id),
                error=None,
                resource_types=resources.RESOURCE_TYPE_LABELS,
            )
        instant = _now()
        action, supplied_id, lock_version, draft = _parse_submission(
            request.form, entry_type, content_id=content_id
        )
        if action == "archive":
            resources.archive_entry(
                supplied_id, lock_version, entry_type, actor=_actor(), now=instant
            )
        else:
            current = resources.get_editor(entry_type, content_id).form
            draft = replace(draft, content_group_id=current.content_group_id)
            resources.save_entry(
                content_id,
                lock_version,
                draft,
                action=action,
                actor=_actor(),
                now=instant,
            )
        endpoint = (
            "admin.admin_resource_edit_v2"
            if entry_type == "resource"
            else "admin.admin_announcement_edit_v2"
        )
        return redirect(url_for(endpoint, content_id=content_id))
    except CatalogFormError as error:
        return _json_error(error)
    except ContentConflictError:
        if draft is None:
            return jsonify({"error": "stale_lock_version"}), 409
        submitted = (
            resources.submitted_resource_form(draft, content_id, lock_version)
            if entry_type == "resource"
            else resources.submitted_announcement_form(draft, content_id, lock_version)
        )
        return (
            render_template(
                _template(entry_type),
                view=resources.get_editor(entry_type, content_id, form=submitted),
                error="内容已被其他操作更新，请核对后重新提交。",
                resource_types=resources.RESOURCE_TYPE_LABELS,
            ),
            409,
        )
    except ContentValidationError as error:
        return jsonify({"error": error.code}), 400
    except ContentStateError as error:
        return jsonify({"error": error.code}), 409
    except ContentNotFoundError:
        abort(404)


def _copy(entry_type, content_id):
    try:
        if set(request.form.keys()) != {
            "csrf_token", "content_id", "expected_lock_version"
        }:
            raise CatalogFormError("unknown_field")
        supplied_id = _positive_id(request.form, "content_id")
        if supplied_id != content_id:
            raise CatalogFormError("content_identity_invalid")
        copied_id = resources.copy_revision(
            content_id,
            _positive_id(request.form, "expected_lock_version"),
            entry_type,
            actor=_actor(),
            now=_now(),
        )
        endpoint = (
            "admin.admin_resource_edit_v2"
            if entry_type == "resource"
            else "admin.admin_announcement_edit_v2"
        )
        return redirect(url_for(endpoint, content_id=copied_id))
    except CatalogFormError as error:
        return _json_error(error)
    except ContentConflictError as error:
        return jsonify({"error": error.code}), 409
    except ContentStateError as error:
        return jsonify({"error": error.code}), 409
    except ContentNotFoundError:
        abort(404)


@bp.get("/admin/resources")
def admin_resources_v2():
    return _list("resource")


@bp.route("/admin/resources/new", methods=["GET", "POST"])
def admin_resource_new_v2():
    return _new("resource")


@bp.route("/admin/resources/<int:content_id>", methods=["GET", "POST"])
def admin_resource_edit_v2(content_id):
    return _edit("resource", content_id)


@bp.post("/admin/resources/<int:content_id>/copy")
def admin_resource_copy_v2(content_id):
    return _copy("resource", content_id)


@bp.post("/admin/resources/<int:content_id>/source-check")
def admin_resource_source_check_v2(content_id):
    try:
        if set(request.form.keys()) != {
            "csrf_token", "expected_lock_version", "expected_url_sha256"
        }:
            raise CatalogFormError("unknown_field")
        expected_hash = _one(request.form, "expected_url_sha256")
        if HASH_RE.fullmatch(expected_hash) is None:
            raise CatalogFormError("source_hash_invalid")
        transport = current_app.config.get("RESOURCE_SOURCE_TRANSPORT")
        if transport is None:
            transport = PinnedHttpTransport()
        resources.refresh_resource_source_check(
            content_id,
            _positive_id(request.form, "expected_lock_version"),
            expected_hash,
            actor=_actor(),
            transport=transport,
            now=_now(),
        )
        return redirect(url_for("admin.admin_resource_edit_v2", content_id=content_id))
    except CatalogFormError as error:
        return _json_error(error)
    except ContentConflictError as error:
        return jsonify({"error": error.code}), 409
    except ContentValidationError as error:
        return jsonify({"error": error.code}), 400
    except ContentStateError as error:
        return jsonify({"error": error.code}), 409
    except ContentNotFoundError:
        abort(404)


@bp.get("/admin/announcements")
def admin_announcements_v2():
    return _list("announcement")


@bp.route("/admin/announcements/new", methods=["GET", "POST"])
def admin_announcement_new_v2():
    return _new("announcement")


@bp.route("/admin/announcements/<int:content_id>", methods=["GET", "POST"])
def admin_announcement_edit_v2(content_id):
    return _edit("announcement", content_id)


@bp.post("/admin/announcements/<int:content_id>/copy")
def admin_announcement_copy_v2(content_id):
    return _copy("announcement", content_id)
