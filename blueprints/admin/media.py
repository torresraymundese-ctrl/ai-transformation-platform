"""Authenticated admin upload, preview, and archival routes."""

from flask import abort, redirect, render_template, request, send_file, url_for

from blueprints.admin import bp
from media_service import (
    MediaInUseError,
    MediaNotFoundError,
    archive_media,
    get_media_asset,
    media_root,
    parse_media_filters,
    query_media_assets,
    store_media,
)
from media_validation import ATTACHMENT_MIMES
from repository import DataConflictError
from pagination import parse_pagination


@bp.route("/admin/media", methods=["GET", "POST"])
def admin_media():
    if request.method == "POST":
        store_media(
            request.files.get("file"),
            metadata_review_confirmed=(
                request.form.get("metadata_review_confirmed") == "1"
            ),
        )
        return redirect(url_for("admin.admin_media"))
    filters = parse_media_filters(request.args)
    return render_template(
        "admin/media.html",
        page=query_media_assets(filters, parse_pagination(request.args)),
        filters=filters,
    )


@bp.get("/admin/media/<int:asset_id>/preview")
def admin_media_preview(asset_id):
    asset = get_media_asset(asset_id)
    if asset is None or asset.status != "ready":
        abort(404)
    root = media_root()
    path = (root / asset.storage_name).resolve()
    if path.parent != root or not path.is_file():
        abort(404)

    response = send_file(
        path,
        mimetype=asset.detected_mime,
        as_attachment=asset.detected_mime in ATTACHMENT_MIMES,
        download_name=asset.display_name,
        conditional=False,
        etag=False,
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@bp.post("/admin/media/<int:asset_id>/archive")
def admin_media_archive(asset_id):
    try:
        archive_media(asset_id)
    except MediaNotFoundError:
        abort(404)
    except MediaInUseError as error:
        raise DataConflictError("media is still referenced") from error
    return redirect(url_for("admin.admin_media"))
