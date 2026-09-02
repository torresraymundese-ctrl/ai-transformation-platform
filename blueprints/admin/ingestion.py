"""Choice-first admin controls for the private ingestion queue."""

from flask import abort, current_app, jsonify, redirect, render_template, request, session, url_for

from blueprints.admin import bp
from content_clock import shanghai_now
from ingestion_repository import (
    load_candidate,
    parse_ingestion_filters,
    query_ingestion_candidates,
)
from ingestion_service import (
    AcceptDecision,
    IngestionDecisionError,
    REJECTION_CODES,
    accept_candidate,
    reject_candidate,
)
from scraper import IngestionQueueNotReadyError, run_scraper
from pagination import parse_pagination


def _actor():
    return session.get("admin_username") or current_app.config["ADMIN_USERNAME"]


def _now():
    provider = current_app.config.get("ADMIN_NOW_PROVIDER")
    return provider() if callable(provider) else shanghai_now()


@bp.get("/admin/ingestion")
def admin_ingestion():
    filters = parse_ingestion_filters(request.args)
    return render_template(
        "admin/ingestion.html",
        page=query_ingestion_candidates(filters, parse_pagination(request.args)),
        filters=filters,
    )


@bp.get("/admin/ingestion/<int:candidate_id>")
def admin_ingestion_detail(candidate_id):
    candidate = load_candidate(candidate_id)
    if candidate is None:
        abort(404)
    return render_template(
        "admin/ingestion_detail.html",
        candidate=candidate,
        rejection_codes=sorted(REJECTION_CODES),
    )


@bp.post("/admin/ingestion/<int:candidate_id>/decision")
def admin_ingestion_decision(candidate_id):
    common = {"csrf_token", "action", "expected_lock_version"}
    action = request.form.get("action", "")
    expected_fields = common | ({"slug"} if action == "accept" else {"reason_code", "note"})
    if set(request.form) != expected_fields:
        return jsonify({"error": "decision_invalid"}), 400
    try:
        lock_version = int(request.form["expected_lock_version"])
        if action == "accept":
            accept_candidate(
                candidate_id,
                AcceptDecision(request.form["slug"]),
                lock_version,
                _actor(),
                _now(),
            )
        elif action == "reject":
            reject_candidate(
                candidate_id,
                request.form["reason_code"],
                request.form["note"],
                lock_version,
                _actor(),
                _now(),
            )
        else:
            raise IngestionDecisionError("decision_invalid")
    except (KeyError, ValueError, IngestionDecisionError) as error:
        code = getattr(error, "args", ("decision_invalid",))[0]
        if code == "candidate_conflict":
            return jsonify({"error": "candidate_conflict"}), 409
        return jsonify({"error": "decision_invalid"}), 400
    return redirect(url_for("admin.admin_ingestion_detail", candidate_id=candidate_id))


@bp.post("/admin/scrape")
def admin_scrape():
    if set(request.form) - {"csrf_token"}:
        return jsonify({"error": "request_invalid"}), 400
    try:
        result = run_scraper(
            transport=current_app.config.get("INGESTION_TRANSPORT"),
            adapters=current_app.config.get("INGESTION_ADAPTERS"),
            now=_now(),
        )
    except IngestionQueueNotReadyError:
        return jsonify({"error": "ingestion_queue_not_ready"}), 410
    except Exception as error:
        current_app.logger.error(
            "Admin ingestion failed error_type=%s", type(error).__name__
        )
        return jsonify({"error": "ingestion_failed"}), 502
    return jsonify(
        {
            "created_count": len(result.created_ids),
            "created_ids": list(result.created_ids),
            "deduplicated": result.deduplicated,
            "failed_sources": result.failed_sources,
        }
    )
