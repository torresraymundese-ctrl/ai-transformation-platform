"""Admin routes that remain outside the revisioned content editors."""

from flask import render_template

from blueprints.admin import bp
import content_repository


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
