#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Enterprise AI transformation platform application factory."""

import io
import ipaddress
import os
import re
import unicodedata
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from flask import Flask, abort, g, request, url_for
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.middleware.proxy_fix import ProxyFix

import analytics_repository
from blueprints.admin import bp as admin_bp
from blueprints.assessment import bp as assessment_bp
from blueprints.api import bp as api_bp
from blueprints.public import bp as public_bp, svc_emoji
from blueprints.public_catalog import bp as public_catalog_bp
from blueprints.media import bp as media_bp
from models import init_db
from security import (add_security_headers, audit_admin_actions, check_admin_auth,
                      csrf_token, data_conflict, forbidden, invalid_form,
                      not_found, protect_admin_routes, request_too_large,
                      sanitize_html, unexpected_error)
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
    "MAX_CONTENT_LENGTH": 22 * 1024 * 1024,
    "MEDIA_UPLOAD_ROOT": os.environ.get("AI_PLATFORM_MEDIA_ROOT"),
    "PUBLIC_BASE_URL": os.environ.get("AI_PLATFORM_PUBLIC_BASE_URL"),
    "MEDIA_IMAGE_MAX_BYTES": 8 * 1024 * 1024,
    "MEDIA_ATTACHMENT_MAX_BYTES": 20 * 1024 * 1024,
    "MEDIA_IMAGE_MAX_PIXELS": 40_000_000,
    "MEDIA_OOXML_MAX_MEMBERS": 1024,
    "MEDIA_OOXML_MAX_UNCOMPRESSED_BYTES": 100 * 1024 * 1024,
    "MEDIA_OOXML_MAX_COMPRESSION_RATIO": 20,
    "MEDIA_OOXML_XML_MAX_NODES": 250_000,
    "MEDIA_OOXML_XML_MAX_DEPTH": 128,
    "MEDIA_OOXML_XML_MAX_CHARACTERS": 8_000_000,
    "MEDIA_PDF_MAX_PAGES": 500,
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
    "ANALYTICS_EVENT_RATE_LIMIT": 120,
    "ANALYTICS_EVENT_RATE_WINDOW": 60 * 60,
    "APPOINTMENT_NOW_PROVIDER": None,
    "ADMIN_NOW_PROVIDER": None,
    "PRIVACY_PROCESSOR_NAME": os.environ.get(
        "AI_PLATFORM_PRIVACY_PROCESSOR_NAME"
    ),
    "PRIVACY_CONTACT": os.environ.get("AI_PLATFORM_PRIVACY_CONTACT"),
    "PRIVACY_POLICY_URL": os.environ.get("AI_PLATFORM_PRIVACY_POLICY_URL"),
    "SCRAPE_RATE_LIMIT": 3,
    "SCRAPE_RATE_WINDOW": 60 * 60,
}

ANALYTICS_CONFIG_ENDPOINT = "assessment_v2.assessment_config"
_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


def enable_public_analytics_response():
    """Mark an analytics-enabled response and establish its hashed identity."""
    g.public_analytics_response = True
    analytics_repository.session_analytics_id_hash()
    return ""


def establish_config_analytics_session():
    """Bootstrap analytics for the stateful assessment config response."""
    if (
        request.method == "GET"
        and request.endpoint == ANALYTICS_CONFIG_ENDPOINT
    ):
        enable_public_analytics_response()


def add_public_analytics_cache_policy(response):
    if getattr(g, "public_analytics_response", False) or getattr(
        g, "admin_response", False
    ):
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


