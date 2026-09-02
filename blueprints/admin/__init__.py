"""Admin blueprint assembled from authentication, content, and asset modules."""

from flask import Blueprint


bp = Blueprint("admin", __name__)


from . import (  # noqa: E402,F401
    assets,
    auth,
    cases,
    catalog,
    content,
    ingestion,
    leads,
    media,
    operations,
    resources,
)
