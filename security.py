"""Authentication, CSRF, rate limits, sanitization, errors, and audit hooks."""

import hashlib
import re
import secrets
import sqlite3
import time
from hmac import compare_digest

import bleach
from flask import (abort, current_app, g, jsonify, make_response, redirect,
                   render_template, request, session, url_for)
from markupsafe import Markup
from werkzeug.exceptions import HTTPException

from models import get_db
from repository import DataConflictError
from validation import ValidationError


ALLOWED_HTML_TAGS = {
    "a", "blockquote", "br", "code", "em", "h2", "h3", "h4", "hr",
    "li", "ol", "p", "pre", "strong", "table", "tbody", "td", "th",
    "thead", "tr", "ul",
}
ALLOWED_HTML_ATTRIBUTES = {
    "a": ["href", "title"],
    "th": ["colspan", "rowspan"],
    "td": ["colspan", "rowspan"],
}


def security_configured():
    password_hash = current_app.config.get("ADMIN_PASSWORD_HASH")
    return bool(
        current_app.config.get("SECRET_KEY")
        and current_app.config.get("ADMIN_USERNAME")
        and isinstance(password_hash, str)
        and password_hash.startswith(("scrypt:", "pbkdf2:"))
    )


def csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def csrf_is_valid():
    expected = session.get("csrf_token", "")
    supplied = request.form.get("csrf_token", "") or request.headers.get(
        "X-CSRF-Token", ""
    )
    return bool(expected and supplied and compare_digest(expected, supplied))


def require_public_csrf():
    """Require the Session-bound CSRF token for a public write endpoint."""
    if not csrf_is_valid():
        abort(403)


def check_admin_auth():
    return (
        security_configured()
        and session.get("admin_username") == current_app.config["ADMIN_USERNAME"]
    )


def request_identity_hash():
    identifier = request.remote_addr or "unknown"
    return hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:32]


def consume_rate_limit(bucket, limit, window_seconds):
    limit = int(limit)
    window_seconds = int(window_seconds)
    if limit < 1 or window_seconds < 1:
        return False

    now = int(time.time())
    window_start = now - (now % window_seconds)
    identity_hash = request_identity_hash()
    db = get_db()
    try:
        db.execute(
            "INSERT INTO request_rate_limits "
            "(bucket, identity_hash, window_start, request_count) VALUES (?,?,?,1) "
            "ON CONFLICT(bucket, identity_hash, window_start) "
            "DO UPDATE SET request_count=request_count+1",
            (bucket, identity_hash, window_start),
        )
        count = db.execute(
            "SELECT request_count FROM request_rate_limits "
            "WHERE bucket=? AND identity_hash=? AND window_start=?",
            (bucket, identity_hash, window_start),
        ).fetchone()[0]
        db.execute(
            "DELETE FROM request_rate_limits WHERE bucket=? AND window_start < ?",
            (bucket, window_start - window_seconds),
        )
        db.commit()
    finally:
        db.close()
    return count <= limit


def rate_limit_response(window_seconds):
    response = jsonify({"error": "rate limit exceeded"})
    response.status_code = 429
    response.headers["Retry-After"] = str(int(window_seconds))
    return response


def sanitize_html(value):
    without_active_blocks = re.sub(
        r"(?is)<(script|style)\b[^>]*>.*?</\1\s*>", "", value or ""
    )
    cleaned = bleach.clean(
        without_active_blocks,
        tags=ALLOWED_HTML_TAGS,
        attributes=ALLOWED_HTML_ATTRIBUTES,
        protocols={"http", "https", "mailto"},
        strip=True,
    )
    return Markup(cleaned)


def invalid_form(error):
    message = (
        "提交内容不符合要求，请返回检查后重试。"
        if _is_admin_request()
        else str(error)
    )
    return _render_error("提交内容无效", message, 400)


def forbidden(error):
    return _render_error(
        "操作被拒绝",
        "请求缺少有效授权或安全校验，请返回后重试。",
        403,
    )


def data_conflict(error):
    return _render_error(
        "数据冲突",
        "该记录与已有数据冲突，请检查当前状态后重试。",
        409,
    )


def not_found(error):
    return _render_error(
        "页面未找到", "你访问的页面不存在或已被移动。", 404
    )


def request_too_large(error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "request too large"}), 413
    return _render_error(
        "提交内容过大", "请缩小内容或附件后重试。", 413
    )


def unexpected_error(error):
    if isinstance(error, HTTPException):
        if _is_admin_request():
            return _render_error(
                "请求无法处理",
                "当前后台请求无法完成，请检查后重试。",
                error.code or 500,
            )
        return error
    current_app.logger.error(
        "Unhandled application error error_type=%s endpoint=%s",
        type(error).__name__,
        request.endpoint or "unknown",
    )
    return _render_error(
        "系统暂时无法处理请求",
        "请稍后重试；如果问题持续存在，请联系平台管理员。",
        500,
    )


def _is_admin_request():
    return request.path == "/admin" or request.path.startswith("/admin/")


def _render_error(title, message, status_code):
    template = "admin/error.html" if _is_admin_request() else "error.html"
    return render_template(
        template,
        title=title,
        message=message,
        admin_authenticated=check_admin_auth() if _is_admin_request() else False,
    ), status_code


def _admin_rate_limit_response(window_seconds):
    body, status_code = _render_error(
        "请求过于频繁",
        "尝试次数过多，请稍后再试。",
        429,
    )
    response = make_response(body, status_code)
    response.headers["Retry-After"] = str(int(window_seconds))
    return response


def protect_admin_routes():
    if not request.path.startswith("/admin"):
        return None
    g.admin_response = True
    if not security_configured():
        return _render_error(
            "后台暂不可用",
            "后台安全配置未完成。",
            503,
        )
    if request.path == "/admin/login":
        if request.method == "POST" and not csrf_is_valid():
            abort(403)
        if request.method == "POST" and not consume_rate_limit(
            "admin_login",
            current_app.config["LOGIN_RATE_LIMIT"],
            current_app.config["LOGIN_RATE_WINDOW"],
        ):
            return _admin_rate_limit_response(
                current_app.config["LOGIN_RATE_WINDOW"]
            )
        return None
    if not check_admin_auth():
        return redirect(url_for("admin.admin_login", next=request.path))
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not csrf_is_valid():
        abort(403)
    if request.path == "/admin/scrape" and request.method == "POST":
        if not consume_rate_limit(
            "admin_scrape",
            current_app.config["SCRAPE_RATE_LIMIT"],
            current_app.config["SCRAPE_RATE_WINDOW"],
        ):
            return rate_limit_response(current_app.config["SCRAPE_RATE_WINDOW"])
    return None


def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
    )
    return response


def audit_admin_actions(response):
    if request.path.startswith("/admin") and request.method in {
        "POST", "PUT", "PATCH", "DELETE"
    }:
        actor = getattr(g, "audit_actor", None) or session.get(
            "admin_username"
        ) or "anonymous"
        action = (request.endpoint or "unmatched_admin_request").rsplit(".", 1)[-1]
        db = None
        try:
            db = get_db()
            db.execute(
                "INSERT INTO admin_audit_logs "
                "(actor, action, status_code, ip_hash) VALUES (?,?,?,?)",
                (actor, action, response.status_code, request_identity_hash()),
            )
            db.commit()
        except sqlite3.Error:
            current_app.logger.error("Failed to write admin audit event")
        finally:
            if db is not None:
                db.close()
    return response