def enforce_request_size_policy():
    """Keep 1 MiB everywhere except the authenticated media upload adapter."""
    if request.path.startswith("/admin"):
        g.admin_response = True
    if (
        request.method == "POST"
        and request.endpoint == "admin.admin_media"
        and check_admin_auth()
    ):
        return None
    maximum = 1024 * 1024
    request.max_content_length = maximum
    if request.content_length is None:
        if request.environ.get("wsgi.input_terminated"):
            body = bytearray()
            stream = request.environ["wsgi.input"]
            while len(body) <= maximum:
                chunk = stream.read(maximum + 1 - len(body))
                if not chunk:
                    break
                body.extend(chunk)
            if len(body) > maximum:
                abort(413)
            request.environ["wsgi.input"] = io.BytesIO(bytes(body))
            request.environ["CONTENT_LENGTH"] = str(len(body))
        return None
    if request.content_length > request.max_content_length:
        abort(413)
    return None


def media_image_url(asset_id):
    return url_for("media.published_image", asset_id=asset_id)


def media_download_url(asset_id):
    return url_for("media.published_download", asset_id=asset_id)


def _valid_public_hostname(hostname):
    """Validate a configured origin host without resolving or contacting it."""
    if type(hostname) is not str or not hostname:
        return False
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        pass
    try:
        ascii_hostname = hostname.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return False
    if (
        not ascii_hostname or len(ascii_hostname) > 253
        or ascii_hostname.startswith(".") or ascii_hostname.endswith(".")
    ):
        return False
    return all(
        1 <= len(label) <= 63 and _HOST_LABEL.fullmatch(label)
        for label in ascii_hostname.split(".")
    )


def _strict_public_base_url(value):
    """Accept only an unambiguous, literal HTTPS origin from deployment config."""
    if type(value) is not str or any(
        unicodedata.category(character).startswith("C") for character in value
    ):
        raise ValueError("PUBLIC_BASE_URL must be an HTTPS origin")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as error:
        raise ValueError("PUBLIC_BASE_URL must be an HTTPS origin") from error
    origin = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
    if (
        parts.scheme != "https" or not parts.netloc
        or not _valid_public_hostname(parts.hostname)
        or parts.username is not None or parts.password is not None
        or port == 0 or parts.path or parts.query or parts.fragment or value != origin
    ):
        raise ValueError("PUBLIC_BASE_URL must be an HTTPS origin")
    return origin


def create_app(test_config=None):
    """Build an isolated Flask application instance."""
    flask_app = Flask(__name__)
    flask_app.config.from_mapping(DEFAULT_CONFIG)
    if test_config:
        flask_app.config.update(test_config)
    flask_app.config["PUBLIC_BASE_URL"] = _strict_public_base_url(
        flask_app.config.get("PUBLIC_BASE_URL")
    )
    if not flask_app.config.get("MEDIA_UPLOAD_ROOT"):
        flask_app.config["MEDIA_UPLOAD_ROOT"] = str(
            Path(__file__).resolve().parent / "data" / "media"
        )
    flask_app.wsgi_app = ProxyFix(flask_app.wsgi_app, x_for=1, x_proto=1)

    flask_app.jinja_env.globals.update(
        csrf_token=csrf_token,
        enable_public_analytics_response=enable_public_analytics_response,
        svc_emoji=svc_emoji,
        media_image_url=media_image_url,
        media_download_url=media_download_url,
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
    flask_app.before_request(enforce_request_size_policy)
    flask_app.before_request(protect_admin_routes)
    flask_app.before_request(establish_config_analytics_session)
    flask_app.after_request(add_public_analytics_cache_policy)
    flask_app.after_request(add_security_headers)
    flask_app.after_request(audit_admin_actions)

    flask_app.register_blueprint(public_bp)
    flask_app.register_blueprint(public_catalog_bp)
    flask_app.register_blueprint(api_bp)
    flask_app.register_blueprint(assessment_bp)
    flask_app.register_blueprint(admin_bp)
    flask_app.register_blueprint(media_bp)
    return flask_app


app = create_app()


if __name__ == "__main__":
    init_db()
    print("Enterprise AI Transformation Platform")
    print("Open http://127.0.0.1:5080")
    app.run(host="127.0.0.1", port=5080, debug=False, threaded=True)
