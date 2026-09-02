"""Authenticated HTTP adapter for V2 verified cases."""

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
import case_repository as cases
from content_clock import format_shanghai, shanghai_now
from content_contracts import CaseMetric, ContentDraft
from content_validation import CASE_BASIS_TYPES, CASE_VERIFICATION, ContentValidationError
from pagination import parse_pagination
from publishing_repository import (
    ContentConflictError,
    ContentNotFoundError,
    ContentStateError,
)
from source_url_checker import PinnedHttpTransport


ACTIONS = frozenset({"save", "review", "publish", "archive"})
FIXED_FIELDS = frozenset(
    {
        "csrf_token", "action", "content_id", "lock_version", "slug", "title",
        "summary", "seo_title", "seo_description", "share_image_media_id",
        "verification_code", "is_verified", "basis_type", "private_basis_reference",
        "source_url", "review_confirmed", "privacy_review_confirmed",
        "media_review_confirmed",
    }
)
METRIC_SUFFIXES = frozenset(
    {
        "name", "before_value", "after_value", "unit", "statistical_period",
        "evidence_explanation",
    }
)
METRIC_FIELD = re.compile(r"^metrics-(0|[1-9][0-9]*)-([a-z_]+)$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def _actor():
    return session.get("admin_username") or current_app.config["ADMIN_USERNAME"]


def _now():
    provider = current_app.config.get("ADMIN_NOW_PROVIDER")
    return provider() if callable(provider) else shanghai_now()


def _validate_names(data):
    for name in data.keys():
        if name in FIXED_FIELDS:
            continue
        block = BLOCK_FIELD.fullmatch(name)
        if block is not None and block.group(2) in BLOCK_SUFFIXES:
            continue
        metric = METRIC_FIELD.fullmatch(name)
        if metric is not None and metric.group(2) in METRIC_SUFFIXES:
            continue
        raise CatalogFormError("unknown_field", name)


def _exact_flag(data, name, *, required=True):
    raw = _one(data, name, required=required)
    if not required and raw == "":
        return 0
    if raw not in {"0", "1"}:
        raise CatalogFormError("field_invalid", name)
    return int(raw)


def _confirmation(data, name):
    raw = _one(data, name, required=False)
    if raw not in {"", "1"}:
        raise CatalogFormError("field_invalid", name)
    return raw == "1"


def _metric(data, index):
    prefix = f"metrics-{index}-"
    supplied = {
        match.group(2)
        for name in data.keys()
        if (match := METRIC_FIELD.fullmatch(name)) is not None
        and int(match.group(1)) == index
    }
    if supplied != METRIC_SUFFIXES:
        raise CatalogFormError("metric_fields_invalid")
    return CaseMetric(
        _one(data, prefix + "name"),
        _one(data, prefix + "before_value"),
        _one(data, prefix + "after_value"),
        _one(data, prefix + "unit"),
        _one(data, prefix + "statistical_period"),
        _one(data, prefix + "evidence_explanation"),
        index,
    )


def _parse_submission(data, *, content_id=None, now=None):
    _validate_names(data)
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
    verification_code = _one(data, "verification_code")
    basis_type = _one(data, "basis_type")
    if verification_code not in CASE_VERIFICATION:
        raise CatalogFormError("verification_code_invalid")
    if basis_type not in CASE_BASIS_TYPES:
        raise CatalogFormError("basis_type_invalid")
    is_verified = _exact_flag(data, "is_verified")
    review = _confirmation(data, "review_confirmed")
    privacy = _confirmation(data, "privacy_review_confirmed")
    media = _confirmation(data, "media_review_confirmed")
    if action in {"review", "publish"} and not (review and privacy and media):
        raise CatalogFormError("review_confirmation_required")
    blocks = tuple(
        _parse_block(data, index)
        for index in _indexed_fields(data, BLOCK_FIELD, 40)
    )
    metrics = tuple(
        _metric(data, index)
        for index in _indexed_fields(data, METRIC_FIELD, 20)
    )
    private_reference = _one(data, "private_basis_reference") or None
    source_url = _one(data, "source_url") or None
    draft = ContentDraft(
        entry_type="case",
        slug=_one(data, "slug"),
        title=_one(data, "title"),
        summary=_one(data, "summary"),
        seo_title=_one(data, "seo_title"),
        seo_description=_one(data, "seo_description"),
        content_group_id=None,
        share_image_media_id=_positive_id(data, "share_image_media_id", nullable=True),
        extension={
            "verification_code": verification_code,
            "is_anonymized": 1 if verification_code == "authorized_anonymous" else 0,
            "basis_type": basis_type,
            "private_basis_reference": private_reference,
            "source_url": source_url,
            "source_url_sha256": None,
            "source_check_code": None,
            "source_checked_at": None,
            "source_check_expires_at": None,
            "source_check_url_sha256": None,
            "is_verified": is_verified,
            "review_confirmed": 1 if review and privacy and media else 0,
            "verified_at": format_shanghai(now if now is not None else _now()) if is_verified == 1 else None,
        },
        blocks=blocks,
        metrics=metrics,
    )
    return action, supplied_id, lock_version, draft


def _json_error(error):
    payload = {"error": error.code}
    if getattr(error, "field", None) is not None:
        payload["field"] = error.field
    return jsonify(payload), 400


@bp.get("/admin/cases")
def admin_cases_v2():
    filters = cases.parse_case_filters(request.args)
    return render_template(
        "admin/case_list_v2.html",
        page=cases.admin_cases(parse_pagination(request.args), filters),
        filters=filters,
    )


@bp.route("/admin/cases/new", methods=["GET", "POST"])
def admin_case_new_v2():
    if request.method == "GET":
        return render_template(
            "admin/case_edit_v2.html", view=cases.get_editor(), error=None
        )
    draft = None
    try:
        instant = _now()
        action, _, _, draft = _parse_submission(request.form, now=instant)
        result = cases.create_case(draft, action=action, actor=_actor(), now=instant)
        return redirect(url_for("admin.admin_case_edit_v2", content_id=result.content_id))
    except CatalogFormError as error:
        return _json_error(error)
    except ContentConflictError as error:
        return jsonify({"error": error.code}), 409
    except ContentValidationError as error:
        return jsonify({"error": error.code}), 400


@bp.route("/admin/cases/<int:content_id>", methods=["GET", "POST"])
def admin_case_edit_v2(content_id):
    draft = None
    try:
        if request.method == "GET":
            editable_id = cases.editable_revision(content_id)
            if editable_id is not None and editable_id != content_id:
                return redirect(url_for("admin.admin_case_edit_v2", content_id=editable_id))
            return render_template(
                "admin/case_edit_v2.html", view=cases.get_editor(content_id), error=None
            )
        instant = _now()
        action, supplied_id, lock_version, draft = _parse_submission(
            request.form, content_id=content_id, now=instant
        )
        if action == "archive":
            cases.archive_case(
                supplied_id, lock_version, actor=_actor(), now=instant
            )
        else:
            current = cases.get_editor(content_id).form
            draft = replace(draft, content_group_id=current.content_group_id)
            cases.save_case(
                content_id, lock_version, draft, action=action, actor=_actor(), now=instant
            )
        return redirect(url_for("admin.admin_case_edit_v2", content_id=content_id))
    except CatalogFormError as error:
        return _json_error(error)
    except ContentConflictError:
        if draft is None:
            return jsonify({"error": "stale_lock_version"}), 409
        form = cases.submitted_form(draft, content_id, lock_version)
        return (
            render_template(
                "admin/case_edit_v2.html",
                view=cases.get_editor(content_id, form=form),
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


@bp.post("/admin/cases/<int:content_id>/copy")
def admin_case_copy_v2(content_id):
    try:
        if set(request.form.keys()) != {
            "csrf_token", "content_id", "expected_lock_version"
        }:
            raise CatalogFormError("unknown_field")
        supplied_id = _positive_id(request.form, "content_id")
        if supplied_id != content_id:
            raise CatalogFormError("content_identity_invalid")
        copied_id = cases.copy_revision(
            content_id,
            _positive_id(request.form, "expected_lock_version"),
            actor=_actor(),
            now=_now(),
        )
        return redirect(url_for("admin.admin_case_edit_v2", content_id=copied_id))
    except CatalogFormError as error:
        return _json_error(error)
    except ContentConflictError as error:
        return jsonify({"error": error.code}), 409
    except ContentStateError as error:
        return jsonify({"error": error.code}), 409
    except ContentNotFoundError:
        abort(404)


@bp.post("/admin/cases/<int:content_id>/source-check")
def admin_case_source_check_v2(content_id):
    try:
        if set(request.form.keys()) != {
            "csrf_token", "expected_lock_version", "expected_url_sha256"
        }:
            raise CatalogFormError("unknown_field")
        lock_version = _positive_id(request.form, "expected_lock_version")
        expected_hash = _one(request.form, "expected_url_sha256")
        if HASH_RE.fullmatch(expected_hash) is None:
            raise CatalogFormError("source_hash_invalid")
        transport = current_app.config.get("CASE_SOURCE_TRANSPORT")
        if transport is None:
            transport = PinnedHttpTransport()
        instant = _now()
        cases.refresh_source_check(
            content_id,
            lock_version,
            expected_hash,
            actor=_actor(),
            transport=transport,
            now=instant,
        )
        return redirect(url_for("admin.admin_case_edit_v2", content_id=content_id))
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
