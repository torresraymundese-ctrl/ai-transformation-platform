"""Atomic orchestration for a consented, deterministic assessment report."""

import analytics_repository
import assessment_repository
import lead_repository
from assessment.contracts import AssessmentInputError, CompletionResult
from assessment.reporting import (
    REPORT_ROI_BAND_LABELS,
    REPORT_SERVICE_CATEGORY_LABELS,
    ReportLegalCopy,
    ReportLegalVersion,
    ReportPublicCopy,
)
from assessment_flow import IssuedFlow
from assessment.matching import match_scenarios
from assessment.reporting import build_report_snapshot
from assessment.roi import calculate_roi
from assessment.scoring import score_assessment
from repository import run_transaction
from legal_repository import LegalVersionIds, load_legal_bundle
from repository import DataConflictError
from rule_release_runtime import load_rule_bundle
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


def complete_assessment(request, identity_hash, issued_flow):
    submission_key = validated_submission_key(request.submission_key)
    if type(issued_flow) is not IssuedFlow:
        raise ValidationError("invalid assessment flow")

    def operation(db):
        db.execute("BEGIN IMMEDIATE")
        rule_bundle = load_rule_bundle(
            db, issued_flow.rule_version_id, issued_flow.branch_code
        )
        legal_bundle = load_legal_bundle(
            db,
            LegalVersionIds(
                privacy=issued_flow.privacy_id,
                terms=issued_flow.terms_id,
                roi_disclaimer=issued_flow.roi_disclaimer_id,
                ai_content_notice=issued_flow.ai_notice_id,
            ),
        )
        existing = assessment_repository.find_by_submission_key(db, submission_key)
        if existing is not None:
            expected_legal = {
                "privacy": issued_flow.privacy_id,
                "terms": issued_flow.terms_id,
                "roi_disclaimer": issued_flow.roi_disclaimer_id,
                "ai_content_notice": issued_flow.ai_notice_id,
            }
            if (
                existing["branch_code"] != issued_flow.branch_code
                or existing["rule_version_id"] != issued_flow.rule_version_id
                or assessment_repository.load_assessment_legal_ids(
                    db, existing["id"]
                )
                != expected_legal
            ):
                raise DataConflictError("assessment binding conflict")
            return CompletionResult(existing["id"], existing["lead_id"], False)

        try:
            attribution_source = _validate_request(
                request, identity_hash, legal_bundle.privacy.version_code
            )
            catalog = rule_bundle.catalog
            _validate_profile_catalog_membership(
                request.profile, catalog, rule_bundle.public_config
            )
            scores = score_assessment(catalog, request.profile)
            scenarios = rule_bundle.scenarios
            services = rule_bundle.services
            matches = match_scenarios(request.profile, scores, scenarios, services)
            ranges = rule_bundle.roi_ranges
            primary = matches[0]
            roi = calculate_roi(
                request.profile.roi_choices,
                ranges,
                primary.scenario,
                primary.service,
            )
            report_snapshot = build_report_snapshot(
                request.profile,
                scores,
                matches,
                roi,
                catalog,
                ranges,
                public_copy=_report_public_copy(rule_bundle),
                legal_copy=_report_legal_copy(legal_bundle),
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
            db,
            lead_id,
            request.consent,
            identity_hash,
            legal_bundle.privacy.id,
            completed_at,
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
            legal_bundle,
            completed_at,
        )
        analytics_repository.insert_server_event(
            db,
            "assessment_completed",
            assessment_id,
            created_at=completed_at,
        )
        analytics_repository.insert_server_event(
            db,
            "lead_submitted",
            assessment_id,
            created_at=completed_at,
        )
        return CompletionResult(assessment_id, lead_id, True)

    return run_transaction(operation)


def _report_public_copy(rule_bundle):
    labels = rule_bundle.release.public_labels
    return ReportPublicCopy(
        risk_explanations=labels.risk_explanations,
        display_labels={
            "dimensions": labels.dimensions,
            "maturities": labels.maturities,
            "scenarios": {
                scenario.code: scenario.public_name
                for scenario in rule_bundle.release.scenarios
            },
            "integrations": labels.integrations,
            "service_categories": REPORT_SERVICE_CATEGORY_LABELS,
            "risk_labels": labels.risk_labels,
            "roi_bands": REPORT_ROI_BAND_LABELS,
            "roi_groups": labels.roi_groups,
            "roi_options": labels.roi_options,
        },
    )


def _report_legal_copy(bundle):
    versions = tuple(
        ReportLegalVersion(
            document_type=document_type,
            legal_version_id=version.id,
            version_code=version.version_code,
            content_sha256=version.content_sha256,
            public_path=f"/legal/{document_type}/{version.version_code}",
            external_url=None,
        )
        for document_type, version in (
            ("privacy", bundle.privacy),
            ("terms", bundle.terms),
            ("roi_disclaimer", bundle.roi_disclaimer),
            ("ai_content_notice", bundle.ai_content_notice),
        )
    )
    return ReportLegalCopy(
        versions=versions,
        notices={
            "roi_disclaimer": bundle.roi_disclaimer.body_summary,
            "ai_content_notice": bundle.ai_content_notice.body_summary,
        },
    )


def _validate_request(request, identity_hash, privacy_version_code):
    if request.consent.accepted is not True:
        raise ValidationError("consent must be accepted")
    source = _bounded_text(request.attribution.source, "source", required=True)
    _bounded_text(request.attribution.utm_source, "utm_source")
    _bounded_text(request.attribution.utm_medium, "utm_medium")
    _bounded_text(request.attribution.utm_campaign, "utm_campaign")
    lead_repository.validate_contact(request.contact)
    lead_repository.validate_consent(request.consent, identity_hash)
    if request.consent.policy_version != privacy_version_code:
        raise ValidationError("consent policy does not match assessment flow")
    return source


def _validate_profile_catalog_membership(profile, catalog, public_config):
    if profile.subbranch_code not in catalog.subbranch_codes:
        raise ValidationError("assessment has an invalid value")
    if profile.department_code not in catalog.department_codes:
        raise ValidationError("assessment has an invalid value")
    if profile.company_size_code not in {
        item["code"] for item in public_config["company_sizes"]
    }:
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
