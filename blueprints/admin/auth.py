"""Administrator login and logout routes."""

import secrets
from hmac import compare_digest

from flask import current_app, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from blueprints.admin import bp
from security import check_admin_auth


@bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        username_ok = compare_digest(username, current_app.config["ADMIN_USERNAME"])
        password_ok = check_password_hash(
            current_app.config["ADMIN_PASSWORD_HASH"], password
        )
        if not (username_ok and password_ok):
            return render_template("admin/login.html", error="账号或密码错误"), 401
        session.clear()
        session["admin_username"] = current_app.config["ADMIN_USERNAME"]
        session["csrf_token"] = secrets.token_urlsafe(32)
        session.permanent = True
        return redirect(url_for("admin.admin_index"))
    if check_admin_auth():
        return redirect(url_for("admin.admin_index"))
    return render_template("admin/login.html")


@bp.route("/admin/logout", methods=["POST"])
def admin_logout():
    g.audit_actor = session.get("admin_username", "anonymous")
    session.clear()
    return redirect(url_for("admin.admin_login"))
