"""Public website routes."""

from flask import Blueprint, abort, render_template, request

from models import get_db
from validation import ValidationError, text as valid_text


bp = Blueprint("public", __name__)


def svc_emoji(icon):
    mapping = {
        "database": "🗄️", "server": "🖥️", "book": "📚", "file-text": "📝",
        "target": "🎯", "cpu": "🤖", "repeat": "🔄", "trending-up": "📈",
        "layers": "🏗️", "eye": "👁️", "shield": "🛡️", "users": "👥",
    }
    return mapping.get(icon, "📌")


@bp.route("/health")
def health():
    return {"status": "ok"}


@bp.route("/")
def index():
    db = get_db()
    featured_cases = db.execute(
        "SELECT * FROM cases WHERE is_featured=1 ORDER BY sort_order LIMIT 3"
    ).fetchall()
    services = db.execute("SELECT * FROM services ORDER BY sort_order").fetchall()
    articles = db.execute(
        "SELECT * FROM articles WHERE status='published' "
        "ORDER BY created_at DESC LIMIT 6"
    ).fetchall()
    db.close()
    return render_template(
        "index.html", cases=featured_cases, services=services, articles=articles
    )


@bp.route("/services")
def services_page():
    db = get_db()
    starter = db.execute(
        "SELECT * FROM services WHERE tier='starter' ORDER BY sort_order"
    ).fetchall()
    accelerate = db.execute(
        "SELECT * FROM services WHERE tier='accelerate' ORDER BY sort_order"
    ).fetchall()
    flagship = db.execute(
        "SELECT * FROM services WHERE tier='flagship' ORDER BY sort_order"
    ).fetchall()
    db.close()
    return render_template(
        "services.html", starter=starter, accelerate=accelerate, flagship=flagship
    )


@bp.route("/cases")
def cases_page():
    industry = valid_text(request.args, "industry", maximum=100)
    search = valid_text(request.args, "search", maximum=100)
    query = "SELECT * FROM cases WHERE 1=1"
    params = []
    if industry:
        query += " AND industry=?"
        params.append(industry)
    if search:
        query += (
            " AND (title LIKE ? OR pain_point LIKE ? OR solution LIKE ? "
            "OR result LIKE ? OR tags LIKE ?)"
        )
        params.extend([f"%{search}%"] * 5)
    query += " ORDER BY sort_order"
    db = get_db()
    cases = db.execute(query, params).fetchall()
    industries = db.execute(
        "SELECT DISTINCT industry FROM cases ORDER BY industry"
    ).fetchall()
    db.close()
    return render_template(
        "cases.html",
        cases=cases,
        industries=industries,
        current_industry=industry,
        search=search,
    )


@bp.route("/assessment")
def assessment_page():
    return render_template("assessment.html")


@bp.route("/insights")
def insights_page():
    category = valid_text(request.args, "category", maximum=32)
    if category and category not in {
        "insight", "whitepaper", "tech", "announcement"
    }:
        raise ValidationError("category has an invalid value")
    tag = valid_text(request.args, "tag", maximum=100)
    search = valid_text(request.args, "search", maximum=100)
    if category == "announcement":
        query = (
            "SELECT * FROM articles WHERE status='published' "
            "AND category='announcement'"
        )
        params = []
    else:
        query = (
            "SELECT * FROM articles WHERE status='published' "
            "AND category!='announcement'"
        )
        params = []
        if category:
            query += " AND category=?"
            params.append(category)
        if tag:
            query += " AND tags LIKE ?"
            params.append(f"%{tag}%")
        if search:
            query += " AND (title LIKE ? OR summary LIKE ? OR tags LIKE ?)"
            params.extend([f"%{search}%"] * 3)
    query += " ORDER BY created_at DESC LIMIT 50"
    db = get_db()
    articles = db.execute(query, params).fetchall()
    announcements = db.execute(
        "SELECT * FROM announcements WHERE status='published' "
        "ORDER BY is_pinned DESC, created_at DESC"
    ).fetchall()
    db.close()
    return render_template(
        "insights.html",
        articles=articles,
        current_category=category,
        current_tag=tag,
        announcements=announcements,
        search=search,
    )


@bp.route("/article/<int:article_id>")
def article_page(article_id):
    db = get_db()
    article = db.execute(
        "SELECT * FROM articles WHERE id=?", (article_id,)
    ).fetchone()
    if article is None:
        db.close()
        abort(404)
    related = db.execute(
        "SELECT * FROM articles WHERE status='published' AND id!=? "
        "ORDER BY created_at DESC LIMIT 4",
        (article_id,),
    ).fetchall()
    db.close()
    return render_template("article.html", article=article, related=related)


@bp.route("/about")
def about_page():
    return render_template("about.html")
