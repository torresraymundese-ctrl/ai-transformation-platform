"""Admin content-management routes."""

import hashlib

from flask import (abort, current_app, jsonify, redirect, render_template,
                   request, url_for)

from blueprints.admin import bp
import content_repository
from security import sanitize_html
from validation import (choice as valid_choice, external_url as valid_external_url,
                        integer as valid_integer, text as valid_text)


def article_payload(data):
    title = valid_text(data, "title", maximum=200, required=True)
    return {
        "title": title,
        "source": valid_text(data, "source", maximum=120),
        "source_url": valid_external_url(data, "source_url"),
        "summary": valid_text(data, "summary", maximum=2000),
        "content_html": str(
            sanitize_html(valid_text(data, "content_html", maximum=100000))
        ),
        "tags": valid_text(data, "tags", maximum=500),
        "category": valid_choice(
            data, "category", {"insight", "whitepaper", "tech", "announcement"}
        ),
        "is_featured": valid_integer(
            data, "is_featured", minimum=0, maximum=1, default=0
        ),
        "status": valid_choice(data, "status", {"published", "draft"}),
        "title_hash": hashlib.sha256(
            title.casefold().encode("utf-8")
        ).hexdigest()[:32],
    }


def case_payload(data):
    return {
        "title": valid_text(data, "title", maximum=200, required=True),
        "industry": valid_text(data, "industry", maximum=100, required=True),
        "scale": valid_text(data, "scale", maximum=100),
        "pain_point": valid_text(data, "pain_point", maximum=4000),
        "solution": valid_text(data, "solution", maximum=4000),
        "result": valid_text(data, "result", maximum=4000),
        "tags": valid_text(data, "tags", maximum=500),
        "logo_text": valid_text(data, "logo_text", maximum=8, default="E") or "E",
    }


def announcement_payload(data):
    return {
        "title": valid_text(data, "title", maximum=200, required=True),
        "content_html": str(
            sanitize_html(valid_text(data, "content_html", maximum=50000))
        ),
        "is_pinned": valid_integer(
            data, "is_pinned", minimum=0, maximum=1, default=0
        ),
        "status": valid_choice(
            data, "status", {"published", "draft"}, default="published"
        ),
    }


@bp.route("/admin")
def admin_index():
    return render_template("admin/index.html", stats=content_repository.admin_counts())


@bp.route("/admin/articles")
def admin_articles():
    return render_template(
        "admin/articles.html", articles=content_repository.list_articles()
    )


@bp.route("/admin/article/<int:article_id>", methods=["GET", "POST"])
def admin_article_edit(article_id):
    if request.method == "POST":
        item = article_payload(request.form)
        content_repository.update_article(article_id, item)
        return redirect(url_for("admin.admin_articles"))
    article = content_repository.get_article(article_id)
    if article is None:
        abort(404)
    return render_template("admin/article_edit.html", article=article)


@bp.route("/admin/article/new", methods=["GET", "POST"])
def admin_article_new():
    if request.method == "POST":
        item = article_payload(request.form)
        content_repository.create_article(item)
        return redirect("/admin/articles")
    return render_template("admin/article_edit.html", article=None)


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


@bp.route("/admin/announcements")
def admin_announcements():
    return render_template(
        "admin/announcements.html",
        announcements=content_repository.list_announcements(),
    )


@bp.route("/admin/announcement/new", methods=["GET", "POST"])
def admin_announcement_new():
    if request.method == "POST":
        item = announcement_payload(request.form)
        content_repository.create_announcement(item)
        return redirect("/admin/announcements")
    return render_template("admin/announcement_edit.html", announcement=None)


@bp.route("/admin/announcement/<int:aid>", methods=["GET", "POST"])
def admin_announcement_edit(aid):
    if request.method == "POST":
        item = announcement_payload(request.form)
        content_repository.update_announcement(aid, item)
        return redirect("/admin/announcements")
    announcement = content_repository.get_announcement(aid)
    if announcement is None:
        abort(404)
    return render_template("admin/announcement_edit.html", announcement=announcement)
