"""Public website routes."""

from flask import Blueprint, abort, current_app, redirect, render_template

import content_repository
from content_clock import shanghai_now
bp = Blueprint("public", __name__)


def _canonical(path):
    return f"{current_app.config['PUBLIC_BASE_URL']}{path}"


def _content_now():
    provider = current_app.config.get("CONTENT_NOW_PROVIDER")
    return provider() if callable(provider) else shanghai_now()


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
    data = content_repository.home_page_data(now=_content_now())
    return render_template(
        "index.html",
        canonical=_canonical("/"),
        **data,
    )


@bp.route("/services")
def services_page():
    return redirect("/service-packages", code=301)


@bp.route("/assessment")
def assessment_page():
    return render_template(
        "assessment.html", base_canonical=_canonical("/assessment")
    )


@bp.route("/insights")
def insights_page():
    return redirect("/resources", code=301)


@bp.route("/article/<int:article_id>")
def article_page(article_id):
    slug = content_repository.legacy_article_resource_slug(
        article_id, now=_content_now()
    )
    if slug is None:
        abort(404)
    return redirect(f"/resources/{slug}", code=301)


@bp.route("/about")
def about_page():
    return render_template("about.html", base_canonical=_canonical("/about"))
