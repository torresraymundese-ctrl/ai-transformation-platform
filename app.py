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


def _validated_dns_idn_host(raw_host):
    """Return a non-lossy DNS/IDN host spelling, without resolving it."""
    try:
        ascii_host = raw_host.encode("idna").decode("ascii")
        decoded_host = ascii_host.encode("ascii").decode("idna")
        reencoded_host = decoded_host.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    if (
        raw_host != (ascii_host if raw_host.isascii() else decoded_host)
        or ascii_host != reencoded_host
        or any(unicodedata.category(character).startswith("C") for character in decoded_host)
        or not ascii_host or len(ascii_host) > 253
        or ascii_host.startswith(".") or ascii_host.endswith(".")
    ):
        return None
    if not all(
        1 <= len(label) <= 63 and _HOST_LABEL.fullmatch(label)
        for label in ascii_host.split(".")
    ):
        return None
    return raw_host


def _strict_public_authority(raw_netloc):
    """Validate and reconstruct a literal public-origin authority locally."""
    if type(raw_netloc) is not str or not raw_netloc or "@" in raw_netloc:
        return None
    if raw_netloc.startswith("["):
        closing = raw_netloc.find("]")
        if closing < 2:
            return None
        raw_host = raw_netloc[1:closing]
        remainder = raw_netloc[closing + 1:]
        if remainder:
            if not remainder.startswith(":"):
                return None
            remainder = remainder[1:]
        else:
            remainder = None
        if "%" in raw_host:
            return None
        try:
            host = f"[{ipaddress.IPv6Address(raw_host)}]"
        except ValueError:
            return None
    else:
        if "[" in raw_netloc or "]" in raw_netloc:
            return None
        raw_host, separator, remainder = raw_netloc.rpartition(":")
        if not separator:
            raw_host, remainder = raw_netloc, None
        elif not raw_host or ":" in raw_host:
            return None
        try:
            host = str(ipaddress.IPv4Address(raw_host))
            if host != raw_host:
                return None
        except ValueError:
            if re.fullmatch(r"[0-9.]+", raw_host):
                return None
            host = _validated_dns_idn_host(raw_host)
            if host is None:
                return None
    if remainder is None:
        return host
    if (
        not remainder or not remainder.isascii() or not remainder.isdecimal()
        or (len(remainder) > 1 and remainder.startswith("0"))
    ):
        return None
    port = int(remainder, 10)
    if not 1 <= port <= 65535 or str(port) != remainder:
        return None
    return f"{host}:{port}"


def _strict_public_base_url(value):
    """Accept only an unambiguous, literal HTTPS origin from deployment config."""
    if type(value) is not str or any(
        unicodedata.category(character).startswith("C") for character in value
    ):
        raise ValueError("PUBLIC_BASE_URL must be an HTTPS origin")
    try:
        parts = urlsplit(value)
    except ValueError as error:
        raise ValueError("PUBLIC_BASE_URL must be an HTTPS origin") from error
    authority = _strict_public_authority(parts.netloc)
    origin = urlunsplit(("https", authority or "", "", "", ""))
    if (
        parts.scheme != "https" or authority is None
        or parts.username is not None or parts.password is not None
        or parts.path or parts.query or parts.fragment or value != origin
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
