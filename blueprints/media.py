"""Controlled public media responses for currently published references."""

from flask import Blueprint, abort, make_response, request, send_file

from media_service import get_published_media_asset, media_root


bp = Blueprint("media", __name__)


def _asset_path(asset):
    root = media_root()
    path = (root / asset.storage_name).resolve()
    if path.parent != root or not path.is_file():
        abort(404)
    return path


def _send_public(asset, *, attachment):
    path = _asset_path(asset)
    response = make_response(
        send_file(
            path,
            mimetype=asset.detected_mime,
            as_attachment=attachment,
            download_name=(
                asset.display_name if attachment else asset.storage_name
            ),
            conditional=False,
            etag=False,
            max_age=None,
        )
    )
    response.set_etag(asset.sha256, weak=False)
    response.cache_control.clear()
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.make_conditional(request)
    return response


@bp.get("/media/<int:asset_id>/image")
def published_image(asset_id):
    asset = get_published_media_asset(asset_id, kind="image")
    if asset is None:
        abort(404)
    return _send_public(asset, attachment=False)


@bp.get("/media/<int:asset_id>/download")
def published_download(asset_id):
    asset = get_published_media_asset(asset_id, kind="download")
    if asset is None:
        abort(404)
    return _send_public(asset, attachment=True)
