"""Minimal shared-admin lead, appointment, and privacy workflows."""

import hashlib
import secrets

from flask import abort, current_app, redirect, render_template, request, session, url_for

import appointment_repository
from assessment_validation import BRANCH_CODES
from blueprints.admin import bp
import lead_repository
from validation import ValidationError, integer as valid_integer


def _admin_actor():
    return session.get("admin_username") or current_app.config["ADMIN_USERNAME"]


def _now_provider():
    return current_app.config.get("ADMIN_NOW_PROVIDER")


def _lead_filters():
    status = request.args.get("status", "").strip()
    branch = request.args.get("branch", "").strip()
    if status and status not in lead_repository.LEAD_STATUSES:
        raise ValidationError("status has an invalid value")
    if branch and branch not in BRANCH_CODES:
        raise ValidationError("branch has an invalid value")
    return {
        "status": status or None,
        "branch": branch or None,
        "date_from": lead_repository.parse_date_filter(
            request.args.get("date_from", ""), "date_from"
        ),
        "date_to": lead_repository.parse_date_filter(
            request.args.get("date_to", ""), "date_to"
        ),
    }


@bp.route("/admin/leads")
def admin_leads():
    filters = _lead_filters()
    return render_template(
        "admin/leads.html",
        leads=lead_repository.list_leads(**filters),
        filters=filters,
        statuses=lead_repository.LEAD_STATUSES,
        branches=tuple(sorted(BRANCH_CODES)),
    )


@bp.route("/admin/lead/<int:lead_id>", methods=["GET", "POST"])
def admin_lead_detail(lead_id):
    detail = lead_repository.get_lead_detail(lead_id)
    if detail is None:
        abort(404)
    if request.method == "POST":
        action = request.form.get("action", "")
        now = _now_provider()
        if action == "owner":
            lead_repository.set_lead_owner(
                lead_id, request.form.get("owner_text", ""), now=now
            )
        elif action == "status":
            lead_repository.transition_lead_status(
                lead_id,
                request.form.get("new_status", ""),
                _admin_actor(),
                now=now,
            )
        elif action == "followup":
            lead_repository.add_followup(
                lead_id,
                request.form.get("followup_note", ""),
                request.form.get("next_followup_at", ""),
                _admin_actor(),
                now=now,
            )
        else:
            raise ValidationError("action has an invalid value")
        return redirect(url_for("admin.admin_lead_detail", lead_id=lead_id))
    return render_template(
        "admin/lead_detail.html",
        detail=detail,
        status_transitions=lead_repository.LEAD_TRANSITIONS.get(
            detail["lead"]["status"], ()
        ),
    )


@bp.route("/admin/appointments", methods=["GET", "POST"])
def admin_appointments():
    if request.method == "POST":
        if request.form.get("action") != "transition":
            raise ValidationError("action has an invalid value")
        appointment_id = valid_integer(
            request.form, "appointment_id", minimum=1, maximum=2_147_483_647
        )
        new_status = request.form.get("new_status", "")
        if new_status not in appointment_repository.STATUS_TIMESTAMPS:
            raise ValidationError("new_status has an invalid value")
        appointment_repository.transition_appointment_status(
            appointment_id, new_status
        )
        return redirect(url_for("admin.admin_appointments"))

    status = request.args.get("status", "").strip()
    if status and status not in appointment_repository.ALLOWED_TRANSITIONS:
        raise ValidationError("status has an invalid value")
    return render_template(
        "admin/appointments.html",
        appointments=appointment_repository.list_appointments(
            status=status or None
        ),
        selected_status=status,
        statuses=tuple(appointment_repository.ALLOWED_TRANSITIONS),
        transitions=appointment_repository.ALLOWED_TRANSITIONS,
    )


@bp.route("/admin/data-requests", methods=["GET", "POST"])
def admin_data_requests():
    if request.method == "POST":
        action = request.form.get("action", "")
        now = _now_provider()
        if action == "create":
            if request.form.get("verification_confirmed") != "yes":
                raise ValidationError("verification is required")
            lead_id = valid_integer(
                request.form, "lead_id", minimum=1, maximum=2_147_483_647
            )
            identity_hash = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
            lead_repository.create_data_subject_request(
                lead_id,
                request.form.get("request_type", ""),
                request.form.get("channel", ""),
                request.form.get("requested_at", ""),
                identity_hash,
                now=now,
            )
        elif action == "transition":
            request_id = valid_integer(
                request.form, "request_id", minimum=1, maximum=2_147_483_647
            )
            lead_repository.transition_data_subject_request(
                request_id,
                request.form.get("new_status", ""),
                request.form.get("resolution_note", ""),
                now=now,
            )
        elif action == "complete":
            request_id = valid_integer(
                request.form, "request_id", minimum=1, maximum=2_147_483_647
            )
            lead_repository.complete_data_subject_request(
                request_id,
                request.form.get("resolution_note", ""),
                confirm_anonymization=(
                    request.form.get("confirm_anonymization") == "yes"
                ),
                now=now,
            )
        else:
            raise ValidationError("action has an invalid value")
        return redirect(url_for("admin.admin_data_requests"))

    status = request.args.get("status", "").strip()
    if status and status not in lead_repository.DATA_REQUEST_STATUSES:
        raise ValidationError("status has an invalid value")
    return render_template(
        "admin/data_requests.html",
        data_requests=lead_repository.list_data_subject_requests(
            status=status or None
        ),
        leads=lead_repository.list_leads(include_anonymized=False),
        selected_status=status,
        statuses=tuple(sorted(lead_repository.DATA_REQUEST_STATUSES)),
        request_types=tuple(sorted(lead_repository.DATA_REQUEST_TYPES)),
        channels=tuple(sorted(lead_repository.DATA_REQUEST_CHANNELS)),
    )
