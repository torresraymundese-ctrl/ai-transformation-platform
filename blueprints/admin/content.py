"""Admin content-management routes."""

import hashlib

from flask import (abort, current_app, jsonify, redirect, render_template,
                   request, url_for)

from blueprints.admin import bp
from models import get_db
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
    db = get_db()
    stats = {
        "articles": db.execute("SELECT COUNT(*) FROM articles").fetchone()[0],
        "cases": db.execute("SELECT COUNT(*) FROM cases").fetchone()[0],
        "assessments": db.execute("SELECT COUNT(*) FROM assessments").fetchone()[0],
    }
    db.close()
    return render_template("admin/index.html", stats=stats)


@bp.route("/admin/articles")
def admin_articles():
    db = get_db()
    articles = db.execute(
        "SELECT * FROM articles ORDER BY created_at DESC"
    ).fetchall()
    db.close()
    return render_template("admin/articles.html", articles=articles)


@bp.route("/admin/article/<int:article_id>", methods=["GET", "POST"])
def admin_article_edit(article_id):
    if request.method == "POST":
        item = article_payload(request.form)
        db = get_db()
        db.execute(
            "UPDATE articles SET title=?,source=?,source_url=?,summary=?,"
            "content_html=?,tags=?,category=?,is_featured=?,status=? WHERE id=?",
            (
                item["title"], item["source"], item["source_url"], item["summary"],
                item["content_html"], item["tags"], item["category"],
                item["is_featured"], item["status"], article_id,
            ),
        )
        db.commit()
        db.close()
        return redirect(url_for("admin.admin_articles"))
    db = get_db()
    article = db.execute(
        "SELECT * FROM articles WHERE id=?", (article_id,)
    ).fetchone()
    db.close()
    if article is None:
        abort(404)
    return render_template("admin/article_edit.html", article=article)


@bp.route("/admin/article/new", methods=["GET", "POST"])
def admin_article_new():
    if request.method == "POST":
        item = article_payload(request.form)
        db = get_db()
        db.execute(
            "INSERT INTO articles (title_hash,title,source,source_url,summary,"
            "content_html,tags,category,is_featured,status) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                item["title_hash"], item["title"], item["source"], item["source_url"],
                item["summary"], item["content_html"], item["tags"], item["category"],
                item["is_featured"], item["status"],
            ),
        )
        db.commit()
        db.close()
        return redirect("/admin/articles")
    return render_template("admin/article_edit.html", article=None)


@bp.route("/admin/cases")
def admin_cases():
    db = get_db()
    cases = db.execute("SELECT * FROM cases ORDER BY sort_order").fetchall()
    db.close()
    return render_template("admin/cases.html", cases=cases)


@bp.route("/admin/case/new", methods=["GET", "POST"])
def admin_case_new():
    if request.method == "POST":
        item = case_payload(request.form)
        db = get_db()
        db.execute(
            "INSERT INTO cases (title,industry,scale,pain_point,solution,result,tags,"
            "logo_text) VALUES (?,?,?,?,?,?,?,?)",
            tuple(item.values()),
        )
        db.commit()
        db.close()
        return redirect("/admin/cases")
    return render_template("admin/case_edit.html", case=None)


@bp.route("/admin/case/<int:case_id>", methods=["GET", "POST"])
def admin_case_edit(case_id):
    if request.method == "POST":
        item = case_payload(request.form)
        db = get_db()
        db.execute(
            "UPDATE cases SET title=?,industry=?,scale=?,pain_point=?,solution=?,"
            "result=?,tags=?,logo_text=? WHERE id=?",
            (*item.values(), case_id),
        )
        db.commit()
        db.close()
        return redirect("/admin/cases")
    db = get_db()
    case = db.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    db.close()
    if case is None:
        abort(404)
    return render_template("admin/case_edit.html", case=case)


@bp.route("/admin/assessments")
def admin_assessments():
    db = get_db()
    assessments = db.execute(
        "SELECT * FROM assessments ORDER BY created_at DESC LIMIT 50"
    ).fetchall()
    db.close()
    return render_template("admin/assessments.html", assessments=assessments)


@bp.route("/admin/scrape", methods=["POST"])
def admin_scrape():
    try:
        from scraper import run_scraper

        return jsonify({"success": True, "count": run_scraper()})
    except Exception as error:
        current_app.logger.error("Admin scrape failed error_type=%s", type(error).__name__)
        return jsonify({"success": False, "error": "scrape failed"}), 502


@bp.route("/admin/announcements")
def admin_announcements():
    db = get_db()
    announcements = db.execute(
        "SELECT * FROM announcements ORDER BY created_at DESC"
    ).fetchall()
    db.close()
    return render_template("admin/announcements.html", announcements=announcements)


@bp.route("/admin/announcement/new", methods=["GET", "POST"])
def admin_announcement_new():
    if request.method == "POST":
        item = announcement_payload(request.form)
        db = get_db()
        db.execute(
            "INSERT INTO announcements (title,content_html,is_pinned,status) "
            "VALUES (?,?,?,?)",
            tuple(item.values()),
        )
        db.commit()
        db.close()
        return redirect("/admin/announcements")
    return render_template("admin/announcement_edit.html", announcement=None)


@bp.route("/admin/announcement/<int:aid>", methods=["GET", "POST"])
def admin_announcement_edit(aid):
    if request.method == "POST":
        item = announcement_payload(request.form)
        db = get_db()
        db.execute(
            "UPDATE announcements SET title=?,content_html=?,is_pinned=?,status=? "
            "WHERE id=?",
            (*item.values(), aid),
        )
        db.commit()
        db.close()
        return redirect("/admin/announcements")
    db = get_db()
    announcement = db.execute(
        "SELECT * FROM announcements WHERE id=?", (aid,)
    ).fetchone()
    db.close()
    if announcement is None:
        abort(404)
    return render_template("admin/announcement_edit.html", announcement=announcement)
