"""Admin blueprint assembled from authentication, content, and asset modules."""

from flask import Blueprint
from admin_display import admin_label


bp = Blueprint("admin", __name__)
bp.add_app_template_filter(admin_label, "admin_label")


from . import (  # noqa: E402,F401
    assets,
    auth,
    cases,
    catalog,
    content,
    ingestion,
    leads,
    legal,
    media,
    operations,
    rules,
    resources,
)
