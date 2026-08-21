"""Admin blueprint assembled from authentication, content, and asset modules."""

from flask import Blueprint


bp = Blueprint("admin", __name__)


from . import assets, auth, content, leads  # noqa: E402,F401
