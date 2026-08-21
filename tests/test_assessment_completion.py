import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

import analytics_repository
import lead_repository
import models
from assessment.contracts import (
    AssessmentProfile,
    Attribution,
    CompletionRequest,
    Consent,
    Contact,
)
from assessment_completion_service import complete_assessment
from validation import ValidationError


UUID_1 = "550e8400-e29b-41d4-a716-446655440000"
UUID_2 = "6ba7b810-9dad-41d1-80b4-00c04fd430c8"
UUID_3 = "123e4567-e89b-42d3-a456-426614174000"
QUESTION_CODES = (
    "business_value_frequency",
    "business_value_scope",
    "process_documentation",
    "process_stability",
    "data_availability",
    "data_quality",
    "systems_foundation",
    "systems_automation",
    "organization_owner",
    "organization_adoption",
    "delivery_budget",
    "delivery_timeline",
)


@pytest.fixture()
def completion_db(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "DB_PATH", str(tmp_path / "completion.db"))
    models.init_db()
    return models.DB_PATH


def valid_completion(key=UUID_1, *, phone="13800138000"):
    return CompletionRequest(
        submission_key=key,
        profile=AssessmentProfile(
            branch_code="manufacturing",
            subbranch_code="discrete_manufacturing",
            department_code="production",
            company_size_code="50_200",
            pain_codes=("production_reporting",),
            answers={code: "level_3" for code in QUESTION_CODES},
            roi_choices={
                "headcount": "6_20",
                "monthly_hours": "20_80",
                "monthly_cost": "8000_15000",
                "loss_factor": "normal",
                "budget": "50000_200000",
            },
        ),
        contact=Contact(
            company_name="Company-PII-7f9c",
            contact_name="Contact-PII-8a2d",
            phone=phone,
            email="private-7f9c@example.invalid",
            wechat="wechat-private-8a2d",
        ),
        consent=Consent(accepted=True, policy_version="2026-08-19"),
        attribution=Attribution(
            source="website_assessment",
            utm_source="organic",
            utm_medium="website",
            utm_campaign="task-7",
        ),
    )


def rows(statement, parameters=()):
    db = models.get_db()
    try:
        return db.execute(statement, parameters).fetchall()
    finally:
        db.close()


def counts():
    db = models.get_db()
    try:
        return {
            table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "leads",
                "lead_consents",
                "assessments",
                "roi_estimates",
                "analytics_events",
            )
        }
    finally:
        db.close()


def test_completion_creates_atomic_lead_consent_assessment_roi_and_events(
    completion_db,
):
    result = complete_assessment(valid_completion(), "hashed-ip")

    lead = rows("SELECT * FROM leads WHERE id=?", (result.lead_id,))[0]
    assessment = rows(
        "SELECT * FROM assessments WHERE id=?", (result.assessment_id,)
    )[0]
    consent = rows("SELECT * FROM lead_consents WHERE lead_id=?", (lead["id"],))[0]
    estimate = rows(
        "SELECT * FROM roi_estimates WHERE assessment_id=?", (assessment["id"],)
    )[0]
    events = rows(
        "SELECT event_name FROM analytics_events WHERE assessment_id=? "
        "ORDER BY id",
        (assessment["id"],),
    )

    assert result.created is True
    assert lead["phone_normalized"] == "13800138000"
    assert assessment["lead_id"] == lead["id"]
    assert assessment["report_snapshot_json"]
    assert estimate["rule_version_id"] == assessment["rule_version_id"]
    assert consent["policy_version"] == "2026-08-19"
    assert [event["event_name"] for event in events] == [
        "assessment_completed",
        "lead_submitted",
    ]
    created_at = datetime.fromisoformat(lead["created_at"])
    expires_at = datetime.fromisoformat(lead["retention_expires_at"])
    assert expires_at - created_at == timedelta(days=365)


