"""Admin routes that remain outside the revisioned content editors."""

from flask import current_app, jsonify, render_template

from blueprints.admin import bp
import content_repository


@bp.route("/admin")
def admin_index():
    return render_template("admin/index.html", stats=content_repository.admin_counts())


@bp.route("/admin/case/new", methods=["GET", "POST"])
def admin_case_new():
    return "旧案例编辑器已停用；请等待案例迁移审阅流程。", 410


@bp.route("/admin/case/<int:case_id>", methods=["GET", "POST"])
def admin_case_edit(case_id):
    return "旧案例编辑器已停用；请等待案例迁移审阅流程。", 410


@bp.route("/admin/assessments")
def admin_assessments():
    return render_template(
        "admin/assessments.html", assessments=content_repository.list_assessments()
    )


@bp.route("/admin/scrape", methods=["POST"])
def admin_scrape():
    try:
        from scraper import IngestionQueueNotReadyError, run_scraper

        run_scraper()
    except IngestionQueueNotReadyError:
        return jsonify({"error": "ingestion_queue_not_ready"}), 410
    except Exception as error:
        current_app.logger.error("Admin scrape failed error_type=%s", type(error).__name__)
        return jsonify({"success": False, "error": "scrape failed"}), 502
