"""Authenticated operations dashboard and bounded queue detail."""

from flask import current_app, render_template, request

from blueprints.admin import bp
from content_clock import shanghai_now
from operations_repository import (
    QUEUE_LABELS,
    dashboard_snapshot,
    parse_operation_queue,
    query_operation_queue,
)
from pagination import parse_pagination


def _operations_now():
    provider = current_app.config.get("ADMIN_NOW_PROVIDER")
    return provider() if callable(provider) else shanghai_now()


@bp.route("/admin")
def admin_index():
    now = _operations_now()
    queue = parse_operation_queue(request.args)
    if queue is None:
        return render_template(
            "admin/operations_dashboard.html",
            snapshot=dashboard_snapshot(now),
            selected_queue=None,
            page=None,
            queue_label=None,
        )
    return render_template(
        "admin/operations_dashboard.html",
        snapshot=None,
        selected_queue=queue,
        page=query_operation_queue(queue, parse_pagination(request.args), now),
        queue_label=QUEUE_LABELS[queue],
    )