def test_completion_uses_shanghai_wall_clock_for_exact_365_day_retention(
    completion_db, monkeypatch
):
    clock_calls = []

    class UtcHostDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            clock_calls.append(tz)
            if tz is None:
                return cls(2026, 8, 20, 16, 30, 0)
            assert tz is lead_repository.SHANGHAI
            return cls(2026, 8, 21, 0, 30, 0, tzinfo=tz)

    monkeypatch.setattr(lead_repository, "datetime", UtcHostDatetime)

    result = complete_assessment(valid_completion(), "hashed-ip")

    lead = rows(
        "SELECT created_at,updated_at,retention_expires_at FROM leads WHERE id=?",
        (result.lead_id,),
    )[0]
    assessment = rows(
        "SELECT completed_at,created_at FROM assessments WHERE id=?",
        (result.assessment_id,),
    )[0]
    consent = rows(
        "SELECT consented_at,created_at FROM lead_consents WHERE lead_id=?",
        (result.lead_id,),
    )[0]
    roi = rows(
        "SELECT created_at FROM roi_estimates WHERE assessment_id=?",
        (result.assessment_id,),
    )[0]
    events = rows(
        "SELECT event_name,created_at FROM analytics_events "
        "WHERE assessment_id=? ORDER BY event_name",
        (result.assessment_id,),
    )
    expected_timestamp = "2026-08-21 00:30:00"
    assert clock_calls == [lead_repository.SHANGHAI]
    assert dict(lead) == {
        "created_at": expected_timestamp,
        "updated_at": expected_timestamp,
        "retention_expires_at": "2027-08-21 00:30:00",
    }
    assert tuple(assessment) == (expected_timestamp, expected_timestamp)
    assert tuple(consent) == (expected_timestamp, expected_timestamp)
    assert roi["created_at"] == expected_timestamp
    assert [tuple(event) for event in events] == [
        ("assessment_completed", expected_timestamp),
        ("lead_submitted", expected_timestamp),
    ]


def test_primary_recommendation_supplies_the_single_roi_and_private_snapshot(
    completion_db,
):
    request = valid_completion()
    result = complete_assessment(request, "hashed-ip")
    assessment = rows(
        "SELECT report_snapshot_json FROM assessments WHERE id=?",
        (result.assessment_id,),
    )[0]
    estimate = rows(
        "SELECT recommended_scenarios_json,estimate_snapshot_json "
        "FROM roi_estimates WHERE assessment_id=?",
        (result.assessment_id,),
    )[0]

    snapshot = json.loads(assessment["report_snapshot_json"])
    scenarios = json.loads(estimate["recommended_scenarios_json"])
    roi_snapshot = json.loads(estimate["estimate_snapshot_json"])
    serialized = json.dumps(snapshot, ensure_ascii=False)

    assert snapshot["calculation_basis"]["selected_scenario"] == scenarios[0]
    assert len(scenarios) > 1
    assert roi_snapshot == snapshot["roi"]
    assert snapshot["recommendations"][0]["scenario"]["code"] == scenarios[0]
    for private_value in (
        request.contact.company_name,
        request.contact.contact_name,
        request.contact.phone,
        request.contact.email,
        request.contact.wechat,
    ):
        assert private_value not in serialized
    assert not {
        "company_name",
        "contact_name",
        "phone",
        "phone_normalized",
        "email",
        "contact_email",
        "wechat",
    } & set(_all_keys(snapshot))


def test_foundation_fallback_supplies_a_complete_roi_snapshot(completion_db):
    request = valid_completion()
    fallback_profile = replace(
        request.profile,
        answers={code: "level_0" for code in QUESTION_CODES},
        roi_choices={**request.profile.roi_choices, "budget": "under_50000"},
    )

    result = complete_assessment(replace(request, profile=fallback_profile), "ip")
    snapshot = json.loads(
        rows(
            "SELECT report_snapshot_json FROM assessments WHERE id=?",
            (result.assessment_id,),
        )[0][0]
    )

    assert snapshot["calculation_basis"]["selected_scenario"] == (
        "data_process_foundation"
    )
    assert set(snapshot["roi"]) == {"conservative", "midpoint", "ideal"}


