"""Public JSON API routes."""

import json
import re

from flask import Blueprint, current_app, jsonify, request

import content_repository
from security import consume_rate_limit, rate_limit_response


bp = Blueprint("api", __name__)
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


@bp.route("/api/assessment", methods=["POST"])
def api_assessment():
    if not consume_rate_limit(
        "assessment",
        current_app.config["ASSESSMENT_RATE_LIMIT"],
        current_app.config["ASSESSMENT_RATE_WINDOW"],
    ):
        return rate_limit_response(current_app.config["ASSESSMENT_RATE_WINDOW"])
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "invalid assessment payload"}), 400

    company = data.get("company", "")
    email = data.get("email", "")
    scores = data.get("scores")
    result = data.get("result", "")
    if not isinstance(company, str) or len(company.strip()) > 120:
        return jsonify({"error": "invalid assessment payload"}), 400
    if not isinstance(email, str) or len(email.strip()) > 254:
        return jsonify({"error": "invalid assessment payload"}), 400
    if email.strip() and not EMAIL_PATTERN.fullmatch(email.strip()):
        return jsonify({"error": "invalid assessment payload"}), 400
    if not isinstance(scores, dict) or not scores:
        return jsonify({"error": "invalid assessment payload"}), 400
    if not isinstance(result, str) or not result.strip() or len(result.strip()) > 120:
        return jsonify({"error": "invalid assessment payload"}), 400
    try:
        scores_json = json.dumps(scores, ensure_ascii=False)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid assessment payload"}), 400
    if len(scores_json.encode("utf-8")) > 16 * 1024:
        return jsonify({"error": "invalid assessment payload"}), 400

    content_repository.create_assessment(
        company.strip(), email.strip().lower(), scores_json, result.strip()
    )
    return jsonify({"success": True})
