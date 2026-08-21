"""Atomic orchestration for a consented, deterministic assessment report."""

import analytics_repository
import assessment_repository
import lead_repository
from assessment.contracts import AssessmentInputError, CompletionResult
from assessment.matching import match_scenarios
from assessment.reporting import build_report_snapshot
from assessment.roi import calculate_roi
from assessment.scoring import score_assessment
from repository import run_transaction
from validation import ValidationError, validated_submission_key


PRIVATE_REPORT_KEYS = frozenset(
    {
        "company_name",
        "contact_name",
        "phone",
        "phone_normalized",
        "email",
        "contact_email",
        "wechat",
    }
)


def complete_assessment(request, identity_hash):
    submission_key = validated_submission_key(request.submission_key)

    def operation(db):
        db.execute("BEGIN IMMEDIATE")
        existing = assessment_repository.find_by_submission_key(db, submission_key)
        if existing is not None:
            return CompletionResult(existing["id"], existing["lead_id"], False)

        try:
            attribution_source = _validate_request(request, identity_hash)
            catalog = assessment_repository.load_catalog(
                db, request.profile.branch_code
            )
            _validate_profile_catalog_membership(db, request.profile, catalog)
            scores = score_assessment(catalog, request.profile)
            scenarios = assessment_repository.load_scenarios(db, catalog.version_id)
            services = assessment_repository.load_service_packages(
                db, catalog.version_id
            )
            matches = match_scenarios(request.profile, scores, scenarios, services)
            ranges = assessment_repository.load_roi_option_ranges(
                db, catalog.version_id
            )
            primary = matches[0]
            roi = calculate_roi(
                request.profile.roi_choices,
                ranges,
                primary.scenario,
                primary.service,
            )
            report_snapshot = build_report_snapshot(
                request.profile, scores, matches, roi, catalog, ranges
            )
            _assert_private_report(report_snapshot)
        except ValidationError:
            raise
        except (AssessmentInputError, KeyError, TypeError, ValueError):
            raise ValidationError("assessment has an invalid value") from None

        completed_at = lead_repository.current_shanghai_datetime()
        lead_id = lead_repository.find_or_create(
            db, request.contact, attribution_source, completed_at
        )
        lead_repository.record_consent(
            db, lead_id, request.consent, identity_hash, completed_at
        )
        assessment_id = assessment_repository.insert_completed(
            db,
            lead_id,
            request,
            submission_key,
            catalog,
            scores,
            matches,
            report_snapshot,
            completed_at,
        )
        analytics_repository.insert_server_event(
            db, "assessment_completed", assessment_id
        )
        analytics_repository.insert_server_event(db, "lead_submitted", assessment_id)
        return CompletionResult(assessment_id, lead_id, True)

    return run_transaction(operation)


def _validate_request(request, identity_hash):
    if request.consent.accepted is not True:
        raise ValidationError("consent must be accepted")
    source = _bounded_text(request.attribution.source, "source", required=True)
    _bounded_text(request.attribution.utm_source, "utm_source")
    _bounded_text(request.attribution.utm_medium, "utm_medium")
    _bounded_text(request.attribution.utm_campaign, "utm_campaign")
    lead_repository.validate_contact(request.contact)
    lead_repository.validate_consent(request.consent, identity_hash)
    return source


def _validate_profile_catalog_membership(db, profile, catalog):
    if profile.subbranch_code not in catalog.subbranch_codes:
        raise ValidationError("assessment has an invalid value")
    if profile.department_code not in catalog.department_codes:
        raise ValidationError("assessment has an invalid value")
    if not assessment_repository.is_published_company_size(
        db, profile.company_size_code
    ):
        raise ValidationError("assessment has an invalid value")
    if not 1 <= len(profile.pain_codes) <= 3 or len(set(profile.pain_codes)) != len(
        profile.pain_codes
    ):
        raise ValidationError("assessment has an invalid value")
    if any(code not in catalog.pain_codes for code in profile.pain_codes):
        raise ValidationError("assessment has an invalid value")


def _bounded_text(value, field_name, required=False):
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be text")
    value = value.strip()
    if required and not value:
        raise ValidationError(f"{field_name} is required")
    if len(value) > 100:
        raise ValidationError(f"{field_name} is too long")
    return value


def _assert_private_report(value):
    if isinstance(value, dict):
        if PRIVATE_REPORT_KEYS.intersection(value):
            raise ValidationError("report contains private fields")
        for nested in value.values():
            _assert_private_report(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_private_report(nested)