def test_same_normalized_phone_refreshes_lead_but_keeps_each_assessment(
    completion_db,
):
    first = complete_assessment(valid_completion(phone="+86 138 0013 8000"), "ip")
    changed = replace(
        valid_completion(UUID_2, phone="138-0013-8000"),
        contact=Contact(
            company_name="更新企业",
            contact_name="更新联系人",
            phone="138-0013-8000",
            email="updated@example.invalid",
            wechat="updated-wechat",
        ),
    )
    second = complete_assessment(changed, "ip")

    lead = rows("SELECT * FROM leads WHERE id=?", (first.lead_id,))[0]
    assert first.lead_id == second.lead_id
    assert first.assessment_id != second.assessment_id
    assert lead["company_name"] == "更新企业"
    assert lead["contact_name"] == "更新联系人"
    assert lead["email"] == "updated@example.invalid"
    assert lead["wechat"] == "updated-wechat"
    assert len(rows("SELECT id FROM lead_consents WHERE lead_id=?", (lead["id"],))) == 2


def test_submission_key_returns_original_result_without_duplicate_writes(completion_db):
    request = valid_completion()

    first = complete_assessment(request, "ip")
    changed_retry = replace(
        request,
        contact=Contact("ignored", "ignored", "invalid", "invalid", "w" * 100),
        consent=Consent(False, "ignored"),
    )
    second = complete_assessment(changed_retry, "a-different-identity")

    assert second == replace(first, created=False)
    assert counts() == {
        "leads": 1,
        "lead_consents": 1,
        "assessments": 1,
        "roi_estimates": 1,
        "analytics_events": 2,
    }


def test_write_failure_rolls_back_every_completion_row(completion_db, monkeypatch):
    real_insert = analytics_repository.insert_server_event

    def fail_second_event(db, event_name, assessment_id, *, created_at=None):
        if event_name == "lead_submitted":
            raise sqlite3.OperationalError("forced analytics failure")
        return real_insert(
            db, event_name, assessment_id, created_at=created_at
        )

    monkeypatch.setattr(
        analytics_repository, "insert_server_event", fail_second_event
    )

    with pytest.raises(sqlite3.OperationalError, match="forced analytics failure"):
        complete_assessment(valid_completion(), "ip")

    assert counts() == {
        "leads": 0,
        "lead_consents": 0,
        "assessments": 0,
        "roi_estimates": 0,
        "analytics_events": 0,
    }


def test_write_failure_rolls_back_existing_lead_refresh(completion_db, monkeypatch):
    first = complete_assessment(valid_completion(), "ip")
    original = rows("SELECT * FROM leads WHERE id=?", (first.lead_id,))[0]
    real_insert = analytics_repository.insert_server_event

    def fail_second_event(db, event_name, assessment_id, *, created_at=None):
        if event_name == "lead_submitted":
            raise sqlite3.OperationalError("forced analytics failure")
        return real_insert(
            db, event_name, assessment_id, created_at=created_at
        )

    monkeypatch.setattr(
        analytics_repository, "insert_server_event", fail_second_event
    )
    changed = replace(
        valid_completion(UUID_2),
        contact=Contact(
            "must-roll-back",
            "must-roll-back",
            "13800138000",
            "rollback@example.invalid",
            "must-roll-back",
        ),
    )

    with pytest.raises(sqlite3.OperationalError):
        complete_assessment(changed, "ip")

    current = rows("SELECT * FROM leads WHERE id=?", (first.lead_id,))[0]
    assert current["company_name"] == original["company_name"]
    assert current["contact_name"] == original["contact_name"]
    assert current["email"] == original["email"]
    assert current["wechat"] == original["wechat"]
    assert counts() == {
        "leads": 1,
        "lead_consents": 1,
        "assessments": 1,
        "roi_estimates": 1,
        "analytics_events": 2,
    }


def test_completion_event_repository_rejects_non_allowlisted_events(completion_db):
    db = models.get_db()
    try:
        with pytest.raises(ValidationError):
            analytics_repository.insert_server_event(db, "contact-pii-event", 1)
        assert db.execute("SELECT COUNT(*) FROM analytics_events").fetchone()[0] == 0
    finally:
        db.close()


