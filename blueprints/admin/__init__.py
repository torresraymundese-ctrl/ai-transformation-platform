"""Admin blueprint assembled from authentication, content, and asset modules."""

from flask import Blueprint


bp = Blueprint("admin", __name__)


from . import assets, auth, cases, catalog, content, ingestion, leads, media, resources  # noqa: E402,F401
