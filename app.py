#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Enterprise AI transformation platform application factory."""

import os
from datetime import timedelta

from flask import Flask
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.middleware.proxy_fix import ProxyFix

from blueprints.admin import bp as admin_bp
from blueprints.assessment import bp as assessment_bp
from blueprints.api import bp as api_bp
from blueprints.public import bp as public_bp, svc_emoji
from models import init_db
from security import (add_security_headers, audit_admin_actions, csrf_token,
                      data_conflict, forbidden, invalid_form, not_found,
                      protect_admin_routes, request_too_large, sanitize_html,
                      unexpected_error)
from repository import DataConflictError
from validation import ValidationError, safe_external_url


DEFAULT_CONFIG = {
    "SECRET_KEY": os.environ.get("AI_PLATFORM_SECRET_KEY"),
    "ADMIN_USERNAME": os.environ.get("AI_PLATFORM_ADMIN_USERNAME"),
    "ADMIN_PASSWORD_HASH": os.environ.get("AI_PLATFORM_ADMIN_PASSWORD_HASH"),
    "SESSION_COOKIE_HTTPONLY": True,
    "SESSION_COOKIE_SECURE": True,
    "SESSION_COOKIE_SAMESITE": "Lax",
    "PERMANENT_SESSION_LIFETIME": timedelta(hours=8),
    "MAX_CONTENT_LENGTH": 1024 * 1024,
    "LOGIN_RATE_LIMIT": 10,
    "LOGIN_RATE_WINDOW": 15 * 60,
    "ASSESSMENT_RATE_LIMIT": 30,
    "ASSESSMENT_RATE_WINDOW": 60 * 60,
    "ASSESSMENT_PREVIEW_RATE_LIMIT": 60,
    "ASSESSMENT_PREVIEW_RATE_WINDOW": 60 * 60,
    "ASSESSMENT_COMPLETE_RATE_LIMIT": 10,
    "ASSESSMENT_COMPLETE_RATE_WINDOW": 60 * 60,
    "APPOINTMENT_RATE_LIMIT": 5,
    "APPOINTMENT_RATE_WINDOW": 60 * 60,
    "APPOINTMENT_NOW_PROVIDER": None,
    "PRIVACY_PROCESSOR_NAME": os.environ.get(
        "AI_PLATFORM_PRIVACY_PROCESSOR_NAME"
    ),
    "PRIVACY_CONTACT": os.environ.get("AI_PLATFORM_PRIVACY_CONTACT"),
    "PRIVACY_POLICY_URL": os.environ.get("AI_PLATFORM_PRIVACY_POLICY_URL"),
    "SCRAPE_RATE_LIMIT": 3,
    "SCRAPE_RATE_WINDOW": 60 * 60,
}


def create_app(test_config=None):
    """Build an isolated Flask application instance."""
    flask_app = Flask(__name__)
    flask_app.config.from_mapping(DEFAULT_CONFIG)
    if test_config:
        flask_app.config.update(test_config)
    flask_app.wsgi_app = ProxyFix(flask_app.wsgi_app, x_for=1, x_proto=1)

    flask_app.jinja_env.globals.update(
        csrf_token=csrf_token,
        svc_emoji=svc_emoji,
    )
    flask_app.jinja_env.filters.update(
        safe_html=sanitize_html,
        safe_url=safe_external_url,
    )

    flask_app.register_error_handler(ValidationError, invalid_form)
    flask_app.register_error_handler(DataConflictError, data_conflict)
    flask_app.register_error_handler(403, forbidden)
    flask_app.register_error_handler(404, not_found)
    flask_app.register_error_handler(RequestEntityTooLarge, request_too_large)
    flask_app.register_error_handler(Exception, unexpected_error)
    flask_app.before_request(protect_admin_routes)
    flask_app.after_request(add_security_headers)
    flask_app.after_request(audit_admin_actions)

    flask_app.register_blueprint(public_bp)
    flask_app.register_blueprint(api_bp)
    flask_app.register_blueprint(assessment_bp)
    flask_app.register_blueprint(admin_bp)
    return flask_app


app = create_app()


if __name__ == "__main__":
    init_db()
    print("Enterprise AI Transformation Platform")
    print("Open http://127.0.0.1:5080")
    app.run(host="127.0.0.1", port=5080, debug=False, threaded=True)