def test_false_consent_and_invalid_calculation_make_no_writes(completion_db):
    no_consent = replace(
        valid_completion(), consent=Consent(False, "2026-08-19")
    )
    bad_answers = dict(valid_completion(UUID_2).profile.answers)
    bad_answers["business_value_frequency"] = "request-secret-option"
    invalid_profile = replace(
        valid_completion(UUID_2),
        profile=replace(valid_completion(UUID_2).profile, answers=bad_answers),
    )

    with pytest.raises(ValidationError):
        complete_assessment(no_consent, "ip")
    with pytest.raises(ValidationError) as error:
        complete_assessment(invalid_profile, "ip")

    assert "request-secret-option" not in str(error.value)
    assert counts() == {
        "leads": 0,
        "lead_consents": 0,
        "assessments": 0,
        "roi_estimates": 0,
        "analytics_events": 0,
    }


@pytest.mark.parametrize(
    "contact",
    (
        Contact("企业", "联系人", "1380013800", "", ""),
        Contact("企业", "联系人", "13800138000", f"secret@{'x' * 250}.cn", ""),
        Contact("企业", "联系人", "13800138000", "", "w" * 65),
    ),
)
def test_invalid_contact_is_rejected_without_leaking_values(
    completion_db, caplog, contact
):
    request = replace(valid_completion(), contact=contact)

    with pytest.raises(ValidationError) as error:
        complete_assessment(request, "identity-hash")

    exception_text = str(error.value)
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    for value in (contact.phone, contact.email, contact.wechat):
        if value:
            assert value not in exception_text
            assert value not in log_text
    assert counts()["leads"] == 0


def test_not_progressing_lead_reopens_and_active_status_is_preserved(completion_db):
    first = complete_assessment(valid_completion(), "ip")
    db = models.get_db()
    try:
        db.execute(
            "UPDATE leads SET status='not_progressing',"
            "retention_expires_at='2020-01-01 00:00:00' WHERE id=?",
            (first.lead_id,),
        )
        db.commit()
    finally:
        db.close()

    reopened = complete_assessment(valid_completion(UUID_2), "ip")
    lead = rows("SELECT * FROM leads WHERE id=?", (reopened.lead_id,))[0]
    history = rows(
        "SELECT previous_status,new_status FROM lead_status_history WHERE lead_id=?",
        (reopened.lead_id,),
    )
    assert lead["status"] == "pending_contact"
    assert [(row["previous_status"], row["new_status"]) for row in history] == [
        ("not_progressing", "pending_contact")
    ]
    assert datetime.fromisoformat(lead["retention_expires_at"]) - datetime.fromisoformat(
        lead["updated_at"]
    ) == timedelta(days=365)

    db = models.get_db()
    try:
        db.execute("UPDATE leads SET status='contacted' WHERE id=?", (first.lead_id,))
        db.commit()
    finally:
        db.close()
    complete_assessment(valid_completion(UUID_3), "ip")
    assert rows("SELECT status FROM leads WHERE id=?", (first.lead_id,))[0][0] == "contacted"


def test_won_lead_stays_won_without_retention_or_ordinary_queue_entry(completion_db):
    first = complete_assessment(valid_completion(), "ip")
    db = models.get_db()
    try:
        db.execute(
            "UPDATE leads SET status='won',retention_expires_at=NULL WHERE id=?",
            (first.lead_id,),
        )
        db.commit()
    finally:
        db.close()

    second = complete_assessment(valid_completion(UUID_2), "ip")
    lead = rows("SELECT * FROM leads WHERE id=?", (second.lead_id,))[0]
    db = models.get_db()
    try:
        ordinary_ids = [row["id"] for row in lead_repository.list_ordinary_queue(db)]
    finally:
        db.close()

    assert second.lead_id == first.lead_id
    assert second.assessment_id != first.assessment_id
    assert lead["status"] == "won"
    assert lead["retention_expires_at"] is None
    assert lead["id"] not in ordinary_ids


def _all_keys(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield key
            yield from _all_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _all_keys(nested)
