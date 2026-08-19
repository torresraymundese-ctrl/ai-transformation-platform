"""Public website routes."""

from flask import Blueprint, abort, render_template, request

import content_repository
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
    data = content_repository.home_page_data()
    return render_template(
        "index.html",
        cases=data["cases"],
        services=data["services"],
        articles=data["articles"],
    )


@bp.route("/services")
def services_page():
    services = content_repository.services_by_tier()
    return render_template(
        "services.html",
        starter=services["starter"],
        accelerate=services["accelerate"],
        flagship=services["flagship"],
    )


@bp.route("/cases")
def cases_page():
    industry = valid_text(request.args, "industry", maximum=100)
    search = valid_text(request.args, "search", maximum=100)
    cases, industries = content_repository.search_cases(industry, search)
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
    data = content_repository.insight_page_data(category, tag, search)
    return render_template(
        "insights.html",
        articles=data["articles"],
        current_category=category,
        current_tag=tag,
        announcements=data["announcements"],
        search=search,
    )


@bp.route("/article/<int:article_id>")
def article_page(article_id):
    article, related = content_repository.article_detail(article_id)
    if article is None:
        abort(404)
    return render_template("article.html", article=article, related=related)


@bp.route("/about")
def about_page():
    return render_template("about.html")
