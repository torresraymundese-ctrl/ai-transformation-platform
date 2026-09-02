"""Public current and immutable historical legal-document routes."""

from flask import Blueprint, abort, redirect, render_template

from legal_repository import (
    DOCUMENT_TYPES,
    VERSION_CODE_PATTERN,
    LegalContractError,
    load_public_legal_version,
    normalize_external_legal_url,
)


bp = Blueprint("public_legal", __name__)


def _render_or_redirect(document):
    if document is None:
        abort(404)
    if document.mode == "external_legacy":
        try:
            normalized = normalize_external_legal_url(document.external_url)
        except LegalContractError:
            abort(404)
        if normalized != document.external_url:
            abort(404)
        return redirect(normalized, code=302)
    if document.mode != "internal":
        abort(404)
    return render_template("legal_detail.html", document=document)


@bp.get("/legal/<document_type>")
def legal_current(document_type):
    if document_type not in DOCUMENT_TYPES:
        abort(404)
    return _render_or_redirect(load_public_legal_version(document_type))


@bp.get("/legal/<document_type>/<version_code>")
def legal_version(document_type, version_code):
    if (
        document_type not in DOCUMENT_TYPES
        or VERSION_CODE_PATTERN.fullmatch(version_code) is None
    ):
        abort(404)
    return _render_or_redirect(load_public_legal_version(document_type, version_code))
