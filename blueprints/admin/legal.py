"""Authenticated legal-document drafting, review, and publication routes."""

from datetime import datetime

from flask import current_app, jsonify, make_response, redirect, render_template, request, session, url_for

from blueprints.admin import bp
from content_clock import SHANGHAI, shanghai_now
from legal_repository import (
    DOCUMENT_TYPES,
    LegalContractError,
    confirm_legal_review,
    create_legal_draft,
    load_legal_version,
    parse_legal_filters,
    publish_legal_version,
    query_legal_versions,
    update_legal_draft,
)
from pagination import parse_pagination


def _actor():
    return session.get("admin_username") or current_app.config["ADMIN_USERNAME"]


def _now():
    provider = current_app.config.get("ADMIN_NOW_PROVIDER")
    return provider() if callable(provider) else shanghai_now()


def _local_datetime(value):
    if type(value) is not str or not value or value != value.strip():
        raise LegalContractError("effective_at_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace(" ", "T"))
    except ValueError as error:
        raise LegalContractError("effective_at_invalid") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI)
    return parsed


def _positive(value, code):
    if type(value) is not str or not value.isascii() or not value.isdecimal():
        raise LegalContractError(code)
    parsed = int(value, 10)
    if not 1 <= parsed <= 2_147_483_647:
        raise LegalContractError(code)
    return parsed


def _no_store(response):
    response = make_response(response)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


def _form_error(error):
    status = 409 if "conflict" in str(error) else 400
    return _no_store((jsonify({"error": str(error)}), status))


@bp.get("/admin/legal")
def admin_legal_list():
    filters = parse_legal_filters(request.args)
    return _no_store(
        render_template(
            "admin/legal_list.html",
            page=query_legal_versions(filters, parse_pagination(request.args)),
            filters=filters,
            document_types=tuple(sorted(DOCUMENT_TYPES)),
        )
    )


@bp.route("/admin/legal/new", methods=["GET", "POST"])
def admin_legal_new():
    if request.method == "GET":
        return _no_store(
            render_template(
                "admin/legal_edit.html", document=None, document_types=tuple(sorted(DOCUMENT_TYPES))
            )
        )
    expected = {
        "csrf_token", "document_type", "version_code", "title", "body_summary",
        "body_html", "effective_at",
    }
    if set(request.form) != expected:
        return _form_error(LegalContractError("request_invalid"))
    try:
        version_id = create_legal_draft(
            document_type=request.form["document_type"],
            version_code=request.form["version_code"],
            title=request.form["title"],
            body_summary=request.form["body_summary"],
            body_html=request.form["body_html"],
            effective_at=_local_datetime(request.form["effective_at"]),
            actor=_actor(),
            now=_now(),
        )
    except LegalContractError as error:
        return _form_error(error)
    return redirect(url_for("admin.admin_legal_edit", version_id=version_id))


@bp.route("/admin/legal/<int:version_id>", methods=["GET", "POST"])
def admin_legal_edit(version_id):
    document = load_legal_version(version_id)
    if document is None:
        return _no_store((jsonify({"error": "legal_version_not_found"}), 404))
    if request.method == "GET":
        return _no_store(
            render_template(
                "admin/legal_edit.html", document=document, document_types=tuple(sorted(DOCUMENT_TYPES))
            )
        )
    action = request.form.get("action", "")
    common = {"csrf_token", "action", "expected_lock_version"}
    expected = (
        common | {"title", "body_summary", "body_html", "effective_at"}
        if action == "save"
        else common
    )
    if set(request.form) != expected or action not in {"save", "review", "publish"}:
        return _form_error(LegalContractError("request_invalid"))
    try:
        lock = _positive(request.form["expected_lock_version"], "lock_version_invalid")
        moment = _now()
        if action == "save":
            update_legal_draft(
                version_id,
                lock,
                title=request.form["title"],
                body_summary=request.form["body_summary"],
                body_html=request.form["body_html"],
                effective_at=_local_datetime(request.form["effective_at"]),
                actor=_actor(),
                now=moment,
            )
        elif action == "review":
            confirm_legal_review(version_id, lock, _actor(), moment)
        else:
            publish_legal_version(version_id, lock, _actor(), moment)
    except LegalContractError as error:
        return _form_error(error)
    return redirect(url_for("admin.admin_legal_edit", version_id=version_id))
